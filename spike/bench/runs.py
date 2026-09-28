"""Runs the invented system's test suites at every history step.

For each step (in ``<out>/commits.json``, written by ``bench/build.py``):
``git checkout <sha>`` in ``<out>/repo/``, then run the Python suite with
``uv run --with pytest --with pytest-json-report pytest -q --json-report
--json-report-file <fixture>/runs/pytest-<step>.json`` from the repo root
(skipped, with a message, if the repo has no ``tests/`` directory at that
step), and, if ``dispatch/package.json`` exists at that step, ``npm ci
--silent`` (once per run of this script) followed by ``npx vitest run
--reporter=json --outputFile <fixture>/runs/vitest-<step>.json`` inside
``dispatch/``.

Both subprocesses run with ``GEARWELL_STEP=<step id>`` set, so the fixture's
own conftest can record it (and the commit) itself via pytest's
``pytest_json_modifyreport`` hook. After each pytest run, if the JSON's
``metadata.commit`` is still absent, null or empty, this script fills
``metadata: {commit: <sha>, step: <id>}`` itself — a no-op when the fixture's
conftest already populated it. Vitest has no equivalent hook, so its JSON
gets the same treatment unconditionally. Either report's top-level ``root``
(pytest-json-report writes an absolute path under the authoring machine's
home; vitest reports have no such key) is rewritten to ``"."``, so the
evidence file carries no local path.

Stale-bytecode guard: the same ``repo`` checkout is reused across all six
``git checkout`` calls, and git does not remove untracked files on checkout,
so a ``__pycache__/*.pyc`` written by one step's pytest run can survive into
the next. Python's timestamp-based cache invalidation normally catches a
changed source file, but two checkouts close enough in wall-clock time can
give a file the same on-disk mtime as its predecessor, in which case a stale
``.pyc`` is silently reused and a step reports the *previous* step's test
results (confirmed by reproduction: konyklabs/roadmap#153 thread,
2026-09-28). Guarded twice: every subprocess gets
``PYTHONDONTWRITEBYTECODE=1`` (nothing is ever cached), and any
``__pycache__`` directory already present in ``repo`` is removed right after
each checkout (covering caches written before this env var was set, e.g. a
manual run against the same checkout).

Report-path guard: ``--json-report-file``/``--outputFile`` are always given a
bare filename with no directory component, written inside the subprocess's
own working directory, then moved (in this script, not the subprocess) to
its real location under ``<fixture>/runs/``. ``uv run`` — invoked with
``cwd=repo``, itself a project with its own ``pyproject.toml`` —
misidentifies the project to run in and silently drops ``repo``'s own
``pythonpath`` setting whenever one of its arguments *resolves* to a path
under *this* repo's (``spike/``'s) project tree but outside ``repo`` itself
— e.g. ``<fixture>/runs/pytest-c1.json`` when ``<fixture>`` sits under
``spike/``, which it always does in real use. This is true of an absolute
path *or* a relative one written to resolve to the same place (confirmed by
reproduction both ways); only a path that never leaves ``repo`` avoids it,
which is what a bare filename guarantees. Since ``main()`` always resolves
``--fixture``/``--out`` to absolute paths, this was not a corner case — it
broke every real invocation until fixed.

Quiet subprocess output: this script itself is typically invoked via
``uv run``, which sets ``VIRTUAL_ENV`` to *this* project's (``spike/``'s)
``.venv``; inherited into the inner ``uv run`` for ``repo`` (a different,
nested project), that mismatch printed a "does not match the project
environment path" warning on every step, so ``_step_env`` drops it. The
pytest ``uv run`` also gets ``--quiet``, so a step's output is just the
pytest/vitest summary, not uv's own venv-creation and resolution chatter.

CLI: ``uv run python bench/runs.py [--fixture .] [--out build] [--steps c1,c2]``.
Exits non-zero if any run failed. ``--fixture``/``--out`` are additions for
testability and default so the documented invocation is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


class RunsError(RuntimeError):
    pass


def load_commits(out_root: Path) -> dict[str, dict[str, str]]:
    commits_path = out_root / "commits.json"
    if not commits_path.is_file():
        raise RunsError(f"no commits.json at {commits_path}; run bench/build.py first")
    return json.loads(commits_path.read_text())


def _inject_metadata(report_path: Path, sha: str, step_id: str) -> None:
    if not report_path.is_file():
        return
    data = json.loads(report_path.read_text())
    changed = False

    # Fill commit/step when absent OR present but null/empty (a fixture's
    # own conftest may have added the metadata key without populating it).
    metadata = data.setdefault("metadata", {})
    if not metadata.get("commit"):
        metadata["commit"] = sha
        metadata["step"] = step_id
        changed = True

    # pytest-json-report's top-level `root` is an absolute path under the
    # authoring machine's home directory; rewrite it so the evidence file
    # carries no local path. Vitest reports have no `root` key, so this is
    # effectively pytest-only.
    if "root" in data and data["root"] != ".":
        data["root"] = "."
        changed = True

    if changed:
        report_path.write_text(json.dumps(data, indent=2) + "\n")


def _step_env(step_id: str) -> dict[str, str]:
    env = dict(os.environ)
    env["GEARWELL_STEP"] = step_id
    # Never cache bytecode in the shared repo checkout — see the module
    # docstring's stale-bytecode guard.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # This script itself typically runs under `uv run`, which sets
    # VIRTUAL_ENV to *this* project's (spike/'s) .venv; inherited into the
    # inner `uv run` for repo (a different, nested project), that mismatch
    # prints a "does not match the project environment path" warning on
    # every step. Drop it so each inner uv run resolves repo's own venv
    # cleanly and quietly.
    env.pop("VIRTUAL_ENV", None)
    return env


def _clear_pycache(repo: Path) -> None:
    """Remove every __pycache__ directory left in `repo` by a prior step's
    run, before the next step's tests can see stale bytecode."""
    for cache_dir in repo.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)


