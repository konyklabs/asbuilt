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
tokens, elapsed wall-clock time. It enforces a token budget (dollars via a
per-model price table the caller supplies, ``dollars()``): at 80% of the
budget, the next call is refused before it runs, ``build/stop-<arm>.json``
is written with the counts so far, and ``BudgetExceeded`` is raised —
``bench/run.py`` turns that into a non-zero exit and a message telling the
operator to comment on the driving issue (D-013's stop condition).

``Embedder`` is the same counting shape for a separate embedding-call count,
wrapping ``client.embeddings.create(...)``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STOP_THRESHOLD = 0.8  # D-013: halt at 80% of the budget


class BudgetExceeded(RuntimeError):
    """Raised when the next call would push token usage past the stop
    threshold (80% of the budget, D-013) — before that call is made."""

    def __init__(self, arm: str, tokens_used: int, budget_tokens: int):
        self.arm = arm
        self.tokens_used = tokens_used
        self.budget_tokens = budget_tokens
        super().__init__(
            f"{arm}: token budget exceeded ({tokens_used}/{budget_tokens} tokens, "
            f">= {int(STOP_THRESHOLD * 100)}% stop threshold) — "
            "comment on the driving issue before continuing"
        )


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
    counting tokens and calls, and enforcing `budget_tokens` if given."""

    client: Any
    arm: str
    model: str
    budget_tokens: int | None = None
    stop_dir: Path = field(default_factory=lambda: Path("build"))

    calls: int = field(default=0, init=False)
    input_tokens: int = field(default=0, init=False)
    output_tokens: int = field(default=0, init=False)
    cache_tokens: int = field(default=0, init=False)
    elapsed_seconds: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.messages = _MessagesProxy(self)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_tokens

    def _over_threshold(self) -> bool:
        return (
            self.budget_tokens is not None
            and self.total_tokens >= STOP_THRESHOLD * self.budget_tokens
        )

    def _write_stop_file(self) -> Path:
        self.stop_dir.mkdir(parents=True, exist_ok=True)
        stop_path = self.stop_dir / f"stop-{self.arm}.json"
        stop_path.write_text(
            json.dumps(
                {
                    "arm": self.arm,
                    "model": self.model,
                    "calls": self.calls,
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                    "cache_tokens": self.cache_tokens,
                    "total_tokens": self.total_tokens,
                    "budget_tokens": self.budget_tokens,
                },
                indent=2,
            )
            + "\n"
        )
        return stop_path

    def _call(self, **kwargs: Any) -> Any:
        if self._over_threshold():
            self._write_stop_file()
            raise BudgetExceeded(self.arm, self.total_tokens, self.budget_tokens)

        started = time.perf_counter()
        response = self.client.messages.create(**kwargs)
        elapsed = time.perf_counter() - started

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        cache_tokens = (getattr(usage, "cache_creation_input_tokens", 0) or 0) + (
            getattr(usage, "cache_read_input_tokens", 0) or 0
        )

        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_tokens += cache_tokens
        self.elapsed_seconds += elapsed

        if self._over_threshold():
            self._write_stop_file()
            raise BudgetExceeded(self.arm, self.total_tokens, self.budget_tokens)

        return response

    def dollars(self, price_per_million: dict[str, float]) -> float:
        """`price_per_million` supplies this model's own {"input": $/1M,
        "output": $/1M, "cache": $/1M}; pricing is the caller's to know."""
        return (
            self.input_tokens * price_per_million.get("input", 0.0)
            + self.output_tokens * price_per_million.get("output", 0.0)
            + self.cache_tokens * price_per_million.get("cache", 0.0)
        ) / 1_000_000


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
