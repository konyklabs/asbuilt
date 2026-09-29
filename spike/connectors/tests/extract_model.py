"""The model extractor: one structured-output call per skeleton, through
`bench.llm.CountingClient`, with a provider adapter per backend.

Two providers, both behind the same `ClientFactory` shape
(`client_factory() -> object with .messages.create(**kwargs)`):

- **`claude-code`** (the default — asbuilt#8, Oleg's decision: model calls
  run on his Claude Code subscription, never an API key). One `claude -p`
  subprocess per skeleton — no tools (`--tools ""`), a minimal system
  prompt, `--json-schema` for the same `SCHEMA` the `anthropic` path
  validates against, `--output-format json` for one parseable result, and
  `--max-turns 1`: real and type-checked (`claude --max-turns notanumber
  --version` fails with "must be a number"; an actually-unknown flag is
  silently accepted instead) but hidden from `claude --help`/`claude -p
  --help` on the installed CLI (2.1.284) — on top of `--tools ""` already
  ruling out a tool-driven extra turn. The schema-validated object comes
  back under `structured_output`, NOT `result` (`result` is the assistant's
  own prose text — read only as a fallback, and only when it happens to
  already be schema-shaped JSON on its own; a review round caught this
  module's first draft reading `result` as the structured value, which is
  only true when the model's own text response happens to be empty).
  `is_error: true` or a `subtype` other than `"success"` is an error,
  reported with `result`'s own first line. `CLAUDE_CODE_OAUTH_TOKEN` is
  read from the environment or, if unset, `~/.config/konyklabs/claude-code-
  oauth-token` — placed into the subprocess's own env, which also has every
  `ANTHROPIC_*` name, every `CLAUDE_CODE_USE_*` backend selector
  (`_BEDROCK`/`_VERTEX`/`_FOUNDRY`, or a future sibling), and
  `AWS_BEARER_TOKEN_BEDROCK` stripped first (`_billing_isolated_env`): any
  of these, if set in the parent process, would silently route the call off
  Oleg's subscription (an API key, or a cloud account entirely) — two
  review findings, fixed together since they're the same shape of bug.
  This covers the process environment only; a settings-file
  `apiKeyHelper` is a separate credential path outside it, and stays the
  operator's own responsibility to keep unset here. The token itself is
  never printed, never logged, never part of an exception message (a
  failure surfaces only stderr's or `result`'s own first line).
  `_usage_namespace_from_result` adapts the result JSON's `modelUsage`
  (per-model input/output/cache token counts) into the exact `.input_
  tokens`/`.output_tokens`/`.cache_creation_input_tokens`/`.cache_read_
  input_tokens` shape `bench.llm.CountingClient._call` already reads off
  any Anthropic-SDK-shaped response via `getattr` — the "small adapter"
  that lets its counters, its 80% stop and its stop file work completely
  unchanged; when `modelUsage` itself is absent, this returns None rather
  than a zero-filled usage, so `_call`'s own missing-usage estimate and
  `usage_missing` flag still fire instead of being silently bypassed (a
  third review finding). The exact field names (`modelUsage`, `total_cost_
  usd`) are this module's own stated assumption, from the driving task's
  own description, not yet confirmed against a real call: **no real
  `claude -p` call is made anywhere in this slice** — a fake `claude`
  executable on `PATH` proves the subprocess wiring in
  `tests/test_connector_model.py`, and `python -m connectors.tests
  --model-dry-run` never invokes either provider at all under any
  `--extractor` (a fourth review finding: `--extractor model
  --model-dry-run` used to run the real block first).
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
    assumption pending a real call.

    Review fix, asbuilt#8: None when `modelUsage` is ABSENT — a zero-filled
    namespace there would look like a real ``.usage`` to `CountingClient
    ._call`'s own `getattr(response, "usage", None)` check, silently
    bypassing its missing-usage estimate and its `usage_missing` flag (the
    exact guard `bench/llm.py`'s own docstring exists for: "a silently-zero
    call would otherwise let real usage hide under a budget that looks
    unspent"). A `modelUsage` key that IS present, even as `{}`, still sums
    to zero-filled totals — only its outright absence means "no usage
    reported at all"."""
    if "modelUsage" not in payload:
        return None
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


