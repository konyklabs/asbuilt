# asbuilt

What a legacy system actually does, as built: proven by its tests, read
from its code, and checked against every document that claims otherwise. A
knowledge base held in a real database, queryable by people and agents, with
provenance on every answer and the disagreements between sources made
explicit rather than averaged away.

> **Status: spike.** Nothing runs yet. The driving idea is
> [konyklabs/roadmap#153](https://github.com/konyklabs/roadmap/issues/153);
> the leverage-versus-build spike is
> [konyklabs/roadmap#154](https://github.com/konyklabs/roadmap/issues/154),
> recorded in D-013: the store is Postgres + pgvector by constraint, and the
> benchmark under `spike/` decides the extraction pipeline, not before.

## The problem

A system that has been in production for a decade is described in five
places. One of them is proof; the other four are claims, and none of them
agrees:

- **The test suite**: the only description that is executed. A passing test
  is a verified statement about behaviour with the strongest provenance
  there is: it ran, it passed, at this commit, on this date. Nobody reads a
  suite of thousands of tests as documentation, so this proof goes unused.
- **Jira**: what was asked for, and sometimes what was decided, in a comment
  thread nobody will find again.
- **Confluence**: what somebody wrote down once, usually at design time.
- **GitHub**: READMEs, ADRs, code comments, PR discussions. Closest to the
  truth, hardest to read as a whole.
- **Google Drive**: a random set of documents, slides and sheets that hold
  the rest.

The only authoritative description is the running system itself. So every
engineer, and now every agent, rebuilds the same understanding from scratch,
per question, and then loses it. Onboarding takes months; an agent's context
starts empty every session.

The name is the construction industry's term for the fix. *As-built* drawings
record what was actually constructed, as opposed to the design drawings.

## What asbuilt is

A tool that ingests all of those sources plus the code, extracts what the
system does into a **categorised knowledge base**, and serves it from a
**real database** that agents can query.

### Categories

| Category | Holds | Example question |
|---|---|---|
| Business logic | The rules the system enforces, and where each one lives | "What decides whether an account can be closed?" |
| Technical implementation | Components, data flows, integrations, contracts, schemas | "Which services read the accounts table?" |
| Operations | How it is run, deployed, monitored, and what breaks | "What is the rollback procedure for the nightly export job?" |
| *(more as needed)* | Product history, decisions, ownership, glossary | "Why does the API have two versions of this endpoint?" |

Categories are a facet on every fact, not separate stores: one question often
spans several.

### Three properties that are not negotiable

1. **Provenance on every fact.** Where it came from (source system, document,
   line, commit), when, and who. An answer without a citation is not an
   answer.
2. **Freshness and contradiction are first-class.** When the wiki says X and
   the code says Y, the tool says so, and says which is newer. It never
   averages.
3. **A database, not a document.** The store is an established engine that
   supports the four access patterns we expect agents to use: exact lookup,
   relationship traversal, full-text search, and semantic (vector) search.
   Whether that is the real query mix is one of the things the spike's
   benchmark tests.

## What asbuilt is not

- Not another wiki. It points back at the sources; it does not replace them.
- Not a chatbot over PDFs. Retrieval is one access path among four.
- Not a code-search tool, though code is one of its inputs.
- Not a general-purpose agent memory. It models one system's knowledge.

## The knowledge model, first cut

```
Source         a system of record: jira | confluence | github | gdrive | code | tests
Document       one addressable thing in a source (issue, page, file, commit), versioned
Fact           one claim about the system: a stable id, one category, a tier derived from
               what it cites (executed > code > documented), and, when numeric, a structured
               claim (entity, attribute, value, unit) that is its identity across re-ingest
               └─ cites → Document (+ location: symbol, test id, anchor, comment id)
Entity         a named thing facts are about: component, service, table, rule, job, team
               └─ Fact ─about→ Entity;  Entity ─relates(kind)→ Entity
Contradiction  two facts that cannot both hold, with the newer one marked
Snapshot       a named point in stored time (created_at / expired_at), never a copy, so
               "what did we know in June" is answerable; every query surface takes as_of
```

This is a sketch to argue with, not a schema. The pipeline-and-schema ADR settles it.
D-013 adds one thing to every fact: a **provenance tier**, executed (a test
ran and passed, at a commit, on a date) above code (read from source at a
commit) above documented (a page, a ticket, a comment). Test suites are a
source of their own, and a passing run is what lifts a statement to the top
tier; a statement with no passing run is a code-tier claim, and a passing
test proves exactly what it asserted, no more.

## The store, and the benchmark

The store is decided by constraint, not by benchmark: **Postgres + pgvector**,
the one established engine that holds facts, relationships, text search and
vectors, runs locally in a container and on RDS or Aurora with no rewrite,
idles at near-zero cost, and puts no third party in the path (D-013, from
the spike's R7). The table below is the candidate list the spike evaluated
and why each other engine lost:

| Candidate | Shape | Why it is on the list | Cost of choosing it |
|---|---|---|---|
| PostgreSQL + pgvector (+ Apache AGE for graph) | Relational, with full-text search, vectors, optional graph | The most established option that covers all four access patterns in one engine; SQL is a query surface every agent already speaks | Graph traversal is bolted on and deep multi-hop queries get awkward; AGE ships per Postgres major, and its newest line is still a release candidate |
| Neo4j | Property graph | Knowledge-graph native; Cypher; the GraphRAG ecosystem targets it | Heavier to run; vector search (2023) and full-text (2018) are newer than the engine; Community is GPLv3 and single-instance, Enterprise and Aura are commercial |
| Memgraph | In-memory property graph | Lighter than Neo4j; Cypher-compatible | Smaller ecosystem; source-available under BSL 1.1, not open source |
| SQLite + sqlite-vec | Embedded, single file | Zero-ops and local-first; a laptop-sized base needs nothing more | Traversal only through recursive CTEs; concurrency and scale ceiling; sqlite-vec is pre-1.0 |
| Frameworks: Graphiti, Cognee, LightRAG (Microsoft GraphRAG is in maintenance mode) | Not engines: ingest and graph-building layers on top of one | Solve extraction and temporal edges so we do not have to; evaluated for the extraction step, not benchmarked as stores | Each pins or prefers an engine (Graphiti: Neo4j, FalkorDB, Neptune; LightRAG: pluggable, Postgres recommended) and a data model; adopting one is adopting its opinions |

Search engines (OpenSearch, Elasticsearch) and vector-only stores are
retrieval layers, not systems of record, and are out unless the spike finds
the chosen engine's search is not enough. Kùzu was on the list until its
upstream repository was archived in October 2025 after the company's
acquisition; it fails the "established" requirement on its own, whatever its
forks do. The claims in this table were checked against the projects' own
pages on 2026-09-28; re-check before the spike starts.

**What the benchmark decides is the extraction pipeline**, not the engine:
our own pipeline (stack B: Claude structured output against our schema)
against Graphiti's (stack A), both against a no-store baseline that hands
the corpus to the model directly, on one invented system with planted
ground truth under `spike/`. Its integrity rules, its measures (led by
executed-tier precision), its pre-registered decision rule and its spend cap
are in D-013. B runs first; A runs only if B misses a threshold or Oleg asks,
time-boxed. The test connector is built once, engine-independent, before
either arm, because both consume it.

**Two ADRs, not one.** D-013 records what to leverage, what to build, the
language, the store and the benchmark's rule. The second ADR, written from
the benchmark's numbers, records the pipeline, the first cut of the schema
above, the write-side store interface, and the fate of `spike/`: promoted to
`tests/fixtures/` or deleted. That is not the build: nothing lands under
`src/` before it.

## Ingest

One connector per source, each against the source's public API only:

```
fetch (incremental, from the last cursor)
  → normalise (to Document, versioned)
    → extract (facts and entities, by a model, with the citation kept)
      → store (with provenance; contradiction check against existing facts)
```

Connectors in build order: **tests** first (pytest collection and the test
source for the statements; run evidence from pytest-json-report, reportlog
or a CI run's JUnit XML with the commit attached, so no change to the suite
under test is needed; JavaScript runners next), then **GitHub** (code,
markdown, issues and pull-request threads; `code` is a separate Source kind
so that a fact from a comment and a fact from a function are never confused,
but it is the same connector), then Confluence, Jira and Google Drive.
Extraction is where the model runs; nothing downstream of it is trusted
without its citation. Ingest is incremental by commit and run id; only
changed documents are re-extracted. Connector credentials live on the
machine only and never enter the fact store, a citation or a log. Tickets
and comments carry people's names: retention, redaction and access are
answered no later than the first product slice.

## Agent access

An MCP server, and a typed client in the same package, exposing:

- `search(query, category?, since?, as_of?)`: ranked facts with citations
- `explain(name, as_of?)`: everything known about one component, rule or job, by
  category, ranked by tier; the name is resolved to an entity (`entities(query)`
  lists candidates), because a session knows names, not ids
- `contradictions(entity?)`: what the sources disagree on, and which side wins
- `stale(since)`: facts whose source has changed since they were extracted
- `report(area)`: explain, contradictions and stale over one service or team,
  written as a cited file and returned by link
- `ask(question)`: the composed answer, every sentence cited

Every response carries provenance, twice: in `structuredContent` for machines
and inline for the model, because MCP has no citation type. Results are
paginated under the client's result cap. A consumer that drops provenance is
doing it wrong. The tools ship as a Claude Code plugin, installed from the
git URL plus a compose file; nothing is published to a registry until Oleg
decides to.

## Boundaries

This organisation's cleanroom rule applies in full. `asbuilt` is a generic
tool developed against **synthetic fixtures and public API surfaces only**. No
proprietary system's knowledge, structure, vocabulary or data enters this
repository, its issues, its tests or its examples. The problem it solves is
the generic shape of a problem most organisations with a decade-old system
have; the fixtures describe an invented one.

The boundary at real use is different and stated in D-013: whether real
documents and code may be sent to a model API for extraction is the policy
of whoever owns the system, so the provider is configurable; where the
extracted store lives is the owner's call; nothing from a real ingest (facts,
fixtures, bug reports, memory) flows back into this repository; every
Document carries a visibility scope, and a fact is served only with the
citations the caller may read. A public open-source project may serve as a
second demo target, each in its own demo repository.

## Repository layout, planned

```
src/asbuilt/
  model/        the knowledge model: Fact, Entity, Document, Source, Contradiction, Snapshot
  store/        the write-side interface (upsert fact, supersede, link contradiction,
                query by entity, time, text, vector) and the Postgres adapter
  ingest/       one connector per source, plus the extraction step
  serve/        the MCP server and the typed client
  cli.py
tests/
  fixtures/     the invented system: a small codebase, wiki pages, tickets, docs
spike/          the storage-engine spike: synthetic system and benchmark harness, until the ADR
docs/
```

Python, per D-013.

## Working here

Read [`AGENTS.md`](AGENTS.md) before changing anything. The org's rules live
in the workspace and apply here unchanged: a task in `roadmap` before a push,
a conventional-commit PR title carrying the task ref, evidence pasted rather
than claimed, and squash merges only.

## Roadmap

1. **Spike** (in progress): D-013; the harness and the invented system
   under `spike/`; the test connector; the no-store baseline and stack B,
   with a thin MCP adapter so the invented system can be queried from a
   Claude Code session and every benchmark run writes a cited transcript;
   stack A under the rule; the report and the pipeline-and-schema ADR.
2. **Schema, tests and code.** The knowledge model in Postgres with fact
   identity and stored-time snapshots from the start; the test connector
   promoted to `src/`; the GitHub code and markdown connector; run evidence
   from CI.
3. **Query surface.** The plugin: `explain`, `search`, and `contradictions`
   limited to test-versus-document, with the winner shown.
4. **Reports and staleness.** `report(area)` and `stale`, composed from the
   above.
5. **Remaining connectors.** Confluence, Jira, Google Drive; the general
   cross-source contradiction pass with the NLI pre-filter; the JavaScript
   runners.
6. **Composed answers.** `ask`, once every fact it could cite is in.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
