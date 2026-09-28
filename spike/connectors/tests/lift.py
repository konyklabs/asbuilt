"""D-013's provenance-tier rule, for the test connector: at commit c, a
skeleton is ``executed`` when a passing run exists at some ``c' <= c`` and
neither the test file nor the source files it exercises (approximated from
its imports) changed between ``c'`` and ``c`` (``git diff --name-only
c'..c`` in the built repository); otherwise it is ``code`` if the skeleton
exists at all. A failing run *at c* demotes to ``code`` and opens a
contradiction candidate (the statement, the failing run's id, and the code
citation). Skipped and xfail never lift on their own, but do not erase an
earlier still-valid executed proof either. A commit where attempt 1 fails
and attempt 2 (the rerun) passes neither lifts nor demotes at that commit —
marked ``flaky`` — falling back to the nearest earlier still-valid proof, if
any (D-013 is silent on flaky handling; this fixture's own reading, stated
in ``truth/planted-runs.yaml``'s ``rules``, is followed here: "neither lifts
nor demotes... the fact keeps the tier its latest conclusive step gives
it"). ``truth/planted-runs.yaml`` is read only by this package's own tests,
to assert against the expected outcomes there — never by this module at
runtime, which has no dependency on ``truth/`` at all.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from connectors.tests.collect import Skeleton
from connectors.tests.evidence import Outcome
from connectors.tests.extract_rules import Rule, build_constant_claim, find_python_constant

_PYTHON_SKIP_IMPORTS = {"__future__", "pytest", "decimal", "datetime", "typing", "dataclasses"}
_TS_SKIP_IMPORTS = {"vitest"}


@dataclass(frozen=True)
class ContradictionCandidate:
    statement_step: str
    failing_run_id: str | None
    code_citation: str


@dataclass(frozen=True)
class Lift:
    tier: str  # "executed" | "code"
    valid_from_step: str | None
    executed_run_id: str | None
    contradiction_candidate: ContradictionCandidate | None
    flaky: bool


def exercised_paths(skeleton: Skeleton) -> set[str]:
    """The test file itself, plus source files it likely exercises,
    approximated from its own module-level imports — a Python
    ``farebox.pricing`` import becomes ``farebox/pricing.py``; a TypeScript
    relative import becomes a path resolved against the test file's own
    directory. An approximation, not a real dependency graph — the same
    kind of best-effort signal `extract_rules.py`'s heuristics already are."""
    paths = {skeleton.file}
    if skeleton.language == "python":
        for imp in skeleton.imports:
            if imp in _PYTHON_SKIP_IMPORTS:
                continue
            paths.add(imp.replace(".", "/") + ".py")
    else:
        test_dir = Path(skeleton.file).parent
        for imp in skeleton.imports:
            if imp in _TS_SKIP_IMPORTS or not imp.startswith("."):
                continue
            resolved = (test_dir / imp).as_posix()
            if resolved.endswith(".js"):
                resolved = resolved[: -len(".js")] + ".ts"
            paths.add(resolved)
    return paths


def _changed_paths(repo: Path, from_sha: str, to_sha: str) -> set[str]:
    if from_sha == to_sha:
        return set()
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{from_sha}..{to_sha}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _attempts_at(
    outcomes_by_step: dict[str, list[Outcome]], step: str, node_id: str
) -> dict[int, Outcome]:
    return {o.attempt: o for o in outcomes_by_step.get(step, []) if o.node_id == node_id}


