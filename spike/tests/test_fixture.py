"""Tests against the REAL spike fixture (not tests/fixtures/mini/).

Marked ``fixture`` (registered in pyproject.toml) so it can be deselected
with ``-m "not fixture"``, but it runs by default like everything else.
Every test skips outright if ``truth/facts.yaml`` doesn't exist yet — the
real fixture is authored separately from this harness and may not be
complete, or present at all, when this suite runs.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bench.build import build
from bench.truth import Carrier, _check_run_carrier, check_consistency, load_truth, summarize
from tests._support import SPIKE_ROOT

pytestmark = pytest.mark.fixture

FACTS_PATH = SPIKE_ROOT / "truth" / "facts.yaml"
COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _skip_if_no_real_fixture() -> None:
    if not FACTS_PATH.is_file():
        pytest.skip(f"real fixture not present yet: no {FACTS_PATH}")


def test_check_consistency_reports_no_problems():
    _skip_if_no_real_fixture()
    problems = check_consistency(SPIKE_ROOT)
    assert problems == [], summarize(problems)


def test_truth_counts():
    _skip_if_no_real_fixture()
    truth = load_truth(SPIKE_ROOT / "truth")
    # 125 and 22 since asbuilt#37: five rider-portal facts and one fake-vs-real pair at c7.
    assert len(truth.facts) == 125
    assert len(truth.contradictions) == 22
    assert len(truth.stale) == 10

    pull_only = [
        f
        for f in truth.facts.values()
        if len(f.carriers) == 1 and f.carriers[0].document.startswith("pull/")
    ]
    assert len(pull_only) == 5

    tier_counts: dict[str, int] = {}
    for fact in truth.facts.values():
        tier_counts[fact.tier] = tier_counts.get(fact.tier, 0) + 1
    # asbuilt#37: three executed portal facts (real, mocked, real), one demoted
    # to code by the real run, one code fact about the portal's server.
    assert tier_counts == {"executed": 30, "code": 43, "documented": 52}

    fidelity_counts: dict[str, int] = {}
    for fact in truth.facts.values():
        if fact.tier == "executed":
            fidelity_counts[fact.fidelity] = fidelity_counts.get(fact.fidelity, 0) + 1
    assert fidelity_counts == {"in-process": 27, "real": 2, "mocked": 1}
    assert truth.fidelities is not None
    assert truth.fidelities.ranked == ("real", "in-process", "fake", "mocked")
    assert truth.fidelities.real_backend == "in-process"


def test_playwright_run_carriers_resolve_by_project_and_title_path():
    """Each Playwright run carrier resolves in its own project only: the same
    title path in a project where the test failed or was skipped does not."""
    _skip_if_no_real_fixture()
    truth = load_truth(SPIKE_ROOT / "truth")
    carriers = [
        (fact.id, c)
        for fact in truth.facts.values()
        for c in fact.carriers
        if c.document.startswith("run/playwright-")
    ]
    assert len(carriers) == 7
    for fid, carrier in carriers:
        assert _check_run_carrier(carrier, SPIKE_ROOT) is None, (fid, carrier)
        assert truth.fidelities.of_carrier(carrier) == carrier.project

    real_fail = Carrier(
        document="run/playwright-c7",
        project="real",
        location="fare preview › shows the price-sheet cap for a 200-minute casual ride",
    )
    assert "no passed playwright test in 'real'" in _check_run_carrier(real_fail, SPIKE_ROOT)
    no_project = Carrier(document="run/playwright-c7", location=real_fail.location)
    assert "no project None" in _check_run_carrier(no_project, SPIKE_ROOT)


def test_every_run_has_commit_and_step_metadata():
    _skip_if_no_real_fixture()
    runs_dir = SPIKE_ROOT / "runs"
    report_paths = sorted(runs_dir.glob("*.json"))
    assert report_paths, f"no run reports under {runs_dir}"

    for report_path in report_paths:
        data = json.loads(report_path.read_text())
        metadata = data.get("metadata", {})
        commit = metadata.get("commit")
        assert commit and COMMIT_SHA_RE.fullmatch(commit), report_path
        assert metadata.get("step"), report_path


def test_build_reproduces_the_shas_recorded_in_runs(tmp_path: Path):
    """Builds the real fixture into a tmp dir and checks every step's SHA
    matches what's recorded in runs/*.json's metadata — proof both that the
    build is reproducible and that the committed runs came from this
    system/, not some other build of it."""
    _skip_if_no_real_fixture()
    commits = build(SPIKE_ROOT, tmp_path / "out")

    expected_by_step: dict[str, set[str]] = {}
    for report_path in (SPIKE_ROOT / "runs").glob("*.json"):
        metadata = json.loads(report_path.read_text()).get("metadata", {})
        step, commit = metadata.get("step"), metadata.get("commit")
        if step and commit:
            expected_by_step.setdefault(step, set()).add(commit)

    assert expected_by_step
    for step, shas in expected_by_step.items():
        assert len(shas) == 1, f"{step}: conflicting SHAs recorded across runs/*.json: {shas}"
        assert commits[step]["sha"] == next(iter(shas)), step


def test_validate_rejects_a_run_cited_where_the_test_does_not_assert_the_fact(tmp_path: Path):
    """asbuilt#35 item 7: an executed fact's runs are the steps where its
    test passes AND asserts it. F-007's test passes c1..c6 but carries the
    member assertion only from c5, so citing run/pytest-c4 is rejected; the
    fixture as committed passes."""
    _skip_if_no_real_fixture()
    for rel in ("truth", "system/history/steps.yaml", "queries/mix.yaml"):
        src, dest = SPIKE_ROOT / rel, tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy(src, dest)
    validate = [sys.executable, str(tmp_path / "truth" / "validate.py")]
    ok = subprocess.run(validate, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    facts = tmp_path / "truth" / "facts.yaml"
    run_c5 = (
        "  - document: run/pytest-c5\n"
        "    location: tests/unit/test_pricing.py::test_ebike_surcharge_when_flag_on\n"
    )
    text = facts.read_text()
    assert text.count(run_c5) == 1
    facts.write_text(text.replace(run_c5, run_c5.replace("c5", "c4") + run_c5))
    bad = subprocess.run(validate, capture_output=True, text=True)
    assert bad.returncode == 1
    assert (
        "F-007: runs of tests/unit/test_pricing.py::test_ebike_surcharge_when_flag_on at "
        "['c4', 'c5', 'c6'], but it passes and asserts the fact within the validity at "
        "['c5', 'c6']"
    ) in bad.stdout
