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
home; vitest reports have no such key) is rewritten to ``"."``, and, since
asbuilt#37, every other occurrence of the built repository's absolute path in
any string of any report (pytest's crash ``path`` and ``longrepr``, Vitest's
``testResults[].name``) becomes ``"."`` too, so the evidence file carries no
local path. The c1 to c6 reports were written before that and keep theirs.

Planted-outcome tolerance and reruns (D-013 #7; ``truth/planted-runs.yaml``'s
own ``runner`` section is the contract this follows): every step's pytest
suite runs once with ``GEARWELL_ATTEMPT=1``, writing ``pytest-<step>.json``.
If that attempt has any failed/errored test, exactly those node ids are
re-invoked with ``GEARWELL_ATTEMPT=2``, writing ``pytest-<step>-rerun.json``
(document id ``run/pytest-<step>-rerun``) — this is *data-driven*: it is not
looked up in ``planted-runs.yaml`` first, it happens whenever attempt 1
actually failed something, whether planted or not, mirroring the real
contract (``truth/planted-runs.yaml``'s P-1, a genuinely still-failing test,
reruns exactly like P-3, a flaky one — the *rerun trigger* is "attempt 1
failed", the *tolerance* is a separate check against the file). Vitest has
no per-test re-invocation here (unlike pytest, selecting a specific failed
vitest test by name across files is a name-pattern match, not a plain
argument list); if its attempt 1 has any failure, the whole suite reruns
with ``GEARWELL_ATTEMPT=2`` — untested against a real planted case, since
the current planted set names three pytest tests and no vitest one.

Whether a step's outcome is "unexpected" (and so makes this script exit
non-zero) is read from ``truth/planted-runs.yaml`` if the truth author has
written it: top-level ``planted``, a list of entries with a ``test`` (a
pytest node id, or a vitest ``ancestorTitles + [title]`` joined with
``" > "``), an ``outcomes`` map (step id -> the outcome attempt 1 is
expected to report) and, when a rerun is expected, a ``reruns`` map (step id
-> the outcome attempt 2 is expected to report — P-1's genuinely-broken test
stays ``"failed"`` there; P-3's flaky one becomes ``"passed"``). A reported
outcome that matches its entry's table (attempt 1 against ``outcomes``,
attempt 2 against ``reruns``) is expected; a failed/errored test with no
matching entry is unexpected; anything else (passed, or a skip, matching or
not) is left alone. Without ``planted-runs.yaml``, any failure is
unexpected and reruns still happen (the trigger doesn't need the file).

Stale-bytecode guard: the same ``repo`` checkout is reused across every
``git checkout`` call, and git does not remove untracked files on checkout,
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

Playwright (asbuilt#37): if ``web/playwright.config.ts`` exists at a step,
``npm ci --silent`` in ``web/`` (once per run of this script) and then ``npx
playwright test --reporter=list,json,junit`` there, once: the config's three
projects (``mocked``, ``fake``, ``real``) each start their own backend through
``webServer``, with ``retries: 0``, and nothing is rerun, since a planted
Playwright failure is a fidelity outcome, not a flaky one. The subprocess gets
``GEARWELL_COMMIT=<sha>`` (the config's ``metadata.commit`` and every
project's ``metadata.backend``), ``GEARWELL_PYTHON`` (this interpreter, for
``web/serve.py``) and ``FORCE_COLOR=0``; the JSON and JUnit reports are
written under fresh bare filenames in ``web/`` (the report-path guard
below), and the run is refused, non-zero, with the committed reports left as
they are, when a reporter wrote nothing or the run did not complete
(``_incomplete_playwright_reports``); only then are they moved to
``runs/playwright-<step>.json`` and ``runs/playwright-<step>.xml``.
Both are scrubbed of local paths like every report (below), and an absolute
path in ``config.argv`` (the node binary) becomes its file name; what that
reaches in a Playwright report is the config's ``rootDir`` and
``configFile``, each project's ``testDir``/``outputDir``/``snapshotDir``, an
attachment's ``path`` and a failure's message and stack. The JSON then gets
the same top-level ``metadata: {commit, step}`` the other reports carry. Its
outcomes are checked per project against
``planted-runs.yaml``'s entries with ``runner: playwright``, whose
``outcomes`` map a step to ``{project: outcome}``: exactly those are
expected, a planted outcome the run did not report is unexpected, and any
other test that neither passed nor was skipped is unexpected.

CLI: ``uv run python bench/runs.py [--fixture .] [--out build] [--steps c1,c2]``.
Exits non-zero only on an unexpected failure (see above). ``--fixture``/
``--out`` are additions for testability and default so the documented
invocation is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))

