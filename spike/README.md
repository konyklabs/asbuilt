# Storage-engine spike: benchmark harness

Benchmarks a storage-engine prototype against one synthetic system
("Gearwell", invented — see `../AGENTS.md`'s cleanroom rule) on five agent
access surfaces: `explain`, `search`, `ask`, `contradictions`, `stale`. See
`../README.md`'s "Storage engine: the open spike" for what this settles.

Two halves live here. The **fixture**: `truth/` (the ground truth, authored
first), `system/` (the invented system's code, tests and history),
`sources/` (its wiki, documents, tickets and pull-request threads), `runs/`
(test-run evidence at every commit) and `queries/mix.yaml`. The **harness**:
`bench/` (build, run, score, the prototype protocol) and `tests/` (the
harness's own tests, on a throwaway mini fixture, plus four tests on the real
fixture). `truth/SCHEMA.md` defines the ground-truth yaml shapes. Build issue:
konyklabs/asbuilt#2; decision: D-013 in `konyklabs/roadmap`.

## The invented system

**Gearwell** is a bike-share operator's back office, invented for this
benchmark and resembling no real system (`../AGENTS.md`). Three services:
`dockyard` (Python: stations, docks, bikes, check-out and check-in),
`farebox` (Python: memberships, ride pricing, invoices, refunds, payments
through the invented provider *Tollbooth Pay*, and the `ride.events` queue)
and `dispatch` (TypeScript: rebalancing, maintenance tickets, three scheduled
jobs, the invented weather service *Skyglass*). Fifty entities in
`truth/entities.yaml`: 3 teams, 3 services, 15 tables, 1 queue, 2
integrations, 3 jobs, 4 feature flags, 15 business rules, 4 endpoints.

Six commits (`system/history/steps.yaml`, January to August 2026): the
import; the spring promotion raising member free minutes to 45; membership
grace from 3 to 7 days; the promotion's end; the single-ride cap to $30 and
the lost-bike fee to $150; storm-pause for rebalancing plus the
`refund_auto_approve` flag. `system/<path>` is each file's final content and
`system/history/<step>/<path>` its content *through* that step; `build.py`
turns that into a repository with reproducible SHAs.

Planted, listed in `truth/` before any artefact was written: 120 facts
(48 business logic, 38 technical implementation, 24 operations, 10 history;
28 at the `executed` tier, 40 `code`, 52 `documented`), 20 contradictions
(6 wiki-vs-test, 4 ticket-vs-code, 4 page-vs-page, 6 doc-vs-code), 10 stale
pages, and 5 facts whose only carrier is a pull-request comment. Carriers:
54 Python modules and 16 TypeScript files; 23 distinct pytest tests across
the history (19 at the final commit, end-to-end and unit) and 4 Vitest tests, with 12 run reports (one per suite per commit); 40
wiki pages, 10 documents, 80 tickets (57 of them noise), 8 pull-request
threads. `sources/PLAN.yaml` is the authoring plan every document was written
from; the prose paraphrases each fact (never its statement verbatim) so that
extraction is measured, not string matching.

The JavaScript runner is **Vitest** (5.0.2): its JSON reporter carries
`ancestorTitles` and `title` per test, which is what a run carrier needs to
name a test exactly; Jest would have served, Mocha lacks the structured
reporter out of the box, and Playwright is a browser runner the fixture does
not need. The sizing is the estimate from the tiering comment on
konyklabs/roadmap#154 and stands until Oleg's local landscape note reweights
it.

## Checks on the fixture

```
uv run --with pyyaml python truth/validate.py          # truth <-> PLAN: ids, counts, carriers, dates
uv run --with pyyaml python sources/check_wiki_docs.py # every page: metadata, anchors, values, no verbatim statements
uv run --with pyyaml python sources/check_tickets_pulls.py
uv run pytest tests/test_fixture.py                    # carriers resolve on disk; runs carry commits; SHAs reproduce
```

## Setup

```
cd spike
uv sync
```

## Pipeline

1. **Build the invented system's git history.**

   ```
   uv run python bench/build.py
   ```

   Reads `system/` (final content of every file, minus `history/`) and
   `system/history/steps.yaml` (ordered commit steps, with optional
   per-step content overlays under `system/history/<step>/`). Writes
   `build/repo/` — a real git repository, one commit per step, oldest
   first, with fixed author/committer and the step's own date, so SHAs are
   reproducible — and `build/commits.json` (step id -> sha/date/message).

   Content rule ("content through that step"): a file's content at step k is
   the overlay at the *smallest* step j >= k that has one, or the final
   `system/<path>` if none — so an overlay is written at a value's *last*
   step, not its first, and a run of N steps sharing a value needs exactly
   one overlay file. An empty `<path>.absent` marker means the path doesn't
   exist through that step (a file first appearing at c6 needs one marker,
   at c5). See `bench/build.py`'s module docstring for the exact rule, edge
   cases, and `EXCLUDED_DIRNAMES` (`node_modules/`, `.ruff_cache/`, and
   similar generated directories are never fixture content, even if they
   turn up under `system/` from running the fixture's own code locally).
   `bench.build.Timeline` exposes the same content rule for reuse without a
   build — `check_consistency` (below) materialises a `code/` carrier's
   content this way, not via git.

2. **Run the built system's test suites at every step.**

   ```
   uv run python bench/runs.py
   ```

   For each step: `git checkout` its commit in `build/repo/`, run the
   Python suite with `pytest --json-report` into `runs/pytest-<step>.json`
   (skipped, with a message, if there's no `tests/` yet), and if
   `dispatch/package.json` exists, `npm ci` once and `npx vitest run` into
   `runs/vitest-<step>.json`. Exits non-zero if any run failed.

3. **Run a prototype against the fixed query mix.**

   ```
   uv run python bench/run.py --prototype null [--fixture .] [--out build/results-null.json]
   ```

   Loads the named prototype, calls `ingest(fixture_root)`, then runs
   every query in `queries/mix.yaml`, recording per-query wall-clock
   latency and the raw (JSON-serialised) result. `--prototype null` uses
   the always-empty baseline (`bench/null.py`); see "Prototype contract"
   below for adding a real one.

4. **Score the results against ground truth.**

   ```
   uv run python bench/score.py build/results-null.json [--truth truth] [--json build/score-null.json]
   ```

   Prints precision/recall/F1 per surface (overall and by the truth fact's
   category), contradiction recall and winner agreement, staleness
   precision/recall, p50/p95 latency per surface, the ingest report, and a
   weighted headline (`sum(weight * F1, or recall where precision is
   undefined)`, weights from `queries/mix.yaml`). `--commits` (default
   `build/commits.json`) is used only to resolve a returned code citation's
   SHA back to a step id, when disambiguating between two truth facts that
   share a statement and a code document at different versions (missing is
   fine; disambiguation then falls back to plain string comparison). See
   `bench/score.py`'s module docstring for the interpretation calls made
   where the spec leaves a choice (aggregation is by summing raw counts
   across a surface's queries — micro-averaged — before computing ratios,
   and per-category breakdowns bucket by the *truth* fact's category only).

5. **Check the fixture's own consistency** (a library call, not yet a CLI):

   ```python
   from pathlib import Path
   from bench.truth import check_consistency, summarize

   print(summarize(check_consistency(Path("."))))
   ```

   Checks every carrier document *and location* resolves (wiki/doc heading
   anchors against actual `## Heading` slugs, ticket/pull JSON fields and
   comment ids, a `code/` carrier's symbol against its content at that
   version via `Timeline`, a `run/` carrier's test node id or vitest
   `fullName` against a passed result) and every cross-referenced id exists.
   This is the sources/code/runs side; `truth/validate.py` (authored
   separately) is the truth/PLAN side and is not touched here. `summarize`
   groups problems by kind with counts first — useful since the real
   fixture will report many "not found" problems until sources/system are
   fully authored; each problem is `kind:document:location:reason`.

## `queries/mix.yaml`

There is no schema doc for this file (only `truth/SCHEMA.md` covers
entities/facts/contradictions/stale); `bench/run.py`'s module docstring is
the source of truth for its shape. In short: a top-level `weights` map (one
entry per surface) and a `queries` list, each with an `id`, a `surface`, and
surface-specific fields. `explain` and `contradictions` need no `expects` —
the scorer derives expected results from `truth/` itself (facts naming the
given entity; planted contradictions naming it, or every one if omitted).
`search`, `ask` need an explicit `expects` (a list of truth fact ids); `stale`
needs `since`, either a date-only string or a full ISO datetime — the scorer
compares it against history-step dates by dropping the UTC offset from both
sides whenever one is naive.

## Prototype contract

`bench/protocol.py` is the interface (`ingest`, `explain`, `search`, `ask`,
`contradictions`, `stale`) and the document-id conventions every prototype
must use (`wiki/<slug>`, `ticket/<KEY>`, `doc/<id>`, `pull/<number>`,
`code/<path>`, `run/<run-id>`). `bench/truth.py`'s module docstring fixes the
mapping from those ids to files on disk (`sources/wiki/<slug>.md`,
`system/<path>`, `runs/<run-id>.json`, ...) — the same mapping the scorer
uses to check that a carrier document actually exists. `Fact.entities` are
the ids in `truth/entities.yaml` (`E-...`): the scorer credits a returned fact
only when it shares an entity id with the truth fact, cites one of its
carrier documents, and states the same numbers, so a prototype must resolve
entities to those ids (they are what `explain` and `contradictions` queries
pass in) rather than return prose names.

A prototype named `X` (anything but `null`) must be importable as
`prototypes.X:Prototype` from `spike/prototypes/X/__init__.py`, exposing a
class named `Prototype` with no required constructor arguments. `bench/run.py`
puts the `spike/` directory on `sys.path` itself, so this works regardless of
how it's invoked.

## Testing the harness itself

`tests/fixtures/mini/` is a tiny, self-contained invented fixture used only
to test `bench/` — it is not the real spike fixture. Four history steps;
`farebox/pricing.py` has two overlays (c1, c3) plus a final content, to
exercise the "smallest step >= k" rule; `farebox/refunds.py` is added via a
`.absent` marker; a wiki page, a doc, a ticket and a pull request cover every
carrier-location kind `check_consistency` checks; thirteen facts include a
version-disambiguation case (F-001/F-003 share a statement and a code
document at different versions) and a wiki-vs-code contradiction/staleness
pair. `runs/pytest-c1.json` .. `pytest-c4.json` are genuine
`pytest --json-report` output, generated by actually running `bench/build.py`
and `bench/runs.py` against it; `runs/vitest-c1.json` is a hand-authored stub
in vitest's JSON shape (the mini fixture has no `dispatch/package.json`, so
`bench/runs.py` never actually invokes vitest for it) used only to exercise
`check_consistency`'s vitest-format handling.

```
uv run pytest
uv run ruff check .
```

`ruff check .` covers the whole `spike/` tree, including `truth/` and
`sources/`, which are authored separately; `uv run ruff check bench tests`
scopes it to this harness's own deliverables.
