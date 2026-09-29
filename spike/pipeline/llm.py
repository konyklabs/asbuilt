"""Model calls for the pipeline, all through one counting client (D-013:
"every model call counted through one wrapped client").

The provider is the test connector's: ``claude-code`` by default (one
``claude -p`` subprocess per call on the owner's Claude Code subscription,
``ANTHROPIC_*`` stripped from its environment — ``connectors/tests/
extract_model.py``), ``anthropic`` by opt-in. ``structured_call`` sends a
prompt with a JSON schema (as the first tool's ``input_schema``, which the
claude-code provider passes as ``--json-schema``) and returns the
schema-shaped dict, or None when the call returned nothing usable. Same model
as every other arm (``extract_model.DEFAULT_MODEL``); the CLI takes no
temperature, so none is set on either path.

No real call is made in this repository's tests: they hand in a fake client
factory or put a fake ``claude`` on ``PATH``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bench.llm import CountingClient
from connectors.tests.extract_model import DEFAULT_MODEL, PRICE_TABLE, PROVIDERS
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
    response = client.messages.create(
        model=client.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[{"name": tool_name, "input_schema": schema}],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            payload = getattr(block, "input", None)
            return payload if isinstance(payload, dict) else None
    return None


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
