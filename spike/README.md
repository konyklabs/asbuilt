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
   The matcher itself is calibrated: `bench/score.py --calibrate` runs the
   118 invented paraphrase pairs in `tests/fixtures/calibration.yaml`
   (1.0/1.0), and `--calibrate tests/fixtures/calibration-model-run.yaml`
   the 89 pairs judged from the test connector's first real model run plus
   targeted pairs per rule (asbuilt#17: precision 1.0, recall 0.64 by
   design — the misses are narratives of a test scenario, not matcher
   defects). The rules a fuller statement is held to — HTTP codes set
   aside, extra numbers only of a kind the fact does not use, flag state as
   its own polarity, a claim naming the entity its own way handed to the
   statement rule — are in the module docstring under asbuilt#17.

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
  the same interface either way. Its prompt (asbuilt#18, after the first
  real run returned true sentences about the test's own scenario) asks for
  the general rule the test proves, keeps the scenario in `detail`, wants
  the claim as the rule's own quantity in the code's unit rather than a
  total the test computed, names the system's entity kinds, allows a
  status code only when the fact is about the response, and makes no call
  for a skipped test (its rules guess stays). **`claude-code`** (the default) is one
  `claude -p` subprocess per skeleton (a timeout, a crash — a non-zero
  exit with no result object — or an upstream API error, the result
  object's `api_error_status`, is retried once after a pause,
  `ASBUILT_RETRY_PAUSE`, and counted under `retries`; a model-level error
  such as `error_max_turns` is never retried; the reason quotes what the
  CLI said on stderr or, in JSON mode, the result object's `errors` on
  stdout — asbuilt#21), running on Oleg's Claude Code
  subscription — never an API key, per his own decision. It needs
  `CLAUDE_CODE_OAUTH_TOKEN` in the environment, or, if unset, a token file
  at `~/.config/konyklabs/claude-code-oauth-token` — a credential, so it
  lives on disk only, is read into the subprocess's own environment, and
  never appears in a citation, a log, or a commit (the org's proprietary-
  terms/secrets rule, restated for this one). Every `ANTHROPIC_*` variable
  is stripped from that same subprocess environment first: `-p` mode
  prefers `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` over the OAuth token
  whenever both are set, which would otherwise silently switch a
  claude-code call onto API-key billing the moment the parent process
  happens to export one; every `CLAUDE_CODE_USE_*` backend selector
  (`_BEDROCK`/`_VERTEX`/`_FOUNDRY`) and `AWS_BEARER_TOKEN_BEDROCK` are
  stripped the same way, so none of them can silently route a call onto a
  cloud account instead. This covers the process environment only — a
  settings-file `apiKeyHelper` is a separate credential path outside it,
  and stays the operator's own responsibility to keep unset here.
  **`anthropic`** (`--provider anthropic`, opt-in) needs `ANTHROPIC_API_KEY`
  and the optional `model` dependency group (`uv sync --extra model`)
  instead. `--model-dry-run` builds every prompt and prices it from a
  stated, labelled rate table and makes no call at all, under either
  provider, whether or not `--extractor model` is also given — `--extractor
  model` without `--model-dry-run` is what makes a real call, one per unskipped test
  (or per `--limit N` tests, for the smoke test); none are ever made
  anywhere in this repo's own tests — a fake `claude` executable on `PATH`
  proves the `claude-code` subprocess wiring instead
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

The last one is the smoke test: `--limit N` caps only how many tests get a
REAL model call (at most N), never the written output — every other test in
the step keeps its rules-extractor guess, so `tests-<step>.json` still
covers the whole step. With no explicit `--out`, a `--limit`ed run writes
`tests-<step>-limit<N>.json` instead of `tests-<step>.json`, so it can never
overwrite a full run's own file. `--provider` picks `claude-code` (default)
or `anthropic`.

Each processed step writes `build/connector/tests-<step>.json`: a list of
protocol-shaped Facts (citing `code/tests/...::node` at the step's SHA
always — with the step id itself alongside as `step`, for a human reader —
plus `run/<run-id>` when `executed`), `contradiction_candidates` (each
carrying `opened_step`, the step where the demotion first happened — a
candidate persists across a later step with no fresh run, as long as the
test still exists and hasn't passed again), `flaky` and `skipped` node ids,
and `counts`. After a real model run the file also carries `model_usage`
(provider, model, skeletons requested, results, calls, input/output/cache
tokens, seconds, dollars at the assumed price table, `usage_missing`, and
`stopped` or `failed` when the run did not complete: every fact extracted
before the refused call is kept (the call that crosses the threshold is
counted, its response discarded, so `results` is one below `calls` on a
stop), the rest keep their rules guess, the run halts there even
under `--all-steps` (the next step would spend the same budget again on a
fresh counting client), the file is named `tests-<step>-stopped.json` or
`-failed.json` unless `--out` was given, and the CLI exits 3 on a budget
stop or 2 on a provider failure — asbuilt#15, after the first full run lost
16 extracted facts to a bare budget stop) and prints one `model:` line with
the same numbers. `--model-dry-run` prints token/dollar totals
without making a call; measured on that first run, one headless call writes
about 8,050 tokens to the cache (the CLI's own system prompt) on top of the
prompt, so the estimate adds that per call and prices input at the
cache-creation rate for `claude-code` (the `anthropic` path: prompt text
alone at the input rate). `connectors/tests/RUNNERS.md` documents how to
actually produce `runs/` output for a CI-sourced corpus.

## The baseline arm and the MCP adapter

`prototypes/baseline/` (asbuilt#9) is the no-store baseline (D-013): the
corpus handed to the model directly, no store behind it. `ingest()` reads
the assembled ingest root into an in-memory document manifest — `code/<path>`
for every non-binary file under `repo/` (skipping `node_modules` and the
other directories `bench.build.EXCLUDED_DIRNAMES` already excludes),
`wiki/<slug>`, `doc/<id>`, `ticket/<KEY>`, `pull/<n>` (one per file under
`sources/<kind>/`, id = the filename stem) and `run/<id>` (one per
`runs/*.json`) — and makes no model call: zero tokens, `documents` set to
the manifest's size. Every query surface (`explain`, `search`, `ask`,
`contradictions`, `stale`) then issues exactly one structured call through
`bench.claude_code.structured_call`, wrapped in one `bench.llm.CountingClient`
kept for the prototype's whole lifetime, so the 80% budget stop (D-013)
applies across every query, not per call.

Two variants, `ASBUILT_BASELINE_VARIANT` (default `full`):

- **`full`**: the whole corpus goes into the prompt (a `=== <document id>
  ===` header per document) alongside the query, the allowed entity kinds
  and an output schema. If the corpus's estimated size (`len(text) // 4`
  against `ASBUILT_BASELINE_MAX_TOKENS`, default 150k) is over the estimate,
  that query falls back to the `grep` call instead.
- **`grep`**: one headless `claude -p` call with tools enabled (`--tools
  Read,Grep,Glob`), working directory set to the ingest root, and a turn cap
  (`ASBUILT_BASELINE_GREP_TURNS`, default 6) — the model reads the corpus
  itself; the prompt explains the on-disk layout and the document-id
  convention it must reconstruct.

A `code/<path>` citation's `version` is the SHA `build/commits.json`
(`bench.build.build`'s own output) records for the ingest root's own history
step, read from `step.json` — a small file `bench.run.assemble_ingest_root`
now writes into every root it assembles, recording which `--through-step` it
was built from, so an incremental run's two phase roots each resolve to
their own correct step rather than guessing from `commits.json` alone (see
`prototypes/baseline`'s module docstring for the narrower fallback used when
a root wasn't produced by `assemble_ingest_root` at all).

`bench/claude_code.py` (moved from `connectors/tests/extract_model.py`,
which still re-exports every name so nothing that already imported it
breaks) is `ClaudeCodeClient`'s new home: the `claude -p` subprocess
provider, generalised to accept `tools`/`cwd`/`max_turns`/`timeout` so the
baseline's `grep` variant can enable tools and set a working directory,
which the test connector's own no-tools call never needed.
`structured_call(client, system, prompt, schema)` is the generic "one
structured call, through the one wrapped client" helper both the connector
and every arm use.

The prompt travels over stdin, never as an argv element (review fix,
asbuilt#9): the `full` variant embeds the whole corpus — hundreds of KB on
the real fixture — and Linux caps a single argv element around 128 KB
(`ARG_MAX` is much larger, but the per-argument limit still applies; macOS
tolerates it, which is why this shipped once uncaught). `subprocess.run(...,
input=prompt)` also means a `claude -p` subprocess launched from inside
`asbuilt_mcp.py`'s own stdio server never inherits the server's JSON-RPC
pipe on stdin — it gets its own pipe, written once and closed. Every call
also passes `--strict-mcp-config` (verified present via `claude -p --help`
on the installed CLI) so it loads no project-scoped MCP servers — without
it, a call made with `spike/` as its cwd would also try to load a
`.mcp.json` there, if one existed — and has a `timeout` (default 600s,
`ASBUILT_BASELINE_TIMEOUT` for the baseline arm) that raises `RuntimeError`
rather than leaving a hung subprocess; a timeout, a crash or an upstream
API error is retried once after `ASBUILT_RETRY_PAUSE` (asbuilt#21), so a
baseline query's wall clock is bounded by two timeouts plus the pause, and
the baseline's `stats()` counts the retries.

### The MCP adapter

`asbuilt_mcp.py` is a thin [FastMCP](https://gofastmcp.com) server over any
`bench.protocol.Prototype` — the sequence's own promise (D-013): the
invented system can be queried from a Claude Code session during the spike,
using the same tool contract a real ingest would serve behind. Not named
`mcp.py`: Python puts a script's own directory first on `sys.path` before
any of its code runs, so a same-directory `mcp.py` shadows the real `mcp`
package `fastmcp` itself imports (confirmed by trying it — a
`ModuleNotFoundError` importing `mcp.server`, because the import resolved to
this file instead of site-packages).

`ASBUILT_ARM` selects the prototype (default `null`; `baseline`; later
`b_postgres`, looked up the same way `bench.run.load_prototype` is);
`ASBUILT_FIXTURE` names the fixture root to ingest FROM — this module
assembles its own ingest root through the fixture's last history step,
exactly as `bench/run.py` does for a scored run, never handing `ingest()`
the raw fixture. Ingestion is lazy and thread-safe: the first tool call
triggers it, guarded by a lock with a double check, since fastmcp 4.0.10
runs sync tools in a threadpool and two requests can otherwise race to
`ingest()` twice (a review-caught concurrency bug — two parallel first
calls both rebuilding the ingest root).

Tools: `search`, `explain` (an entity name), `entities` (a name lookup —
`bench.protocol.Prototype` has no first-class entity directory, so this is
derived: the distinct entity names across `search(name)`'s own returned
facts, a stated interpretation, not a separate store query),
`contradictions`, `stale`, `ask`. Every result carries `structuredContent`
(the facts/sentences/contradictions with their citations) and a text block
with the same content rendered as inline-cited lines. `search`/`explain`/
`contradictions`/`stale` paginate with `limit`/`offset` (default page 20,
capped at 100); invalid arguments and a failing prototype surface as MCP
tool errors (`fastmcp.exceptions.ToolError`), never a raw exception.

`uv sync --extra serve` installs `fastmcp` (pinned exact in `pyproject.toml`,
since this is a dependency real Claude Code sessions load at runtime, not
just this repo's own tests — also listed in the `dev` group so a plain
`uv sync` already has it for `tests/test_asbuilt_mcp.py`'s in-process
client). `plugin/.claude-plugin/plugin.json` and `plugin/.mcp.json` register
the server as a Claude Code plugin — in its own `plugin/` subdirectory, not
`spike/` itself (review fix): `spike/` is the harness's own documented cwd
for every `claude -p` benchmark call, and a `.mcp.json` sitting there too
would be picked up as a *project-scoped* server on top of `--strict-mcp-
config` guarding the calls this code makes itself, which is one hazard
fewer to reason about. The command is `uv run --project
${CLAUDE_PLUGIN_ROOT}/.. --extra serve python
${CLAUDE_PLUGIN_ROOT}/../asbuilt_mcp.py` (`..` because the plugin root is
`spike/plugin`, one level below the `uv` project and `asbuilt_mcp.py`
itself), with `ASBUILT_ARM`/`ASBUILT_FIXTURE` passed through from the
launching environment. Try it:

```
cd spike
ASBUILT_ARM=baseline ASBUILT_FIXTURE=. claude --plugin-dir plugin
# then, in the session: use the asbuilt MCP server's explain tool on "farebox"
```

### Trying a benchmark run's own transcript

`bench/run.py --transcript build/transcripts/<arm>-<step>.md` writes a
markdown file alongside the results JSON: one `##` section per query
actually run, with the question, the answer (facts as lines, or the `ask`
sentences) and its citations — so a benchmark run doubles as a demo script,
not just a scored artefact. `--only-surfaces explain,contradictions` runs
(and transcribes) just that subset of the query mix, for a quick check.

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

## Stack B

Our own fact model on Postgres + pgvector (konyklabs/asbuilt#4, D-013's
default stack). Two halves:

- **`pipeline/`**, shared by every arm and written once against the
  write-side `StoreInterface` (`pipeline/store.py`: upsert fact, supersede,
  link contradiction, query by entity, time, text and vector, snapshot).
  `lift.py` applies the test connector's tiers, candidates and supersessions;
  `resolve.py` maps names to entities (exact name, alias, separator-folded,
  then embedding similarity within a kind, else a new entity);
  `contradict.py` joins claims and, for prose, runs the NLI pre-filter then a
  model verdict; `stale.py` flags documented facts the code has moved past;
  `history.py` and `sources.py` give every document its version.
  `MemoryStore` implements the interface in pure Python for the unit tests.
- **`prototypes/b_postgres/`**: `schema.sql` (plain SQL), `store.py` (psycopg
  3, recursive CTEs for traversal, a GIN `tsvector` index, HNSW cosine on
  `vector(384)`), `extract.py` (one structured call per wiki page, document,
  ticket or pull request, citation mandatory in the schema), and `Prototype`
  in `__init__.py`. Module docstrings carry the exact rules.

The test connector needs git history the ingest root does not carry (a
passing run proves a test only if nothing it exercises changed since), so
the arm builds the invented system's repository with `bench/build.py`'s
reproducible SHAs into `build/b_postgres/` on every ingest, or reads one
from `ASBUILT_B_BUILT` (a directory with `repo/` and `commits.json`). It
never reads `system/history/steps.yaml` itself.

### Commands

```
uv sync --extra pipeline                       # psycopg, sentence-transformers (torch)
cd prototypes/b_postgres && docker compose up -d --wait && cd ../..
ASBUILT_B_NO_MODEL=1 uv run python bench/run.py --prototype b_postgres --fixture .
uv run python bench/score.py build/results-b_postgres.json
uv run python -m prototypes.b_postgres --dry-run --fixture .   # token estimate, no call
prototypes/b_postgres/reset.sh                 # down -v, then up --wait; --down stops there
```

Where the `docker compose` plugin is missing (colima with Homebrew),
`docker-compose` is the same command; `reset.sh` picks whichever exists.

- **Port.** `ASBUILT_PG_PORT`, default 55432, bound to 127.0.0.1. Trust
  auth on loopback, so no credential lives in the repository.
  `ASBUILT_PG_DSN` overrides the whole DSN; `ASBUILT_PG_SCHEMA` (default
  `asbuilt`) names the schema.
- **Reset.** A full ingest (`incremental=False`) drops and re-applies the
  schema by itself; `reset.sh` (what `bench/run.py --reset` runs) also
  deletes the named volume.
- **Incremental.** A text document is registered at its new version only
  after its facts are stored, so a budget stop or a crash mid-extraction
  leaves it pending and the next ingest extracts it. `bench/run.py
  --incremental` copies `sources/` whole into both phases
  (`assemble_ingest_root`), so no document version changes between them: the
  incremental measure exercises the code steps and the runs only, until a
  document-version delta is planted in the fixture.
- **Embedder.** `sentence-transformers/all-MiniLM-L6-v2` at revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` (Apache-2.0, 384 dimensions),
  cached under `build/models/`. `ASBUILT_EMBED=fake`, or sentence-transformers
  not installed, selects the deterministic hash embedder of the same
  dimension; the `IngestReport.embedder` field says which ran and why.
- **NLI.** `cross-encoder/nli-deberta-v3-base` at revision
  `6c749ce3425cd33b46d187e45b92bbf96ee12ec7` (Apache-2.0), same cache. Skipped
  when not installed or `ASBUILT_NLI=off`; a lexical stand-in then feeds the
  model verdict, and the ingest log says so.
- **No-model mode.** `ASBUILT_B_NO_MODEL=1` makes no model call at all: no
  document extraction (text documents stay pending, unregistered), no prose
  verdict, `ask` composes one sentence per fact deterministically. What remains is the test connector's `executed`
  and `code` facts, the run-vs-code contradiction, and supersession; there
  are no `documented` facts, so documented-tier recall is zero and `stale`
  is empty by construction.
- **Model mode** (unset `ASBUILT_B_NO_MODEL`) calls `claude -p` on the
  owner's subscription through the connector's `claude-code` provider, every
  call through `bench.llm.CountingClient`; `bench/run.py --budget-dollars`
  is the stop condition. Run the dry run first.

### Tests

```
uv run pytest tests/test_pipeline_*.py tests/test_b_prototype.py   # no Docker
uv run pytest -m postgres                                          # a throwaway pgvector container
```

`tests/test_b_postgres.py` runs the store contract from
`tests/_support/store_contract.py` (the same one `MemoryStore` passes) and
the real-fixture integration test on a testcontainers container, skipped
when Docker does not answer. With colima, the fixture takes `DOCKER_HOST`
from the active Docker context. No test makes a model call: they use a fake
client or a fake `claude` on `PATH`.
