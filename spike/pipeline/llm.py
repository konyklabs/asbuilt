"""Model calls for the pipeline, all through one counting client (D-013:
"every model call counted through one wrapped client").

The provider is the benchmark's shared one, ``bench/claude_code.py``
(asbuilt#9): ``claude-code`` by default (one ``claude -p`` subprocess per
call on the owner's Claude Code subscription, ``ANTHROPIC_*`` and the cloud
backend selectors stripped from its environment), ``anthropic`` by opt-in
through the test connector's ``PROVIDERS`` table. ``structured_call`` here is
the pipeline's keyword-only front for ``bench.claude_code.structured_call``:
it takes the model from the counting client so every call in one arm uses
the arm's model (``bench.claude_code.DEFAULT_MODEL``, the same as every other
arm); the CLI takes no temperature, so none is set on either path.

No real call is made in this repository's tests: they hand in a fake client
factory or put a fake ``claude`` on ``PATH``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bench.claude_code import DEFAULT_MODEL
from bench.claude_code import structured_call as _structured_call
from bench.llm import CountingClient
from connectors.tests.extract_model import PRICE_TABLE, PROVIDERS
from pipeline.store import StoredFact


def make_client(
    arm: str,
    *,
    model: str = DEFAULT_MODEL,
    provider: str = "claude-code",
    client_factory: Callable[[], Any] | None = None,
    stop_dir: Path | None = None,
) -> CountingClient:
    factory = client_factory or PROVIDERS[provider]
    kwargs: dict[str, Any] = {}
    if stop_dir is not None:
        kwargs["stop_dir"] = stop_dir
    return CountingClient(
        client=factory(), arm=arm, model=model, prices=PRICE_TABLE.get(model), **kwargs
    )


def structured_call(
    client: CountingClient,
    *,
    prompt: str,
    schema: dict[str, Any],
    system: str,
    tool_name: str,
    max_tokens: int = 2000,
) -> dict[str, Any] | None:
    """``bench.claude_code.structured_call`` with the model taken from the
    counting client (module docstring)."""
    return _structured_call(
        client,
        system,
        prompt,
        schema,
        model=client.model,
        max_tokens=max_tokens,
        tool_name=tool_name,
    )


VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["refutes", "supports", "unrelated"]},
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
}
VERDICT_SYSTEM = (
    "You judge whether two statements about one software system can both be true "
    "at the same time. Answer refutes only when they cannot; supports when one "
    "implies the other; unrelated otherwise. One short reason."
)


def _describe(fact: StoredFact) -> str:
    cites = ", ".join(c.document for c in fact.citations[:3])
    when = fact.valid_at.isoformat() if fact.valid_at else "unknown"
    return f"{fact.statement} (tier {fact.tier}; stated from {when}; cites {cites})"


class ModelJudge:
    """The prose verdict through the counting client (``contradict.Judge``)."""

    def __init__(self, client: CountingClient) -> None:
        self.client = client

    def verdict(self, a: StoredFact, b: StoredFact) -> tuple[str, str]:
        prompt = "\n".join(["Statement A: " + _describe(a), "Statement B: " + _describe(b)])
        payload = structured_call(
            self.client,
            prompt=prompt,
            schema=VERDICT_SCHEMA,
            system=VERDICT_SYSTEM,
            tool_name="record_verdict",
            max_tokens=200,
        )
        if not payload:
            return "unrelated", "no structured verdict returned"
        label = str(payload.get("label", "unrelated"))
        return (label if label in ("refutes", "supports") else "unrelated"), str(
            payload.get("reason", "")
        )


def prompt_tokens(*texts: str) -> int:
    """The dry-run estimate every harness module uses: len(text) // 4."""
    return sum(len(t) for t in texts) // 4


def schema_text(schema: dict[str, Any]) -> str:
    return json.dumps(schema, separators=(",", ":"))
