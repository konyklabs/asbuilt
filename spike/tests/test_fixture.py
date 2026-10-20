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
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from bench.build import build
from bench.run import load_mix, run
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
    # asbuilt#37: three executed portal facts (real, mocked, real), one code
    # fact about the portal's server, and one demoted by the real run to
    # documented (only the fake carried it in code).
    assert tier_counts == {"executed": 30, "code": 42, "documented": 53}

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
        "['c4', 'c5', 'c6', 'c7'], but it passes and asserts the fact within the validity at "
        "['c5', 'c6', 'c7']"
    ) in bad.stdout


def test_a_run_by_default_is_d013s_registered_benchmark_and_asks_the_c6_queries(tmp_path: Path):
    """c7 (asbuilt#37) moved neither default: a run that names no step ingests
    through c6 and asks only the queries valid at c6, the 62 every 2026-10-20
    results file asked; --incremental ingests c5 then c6; c7 only on request."""
    _skip_if_no_real_fixture()
    mix = load_mix(SPIKE_ROOT / "queries" / "mix.yaml")
    before_c7 = [q["id"] for q in mix["queries"] if "valid_from" not in q]
    assert len(before_c7) == 62

    full = run(SPIKE_ROOT, "null", ingest_root=tmp_path / "full", repeats=0)
    assert full["through_step"] == "c6"
    assert [q["id"] for q in full["queries"]] == before_c7

    incremental = run(SPIKE_ROOT, "null", ingest_root=tmp_path / "inc", repeats=0, incremental=True)
    steps = incremental["ingest_incremental"]
    assert (steps["through_step_1"], steps["through_step_2"]) == ("c5", "c6")
    assert [q["id"] for q in incremental["queries"]] == before_c7

    at_c7 = run(SPIKE_ROOT, "null", through_step="c7", ingest_root=tmp_path / "c7", repeats=0)
    assert at_c7["through_step"] == "c7"
    assert [q["id"] for q in at_c7["queries"]] == [q["id"] for q in mix["queries"]]
    assert len(at_c7["queries"]) == 67


def _validate(tmp_path: Path, mutate: Callable[[Path], None]) -> tuple[int, str]:
    """truth/validate.py run on a copy of the real truth, query mix and steps,
    after `mutate` edits the copy."""
    root = tmp_path / "spike"
    shutil.copytree(SPIKE_ROOT / "truth", root / "truth")
    shutil.copytree(SPIKE_ROOT / "queries", root / "queries")
    (root / "system" / "history").mkdir(parents=True)
    shutil.copy(SPIKE_ROOT / "system" / "history" / "steps.yaml", root / "system" / "history")
    mutate(root)
    done = subprocess.run(
        [sys.executable, str(root / "truth" / "validate.py")], capture_output=True, text=True
    )
    return done.returncode, done.stdout


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new))


def test_validate_passes_on_the_real_truth(tmp_path: Path):
    _skip_if_no_real_fixture()
    code, out = _validate(tmp_path, lambda root: None)
    assert code == 0, out


def test_a_demotion_never_rests_on_a_test_double(tmp_path: Path):
    """F-123 back at code tier, carried by the fake's constant (the shape the
    lens round refused): a test double is not Gearwell's code, so the fact
    stands on its documents."""
    _skip_if_no_real_fixture()

    def back_to_code(root: Path) -> None:
        facts = root / "truth" / "facts.yaml"
        _replace(
            facts,
            "  tier: documented\n  valid_from: c7\n  demoted_by:",
            "  tier: code\n  valid_from: c7\n  demoted_by:",
        )
        _replace(
            facts,
            "  - document: wiki/fares-overview\n    location: '#cap'\n    version: 5\n"
            "  - document: doc/fares-price-sheet\n    location: '#caps-and-fees'\n"
            "    version: 1Qm4Vr12\n  - document: code/web/tests/fare-preview.spec.ts",
            "  - document: code/web/fake_farebox.py\n    location: SINGLE_RIDE_CAP_CENTS\n"
            "    version: c7\n  - document: code/web/tests/fare-preview.spec.ts",
        )
        plan_path = root / "truth" / "PLAN.yaml"
        plan = yaml.safe_load(plan_path.read_text())
        for page in (*plan["wiki"], *plan["docs"]):
            for anchor in page.get("anchors", []):
                anchor["facts"] = [f for f in anchor["facts"] if f["id"] != "F-123"]
        fake = next(c for c in plan["code"] if c["path"] == "web/fake_farebox.py")
        cap = next(s for s in fake["symbols"] if s["name"] == "SINGLE_RIDE_CAP_CENTS")
        cap["facts"] = [{"fact": "F-123", "steps": ["c7"]}]
        plan_path.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))

    code, out = _validate(tmp_path, back_to_code)
    assert code == 1
    assert "F-123: carried at code by a test double alone" in out
    assert "F-123: demoted, so it stands on its non-run evidence at documented, not code" in out


