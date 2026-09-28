"""Runs one prototype against the fixed query mix and writes raw results.

CLI: ``uv run python bench/run.py --prototype null [--fixture .]
[--out build/results-null.json]``.

Prototype lookup: ``--prototype null`` loads ``bench.null:NullPrototype``.
Any other name ``X`` loads ``prototypes.X:Prototype``, importable from
``spike/prototypes/X/__init__.py`` exposing a class named ``Prototype`` that
implements ``bench.protocol.Prototype`` (see that module's docstring for the
document-id conventions every prototype must honour).

``queries/mix.yaml`` shape (this harness's own contract; there is no
SCHEMA.md for it, only ``truth/SCHEMA.md`` for facts/entities/contradictions/
stale — see ``spike/README.md``):

    weights:
      explain: 40
      search: 25
      ask: 15
      contradictions: 10
      stale: 10
    queries:
      - id: q-explain-01
        surface: explain
        entity: E-...
      - id: q-search-01
        surface: search
        query: "free text"
        category: business-logic   # optional
        since: null                 # optional ISO datetime
        expects: [F-001, F-002]     # truth fact ids
      - id: q-ask-01
        surface: ask
        question: "..."
        expects: [F-001]
      - id: q-contradictions-01
        surface: contradictions
        entity: E-...                # optional; omitted/null = every contradiction
      - id: q-stale-01
        surface: stale
        since: "2026-01-15T00:00:00-05:00"

``explain`` and ``contradictions`` have no ``expects``: the scorer derives
expected results from ``truth/`` itself (facts naming the entity; planted
contradictions naming the entity, or every one if omitted). ``search``,
``ask`` and ``stale`` need an explicit ``expects``/``since`` because there is
no other way to know which facts a free-text query or a time cutoff should
surface. ``since`` may be date-only or a full ISO datetime with an offset;
the scorer compares it against history-step dates (which do carry an offset)
by dropping the offset from both sides whenever one of them is naive, so a
date-only cutoff still works (see ``bench/score.py``'s ``_comparable``).

Output: a JSON file with the prototype's ``ingest`` report and, per query,
its wall-clock latency in milliseconds and its raw (serialised) result.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import sys
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))

import yaml  # noqa: E402

from bench.protocol import Category  # noqa: E402


class RunError(RuntimeError):
    pass


def load_prototype(name: str):
    if name == "null":
        module = importlib.import_module("bench.null")
        return module.NullPrototype()
    module = importlib.import_module(f"prototypes.{name}")
    return module.Prototype()


def _to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def load_mix(queries_path: Path) -> dict[str, Any]:
    if not queries_path.is_file():
        raise RunError(f"no query mix at {queries_path}")
    mix = yaml.safe_load(queries_path.read_text()) or {}
    mix.setdefault("weights", {})
    mix.setdefault("queries", [])
    return mix


def run_query(prototype: Any, query: dict[str, Any]) -> dict[str, Any]:
    surface = query["surface"]
    started = time.perf_counter()

    if surface == "explain":
        result = prototype.explain(query["entity"])
    elif surface == "search":
        category = Category(query["category"]) if query.get("category") else None
        result = prototype.search(
            query["query"],
            category=category,
            since=_parse_datetime(query.get("since")),
        )
    elif surface == "ask":
        result = prototype.ask(query["question"])
    elif surface == "contradictions":
        result = prototype.contradictions(query.get("entity"))
    elif surface == "stale":
        since = _parse_datetime(query["since"])
        result = prototype.stale(since)
    else:
        raise RunError(f"unknown query surface {surface!r} in query {query.get('id')!r}")

    latency_ms = (time.perf_counter() - started) * 1000

    return {
        "id": query.get("id"),
        "surface": surface,
        "latency_ms": latency_ms,
        "params": {k: v for k, v in query.items() if k not in ("id", "surface")},
        "result": _to_jsonable(result),
    }


def run(fixture_root: Path, prototype_name: str) -> dict[str, Any]:
    prototype = load_prototype(prototype_name)
    ingest_report = prototype.ingest(fixture_root)
    mix = load_mix(fixture_root / "queries" / "mix.yaml")

    queries_out = [run_query(prototype, query) for query in mix["queries"]]

    return {
        "prototype": getattr(prototype, "name", prototype_name),
        "fixture": str(fixture_root),
        "weights": mix["weights"],
        "ingest": _to_jsonable(ingest_report),
        "queries": queries_out,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", required=True, help='"null" or a name under prototypes/')
    parser.add_argument("--fixture", default=".", help="fixture root (default: .)")
    parser.add_argument(
        "--out", default=None, help="results file (default: build/results-<prototype>.json)"
    )
    args = parser.parse_args(argv)

    fixture_root = Path(args.fixture).resolve()
    out_path = Path(args.out) if args.out else Path("build") / f"results-{args.prototype}.json"
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results = run(fixture_root, args.prototype)
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {out_path} ({len(results['queries'])} queries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
