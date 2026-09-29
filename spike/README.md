# The extraction-pipeline benchmark: harness

Benchmarks an extraction-pipeline prototype against one synthetic system
("Gearwell", invented — see `../AGENTS.md`'s cleanroom rule) on five agent
access surfaces: `explain`, `search`, `ask`, `contradictions`, `stale`. See
`../README.md`'s "The store, and the benchmark" for what this settles — the
store itself is decided by constraint, not benchmarked; the pipeline is.

Two halves live here. The **fixture**: `truth/` (the ground truth, authored
first), `system/` (the invented system's code, tests and history),
`sources/` (its wiki, documents, tickets and pull-request threads), `runs/`
(test-run evidence at every commit) and `queries/mix.yaml`. The **harness**:
`bench/` (build, run, score, the prototype protocol) and `tests/` (the
harness's own tests, on a throwaway mini fixture, plus four real-fixture
tests and the leak test). `truth/SCHEMA.md` defines the ground-truth yaml
shapes. Build issue: konyklabs/asbuilt#2; decision: D-013 in
`konyklabs/roadmap`.

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
27 at the `executed` tier, 41 `code`, 52 `documented`), 21 contradictions in
five kinds (6 wiki-vs-test, 6 doc-vs-code, 4 ticket-vs-code, 4 page-vs-page,
1 run-vs-code), 10 stale pages, and 5 facts whose only carrier is a
pull-request comment. Carriers: 54 Python modules and 16 TypeScript files;
24 distinct pytest node ids across the history (20 collected at the final
commit, of which one is skipped) and 4 Vitest tests, with 14 run reports
(one per suite per commit, plus two reruns); 40 wiki pages, 10 documents,
80 tickets (57 of them noise), 8 pull-request threads. `truth/PLAN.yaml` is
the authoring plan every document was written from; the prose paraphrases
each fact (never its statement verbatim) so that extraction is measured, not
string matching.

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
uv run --with pyyaml python tools/check_wiki_docs.py   # every page: metadata, anchors, values, no verbatim statements
uv run --with pyyaml python tools/check_tickets_pulls.py
uv run --with pyyaml python tools/check_code_leaks.py  # code/tests: no fact id, no 8-word prefix, no >=0.5 similarity
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
   `runs/vitest-<step>.json`.

   Planted-outcome tolerance and reruns (D-013; the contract is
   `truth/planted-runs.yaml`'s own `runner` section): a failing test (P-1), a
   skipped one (P-2) and a flaky one (P-3) are planted in the fixture's
   history. Every step's pytest suite runs once with `GEARWELL_ATTEMPT=1`;
   if that attempt has any failed/errored test, exactly those node ids
   re-run with `GEARWELL_ATTEMPT=2`, into `pytest-<step>-rerun.json`
   (document `run/pytest-<step>-rerun`) — this trigger is data-driven (any
   attempt-1 failure reruns, planted or not; P-1's genuinely-still-broken
   test reruns exactly like P-3's flaky one) and only vitest has no
   per-test re-invocation, so it reruns the whole suite on any failure
   (untested against a real case — the current planted set is pytest-only).
   Whether an outcome counts as *unexpected* (and makes the run exit
   non-zero) is checked against `planted-runs.yaml`'s per-test `outcomes`
   (attempt 1) and `reruns` (attempt 2) tables if the file exists; without
   it, any failure is unexpected (reruns still happen). See
   `bench/runs.py`'s module docstring for the exact matching rule and the
   stale-bytecode and report-path guards it also carries.

3. **Run a prototype against the fixed query mix.**

   ```
   uv run python bench/run.py --prototype null [--fixture .]
     [--out build/results-null.json] [--through-step c6] [--repeats 20]
     [--budget-tokens N] [--reset]
   ```

   Assembles `build/ingest/` — the ingest-root integrity rule (D-013): never
   the raw fixture, only the built repository's content *through*
   `--through-step` (default: the fixture's last step, via `Timeline`, never
   a git checkout of `system/`), `sources/{wiki,docs,tickets,pulls}` whole,
   and the `runs/*.json` reports at or before that step (by each report's own
   `metadata.step`). `truth/`, `truth/PLAN.yaml`, `queries/` and `tools/` are
   never in it — `tests/test_leaks.py` fails if any assembled file still
   carries a fact id or a near-verbatim statement. Calls
   `ingest(ingest_root, ENTITY_KINDS, incremental)` (the fixed entity-kind
   vocabulary, the same for every arm), then runs every query in
   `queries/mix.yaml`: each query's first (cold) call is timed and kept as
   the result; `--repeats` (default 20) further warm calls follow, discarded
   except for `p50_ms`/`p95_ms`. `--budget-tokens N` sets
   `ASBUILT_BUDGET_TOKENS` for a prototype's own `bench.llm.CountingClient`
   to read; `bench.llm.BudgetExceeded` from `ingest` prints the stop message
   and exits non-zero rather than writing a partial results file.
   `--reset` calls `bench/reset.py`'s `reset_arm` first. `--prototype null`
   uses the always-empty baseline (`bench/null.py`); see "Prototype
   contract" below for adding a real one.

   **Operations** (D-013): `bench/llm.py`'s `CountingClient` wraps any
   `messages.create`-shaped client (no vendor SDK imported here), counting
   calls and tokens and enforcing a budget — at 80% of it, the next call is
   refused, `build/stop-<arm>.json` is written with the counts, and
   `BudgetExceeded` is raised; `Embedder` is the same shape for embedding
   calls. `bench/reset.py --arm <name>` runs `prototypes/<name>/reset.sh` if
   present, else `docker compose down -v` in that directory if it has a
   `docker-compose.yml`, then clears `build/ingest/` (`null` just clears
   `build/ingest/`, having no store). Convention, not enforced in code: only
   one arm's compose stack runs at a time.

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
surface-specific fields. `explain`/`contradictions` take an entity NAME
(`truth/entities.yaml`'s `name` field, e.g. `farebox`), never an `E-` id —
arms return names too (D-013; see "Prototype contract" below) — and need no
`expects`: the scorer derives expected results from `truth/` itself (facts
naming the given entity; planted contradictions naming it, or every one if
omitted). `search`, `ask` need an explicit `expects` (a list of truth fact
ids); `stale` needs `since`, either a date-only string or a full ISO datetime
— the scorer compares it against history-step dates by dropping the UTC
offset from both sides whenever one is naive.

## Prototype contract

`bench/protocol.py` is the interface (`ingest`, `explain`, `search`, `ask`,
`contradictions`, `stale`) and the document-id conventions every prototype
must use (`wiki/<slug>`, `ticket/<KEY>`, `doc/<id>`, `pull/<number>`,
`code/<path>`, `run/<run-id>`). `bench/truth.py`'s module docstring fixes the
mapping from those ids to files on disk (`sources/wiki/<slug>.md`,
`system/<path>`, `runs/<run-id>.json`, ...) — the same mapping the scorer
uses to check that a carrier document actually exists.

`Fact.entities` are entity NAMES (D-013), never the `E-` id: a prototype
resolves its own entities and returns them by name (`explain`/`contradictions`
queries pass a name in too, never an id); the scorer aligns a returned name
to a truth id through `truth/aliases.yaml`, which prototypes never see, so
entity resolution is itself measured. A returned fact still credits only
when it shares a resolved entity with the truth fact, cites one of its
carrier documents, and states the same numbers. `Fact` also carries an
optional `id` (the prototype's own stable id) and an optional `claim`
(`Claim(entity, attribute, value, unit)` — a numeric fact's identity across
re-ingest, D-013). `ingest(fixture_root, entity_kinds, incremental=False)`
takes the fixed entity-kind vocabulary (`bench/run.py`'s `ENTITY_KINDS`, the
same set and order for every arm) and, when `incremental` is True, is being
handed a *later* ingest root to advance an already-ingested store rather
than start over (the incremental phase: through c5, then through c6).
`IngestReport` also carries `model`, `embedder`, `calls`, `embedding_tokens`
and `cache_tokens` — see `bench/llm.py`.

A prototype named `X` (anything but `null`) must be importable as
`prototypes.X:Prototype` from `spike/prototypes/X/__init__.py`, exposing a
class named `Prototype` with no required constructor arguments. `bench/run.py`
puts the `spike/` directory on `sys.path` itself, so this works regardless of
how it's invoked.

## The test connector

`connectors/tests/` turns the fixture's own pytest/Vitest suite into cited
candidate facts, per D-013's provenance tiers. It has two halves:

- **Static.** `collect.py` walks `tests/**/test_*.py` with `ast` (no
  execution) into one `Skeleton` per test function — node id, file, line,
  docstring, markers (including `skip`/`xfail`/`parametrize`, one skeleton
  per parametrize case), fixtures, imports, called/compared names, and every
  `assert`'s operands — and tolerantly line-scans `*.test.ts`/`*.spec.ts`
  for `describe`/`it`/`expect` (no tree-sitter). `collect_from_timeline`
  collects at any history step via `bench.build.Timeline`, materialized to a
  temp directory.
- **Extraction.** `extract_rules.py` is a deterministic extractor: one
  ONE-SENTENCE `statement` per test, never past its own assertion, built
  from the test's own name (e.g. `test_lost_bike_fee_150` → "Lost bike fee
  $150.00." — the name's own trailing number upgraded to its primary
  assert's money value); every assertion clause, API/error clause and event
  clause instead goes into a separate `detail` field (semicolon-joined,
  carried for arms and readers but never matched against truth — appending
  them to `statement` itself was tried and reverted: the matcher's
  similarity is a word-overlap coefficient over the whole statement, and
  enough unrelated clause words pushed even a correct name sentence below
  its threshold). Claims come from module-level constants the test's own
  assertions reference first, falling back — conservatively, only when
  confident (a sole or name-word-matching money/cents/count comparison,
  never an HTTP status or a bare length) — to a claim derived from the
  test's own name when no constant resolves. Category is a business-logic/
  technical-implementation heuristic on the test's own name and file path.
  `extract_model.py` is the model alternative — one structured-output call
  per skeleton through `bench.llm.CountingClient`, with a provider behind
  the same interface either way. **`claude-code`** (the default) is one
  `claude -p` subprocess per skeleton, running on Oleg's Claude Code
  subscription — never an API key, per his own decision. It needs
  `CLAUDE_CODE_OAUTH_TOKEN` in the environment, or, if unset, a token file
  at `~/.config/konyklabs/claude-code-oauth-token` — a credential, so it
  lives on disk only, is read into the subprocess's own environment, and
  never appears in a citation, a log, or a commit (the org's proprietary-
  terms/secrets rule, restated for this one). **`anthropic`** (`--provider
  anthropic`, opt-in) needs `ANTHROPIC_API_KEY` and the optional `model`
  dependency group (`uv sync --extra model`) instead. `--model-dry-run`
  builds every prompt and prices it from a stated, labelled rate table
  without making a call, under either provider; the smoke test (`--limit N`
  with `--extractor model`) is the only mode that makes real calls, and none
  are made anywhere in this repo's own tests — a fake `claude` executable on
  `PATH` proves the `claude-code` subprocess wiring instead
  (`tests/test_connector_model.py`).

Dynamic evidence comes from `evidence.py`, which reads pytest-json-report,
pytest-reportlog, JUnit XML (pytest's own shape and the generic
testsuite/testcase shape, with commit from a `<property name="commit">` or a
`.commit.txt` sidecar) and Vitest JSON (fullName rebuilt from
`ancestorTitles + title`, matching `bench/truth.py`'s own convention) into
per-test-id outcomes with an attempt number.

`lift.py` applies D-013's tier rule at a target commit: **executed** when a
passing run exists at some earlier-or-equal commit and neither the test file
nor the source files its imports approximate (`git diff --name-only`
between the two, in the built repo) changed since; otherwise **code**. A
failing run at the target commit demotes to `code` and opens a contradiction
candidate (statement, failing run id, code citation). Skipped and xfail
never lift on their own but don't erase an earlier still-valid proof.
A commit whose attempts disagree (attempt 1 fails, the rerun passes) neither
lifts nor demotes and is marked `flaky` — D-013 is silent here, so this
connector follows the fixture's own stated reading
(`truth/planted-runs.yaml`'s `rules`): a flaky commit's own runs are never
cited, and the fact simply keeps the tier its latest conclusive (non-flaky)
step already gave it, without re-checking that step's proof against the
flaky commit's own code state.

Run it with:

```
uv run python -m connectors.tests --fixture . --step c6 --extractor rules
uv run python -m connectors.tests --fixture . --all-steps --extractor rules
uv run python -m connectors.tests --fixture . --step c6 --extractor rules --model-dry-run
uv run python -m connectors.tests --fixture . --step c6 --extractor model --limit 3
```

The last one is the smoke test: `--limit N` caps a real `--extractor model`
run to the first N tests, so trying the provider costs at most N calls;
`--provider` picks `claude-code` (default) or `anthropic`.

Each processed step writes `build/connector/tests-<step>.json`: a list of
protocol-shaped Facts (citing `code/tests/...::node` at the step's SHA
always — with the step id itself alongside as `step`, for a human reader —
plus `run/<run-id>` when `executed`), `contradiction_candidates` (each
carrying `opened_step`, the step where the demotion first happened — a
candidate persists across a later step with no fresh run, as long as the
test still exists and hasn't passed again), `flaky` and `skipped` node ids,
and `counts`. `--model-dry-run` additionally prints token/dollar totals
without making a call. `connectors/tests/RUNNERS.md` documents how to
actually produce `runs/` output for a CI-sourced corpus.

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

`tests/test_leaks.py` exercises the ingest-root leak scanner (`find_leaks`)
against synthetic content directly, and, marked `fixture` like
`tests/test_fixture.py` (skips if `truth/facts.yaml` is absent), against the
real fixture's own assembled ingest root — also running
`tools/check_code_leaks.py`'s stronger 0.5-similarity rule over the root's
code, imported from there rather than reimplemented. The leak count is
always printed and in the assertion message, not just a bare pass/fail.

```
uv run pytest
uv run ruff check .
```

`ruff check .` covers the whole `spike/` tree, including `truth/` and
`sources/`, which are authored separately; `uv run ruff check bench tests`
scopes it to this harness's own deliverables.