def test_a_pass_below_a_failure_at_a_higher_fidelity_never_stays_executed(tmp_path: Path):
    """An unplanted Playwright test that passes at mocked and fake and fails at
    real, its fact left executed at fake: D-014 demotes it, planted or not."""
    _skip_if_no_real_fixture()
    title = "fare preview › shows a fare"

    def unplanted(root: Path) -> None:
        with (root / "truth" / "facts.yaml").open("a") as facts:
            facts.write(
                "- id: F-126\n"
                "  statement: The fare preview page shows a fare once Preview fare is pressed.\n"
                "  category: technical-implementation\n"
                "  entities: [E-web-rider-portal, E-page-fare-preview]\n"
                "  tier: executed\n  fidelity: fake\n  valid_from: c7\n  carriers:\n"
                "  - document: code/web/public/portal.js\n    location: formatCents\n"
                "    version: c7\n"
                f"  - document: code/web/tests/fare-preview.spec.ts\n    location: {title}\n"
                "    version: c7\n"
                f"  - document: run/playwright-c7\n    project: mocked\n    location: {title}\n"
                f"  - document: run/playwright-c7\n    project: fake\n    location: {title}\n"
            )
        with (root / "truth" / "executed-audit.md").open("a") as audit:
            audit.write(f"| F-126 | `{title}` | a | a preview shows a fare | - | c7 |\n")
        plan_path = root / "truth" / "PLAN.yaml"
        plan = yaml.safe_load(plan_path.read_text())
        portal = next(c for c in plan["code"] if c["path"] == "web/public/portal.js")
        portal["symbols"].append(
            {"name": "formatCents", "facts": [{"fact": "F-126", "steps": ["c7"]}]}
        )
        plan["tests"].append(
            {
                "document": "code/web/tests/fare-preview.spec.ts",
                "id": title,
                "framework": "playwright",
                "asserts": [{"fact": "F-126", "steps": ["c7"]}],
                "outcomes": {"c7": {"mocked": "passed", "fake": "passed", "real": "failed"}},
            }
        )
        run = next(r for r in plan["runs"] if r["id"] == "run/playwright-c7")
        run["projects"]["mocked"]["passes"].append(title)
        run["projects"]["fake"]["passes"].append(title)
        run["projects"]["real"]["failed"].append(title)
        plan_path.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))

    code, out = _validate(tmp_path, unplanted)
    errors = [line for line in out.splitlines() if line.startswith("  - ")]
    assert code == 1, out
    assert errors == [
        f"  - F-126: {title} fails at c7 at a higher fidelity than it passes "
        "(run/playwright-c7 real), so the fact needs that run as demoted_by and a "
        "fake-vs-real contradiction",
        "  - audit: covers 33 facts; missing [], extra []; expected 32",  # the 33rd is F-126
    ]


def _demoted_by_real_on_portal_code(tier: str) -> Callable[[Path], None]:
    """A planted-style fact carried by the portal's own code, passing at
    mocked and failing at real, demoted by the real run, at `tier`; the
    fake-vs-real pair it needs is X-023 against F-124."""
    title = "fare preview › shows a fare"

    def mutate(root: Path) -> None:
        with (root / "truth" / "facts.yaml").open("a") as facts:
            facts.write(
                "- id: F-126\n"
                "  statement: The fare preview page shows a fare once Preview fare is pressed.\n"
                "  category: technical-implementation\n"
                "  entities: [E-web-rider-portal, E-page-fare-preview]\n"
                f"  tier: {tier}\n  valid_from: c7\n  demoted_by:\n"
                f"    document: run/playwright-c7\n    project: real\n    location: {title}\n"
                "  carriers:\n"
                "  - document: code/web/public/portal.js\n    location: formatCents\n"
                "    version: c7\n"
                f"  - document: code/web/tests/fare-preview.spec.ts\n    location: {title}\n"
                "    version: c7\n"
                f"  - document: run/playwright-c7\n    project: mocked\n    location: {title}\n"
            )
        with (root / "truth" / "contradictions.yaml").open("a") as contradictions:
            contradictions.write(
                "- id: X-023\n  facts: [F-126, F-124]\n  kind: fake-vs-real\n"
                "  winner: F-124\n  label: refutes\n  opened_by: c7\n"
            )
        with (root / "truth" / "executed-audit.md").open("a") as audit:
            audit.write(f"| F-126 | `{title}` | a | a preview shows a fare | - | c7 |\n")
        plan_path = root / "truth" / "PLAN.yaml"
        plan = yaml.safe_load(plan_path.read_text())
        portal = next(c for c in plan["code"] if c["path"] == "web/public/portal.js")
        portal["symbols"].append(
            {"name": "formatCents", "facts": [{"fact": "F-126", "steps": ["c7"]}]}
        )
        plan["tests"].append(
            {
                "document": "code/web/tests/fare-preview.spec.ts",
                "id": title,
                "framework": "playwright",
                "asserts": [{"fact": "F-126", "steps": ["c7"]}],
                "outcomes": {"c7": {"mocked": "passed", "fake": "skipped", "real": "failed"}},
            }
        )
        run = next(r for r in plan["runs"] if r["id"] == "run/playwright-c7")
        run["projects"]["mocked"]["passes"].append(title)
        run["projects"]["fake"]["skipped"].append(title)
        run["projects"]["real"]["failed"].append(title)
        plan_path.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))

    return mutate


# The added fact and pair move two exact counts; nothing else may fail.
_COUNT_ERRORS = [
    "  - audit: covers 33 facts; missing [], extra []; expected 32",
    "  - contradictions: 23, expected exactly 22",
]


def test_a_demotion_carried_by_system_code_stands_at_code(tmp_path: Path):
    """D-014 below the real backend, demoted, carried by the portal's own
    script: it stands at code, above where its mocked pass ranked it."""
    _skip_if_no_real_fixture()
    code, out = _validate(tmp_path / "code", _demoted_by_real_on_portal_code("code"))
    assert [line for line in out.splitlines() if line.startswith("  - ")] == _COUNT_ERRORS, out

    code, out = _validate(tmp_path / "doc", _demoted_by_real_on_portal_code("documented"))
    errors = [line for line in out.splitlines() if line.startswith("  - ")]
    assert "  - F-126: demoted, so it stands on its non-run evidence at code, not documented" in (
        errors
    )