import yaml  # noqa: E402

from bench.truth import playwright_outcomes  # noqa: E402


class RunsError(RuntimeError):
    pass


def load_commits(out_root: Path) -> dict[str, dict[str, str]]:
    commits_path = out_root / "commits.json"
    if not commits_path.is_file():
        raise RunsError(f"no commits.json at {commits_path}; run bench/build.py first")
    return json.loads(commits_path.read_text())


def load_planted_runs(fixture_root: Path) -> dict | None:
    """truth/planted-runs.yaml if present, else None. See the module
    docstring's tolerance section for the shape read here (`planted`, a list
    of {test, outcomes, reruns})."""
    path = fixture_root / "truth" / "planted-runs.yaml"
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text()) or {}


def _planted_entry(planted: dict | None, test_id: str) -> dict | None:
    if not planted:
        return None
    for entry in planted.get("planted", []):
        if entry.get("test") == test_id and entry.get("runner") != "playwright":
            return entry
    return None


def _expected_outcome(
    planted: dict | None, test_id: str, step_id: str, *, attempt: int
) -> str | None:
    entry = _planted_entry(planted, test_id)
    if entry is None:
        return None
    table = entry.get("reruns", {}) if attempt == 2 else entry.get("outcomes", {})
    return table.get(step_id)


def _unexpected_pytest_outcomes(
    report_path: Path, step_id: str, planted: dict | None, *, attempt: int
) -> list[str]:
    if not report_path.is_file():
        return ["<no report written>"]
    data = json.loads(report_path.read_text())
    unexpected: list[str] = []
    # exitcode 0 = all passed, 1 = some test failed — both are per-test
    # outcomes a planted entry can explain; 2-5 (interrupted, internal
    # error, usage error, no tests collected) are never tolerable.
    exitcode = data.get("exitcode")
    if exitcode not in (0, 1):
        unexpected.append(f"<pytest exitcode {exitcode}>")
    for t in data.get("tests", []):
        outcome = t.get("outcome")
        nodeid = t.get("nodeid")
        expected = _expected_outcome(planted, nodeid, step_id, attempt=attempt)
        if expected is not None:
            if outcome != expected:
                unexpected.append(f"{nodeid} (expected {expected!r}, got {outcome!r})")
            continue
        if outcome in ("failed", "error"):
            unexpected.append(nodeid)
    return unexpected


def _unexpected_vitest_outcomes(
    report_path: Path, step_id: str, planted: dict | None, *, attempt: int
) -> list[str]:
    if not report_path.is_file():
        return ["<no report written>"]
    data = json.loads(report_path.read_text())
    unexpected: list[str] = []
    if not data.get("testResults") and data.get("success") is False:
        unexpected.append("<vitest run failed with no testResults>")
    for suite in data.get("testResults", []):
        for assertion in suite.get("assertionResults", []):
            full_name = " > ".join(
                [*assertion.get("ancestorTitles", []), assertion.get("title", "")]
            )
            outcome = assertion.get("status")
            expected = _expected_outcome(planted, full_name, step_id, attempt=attempt)
            if expected is not None:
                if outcome != expected:
                    unexpected.append(f"{full_name} (expected {expected!r}, got {outcome!r})")
                continue
            if outcome == "failed":
                unexpected.append(full_name)
    return unexpected


