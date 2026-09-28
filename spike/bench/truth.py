"""Ground-truth loaders for entities, facts, contradictions and stale pages.

See ``spike/truth/SCHEMA.md`` for the yaml shapes. This module loads them into
plain dataclasses, resolves a history step id to its built commit, and checks
that every carrier document and every cross-referenced id actually resolves
(``check_consistency``) — the sources/code/runs side of validation;
``truth/validate.py`` (owned separately) checks the truth/PLAN side (tier
composition, fact counts, and so on) and is not touched here.

Document-id-to-path convention (not in SCHEMA.md; fixed here because both
this loader and every fixture author need the same mapping), and how a
carrier's ``location`` is checked against it:

    wiki/<slug>      sources/wiki/<slug>.md; location `#anchor` must match a
                     `## Heading` whose GitHub-style slug equals the anchor.
    doc/<id>         sources/docs/<id>.md; anchors checked the same way.
    ticket/<KEY>     sources/tickets/<KEY>.json; location `description` needs
                     a `description` field, `comment-<k>` needs a `comments[]`
                     entry with that `id`.
    pull/<number>    sources/pulls/<number>.json; location `body` needs a
                     `body` field, `comment-<k>` as for tickets.
    code/<path>      materialised at the carrier's `version` (a history step
                     id) via bench.build.Timeline — not via git. Then, by
                     `location` shape: a test node id containing "::" checks
                     the part after it as a whole word; a vitest test title
                     containing " > " (describe(s) > it) checks each name as
                     a literal quoted `describe(...)`/`it(...)` call argument
                     (any of ' " `, not a word boundary — a bare mention
                     isn't a call); a dotted symbol (e.g.
                     `FareboxClient.close_ride`) checks the class name and
                     the last segment each as a whole word; anything else
                     checks the whole `location` as a whole word.
    run/<run-id>     runs/<run-id>.json; for a pytest report (has a `tests`
                     key), `location` must equal some test's `nodeid` with
                     `outcome == "passed"`; for a vitest/jest report (has a
                     `testResults` key), `location` must equal some
                     assertionResult's `ancestorTitles + [title]` joined with
                     " > ", with `status == "passed"` (the join is
                     reconstructed rather than trusting a raw `fullName`
                     field, whose own separator isn't guaranteed).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ENTITIES_FILE = "entities.yaml"
FACTS_FILE = "facts.yaml"
CONTRADICTIONS_FILE = "contradictions.yaml"
STALE_FILE = "stale.yaml"

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Entity:
    id: str
    kind: str
    name: str
    owner: str | None = None
    summary: str | None = None


@dataclass(frozen=True)
class Carrier:
    document: str
    location: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class TruthFact:
    id: str
    statement: str
    category: str
    entities: tuple[str, ...]
    tier: str
    carriers: tuple[Carrier, ...]
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass(frozen=True)
class TruthContradiction:
    id: str
    facts: tuple[str, str]
    kind: str
    winner: str | None = None
    label: str = "refutes"


@dataclass(frozen=True)
class StaleEntry:
    id: str
    document: str
    states: str
    changed_by: str
    superseded_by: str | None = None


@dataclass
class Truth:
    entities: dict[str, Entity] = field(default_factory=dict)
    facts: dict[str, TruthFact] = field(default_factory=dict)
    contradictions: dict[str, TruthContradiction] = field(default_factory=dict)
    stale: dict[str, StaleEntry] = field(default_factory=dict)


def _load_raw(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return yaml.safe_load(path.read_text()) or []


def load_entities(path: Path) -> dict[str, Entity]:
    return {
        raw["id"]: Entity(
            id=raw["id"],
            kind=raw["kind"],
            name=raw["name"],
            owner=raw.get("owner"),
            summary=raw.get("summary"),
        )
        for raw in _load_raw(path)
    }


def load_facts(path: Path) -> dict[str, TruthFact]:
    facts: dict[str, TruthFact] = {}
    for raw in _load_raw(path):
        carriers = tuple(
            Carrier(
                document=c["document"],
                location=c.get("location"),
                version=c.get("version"),
            )
            for c in raw.get("carriers", [])
        )
        facts[raw["id"]] = TruthFact(
            id=raw["id"],
            statement=raw["statement"],
            category=raw["category"],
            entities=tuple(raw.get("entities", [])),
            tier=raw["tier"],
            carriers=carriers,
            valid_from=raw.get("valid_from"),
            valid_to=raw.get("valid_to"),
        )
    return facts


def load_contradictions(path: Path) -> dict[str, TruthContradiction]:
    contradictions: dict[str, TruthContradiction] = {}
    for raw in _load_raw(path):
        facts = tuple(raw["facts"])
        if len(facts) != 2:
            raise ValueError(f"contradiction {raw.get('id')!r} must name exactly two facts")
        contradictions[raw["id"]] = TruthContradiction(
            id=raw["id"],
            facts=facts,
            kind=raw["kind"],
            winner=raw.get("winner"),
            label=raw.get("label", "refutes"),
        )
    return contradictions


def load_stale(path: Path) -> dict[str, StaleEntry]:
    return {
        raw["id"]: StaleEntry(
            id=raw["id"],
            document=raw["document"],
            states=raw["states"],
            changed_by=raw["changed_by"],
            superseded_by=raw.get("superseded_by"),
        )
        for raw in _load_raw(path)
    }


def load_truth(truth_root: Path) -> Truth:
    return Truth(
        entities=load_entities(truth_root / ENTITIES_FILE),
        facts=load_facts(truth_root / FACTS_FILE),
        contradictions=load_contradictions(truth_root / CONTRADICTIONS_FILE),
        stale=load_stale(truth_root / STALE_FILE),
    )


def load_commits(out_root: Path) -> dict[str, dict[str, str]]:
    commits_path = out_root / "commits.json"
    return json.loads(commits_path.read_text())


def resolve_step(step_id: str, commits: dict[str, dict[str, str]]) -> dict[str, str]:
    """Resolve a history step id to its {sha, date, message}, from commits.json."""
    try:
        return commits[step_id]
    except KeyError as exc:
        raise KeyError(f"unknown history step {step_id!r}; not in commits.json") from exc


def github_slugify(text: str) -> str:
    """Approximates GitHub's heading-anchor algorithm: lowercase, drop
    anything that isn't a word character, space or hyphen, turn spaces into
    hyphens. Does not handle duplicate-heading disambiguation (-1, -2, ...);
    none of the fixture's pages repeat a heading."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text)


