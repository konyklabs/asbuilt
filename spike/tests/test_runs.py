from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from bench.build import build as build_repo
from bench.runs import _clear_pycache, run_all
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