def _collect_report(temp_report: Path, report_path: Path) -> None:
    """Move a subprocess-local report to its real location. See the module
    docstring's report-path guard: the subprocess never sees `report_path`,
    only `temp_report`'s bare filename, in its own cwd."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if temp_report.is_file():
        shutil.move(str(temp_report), str(report_path))


def _run_pytest(repo: Path, runs_dir: Path, step_id: str, sha: str) -> bool:
    if not (repo / "tests").is_dir():
        print(f"[{step_id}] no tests/ directory yet, skipping pytest")
        return True

    temp_name = f".bench-runs-report-pytest-{step_id}.json"
    temp_report = repo / temp_name
    temp_report.unlink(missing_ok=True)

    result = subprocess.run(
        [
            "uv",
            "run",
            "--quiet",
            "--with",
            "pytest",
            "--with",
            "pytest-json-report",
            "pytest",
            "-q",
            "--json-report",
            "--json-report-file",
            temp_name,
        ],
        cwd=repo,
        env=_step_env(step_id),
    )
    report_path = runs_dir / f"pytest-{step_id}.json"
    _collect_report(temp_report, report_path)
    _inject_metadata(report_path, sha, step_id)
    if result.returncode != 0:
        print(f"[{step_id}] pytest failed (exit {result.returncode})")
        return False
    return True


def _run_vitest(
    repo: Path, runs_dir: Path, step_id: str, sha: str, npm_installed: set[Path]
) -> bool:
    dispatch_dir = repo / "dispatch"
    if not (dispatch_dir / "package.json").is_file():
        return True

    if dispatch_dir not in npm_installed:
        install = subprocess.run(["npm", "ci", "--silent"], cwd=dispatch_dir)
        if install.returncode != 0:
            print(f"[{step_id}] npm ci failed (exit {install.returncode})")
            return False
        npm_installed.add(dispatch_dir)

    temp_name = f".bench-runs-report-vitest-{step_id}.json"
    temp_report = dispatch_dir / temp_name
    temp_report.unlink(missing_ok=True)

    result = subprocess.run(
        [
            "npx",
            "vitest",
            "run",
            "--reporter=json",
            f"--outputFile={temp_name}",
        ],
        cwd=dispatch_dir,
        env=_step_env(step_id),
    )
    report_path = runs_dir / f"vitest-{step_id}.json"
    _collect_report(temp_report, report_path)
    # Vitest has no metadata hook of its own; always fill it in ourselves.
    _inject_metadata(report_path, sha, step_id)
    if result.returncode != 0:
        print(f"[{step_id}] vitest failed (exit {result.returncode})")
        return False
    return True


def run_all(fixture_root: Path, out_root: Path, steps: list[str] | None = None) -> bool:
    commits = load_commits(out_root)
    repo = out_root / "repo"
    runs_dir = fixture_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    step_ids = steps if steps is not None else list(commits)
    ok = True
    npm_installed: set[Path] = set()
    for step_id in step_ids:
        if step_id not in commits:
            print(f"unknown step {step_id!r}, skipping")
            ok = False
            continue
        sha = commits[step_id]["sha"]
        subprocess.run(["git", "checkout", "--quiet", sha], cwd=repo, check=True)
        _clear_pycache(repo)

        if not _run_pytest(repo, runs_dir, step_id, sha):
            ok = False
        if not _run_vitest(repo, runs_dir, step_id, sha, npm_installed):
            ok = False

    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=".", help="fixture root (default: .)")
    parser.add_argument("--out", default="build", help="build output directory")
    parser.add_argument("--steps", default=None, help="comma-separated step ids to run")
    args = parser.parse_args(argv)

    fixture_root = Path(args.fixture).resolve()
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = Path.cwd() / out_root

    steps = args.steps.split(",") if args.steps else None
    ok = run_all(fixture_root, out_root, steps)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
