# asbuilt

What a system actually does, as built. A knowledge base for large, badly
documented legacy systems: gathered from the code and from every place the
documentation is scattered, held in a real database, and queryable by people
and agents with provenance on every answer.

> **Status: spike.** Nothing runs yet. The driving idea is
> [konyklabs/roadmap#153](https://github.com/konyklabs/roadmap/issues/153);
> the leverage-versus-build spike is
> [konyklabs/roadmap#154](https://github.com/konyklabs/roadmap/issues/154),
> recorded in D-013. The storage engine is decided by the benchmark under
> `spike/`, and not before.

## The problem

A system that has been in production for a decade is described in four
places, and none of them agrees:

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
Fact           one claim about the system, in one category, with a confidence
               └─ cites → Document (+ location: line, anchor, comment id)
Entity         a named thing facts are about: component, service, table, rule, job, team
               └─ Fact ─about→ Entity;  Entity ─relates(kind)→ Entity
Contradiction  two facts that cannot both hold, with the newer one marked
Snapshot       the base at a point in time, so "what did we know in June" is answerable
```

This is a sketch to argue with, not a schema. The engine ADR settles it.
D-013 adds one thing to every fact: a **provenance tier**, executed (a test
ran and passed, at a commit, on a date) above code (read from source at a
commit) above documented (a page, a ticket, a comment). Test suites are a
source of their own, and a passing run is what lifts a statement to the top
tier; a statement with no passing run is a code-tier claim, and a passing
test proves exactly what it asserted, no more.

## Storage engine: the open spike

The requirement is an established, industry-standard engine: one that holds
facts, relationships, text search and vectors, runs locally in a container and
cheaply in the cloud, and that agents can query without a bespoke DSL.
Candidates, to be tested rather than argued:

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

**Working hypothesis for the spike:** PostgreSQL with pgvector, because it is
the most established engine that covers all four patterns, and Python and
TypeScript both have first-class drivers. A graph engine is the challenger if
relationship traversal turns out to dominate the query mix.

**Two ADRs, not one.** The first half of the spike, what to leverage, what
to build and in which language, is recorded in D-013: build, Python, and a
benchmark of two stacks (Graphiti on a graph store; our own fact model on
Postgres + pgvector) on one synthetic system with one fixed query mix (the
five surfaces under "Agent access", weighted). The engine, the first cut of
the schema above and the fate of `spike/` are the second ADR, written from
the benchmark's numbers. The synthetic system and the benchmark harness live
in this repository under `spike/`; that ADR either promotes them to
`tests/fixtures/` or deletes them. That is not the build: nothing lands under
`src/` before it.

## Ingest

One connector per source, each against the source's public API only:

```
fetch (incremental, from the last cursor)
  → normalise (to Document, versioned)
    → extract (facts and entities, by a model, with the citation kept)
      → store (with provenance; contradiction check against existing facts)
```

Connectors in build order: **GitHub** first (it needs no private data to
develop against, and code is the source closest to the truth), then
Confluence, Jira, Google Drive. The GitHub connector reads both a repository's
discussion surfaces (issues, pull requests, READMEs, ADRs) and its code;
`code` is a separate Source kind so that a fact from a comment and a fact from
a function are never confused, but it is the same connector. Extraction is
where the model runs; nothing downstream of it is trusted without its
citation.

## Agent access

An MCP server, and a typed client in the same package, exposing:

- `search(query, category?, since?)`: ranked facts with citations
- `explain(entity)`: everything known about one component, rule or job, by category
- `contradictions(entity?)`: what the sources disagree on
- `stale(since)`: facts whose source has changed since they were extracted
- `ask(question)`: the composed answer, every sentence cited

Every response carries provenance. A consumer that drops it is doing it wrong.

## Boundaries

This organisation's cleanroom rule applies in full. `asbuilt` is a generic
tool developed against **synthetic fixtures and public API surfaces only**. No
proprietary system's knowledge, structure, vocabulary or data enters this
repository, its issues, its tests or its examples. The problem it solves is
the generic shape of a problem most organisations with a decade-old system
have; the fixtures describe an invented one.

## Repository layout, planned

```
src/asbuilt/
  model/        the knowledge model: Fact, Entity, Document, Source, Contradiction, Snapshot
  store/        the engine adapter behind one interface; the spike decides the first
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

1. **Spike** (in progress): D-013 leverage versus build; the harness and
   the invented system under `spike/`; two prototypes; the engine ADR.
2. **Schema and one connector.** The knowledge model in the chosen engine,
   point-in-time snapshots included from the start because they are hard to
   add later, the GitHub connector, extraction with citations.
3. **Query surface.** The MCP server and client; `search` and `explain`.
4. **Remaining connectors.** Confluence, Jira, Google Drive.
5. **Contradiction and staleness.** The detection pass and the two queries.
6. **Composed answers.** `ask`, once every fact it could cite is in.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
