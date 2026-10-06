"""Tests for `bench.claude_code._invoke_claude_code`'s subprocess wiring
(asbuilt#9 review): the prompt travels over stdin, never argv, a large
(~500 KB) prompt proves it structurally (no argv element carries it — the
real bug this guards was Linux's ~128 KB per-argument cap, which macOS
tolerates, so a size-based assertion is the only OS-independent way to
catch a regression back to `-p <prompt>`); `--strict-mcp-config` is always
passed; a call that outruns its `timeout` raises `RuntimeError`, not
`subprocess.TimeoutExpired`; a result with no `modelUsage` yields `usage=
None` (not a zero-filled stand-in), so `bench.llm.CountingClient`'s own
missing-usage guard fires; every `CLAUDE_CODE_USE_*`/`AWS_BEARER_TOKEN_
BEDROCK` variable is stripped from the child env, alongside `ANTHROPIC_*`
(stack-B review). No real `claude -p` call — a fake `claude` executable on
`PATH`, as every other test in this repo uses."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from bench.claude_code import (
    DEFAULT_MAX_TURNS,
    ClaudeCodeClient,
    _failure_reason,
    _invoke_claude_code,
    schema_union_types,
    structured_call,
)
from bench.llm import CountingClient

_ECHO_STDIN_SCRIPT = r"""#!/usr/bin/env python3
import json
import os
import sys

stdin_data = sys.stdin.read()
argv_max_len = max((len(a) for a in sys.argv), default=0)

args_path = os.environ.get("FAKE_CLAUDE_ARGS_PATH")
if args_path:
    with open(args_path, "w") as f:
        json.dump(sys.argv, f)

result = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "",
    "structured_output": {"stdin_len": len(stdin_data), "argv_max_len": argv_max_len},
    "modelUsage": {},
}
sys.stdout.write(json.dumps(result))
"""

_SLEEP_SCRIPT = r"""#!/usr/bin/env python3
import sys
import time

sys.stdin.read()  # drain, so the parent's write never blocks
time.sleep(5)
"""

_NO_MODEL_USAGE_SCRIPT = r"""#!/usr/bin/env python3
import json
import sys

sys.stdin.read()

result = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "ok",
    "structured_output": {"facts": []},
    # Deliberately no "modelUsage" key at all.
}
sys.stdout.write(json.dumps(result))
"""

_ENV_LEAK_SCRIPT = r"""#!/usr/bin/env python3
import json
import os
import sys

sys.stdin.read()

check_path = os.environ.get("FAKE_CLAUDE_ENV_CHECK_PATH")
if check_path:
    leaked = sorted(
        k
        for k in os.environ
        if k.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_")) or k == "AWS_BEARER_TOKEN_BEDROCK"
    )
    with open(check_path, "w") as f:
        f.write(",".join(leaked))  # names only, never any value

result = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "",
    "structured_output": {},
    "modelUsage": {"claude-sonnet-5": {"inputTokens": 1, "outputTokens": 1}},
}
sys.stdout.write(json.dumps(result))
"""


def _install_fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    claude_path = bin_dir / "claude"
    claude_path.write_text(script)
    claude_path.chmod(claude_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("ASBUILT_RETRY_PAUSE", "0")  # asbuilt#21: no 5 s pause in tests
    monkeypatch.setenv("ASBUILT_FAILURE_DIR", str(tmp_path / "failures"))  # never spike/build/
    return claude_path


def test_large_prompt_travels_over_stdin_not_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _install_fake_claude(tmp_path, monkeypatch, _ECHO_STDIN_SCRIPT)
    huge_prompt = "x" * 500_000  # ~500 KB — over Linux's ~128 KB per-argv-element cap

    response = _invoke_claude_code(huge_prompt, "claude-sonnet-5", schema=None, system_prompt="sys")

    payload = response.content[0].input
    assert payload["stdin_len"] == len(huge_prompt)
    assert payload["argv_max_len"] < 1_000  # no argv element carries anything corpus-sized


def test_strict_mcp_config_and_no_inline_prompt_are_always_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    args_path = tmp_path / "args.json"
    monkeypatch.setenv("FAKE_CLAUDE_ARGS_PATH", str(args_path))
    _install_fake_claude(tmp_path, monkeypatch, _ECHO_STDIN_SCRIPT)

    _invoke_claude_code("a prompt", "claude-sonnet-5", schema=None, system_prompt="sys")

    argv = json.loads(args_path.read_text())
    assert "--strict-mcp-config" in argv
    assert argv[1] == "-p"
    assert "a prompt" not in argv  # the prompt is never one of the argv elements
    # asbuilt#23: four turns, not one — the structured-output tool call may
    # follow a sentence of prose, and a schema-invalid answer is bounced back
    assert argv[argv.index("--max-turns") + 1] == "4"
    assert DEFAULT_MAX_TURNS == 4


def test_the_client_path_passes_the_same_turn_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The path that failed on the real run goes through `ClaudeCodeClient`,
    whose own default must reach the argv (a lens-round note: the direct
    call's default alone could regress with the suite green)."""
    args_path = tmp_path / "args.json"
    monkeypatch.setenv("FAKE_CLAUDE_ARGS_PATH", str(args_path))
    _install_fake_claude(tmp_path, monkeypatch, _ECHO_STDIN_SCRIPT)

    ClaudeCodeClient().messages.create(
        model="claude-sonnet-5", messages=[{"role": "user", "content": "a prompt"}]
    )
    argv = json.loads(args_path.read_text())
    assert argv[argv.index("--max-turns") + 1] == str(DEFAULT_MAX_TURNS)

    args_path.unlink()
    ClaudeCodeClient(max_turns=6).messages.create(
        model="claude-sonnet-5", messages=[{"role": "user", "content": "a prompt"}]
    )
    argv = json.loads(args_path.read_text())
    assert argv[argv.index("--max-turns") + 1] == "6"


def test_timeout_raises_runtime_error_not_a_raw_timeout_expired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _install_fake_claude(tmp_path, monkeypatch, _SLEEP_SCRIPT)

    with pytest.raises(RuntimeError, match="timed out"):
        _invoke_claude_code(
            "prompt", "claude-sonnet-5", schema=None, system_prompt="sys", timeout=0.2
        )


def test_failure_reason_reads_stderr_then_the_result_objects_errors_then_result_then_subtype():
    """asbuilt#21: what a failed call said, one line, in that order. The
    installed CLI reports a non-success subtype's message under `errors`
    and uses `result` only on the success variant (an API error is
    success + is_error + api_error_status + result)."""
    execution = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "errors": ["Execution failed\nmore"],
        }
    )
    api = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": 429,
            "result": "Rate limit reached\nmore",
        }
    )
    assert _failure_reason(1, execution, "boom\nmore") == "claude -p exited 1: boom"
    assert _failure_reason(1, execution, "") == "claude -p exited 1: Execution failed"
    assert _failure_reason(1, api, "") == "claude -p exited 1: Rate limit reached"
    assert _failure_reason(0, api, "") == "claude -p returned an error: Rate limit reached"
    only_subtype = json.dumps({"subtype": "error_max_turns", "errors": []})
    assert _failure_reason(1, only_subtype, "") == "claude -p exited 1: error_max_turns"
    # the success variant flagged is_error with a placeholder text: say what
    # it is, never "success"
    blank_api = json.dumps(
        {"subtype": "success", "is_error": True, "api_error_status": 529, "result": ""}
    )
    assert _failure_reason(1, blank_api, "") == "claude -p exited 1: API error 529"
    no_status = json.dumps(
        {"subtype": "success", "is_error": True, "api_error_status": None, "result": ""}
    )
    assert _failure_reason(1, no_status, "") == "claude -p exited 1: API error"
    assert _failure_reason(2, "not json\nmore", "  \n") == "claude -p exited 2: not json"
    assert _failure_reason(3, "", "") == "claude -p exited 3 with no output"


