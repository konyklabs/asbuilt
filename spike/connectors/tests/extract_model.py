"""The model extractor: one structured-output call per skeleton, through
`bench.llm.CountingClient`, with a provider adapter that imports the
``anthropic`` SDK lazily (never at module import time — ``uv sync`` without
the optional ``model`` dependency group, and every test in this repo, must
work without it installed). Bedrock is meant to follow through the same
``client_factory`` shape once a provider is chosen; not built in this slice.

**No real call is made anywhere in this module's own tests, nor by the CLI
in this slice** — ``spike/connectors/tests/__main__.py --model-dry-run``
is the only mode exercised, per the driving issue: no key is used until
Oleg names the paying account. ``dry_run`` builds every prompt exactly as
``extract_with_model`` would, estimates tokens as ``len(text) // 4``, and
prices them from ``PRICE_TABLE`` — stated and labelled here, not fetched,
so it is visibly a stated assumption rather than a silently-current price.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from connectors.tests.collect import Skeleton
from connectors.tests.extract_rules import Rule

# $ per million tokens. Stated assumption, 2026-09-28, Claude pricing as
# publicly listed; re-check before any real spend.
PRICE_TABLE: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_creation": 3.75, "cache_read": 0.30},
}
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_OUTPUT_TOKENS_PER_CALL = 200  # a structured-output Fact is short

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "statement": {"type": "string"},
        "category": {
            "type": "string",
            "enum": ["business-logic", "technical-implementation", "operations", "history"],
        },
        "entities": {"type": "array", "items": {"type": "string"}},
        "claim": {
            "type": ["object", "null"],
            "properties": {
                "entity": {"type": "string"},
                "attribute": {"type": "string"},
                "value": {},
                "unit": {"type": ["string", "null"]},
            },
        },
    },
    "required": ["statement", "category", "entities"],
}


def build_prompt(skeleton: Skeleton, rule: Rule | None) -> str:
    """The prompt: the test's own source-derived facts (never more than the
    assertion proves) plus the rules extractor's own guess, for the model
    to confirm, correct or refine — it is never asked to invent beyond
    what's given."""
    lines = [
        "Say exactly what this test's assertion proves, in one sentence, present tense.",
        f"Test: {skeleton.node_id}",
        f"Docstring: {skeleton.docstring or '(none)'}",
        f"Markers: {', '.join(skeleton.markers) or '(none)'}",
        "Asserts:",
    ]
    lines.extend(f"  {a.source}" for a in skeleton.asserts)
    if rule is not None:
        lines.append(
            f"Rules-extractor guess: {rule.statement!r} category={rule.category} "
            f"entities={rule.entities} claim={rule.claim}"
        )
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


@dataclass(frozen=True)
class DryRunResult:
    prompts: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    model: str
    price_per_million: dict[str, float]
    estimated_dollars: float


def dry_run(
    skeletons: list[Skeleton],
    rules: dict[str, Rule],
    *,
    model: str = DEFAULT_MODEL,
    output_tokens_per_call: int = DEFAULT_OUTPUT_TOKENS_PER_CALL,
) -> DryRunResult:
    if model not in PRICE_TABLE:
        raise ValueError(f"no price table entry for {model!r}; add one to PRICE_TABLE")
    prices = PRICE_TABLE[model]

    total_input = sum(_estimate_tokens(build_prompt(s, rules.get(s.node_id))) for s in skeletons)
    total_output = len(skeletons) * output_tokens_per_call
    dollars = (total_input * prices["input"] + total_output * prices["output"]) / 1_000_000

    return DryRunResult(
        prompts=len(skeletons),
        estimated_input_tokens=total_input,
        estimated_output_tokens=total_output,
        model=model,
        price_per_million=prices,
        estimated_dollars=dollars,
    )


class ClientFactory(Protocol):
    def __call__(self) -> Any: ...


def load_anthropic_client(api_key: str | None = None) -> Any:
    """Lazily imports the `anthropic` SDK (the `model` optional dependency
    group) — never at module import time."""
    import anthropic  # noqa: PLC0415 - deliberately lazy, see module docstring

    return anthropic.Anthropic(api_key=api_key)


def _extract_tool_input(response: Any) -> dict[str, Any] | None:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            return getattr(block, "input", None)
    return None


def extract_with_model(
    skeletons: list[Skeleton],
    rules: dict[str, Rule],
    *,
    client_factory: ClientFactory = load_anthropic_client,
    arm: str = "stack-b-model",
    model: str = DEFAULT_MODEL,
    budget: Any = None,
    stop_dir: Any = None,
) -> tuple[list[dict[str, Any]], Any]:
    """Makes one real structured-output call per skeleton, through a
    `CountingClient`. Not called by `__main__.py` in this slice (dry-run
    only) and never given a real client in this package's own tests — a
    fake `client_factory` proves the wiring without spending anything (see
    `tests/test_connector_model.py`). `stop_dir` passes through to
    `CountingClient` (default: its own `build/`) so a test exercising the
    budget stop condition can point it at a `tmp_path` instead."""
    from bench.llm import CountingClient

    kwargs: dict[str, Any] = {}
    if stop_dir is not None:
        kwargs["stop_dir"] = stop_dir
    wrapped = CountingClient(
        client=client_factory(),
        arm=arm,
        model=model,
        budget=budget,
        prices=PRICE_TABLE.get(model),
        **kwargs,
    )

    results = []
    for skeleton in skeletons:
        prompt = build_prompt(skeleton, rules.get(skeleton.node_id))
        response = wrapped.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"name": "record_fact", "input_schema": SCHEMA}],
            tool_choice={"type": "tool", "name": "record_fact"},
        )
        payload = _extract_tool_input(response)
        if payload is not None:
            results.append({"node_id": skeleton.node_id, **payload})
    return results, wrapped