def lift(
    skeleton: Skeleton,
    outcomes_by_step: dict[str, list[Outcome]],
    step_order: list[str],
    target_step: str,
    repo: Path,
    commits: dict[str, dict[str, str]],
) -> Lift:
    target_index = step_order.index(target_step)

    attempts = _attempts_at(outcomes_by_step, target_step, skeleton.node_id)
    outcomes_seen = {a.outcome for a in attempts.values()}
    flaky = len(attempts) >= 2 and "passed" in outcomes_seen and "failed" in outcomes_seen

    if flaky:
        # An inconclusive (flaky) step is never itself compared against —
        # not even for staleness — it simply carries forward whatever tier
        # its nearest earlier step already established (the fixture's own
        # stated reading of D-013's silence, in truth/planted-runs.yaml's
        # `rules`: "the fact keeps the tier its latest conclusive step gives
        # it"). At the first step this can only be "code": there is no
        # earlier step to inherit from.
        if target_index == 0:
            return Lift(
                tier="code",
                valid_from_step=None,
                executed_run_id=None,
                contradiction_candidate=None,
                flaky=True,
            )
        earlier = lift(
            skeleton, outcomes_by_step, step_order, step_order[target_index - 1], repo, commits
        )
        return Lift(
            tier=earlier.tier,
            valid_from_step=earlier.valid_from_step,
            executed_run_id=earlier.executed_run_id,
            contradiction_candidate=earlier.contradiction_candidate,
            flaky=True,
        )

    if attempts:
        latest_attempt = attempts[max(attempts)]
        if latest_attempt.outcome == "failed":
            candidate = ContradictionCandidate(
                statement_step=target_step,
                failing_run_id=latest_attempt.run_id,
                code_citation=f"code/{skeleton.file}",
            )
            return Lift(
                tier="code",
                valid_from_step=None,
                executed_run_id=None,
                contradiction_candidate=candidate,
                flaky=False,
            )
        # skipped/xfail/error fall through to the backward search below,
        # same as "no run at all" — none of them lift on their own.

    exercised = exercised_paths(skeleton)
    target_sha = commits[target_step]["sha"]
    for idx in range(target_index, -1, -1):
        step = step_order[idx]
        step_attempts = _attempts_at(outcomes_by_step, step, skeleton.node_id)
        passing = next((a for a in step_attempts.values() if a.outcome == "passed"), None)
        if passing is None:
            continue
        candidate_sha = commits[step]["sha"]
        changed = _changed_paths(repo, candidate_sha, target_sha) if step != target_step else set()
        if changed & exercised:
            break  # the nearest pass no longer covers target_step's code; no valid proof
        return Lift(
            tier="executed",
            valid_from_step=step,
            executed_run_id=passing.run_id,
            contradiction_candidate=None,
            flaky=False,
        )

    return Lift(
        tier="code",
        valid_from_step=None,
        executed_run_id=None,
        contradiction_candidate=None,
        flaky=False,
    )


# ------------------------------------------------- contradiction candidates
#
# asbuilt#8 integration review, point 6: the candidate the scorer reads is
# not the lightweight `ContradictionCandidate` above (that only carries
# enough to demote a fact and cite the failing run) but a full {a, b,
# winner, reason} shape matching how `bench.score.score_contradictions`
# matches a returned pair against a `truth/contradictions.yaml` `run-vs-code`
# entry: `a` and `b` are each a complete Fact dict, matched the same way any
# returned fact is (shared entity, shared cited document, statement text).
#
# The demoted test itself often never names the constant that changed (a
# behavioural test like `test_lost_bike_fee_150` proves the fee through the
# invoice total, never by importing `LOST_BIKE_FEE` — see extract_rules.py's
# module docstring point 2), so `b`'s constant is found independently here:
# among the demoted skeleton's own exercised, non-test Python source files,
# the one ALL_CAPS module-level assignment whose text differs between the
# nearest earlier step and the failing step. This is a deterministic,
# source-derived proxy for "what the code changed to" — not a claim the
# demoted test itself makes — and is skipped (no payload) when zero or more
# than one such constant changed, rather than guess.