def test_timeout_is_retried_once_when_asked_and_then_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _install_fake_claude(tmp_path, monkeypatch, _SLEEP_SCRIPT)
    retries: list[int] = []

    with pytest.raises(RuntimeError, match=r"timed out after 0.2s \(after 1 retry\)"):
        _invoke_claude_code(
            "prompt",
            "claude-sonnet-5",
            schema=None,
            system_prompt="sys",
            timeout=0.2,
            max_retries=1,
            retry_pause=0,
            on_retry=lambda: retries.append(1),
        )
    assert retries == [1]


def test_no_model_usage_yields_none_usage_not_a_zero_filled_stand_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Stack-B review: a result with no `modelUsage` must produce `usage=
    None`, not a zero-filled `SimpleNamespace` that would look like genuine
    zero-token usage to `bench.llm.CountingClient`."""
    _install_fake_claude(tmp_path, monkeypatch, _NO_MODEL_USAGE_SCRIPT)

    response = _invoke_claude_code("prompt", "claude-sonnet-5", schema=None, system_prompt="sys")

    assert response.usage is None


def test_missing_usage_trips_countingclient_usage_missing_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """End to end through `CountingClient` (not just `_invoke_claude_code`
    in isolation): a `None` usage must actually set `usage_missing` and
    estimate tokens from text length, rather than counting a real call as
    zero-cost."""
    from bench.claude_code import ClaudeCodeClient

    _install_fake_claude(tmp_path, monkeypatch, _NO_MODEL_USAGE_SCRIPT)
    wrapped = CountingClient(client=ClaudeCodeClient(), arm="test", model="claude-sonnet-5")

    structured_call(wrapped, "system", "a prompt long enough to estimate", {"type": "object"})

    assert wrapped.usage_missing is True
    assert wrapped.usage_missing_calls == 1
    assert wrapped.calls == 1
    assert wrapped.input_tokens > 0  # estimated from text length, not zeroed


def test_bedrock_vertex_foundry_env_vars_are_stripped_from_the_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
    monkeypatch.setenv("CLAUDE_CODE_USE_FOUNDRY", "1")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "leaked-if-this-test-fails")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "also-leaked-if-this-test-fails")
    check_path = tmp_path / "env-check.txt"
    monkeypatch.setenv("FAKE_CLAUDE_ENV_CHECK_PATH", str(check_path))
    _install_fake_claude(tmp_path, monkeypatch, _ENV_LEAK_SCRIPT)

    _invoke_claude_code("prompt", "claude-sonnet-5", schema=None, system_prompt="sys")

    assert check_path.read_text() == ""  # no stripped name survived into the child


def test_a_union_of_non_null_types_is_refused_before_any_process_is_spawned(tmp_path: Path):
    """konyklabs/roadmap#154, 2026-10-02: stack B's first model run died
    inside the CLI on `strict mode: use allowUnionTypes ...`, after one paid
    retry. The guard turns that into a ValueError at the call site, before a
    process exists: `claude_bin` here does not exist, so a spawn would fail
    differently (and later). Ajv's strict mode allows the nullable form, so
    `[T, "null"]` arrays pass the guard unchanged and anyOf passes too."""
    schema = {
        "type": "object",
        "properties": {
            "claim": {
                "type": ["object", "null"],  # allowed: a union with null only
                "properties": {"v": {"type": ["number", "string"]}},  # prohibited
            }
        },
    }
    expected = r"anyOf.*#/properties/claim/properties/v/type"
    with pytest.raises(ValueError, match=expected):
        _invoke_claude_code(
            "p",
            "claude-sonnet-5",
            claude_bin=str(tmp_path / "no-such-claude"),
            schema=schema,
            system_prompt="sys",
        )
    assert schema_union_types(schema) == ["#/properties/claim/properties/v/type"]
    assert schema_union_types({"type": ["number", "string", "null"]}) == ["#/type"]
    assert schema_union_types({"type": ["string", "null"]}) == []
    assert schema_union_types({"anyOf": [{"type": "number"}, {"type": "string"}]}) == []


def test_every_schema_the_spike_hands_the_cli_passes_ajv_strict_mode():
    """Each arm and connector builds its own schema; one of them (stack B)
    had a `["number", "string"]` value while the others only had nullable
    unions, which is why the extractor and baseline runs worked and the
    stack-B run did not. Every schema that reaches `--json-schema` is checked
    here, and the stack-B claim keeps its shape: an object or null, with a
    number-or-string value."""
    from connectors.tests.extract_model import SCHEMA as connector_schema
    from pipeline.llm import VERDICT_SCHEMA
    from prototypes.b_postgres.extract import build_schema
    from prototypes.baseline import FACTS_SCHEMA

    b_schema = build_schema(("table", "endpoint", "rule"))
    schemas = {
        "connectors.tests.extract_model.SCHEMA": connector_schema,
        "pipeline.llm.VERDICT_SCHEMA": VERDICT_SCHEMA,
        "prototypes.baseline.FACTS_SCHEMA": FACTS_SCHEMA,
        "prototypes.b_postgres.extract.build_schema": b_schema,
    }
    assert {name: schema_union_types(s) for name, s in schemas.items()} == {
        name: [] for name in schemas
    }

    claim = b_schema["properties"]["facts"]["items"]["properties"]["claim"]
    assert claim["type"] == ["object", "null"]
    assert claim["required"] == ["entity", "attribute", "value"]
    assert claim["properties"]["value"] == {"anyOf": [{"type": "number"}, {"type": "string"}]}


_MAX_TURNS_SCRIPT = r"""#!/usr/bin/env python3
import json
import sys

