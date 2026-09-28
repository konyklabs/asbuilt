"""Tests for bench.llm's counting wrapper and D-013's budget stop condition,
including the full wiring through bench.run.main (the BLOCKING review
finding: --budget-tokens set an env var nothing read)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bench.llm import Budget, BudgetExceeded, CountingClient, budget_from_env
from bench.protocol import IngestReport
from tests._support import MINI_ROOT


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def _usage_response(input_tokens, output_tokens, cache_creation=0, cache_read=0):
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )
    return SimpleNamespace(usage=usage, content=[])


def test_counting_client_counts_tokens_and_calls():
    client = _FakeClient([_usage_response(100, 50), _usage_response(10, 5)])
    wrapped = CountingClient(client=client, arm="test-arm", model="test-model")
    wrapped.messages.create(prompt="a")
    wrapped.messages.create(prompt="b")
    assert wrapped.calls == 2
    assert wrapped.input_tokens == 110
    assert wrapped.output_tokens == 55
    assert wrapped.cache_tokens == 0


def test_counting_client_tracks_cache_creation_and_read_separately():
    client = _FakeClient([_usage_response(10, 5, cache_creation=100, cache_read=200)])
    wrapped = CountingClient(client=client, arm="a", model="m")
    wrapped.messages.create()
    assert wrapped.cache_creation_tokens == 100
    assert wrapped.cache_read_tokens == 200
    assert wrapped.cache_tokens == 300


def test_dollars_raises_on_missing_price_key():
    client = _FakeClient([_usage_response(1000, 1000)])
    wrapped = CountingClient(client=client, arm="a", model="m")
    wrapped.messages.create()
    with pytest.raises(KeyError):
        wrapped.dollars({"input": 1.0, "output": 1.0})  # missing cache_creation/cache_read


def test_dollars_prices_all_four_kinds_separately():
    client = _FakeClient(
        [_usage_response(1_000_000, 1_000_000, cache_creation=1_000_000, cache_read=1_000_000)]
    )
    wrapped = CountingClient(client=client, arm="a", model="m")
    wrapped.messages.create()
    prices = {"input": 1.0, "output": 2.0, "cache_creation": 3.0, "cache_read": 4.0}
    assert wrapped.dollars(prices) == pytest.approx(10.0)


def test_budget_stop_refuses_before_the_wrapped_client_is_called(tmp_path):
    """Usage already at the stop threshold (as if from an earlier call, set
    directly here to isolate the pre-call check from the post-call one):
    the next call must never reach the wrapped client at all."""
    client = _FakeClient([_usage_response(0, 0)])
    wrapped = CountingClient(
        client=client, arm="test-arm", model="m", budget=Budget(tokens=1000), stop_dir=tmp_path
    )
    wrapped.input_tokens = 900  # already at 90%

    with pytest.raises(BudgetExceeded):
        wrapped.messages.create()
    assert client.messages.calls == []  # never reached the fake client

    stop_path = tmp_path / "stop-test-arm.json"
    assert stop_path.is_file()
    data = json.loads(stop_path.read_text())
    assert data["arm"] == "test-arm"
    assert data["total_tokens"] == 900


def test_budget_stop_also_triggers_mid_call_when_that_call_crosses_the_line(tmp_path):
    """A call that itself pushes usage past the threshold (starting below
    it) is still caught, just after it runs rather than before."""
    client = _FakeClient([_usage_response(900, 0)])
    wrapped = CountingClient(
        client=client, arm="test-arm", model="m", budget=Budget(tokens=1000), stop_dir=tmp_path
    )
    with pytest.raises(BudgetExceeded):
        wrapped.messages.create()  # 900/1000 = 90% >= 80%, caught right after this call
    assert len(client.messages.calls) == 1  # the call itself did happen


def test_budget_from_env_reads_both_vars(monkeypatch):
    monkeypatch.setenv("ASBUILT_BUDGET_TOKENS", "5000")
    monkeypatch.setenv("ASBUILT_BUDGET_DOLLARS", "12.5")
    budget = budget_from_env()
    assert budget.tokens == 5000
    assert budget.dollars == 12.5


def test_budget_from_env_absent_is_empty(monkeypatch):
    monkeypatch.delenv("ASBUILT_BUDGET_TOKENS", raising=False)
    monkeypatch.delenv("ASBUILT_BUDGET_DOLLARS", raising=False)
    assert not budget_from_env()


def test_counting_client_uses_env_budget_when_none_given_explicitly(monkeypatch, tmp_path):
    monkeypatch.setenv("ASBUILT_BUDGET_TOKENS", "100")
    monkeypatch.delenv("ASBUILT_BUDGET_DOLLARS", raising=False)
    client = _FakeClient([_usage_response(90, 0)])
    wrapped = CountingClient(client=client, arm="a", model="m", stop_dir=tmp_path)
    with pytest.raises(BudgetExceeded):
        wrapped.messages.create()  # 90/100 = 90% >= 80%, from the env-derived budget


def test_missing_usage_is_estimated_not_zero_and_flagged(tmp_path):
    response_without_usage = SimpleNamespace(content=[SimpleNamespace(text="a" * 40)])
    client = _FakeClient([response_without_usage])
    wrapped = CountingClient(client=client, arm="a", model="m", stop_dir=tmp_path)
    wrapped.messages.create(prompt="b" * 20)
    assert wrapped.usage_missing is True
    assert wrapped.usage_missing_calls == 1
    assert wrapped.input_tokens > 0
    assert wrapped.output_tokens > 0


def test_dollar_budget_also_stops(tmp_path):
    client = _FakeClient([_usage_response(1_000_000, 0)])
    wrapped = CountingClient(
        client=client,
        arm="a",
        model="m",
        budget=Budget(dollars=1.0),
        prices={"input": 1.0, "output": 0.0, "cache_creation": 0.0, "cache_read": 0.0},
        stop_dir=tmp_path,
    )
    with pytest.raises(BudgetExceeded):
        wrapped.messages.create()  # $1.00 spent >= 80% of the $1.00 cap


def test_run_main_exits_nonzero_on_budget_exceeded(tmp_path, monkeypatch, capsys):
    """End-to-end: --budget-tokens on the CLI reaches a prototype's own
    CountingClient (via ASBUILT_BUDGET_TOKENS + budget_from_env), which
    raises BudgetExceeded, and main() turns that into exit 1 plus a message
    naming the stop file — the wiring the review flagged as missing."""

    class _BudgetBustingPrototype:
        name = "budget-busting"

        def ingest(self, fixture_root, entity_kinds, incremental=False):
            client = _FakeClient([_usage_response(900, 0)])
            wrapped = CountingClient(
                client=client, arm="budget-busting", model="m", stop_dir=tmp_path / "build"
            )
            wrapped.messages.create()  # env budget is 1000 -> 900/1000 = 90% -> raises
            return IngestReport(
                seconds=0.0, input_tokens=0, output_tokens=0, dollars=0.0, services=(), documents=0
            )

    import bench.run as run_module

    monkeypatch.setattr(run_module, "load_prototype", lambda name: _BudgetBustingPrototype())
    monkeypatch.chdir(tmp_path)

    exit_code = run_module.main(
        [
            "--prototype",
            "budget-busting",
            "--fixture",
            str(MINI_ROOT),
            "--out",
            str(tmp_path / "results.json"),
            "--budget-tokens",
            "1000",
        ]
    )

    assert exit_code == 1
    assert not (tmp_path / "results.json").exists()
    captured = capsys.readouterr()
    assert "STOPPED" in captured.out
    assert "stop-budget-busting.json" in captured.out
    assert (tmp_path / "build" / "stop-budget-busting.json").is_file()
