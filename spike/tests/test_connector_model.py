"""Tests for connectors.tests.extract_model's real-call path
(`extract_with_model`): the fake-`client_factory` wiring, call/token
counting, and `BudgetExceeded` surfacing the module's own docstring
promises but which had no test at all (asbuilt#8 review, point 4) — its
`dry_run` no-call promise is covered separately in
`tests/test_connector_tests.py::test_extract_model_dry_run_makes_no_call_and_counts_tokens`,
not duplicated here."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.llm import Budget, BudgetExceeded
from connectors.tests.collect import Skeleton
from connectors.tests.extract_model import extract_with_model


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
