"""The no-store baseline arm (D-013, asbuilt#9): the corpus handed to the
model directly, no store behind it at all. Ingest reads the assembled
ingest root into an in-memory document manifest and makes no model call
(zero tokens); every query surface issues exactly one structured call
through `bench.claude_code.structured_call`, wrapped in the one
`bench.llm.CountingClient` this arm keeps for its whole lifetime, so the
80% budget stop (D-013) applies across every query, not per call.

Two variants, `ASBUILT_BASELINE_VARIANT` (default `"full"`):

- **`full`**: the whole corpus goes into the prompt (file headers with
  document ids, per the protocol's id conventions) alongside the query and
  an output schema. If the corpus's estimated size (`len(text) // 4`,
  against `ASBUILT_BASELINE_MAX_TOKENS`, default 150k) exceeds the
  estimate, THAT query falls back to the `grep` call instead — the corpus
  is static per ingest, so in practice this means every query falls back
  once the fixture is large enough, but the check is made per call, not
  cached, so a smaller corpus (the harness's own mini fixture, a future
  incremental phase) still gets the direct-prompt path.
- **`grep`**: one headless `claude -p` call with tools enabled (`--tools
  Read,Grep,Glob`), working directory set to the ingest root, and a turn
  cap (`ASBUILT_BASELINE_GREP_TURNS`, default 6) — the model reads the
  corpus itself rather than having it pasted in, and the prompt explains
  the on-disk layout and the document-id convention it must reconstruct.

Every call's subprocess timeout is `ASBUILT_BASELINE_TIMEOUT` seconds
(default `bench.claude_code.DEFAULT_TIMEOUT_SECONDS`, 600) — passed straight
through to `ClaudeCodeClient`, which surfaces an expired timeout as the same
kind of `RuntimeError` every other `claude -p` failure raises. Since
asbuilt#21 that client retries a timeout, a crash or an upstream API error
once after `ASBUILT_RETRY_PAUSE` seconds (default 5), so one query's wall
clock is bounded by twice the timeout plus the pause, never by one timeout;
a model-level error (the grep variant's own turn cap, `error_max_turns`,
above all) is never retried. `stats()` reports the retries made.

Document ids (`bench/protocol.py`'s conventions): `code/<path>` (walking the
ingest root's `repo/`, skipping `node_modules`/`.git`/binaries — the same
`EXCLUDED_DIRNAMES` `bench.build` already excludes from the built
repository), `wiki/<slug>`, `doc/<id>`, `ticket/<KEY>`, `pull/<n>` (one per
file under `sources/<kind>/`, id = the filename stem) and `run/<id>` (one
per `runs/*.json`, id = the filename stem — matching `bench/truth.py`'s own
mapping). Every `code/` citation's `version` is the SHA `build/commits.json`
(`bench.build.build`'s own output) records for the ingest root's OWN history
step — read from `step.json`, which `bench.run.assemble_ingest_root` writes
into every root it builds (asbuilt#9), so an incremental run's two phase
roots (`build/ingest/phase-1`, `phase-2`) each resolve to their own correct
step rather than both falling to whichever step happens to be
`commits.json`'s last entry. A root not produced by `assemble_ingest_root`
at all (e.g. a hand-built one in a test) falls back to that last-entry
guess — a stated, narrower assumption, documented on `_find_commits_sha`
itself. No `commits.json` found anywhere above the root (a scratch fixture
never built) means `version=None`, which `Citation` already allows.
Non-code citations carry no version — the ingest root's sources/runs files
don't carry a separate version field a baseline could cite without
inventing one.

Every model call goes through `bench.claude_code.ClaudeCodeClient` (never an
API key, per Oleg's decision, D-013) — no real call is made in this
package's own tests; a fake `claude` executable on `PATH` proves the wiring
exactly as `tests/test_connector_model.py` does.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bench.build import EXCLUDED_DIRNAMES
from bench.claude_code import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    ClaudeCodeClient,
    structured_call,
)
from bench.llm import CountingClient
from bench.protocol import (
    Answer,
    Category,
    Citation,
    Claim,
    Contradiction,
    Fact,
    IngestReport,
    Sentence,
    Tier,
)

ARM_NAME = "baseline"
DEFAULT_VARIANT = "full"
DEFAULT_MAX_CORPUS_TOKENS = 150_000
DEFAULT_GREP_MAX_TURNS = 6

_CATEGORY_VALUES = [c.value for c in Category]
_TIER_VALUES = [t.value for t in Tier]

_CITATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document": {
            "type": "string",
            "description": (
                "a document id from the corpus, e.g. code/farebox/pricing.py, "
                "wiki/pricing-rules, doc/DOC-1, ticket/GW-1, pull/1, run/pytest-c6"
            ),
        },
        "location": {
            "type": ["string", "null"],
            "description": (
                "a symbol, test node id, vitest title, heading anchor or comment id "
                "within the document, if applicable"
            ),
        },
    },
    "required": ["document"],
}

_CLAIM_SCHEMA: dict[str, Any] = {
    "type": ["object", "null"],
    "properties": {
        "entity": {"type": "string"},
        "attribute": {"type": "string"},
        "value": {},
        "unit": {"type": ["string", "null"]},
    },
}

_FACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "statement": {"type": "string"},
        "category": {"type": "string", "enum": _CATEGORY_VALUES},
        "entities": {"type": "array", "items": {"type": "string"}},
        "tier": {"type": "string", "enum": _TIER_VALUES},
        "claim": _CLAIM_SCHEMA,
        "citations": {"type": "array", "items": _CITATION_SCHEMA, "minItems": 1},
    },
    "required": ["statement", "category", "entities", "tier", "citations"],
}

FACTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": _FACT_SCHEMA}},
    "required": ["facts"],
}

ASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": _CITATION_SCHEMA},
                },
                "required": ["text", "citations"],
            },
        }
    },
    "required": ["sentences"],
}

CONTRADICTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "a": _FACT_SCHEMA,
                    "b": _FACT_SCHEMA,
                    "label": {"type": "string", "enum": ["supports", "refutes"]},
                    "winner": {"type": ["string", "null"], "enum": ["a", "b", None]},
                },
                "required": ["a", "b"],
            },
        }
    },
    "required": ["contradictions"],
}

SYSTEM_PROMPT = (
    "You are a knowledge-extraction assistant answering queries against an "
    "ingested corpus of one software system's code, wiki pages, documents, "
    "tickets, pull-request threads and test-run reports, for a benchmark of "
    "a no-store baseline (the corpus is handed to you directly; there is no "
    "database behind you). Every fact or sentence you return must cite at "
    "least one document by its id (code/<path>, wiki/<slug>, doc/<id>, "
    "ticket/<KEY>, pull/<number>, run/<run-id>) drawn from the corpus you "
    "were given — never invent a document id, and never state a fact with "
    "no supporting document. Respond with only the JSON the schema requires."
)

_GREP_LAYOUT_NOTE = (
    "The corpus is not in this prompt: read it yourself from disk with Read, "
    "Grep and Glob, rooted at your current working directory. Code lives "
    "under repo/, so a file at repo/farebox/pricing.py is document id "
    "code/farebox/pricing.py; wiki pages at sources/wiki/<slug>.md are "
    "wiki/<slug>; sources/docs/<id>.md are doc/<id>; sources/tickets/<KEY>.json "
    "are ticket/<KEY>; sources/pulls/<n>.json are pull/<n>; runs/<id>.json are "
    "run/<id>."
)


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _iter_code_documents(repo_root: Path) -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    if not repo_root.is_dir():
        return documents
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if any(part in EXCLUDED_DIRNAMES for part in rel.parts):
            continue
        text = _read_text(path)
        if text is None:  # binary, or unreadable — never fabricate a document
            continue
        documents.append((f"code/{rel.as_posix()}", text))
    return documents


def _iter_source_documents(sources_root: Path, kind: str, id_prefix: str) -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    directory = sources_root / kind
    if not directory.is_dir():
        return documents
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        text = _read_text(path)
        if text is None:
            continue
        documents.append((f"{id_prefix}/{path.stem}", text))
    return documents


def _iter_run_documents(runs_root: Path) -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    if not runs_root.is_dir():
        return documents
    for path in sorted(runs_root.glob("*.json")):
        text = _read_text(path)
        if text is None:
            continue
        documents.append((f"run/{path.stem}", text))
    return documents


def _build_documents(root: Path) -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    documents.extend(_iter_code_documents(root / "repo"))
    sources_root = root / "sources"
    documents.extend(_iter_source_documents(sources_root, "wiki", "wiki"))
    documents.extend(_iter_source_documents(sources_root, "docs", "doc"))
    documents.extend(_iter_source_documents(sources_root, "tickets", "ticket"))
    documents.extend(_iter_source_documents(sources_root, "pulls", "pull"))
    documents.extend(_iter_run_documents(root / "runs"))
    return documents


def _find_commits(root: Path) -> dict[str, dict[str, str]] | None:
    """A `commits.json` found by walking upward from `root` (bounded, so
    this terminates on a filesystem root instead of looping) — sibling to
    the ingest root under the same `build/` directory `bench.build.build`
    writes into (`build/ingest` by default; `build/ingest/phase-1` and
    `phase-2` for an incremental run, two levels down)."""
    candidate = root.resolve()
    for _ in range(6):
        commits_path = candidate / "commits.json"
        if commits_path.is_file():
            try:
                return json.loads(commits_path.read_text())
            except json.JSONDecodeError:
                return None
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return None


def _find_commits_sha(root: Path) -> str | None:
    """The SHA for `root`'s own history step (D-013: "version = the SHA
    read from build/commits.json for the root's step") — the step comes
    from `step.json`, which `bench.run.assemble_ingest_root` writes into
    every root it builds. Falls back to the LAST entry in `commits.json`
    (chronological order, since `bench.build.build` inserts steps in that
    order) when there's no `step.json` — a root not produced by
    `assemble_ingest_root` at all (e.g. a hand-built one in a test) — which
    is only correct when that file's own last step matches this root's;
    stated here as the fallback's own known limit. No `commits.json` found
    at all (a scratch fixture never built) returns None, which `Citation`
    already allows."""
    commits = _find_commits(root)
    if not commits:
        return None
    step_path = root / "step.json"
    if step_path.is_file():
        try:
            step = json.loads(step_path.read_text()).get("step")
        except json.JSONDecodeError:
            step = None
        if step and step in commits:
            return commits[step].get("sha")
    last_step = next(reversed(commits))
    return commits[last_step].get("sha")


def _citation_from_payload(raw: dict[str, Any], commits_sha: str | None) -> Citation:
    document = raw.get("document", "")
    version = commits_sha if document.startswith("code/") else None
    return Citation(document=document, location=raw.get("location"), version=version)


def _claim_from_payload(raw: dict[str, Any] | None) -> Claim | None:
    if not raw:
        return None
    return Claim(
        entity=raw.get("entity", ""),
        attribute=raw.get("attribute", ""),
        value=raw.get("value"),
        unit=raw.get("unit"),
    )


def _fact_from_payload(raw: dict[str, Any], commits_sha: str | None) -> Fact | None:
    try:
        category = Category(raw["category"])
        tier = Tier(raw["tier"])
    except (KeyError, ValueError):
        return None
    citations = tuple(
        _citation_from_payload(c, commits_sha) for c in raw.get("citations", []) or []
    )
    return Fact(
        statement=raw.get("statement", ""),
        category=category,
        entities=tuple(raw.get("entities", []) or []),
        tier=tier,
        citations=citations,
        claim=_claim_from_payload(raw.get("claim")),
    )


def _facts_from_response(payload: dict[str, Any] | None, commits_sha: str | None) -> list[Fact]:
    if not payload:
        return []
    facts = []
    for raw in payload.get("facts", []) or []:
        fact = _fact_from_payload(raw, commits_sha)
        if fact is not None:
            facts.append(fact)
    return facts


class Prototype:
    """The no-store baseline (module docstring). `name` and the five
    protocol surfaces (`bench/protocol.py`) plus `ingest`."""

    name = ARM_NAME

    def __init__(self) -> None:
        self.variant = os.environ.get("ASBUILT_BASELINE_VARIANT", DEFAULT_VARIANT)
        if self.variant not in ("full", "grep"):
            raise ValueError(f"ASBUILT_BASELINE_VARIANT={self.variant!r}; want 'full' or 'grep'")
        self.model = os.environ.get("ASBUILT_BASELINE_MODEL", DEFAULT_MODEL)
        self._max_corpus_tokens = int(
            os.environ.get("ASBUILT_BASELINE_MAX_TOKENS", DEFAULT_MAX_CORPUS_TOKENS)
        )
        self._grep_max_turns = int(
            os.environ.get("ASBUILT_BASELINE_GREP_TURNS", DEFAULT_GREP_MAX_TURNS)
        )
        self._timeout = float(os.environ.get("ASBUILT_BASELINE_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
        self._documents: list[tuple[str, str]] = []
        self._entity_kinds: tuple[str, ...] = ()
        self._root: Path | None = None
        self._commits_sha: str | None = None
        self._full_client = ClaudeCodeClient(system_prompt=SYSTEM_PROMPT, timeout=self._timeout)
        self._grep_client: ClaudeCodeClient | None = None  # built once `ingest` knows the root
        # One CountingClient for the whole prototype lifetime, so the 80%
        # budget stop (D-013) applies across every query this instance ever
        # makes, not per call — `.client` is swapped between the full and
        # grep configurations right before each call (see `_call`) rather
        # than wrapping each in its own CountingClient, which would split
        # the budget in two.
        self._counting = CountingClient(
            client=self._full_client, arm=f"{ARM_NAME}-{self.variant}", model=self.model
        )

    def ingest(
        self,
        fixture_root: Path,
        entity_kinds: tuple[str, ...] = (),
        incremental: bool = False,
    ) -> IngestReport:
        """No-store: each call re-reads `fixture_root` (an assembled ingest
        root — never the raw fixture, see bench/run.py) into a fresh
        in-memory manifest, discarding whatever the previous call held —
        there is nothing to supersede or advance, so `incremental` changes
        nothing here beyond which root gets read. Makes no model call
        (zero tokens): the manifest is corpus text kept for the query
        surfaces, not an extraction."""
        started = time.perf_counter()
        self._root = Path(fixture_root)
        self._entity_kinds = tuple(entity_kinds)
        self._documents = _build_documents(self._root)
        self._commits_sha = _find_commits_sha(self._root)
        self._grep_client = ClaudeCodeClient(
            tools="Read,Grep,Glob",
            cwd=self._root,
            max_turns=self._grep_max_turns,
            timeout=self._timeout,
            system_prompt=SYSTEM_PROMPT,
        )
        elapsed = time.perf_counter() - started
        return IngestReport(
            seconds=elapsed,
            input_tokens=0,
            output_tokens=0,
            dollars=0.0,
            services=(),
            documents=len(self._documents),
            model=self.model,
            embedder=None,
            calls=0,
            embedding_tokens=0,
            cache_tokens=0,
        )

    def stats(self) -> dict[str, int]:
        """Cumulative counts from the one CountingClient every query call
        goes through (D-013) — not part of the Prototype protocol; a
        transcript writer or a script may read it for cost reporting after a
        run (bench/run.py's --transcript)."""
        return {
            "calls": self._counting.calls,
            "input_tokens": self._counting.input_tokens,
            "output_tokens": self._counting.output_tokens,
            "cache_tokens": self._counting.cache_tokens,
            # process-level retries over both providers' lives (asbuilt#21)
            "retries": int(getattr(self._full_client, "retries", 0) or 0)
            + int(getattr(self._grep_client, "retries", 0) or 0),
        }

    def _entity_kinds_note(self) -> str:
        if not self._entity_kinds:
            return ""
        return f"Allowed entity kinds: {', '.join(self._entity_kinds)}."

    def _corpus_text(self) -> str:
        return "\n\n".join(f"=== {doc_id} ===\n{text}" for doc_id, text in self._documents)

    def _call(self, task: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        """Issues exactly one structured call for this query: `full` puts
        the whole corpus in the prompt unless it's estimated over
        `ASBUILT_BASELINE_MAX_TOKENS`, in which case (or always, under the
        `grep` variant) the model is handed tools and the ingest root as its
        working directory instead — see the module docstring."""
        note = self._entity_kinds_note()
        if self.variant == "full":
            corpus_text = self._corpus_text()
            if _estimate_tokens(corpus_text) <= self._max_corpus_tokens:
                prompt = f"{task}\n{note}\n\nCorpus:\n{corpus_text}"
                self._counting.client = self._full_client
                return structured_call(
                    self._counting, SYSTEM_PROMPT, prompt, schema, model=self.model
                )
        if self._grep_client is None:
            raise RuntimeError("baseline prototype: ingest() must run before any query")
        prompt = f"{task}\n{note}\n\n{_GREP_LAYOUT_NOTE}"
        self._counting.client = self._grep_client
        return structured_call(self._counting, SYSTEM_PROMPT, prompt, schema, model=self.model)

    def explain(self, entity: str) -> list[Fact]:
        task = f"List every fact in the corpus that concerns the entity named {entity!r}."
        payload = self._call(task, FACTS_SCHEMA)
        return _facts_from_response(payload, self._commits_sha)

    def search(
        self,
        query: str,
        category: Category | None = None,
        since: datetime | None = None,
    ) -> list[Fact]:
        constraints = []
        if category is not None:
            constraints.append(f"only facts in category {category.value!r}")
        if since is not None:
            constraints.append(f"only facts that changed at or after {since.isoformat()}")
        constraint_text = f" ({'; '.join(constraints)})" if constraints else ""
        task = (
            f"Find facts in the corpus relevant to the free-text query {query!r}{constraint_text}."
        )
        payload = self._call(task, FACTS_SCHEMA)
        return _facts_from_response(payload, self._commits_sha)

    def ask(self, question: str) -> Answer:
        task = f"Answer this question in one to three cited sentences: {question!r}"
        payload = self._call(task, ASK_SCHEMA)
        if not payload:
            return Answer(sentences=[])
        sentences = []
        for raw in payload.get("sentences", []) or []:
            citations = tuple(
                _citation_from_payload(c, self._commits_sha) for c in raw.get("citations", []) or []
            )
            sentences.append(Sentence(text=raw.get("text", ""), citations=citations))
        return Answer(sentences=sentences)

    def contradictions(self, entity: str | None = None) -> list[Contradiction]:
        scope = f" concerning the entity named {entity!r}" if entity else ""
        task = f"Find pairs of facts in the corpus that contradict each other{scope}."
        payload = self._call(task, CONTRADICTIONS_SCHEMA)
        if not payload:
            return []
        results = []
        for raw in payload.get("contradictions", []) or []:
            fact_a = _fact_from_payload(raw.get("a") or {}, self._commits_sha)
            fact_b = _fact_from_payload(raw.get("b") or {}, self._commits_sha)
            if fact_a is None or fact_b is None:
                continue
            winner = {"a": fact_a, "b": fact_b}.get(raw.get("winner"))
            results.append(
                Contradiction(a=fact_a, b=fact_b, label=raw.get("label", "refutes"), winner=winner)
            )
        return results

    def stale(self, since: datetime) -> list[Fact]:
        task = (
            "List facts whose supporting document looks stale (superseded or "
            f"out of date) as of {since.isoformat()}."
        )
        payload = self._call(task, FACTS_SCHEMA)
        return _facts_from_response(payload, self._commits_sha)
