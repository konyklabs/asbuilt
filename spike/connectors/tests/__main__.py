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
prompt's context) and prints the token/dollar totals — no call is made
under either extractor.

``--extractor model`` makes one real call per skeleton through
``extract_model.extract_with_model`` instead of the deterministic rules
extractor (``--provider``: ``claude-code`` — the default, Oleg's Claude
Code subscription, never an API key — or ``anthropic``, opt-in;
``--limit N``, the smoke-test knob, caps only how many tests get a REAL
call — every OTHER test in the step still gets its rules-extractor guess,
so the written output always covers the full step). A ``--limit``ed run
with no explicit ``--out`` writes ``tests-<step>-limit<N>.json`` instead of
``tests-<step>.json``, so it can never clobber a full run's own output;
passing ``--out`` explicitly is always honoured as given.
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
from connectors.tests.extract_model import (  # noqa: E402
    DEFAULT_PROVIDER,
    PROVIDERS,
    extract_with_model,
)
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


def _fact_dict(
    rule: Rule, skeleton: Skeleton, lifted: Lift, step: str, commits: dict[str, dict[str, str]]
) -> dict[str, Any]:
    location = skeleton.node_id.split("::")[-1] if "::" in skeleton.node_id else skeleton.node_id
    sha = commits[step]["sha"]
    citations = [
        {"document": f"code/{skeleton.file}", "location": location, "version": sha, "step": step}
    ]
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


def _rule_from_model_result(result: dict[str, Any]) -> Rule:
    """Normalises one `extract_with_model` result dict into the same `Rule`
    shape the rules extractor produces, so every downstream step (tier,
    citations, `_fact_dict`) runs unchanged regardless of which extractor
    supplied the statement/category/entities/claim."""
    claim = result.get("claim")
    return Rule(
        node_id=result["node_id"],
        statement=result.get("statement", ""),
        category=result.get("category", "business-logic"),
        entities=tuple(result.get("entities") or ()),
        claim=claim,
        claims=(claim,) if claim else (),
        detail="",
    )


def build_step_output(
    fixture_root: Path,
    step: str,
    repo: Path,
    commits: dict[str, dict[str, str]],
    outcomes_by_step: dict[str, list[Outcome]],
    step_order: list[str],
    *,
    extractor: str = "rules",
    model_dry_run_enabled: bool = False,
    provider: str = DEFAULT_PROVIDER,
    limit: int | None = None,
) -> dict[str, Any]:
    timeline = Timeline(fixture_root)
    skeletons = collect_from_timeline(timeline, step)
    rules = extract_all(skeletons, _source_lookup(timeline, step))
    rules_by_id = {r.node_id: r for r in rules}

    if extractor == "model" and not model_dry_run_enabled:
        # Review fix, asbuilt#8 (hazard): `--model-dry-run` promises no call
        # under any extractor — `not model_dry_run_enabled` is what makes
        # that true for `--extractor model` too; without it, this whole
        # block (one real `claude -p`/Anthropic call per skeleton) ran
        # BEFORE the dry-run estimate was ever printed.
        #
        # `--limit N` caps only how many skeletons get a REAL call (the
        # smoke test) — everything downstream (the facts loop, counts,
        # candidates, the dry-run estimate) must still see the FULL
        # `skeletons` list, or a smoke-tested run silently overwrites the
        # full output with N facts. `model_skeletons` — never `skeletons`
        # itself — is the capped list passed to the model; a skeleton the
        # model never saw keeps its rules-extractor guess, already in
        # `rules_by_id` from `extract_all` above.
        model_skeletons = skeletons[:limit] if limit is not None else skeletons
        model_results, _wrapped = extract_with_model(
            model_skeletons, rules_by_id, client_factory=PROVIDERS[provider]
        )
        rules_by_id = {
            **rules_by_id,
            **{r["node_id"]: _rule_from_model_result(r) for r in model_results},
        }

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
        if lifted.contradiction_candidate:
            payload = build_contradiction_payload(
                skeleton, rule, lifted.contradiction_candidate, step_order, timeline, commits
            )
            if payload is not None:
                contradiction_candidates.append(
                    {
                        "node_id": skeleton.node_id,
                        "opened_step": lifted.contradiction_candidate.opened_step,
                        **payload,
                    }
                )
        facts.append(_fact_dict(rule, skeleton, lifted, step, commits))

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
        "--extractor",
        default="rules",
        choices=["rules", "model"],
        help="'rules' (deterministic, default) or 'model' (real calls — see --provider/--limit)",
    )
    parser.add_argument(
        "--model-dry-run",
        action="store_true",
        help="also print model-extractor token/dollar estimates; makes no call under any extractor",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=sorted(PROVIDERS),
        help=f"model provider for --extractor model (default: {DEFAULT_PROVIDER})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="with --extractor model, only the first N tests get a real call (the smoke test)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output directory (default: build/connector; see --limit for the filename it picks)",
    )
    args = parser.parse_args(argv)

    fixture_root = Path(args.fixture).resolve()
    out_dir = Path(args.out) if args.out is not None else Path("build/connector")
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
            extractor=args.extractor,
            model_dry_run_enabled=args.model_dry_run,
            provider=args.provider,
            limit=args.limit,
        )
        # Review fix, asbuilt#8: a `--limit`ed smoke-test run must never
        # silently overwrite the real `tests-<step>.json` a full run
        # produced — but if the caller gave an explicit `--out`, that
        # choice is respected as-is (they know what they asked for).
        if args.limit is not None and args.out is None:
            out_path = out_dir / f"tests-{step}-limit{args.limit}.json"
        else:
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
                f"  model-dry-run: provider={args.provider} prompts={d['prompts']} "
                f"input_tokens~{d['estimated_input_tokens']} "
                f"output_tokens~{d['estimated_output_tokens']} "
                f"model={d['model']} dollars~${d['estimated_dollars']:.4f} "
                "(token-based estimate; claude-code billing is subscription, not per-call)"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
