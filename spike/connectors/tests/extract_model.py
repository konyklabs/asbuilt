"""The model extractor: one structured-output call per skeleton, through
`bench.llm.CountingClient`, with a provider adapter per backend.

Two providers, both behind the same `ClientFactory` shape
(`client_factory() -> object with .messages.create(**kwargs)`):

- **`claude-code`** (the default — asbuilt#8, Oleg's decision: model calls
  run on his Claude Code subscription, never an API key). `ClaudeCodeClient`
  and its supporting machinery (the subprocess wiring, the credential rule,
  the `modelUsage` adapter) live in `bench/claude_code.py` as of asbuilt#9 —
  moved so the benchmark's own arms (`prototypes/baseline`) can reuse the
  same provider without importing this test-connector-specific package;
  re-exported below so every existing import of this module is unaffected.
  See that module's docstring for the flag choices, the credential rule and
  the `modelUsage` adapter this connector's own call relies on.
  `python -m connectors.tests --model-dry-run` never invokes either
  provider at all under any `--extractor` (a review finding on asbuilt#8:
  `--extractor model --model-dry-run` used to run the real block first).
- **`anthropic`** (opt-in, `--provider anthropic`) imports the SDK lazily
  (never at module import time — `uv sync` without the optional `model`
  dependency group, and every test in this repo, must work without it
  installed). Needs `ANTHROPIC_API_KEY`; not the default because Oleg's
  decision above rules out API-key billing for routine use.

Bedrock is meant to follow through the same `client_factory` shape once a
provider is chosen; not built in this slice. `dry_run` builds every prompt
exactly as `extract_with_model` would, estimates tokens as `len(text) // 4`,
and prices them from `PRICE_TABLE` — stated and labelled here, not fetched,
so it is visibly a stated assumption rather than a silently-current price;
it is provider-agnostic (a token-based estimate, not a real subscription
cost) and never makes a call under either provider.

`extract_with_model` calls `bench.claude_code.structured_call` — the
generic "one structured call, through the one wrapped client" helper every
benchmark arm uses (asbuilt#9) — with this module's own `SCHEMA` and system
prompt, keeping the `"record_fact"` tool name this module's own tests
already assert on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from bench.claude_code import (
    _CLAUDE_CODE_OAUTH_TOKEN_ENV,  # noqa: F401 - re-exported, see module docstring
    _CLAUDE_CODE_TOKEN_FILE,  # noqa: F401 - re-exported, see module docstring
    ClaudeCodeClient,  # noqa: F401 - re-exported, see module docstring
    _claude_code_oauth_token,  # noqa: F401 - re-exported, see module docstring
    _extract_tool_input,  # noqa: F401 - re-exported, see module docstring
    load_claude_code_client,
    structured_call,
)
from bench.claude_code import DEFAULT_SYSTEM_PROMPT as _CLAUDE_CODE_SYSTEM_PROMPT
from bench.llm import BudgetExceeded
from connectors.tests.collect import Skeleton
from connectors.tests.extract_rules import Rule

# $ per million tokens. Stated assumption, 2026-09-28, Claude pricing as
# publicly listed; re-check before any real spend.
PRICE_TABLE: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_creation": 3.75, "cache_read": 0.30},
}
DEFAULT_MODEL = "claude-sonnet-5"
# Measured on the first real full run, 2026-09-29 (asbuilt#15, 17 calls at c6
# before the budget stop): 9,549 output tokens, so about 560 per call — a
# structured Fact plus the model's own short text; and 139,208 cache-creation
# tokens against 34 input tokens, so every headless `claude -p` call writes
# its whole prompt PLUS the CLI's own system prompt (~8,000 tokens) to the
# cache anew — sessions are not persisted, nothing is read back — and that
# overhead, not the prompt, dominates a connector call. The dry run therefore
# adds it per call and prices everything at the cache-creation rate; the
# first estimate (prompt text alone at the input rate) was 25x under.
DEFAULT_OUTPUT_TOKENS_PER_CALL = 560
CLAUDE_CODE_CALL_OVERHEAD_TOKENS = 8_200

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
    estimated_input_tokens: int  # prompt text plus the per-call overhead
    estimated_output_tokens: int
    model: str
    price_per_million: dict[str, float]
    estimated_dollars: float
    estimated_overhead_tokens: int = 0  # the per-call part of estimated_input_tokens
    priced_input_as: str = "cache_creation"  # see CLAUDE_CODE_CALL_OVERHEAD_TOKENS


def dry_run(
    skeletons: list[Skeleton],
    rules: dict[str, Rule],
    *,
    model: str = DEFAULT_MODEL,
    output_tokens_per_call: int = DEFAULT_OUTPUT_TOKENS_PER_CALL,
    overhead_tokens_per_call: int = CLAUDE_CODE_CALL_OVERHEAD_TOKENS,
) -> DryRunResult:
    """The estimate a run prints before any call. Input = the prompts' own
    text plus `overhead_tokens_per_call` per prompt, priced at the cache-
    creation rate, since a headless call writes all of it to the cache
    (measured, see `CLAUDE_CODE_CALL_OVERHEAD_TOKENS`)."""
    if model not in PRICE_TABLE:
        raise ValueError(f"no price table entry for {model!r}; add one to PRICE_TABLE")
    prices = PRICE_TABLE[model]

    prompt_tokens = sum(_estimate_tokens(build_prompt(s, rules.get(s.node_id))) for s in skeletons)
    overhead = len(skeletons) * overhead_tokens_per_call
    total_input = prompt_tokens + overhead
    total_output = len(skeletons) * output_tokens_per_call
    dollars = (total_input * prices["cache_creation"] + total_output * prices["output"]) / 1_000_000

    return DryRunResult(
        prompts=len(skeletons),
        estimated_input_tokens=total_input,
        estimated_output_tokens=total_output,
        model=model,
        price_per_million=prices,
        estimated_dollars=dollars,
        estimated_overhead_tokens=overhead,
    )


class ModelRunStopped(BudgetExceeded):
    """`BudgetExceeded` raised out of `extract_with_model` WITH the results
    the run had already paid for (asbuilt#15: the first full run lost 16
    extracted facts when the stop propagated bare and the CLI wrote
    nothing). `results` are the payloads completed before the refused call;
    `client` is the `CountingClient` with the counters as they stood."""

    def __init__(self, cause: BudgetExceeded, results: list[dict[str, Any]], client: Any):
        super().__init__(cause.arm, cause.reason)
        self.results = results
        self.client = client


class ModelRunFailed(RuntimeError):
    """A provider error mid-run (a non-zero `claude -p` exit, a timeout,
    unparsable output — every `RuntimeError` the provider raises), re-raised
    WITH the results already paid for and the counting client, for the same
    reason as `ModelRunStopped` (a local review note on asbuilt#15: a
    transient failure on call 20 of 24 must not lose the first 19)."""

    def __init__(self, cause: RuntimeError, results: list[dict[str, Any]], client: Any):
        super().__init__(str(cause))
        self.results = results
        self.client = client


class ClientFactory(Protocol):
    def __call__(self) -> Any: ...


def load_anthropic_client(api_key: str | None = None) -> Any:
    """Lazily imports the `anthropic` SDK (the `model` optional dependency
    group) — never at module import time."""
    import anthropic  # noqa: PLC0415 - deliberately lazy, see module docstring

    return anthropic.Anthropic(api_key=api_key)


PROVIDERS: dict[str, ClientFactory] = {
    "claude-code": load_claude_code_client,
    "anthropic": load_anthropic_client,
}
DEFAULT_PROVIDER = "claude-code"


def extract_with_model(
    skeletons: list[Skeleton],
    rules: dict[str, Rule],
    *,
    client_factory: ClientFactory = load_claude_code_client,
    arm: str = "stack-b-model",
    model: str = DEFAULT_MODEL,
    budget: Any = None,
    stop_dir: Any = None,
) -> tuple[list[dict[str, Any]], Any]:
    """Makes one real structured-output call per skeleton, through a
    `CountingClient`. Defaults to the `claude-code` provider (Oleg's
    decision: never an API key for routine calls — see module docstring);
    pass `client_factory=load_anthropic_client` for the opt-in alternative,
    or look up `PROVIDERS[name]`. Never given a real client in this
    package's own tests — a fake `client_factory` (or a fake `claude`
    executable on `PATH`, for the claude-code path) proves the wiring
    without spending anything (see `tests/test_connector_model.py`).
    `stop_dir` passes through to `CountingClient` (default: its own
    `build/`) so a test exercising the budget stop condition can point it
    at a `tmp_path` instead."""
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

    results: list[dict[str, Any]] = []
    for skeleton in skeletons:
        prompt = build_prompt(skeleton, rules.get(skeleton.node_id))
        try:
            payload = structured_call(
                wrapped,
                _CLAUDE_CODE_SYSTEM_PROMPT,
                prompt,
                SCHEMA,
                model=model,
                max_tokens=300,
                tool_name="record_fact",
            )
        except BudgetExceeded as exc:
            # The stop file is already written by the client; hand back what
            # was extracted so far rather than losing it (asbuilt#15).
            raise ModelRunStopped(exc, results, wrapped) from exc
        except RuntimeError as exc:
            raise ModelRunFailed(exc, results, wrapped) from exc
        if payload is not None:
            results.append({"node_id": skeleton.node_id, **payload})
    return results, wrapped