_ALL_CAPS_ASSIGN_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.+?)\s*(?:#.*)?$", re.MULTILINE)


def _module_constant_texts(source: str) -> dict[str, str]:
    return dict(_ALL_CAPS_ASSIGN_RE.findall(source))


_NAME_SEGMENT_RE = re.compile(r"[^a-z0-9]+")


def _name_overlap(name: str, test_name: str) -> int:
    """Word-segment overlap between a constant's own name and the demoted
    test's name — the tie-breaker `find_changed_constant` uses when a
    changed file touched more than one constant at once (real case: c4->c5
    changes BOTH `LOST_BIKE_FEE` and `SINGLE_RIDE_CAP` in the same file,
    one commit demoting `test_lost_bike_fee_100`, LOST_BIKE_FEE sharing
    "lost"/"bike"/"fee" with the test's own name and SINGLE_RIDE_CAP
    sharing nothing)."""
    name_segments = set(_NAME_SEGMENT_RE.split(name.lower()))
    test_segments = set(_NAME_SEGMENT_RE.split(test_name.lower()))
    return len(name_segments & test_segments)


def find_changed_constant(
    skeleton: Skeleton, good_step: str, failing_step: str, timeline: Any
) -> tuple[str, str, Any, bool] | None:
    """(name, source path, value, is_decimal) for the ALL_CAPS constant
    whose own assignment text changed between `good_step` and
    `failing_step` in one of `skeleton`'s exercised, non-test Python source
    files. When a file changed more than one constant in that span, the one
    whose name shares the most word segments with the demoted test's own
    name wins, provided it strictly beats the runner-up (see
    `_name_overlap`) — never a guess among an unbroken tie. None if no
    source file changed any constant, or a tie couldn't be broken."""
    if skeleton.language != "python":
        return None
    for path in exercised_paths(skeleton):
        if path == skeleton.file or not path.endswith(".py"):
            continue
        old_bytes = timeline.content_at(path, good_step)
        new_bytes = timeline.content_at(path, failing_step)
        if old_bytes is None or new_bytes is None:
            continue
        old_text, new_text = old_bytes.decode(), new_bytes.decode()
        old_map, new_map = _module_constant_texts(old_text), _module_constant_texts(new_text)
        changed = [name for name, value in new_map.items() if old_map.get(name) != value]
        if not changed:
            continue
        if len(changed) > 1:
            ranked = sorted(changed, key=lambda n: _name_overlap(n, skeleton.name), reverse=True)
            if _name_overlap(ranked[0], skeleton.name) <= _name_overlap(ranked[1], skeleton.name):
                continue
            changed = ranked[:1]
        found = find_python_constant(new_text, changed[0])
        if found is None:
            continue
        value, is_decimal = found
        return changed[0], path, value, is_decimal
    return None


def _humanize_constant_name(name: str) -> str:
    text = name.replace("_", " ").strip().lower()
    return text[0].upper() + text[1:] if text else text


def _claim_display(claim: dict[str, Any]) -> str:
    value = claim["value"]
    return f"{value} {claim['unit']}" if claim["unit"] and claim["unit"] != "usd" else str(value)


def build_contradiction_payload(
    skeleton: Skeleton,
    rule: Rule,
    candidate: ContradictionCandidate,
    good_step: str,
    timeline: Any,
) -> dict[str, Any] | None:
    """The full `{a, b, winner, reason}` shape for `candidate`, or None when
    no single changed constant could be found (see `find_changed_constant`).
    `winner` is the same dict object as `b` — the demotion's whole point is
    that the code's current value beats the once-passing test's stale one."""
    found = find_changed_constant(skeleton, good_step, candidate.statement_step, timeline)
    if found is None:
        return None
    name, path, value, is_decimal = found
    claim, document = build_constant_claim(name, value, is_decimal, path)
    service = path.split("/")[0]

    location = skeleton.node_id.split("::")[-1] if "::" in skeleton.node_id else skeleton.node_id
    a = {
        "statement": rule.statement,
        "detail": rule.detail,
        "category": rule.category,
        "entities": list(rule.entities),
        "tier": "code",
        "citations": [
            {
                "document": f"code/{skeleton.file}",
                "location": location,
                "version": candidate.statement_step,
            },
            {"document": f"run/{candidate.failing_run_id}", "location": skeleton.node_id},
        ],
        "claim": rule.claim,
    }
    b = {
        "statement": f"{_humanize_constant_name(name)} is {_claim_display(claim)}.",
        "detail": "",
        "category": rule.category,
        "entities": [service, name],
        "tier": "code",
        "citations": [
            {"document": f"code/{document}", "location": name, "version": candidate.statement_step}
        ],
        "claim": claim,
    }
    return {"a": a, "b": b, "winner": b, "reason": f"failing run {candidate.failing_run_id}"}
