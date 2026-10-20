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
from bench.truth import check_consistency, load_truth, summarize
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
    assert len(truth.facts) == 120
    assert len(truth.contradictions) == 21
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
    assert tier_counts == {"executed": 27, "code": 41, "documented": 52}


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
