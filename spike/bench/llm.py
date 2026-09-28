"""A counting wrapper for model calls, shared by every benchmark arm (D-013).

``CountingClient`` wraps a client-like object exposing a ``messages.create``
call (the Anthropic Messages API shape: ``client.messages.create(**kwargs)``
returning something with ``.usage.input_tokens``/``.output_tokens`` and
optionally ``.cache_creation_input_tokens``/``.cache_read_input_tokens``).
It is provider-agnostic on purpose: no vendor SDK is imported here, at
module level or anywhere else — the caller constructs its own client (however
it authenticates, whatever provider) and hands it in. The wrapper itself
exposes the identical ``.messages.create(...)`` shape, so it drops in
anywhere the raw client was used.

It records, across every call: count, input tokens, output tokens, cache
tokens (creation and read counted, and priced, separately), elapsed
wall-clock time. If a response has no ``.usage`` at all, its tokens are
estimated (``len(text) // 4`` of the request's ``kwargs`` and of whatever
text can be pulled from the response) rather than counted as zero, and
``usage_missing`` is set — a silently-zero call would otherwise let real
usage hide under a budget that looks unspent.

Budget (D-013's stop condition): a token cap, a dollar cap, or both.
``budget_from_env()`` reads ``ASBUILT_BUDGET_TOKENS``/``ASBUILT_BUDGET_DOLLARS``
(set by ``bench/run.py --budget-tokens``/``--budget-dollars``);
``CountingClient`` uses it automatically when constructed with no explicit
``budget=``. Before every call, if tokens or dollars spent *so far* are
already at 80% of their cap, the call is refused, ``build/stop-<arm>.json``
is written with the counts, and ``BudgetExceeded`` is raised — checked again
after the call updates the counters, so a single call that itself crosses
the line is also caught. ``bench/run.py`` turns ``BudgetExceeded`` into a
non-zero exit and a message telling the operator to comment on the driving
issue. A dollar budget needs a price table (``prices=`` at construction, or
passed to ``dollars()`` directly); ``dollars()`` raises if a needed price key
is missing rather than pricing that token kind at $0.

``Embedder`` is the same counting shape for a separate embedding-call count,
wrapping ``client.embeddings.create(...)``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STOP_THRESHOLD = 0.8  # D-013: halt at 80% of the budget
PRICE_KEYS = ("input", "output", "cache_creation", "cache_read")


class BudgetExceeded(RuntimeError):
    """Raised when the next call would push spend past the stop threshold
    (80% of the budget, D-013) — before that call is made."""

    def __init__(self, arm: str, reason: str):
        self.arm = arm
        self.reason = reason
        super().__init__(
            f"{arm}: budget exceeded ({reason}, >= {int(STOP_THRESHOLD * 100)}% stop "
            "threshold) — comment on the driving issue before continuing"
        )


@dataclass(frozen=True)
class Budget:
    tokens: int | None = None
    dollars: float | None = None

    def __bool__(self) -> bool:
        return self.tokens is not None or self.dollars is not None


def budget_from_env() -> Budget:
    """ASBUILT_BUDGET_TOKENS / ASBUILT_BUDGET_DOLLARS from the environment
    (bench/run.py's --budget-tokens/--budget-dollars set these); either,
    both, or neither may be present."""
    tokens_raw = os.environ.get("ASBUILT_BUDGET_TOKENS")
    dollars_raw = os.environ.get("ASBUILT_BUDGET_DOLLARS")
    return Budget(
        tokens=int(tokens_raw) if tokens_raw else None,
        dollars=float(dollars_raw) if dollars_raw else None,
    )


def _estimate_tokens(request_text: str, response_text: str) -> tuple[int, int]:
    return (len(request_text) // 4, len(response_text) // 4)


def _response_text(response: Any) -> str:
    content = getattr(response, "content", None) or []
    parts = [t for block in content if (t := getattr(block, "text", None))]
    return "".join(parts) if parts else str(response)


class _MessagesProxy:
    """Exposes `.create(...)`, mirroring the wrapped client's `.messages`
    attribute, so `CountingClient` itself is a drop-in replacement."""

    def __init__(self, owner: CountingClient):
        self._owner = owner

    def create(self, **kwargs: Any) -> Any:
        return self._owner._call(**kwargs)


@dataclass
class CountingClient:
    """Wraps `client` (anything with a `.messages.create(**kwargs)` call),
    counting tokens and calls, and enforcing `budget` (default:
    `budget_from_env()`) if given."""

    client: Any
    arm: str
    model: str
    budget: Budget | None = None
    prices: dict[str, float] | None = None
    stop_dir: Path = field(default_factory=lambda: Path("build"))

    calls: int = field(default=0, init=False)
    input_tokens: int = field(default=0, init=False)
    output_tokens: int = field(default=0, init=False)
    cache_creation_tokens: int = field(default=0, init=False)
    cache_read_tokens: int = field(default=0, init=False)
    elapsed_seconds: float = field(default=0.0, init=False)
    usage_missing_calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.budget is None:
            self.budget = budget_from_env()
        self.messages = _MessagesProxy(self)

    @property
    def cache_tokens(self) -> int:
        return self.cache_creation_tokens + self.cache_read_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_tokens

    @property
    def usage_missing(self) -> bool:
        return self.usage_missing_calls > 0

    def dollars(self, price_per_million: dict[str, float] | None = None) -> float:
        """Raises if a needed price key is missing — never silently prices
        a token kind at $0."""
        prices = price_per_million if price_per_million is not None else self.prices
        if prices is None:
            raise ValueError(f"{self.arm}: no price table given (dollars() or the constructor)")
        missing = [k for k in PRICE_KEYS if k not in prices]
        if missing:
            raise KeyError(f"{self.arm}: price table missing {missing}")
        return (
            self.input_tokens * prices["input"]
            + self.output_tokens * prices["output"]
            + self.cache_creation_tokens * prices["cache_creation"]
            + self.cache_read_tokens * prices["cache_read"]
        ) / 1_000_000

    def _over_threshold(self) -> str | None:
        """Returns a human-readable reason if spend so far is already at the
        stop threshold, else None."""
        if not self.budget:
            return None
        if (
            self.budget.tokens is not None
            and self.total_tokens >= STOP_THRESHOLD * self.budget.tokens
        ):
            return f"{self.total_tokens}/{self.budget.tokens} tokens"
        if self.budget.dollars is not None:
            spent = self.dollars()
            if spent >= STOP_THRESHOLD * self.budget.dollars:
                return f"${spent:.4f}/${self.budget.dollars:.2f}"
        return None

    def _write_stop_file(self, reason: str) -> Path:
        self.stop_dir.mkdir(parents=True, exist_ok=True)
        stop_path = self.stop_dir / f"stop-{self.arm}.json"
        stop_path.write_text(
            json.dumps(
                {
                    "arm": self.arm,
                    "model": self.model,
                    "reason": reason,
                    "calls": self.calls,
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                    "cache_creation_tokens": self.cache_creation_tokens,
                    "cache_read_tokens": self.cache_read_tokens,
                    "total_tokens": self.total_tokens,
                    "budget_tokens": self.budget.tokens if self.budget else None,
                    "budget_dollars": self.budget.dollars if self.budget else None,
                    "usage_missing_calls": self.usage_missing_calls,
                },
                indent=2,
            )
            + "\n"
        )
        return stop_path

    def _check_and_maybe_stop(self) -> None:
        reason = self._over_threshold()
        if reason is not None:
            self._write_stop_file(reason)
            raise BudgetExceeded(self.arm, reason)

    def _call(self, **kwargs: Any) -> Any:
        self._check_and_maybe_stop()

        started = time.perf_counter()
        response = self.client.messages.create(**kwargs)
        elapsed = time.perf_counter() - started

        usage = getattr(response, "usage", None)
        if usage is None:
            self.usage_missing_calls += 1
            input_tokens, output_tokens = _estimate_tokens(str(kwargs), _response_text(response))
            cache_creation = cache_read = 0
        else:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_creation_tokens += cache_creation
        self.cache_read_tokens += cache_read
        self.elapsed_seconds += elapsed

        self._check_and_maybe_stop()
        return response


@dataclass
class Embedder:
    """The same counting shape for embedding calls: wraps `client`'s
    `.embeddings.create(**kwargs)`, no budget enforcement of its own (an
    embedder's tokens fold into the ingest report's `embedding_tokens`,
    which the caller may still weigh against a shared budget itself)."""

    client: Any
    model: str

    calls: int = field(default=0, init=False)
    embedding_tokens: int = field(default=0, init=False)

    def create(self, **kwargs: Any) -> Any:
        response = self.client.embeddings.create(**kwargs)
        usage = getattr(response, "usage", None)
        tokens = (getattr(usage, "total_tokens", None) or getattr(usage, "prompt_tokens", 0)) or 0
        self.calls += 1
        self.embedding_tokens += tokens
        return response