def _unexpected_playwright_outcomes(
    report_path: Path, step_id: str, planted: dict | None
) -> list[str]:
    if not report_path.is_file():
        return ["<no report written>"]
    data = json.loads(report_path.read_text())
    unexpected = [
        f"<playwright error: {error.get('message', '').splitlines()[0][:120]}>"
        for error in data.get("errors", [])
    ]
    expected: dict[tuple[str, str], str] = {}
    for entry in (planted or {}).get("planted", []):
        if entry.get("runner") == "playwright":
            for project, outcome in (entry.get("outcomes") or {}).get(step_id, {}).items():
                expected[(entry.get("test"), project)] = outcome
    reported: set[tuple[str, str]] = set()
    for project, title_path, status in playwright_outcomes(data):
        key = (title_path, project)
        reported.add(key)
        want = expected.get(key)
        if want is not None:
            if status != want:
                unexpected.append(f"[{project}] {title_path} (expected {want!r}, got {status!r})")
        elif status not in ("passed", "skipped"):
            unexpected.append(f"[{project}] {title_path} ({status})")
    for title_path, project in sorted(expected.keys() - reported):
        unexpected.append(f"[{project}] {title_path} (expected {expected[title_path, project]!r})")
    return unexpected


def _scrub(value: Any, prefixes: list[str]) -> Any:
    if isinstance(value, str):
        for prefix in prefixes:
            value = value.replace(prefix, ".")
        return value
    if isinstance(value, list):
        return [_scrub(v, prefixes) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v, prefixes) for k, v in value.items()}
    return value


def _local_prefixes(repo: Path) -> list[str]:
    """The repository's absolute path as the reports may spell it (macOS
    gives /private/var for /var), longest first."""
    return sorted({str(repo), str(repo.resolve())}, key=len, reverse=True)


def _scrub_json_report(report_path: Path, repo: Path) -> None:
    """Every occurrence of the repository's absolute path, in any string of
    the report, becomes "."; an absolute path in a Playwright report's
    `config.argv` (the node binary) becomes its file name."""
    if not report_path.is_file():
        return
    data = _scrub(json.loads(report_path.read_text()), _local_prefixes(repo))
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    if isinstance(config.get("argv"), list):
        config["argv"] = [Path(a).name if Path(a).is_absolute() else a for a in config["argv"]]
    report_path.write_text(json.dumps(data, indent=2) + "\n")


def _scrub_xml_report(report_path: Path, repo: Path) -> None:
    if not report_path.is_file():
        return
    text = report_path.read_text()
    for prefix in _local_prefixes(repo):
        text = text.replace(prefix, ".")
    report_path.write_text(text)


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


def _step_env(step_id: str, *, attempt: int = 1) -> dict[str, str]:
    env = dict(os.environ)
    env["GEARWELL_STEP"] = step_id
    env["GEARWELL_ATTEMPT"] = str(attempt)
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


def _run_pytest_once(
    repo: Path, step_id: str, *, attempt: int, nodeids: list[str] | None = None
) -> Path:
    suffix = "-rerun" if attempt == 2 else ""
    temp_name = f".bench-runs-report-pytest-{step_id}{suffix}.json"
    temp_report = repo / temp_name
    temp_report.unlink(missing_ok=True)
    cmd = [
        "uv",
        "run",
        "--quiet",
        "--with",
        "pytest",
        "--with",
        "pytest-json-report",
        "pytest",
        "-q",
    ]
    if nodeids:
        cmd.extend(nodeids)
    cmd.extend(["--json-report", "--json-report-file", temp_name])
    subprocess.run(cmd, cwd=repo, env=_step_env(step_id, attempt=attempt))
    return temp_report


