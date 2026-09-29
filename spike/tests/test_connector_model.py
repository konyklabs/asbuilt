"""Tests for connectors.tests.extract_model's real-call path
(`extract_with_model`): the fake-`client_factory` wiring, call/token
counting, and `BudgetExceeded` surfacing the module's own docstring
promises but which had no test at all (asbuilt#8 review, point 4) — its
`dry_run` no-call promise is covered separately in
`tests/test_connector_tests.py::test_extract_model_dry_run_makes_no_call_and_counts_tokens`,
not duplicated here. The `anthropic`-path tests below use a fake
`client_factory`; the `claude-code` (default provider) tests further down
use a fake `claude` EXECUTABLE on `PATH` instead, since that provider talks
to a subprocess, not an SDK object — no real `claude -p` call is made
anywhere in this file."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.llm import Budget, BudgetExceeded
from connectors.tests.collect import Skeleton
from connectors.tests.extract_model import (
    ClaudeCodeClient,
    _claude_code_oauth_token,
    extract_with_model,
)


class _FakeMessages:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses: list) -> None:
        self.messages = _FakeMessages(responses)


def _tool_response(payload: dict, *, input_tokens: int, output_tokens: int) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    block = SimpleNamespace(type="tool_use", input=payload)
    return SimpleNamespace(usage=usage, content=[block])


def _skeleton(name: str = "test_x") -> Skeleton:
    return Skeleton(
        node_id=f"tests/x.py::{name}", file="tests/x.py", line=1, name=name, language="python"
    )


def test_extract_with_model_wires_fake_client_and_extracts_payload(tmp_path: Path):
    skeleton = _skeleton()
    payload = {
        "statement": "X is 1.",
        "category": "business-logic",
        "entities": ["x"],
        "claim": None,
    }
    client = _FakeClient([_tool_response(payload, input_tokens=42, output_tokens=17)])

    results, wrapped = extract_with_model(
        [skeleton], {}, client_factory=lambda: client, stop_dir=tmp_path
    )

    assert results == [{"node_id": skeleton.node_id, **payload}]
    assert client.messages.calls[0]["tools"][0]["name"] == "record_fact"
    assert client.messages.calls[0]["tool_choice"] == {"type": "tool", "name": "record_fact"}
    assert wrapped.input_tokens == 42
    assert wrapped.output_tokens == 17


def test_extract_with_model_counts_calls_and_tokens_across_skeletons(tmp_path: Path):
    skeletons = [_skeleton("test_a"), _skeleton("test_b")]
    payload = {"statement": "X.", "category": "business-logic", "entities": [], "claim": None}
    client = _FakeClient(
        [
            _tool_response(payload, input_tokens=10, output_tokens=5),
            _tool_response(payload, input_tokens=20, output_tokens=8),
        ]
    )

    results, wrapped = extract_with_model(
        skeletons, {}, client_factory=lambda: client, stop_dir=tmp_path
    )

    assert len(results) == 2
    assert wrapped.calls == 2
    assert wrapped.input_tokens == 30
    assert wrapped.output_tokens == 13


def test_extract_with_model_surfaces_budget_exceeded(tmp_path: Path):
    """A first call alone pushes spend to the 80% stop threshold (D-013) —
    `CountingClient` checks again after updating its counters, so the
    SECOND call is never attempted; `BudgetExceeded` propagates out of
    `extract_with_model` rather than being swallowed."""
    skeleton = _skeleton()
    payload = {"statement": "X.", "category": "business-logic", "entities": [], "claim": None}
    client = _FakeClient(
        [
            _tool_response(payload, input_tokens=900, output_tokens=0),
            _tool_response(payload, input_tokens=1, output_tokens=0),
        ]
    )
    budget = Budget(tokens=1000)

    with pytest.raises(BudgetExceeded):
        extract_with_model(
            [skeleton, skeleton],
            {},
            client_factory=lambda: client,
            budget=budget,
            stop_dir=tmp_path,
        )

    assert len(client.messages.calls) == 1  # the second call never happened
    assert (tmp_path / "stop-stack-b-model.json").is_file()


# --------------------------------------------------- claude-code provider

_FAKE_CLAUDE_SCRIPT = """#!/usr/bin/env python3
import json
import os
import sys

mode = os.environ.get("FAKE_CLAUDE_MODE", "success")

