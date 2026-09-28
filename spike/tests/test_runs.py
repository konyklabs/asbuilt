from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from bench.build import build as build_repo
from bench.runs import (
    _clear_pycache,
    _unexpected_pytest_outcomes,
    _unexpected_vitest_outcomes,
    load_planted_runs,
    run_all,
)
from tests._support import MINI_ROOT, SPIKE_ROOT


def _run_import(repo: Path) -> str:
    """Runs `import mod; print(mod.VALUE)` in `repo`, with bytecode caching
    left on (the ambient PYTHONDONTWRITEBYTECODE, if any, is stripped) so a
    .pyc actually gets written — isolating this test to _clear_pycache's own
    effect, independent of bench/runs.py's other guard (the env var)."""
    env = dict(os.environ)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    result = subprocess.run(
        [sys.executable, "-c", "import mod; print(mod.VALUE)"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def test_clear_pycache_defeats_stale_bytecode_from_mtime_collision(tmp_path: Path):
    """Reproduces the failure a teammate hit running the same
    checkout-then-pytest pattern bench/runs.py uses (roadmap#153 thread,
    2026-09-28): git checkout doesn't remove untracked __pycache__ files, and
    Python's default (timestamp-based) bytecode invalidation only compares a
    source file's mtime and size against what's stored in its .pyc — so two
    writes to the same path with an identical mtime and size (forced here via
    os.utime, standing in for two checkouts close enough in wall-clock time to
    land on the same on-disk mtime) leave a stale .pyc silently reused. Proves
    both that the vulnerability is real and that _clear_pycache defeats it.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    mod_path = repo / "mod.py"

    mod_path.write_text("VALUE = 1\n")
    assert _run_import(repo) == "1"  # writes repo/__pycache__/mod...pyc

    stat_before = mod_path.stat()
    mod_path.write_text("VALUE = 2\n")  # same length -> same size as before
    os.utime(mod_path, (stat_before.st_atime, stat_before.st_mtime))  # force identical mtime

    # Without clearing the cache, Python trusts the stale .pyc: this
    # demonstrates the vulnerability bench/runs.py now guards against.
    assert _run_import(repo) == "1"

    _clear_pycache(repo)
    assert _run_import(repo) == "2"


def test_clear_pycache_is_safe_with_no_cache(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _clear_pycache(repo)  # must not raise


def test_clear_pycache_removes_nested_caches(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pkg" / "__pycache__").mkdir(parents=True)
    (repo / "pkg" / "__pycache__" / "mod.cpython-313.pyc").write_bytes(b"stale")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "top.cpython-313.pyc").write_bytes(b"stale")

    _clear_pycache(repo)

    assert not (repo / "pkg" / "__pycache__").exists()
    assert not (repo / "__pycache__").exists()


def test_run_all_with_fixture_under_spike_still_resolves_import():
    """Regression: `uv run` (cwd=repo, itself a project with its own
    pyproject.toml) misidentified which project to run in — and silently
    dropped repo's own `pythonpath` setting — whenever a `--json-report-file`
    argument *resolved* to a path under *this* repo's (spike/'s) project
    tree but outside `repo` itself, e.g. the natural
    `<fixture>/runs/pytest-c1.json` when `<fixture>` sits under spike/, true
    of that path whether given as absolute or as a relative string that
    still resolves there (confirmed both ways while diagnosing this).
    `main()` always resolves `--fixture`/`--out` to absolute paths, so
    reproducing this needs a fixture actually under spike/ (a tmp_path
    elsewhere does not trigger it) — a scratch copy under spike/build/,
    never the tracked mini fixture, so this test never touches
    tests/fixtures/mini/runs/'s real evidence files."""
    scratch_fixture = SPIKE_ROOT / "build" / "runs-regression-fixture"
    scratch_out = SPIKE_ROOT / "build" / "runs-regression-out"
    for scratch in (scratch_fixture, scratch_out):
        if scratch.exists():
            shutil.rmtree(scratch)
    shutil.copytree(MINI_ROOT, scratch_fixture)

    try:
        build_repo(scratch_fixture, scratch_out)
        ok = run_all(scratch_fixture, scratch_out, ["c1"])
        assert ok

        report = json.loads((scratch_fixture / "runs" / "pytest-c1.json").read_text())
        assert report["summary"]["passed"] == 2
        assert "ModuleNotFoundError" not in json.dumps(report)
    finally:
        shutil.rmtree(scratch_fixture, ignore_errors=True)
        shutil.rmtree(scratch_out, ignore_errors=True)


def test_load_planted_runs_missing_file_returns_none(tmp_path: Path):
    assert load_planted_runs(tmp_path) is None


def test_load_planted_runs_reads_yaml(tmp_path: Path):
    """Real schema (truth/planted-runs.yaml): a top-level `planted` list,
    each entry keyed by `test` with an `outcomes` map and (only when a
    rerun is expected) a `reruns` map."""
    (tmp_path / "truth").mkdir()
    (tmp_path / "truth" / "planted-runs.yaml").write_text(
        "planted:\n"
        "- id: P-1\n"
        "  test: tests/test_x.py::test_a\n"
        "  outcomes: {c3: failed}\n"
        "  reruns: {c3: failed}\n"
    )
    planted = load_planted_runs(tmp_path)
    assert planted["planted"][0]["test"] == "tests/test_x.py::test_a"
    assert planted["planted"][0]["outcomes"] == {"c3": "failed"}
    assert planted["planted"][0]["reruns"] == {"c3": "failed"}


def _planted(entries: list[dict]) -> dict:
    return {"planted": entries}


def test_unexpected_pytest_outcomes_tolerates_planted_failure(tmp_path: Path):
    report = tmp_path / "pytest-c3.json"
    report.write_text(
        json.dumps(
            {
                "exitcode": 1,
                "tests": [
                    {"nodeid": "tests/test_x.py::test_a", "outcome": "failed"},
                    {"nodeid": "tests/test_x.py::test_b", "outcome": "passed"},
                ],
            }
        )
    )
    planted = _planted([{"test": "tests/test_x.py::test_a", "outcomes": {"c3": "failed"}}])
    assert _unexpected_pytest_outcomes(report, "c3", planted, attempt=1) == []


def test_unexpected_pytest_outcomes_flags_mismatched_planted_outcome(tmp_path: Path):
    """A planted entry that expected `skipped` at c3 but the test actually
    failed there is unexpected, not silently tolerated."""
    report = tmp_path / "pytest-c3.json"
    report.write_text(
        json.dumps(
            {"exitcode": 1, "tests": [{"nodeid": "tests/test_x.py::test_a", "outcome": "failed"}]}
        )
    )
    planted = _planted([{"test": "tests/test_x.py::test_a", "outcomes": {"c3": "skipped"}}])
    result = _unexpected_pytest_outcomes(report, "c3", planted, attempt=1)
    assert result == ["tests/test_x.py::test_a (expected 'skipped', got 'failed')"]


def test_unexpected_pytest_outcomes_checks_reruns_table_on_attempt_2(tmp_path: Path):
    report = tmp_path / "pytest-c5-rerun.json"
    report.write_text(
        json.dumps(
            {"exitcode": 1, "tests": [{"nodeid": "tests/test_x.py::test_a", "outcome": "failed"}]}
        )
    )
    planted = _planted(
        [
            {
                "test": "tests/test_x.py::test_a",
                "outcomes": {"c5": "failed"},
                "reruns": {"c5": "failed"},
            }
        ]
    )
    assert _unexpected_pytest_outcomes(report, "c5", planted, attempt=2) == []


def test_unexpected_pytest_outcomes_flags_unplanted_failure(tmp_path: Path):
    report = tmp_path / "pytest-c3.json"
    report.write_text(
        json.dumps(
            {
                "exitcode": 1,
                "tests": [{"nodeid": "tests/test_x.py::test_surprise", "outcome": "failed"}],
            }
        )
    )
    assert _unexpected_pytest_outcomes(report, "c3", _planted([]), attempt=1) == [
        "tests/test_x.py::test_surprise"
    ]


def test_unexpected_pytest_outcomes_without_planted_file_flags_everything(tmp_path: Path):
    report = tmp_path / "pytest-c3.json"
    report.write_text(
        json.dumps(
            {"exitcode": 1, "tests": [{"nodeid": "tests/test_x.py::test_a", "outcome": "failed"}]}
        )
    )
    assert _unexpected_pytest_outcomes(report, "c3", None, attempt=1) == ["tests/test_x.py::test_a"]


def test_unexpected_pytest_outcomes_flags_bad_exitcode(tmp_path: Path):
    """exitcode 5 = no tests collected: never explainable by a planted per-test outcome."""
    report = tmp_path / "pytest-c3.json"
    report.write_text(json.dumps({"exitcode": 5, "tests": []}))
    assert _unexpected_pytest_outcomes(report, "c3", _planted([]), attempt=1) == [
        "<pytest exitcode 5>"
    ]


def test_unexpected_vitest_outcomes_tolerates_planted_flaky_rerun():
    report = {
        "testResults": [
            {
                "assertionResults": [
                    {"ancestorTitles": ["suite"], "title": "flaky test", "status": "passed"}
                ]
            }
        ]
    }
    planted = _planted(
        [{"test": "suite > flaky test", "outcomes": {"c4": "failed"}, "reruns": {"c4": "passed"}}]
    )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "vitest-c4-rerun.json"
        report_path.write_text(json.dumps(report))
        assert _unexpected_vitest_outcomes(report_path, "c4", planted, attempt=2) == []
        assert _unexpected_vitest_outcomes(report_path, "c4", _planted([]), attempt=2) == []
        report["testResults"][0]["assertionResults"][0]["status"] = "failed"
        report_path.write_text(json.dumps(report))
        assert _unexpected_vitest_outcomes(report_path, "c4", _planted([]), attempt=2) == [
            "suite > flaky test"
        ]


def _write_flaky_fixture(fixture: Path) -> None:
    """A test that fails on GEARWELL_ATTEMPT=1 and passes on attempt=2 —
    the real fixture's P-3 shape (fails once, then passes on rerun)."""
    system = fixture / "system"
    (system / "tests").mkdir(parents=True)
    (system / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (system / "conftest.py").write_text("")
    (system / "tests" / "test_flaky.py").write_text(
        "import os\n\n\ndef test_flaky():\n    assert os.environ.get('GEARWELL_ATTEMPT') == '2'\n"
    )
    (system / "history").mkdir()
    (system / "history" / "steps.yaml").write_text(
        '- id: c1\n  date: "2026-01-01T00:00:00-05:00"\n  message: "only commit"\n'
    )


def _write_always_failing_fixture(fixture: Path) -> None:
    """A test that fails on every attempt — the real fixture's P-1 shape
    (still failed on the rerun too)."""
    system = fixture / "system"
    (system / "tests").mkdir(parents=True)
    (system / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (system / "conftest.py").write_text("")
    (system / "tests" / "test_broken.py").write_text("def test_broken():\n    assert False\n")
    (system / "history").mkdir()
    (system / "history" / "steps.yaml").write_text(
        '- id: c1\n  date: "2026-01-01T00:00:00-05:00"\n  message: "only commit"\n'
    )


def test_run_all_reruns_on_any_attempt_1_failure_and_tolerates_planted_flaky(tmp_path: Path):
    """End-to-end, the real contract: the rerun trigger is attempt 1 having
    a failure (not a pre-declared 'flaky' step) — pytest-c1.json
    (GEARWELL_ATTEMPT=1, fails) and pytest-c1-rerun.json (GEARWELL_ATTEMPT=2,
    passes) both get written, and run_all() still reports success because
    planted-runs.yaml's `reruns` table says c1 is expected to pass."""
    fixture = tmp_path / "fixture"
    _write_flaky_fixture(fixture)
    (fixture / "truth").mkdir()
    (fixture / "truth" / "planted-runs.yaml").write_text(
        "planted:\n"
        "- id: P-3\n"
        "  test: tests/test_flaky.py::test_flaky\n"
        "  outcomes: {c1: failed}\n"
        "  reruns: {c1: passed}\n"
    )

    out_root = tmp_path / "out"
    build_repo(fixture, out_root)

    ok = run_all(fixture, out_root)
    assert ok

    runs_dir = fixture / "runs"
    first = json.loads((runs_dir / "pytest-c1.json").read_text())
    rerun = json.loads((runs_dir / "pytest-c1-rerun.json").read_text())
    assert first["tests"][0]["outcome"] == "failed"
    assert rerun["tests"][0]["outcome"] == "passed"
    # Attempt 2 re-invokes only the failed node id, not the whole suite.
    assert rerun["summary"]["total"] == 1


def test_run_all_tolerates_planted_still_failing_on_rerun(tmp_path: Path):
    """P-1's shape: both attempts fail, and that's still expected (the
    `reruns` table says c1 -> failed too), so run_all() reports success."""
    fixture = tmp_path / "fixture"
    _write_always_failing_fixture(fixture)
    (fixture / "truth").mkdir()
    (fixture / "truth" / "planted-runs.yaml").write_text(
        "planted:\n"
        "- id: P-1\n"
        "  test: tests/test_broken.py::test_broken\n"
        "  outcomes: {c1: failed}\n"
        "  reruns: {c1: failed}\n"
    )

    out_root = tmp_path / "out"
    build_repo(fixture, out_root)

    ok = run_all(fixture, out_root)
    assert ok
    runs_dir = fixture / "runs"
    assert (runs_dir / "pytest-c1-rerun.json").is_file()


def test_run_all_fails_on_unplanted_failure(tmp_path: Path):
    """The same always-failing test, with no planted-runs.yaml at all:
    run_all() must report failure (it still gets a rerun; that's not
    enough on its own without a matching planted-runs.yaml entry)."""
    fixture = tmp_path / "fixture"
    _write_always_failing_fixture(fixture)

    out_root = tmp_path / "out"
    build_repo(fixture, out_root)

    ok = run_all(fixture, out_root)
    assert not ok
    assert (fixture / "runs" / "pytest-c1-rerun.json").is_file()