def _run_pytest(repo: Path, runs_dir: Path, step_id: str, sha: str, planted: dict | None) -> bool:
    if not (repo / "tests").is_dir():
        print(f"[{step_id}] no tests/ directory yet, skipping pytest")
        return True

    temp_report = _run_pytest_once(repo, step_id, attempt=1)
    report_path = runs_dir / f"pytest-{step_id}.json"
    _collect_report(temp_report, report_path)
    _scrub_json_report(report_path, repo)
    _inject_metadata(report_path, sha, step_id)
    unexpected = _unexpected_pytest_outcomes(report_path, step_id, planted, attempt=1)

    attempt_1_data = json.loads(report_path.read_text()) if report_path.is_file() else {}
    failed_nodeids = [
        t["nodeid"]
        for t in attempt_1_data.get("tests", [])
        if t.get("outcome") in ("failed", "error")
    ]

    if failed_nodeids:
        temp_rerun = _run_pytest_once(repo, step_id, attempt=2, nodeids=failed_nodeids)
        rerun_path = runs_dir / f"pytest-{step_id}-rerun.json"
        _collect_report(temp_rerun, rerun_path)
        _scrub_json_report(rerun_path, repo)
        _inject_metadata(rerun_path, sha, step_id)
        unexpected += _unexpected_pytest_outcomes(rerun_path, step_id, planted, attempt=2)

    if unexpected:
        print(f"[{step_id}] pytest: unexpected failure(s): {sorted(set(unexpected))}")
        return False
    print(f"[{step_id}] pytest: no unexpected failures")
    return True


def _run_vitest_once(dispatch_dir: Path, step_id: str, *, attempt: int) -> Path:
    suffix = "-rerun" if attempt == 2 else ""
    temp_name = f".bench-runs-report-vitest-{step_id}{suffix}.json"
    temp_report = dispatch_dir / temp_name
    temp_report.unlink(missing_ok=True)
    subprocess.run(
        ["npx", "vitest", "run", "--reporter=json", f"--outputFile={temp_name}"],
        cwd=dispatch_dir,
        env=_step_env(step_id, attempt=attempt),
    )
    return temp_report