sys.stdin.read()
# The installed CLI's shape for a turn-capped call: exit 1, the reason under
# `errors`, the last assistant text under `result` (asbuilt#21 read the binary).
result = {
    "type": "result",
    "subtype": "error_max_turns",
    "is_error": True,
    "num_turns": 4,
    "errors": ["Reached maximum number of turns (4)"],
    "result": "I will now extract the facts for this entity. Here is what the documents say:",
    "modelUsage": {"claude-sonnet-5": {"inputTokens": 9, "outputTokens": 2}},
}
sys.stdout.write(json.dumps(result))
sys.exit(1)
"""


def test_a_failed_call_keeps_the_clis_result_object_on_disk_and_names_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """konyklabs/roadmap#154, 2026-10-06: the first baseline model run ended
    on `Reached maximum number of turns (4)` and nothing recorded what the
    model had been doing across those turns. Now the whole result object
    (its `result` text, `num_turns`, usage) is written under
    ASBUILT_FAILURE_DIR, the error names the file, and the prompt itself is
    not in it (only its size)."""
    _install_fake_claude(tmp_path, monkeypatch, _MAX_TURNS_SCRIPT)
    secret_prompt = "the corpus, which must not be copied into a failure file: xyzzy-7"

    expected = r"maximum number of turns.*result object is in "
    with pytest.raises(RuntimeError, match=expected) as info:
        _invoke_claude_code(secret_prompt, "claude-sonnet-5", schema=None, system_prompt="sys")

    path = Path(str(info.value).rsplit(" is in ", 1)[1].rstrip(")"))
    assert path.parent == tmp_path / "failures" and path.is_file()
    kept = json.loads(path.read_text())
    assert kept["result"]["subtype"] == "error_max_turns"
    assert kept["result"]["num_turns"] == 4
    assert kept["result"]["result"].startswith("I will now extract")
    assert kept["prompt_chars"] == len(secret_prompt)
    assert "xyzzy-7" not in path.read_text()
