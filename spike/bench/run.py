"""Assembles the ingest root, runs one prototype's ingest, times every query
over warm repeats, and writes raw results.

CLI: ``uv run python bench/run.py --prototype null [--fixture .]
[--out build/results-null.json] [--through-step c6] [--repeats 20]
[--budget-tokens N] [--reset]``.

Ingest-root integrity (D-013): ``ingest()`` is never handed the raw fixture.
``assemble_ingest_root`` builds ``build/ingest/`` from three things only —
the built repository's content *through* ``--through-step`` (default: the
fixture's last step), via ``bench.build.Timeline``, never a git checkout of
``system/`` itself; ``sources/{wiki,docs,tickets,pulls}``, whole (they don't
carry a step); and only the ``runs/*.json`` reports at or before that step
(by each report's own ``metadata.step``, not by filename). ``truth/``,
``truth/PLAN.yaml``, ``queries/`` and the check scripts under ``tools/`` are
never assembled in — see ``tests/test_leaks.py`` for the check that nothing
under the assembled root carries a truth fact id or near-verbatim statement.
``--through-step`` also drives the incremental phase: ingesting through c5,
then again through c6 with ``incremental=True``, is two separate ``run.py``
invocations (the second passes ``--through-step c6``; whether a prototype
treats that as fresh or incremental is the prototype's own state to hold,
signalled to it by the protocol's ``incremental`` flag — this script always
calls ``ingest`` with ``incremental=False``; a script orchestrating the
two-phase comparison is expected to call the underlying ``run()`` function
directly with ``incremental=True`` for the second phase, since that is a
benchmark-level decision, not a per-invocation CLI default).

Prototype lookup: ``--prototype null`` loads ``bench.null:NullPrototype``.
Any other name ``X`` loads ``prototypes.X:Prototype``, importable from
``spike/prototypes/X/__init__.py`` exposing a class named ``Prototype`` that
implements ``bench.protocol.Prototype`` (see that module's docstring for the
document-id conventions every prototype must honour).

``ENTITY_KINDS`` (below) is the fixed vocabulary passed to every arm's
``ingest`` — the same set, in the same order, for every arm (D-013).

``--budget-tokens N``: the environment variable ``ASBUILT_BUDGET_TOKENS`` is
set to ``N`` before ``ingest`` runs, for a prototype's own ``bench.llm.
CountingClient`` to read as its budget if the prototype doesn't set one more
specifically itself. If ``ingest`` raises ``bench.llm.BudgetExceeded``, this
script prints the stop message and exits non-zero rather than writing a
(necessarily incomplete) results file.

``--reset``: calls ``bench.reset.reset_arm(prototype)`` before assembling the
ingest root.

Latency (D-013): each query's *first* call is timed and kept as the
canonical result (``cold_ms``); after it, ``--repeats`` (default 20) further
warm calls are made and timed, discarded except for their timings, giving
``p50_ms``/``p95_ms``. ``latency_ms`` is kept, equal to ``cold_ms``, for
compatibility with anything already reading the older, single-timing shape.

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
        entity: farebox
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
        entity: farebox               # optional; omitted/null = every contradiction
      - id: q-stale-01
        surface: stale
        since: "2026-01-15T00:00:00-05:00"

``explain``/``contradictions`` take an entity NAME (``truth/entities.yaml``'s
``name`` field), never an ``E-`` id — arms return names too (D-013; see
``bench/protocol.py``'s module docstring). ``explain`` and ``contradictions``
have no ``expects``: the scorer derives expected results from ``truth/``
itself. ``search``, ``ask`` and ``stale`` need an explicit ``expects``/
``since`` because there is no other way to know which facts a free-text
query or a time cutoff should surface. ``since`` may be date-only or a full
ISO datetime with an offset; the scorer compares it against history-step
dates by dropping the offset from both sides whenever one of them is naive.

Output: a JSON file with the prototype's ``ingest`` report and, per query,
its latency fields and its raw (serialised) result.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
import shutil
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

from bench.build import Timeline  # noqa: E402
from bench.llm import BudgetExceeded  # noqa: E402
from bench.protocol import Category  # noqa: E402
from bench.reset import reset_arm  # noqa: E402

# D-013: the same entity-kind vocabulary, in the same order, for every arm —
# truth/entities.yaml's own `kind:` values.
ENTITY_KINDS: tuple[str, ...] = (
    "service",
    "table",
    "rule",
    "job",
    "flag",
    "integration",
    "queue",
    "team",
    "endpoint",
)

DEFAULT_REPEATS = 20


class RunError(RuntimeError):
    pass


def load_prototype(name: str):
    if name == "null":
        module = importlib.import_module("bench.null")
        return module.NullPrototype()
    module = importlib.import_module(f"prototypes.{name}")
    return module.Prototype()


def assemble_ingest_root(fixture_root: Path, through_step: str, ingest_root: Path) -> Path:
    """Builds `ingest_root` from the built repository's content through
    `through_step` (via Timeline, never a git checkout of `system/`),
    `sources/{wiki,docs,tickets,pulls}`, and only the `runs/*.json` reports
    at or before that step. Never truth/, PLAN.yaml, queries/ or tools/ —
    see the module docstring's ingest-root integrity note."""
    timeline = Timeline(fixture_root)
    step_ids = [s.id for s in timeline.steps]
    if through_step not in step_ids:
        raise RunError(f"unknown step {through_step!r}; known steps are {step_ids}")
    through_index = step_ids.index(through_step)

    if ingest_root.exists():
        shutil.rmtree(ingest_root)
    ingest_root.mkdir(parents=True)

    repo_dir = ingest_root / "repo"
    for path in timeline.active_paths_at(through_step):
        content = timeline.content_at(path, through_step)
        if content is None:
            continue
        dest = repo_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    for kind in ("wiki", "docs", "tickets", "pulls"):
        src = fixture_root / "sources" / kind
        if src.is_dir():
            shutil.copytree(src, ingest_root / "sources" / kind)

    runs_src = fixture_root / "runs"
    if runs_src.is_dir():
        runs_dst = ingest_root / "runs"
        runs_dst.mkdir(parents=True, exist_ok=True)
        for report_path in sorted(runs_src.glob("*.json")):
            try:
                data = json.loads(report_path.read_text())
            except json.JSONDecodeError:
                continue
            step = (data.get("metadata") or {}).get("step")
            if step in step_ids and step_ids.index(step) <= through_index:
                shutil.copy2(report_path, runs_dst / report_path.name)

    return ingest_root


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


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _call_surface(prototype: Any, query: dict[str, Any]) -> Any:
    surface = query["surface"]
    if surface == "explain":
        return prototype.explain(query["entity"])
    if surface == "search":
        category = Category(query["category"]) if query.get("category") else None
        return prototype.search(
            query["query"], category=category, since=_parse_datetime(query.get("since"))
        )
    if surface == "ask":
        return prototype.ask(query["question"])
    if surface == "contradictions":
        return prototype.contradictions(query.get("entity"))
    if surface == "stale":
        return prototype.stale(_parse_datetime(query["since"]))
    raise RunError(f"unknown query surface {surface!r} in query {query.get('id')!r}")