def _run_vitest(
    repo: Path,
    runs_dir: Path,
    step_id: str,
    sha: str,
    npm_installed: set[Path],
    planted: dict | None,
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

    temp_report = _run_vitest_once(dispatch_dir, step_id, attempt=1)
    report_path = runs_dir / f"vitest-{step_id}.json"
    _collect_report(temp_report, report_path)
    _scrub_json_report(report_path, repo)
    # Vitest has no metadata hook of its own; always fill it in ourselves.
    _inject_metadata(report_path, sha, step_id)
    unexpected = _unexpected_vitest_outcomes(report_path, step_id, planted, attempt=1)

    attempt_1_data = json.loads(report_path.read_text()) if report_path.is_file() else {}
    any_failed = any(
        assertion.get("status") == "failed"
        for suite in attempt_1_data.get("testResults", [])
        for assertion in suite.get("assertionResults", [])
    )

    if any_failed:
        # No per-test selection for vitest here — see the module docstring.
        temp_rerun = _run_vitest_once(dispatch_dir, step_id, attempt=2)
        rerun_path = runs_dir / f"vitest-{step_id}-rerun.json"
        _collect_report(temp_rerun, rerun_path)
        _scrub_json_report(rerun_path, repo)
        _inject_metadata(rerun_path, sha, step_id)
        unexpected += _unexpected_vitest_outcomes(rerun_path, step_id, planted, attempt=2)

    if unexpected:
        print(f"[{step_id}] vitest: unexpected failure(s): {sorted(set(unexpected))}")
        return False
    print(f"[{step_id}] vitest: no unexpected failures")
    return True


def _incomplete_playwright_reports(returncode: int, json_path: Path, xml_path: Path) -> list[str]:
    """Why a Playwright run's fresh reports may not replace the committed
    ones: a reporter wrote nothing, or the run did not complete (an exit
    other than 0 or 1, a run-level error such as a backend that never
    started, an interrupted test, no test run at all, a report that does not
    parse). Empty means both reports are whole."""
    reasons = []
    if returncode not in (0, 1):
        reasons.append(f"playwright exited {returncode}")
    if not json_path.is_file():
        reasons.append("no JSON report written")
    else:
        try:
            data = json.loads(json_path.read_text())
        except json.JSONDecodeError as exc:
            data = {}
            reasons.append(f"JSON report does not parse ({exc})")
        stats = data.get("stats") or {}
        ran = sum(stats.get(k, 0) for k in ("expected", "unexpected", "flaky", "skipped"))
        if "suites" not in data or not ran:
            reasons.append("JSON report shows no completed test")
        reasons.extend(
            f"run error: {error.get('message', '').splitlines()[0][:120]}"
            for error in data.get("errors", [])
        )
        if any(status == "interrupted" for _, _, status in playwright_outcomes(data)):
            reasons.append("a test was interrupted")
    if not xml_path.is_file():
        reasons.append("no JUnit report written")
    else:
        try:
            if ElementTree.parse(xml_path).getroot().tag != "testsuites":
                reasons.append("JUnit report has no <testsuites> root")
        except ElementTree.ParseError as exc:
            reasons.append(f"JUnit report does not parse ({exc})")
    return reasons


def _run_playwright(
    repo: Path,
    runs_dir: Path,
    step_id: str,
    sha: str,
    npm_installed: set[Path],
    planted: dict | None,
) -> bool:
    web_dir = repo / "web"
    if not (web_dir / "playwright.config.ts").is_file():
        return True

    if web_dir not in npm_installed:
        install = subprocess.run(["npm", "ci", "--silent"], cwd=web_dir)
        if install.returncode != 0:
            print(f"[{step_id}] npm ci in web/ failed (exit {install.returncode})")
            return False
        npm_installed.add(web_dir)

    temp_json = web_dir / f".bench-runs-report-playwright-{step_id}.json"
    temp_xml = web_dir / f".bench-runs-report-playwright-{step_id}.xml"
    for temp in (temp_json, temp_xml):
        temp.unlink(missing_ok=True)
    env = _step_env(step_id)
    env.update(
        {
            "GEARWELL_COMMIT": sha,
            "GEARWELL_PYTHON": sys.executable,
            "PLAYWRIGHT_JSON_OUTPUT_NAME": temp_json.name,
            "PLAYWRIGHT_JUNIT_OUTPUT_NAME": temp_xml.name,
            "FORCE_COLOR": "0",
        }
    )
    done = subprocess.run(
        ["npx", "playwright", "test", "--reporter=list,json,junit"], cwd=web_dir, env=env
    )
    refused = _incomplete_playwright_reports(done.returncode, temp_json, temp_xml)
    if refused:
        for temp in (temp_json, temp_xml):
            temp.unlink(missing_ok=True)
        print(f"[{step_id}] playwright: refused, the committed reports are kept: {refused}")
        return False
    _scrub_json_report(temp_json, repo)
    _scrub_xml_report(temp_xml, repo)
    _inject_metadata(temp_json, sha, step_id)
    json_path = runs_dir / f"playwright-{step_id}.json"
    xml_path = runs_dir / f"playwright-{step_id}.xml"
    _collect_report(temp_json, json_path)
    _collect_report(temp_xml, xml_path)

    unexpected = _unexpected_playwright_outcomes(json_path, step_id, planted)
    if unexpected:
        print(f"[{step_id}] playwright: unexpected outcome(s): {sorted(set(unexpected))}")
        return False
    print(f"[{step_id}] playwright: no unexpected outcomes")
    return True


def run_all(fixture_root: Path, out_root: Path, steps: list[str] | None = None) -> bool:
    commits = load_commits(out_root)
    repo = out_root / "repo"
    runs_dir = fixture_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    planted = load_planted_runs(fixture_root)

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

        if not _run_pytest(repo, runs_dir, step_id, sha, planted):
            ok = False
        if not _run_vitest(repo, runs_dir, step_id, sha, npm_installed, planted):
            ok = False
        if not _run_playwright(repo, runs_dir, step_id, sha, npm_installed, planted):
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
