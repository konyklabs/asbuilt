"""Assembles the ingest root, runs one prototype's ingest, times every query
over warm repeats, and writes raw results.

CLI: ``uv run python bench/run.py --prototype null [--fixture .]
[--out build/results-null.json] [--through-step c6] [--repeats 20]
[--budget-tokens N] [--budget-dollars N] [--reset] [--incremental]
[--only-surfaces explain,contradictions] [--transcript build/transcripts/<arm>-<step>.md]``.

``--only-surfaces`` (asbuilt#9) restricts the query mix to the given
comma-separated surface names before running anything — a subset run for a
quick check or a smoke demo, never a different mix file. ``--transcript``
writes a markdown file (``write_transcript``): one ``##`` section per query
actually run, each with the question, the answer (facts as lines, or the
`ask` sentences) and its citations — so a benchmark run's own output is
usable as a demo script, not just a scored artefact.

Ingest-root integrity (D-013): ``ingest()`` is never handed the raw fixture.
``assemble_ingest_root`` builds ``build/ingest/`` from three things only —
the built repository's content *through* ``--through-step`` (default: the
fixture's last step), via ``bench.build.Timeline``, never a git checkout of
``system/`` itself; ``sources/{wiki,docs,tickets,pulls}``, whole (they don't
carry a step); and only the ``runs/*.json`` reports at or before that step
(by each report's own ``metadata.step``, not by filename — a report that
fails to parse, or has none, is an error, not a silent skip: an ingest root
silently missing evidence it should have is worse than one that fails to
build at all). ``truth/``, ``truth/PLAN.yaml``, ``queries/`` and the check
scripts under ``tools/`` are never assembled in — see ``tests/test_leaks.py``
for the check that nothing under the assembled root carries a truth fact id
or near-verbatim statement.

``--incremental``: the two-phase run (D-013). Assembles the ingest root
through the fixture's *second-to-last* step and calls
``ingest(root, ENTITY_KINDS, incremental=False)``, then assembles it again
through the *last* step and calls
``ingest(root, ENTITY_KINDS, incremental=True)``. Both ``IngestReport``s and
their delta (seconds, tokens, dollars, calls — the second call's own numbers,
since each call reports only the work it did) are recorded under
``ingest_incremental`` in the results file; ``phase`` is ``"incremental"``
(else ``"full"``). The query mix still runs once, after the second ingest,
so the scorer can check the prototype answers as of the *later* state
(supersession, not a stale snapshot from the first phase). ``--through-step``
is ignored with ``--incremental`` (the two steps are fixed by the fixture's
own history, not chosen).

Prototype lookup: ``--prototype null`` loads ``bench.null:NullPrototype``.
Any other name ``X`` loads ``prototypes.X:Prototype``, importable from
``spike/prototypes/X/__init__.py`` exposing a class named ``Prototype`` that
implements ``bench.protocol.Prototype`` (see that module's docstring for the
document-id conventions every prototype must honour).

``ENTITY_KINDS`` (below) is the fixed vocabulary passed to every arm's
``ingest`` — the same set, in the same order, for every arm (D-013).

``--budget-tokens N``/``--budget-dollars N``: set ``ASBUILT_BUDGET_TOKENS``/
``ASBUILT_BUDGET_DOLLARS`` before ``ingest`` runs, for ``bench.llm.
budget_from_env()`` — which ``bench.llm.CountingClient`` calls automatically
when constructed with no explicit ``budget=`` — to read. If ``ingest`` raises
``bench.llm.BudgetExceeded``, this script prints the stop message and exits
non-zero rather than writing a (necessarily incomplete) results file.

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
            except json.JSONDecodeError as exc:
                raise RunError(f"{report_path}: invalid JSON ({exc})") from exc
            step = (data.get("metadata") or {}).get("step")
            if not step:
                raise RunError(f"{report_path}: missing metadata.step")
            if step not in step_ids:
                raise RunError(f"{report_path}: metadata.step {step!r} is not a known history step")
            if step_ids.index(step) <= through_index:
                shutil.copy2(report_path, runs_dst / report_path.name)

    # Records which history step this root was assembled through — not
    # fixture content, just the one fact a prototype needs to resolve a
    # `code/<path>` citation's version against `build/commits.json` (asbuilt#9:
    # prototypes/baseline reads this to avoid guessing at the step from
    # commits.json alone, which breaks once that file holds steps beyond
    # this root's own, e.g. after a full `bench/build.py` run).
    (ingest_root / "step.json").write_text(json.dumps({"step": through_step}) + "\n")

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


def _empty_result(surface: str) -> Any:
    """What a failed query reports in place of its result: the surface's
    empty shape, so the scorer counts it as a miss and nothing else."""
    return {"sentences": []} if surface == "ask" else []


def run_query(
    prototype: Any, query: dict[str, Any], repeats: int = DEFAULT_REPEATS
) -> dict[str, Any]:
    """Times the query's first (cold) call, kept as the canonical result,
    then `repeats` further warm calls, timed and discarded, for p50/p95.

    A query whose call raises is recorded, not propagated: its `result` is
    the surface's empty shape, `error` carries the exception, and the run
    goes on to the next query. The first baseline model run
    (konyklabs/roadmap#154, 2026-10-06) died on one explain call after 33
    minutes of paid queries and wrote nothing, because one failure aborted
    the arm. A `BudgetExceeded` still aborts: that is the stop condition."""
    started = time.perf_counter()
    error: str | None = None
    try:
        result = _call_surface(prototype, query)
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - one failed query must not lose the others
        error = f"{type(exc).__name__}: {exc}"
        result = None
    cold_ms = (time.perf_counter() - started) * 1000

    warm_ms: list[float] = []
    if error is None:
        for _ in range(repeats):
            t0 = time.perf_counter()
            try:
                _call_surface(prototype, query)
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - the cold result stands; say what failed
                error = f"warm repeat {len(warm_ms) + 1}: {type(exc).__name__}: {exc}"
                break
            warm_ms.append((time.perf_counter() - t0) * 1000)
    warm_sorted = sorted(warm_ms)

    out = {
        "id": query.get("id"),
        "surface": query["surface"],
        "latency_ms": cold_ms,  # kept for compatibility; equal to cold_ms
        "cold_ms": cold_ms,
        "p50_ms": _percentile(warm_sorted, 50) if warm_sorted else None,
        "p95_ms": _percentile(warm_sorted, 95) if warm_sorted else None,
        "warm_repeats": len(warm_ms),
        "params": {k: v for k, v in query.items() if k not in ("id", "surface")},
        "result": _to_jsonable(result) if result is not None else _empty_result(query["surface"]),
    }
    if error is not None:
        out["error"] = error
        print(f"query {query.get('id')} ({query['surface']}) failed: {error}", file=sys.stderr)
    return out


def _format_citations(citations: list[dict[str, Any]] | None) -> str:
    if not citations:
        return "(no citations)"
    parts = []
    for c in citations:
        document = c.get("document", "?")
        location = c.get("location")
        parts.append(f"{document}#{location}" if location else document)
    return ", ".join(parts)


def _format_fact_line(fact: dict[str, Any]) -> str:
    tier = fact.get("tier", "?")
    statement = fact.get("statement", "")
    return f"- [{tier}] {statement} ({_format_citations(fact.get('citations'))})"


def _query_question(query_out: dict[str, Any]) -> str:
    """A one-line rendering of what was asked, from the query's own
    `params` (`run_query`'s copy of every query field but `id`/`surface`) —
    used by `write_transcript` (asbuilt#9) so a transcript reads as the
    question, then the answer, never just the raw params dict."""
    params = query_out.get("params") or {}
    surface = query_out["surface"]
    if surface == "explain":
        return f"explain({params.get('entity')!r})"
    if surface == "search":
        return f"search({params.get('query')!r})"
    if surface == "ask":
        return f"ask({params.get('question')!r})"
    if surface == "contradictions":
        return f"contradictions({params.get('entity')!r})"
    if surface == "stale":
        return f"stale(since={params.get('since')!r})"
    return f"{surface}({params!r})"


def _render_transcript_entry(query_out: dict[str, Any]) -> str:
    lines = [f"## {query_out.get('id')} — {_query_question(query_out)}", ""]
    if query_out.get("error"):
        lines.append(f"(failed: {query_out['error']})")
    surface = query_out["surface"]
    result = query_out.get("result")
    if surface == "ask":
        sentences = (result or {}).get("sentences") or []
        if not sentences:
            lines.append("(no answer)")
        for sentence in sentences:
            citations = _format_citations(sentence.get("citations"))
            lines.append(f"- {sentence.get('text', '')} ({citations})")
    elif surface == "contradictions":
        items = result or []
        if not items:
            lines.append("(no contradictions)")
        for contradiction in items:
            a = contradiction.get("a") or {}
            b = contradiction.get("b") or {}
            winner = contradiction.get("winner")
            winner_text = winner.get("statement") if winner else "undecided"
            lines.append(f"- A: {_format_fact_line(a)}")
            lines.append(f"  B: {_format_fact_line(b)}")
            lines.append(f"  label={contradiction.get('label')}, winner={winner_text!r}")
    else:  # explain, search, stale: list[Fact]
        items = result or []
        if not items:
            lines.append("(no facts)")
        for fact in items:
            lines.append(_format_fact_line(fact))
    lines.append("")
    return "\n".join(lines)


def write_transcript(
    path: Path, prototype_name: str, step: str, queries_out: list[dict[str, Any]]
) -> None:
    """Writes `path` (asbuilt#9): for every query, the question, the answer
    (facts as lines, or the ask sentences) and the citations — so a
    benchmark run's own output doubles as a demo script. Markdown, one `##`
    section per query, in the query mix's own order."""
    header = f"# {prototype_name} @ {step}\n\n"
    body = "\n".join(_render_transcript_entry(q) for q in queries_out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body)


def run(
    fixture_root: Path,
    prototype_name: str,
    *,
    through_step: str | None = None,
    ingest_root: Path | None = None,
    repeats: int = DEFAULT_REPEATS,
    budget_tokens: int | None = None,
    budget_dollars: float | None = None,
    incremental: bool = False,
    only_surfaces: frozenset[str] | None = None,
    transcript_path: Path | None = None,
    flush_path: Path | None = None,
) -> dict[str, Any]:
    """Runs one arm: ingest, then the query mix. With `flush_path`, the
    results so far are written there after every query, marked
    `"complete": false`, so a crash or a budget stop keeps what was paid
    for; `main` writes the complete file at the end."""
    prototype = load_prototype(prototype_name)
    timeline = Timeline(fixture_root)
    ingest_root = ingest_root or (Path.cwd() / "build" / "ingest")

    if budget_tokens is not None:
        os.environ["ASBUILT_BUDGET_TOKENS"] = str(budget_tokens)
    if budget_dollars is not None:
        os.environ["ASBUILT_BUDGET_DOLLARS"] = str(budget_dollars)

    ingest_incremental: dict[str, Any] | None = None

    if incremental:
        if len(timeline.steps) < 2:
            raise RunError("--incremental needs at least two history steps")
        first_step, second_step = timeline.steps[-2].id, timeline.steps[-1].id

        first_root = assemble_ingest_root(fixture_root, first_step, ingest_root / "phase-1")
        first_report = prototype.ingest(first_root, ENTITY_KINDS, False)

        second_root = assemble_ingest_root(fixture_root, second_step, ingest_root / "phase-2")
        second_report = prototype.ingest(second_root, ENTITY_KINDS, True)

        ingest_report = second_report
        step = second_step
        ingest_incremental = {
            "through_step_1": first_step,
            "through_step_2": second_step,
            "report_1": _to_jsonable(first_report),
            "report_2": _to_jsonable(second_report),
            # The second call's own numbers: each ingest() call reports only
            # the work it did, so this *is* the added cost of the second step.
            "delta": {
                "seconds": second_report.seconds,
                "input_tokens": second_report.input_tokens,
                "output_tokens": second_report.output_tokens,
                "dollars": second_report.dollars,
                "calls": second_report.calls,
            },
        }
    else:
        step = through_step or timeline.steps[-1].id
        assembled = assemble_ingest_root(fixture_root, step, ingest_root)
        ingest_report = prototype.ingest(assembled, ENTITY_KINDS, False)

    mix = load_mix(fixture_root / "queries" / "mix.yaml")
    selected_queries = (
        mix["queries"]
        if only_surfaces is None
        else [q for q in mix["queries"] if q["surface"] in only_surfaces]
    )
    prototype_display_name = getattr(prototype, "name", prototype_name)

    def assemble(queries_out: list[dict[str, Any]], complete: bool) -> dict[str, Any]:
        result: dict[str, Any] = {
            "prototype": prototype_display_name,
            "fixture": str(fixture_root),
            "through_step": step,
            "phase": "incremental" if incremental else "full",
            "weights": mix["weights"],
            "ingest": _to_jsonable(ingest_report),
            "queries": queries_out,
            "complete": complete,
        }
        if ingest_incremental is not None:
            result["ingest_incremental"] = ingest_incremental
        return result

    queries_out: list[dict[str, Any]] = []
    for query in selected_queries:
        queries_out.append(run_query(prototype, query, repeats))
        if flush_path is not None:
            flush_path.write_text(json.dumps(assemble(queries_out, False), indent=2) + "\n")

    if transcript_path is not None:
        write_transcript(transcript_path, prototype_display_name, step, queries_out)

    return assemble(queries_out, True)


# The arms that run pipeline/ and therefore its embedder and NLI cross-encoder.
_PIPELINE_PROTOTYPES = frozenset({"b_postgres"})


def pipeline_models_missing(prototype: str, environ: dict[str, str] | None = None) -> str | None:
    """The reason an arm run must not start, or None. `pipeline.embed` and
    `pipeline.contradict` fall back to a hash embedder and to no NLI
    pre-filter when sentence-transformers is not importable, by design for
    the tests. An arm run must never take that fallback unasked: the first
    stack-B model run (konyklabs/roadmap#154, 2026-10-06, 198 calls) ingested
    with `hash-384 (fake: sentence-transformers not installed)` and skipped
    the NLI pass because the `pipeline` extra was not in the environment,
    and only the results file said so afterwards. Here the run refuses
    before any call unless the operator asked for both fallbacks explicitly
    (`ASBUILT_EMBED=fake` and `ASBUILT_NLI=off`), which the results then
    record as such."""
    if prototype not in _PIPELINE_PROTOTYPES:
        return None
    env = os.environ if environ is None else environ
    asked_fake = env.get("ASBUILT_EMBED", "").lower() == "fake"
    asked_no_nli = env.get("ASBUILT_NLI", "").lower() == "off"
    if asked_fake and asked_no_nli:
        return None
    try:
        import sentence_transformers  # noqa: F401, PLC0415 - availability probe only
    except ImportError:
        return (
            f"{prototype} needs the real embedder and the NLI cross-encoder, and "
            "sentence-transformers is not importable: run with `uv run --extra pipeline` "
            "(or `uv sync --extra pipeline` first), or set ASBUILT_EMBED=fake and "
            "ASBUILT_NLI=off to accept both fallbacks on purpose"
        )
    return None


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
        "--budget-dollars", type=float, default=None, help="sets ASBUILT_BUDGET_DOLLARS for ingest"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="reset the arm (bench.reset.reset_arm) before ingesting",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="two-phase ingest: second-to-last step, then the last with incremental=True",
    )
    parser.add_argument(
        "--only-surfaces",
        default=None,
        help="comma-separated surface names (e.g. explain,contradictions); default: every surface",
    )
    parser.add_argument(
        "--transcript",
        default=None,
        help="write a cited markdown transcript (question, answer, citations) per query",
    )
    args = parser.parse_args(argv)

    missing = pipeline_models_missing(args.prototype)
    if missing is not None:
        print(f"bench/run.py: {missing}", file=sys.stderr)
        return 2

    fixture_root = Path(args.fixture).resolve()
    out_path = Path(args.out) if args.out else Path("build") / f"results-{args.prototype}.json"
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # A failed CLI call keeps its whole result object beside the results
    # (bench.claude_code._keep_failure); the error names the file.
    os.environ.setdefault("ASBUILT_FAILURE_DIR", str(out_path.parent / "failures"))

    only_surfaces = (
        frozenset(s.strip() for s in args.only_surfaces.split(",") if s.strip())
        if args.only_surfaces
        else None
    )
    transcript_path = Path(args.transcript) if args.transcript else None
    if transcript_path is not None and not transcript_path.is_absolute():
        transcript_path = Path.cwd() / transcript_path

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
            budget_dollars=args.budget_dollars,
            incremental=args.incremental,
            only_surfaces=only_surfaces,
            transcript_path=transcript_path,
            flush_path=out_path,
        )
    except BudgetExceeded as exc:
        print(f"STOPPED: {exc}")
        print(f"comment on the driving issue before continuing; see build/stop-{exc.arm}.json")
        print(f"the queries finished before the stop are in {out_path} (complete: false)")
        return 1

    out_path.write_text(json.dumps(results, indent=2) + "\n")
    failed = [q["id"] for q in results["queries"] if "error" in q]
    suffix = f", {len(failed)} failed: {', '.join(str(f) for f in failed)}" if failed else ""
    print(f"wrote {out_path} ({len(results['queries'])} queries{suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
