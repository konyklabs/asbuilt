"""The `claude-code` provider: one `claude -p` subprocess call, wrapped in
the Anthropic-Messages-API shape (`client.messages.create(**kwargs)`) every
other piece of this harness already expects (asbuilt#9; moved here from
`connectors/tests/extract_model.py`, asbuilt#8, so `bench`'s own benchmark
arms can use it without importing the test-connector package — re-exported
from there so nothing that already imports it breaks).

`ClaudeCodeClient` is the default provider (Oleg's decision: model calls run
on his Claude Code subscription, never an API key). One subprocess per
prompt, no vendor SDK: `-p` with NO inline prompt, `--output-format json`,
`--model`, an optional `--json-schema` (pulled out of the Anthropic-shaped
call's own `tools[0]["input_schema"]` — see `structured_call` below — so a
caller never constructs the CLI flag directly), `--no-session-persistence`,
`--strict-mcp-config`, and `--max-turns` (hidden from `claude --help`/
`claude -p --help` on the installed CLI (2.1.284) but real and type-checked:
`claude --max-turns notanumber --version` fails with "must be a number").
`tools`/`cwd` generalise the original test-connector-only call (which always
ran with `--tools ""` and the parent's own cwd) so a caller that needs the
model to read the corpus itself — the baseline arm's `grep` variant
(`prototypes/baseline`, asbuilt#9) — can pass `tools="Read,Grep,Glob"` and a
working directory, while the connector's own no-tools, cwd-less call keeps
working unchanged.

**The prompt travels over stdin, never argv** (asbuilt#9 review, blocking):
an earlier version passed it as `-p <prompt>`, one argv element — fine for a
short test-connector prompt, but the baseline arm's `full` variant embeds
the whole ingested corpus (hundreds of KB on the real fixture) in that same
prompt, and Linux caps a single argv element around 128 KB (`ARG_MAX` is
much larger, but the per-argument limit still applies; macOS tolerates it,
which is why this shipped once before it was caught). `subprocess.run(...,
input=prompt, text=True)` writes it to the child's stdin instead — the CLI
reads `-p` with no value as "read the prompt from stdin", so nothing else
about the call changes — and, as a side effect, this is also what keeps a
`claude -p` subprocess launched from inside `asbuilt_mcp.py`'s own stdio
server from inheriting the parent's JSON-RPC pipe on stdin (review point 2):
`subprocess.run(input=...)` always gives the child its own pipe, written
once and closed, never the parent's real stdin descriptor. `--strict-mcp-
config` (review point 3, verified present on the installed CLI via `claude
-p --help`) stops a `claude -p` call made from inside `spike/` from also
loading `spike/.mcp.json` as a *project-scoped* server — that file exists
for a person's own interactive `claude --plugin-dir spike/plugin` session,
not for this module's own headless calls, and loading it added an
unresolved-`${CLAUDE_PLUGIN_ROOT}` failure plus ~2s of startup to every
timed query. `timeout` (default `DEFAULT_TIMEOUT_SECONDS`, review point 1)
bounds the subprocess call; a `subprocess.TimeoutExpired` is turned into the
same kind of `RuntimeError` every other failure path here raises, never a
raw exception escaping to the caller.

The schema-validated object comes back under `structured_output`, NOT
`result` (`result` is the assistant's own prose text — read only as a
fallback, and only when it happens to already be schema-shaped JSON on its
own). `is_error: true` or a `subtype` other than `"success"` is an error,
reported with `result`'s own first line. `CLAUDE_CODE_OAUTH_TOKEN` is read
from the environment or, if unset, `~/.config/konyklabs/claude-code-oauth-
token` — placed into the subprocess's own env, which also has every
`ANTHROPIC_*`, `CLAUDE_CODE_USE_*` (`_BEDROCK`/`_VERTEX`/`_FOUNDRY`) and
`AWS_BEARER_TOKEN_BEDROCK` variable stripped first (`_isolated_credential_env`
— exactly that list, nothing else in the parent environment is touched): in
`-p` mode the CLI prefers `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` over the
OAuth token whenever both are set, and any of the third-party-provider
variables would redirect the call off the subscription entirely — either
would silently switch billing or provider the moment the parent process
happens to have one set (stack-B review, asbuilt#9). The token itself is
never printed, never logged, never part of an exception message.

`structured_call(client, system, prompt, schema, *, model=, max_tokens=,
tool_name=)` is the generic, provider-agnostic helper both
`connectors.tests.extract_model.extract_with_model` and every
`prototypes.*` arm use: one Anthropic-Messages-shaped call with `schema` as
a tool's `input_schema` (the claude-code provider above pulls it back out
for `--json-schema`; the `anthropic` provider's SDK reads `tools=` directly,
so no provider-specific branch is needed here), returning the parsed dict or
`None` if the model made no tool call.

No real `claude -p` call is made anywhere in this repository's own tests — a
fake `claude` executable on `PATH` proves the subprocess wiring instead
(`tests/test_connector_model.py`, `tests/test_prototype_baseline.py`).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_TIMEOUT_SECONDS = 600.0
# asbuilt#21: a process-level failure (non-zero exit, timeout) is retried
# once by the client after this pause; `ASBUILT_RETRY_PAUSE` overrides it
# (tests set 0). A model-level error is never retried.
DEFAULT_RETRY_PAUSE_SECONDS = 5.0
DEFAULT_MAX_RETRIES = 1


class ProcessFailure(RuntimeError):
    """One `claude -p` call failed in a way worth one retry (asbuilt#21): a
    timeout, a crash (a non-zero exit with no result object on stdout), or
    an upstream API error (a result object carrying `api_error_status` —
    the CLI's shape for a rate limit, an overloaded or 5xx answer). Every
    other failure — a result object with a non-success `subtype` such as
    `error_max_turns`, `error_max_budget_usd` or `error_during_execution`,
    or `is_error` without an API status — is a plain RuntimeError and is
    never retried: deterministic, and re-sending it only spends again."""


def _what_it_said(payload: Any, stdout: str, stderr: str) -> str:
    """What a failed call said, one line, never the token (asbuilt#21: the
    second real run ended with "exited 1: (no stderr)" and nothing more).
    stderr's first non-blank line; else, from the result object the CLI
    writes to stdout in `--output-format json` mode, the first of its
    `errors` (the installed CLI, 2.1.285, reports every non-success
    `subtype` there — a local lens round read the binary: `result` exists
    only on the `success` variant, where an API error arrives as `is_error`
    plus `api_error_status` plus `result` text); else that `result` text;
    else the `subtype`; else stdout's first non-blank line; else nothing."""
    line = _first_line(stderr, "")
    if line:
        return line
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list):
            for entry in errors:
                said = _first_line(str(entry), "") if entry is not None else ""
                if said:
                    return said
        text = payload.get("result") if isinstance(payload.get("result"), str) else ""
        said = _first_line(text, "") or str(payload.get("subtype") or "")
        if said:
            return said
    return _first_line(stdout, "")


def _failure_reason(returncode: int, stdout: str, stderr: str) -> str:
    """The one-line reason for a failed call — see `_what_it_said`."""
    try:
        payload = json.loads(stdout or "")
    except json.JSONDecodeError:
        payload = None
    said = _what_it_said(payload, stdout, stderr)
    if returncode != 0:
        if said:
            return f"claude -p exited {returncode}: {said}"
        return f"claude -p exited {returncode} with no output"
    return f"claude -p returned an error: {said or '(no text)'}"


DEFAULT_SYSTEM_PROMPT = (
    "You extract exactly one structured fact from a single test's own source "
    "and assertion. Never invent beyond what the test proves. Respond with "
    "only the JSON the schema requires."
)

_CLAUDE_CODE_OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
_CLAUDE_CODE_TOKEN_FILE = Path.home() / ".config" / "konyklabs" / "claude-code-oauth-token"


def _claude_code_oauth_token() -> str | None:
    """`CLAUDE_CODE_OAUTH_TOKEN` from the environment, else the token file at
    `_CLAUDE_CODE_TOKEN_FILE` — never printed, never logged, and never
    included in any exception message this module raises (see
    `_invoke_claude_code`, which only ever surfaces stderr's or the model
    result's own first line)."""
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
    response-usage shape. Field names are read defensively, camelCase (the
    Claude Code CLI's own convention) with a snake_case fallback, since this
    shape is a stated assumption pending a real call (asbuilt#8).

    Returns `None` when the payload carries no `modelUsage` at all (or an
    empty one) — stack-B review, asbuilt#9: an earlier version returned a
    zero-filled `SimpleNamespace` here instead, which `bench.llm.
    CountingClient._call`'s `usage is None` check treats as genuine
    zero-token usage, silently bypassing its own missing-usage estimate and
    `usage_missing` flag rather than tripping them."""
    model_usage = payload.get("modelUsage")
    if not model_usage:
        return None
    totals = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    for usage in model_usage.values():
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


def _matches_schema(obj: Any, schema: dict[str, Any]) -> bool:
    """A light check — required top-level keys present on a dict — not a
    real JSON-Schema validator; enough to tell a genuine structured result
    parsed out of `result`'s prose apart from an object that merely happens
    to be valid JSON (an error message, a stray code block, ...)."""
    return isinstance(obj, dict) and all(key in obj for key in schema.get("required", []))


_STRIPPED_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_")
_STRIPPED_NAMES = ("AWS_BEARER_TOKEN_BEDROCK",)


def _isolated_credential_env() -> dict[str, str]:
    """A copy of the parent environment with every credential/provider
    variable that could redirect a claude-code call away from Oleg's
    subscription removed: every `ANTHROPIC_*` name (`ANTHROPIC_API_KEY`/
    `ANTHROPIC_AUTH_TOKEN` are preferred by the CLI over
    `CLAUDE_CODE_OAUTH_TOKEN` whenever both are set — review finding,
    asbuilt#8), every `CLAUDE_CODE_USE_*` name (`CLAUDE_CODE_USE_BEDROCK`/
    `_VERTEX`/`_FOUNDRY` switch the CLI onto a third-party provider), and
    `AWS_BEARER_TOKEN_BEDROCK` (Bedrock's own bearer-token credential) —
    stack-B review, asbuilt#9: any of these, inherited from the parent
    process, would silently switch a call meant for the subscription onto a
    different provider or billing path. This list is exactly what is
    stripped; nothing else in the parent environment is touched. Only
    `CLAUDE_CODE_OAUTH_TOKEN` is added back, by the caller, never any of the
    names stripped here."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(_STRIPPED_PREFIXES) and k not in _STRIPPED_NAMES
    }


def _invoke_claude_code(
    prompt: str,
    model: str,
    claude_bin: str = "claude",
    *,
    schema: dict[str, Any] | None,
    system_prompt: str,
    tools: str = "",
    cwd: Path | None = None,
    max_turns: int = 1,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = 0,
    retry_pause: float = DEFAULT_RETRY_PAUSE_SECONDS,
    on_retry: Any = None,
) -> Any:
    """One `claude -p` subprocess call — see the module docstring for the
    flag choices, the stdin-not-argv rule and the credential rule. Returns
    an Anthropic-response-shaped object (`.usage`, `.content` with one
    `tool_use` block carrying the schema-validated dict, when `schema` is
    given) so `_extract_tool_input` and `structured_call` need no
    provider-specific branch at all.

    `structured_output` is read first; `result` is only a fallback, and only
    when it happens to already be schema-shaped JSON on its own — prose in
    `result` never becomes a candidate structured value. `is_error` true or a
    `subtype` other than `"success"` is an error, reported with the first
    line of `result`'s own text (never stderr, since a model-level error is
    not a process-level one). `tools`/`cwd` let a caller enable the CLI's own
    tools (e.g. `"Read,Grep,Glob"`) and set the subprocess's working
    directory — the baseline arm's `grep` variant needs both; the
    test-connector's own calls pass neither (no tools, inherited cwd).
    `timeout` bounds each attempt; a `subprocess.TimeoutExpired` becomes a
    `ProcessFailure` (a `RuntimeError`) like every other failure path here,
    not a raw exception, and with `max_retries` above zero one more attempt
    follows after `retry_pause` (asbuilt#21; the client passes 1)."""
    env = _isolated_credential_env()
    token = _claude_code_oauth_token()
    if token:
        env[_CLAUDE_CODE_OAUTH_TOKEN_ENV] = token

    args = [
        claude_bin,
        "-p",  # no inline prompt — sent over stdin below, never as an argv element
        "--output-format",
        "json",
        "--model",
        model,
    ]
    if schema is not None:
        args += ["--json-schema", json.dumps(schema)]
    args += [
        "--tools",
        tools,
        "--system-prompt",
        system_prompt,
        "--no-session-persistence",
        # Loads no project-scoped MCP servers (e.g. spike/.mcp.json, meant
        # for an interactive plugin session, not this headless call) —
        # without it, a call made from inside spike/ fails resolving
        # ${CLAUDE_PLUGIN_ROOT} and adds ~2s startup to every query (review).
        "--strict-mcp-config",
        # Hidden from `claude --help`/`claude -p --help` on 2.1.284, but a
        # real, type-checked option — the closest thing to a turn cap this
        # CLI has, on top of `--tools ""` (when no tools are given) already
        # ruling out any tool-driven extra turn.
        "--max-turns",
        str(max_turns),
    ]
    # asbuilt#21: a process-level failure is retried up to `max_retries`
    # times after `retry_pause` (the client passes 1; a direct call none);
    # `on_retry` is told each time so the run's usage record can count it.
    attempts = 1 + max(0, int(max_retries))
    for attempt in range(1, attempts + 1):
        try:
            payload = _run_claude_once(args, prompt, env, cwd, timeout)
            break
        except ProcessFailure as exc:
            if attempt >= attempts:
                if attempts > 1:
                    raise ProcessFailure(f"{exc} (after {attempts - 1} retry)") from exc
                raise
            if on_retry is not None:
                on_retry()
            time.sleep(retry_pause)

    result_text = payload.get("result") if isinstance(payload.get("result"), str) else ""
    structured = payload.get("structured_output")
    if structured is None and result_text:
        try:
            candidate = json.loads(result_text)
        except json.JSONDecodeError:
            candidate = None
        if candidate is not None and (schema is None or _matches_schema(candidate, schema)):
            structured = candidate

    return SimpleNamespace(
        usage=_usage_namespace_from_result(payload),
        content=[SimpleNamespace(type="tool_use", input=structured)],
        total_cost_usd=payload.get("total_cost_usd"),
    )


def _run_claude_once(
    args: list[str], prompt: str, env: dict[str, str], cwd: Path | None, timeout: float
) -> dict[str, Any]:
    """One attempt: the subprocess, then the outcome sorted into a
    successful result object (returned), a `ProcessFailure` (a timeout, a
    crash with no result object, an upstream API error — worth one retry)
    or a plain `RuntimeError` (a model-level error — never retried); see
    `ProcessFailure`. `subprocess.run` kills the child on a timeout before
    raising, so a retry never races a still-running first attempt."""
    try:
        result = subprocess.run(
            args,
            input=prompt,  # stdin, not argv (review, blocking) — see module docstring
            capture_output=True,
            text=True,
            env=env,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessFailure(f"claude -p timed out after {timeout}s") from exc
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        reason = _failure_reason(result.returncode, result.stdout, result.stderr)
        if result.returncode != 0:
            raise ProcessFailure(reason)  # a crash: nothing parseable came back
        raise RuntimeError(
            f"claude -p produced unparsable JSON: {_first_line(result.stdout, '(empty stdout)')}"
        )
    failed = (
        result.returncode != 0
        or bool(payload.get("is_error"))
        or payload.get("subtype", "success") != "success"
    )
    if failed:
        reason = _failure_reason(result.returncode, result.stdout, result.stderr)
        if payload.get("api_error_status") is not None:
            raise ProcessFailure(reason)  # an upstream API error: worth one retry
        raise RuntimeError(reason)  # model-level: deterministic, never retried
    return payload


class _ClaudeCodeMessages:
    def __init__(
        self,
        claude_bin: str = "claude",
        *,
        tools: str = "",
        cwd: Path | None = None,
        max_turns: int = 1,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        default_system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_pause: float | None = None,
    ) -> None:
        self._claude_bin = claude_bin
        self._tools = tools
        self._cwd = cwd
        self._max_turns = max_turns
        self._timeout = timeout
        self._default_system_prompt = default_system_prompt
        self._max_retries = max_retries
        self._retry_pause = (
            float(os.environ.get("ASBUILT_RETRY_PAUSE", DEFAULT_RETRY_PAUSE_SECONDS))
            if retry_pause is None
            else retry_pause
        )
        self.retries = 0  # process-level retries made over this client's life (asbuilt#21)

    def _count_retry(self) -> None:
        self.retries += 1

    def create(self, **kwargs: Any) -> Any:
        # `max_tokens`/`tool_choice` are the `anthropic` path's own call
        # shape — ignored here (the CLI has no per-call max-output-tokens
        # flag; the schema goes over `--json-schema` instead). The schema
        # itself is read back out of the Anthropic-shaped `tools=[{"name":
        # ..., "input_schema": schema}]` a caller (structured_call) already
        # built, so this class needs no schema parameter of its own.
        model = kwargs.get("model", DEFAULT_MODEL)
        messages = kwargs.get("messages") or []
        prompt = messages[-1]["content"] if messages else ""
        system_prompt = kwargs.get("system") or self._default_system_prompt
        tools_spec = kwargs.get("tools")
        schema = tools_spec[0].get("input_schema") if tools_spec else None
        return _invoke_claude_code(
            prompt,
            model,
            self._claude_bin,
            schema=schema,
            system_prompt=system_prompt,
            tools=self._tools,
            cwd=self._cwd,
            max_turns=self._max_turns,
            timeout=self._timeout,
            max_retries=self._max_retries,
            retry_pause=self._retry_pause,
            on_retry=self._count_retry,
        )


class ClaudeCodeClient:
    """The default provider (module docstring): a `client.messages.create(
    **kwargs)`-shaped wrapper over one `claude -p` subprocess call per
    prompt, dropping into `structured_call`/`bench.llm.CountingClient`
    exactly where an `anthropic.Anthropic()` client would. `tools`/`cwd`/
    `max_turns`/`timeout` are fixed for the life of one client — the
    baseline arm's `grep` variant constructs a separate instance with
    `tools="Read,Grep,Glob"` and `cwd=<ingest root>` rather than varying them
    per call."""

    def __init__(
        self,
        claude_bin: str = "claude",
        *,
        tools: str = "",
        cwd: Path | None = None,
        max_turns: int = 1,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        system_prompt: str | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_pause: float | None = None,
    ) -> None:
        self.messages = _ClaudeCodeMessages(
            claude_bin=claude_bin,
            tools=tools,
            cwd=cwd,
            max_turns=max_turns,
            timeout=timeout,
            default_system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
            max_retries=max_retries,
            retry_pause=retry_pause,
        )

    @property
    def retries(self) -> int:
        """Process-level retries made over this client's life (asbuilt#21)."""
        return self.messages.retries


def load_claude_code_client(claude_bin: str = "claude") -> ClaudeCodeClient:
    return ClaudeCodeClient(claude_bin=claude_bin)


def _extract_tool_input(response: Any) -> dict[str, Any] | None:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            return getattr(block, "input", None)
    return None


def structured_call(
    client: Any,
    system: str,
    prompt: str,
    schema: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    tool_name: str = "structured_output",
) -> dict[str, Any] | None:
    """One structured-output call over `client` (anything Anthropic-Messages-
    shaped: a raw SDK client, a `ClaudeCodeClient`, or a
    `bench.llm.CountingClient` wrapping either — this is the "one wrapped
    client" every model call in the benchmark goes through, D-013).  `schema`
    is given as a tool's `input_schema`; both providers read it from there
    (the claude-code provider pulls it back out for `--json-schema`; the
    `anthropic` SDK reads `tools=` directly). Returns the parsed dict, or
    `None` if the model made no tool call."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[{"name": tool_name, "input_schema": schema}],
        tool_choice={"type": "tool", "name": tool_name},
    )
    return _extract_tool_input(response)