check_path = os.environ.get("FAKE_CLAUDE_TOKEN_CHECK_PATH")
expected = os.environ.get("FAKE_CLAUDE_EXPECTED_TOKEN")
if check_path and expected is not None:
    seen = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    with open(check_path, "w") as f:
        f.write("MATCH" if seen == expected else "NOMATCH")  # never the token itself

if mode == "fail":
    sys.stderr.write("simulated claude failure: rate limited\\n")
    sys.stderr.write("(a second stderr line that must never be surfaced)\\n")
    sys.exit(1)

if mode == "badjson":
    sys.stdout.write("not json at all")
    sys.exit(0)

structured = {
    "statement": "Skeleton is proven.",
    "category": "business-logic",
    "entities": ["farebox"],
    "claim": None,
}
result = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": json.dumps(structured),
    "total_cost_usd": 0.0042,
    "modelUsage": {
        "claude-sonnet-5": {
            "inputTokens": 123,
            "outputTokens": 45,
            "cacheReadInputTokens": 7,
            "cacheCreationInputTokens": 0,
        }
    },
}
sys.stdout.write(json.dumps(result))
"""


def _install_fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(_FAKE_CLAUDE_SCRIPT)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return script


def test_claude_code_client_wires_subprocess_and_parses_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The fake `claude` on PATH proves the whole round trip: the subprocess
    is actually found and invoked by bare name (not a hardcoded path), its
    `--output-format json` result's `result` field (a JSON string) is
    parsed into the schema-shaped dict `_extract_tool_input` reads, and its
    `modelUsage` is summed into `CountingClient`'s own token counters."""
    _install_fake_claude(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    skeleton = Skeleton(
        node_id="tests/x.py::test_x", file="tests/x.py", line=1, name="test_x", language="python"
    )

    results, wrapped = extract_with_model(
        [skeleton], {}, client_factory=ClaudeCodeClient, stop_dir=tmp_path
    )

    assert results == [
        {
            "node_id": "tests/x.py::test_x",
            "statement": "Skeleton is proven.",
            "category": "business-logic",
            "entities": ["farebox"],
            "claim": None,
        }
    ]
    assert wrapped.input_tokens == 123
    assert wrapped.output_tokens == 45
    assert wrapped.cache_read_tokens == 7


def test_claude_code_client_sends_oauth_token_from_env_without_exposing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`CLAUDE_CODE_OAUTH_TOKEN` reaches the subprocess's own env — checked
    only by equality inside the fake script, which writes back "MATCH" or
    "NOMATCH", never the token itself, to a side file this test reads."""
    _install_fake_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-test-token-do-not-print")
    check_path = tmp_path / "token-check.txt"
    monkeypatch.setenv("FAKE_CLAUDE_TOKEN_CHECK_PATH", str(check_path))
    monkeypatch.setenv("FAKE_CLAUDE_EXPECTED_TOKEN", "sk-test-token-do-not-print")
    skeleton = Skeleton(
        node_id="tests/x.py::test_x", file="tests/x.py", line=1, name="test_x", language="python"
    )

    extract_with_model([skeleton], {}, client_factory=ClaudeCodeClient, stop_dir=tmp_path)

    assert check_path.read_text() == "MATCH"


def test_claude_code_oauth_token_falls_back_to_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    token_file = tmp_path / "claude-code-oauth-token"
    token_file.write_text("file-token-do-not-print\n")
    monkeypatch.setattr("connectors.tests.extract_model._CLAUDE_CODE_TOKEN_FILE", token_file)

    assert _claude_code_oauth_token() == "file-token-do-not-print"


def test_claude_code_client_surfaces_nonzero_exit_as_stderr_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _install_fake_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    skeleton = Skeleton(
        node_id="tests/x.py::test_x", file="tests/x.py", line=1, name="test_x", language="python"
    )

    with pytest.raises(RuntimeError, match="simulated claude failure: rate limited"):
        extract_with_model([skeleton], {}, client_factory=ClaudeCodeClient, stop_dir=tmp_path)


def test_claude_code_client_surfaces_unparsable_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _install_fake_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "badjson")
    skeleton = Skeleton(
        node_id="tests/x.py::test_x", file="tests/x.py", line=1, name="test_x", language="python"
    )

    with pytest.raises(RuntimeError, match="unparsable JSON"):
        extract_with_model([skeleton], {}, client_factory=ClaudeCodeClient, stop_dir=tmp_path)