def _matches_schema(obj: Any) -> bool:
    """A light check — required top-level keys present on a dict — not a
    real JSON-Schema validator; enough to tell a genuine structured result
    parsed out of `result`'s prose apart from an object that merely happens
    to be valid JSON (an error message, a stray code block, ...)."""
    return isinstance(obj, dict) and all(key in obj for key in SCHEMA["required"])


_DROPPED_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_")
_DROPPED_ENV_NAMES = {"AWS_BEARER_TOKEN_BEDROCK"}


def _billing_isolated_env() -> dict[str, str]:
    """A copy of the parent environment with every credential or backend
    selector that could route a call off Oleg's Claude Code subscription
    removed: `ANTHROPIC_*` (in `-p` mode the CLI prefers `ANTHROPIC_API_KEY`/
    `ANTHROPIC_AUTH_TOKEN` over `CLAUDE_CODE_OAUTH_TOKEN` whenever both are
    set — review finding, asbuilt#8), `CLAUDE_CODE_USE_*` (`_BEDROCK`/
    `_VERTEX`/`_FOUNDRY` and any future sibling — a second review finding:
    any of these, if set in the parent, would silently switch the call onto
    that cloud account instead), and `AWS_BEARER_TOKEN_BEDROCK` (Bedrock's
    own credential, not covered by either prefix). Only `CLAUDE_CODE_OAUTH_
    TOKEN` is added back, by the caller, never any of the removed names.
    This covers the process environment only — a settings-file
    `apiKeyHelper` (`claude --settings`/project/user settings) is a
    separate credential path this function has no way to see or strip, and
    stays the operator's own responsibility to keep unset for this use."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(_DROPPED_ENV_PREFIXES) and k not in _DROPPED_ENV_NAMES
    }


def _invoke_claude_code(prompt: str, model: str, claude_bin: str = "claude") -> Any:
    """One `claude -p` subprocess call — see the module docstring for the
    flag choices and the credential rule. Returns an Anthropic-response-
    shaped object (`.usage`, `.content` with one `tool_use` block carrying
    the schema-validated dict) so `_extract_tool_input` and
    `extract_with_model` need no provider-specific branch at all.

    Review fix, asbuilt#8: the installed CLI (2.1.284) puts the schema-
    validated object under `structured_output`, not `result` — `result`
    holds the assistant's own prose text (the JSON is back-filled into
    `result` only when that text is empty, which this function never relies
    on). `structured_output` is read first; `result` is only a fallback,
    and only when it happens to already be schema-shaped JSON on its own —
    prose in `result` never becomes a candidate structured value. `is_error`
    true or a `subtype` other than `"success"` is an error, reported with
    the first line of `result`'s own text (never stderr, since a model-
    level error is not a process-level one)."""
    env = _billing_isolated_env()
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
        # Hidden from `claude --help`/`claude -p --help` on 2.1.284, but a
        # real, type-checked option (`claude --max-turns notanumber
        # --version` fails with "must be a number"; an actually-unknown
        # flag is silently accepted instead) — the closest thing to a turn
        # cap this CLI has, on top of `--tools ""` already ruling out any
        # tool-driven extra turn.
        "--max-turns",
        "1",
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

    result_text = payload.get("result") if isinstance(payload.get("result"), str) else ""
    if payload.get("is_error") or payload.get("subtype", "success") != "success":
        raise RuntimeError(f"claude -p returned an error: {_first_line(result_text, '(no text)')}")

    structured = payload.get("structured_output")
    if structured is None and result_text:
        try:
            candidate = json.loads(result_text)
        except json.JSONDecodeError:
            candidate = None
        if _matches_schema(candidate):
            structured = candidate

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
