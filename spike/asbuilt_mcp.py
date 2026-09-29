"""The MCP adapter (D-013, asbuilt#9): a thin FastMCP server over any
`bench.protocol.Prototype`, so the invented Gearwell system can be queried
from a Claude Code session during the spike, and so a benchmark run's own
`--transcript` demonstrates the same tool contract a real ingest would serve
behind. `ASBUILT_ARM` selects the prototype (default `"null"` —
`bench.null.NullPrototype`; `"baseline"` — `prototypes.baseline.Prototype`;
later `"b_postgres"` — looked up the same way `bench.run.load_prototype`
is); `ASBUILT_FIXTURE` names the fixture root to ingest FROM (never an
already-assembled ingest root — this module assembles one itself, through
the fixture's last history step, exactly as `bench/run.py` does for a
benchmark run, so a person pointing a Claude Code session at `spike/`
(`ASBUILT_FIXTURE=.`) gets the same ingest-root-integrity behaviour a scored
run gets). Ingest is lazy: the first tool call triggers it, not server
startup, so importing this module (as the test suite does, via `create_app`)
never assembles anything on its own.

Tools: `search`, `explain` (an entity name), `entities` (a name lookup —
`bench.protocol.Prototype` has no first-class entity directory, so this is
derived: the distinct entity names appearing across `search(name)`'s own
returned facts, not a separate store query — a stated interpretation of the
driving task's "entities (name lookup)"), `contradictions`, `stale`, `ask`.
Every result carries `structuredContent` (the facts/sentences/contradictions
with their citations, JSON-serialised via `bench.run._to_jsonable`, which
already handles the protocol's dataclasses/enums/datetimes) and a text block
with the same content rendered as inline-cited lines, per D-013 ("every
answer cites"). `search`/`explain`/`contradictions`/`stale` paginate their
list result with `limit`/`offset` (default page `DEFAULT_PAGE_SIZE`, capped
at `MAX_PAGE_SIZE`); `ask` returns a single answer, not paginated. Invalid
arguments (empty required strings, out-of-range pagination) and a prototype
that raises are surfaced as MCP tool errors (`fastmcp.exceptions.ToolError`)
rather than a raw exception.

`uv sync --extra serve` installs `fastmcp` (pinned in `pyproject.toml`);
`.claude-plugin/plugin.json` and `.mcp.json` register this module as a
Claude Code plugin's MCP server (`uv run --project <spike> python
asbuilt_mcp.py`).

Named `asbuilt_mcp.py`, not `mcp.py` (the driving task's own suggestion):
`python <script>.py` puts the script's own directory FIRST on `sys.path`
before any of the script's own code runs, so a same-directory `mcp.py`
would shadow the real `mcp` package `fastmcp` itself imports
(`from mcp.server... import ...`) — confirmed by trying it (`ModuleNotFoundError:
No module named 'mcp.server'; 'mcp' is not a package`, since Python resolves
the import to this file instead of the site-packages one). Renaming is the
only fix available in-process; every other reference (`.mcp.json`,
`plugin.json`, the README) uses this name.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parent
if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))

from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from fastmcp.tools import ToolResult  # noqa: E402
from mcp.types import TextContent  # noqa: E402

from bench.build import Timeline  # noqa: E402
from bench.protocol import Category  # noqa: E402
from bench.run import ENTITY_KINDS, assemble_ingest_root  # noqa: E402
from bench.run import _to_jsonable as to_jsonable  # noqa: E402

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def load_prototype_from_env() -> Any:
    """Mirrors `bench.run.load_prototype`'s own lookup (`"null"` ->
    `bench.null.NullPrototype`; anything else -> `prototypes.<name>:
    Prototype`), read from `ASBUILT_ARM` rather than an argparse flag, since
    this module runs as a long-lived server, not a one-shot CLI."""
    arm = os.environ.get("ASBUILT_ARM", "null")
    if arm == "null":
        module = importlib.import_module("bench.null")
        return module.NullPrototype()
    module = importlib.import_module(f"prototypes.{arm}")
    return module.Prototype()


def _assemble_from_fixture(fixture_root: Path) -> Path:
    """Assembles an ingest root through the fixture's own last history
    step — the same integrity rule `bench/run.py` applies for a scored
    benchmark run (never the raw fixture handed to `ingest()` directly)."""
    timeline = Timeline(fixture_root)
    step = timeline.steps[-1].id
    ingest_root = fixture_root / "build" / "mcp-ingest"
    return assemble_ingest_root(fixture_root, step, ingest_root)


@dataclass
class _ServerState:
    """Lazy ingest (module docstring): the first tool call triggers it, not
    server construction — `fixture_root=None` (the test double's own case)
    skips fixture assembly entirely and trusts the injected prototype is
    already queryable (e.g. a stub primed with facts in its own
    constructor)."""

    prototype: Any
    fixture_root: Path | None = None
    _ingested: bool = field(default=False, init=False)

    def ensure_ingested(self) -> None:
        if self._ingested:
            return
        if self.fixture_root is not None:
            ingest_root = _assemble_from_fixture(self.fixture_root)
            self.prototype.ingest(ingest_root, ENTITY_KINDS)
        self._ingested = True


def _require_nonempty(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ToolError(f"{field_name!r} must not be empty")


def _validate_pagination(limit: int, offset: int) -> None:
    if limit <= 0:
        raise ToolError(f"limit must be positive, got {limit}")
    if limit > MAX_PAGE_SIZE:
        raise ToolError(f"limit must be at most {MAX_PAGE_SIZE}, got {limit}")
    if offset < 0:
        raise ToolError(f"offset must not be negative, got {offset}")


def _paginate(items: list[Any], limit: int, offset: int) -> tuple[list[Any], dict[str, Any]]:
    page = items[offset : offset + limit]
    return page, {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "returned": len(page),
    }


def _fact_line(fact: Any) -> str:
    citations = ", ".join(
        c.document + (f"#{c.location}" if c.location else "") for c in fact.citations
    )
    return f"- [{fact.tier.value}] {fact.statement} ({citations})"


def _facts_result(facts: list[Any], limit: int, offset: int) -> ToolResult:
    page, meta = _paginate(facts, limit, offset)
    text = "\n".join(_fact_line(f) for f in page) or "(no facts)"
    return ToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content={"facts": [to_jsonable(f) for f in page], "page": meta},
    )


def _sentence_line(sentence: Any) -> str:
    citations = ", ".join(
        c.document + (f"#{c.location}" if c.location else "") for c in sentence.citations
    )
    return f"{sentence.text} ({citations})" if citations else sentence.text


def create_app(
    prototype: Any,
    *,
    fixture_root: Path | None = None,
    name: str = "asbuilt",
) -> FastMCP:
    """Builds the FastMCP app over `prototype`. `fixture_root=None` (the
    default) leaves ingestion to the caller or to a prototype that's already
    primed — used by this module's own tests, which inject the null
    prototype and a stub double directly rather than assembling a real
    fixture."""
    app = FastMCP(name)
    state = _ServerState(prototype=prototype, fixture_root=fixture_root)

    @app.tool
    def search(
        query: str,
        category: str | None = None,
        since: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> ToolResult:
        """Free-text search over the ingested corpus, returning cited facts."""
        _require_nonempty(query, "query")
        _validate_pagination(limit, offset)
        state.ensure_ingested()
        cat = Category(category) if category else None
        when = datetime.fromisoformat(since) if since else None
        facts = state.prototype.search(query, category=cat, since=when)
        return _facts_result(facts, limit, offset)

    @app.tool
    def explain(name: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> ToolResult:
        """Every cited fact the ingested corpus holds about the named entity."""
        _require_nonempty(name, "name")
        _validate_pagination(limit, offset)
        state.ensure_ingested()
        facts = state.prototype.explain(name)
        return _facts_result(facts, limit, offset)

    @app.tool
    def entities(name: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> ToolResult:
        """Best-effort entity-name lookup (module docstring): the distinct
        entity names appearing across `search(name)`'s own returned facts —
        derived, since the Prototype protocol has no entity directory of
        its own."""
        _require_nonempty(name, "name")
        _validate_pagination(limit, offset)
        state.ensure_ingested()
        facts = state.prototype.search(name)
        names = sorted({entity for fact in facts for entity in fact.entities})
        page, meta = _paginate(names, limit, offset)
        text = "\n".join(f"- {n}" for n in page) or "(no entities found)"
        return ToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content={"entities": page, "page": meta},
        )

    @app.tool
    def contradictions(
        entity: str | None = None, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> ToolResult:
        """Contradicting fact pairs, optionally scoped to one named entity."""
        _validate_pagination(limit, offset)
        state.ensure_ingested()
        results = state.prototype.contradictions(entity)
        page, meta = _paginate(results, limit, offset)
        lines = []
        for c in page:
            winner = "a" if c.winner is c.a else ("b" if c.winner is c.b else "undecided")
            lines.append(
                f"- ({c.label}, winner={winner})\n  a: {_fact_line(c.a)}\n  b: {_fact_line(c.b)}"
            )
        text = "\n".join(lines) or "(no contradictions)"
        return ToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content={
                "contradictions": [
                    {
                        "a": to_jsonable(c.a),
                        "b": to_jsonable(c.b),
                        "label": c.label,
                        "winner": ("a" if c.winner is c.a else ("b" if c.winner is c.b else None)),
                    }
                    for c in page
                ],
                "page": meta,
            },
        )

    @app.tool
    def stale(since: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> ToolResult:
        """Facts whose supporting document looks stale as of `since` (an
        ISO date or datetime)."""
        _require_nonempty(since, "since")
        _validate_pagination(limit, offset)
        state.ensure_ingested()
        facts = state.prototype.stale(datetime.fromisoformat(since))
        return _facts_result(facts, limit, offset)

    @app.tool
    def ask(question: str) -> ToolResult:
        """A cited, sentence-level answer to a free-text question."""
        _require_nonempty(question, "question")
        state.ensure_ingested()
        answer = state.prototype.ask(question)
        text = "\n".join(_sentence_line(s) for s in answer.sentences) or "(no answer)"
        return ToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content={"sentences": [to_jsonable(s) for s in answer.sentences]},
        )

    return app


def main() -> None:
    prototype = load_prototype_from_env()
    fixture = os.environ.get("ASBUILT_FIXTURE")
    fixture_root = Path(fixture).resolve() if fixture else None
    app = create_app(prototype, fixture_root=fixture_root)
    app.run()


if __name__ == "__main__":
    main()
