"""The model extractor: one structured-output call per skeleton, through
`bench.llm.CountingClient`, with a provider adapter per backend.

Two providers, both behind the same `ClientFactory` shape
(`client_factory() -> object with .messages.create(**kwargs)`):

- **`claude-code`** (the default — asbuilt#8, Oleg's decision: model calls
  run on his Claude Code subscription, never an API key). One `claude -p`
  subprocess per skeleton — no tools (`--tools ""`; the installed CLI,
  version 2.1.284, has no separate turn-cap flag in `claude --help`/
  `claude -p --help`, but no tools at all means no turn beyond the first is
  possible either way), a minimal system prompt, `--json-schema` for the
  same `SCHEMA` the `anthropic` path validates against, `--output-format
  json` for one parseable result. `CLAUDE_CODE_OAUTH_TOKEN` is read from
  the environment or, if unset, `~/.config/konyklabs/claude-code-oauth-
  token` — placed into the subprocess's own env only, never printed, never
  logged, never part of an exception message (a failure surfaces only
  stderr's first line). `_usage_namespace_from_result` adapts the result
  JSON's `modelUsage` (per-model input/output/cache token counts) into the
  exact `.input_tokens`/`.output_tokens`/`.cache_creation_input_tokens`/
  `.cache_read_input_tokens` shape `bench.llm.CountingClient._call` already
  reads off any Anthropic-SDK-shaped response via `getattr` — the "small
  adapter" that lets its counters, its 80% stop and its stop file work
  completely unchanged. The exact field names (`modelUsage`, `total_cost_
  usd`) are this module's own stated assumption, from the driving task's
  own description, not yet confirmed against a real call: **no real
  `claude -p` call is made anywhere in this slice** — a fake `claude`
  executable on `PATH` proves the subprocess wiring in
  `tests/test_connector_model.py`, and `python -m connectors.tests
  --model-dry-run` never invokes either provider at all.
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
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
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


_CLAUDE_CODE_OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
_CLAUDE_CODE_TOKEN_FILE = Path.home() / ".config" / "konyklabs" / "claude-code-oauth-token"
_CLAUDE_CODE_SYSTEM_PROMPT = (
    "You extract exactly one structured fact from a single test's own source "
    "and assertion. Never invent beyond what the test proves. Respond with "
    "only the JSON the schema requires."
)


def _claude_code_oauth_token() -> str | None:
    """`CLAUDE_CODE_OAUTH_TOKEN` from the environment, else the token file at
    `_CLAUDE_CODE_TOKEN_FILE` — never printed, never logged, and never
    included in any exception message this module raises (see
    `_invoke_claude_code`, which only ever surfaces stderr's first line)."""
    token = os.environ.get(_CLAUDE_CODE_OAUTH_TOKEN_ENV)
    if token:
        return token
    if _CLAUDE_CODE_TOKEN_FILE.is_file():
        return _CLAUDE_CODE_TOKEN_FILE.read_text().strip() or None
    return None


def _first_line(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line
    return fallback


def _usage_namespace_from_result(payload: dict[str, Any]) -> Any:
    """Sums `modelUsage` (one entry per model — more than one only if a
    fallback model fired mid-call) into `bench.llm.CountingClient`'s own
    response-usage shape (module docstring: the "small adapter"). Field
    names are read defensively, camelCase (the Claude Code CLI's own
    convention) with a snake_case fallback, since this shape is a stated
    assumption pending a real call."""
    totals = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    for usage in (payload.get("modelUsage") or {}).values():
        totals["input"] += usage.get("inputTokens", usage.get("input_tokens", 0)) or 0
        totals["output"] += usage.get("outputTokens", usage.get("output_tokens", 0)) or 0
        totals["cache_creation"] += (
            usage.get("cacheCreationInputTokens", usage.get("cache_creation_input_tokens", 0)) or 0
        )
        totals["cache_read"] += (
            usage.get("cacheReadInputTokens", usage.get("cache_read_input_tokens", 0)) or 0
        )
    return SimpleNamespace(
        input_tokens=totals["input"],
        output_tokens=totals["output"],
        cache_creation_input_tokens=totals["cache_creation"],
        cache_read_input_tokens=totals["cache_read"],
    )


def _invoke_claude_code(prompt: str, model: str, claude_bin: str = "claude") -> Any:
    """One `claude -p` subprocess call — see the module docstring for the
    flag choices and the credential rule. Returns an Anthropic-response-
    shaped object (`.usage`, `.content` with one `tool_use` block carrying
    the schema-validated dict) so `_extract_tool_input` and
    `extract_with_model` need no provider-specific branch at all."""
    env = dict(os.environ)
    token = _claude_code_oauth_token()
    if token:
        env[_CLAUDE_CODE_OAUTH_TOKEN_ENV] = token

    args = [
        claude_bin,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--model",
        model,
        "--json-schema",
        json.dumps(SCHEMA),
        "--tools",
        "",
        "--system-prompt",
        _CLAUDE_CODE_SYSTEM_PROMPT,
        "--no-session-persistence",
    ]
    result = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {result.returncode}: {_first_line(result.stderr, '(no stderr)')}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"claude -p produced unparsable JSON: {_first_line(result.stdout, '(empty stdout)')}"
        ) from exc

    raw_result = payload.get("result")
    structured = raw_result
    if isinstance(raw_result, str):
        try:
            structured = json.loads(raw_result)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"claude -p's result field wasn't valid JSON: {exc}") from exc

    return SimpleNamespace(
        usage=_usage_namespace_from_result(payload),
        content=[SimpleNamespace(type="tool_use", input=structured)],
        total_cost_usd=payload.get("total_cost_usd"),
    )


class _ClaudeCodeMessages:
    def __init__(self, claude_bin: str = "claude") -> None:
        self._claude_bin = claude_bin

    def create(self, **kwargs: Any) -> Any:
        # `tools`/`tool_choice`/`max_tokens` are the `anthropic` path's own
        # call shape (see `extract_with_model`) — ignored here; the schema
        # goes over `--json-schema` instead (see `_invoke_claude_code`).
        model = kwargs.get("model", DEFAULT_MODEL)
        messages = kwargs.get("messages") or []
        prompt = messages[-1]["content"] if messages else ""
        return _invoke_claude_code(prompt, model, self._claude_bin)


class ClaudeCodeClient:
    """The default provider (module docstring): a `client.messages.create(
    **kwargs)`-shaped wrapper over one `claude -p` subprocess call per
    prompt, dropping into `extract_with_model`/`CountingClient` exactly
    where `load_anthropic_client`'s client would."""

    def __init__(self, claude_bin: str = "claude") -> None:
        self.messages = _ClaudeCodeMessages(claude_bin=claude_bin)


def load_claude_code_client(claude_bin: str = "claude") -> ClaudeCodeClient:
    return ClaudeCodeClient(claude_bin=claude_bin)


PROVIDERS: dict[str, ClientFactory] = {
    "claude-code": load_claude_code_client,
    "anthropic": load_anthropic_client,
}
DEFAULT_PROVIDER = "claude-code"


def _extract_tool_input(response: Any) -> dict[str, Any] | None:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            return getattr(block, "input", None)
    return None


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