def run_query(
    prototype: Any, query: dict[str, Any], repeats: int = DEFAULT_REPEATS
) -> dict[str, Any]:
    """Times the query's first (cold) call, kept as the canonical result,
    then `repeats` further warm calls, timed and discarded, for p50/p95."""
    started = time.perf_counter()
    result = _call_surface(prototype, query)
    cold_ms = (time.perf_counter() - started) * 1000

    warm_ms: list[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        _call_surface(prototype, query)
        warm_ms.append((time.perf_counter() - t0) * 1000)
    warm_sorted = sorted(warm_ms)

    return {
        "id": query.get("id"),
        "surface": query["surface"],
        "latency_ms": cold_ms,  # kept for compatibility; equal to cold_ms
        "cold_ms": cold_ms,
        "p50_ms": _percentile(warm_sorted, 50) if warm_sorted else None,
        "p95_ms": _percentile(warm_sorted, 95) if warm_sorted else None,
        "warm_repeats": len(warm_ms),
        "params": {k: v for k, v in query.items() if k not in ("id", "surface")},
        "result": _to_jsonable(result),
    }


def run(
    fixture_root: Path,
    prototype_name: str,
    *,
    through_step: str | None = None,
    ingest_root: Path | None = None,
    repeats: int = DEFAULT_REPEATS,
    budget_tokens: int | None = None,
    incremental: bool = False,
) -> dict[str, Any]:
    prototype = load_prototype(prototype_name)

    timeline = Timeline(fixture_root)
    step = through_step or timeline.steps[-1].id
    ingest_root = ingest_root or (Path.cwd() / "build" / "ingest")
    assembled = assemble_ingest_root(fixture_root, step, ingest_root)

    if budget_tokens is not None:
        os.environ["ASBUILT_BUDGET_TOKENS"] = str(budget_tokens)

    ingest_report = prototype.ingest(assembled, ENTITY_KINDS, incremental)
    mix = load_mix(fixture_root / "queries" / "mix.yaml")

    queries_out = [run_query(prototype, query, repeats) for query in mix["queries"]]

    return {
        "prototype": getattr(prototype, "name", prototype_name),
        "fixture": str(fixture_root),
        "through_step": step,
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
    parser.add_argument(
        "--through-step", default=None, help="build the ingest root as of this step (default: last)"
    )
    parser.add_argument(
        "--repeats", type=int, default=DEFAULT_REPEATS, help="warm latency repeats per query"
    )
    parser.add_argument(
        "--budget-tokens", type=int, default=None, help="sets ASBUILT_BUDGET_TOKENS for ingest"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="reset the arm (bench.reset.reset_arm) before ingesting",
    )
    args = parser.parse_args(argv)

    fixture_root = Path(args.fixture).resolve()
    out_path = Path(args.out) if args.out else Path("build") / f"results-{args.prototype}.json"
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.reset:
        # spike_root=fixture_root: in the documented invocation (`cd spike
        # && ... --fixture .`) these coincide, so this resets the real
        # arm/build directories; passing fixture_root explicitly (rather
        # than bench.reset's own default, the actual spike/ on disk) keeps
        # a test run pointed at a scratch fixture from touching real state.
        print(reset_arm(args.prototype, spike_root=fixture_root))

    try:
        results = run(
            fixture_root,
            args.prototype,
            through_step=args.through_step,
            repeats=args.repeats,
            budget_tokens=args.budget_tokens,
        )
    except BudgetExceeded as exc:
        print(f"STOPPED: {exc}")
        print(f"comment on the driving issue before continuing; see build/stop-{exc.arm}.json")
        return 1

    out_path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {out_path} ({len(results['queries'])} queries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