def _heading_slugs(markdown_text: str) -> set[str]:
    return {github_slugify(m.group(1)) for m in _HEADING_RE.finditer(markdown_text)}


def _word_in(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _document_exists(document: str, fixture_root: Path) -> bool:
    """Existence only (no location check) — used for stale.yaml's `document`,
    which names a page but not an anchor within it."""
    kind, _, rest = document.partition("/")
    if kind == "wiki":
        return (fixture_root / "sources" / "wiki" / f"{rest}.md").is_file()
    if kind == "doc":
        return (fixture_root / "sources" / "docs" / f"{rest}.md").is_file()
    if kind == "ticket":
        return (fixture_root / "sources" / "tickets" / f"{rest}.json").is_file()
    if kind == "pull":
        return (fixture_root / "sources" / "pulls" / f"{rest}.json").is_file()
    if kind == "code":
        system_root = fixture_root / "system"
        if (system_root / rest).is_file():
            return True
        history_root = system_root / "history"
        if history_root.is_dir():
            for step_dir in history_root.iterdir():
                if (step_dir / rest).is_file():
                    return True
        return False
    if kind == "run":
        return (fixture_root / "runs" / f"{rest}.json").is_file()
    return False


def _check_wiki_or_doc_carrier(carrier: Carrier, fixture_root: Path, kind: str) -> str | None:
    dirname = "wiki" if kind == "wiki" else "docs"
    rest = carrier.document.split("/", 1)[1]
    doc_path = fixture_root / "sources" / dirname / f"{rest}.md"
    if not doc_path.is_file():
        return f"{kind}:{carrier.document}:{carrier.location}:document not found"
    location = carrier.location or ""
    anchor = location.lstrip("#")
    if anchor not in _heading_slugs(doc_path.read_text()):
        return f"{kind}:{carrier.document}:{location}:no heading slug matches"
    return None


def _check_ticket_or_pull_carrier(carrier: Carrier, fixture_root: Path, kind: str) -> str | None:
    dirname = "tickets" if kind == "ticket" else "pulls"
    default_location = "description" if kind == "ticket" else "body"
    rest = carrier.document.split("/", 1)[1]
    doc_path = fixture_root / "sources" / dirname / f"{rest}.json"
    if not doc_path.is_file():
        return f"{kind}:{carrier.document}:{carrier.location}:document not found"
    try:
        data = json.loads(doc_path.read_text())
    except json.JSONDecodeError as exc:
        return f"{kind}:{carrier.document}:{carrier.location}:invalid json ({exc})"
    location = carrier.location or ""
    if location == default_location:
        if default_location not in data:
            return f"{kind}:{carrier.document}:{location}:no {default_location!r} field"
        return None
    if location.startswith("comment-"):
        comment_ids = {c.get("id") for c in data.get("comments", [])}
        if location not in comment_ids:
            return f"{kind}:{carrier.document}:{location}:no comment with that id"
        return None
    return f"{kind}:{carrier.document}:{location}:unrecognised location"


_QUOTE_CHARS = ("'", '"', "`")


def _has_quoted_call(text: str, fn_name: str, literal: str) -> bool:
    """True if `text` contains `fn_name(<quote>literal<quote>` for any of
    ' " ` as the quote — a vitest `describe(...)`/`it(...)` call naming
    `literal` as a literal string argument, not just a coincidental mention."""
    return any(f"{fn_name}({q}{literal}{q}" in text for q in _QUOTE_CHARS)


def _check_code_carrier(carrier: Carrier, fixture_root: Path, timeline) -> str | None:
    path = carrier.document.split("/", 1)[1]
    if timeline is None:
        return f"code:{carrier.document}:{carrier.location}:no history/steps.yaml to build against"
    if carrier.version is None:
        return f"code:{carrier.document}:{carrier.location}:no version given"
    try:
        content = timeline.content_at(path, carrier.version)
    except Exception as exc:  # noqa: BLE001 - surfaced as a problem, not raised
        return f"code:{carrier.document}:{carrier.location}:{exc}"
    if content is None:
        return (
            f"code:{carrier.document}:{carrier.location}:path does not exist at {carrier.version}"
        )
    text = content.decode("utf-8", errors="replace")
    location = carrier.location or ""

    if " > " in location:
        # A vitest test title: describe(s) > it. Each name must appear as a
        # literal quoted call argument (describe(...)/it(...)), not just a
        # bare word — matching literal text, not a word boundary (a symbol
        # like "maintenanceSweep" could otherwise appear anywhere).
        *describes, it_title = location.split(" > ")
        for name in describes:
            if not _has_quoted_call(text, "describe", name):
                return (
                    f"code:{carrier.document}:{location}:"
                    f"describe({name!r}) not found at {carrier.version}"
                )
        if not _has_quoted_call(text, "it", it_title):
            return (
                f"code:{carrier.document}:{location}:"
                f"it({it_title!r}) not found at {carrier.version}"
            )
        return None

    if "::" in location:
        symbol = location.rsplit("::", 1)[-1]
    elif "." in location:
        # A dotted symbol (e.g. FareboxClient.close_ride): resolves when the
        # class name and the last segment both appear as whole words.
        class_name, _, member = location.rpartition(".")
        if _word_in(text, class_name) and _word_in(text, member):
            return None
        return (
            f"code:{carrier.document}:{location}:"
            f"dotted symbol {location!r} not found at {carrier.version}"
        )
    else:
        symbol = location

    if not _word_in(text, symbol):
        return (
            f"code:{carrier.document}:{location}:symbol {symbol!r} not found at {carrier.version}"
        )
    return None


def _run_fullname(assertion: dict) -> str:
    return " > ".join([*assertion.get("ancestorTitles", []), assertion.get("title", "")])


def _check_run_carrier(carrier: Carrier, fixture_root: Path) -> str | None:
    rest = carrier.document.split("/", 1)[1]
    report_path = fixture_root / "runs" / f"{rest}.json"
    if not report_path.is_file():
        return f"run:{carrier.document}:{carrier.location}:document not found"
    try:
        data = json.loads(report_path.read_text())
    except json.JSONDecodeError as exc:
        return f"run:{carrier.document}:{carrier.location}:invalid json ({exc})"
    location = carrier.location
    if "tests" in data:
        for t in data["tests"]:
            if t.get("nodeid") == location and t.get("outcome") == "passed":
                return None
        return f"run:{carrier.document}:{location}:no passed pytest nodeid match"
    if "testResults" in data:
        for suite in data["testResults"]:
            for assertion in suite.get("assertionResults", []):
                if _run_fullname(assertion) == location and assertion.get("status") == "passed":
                    return None
        return f"run:{carrier.document}:{location}:no passed vitest fullName match"
    return f"run:{carrier.document}:{location}:unrecognised run json shape"


def _check_carrier(carrier: Carrier, fixture_root: Path, timeline) -> str | None:
    kind = carrier.document.split("/", 1)[0]
    if kind in ("wiki", "doc"):
        return _check_wiki_or_doc_carrier(carrier, fixture_root, kind)
    if kind in ("ticket", "pull"):
        return _check_ticket_or_pull_carrier(carrier, fixture_root, kind)
    if kind == "code":
        return _check_code_carrier(carrier, fixture_root, timeline)
    if kind == "run":
        return _check_run_carrier(carrier, fixture_root)
    return f"{kind}:{carrier.document}:{carrier.location}:unrecognised document kind"


def check_consistency(fixture_root: Path) -> list[str]:
    """Check every carrier document/location and cross-referenced id in
    truth/. Returns a list of problems, one per issue, each formatted
    ``kind:document:location:reason`` for a carrier or ``kind: message`` for
    a cross-reference; empty means consistent. Does not require the
    repository to be built — code/ and run/ documents are checked against
    the fixture's own files (code/ via bench.build.Timeline), not a build.
    """
    truth = load_truth(fixture_root / "truth")
    problems: list[str] = []

    step_ids: set[str] = set()
    steps_path = fixture_root / "system" / "history" / "steps.yaml"
    if steps_path.is_file():
        step_ids = {raw["id"] for raw in (yaml.safe_load(steps_path.read_text()) or [])}

    timeline = None
    if steps_path.is_file():
        from bench.build import BuildError, Timeline

        try:
            timeline = Timeline(fixture_root)
        except BuildError:
            timeline = None

    for entity in truth.entities.values():
        if entity.owner is not None and entity.owner not in truth.entities:
            problems.append(f"entity: {entity.id} owner {entity.owner!r} is not a known entity")

    for fact in truth.facts.values():
        for entity_id in fact.entities:
            if entity_id not in truth.entities:
                problems.append(f"fact: {fact.id} entity {entity_id!r} is not a known entity")
        if not fact.carriers:
            problems.append(f"fact: {fact.id} has no carriers")
        for carrier in fact.carriers:
            problem = _check_carrier(carrier, fixture_root, timeline)
            if problem:
                problems.append(problem)
        if fact.valid_from is not None and step_ids and fact.valid_from not in step_ids:
            problems.append(f"fact: {fact.id} valid_from {fact.valid_from!r} is not a known step")
        if fact.valid_to is not None and step_ids and fact.valid_to not in step_ids:
            problems.append(f"fact: {fact.id} valid_to {fact.valid_to!r} is not a known step")

    for contradiction in truth.contradictions.values():
        for fact_id in contradiction.facts:
            if fact_id not in truth.facts:
                problems.append(
                    f"contradiction: {contradiction.id} fact {fact_id!r} is not a known fact"
                )
        if contradiction.winner is not None:
            if contradiction.winner not in truth.facts:
                problems.append(
                    f"contradiction: {contradiction.id} winner {contradiction.winner!r} "
                    "is not a known fact"
                )
            elif contradiction.winner not in contradiction.facts:
                problems.append(
                    f"contradiction: {contradiction.id} winner {contradiction.winner!r} "
                    "is not one of its own facts"
                )

    for stale in truth.stale.values():
        if not _document_exists(stale.document, fixture_root):
            problems.append(f"stale: {stale.id} document {stale.document!r} not found")
        if stale.states not in truth.facts:
            problems.append(f"stale: {stale.id} states {stale.states!r} is not a known fact")
        if step_ids and stale.changed_by not in step_ids:
            problems.append(
                f"stale: {stale.id} changed_by {stale.changed_by!r} is not a known step"
            )
        if stale.superseded_by is not None and stale.superseded_by not in truth.facts:
            problems.append(
                f"stale: {stale.id} superseded_by {stale.superseded_by!r} is not a known fact"
            )

    return problems


def summarize(problems: list[str]) -> str:
    """A readable report grouped by kind, counts first — for check_consistency
    run against the real fixture, where most carriers may still be missing
    while other agents are mid-authoring."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for p in problems:
        grouped[p.split(":", 1)[0]].append(p)

    lines = [f"{len(problems)} problem(s)"]
    for kind in sorted(grouped):
        lines.append(f"  {kind}: {len(grouped[kind])}")
    for kind in sorted(grouped):
        lines.append(f"\n-- {kind} ({len(grouped[kind])}) --")
        lines.extend(f"  {p}" for p in grouped[kind])
    return "\n".join(lines)
