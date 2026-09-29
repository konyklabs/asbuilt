"""Dynamic evidence: outcomes per test id per commit, from four run-report
formats. This harness's own ``runs/`` only ever writes pytest-json-report
and Vitest JSON (``read_runs_directory`` dispatches between the two by
shape); the reportlog and JUnit XML readers exist for a CI-sourced corpus
(D-013's sequence note: "run evidence accepted from CI as JUnit XML without
changing the suite under test"), each exercised in
``spike/tests/test_connector_tests.py`` against a hand-written, labelled
sample of its format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class Outcome:
    node_id: str
    outcome: str  # "passed" | "failed" | "skipped" | "error" | ...
    step: str | None
    commit: str | None
    attempt: int
    run_id: str | None  # e.g. "pytest-c5", for citation as run/<run_id>


def read_pytest_json_report(path: Path, *, attempt: int = 1) -> list[Outcome]:
    data = json.loads(path.read_text())
    metadata = data.get("metadata") or {}
    run_id = path.stem  # "pytest-c5" or "pytest-c5-rerun"
    return [
        Outcome(
            node_id=t["nodeid"],
            outcome=t["outcome"],
            step=metadata.get("step"),
            commit=metadata.get("commit"),
            attempt=attempt,
            run_id=run_id,
        )
        for t in data.get("tests", [])
    ]


def read_pytest_reportlog(
    path: Path, *, attempt: int = 1, step: str | None = None, commit: str | None = None
) -> list[Outcome]:
    """pytest-reportlog's JSON-lines format: one JSON object per line, each
    a ``$report_type`` event. Only ``TestReport`` events matter; ``when ==
    "call"`` is the test body's own outcome, preferred, but a skip usually
    only shows on ``when == "setup"``, kept when no "call" entry exists for
    the same node id. Reportlog carries no step/commit of its own — the
    caller supplies them (from the invocation that produced the file, e.g.
    a CI job's own commit SHA), documented here since there is no
    convention for it in the format itself."""
    outcomes: dict[str, str] = {}
    run_id = path.stem
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event.get("$report_type") != "TestReport":
            continue
        nodeid, when, outcome = event.get("nodeid"), event.get("when"), event.get("outcome")
        if nodeid is None or outcome is None:
            continue
        if when == "call":
            outcomes[nodeid] = outcome
        elif when == "setup" and outcome == "skipped" and nodeid not in outcomes:
            outcomes[nodeid] = "skipped"
    return [
        Outcome(node_id=nid, outcome=oc, step=step, commit=commit, attempt=attempt, run_id=run_id)
        for nid, oc in outcomes.items()
    ]


_JUNIT_OUTCOME_TAGS = {"failure": "failed", "error": "error", "skipped": "skipped"}


def read_junit_xml(path: Path, *, attempt: int = 1) -> list[Outcome]:
    """Pytest's own ``--junitxml`` shape (a ``<testsuites>`` root with
    nested ``<testsuite>``/``<testcase>``) and the generic bare
    ``<testsuite>`` root both parse the same way: a ``<testcase>``'s own
    child element (``<failure>``/``<error>``/``<skipped>``) names its
    outcome, none present means passed. The commit: a
    ``<property name="commit" value="...">`` under ``<properties>`` if
    present (pytest's ``record_testsuite_property`` fixture can write this),
    else a sidecar ``<path>.commit.txt`` file holding just the SHA — this
    reader's own convention, documented here since JUnit XML has no
    standard place for a commit at all."""
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))

    commit = None
    for props in root.iter("properties"):
        for prop in props.findall("property"):
            if prop.get("name") == "commit":
                commit = prop.get("value")
    if commit is None:
        sidecar = path.with_suffix(path.suffix + ".commit.txt")
        if sidecar.is_file():
            commit = sidecar.read_text().strip()

    run_id = path.stem
    outcomes = []
    for suite in suites:
        for testcase in suite.findall("testcase"):
            classname, name = testcase.get("classname", ""), testcase.get("name", "")
            node_id = f"{classname}::{name}" if classname else name
            outcome = "passed"
            for tag, mapped in _JUNIT_OUTCOME_TAGS.items():
                if testcase.find(tag) is not None:
                    outcome = mapped
                    break
            outcomes.append(
                Outcome(
                    node_id=node_id,
                    outcome=outcome,
                    step=None,
                    commit=commit,
                    attempt=attempt,
                    run_id=run_id,
                )
            )
    return outcomes


def read_vitest_json(path: Path, *, attempt: int = 1) -> list[Outcome]:
    """``fullName`` reconstructed from ``ancestorTitles + [title]``,
    ``" > "``-joined — the same convention ``bench/truth.py`` uses, never
    the raw ``fullName`` field (its own separator isn't guaranteed)."""
    data = json.loads(path.read_text())
    metadata = data.get("metadata") or {}
    run_id = path.stem
    outcomes = []
    for suite in data.get("testResults", []):
        for assertion in suite.get("assertionResults", []):
            full_name = " > ".join(
                [*assertion.get("ancestorTitles", []), assertion.get("title", "")]
            )
            outcomes.append(
                Outcome(
                    node_id=full_name,
                    outcome=assertion.get("status"),
                    step=metadata.get("step"),
                    commit=metadata.get("commit"),
                    attempt=attempt,
                    run_id=run_id,
                )
            )
    return outcomes


def read_runs_directory(runs_dir: Path) -> list[Outcome]:
    """Reads every ``runs/*.json``, dispatching pytest-json-report vs
    Vitest JSON by shape (``tests`` key vs ``testResults`` key — the same
    discriminator ``bench/truth.py``'s ``check_consistency`` uses). Attempt
    number is 2 for a ``*-rerun.json`` file, else 1."""
    outcomes: list[Outcome] = []
    for path in sorted(runs_dir.glob("*.json")):
        data = json.loads(path.read_text())
        attempt = 2 if path.stem.endswith("-rerun") else 1
        if "tests" in data:
            outcomes.extend(read_pytest_json_report(path, attempt=attempt))
        elif "testResults" in data:
            outcomes.extend(read_vitest_json(path, attempt=attempt))
    return outcomes
