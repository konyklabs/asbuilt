"""The test connector's CLI.

``uv run python -m connectors.tests --fixture . --step c6 --extractor rules
[--model-dry-run] [--all-steps] [--out build/connector]`` writes
``build/connector/tests-<step>.json``: a list of Facts in the protocol's
JSON shape (statement, category, entities as names, tier, citations —
``code/tests/...::node`` at the step's SHA always, plus ``run/<id>`` when
executed — ``valid_from`` the step, claim), plus ``contradiction_candidates``,
``flaky``, ``skipped`` node ids, and ``counts``. ``--all-steps`` does every
history step (c1..c6). Builds the fixture first (``bench.build.build``, the
same idempotent, fast — under a second — step every other CLI in this
harness already does) so ``git diff`` has a real repository to compare
against for the tier rule (``lift.py``).

``--model-dry-run`` additionally runs ``extract_model.dry_run`` over each
processed step's skeletons (using the rules extractor's own guesses as the
prompt's context) and prints the token/dollar totals — no call is made.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))

from bench.build import Timeline  # noqa: E402
from bench.build import build as build_repo  # noqa: E402
from connectors.tests.collect import Skeleton, collect_from_timeline  # noqa: E402
from connectors.tests.evidence import Outcome, read_runs_directory  # noqa: E402
from connectors.tests.extract_model import dry_run as model_dry_run  # noqa: E402
from connectors.tests.extract_rules import Rule, extract_all  # noqa: E402
from connectors.tests.lift import Lift, build_contradiction_payload, lift  # noqa: E402


def _source_lookup(timeline: Timeline, step: str) -> Any:
    def _lookup(path: str) -> str | None:
        content = timeline.content_at(path, step)
        return None if content is None else content.decode(errors="replace")

    return _lookup


def _load_outcomes_by_step(fixture_root: Path) -> dict[str, list[Outcome]]:
    runs_dir = fixture_root / "runs"
    if not runs_dir.is_dir():
        return {}
    by_step: dict[str, list[Outcome]] = {}
    for outcome in read_runs_directory(runs_dir):
        if outcome.step:
            by_step.setdefault(outcome.step, []).append(outcome)
    return by_step


def _fact_dict(rule: Rule, skeleton: Skeleton, lifted: Lift, step: str) -> dict[str, Any]:
    location = skeleton.node_id.split("::")[-1] if "::" in skeleton.node_id else skeleton.node_id
    citations = [{"document": f"code/{skeleton.file}", "location": location, "version": step}]
    if lifted.tier == "executed" and lifted.executed_run_id:
        citations.append(
            {"document": f"run/{lifted.executed_run_id}", "location": skeleton.node_id}
        )
    return {
        "statement": rule.statement,
        "detail": rule.detail,
        "category": rule.category,
        "entities": list(rule.entities),
        "tier": lifted.tier,
        "citations": citations,
        "valid_from": lifted.valid_from_step or step,
        "claim": rule.claim,
        "claims": list(rule.claims),
    }


def build_step_output(
    fixture_root: Path,
    step: str,
    repo: Path,
    commits: dict[str, dict[str, str]],
    outcomes_by_step: dict[str, list[Outcome]],
    step_order: list[str],
    *,
    model_dry_run_enabled: bool = False,
) -> dict[str, Any]:
    timeline = Timeline(fixture_root)
    skeletons = collect_from_timeline(timeline, step)
    rules = extract_all(skeletons, _source_lookup(timeline, step))
    rules_by_id = {r.node_id: r for r in rules}
    step_index = step_order.index(step)
    good_step = step_order[step_index - 1] if step_index > 0 else None

    facts: list[dict[str, Any]] = []
    contradiction_candidates: list[dict[str, Any]] = []
    flaky: list[str] = []
    skipped: list[str] = []

    for skeleton in skeletons:
        rule = rules_by_id.get(skeleton.node_id)
        if rule is None:
            continue
        lifted = lift(skeleton, outcomes_by_step, step_order, step, repo, commits)
        if lifted.flaky:
            flaky.append(skeleton.node_id)
        if any(m == "skip" or m.startswith("skip:") for m in skeleton.markers):
            skipped.append(skeleton.node_id)
        if lifted.contradiction_candidate and good_step is not None:
            payload = build_contradiction_payload(
                skeleton, rule, lifted.contradiction_candidate, good_step, timeline
            )
            if payload is not None:
                contradiction_candidates.append({"node_id": skeleton.node_id, **payload})
        facts.append(_fact_dict(rule, skeleton, lifted, step))

    counts = {
        "statements": len(facts),
        "executed": sum(1 for f in facts if f["tier"] == "executed"),
        "code": sum(1 for f in facts if f["tier"] == "code"),
        "candidates": len(contradiction_candidates),
        "flaky": len(flaky),
        "skipped": len(skipped),
    }

    output: dict[str, Any] = {
        "step": step,
        "sha": commits[step]["sha"],
        "facts": facts,
        "contradiction_candidates": contradiction_candidates,
        "flaky": flaky,
        "skipped": skipped,
        "counts": counts,
    }

    if model_dry_run_enabled:
        result = model_dry_run(skeletons, rules_by_id)
        output["model_dry_run"] = dataclasses.asdict(result)

    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=".", help="fixture root (default: .)")
    parser.add_argument("--step", default=None, help="a single step id (default: the last step)")
    parser.add_argument("--all-steps", action="store_true", help="process every history step")
    parser.add_argument(
        "--extractor", default="rules", choices=["rules"], help="only 'rules' this slice"
    )
    parser.add_argument(
        "--model-dry-run",
        action="store_true",
        help="also print model-extractor token/dollar estimates",
    )
    parser.add_argument("--out", default="build/connector", help="output directory")
    args = parser.parse_args(argv)

    fixture_root = Path(args.fixture).resolve()
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    build_out = Path.cwd() / "build"
    commits = build_repo(fixture_root, build_out)
    repo = build_out / "repo"
    step_order = list(commits)

    outcomes_by_step = _load_outcomes_by_step(fixture_root)
    steps = step_order if args.all_steps else [args.step or step_order[-1]]

    for step in steps:
        if step not in commits:
            raise SystemExit(f"unknown step {step!r}; known steps are {step_order}")
        output = build_step_output(
            fixture_root,
            step,
            repo,
            commits,
            outcomes_by_step,
            step_order,
            model_dry_run_enabled=args.model_dry_run,
        )
        out_path = out_dir / f"tests-{step}.json"
        out_path.write_text(json.dumps(output, indent=2) + "\n")

        c = output["counts"]
        line = (
            f"{step}: statements={c['statements']} executed={c['executed']} code={c['code']} "
            f"candidates={c['candidates']} flaky={c['flaky']} skipped={c['skipped']}"
        )
        print(line)
        if args.model_dry_run:
            d = output["model_dry_run"]
            print(
                f"  model-dry-run: prompts={d['prompts']} "
                f"input_tokens~{d['estimated_input_tokens']} "
                f"output_tokens~{d['estimated_output_tokens']} "
                f"model={d['model']} dollars~${d['estimated_dollars']:.4f}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
