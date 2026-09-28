"""Scores a prototype's raw results (from bench/run.py) against ground truth.

CLI: ``uv run python bench/score.py build/results-null.json [--truth truth]
[--json build/score-null.json]``. Several results files for the *same* arm
may be given (``bench/score.py a1.json a2.json a3.json``): each is scored
independently and each measure's median/min/max across the runs is printed
after the first run's own full report. ``--compare-with b1.json b2.json``
scores a second arm's file(s) the same way, then prints a paired bootstrap
(resampling queries, seed fixed) 95% interval for the difference in F1 per
surface and in executed-tier precision, using the *first* file of each arm's
set for the per-query pairing (see "Interpretation calls"). ``--calibrate
[FILE]`` (default ``tests/fixtures/calibration.yaml``) runs the matcher
calibration set instead of scoring a results file. ``--truth`` defaults to
``truth`` (relative to the current directory, matching a run from
``spike/``); the fixture root used to resolve history-step dates for
staleness is read from the results file itself (``results["fixture"]``,
written by ``bench/run.py``), not re-specified here.

Interpretation calls made where the spec leaves a choice (stated, not just
assumed, per the task's ambiguity rule):

* Per-category breakdowns bucket strictly by the *truth* fact's category
  (never the returned fact's), for both explain/search/ask and for
  contradictions where relevant. For explain/search/ask, the per-category
  ``tp`` is a partition of the overall ``tp`` — categories' true-positive
  counts sum to the surface's overall true-positive count — while the
  precision denominator (total returned) is shared across categories, so a
  category's precision is its *contribution* to the surface's precision, not
  an independent ratio. This was chosen because the spec ties categorisation
  to "category of the truth fact" as a single scheme, not two different
  denominators for precision and recall.
* Aggregation across multiple queries on the same surface is by summing raw
  counts (tp, returned, expected, ...) before computing ratios — i.e.
  micro-averaged, not a mean of per-query ratios — so the printed
  denominators are the true totals. This also governs tier, category,
  validity and entity-resolution aggregation (new in this revision): all are
  summed across a surface's queries before a ratio is taken.
* For ``ask``, "recall = expected facts covered" is evaluated per query by
  summing distinct covered-fact counts; aggregating across queries sums
  those per-query counts rather than re-deduplicating globally (a fact
  "covered" by two different ask queries counts twice), consistent with
  summing raw counts everywhere else.
* Version disambiguation (when a returned fact could match more than one
  expected truth fact — e.g. two facts share a statement and a code document
  at different versions) is applied in ``match_facts``, used by explain and
  search. It is not applied inside ``score_contradictions`` (a different,
  pairwise matching loop) or ``score_ask_query`` (which matches by cited
  document, not by ``facts_match``, so the ambiguity doesn't arise there).
* ``facts_match`` requires the two statements' numbers (money, percentages,
  times, decimals, integers — see ``_number_tokens``) to be equal, as sets,
  whenever either statement names one; text similarity alone is not enough.
  Without this, a superseded value ("45 minutes") matches its replacement
  ("30 minutes") on wording despite naming a different fact (measured: 0.959
  similarity for that pair, 0.648 for "$25.00" vs "$30.00" — both above the
  0.6 threshold). This also governs the winner check inside
  ``score_contradictions``, which reuses ``facts_match``. The number/negation
  logic itself lives in ``_statement_matches``, shared with ``ask`` scoring.
* ``score_stale`` credits every still-unmatched expected entry a returned
  fact's citations *and* statement (via ``facts_match``) both support, not
  just the first one its documents happen to touch — a single returned fact
  citing two stale pages should credit both, and two stale entries sharing
  one document (different pages can restate the same superseded claim, or
  restate different claims on the same page) are told apart by which one the
  statement actually agrees with, not by the shared document alone.

New in this revision (D-013 hardening, konyklabs/asbuilt#7):

* Entity alignment (arms return names, never ids — bench/protocol.py). The
  alias index registers each entity's own id *and* name (normalised the same
  way), plus every ``truth/aliases.yaml`` alias; an id is registered so a
  ``queries/mix.yaml`` (or hand-built test) that still names entities by id
  keeps working unmodified while the harness's own fixtures transition to
  names — this is a deliberate back-compat fallback, not a claim that ids
  are a supported arm output. Entity-name normalisation (``norm_entity``)
  treats ``-``/``_`` as word separators (so "member-free-minutes" ==
  "member free minutes"), unlike statement ``norm()``, which strips them —
  entity names are identifiers with conventional separators; statements are
  prose. The fuzzy fallback (``difflib.get_close_matches``, cutoff 0.88) is
  used only when no exact normalised match exists, and only when it is
  unambiguous — a second candidate at the same cutoff resolving to a
  *different* entity aborts the guess rather than picking one, per "a
  conservative fuzzy fallback with a high threshold" in the task.
* The entity-resolution measure (precision/recall of a matched fact's
  resolved entities against the truth fact's) is computed over the matches
  ``match_facts`` produces for ``explain`` and ``search`` specifically —
  those are the two surfaces that hand the scorer raw, individually-matched
  facts; ``contradictions`` and ``stale`` returned facts are still resolved
  (so their own matching works correctly) but don't feed this aggregate
  measure, to keep its denominator meaning single and clear. The unresolved-
  names audit list, by contrast, is collected from every surface's
  resolution pass (matched or not), since an unresolved name that never even
  produced a match is exactly the failure worth surfacing.
* Hard false positives vs. unplanted (an unmatched returned fact's split) is
  judged against the *entire* truth fact set (``truth.facts``), not just the
  query's own ``expected`` subset — "same entity and same cited document as
  some truth fact" reads as "anywhere in the ground truth", not "anywhere in
  what this particular query expected"; a returned fact about the right
  entity/document pair but wrong query is still evidence of a real
  (mis-cited) hard error, not noise.
* ``precision@5``/``recall@10`` (search only) use the returned list's own
  order as rank; the precision denominator is ``min(5, len(returned))`` —
  the common small-result-set convention — rather than a fixed 5, so a
  three-result answer isn't penalised for results it was never asked to
  produce; aggregation across queries sums hits and denominators (same
  micro-averaging policy as everywhere else), not a mean of per-query
  ratios.
* ``ask`` sentence correctness is text-match, not citation-only: a
  sentence's (capped) citations identify *candidate* expected facts via the
  document they carry, and the sentence's own text must then satisfy
  ``_statement_matches`` against at least one candidate's statement.
* ``contradictions`` now reports precision (``matched / returned``) in
  addition to recall, since a returned contradiction list has a real
  false-positive question (a returned pair that doesn't correspond to any
  planted contradiction) that recall alone never penalises.
* The matcher's number-word/date/clock-time normalisation
  (``_prenormalize_numeric_prose``) runs only ahead of number-*token*
  extraction, never on the text fed to the difflib similarity ratio — it
  would otherwise let two statements that use *different* number-word
  spellings for otherwise-unrelated numbers look more alike than they are.
  Prose dates are matched only in the exact "Month D, YYYY" shape the task's
  example uses (no ordinal suffixes, no abbreviated months) — a deliberate
  scope limit given the calibration set's own needs, not a general date
  parser.
* The negation guard (``not``/``never``/``no``/``off``, word-boundary,
  case-insensitive) is a hard veto in ``_statement_matches``: a mismatch on
  either side's negation blocks the match outright, before the number or
  similarity checks even run, since "free" and "not free" can otherwise
  still score above the similarity threshold.
* Multi-run aggregation reports median/min/max for each surface's
  precision/recall/f1 and, for explain/search, the executed-tier precision;
  it does not attempt to re-run entity resolution or re-derive by-category
  detail across runs, since those are per-run diagnostics rather than
  headline noise measures.
* ``--compare-with``'s exact flag shape isn't fixed by the task (which only
  says "between two arms' file sets"); paired with the existing positional
  ``results`` this reads as "compare *this* arm's runs against that one's",
  and is the simplest shape that doesn't require inventing arm-labelling
  syntax. The paired bootstrap pairs queries by *position* in each arm's
  ``queries`` list (both score the same fixed ``queries/mix.yaml``, in the
  same order, so position is a valid pairing key without matching by id).
* The single weighted headline is no longer printed by default (the task
  says to drop it); ``score()`` still computes it (and an unweighted
  equal-weights variant) into the report dict unconditionally, since it
  costs nothing and ``--json``/``--compare`` consumers may still want it —
  only ``print_report``'s default terminal output omits it, behind
  ``--headline``.
"""

from __future__ import annotations

import argparse
import difflib
import json
import random
import re
import statistics
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))

import yaml  # noqa: E402

from bench.truth import StaleEntry, Truth, TruthFact, load_truth  # noqa: E402

_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")

# Order matters: Python's re alternation takes the first branch that matches
# at a position, not the longest, so money/percent/time must be tried before
# the bare decimal/integer branches would otherwise split them apart.
_MONEY_RE = r"\$\d+(?:\.\d+)?"
_PERCENT_RE = r"\d+(?:\.\d+)?%"
_TIME_RE = r"\d{1,2}:\d{2}"
_DECIMAL_RE = r"\d+\.\d+"
_INTEGER_RE = r"\d+"
_NUMBER_RE = re.compile(f"{_MONEY_RE}|{_PERCENT_RE}|{_TIME_RE}|{_DECIMAL_RE}|{_INTEGER_RE}")

SURFACES = ("explain", "search", "ask", "contradictions", "stale")

DEFAULT_CALIBRATION = "tests/fixtures/calibration.yaml"


def norm(text: str) -> str:
    text = text.lower()
    text = _PUNCTUATION.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


# --------------------------------------------------------------------------
# Number/date/time normalisation and statement matching
# --------------------------------------------------------------------------


def _normalize_number(token: str) -> str:
    """Strip $/% decoration and trailing zeros, so "$25.00" == "$25" and
    "20.0%" == "20%"; a bare integer/decimal or a time (kept as-is, trailing
    zeros in HH:MM aren't decoration) is returned unchanged apart from that."""
    if token.startswith("$"):
        value = token[1:]
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        return f"${value or '0'}"
    if token.endswith("%"):
        value = token[:-1]
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        return f"{value or '0'}%"
    if ":" in token:
        return token
    if "." in token:
        value = token.rstrip("0").rstrip(".")
        return value or "0"
    return token


_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_PROSE_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),\s*(\d{4})\b", re.IGNORECASE
)


def _replace_prose_dates(text: str) -> str:
    """ "January 12, 2026" -> "2026-01-12" (see module docstring: exact
    "Month D, YYYY" shape only, no ordinals, no abbreviations)."""

    def repl(m: re.Match[str]) -> str:
        month = _MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        year = m.group(3)
        return f"{year}-{month:02d}-{day:02d}"

    return _PROSE_DATE_RE.sub(repl, text)


_CLOCK_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([AaPp][Mm])\b")


def _replace_clock_times(text: str) -> str:
    """ "3am" -> "03:00", "3:30pm" -> "15:30", "12am" -> "00:00"."""

    def repl(m: re.Match[str]) -> str:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        meridiem = m.group(3).lower()
        if meridiem == "am":
            hour24 = 0 if hour == 12 else hour
        else:
            hour24 = 12 if hour == 12 else hour + 12
        return f"{hour24:02d}:{minute:02d}"

    return _CLOCK_TIME_RE.sub(repl, text)


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twice": 2,
    "thrice": 3,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)


def _replace_number_words(text: str) -> str:
    return _NUMBER_WORD_RE.sub(lambda m: str(_NUMBER_WORDS[m.group(1).lower()]), text)


def _prenormalize_numeric_prose(text: str) -> str:
    """Applied only ahead of number-TOKEN extraction (never to the statement
    text used for the word-overlap similarity — see module docstring):
    spelled-out numbers up to twenty and the tens, prose dates and 12-hour
    clock times are rewritten to the digit forms `_NUMBER_RE` recognises.
    "twice"/"thrice" are included too (calibration found "fails twice" vs
    "fails two times" a real paraphrase pair the task's literal word list
    would otherwise fail on); "once" is deliberately excluded — it is at
    least as often a conjunction ("once the flag is on") as a numeral, and
    misreading the conjunction sense as `1` would create number mismatches
    on unrelated statements far more often than it would fix real ones."""
    text = _replace_prose_dates(text)
    text = _replace_clock_times(text)
    text = _replace_number_words(text)
    return text


def _number_tokens(text: str) -> set[str]:
    """Every money/percentage/time/decimal/integer token in `text` (the raw,
    un-normed statement, after word/date/time prose normalisation),
    normalised so equivalent forms compare equal."""
    text = _prenormalize_numeric_prose(text)
    return {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(text)}


_NEGATION_RE = re.compile(r"\b(not|never|no|off|cannot)\b|\w+n't\b", re.IGNORECASE)


def _has_negation(text: str) -> bool:
    """ "not"/"never"/"no"/"off"/"cannot", plus any "...n't" contraction
    (isn't, doesn't, won't, don't, ...) — "cannot" and the contractions are
    additions beyond the task's literal word list: `\\bnot\\b` never matches
    inside "cannot" (no word boundary before "not" there) or inside a
    contraction (the apostrophe isn't a word-breaking character to `\\b`
    either), so a paraphrase that contracts "does not" to "doesn't" would
    otherwise silently look like agreement instead of the negation match it
    needs to be (calibration measured this directly: "can unlock" vs
    "cannot unlock" scored 0.889 similarity with no numbers to catch it)."""
    return bool(_NEGATION_RE.search(text))


def _statement_matches(returned_statement: str, truth_statement: str) -> bool:
    """Number-aware, negation-guarded text match: shared by `facts_match`
    (which additionally requires a shared entity and cited document) and
    `ask` sentence scoring (which matches by citation, not entity, so it
    calls this directly). A negation mismatch (one side says "not"/"never"/
    "no"/"off" and the other doesn't) vetoes the match outright; otherwise
    numbers named by either side must agree as sets, then text similarity
    (on the un-prenormalised, punctuation-stripped statements) must be
    >= 0.6."""
    if _has_negation(returned_statement) != _has_negation(truth_statement):
        return False
    returned_numbers = _number_tokens(returned_statement)
    truth_numbers = _number_tokens(truth_statement)
    if (returned_numbers or truth_numbers) and returned_numbers != truth_numbers:
        return False
    return _text_similarity(returned_statement, truth_statement) >= _SIMILARITY_THRESHOLD


_SIMILARITY_THRESHOLD = 0.6


def _text_similarity(a: str, b: str) -> float:
    """The overlap coefficient (|A n B| / min(|A|, |B|), multiset
    intersection via Counter), not a sequence-alignment ratio and not the
    Dice coefficient. `difflib.SequenceMatcher`, char- or word-level, scores
    *ordered* common subsequences: a clause-reordering paraphrase ("A
    member's first 30 minutes... are free" vs "Members get their first 30
    minutes free on...") shares most of its content words with the truth
    statement but not in the same relative order, and SequenceMatcher
    undercounts exactly that — the audit's "7 of 20" short-paraphrase
    finding was the same failure mode. Dice (2*overlap/(|A|+|B|)) fixes the
    ordering problem but still penalises a short graph-edge statement
    ("member -> free minutes -> 30", 4 words) against a verbose prose truth
    statement (10 words) for the length gap alone, even though the short
    side is fully contained in the long one; dividing by min(|A|, |B|)
    instead measures exactly that containment, which is what a terse
    paraphrase actually needs. It is more permissive on same-length hard
    negatives than Dice (a single swapped word among many shared ones can
    still score high under either), so it doesn't fix the "different owner/
    team" category — see the calibration report and the module docstring."""
    words_a = _words(a)
    words_b = _words(b)
    if not words_a or not words_b:
        return 1.0 if words_a == words_b else 0.0
    counts_a = Counter(words_a)
    counts_b = Counter(words_b)
    overlap = sum((counts_a & counts_b).values())
    return overlap / min(len(words_a), len(words_b))


_WORD_JOINERS = re.compile(r"[-_]+")


def _words(text: str) -> list[str]:
    """Word list for `_text_similarity`: `-`/`_` are separators, not glue —
    a graph-edge-style attribute name ("free_minutes") or a hyphenated
    entity name ("member-free-minutes") must split the same way prose would
    ("free minutes" / "member free minutes"), matching `norm_entity`'s
    treatment of the same characters. Plain `norm()` alone would keep
    "free_minutes" as one token (`_` is a regex word character) while never
    reassembling "->" into a separator (it's stripped with no space left
    behind but the words either side already had one), so a graph-edge
    candidate would share almost no tokens with a prose truth statement. A
    trailing "s" is then dropped from words over 3 letters (a deliberately
    tiny stemmer, not a real one) — "member"/"members" and "refund"/
    "refunds" are singular-vs-plural spellings of the same content word and
    calibration measured several genuine paraphrases losing that one word's
    credit to the mismatch alone."""
    return [_destem(w) for w in norm(_WORD_JOINERS.sub(" ", text)).split()]


def _destem(word: str) -> str:
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def facts_match(returned: dict[str, Any], truth_fact: TruthFact) -> bool:
    """(a) shared entity, (b) shared cited document, (c) `_statement_matches`
    on the two statements (number-aware, negation-guarded). Entities here are
    expected to already be resolved ids (see `resolve_fact_entities`) —
    `facts_match` itself does no name alignment, so a caller working directly
    with arm-returned names must resolve them first."""
    citations = returned.get("citations") or []
    if not citations:
        return False
    returned_entities = set(returned.get("entities") or [])
    if not returned_entities & set(truth_fact.entities):
        return False
    returned_docs = {c["document"] for c in citations}
    truth_docs = {c.document for c in truth_fact.carriers}
    if not returned_docs & truth_docs:
        return False
    return _statement_matches(returned.get("statement", ""), truth_fact.statement)


# --------------------------------------------------------------------------
# Entity alignment (arms return names; the scorer aligns them to ids)
# --------------------------------------------------------------------------

_ENTITY_PUNCT = re.compile(r"[^\w\s-]")
_ENTITY_SEPARATORS = re.compile(r"[-_\s]+")
_FUZZY_CUTOFF = 0.88


def norm_entity(text: str) -> str:
    """Entity-name normalisation: case-insensitive, and `-`/`_` are treated
    as word separators (collapsed to a single space, same as whitespace) —
    unlike statement `norm()`, which strips punctuation outright. Entity
    names are identifiers with conventional separators ("member-free-
    minutes" and "member free minutes" name the same thing); statement
    `norm()` is comparing prose, where that distinction doesn't apply."""
    text = text.lower().strip()
    text = _ENTITY_PUNCT.sub("", text)
    text = _ENTITY_SEPARATORS.sub(" ", text)
    return text.strip()


def build_alias_index(truth: Truth) -> dict[str, str]:
    """Normalised name/alias/id -> entity id. Registers each entity's own id
    and name from `entities.yaml`, then every name/alias from
    `aliases.yaml` (tolerant of that file being absent — see
    `bench.truth.load_aliases`). First registration wins on a collision
    (stable, since dict iteration is insertion order)."""
    index: dict[str, str] = {}
    for entity in truth.entities.values():
        for key in (entity.id, entity.name):
            index.setdefault(norm_entity(key), entity.id)
    for entry in truth.aliases.values():
        for key in (entry.name, *entry.aliases):
            index.setdefault(norm_entity(key), entry.id)
    return index


def _fuzzy_resolve(key: str, index: dict[str, str]) -> str | None:
    """A conservative fallback: only when a name has no exact normalised
    match, and only when the closest candidate at `_FUZZY_CUTOFF` is
    unambiguous (no second candidate at the same cutoff naming a *different*
    entity) — otherwise this returns None rather than guess."""
    candidates = difflib.get_close_matches(key, index.keys(), n=2, cutoff=_FUZZY_CUTOFF)
    if not candidates:
        return None
    best_id = index[candidates[0]]
    if len(candidates) > 1 and index[candidates[1]] != best_id:
        return None
    return best_id


def align_entities(names: Iterable[str], index: dict[str, str]) -> tuple[list[str], list[str]]:
    """Resolves each name (exact normalised match, else the fuzzy fallback)
    to an entity id. Returns (resolved ids, deduped, in first-seen order;
    unresolved names, in input order)."""
    resolved: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for raw in names:
        key = norm_entity(str(raw))
        entity_id = index.get(key) or _fuzzy_resolve(key, index)
        if entity_id is None:
            unresolved.append(raw)
        elif entity_id not in seen:
            resolved.append(entity_id)
            seen.add(entity_id)
    return resolved, unresolved


def resolve_fact_entities(fact: dict[str, Any], index: dict[str, str]) -> dict[str, Any]:
    """A shallow copy of `fact` with `entities` (arm-returned names)
    replaced by resolved truth ids; unresolved names are kept under the
    private `_unresolved_entities` key for the audit trail."""
    names = fact.get("entities") or []
    resolved, unresolved = align_entities(names, index)
    out = dict(fact)
    out["entities"] = resolved
    out["_unresolved_entities"] = unresolved
    return out


def _resolve_contradiction_entities(rc: dict[str, Any], index: dict[str, str]) -> dict[str, Any]:
    out = dict(rc)
    for key in ("a", "b", "winner"):
        if rc.get(key) is not None:
            out[key] = resolve_fact_entities(rc[key], index)
    return out


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


def _version_matches(returned_version: Any, truth_version: str, commits: dict[str, Any]) -> bool:
    """String-equal, or the truth version is a step id that commits.json maps
    to the SHA the returned citation carries."""
    if returned_version == truth_version:
        return True
    info = commits.get(truth_version)
    return bool(info) and info.get("sha") == returned_version


def _shares_matching_version(
    returned: dict[str, Any], truth_fact: TruthFact, commits: dict[str, Any]
) -> bool:
    """True if some document cited by `returned` is also a carrier of
    `truth_fact`, with the same version (see _version_matches)."""
    citation_versions = {c["document"]: c.get("version") for c in (returned.get("citations") or [])}
    for carrier in truth_fact.carriers:
        returned_version = citation_versions.get(carrier.document)
        if returned_version is not None and carrier.version is not None:
            if _version_matches(returned_version, carrier.version, commits):
                return True
    return False


def match_facts(
    returned_facts: list[dict[str, Any]],
    expected: dict[str, TruthFact],
    commits: dict[str, Any] | None = None,
) -> tuple[list[tuple[dict[str, Any], str]], int]:
    """One-to-one match; each expected fact matches at most once. When a
    returned fact could match more than one still-unmatched expected fact,
    prefer one whose carrier version agrees with the returned citation's
    version (see _shares_matching_version); otherwise take candidates in
    `expected`'s order (greedy first-match). Returns (matches, uncited_count).
    Entities on `returned_facts` are expected to already be resolved ids.
    """
    commits = commits or {}
    matched_ids: set[str] = set()
    matches: list[tuple[dict[str, Any], str]] = []
    uncited = 0
    for rf in returned_facts:
        if not rf.get("citations"):
            uncited += 1
            continue
        candidates = [
            fid for fid, tf in expected.items() if fid not in matched_ids and facts_match(rf, tf)
        ]
        if not candidates:
            continue
        preferred = [
            fid for fid in candidates if _shares_matching_version(rf, expected[fid], commits)
        ]
        chosen = preferred[0] if preferred else candidates[0]
        matches.append((rf, chosen))
        matched_ids.add(chosen)
    return matches, uncited


def _by_category_counts(
    matched_ids: set[str], expected: dict[str, TruthFact]
) -> dict[str, dict[str, int]]:
    by_category: dict[str, dict[str, int]] = {}
    for cat in {f.category for f in expected.values()}:
        cat_ids = {fid for fid, f in expected.items() if f.category == cat}
        by_category[cat] = {"tp": len(matched_ids & cat_ids), "expected": len(cat_ids)}
    return by_category


# --------------------------------------------------------------------------
# Tier / category / validity / entity-resolution / unmatched-split measures
# --------------------------------------------------------------------------

_EXECUTED = "executed"


def _has_run_citation(rf: dict[str, Any]) -> bool:
    return any(str(c.get("document", "")).startswith("run/") for c in (rf.get("citations") or []))


def _tier_stats(
    resolved: list[dict[str, Any]],
    matches: list[tuple[dict[str, Any], str]],
    expected: dict[str, TruthFact],
) -> dict[str, Any]:
    """A confusion matrix (rows = truth tier, cols = returned tier) over
    matched facts, plus executed-tier counts: `returned_executed` counts
    EVERY returned fact claiming `executed` (matched or not — an unmatched
    "executed" claim is still a wrong claim, and must reduce precision), and
    a hard error is any returned fact claiming `executed` with no `run/`
    citation, counted separately from the confusion matrix."""
    confusion: dict[str, dict[str, int]] = {}
    for rf, fid in matches:
        truth_tier = expected[fid].tier
        returned_tier = rf.get("tier")
        row = confusion.setdefault(truth_tier, {})
        row[returned_tier] = row.get(returned_tier, 0) + 1

    hard_errors = 0
    returned_executed = 0
    for rf in resolved:
        if rf.get("tier") == _EXECUTED:
            returned_executed += 1
            if not _has_run_citation(rf):
                hard_errors += 1

    tp_executed = sum(
        1 for rf, fid in matches if rf.get("tier") == _EXECUTED and expected[fid].tier == _EXECUTED
    )
    expected_executed = sum(1 for f in expected.values() if f.tier == _EXECUTED)

    return {
        "confusion": confusion,
        "hard_errors": hard_errors,
        "returned_executed": returned_executed,
        "tp_executed": tp_executed,
        "expected_executed": expected_executed,
    }


def _category_accuracy(
    matches: list[tuple[dict[str, Any], str]], expected: dict[str, TruthFact]
) -> dict[str, int]:
    correct = 0
    for rf, fid in matches:
        returned_cat = str(rf.get("category") or "").strip().lower()
        truth_cat = expected[fid].category.strip().lower()
        if returned_cat == truth_cat:
            correct += 1
    return {"correct": correct, "total": len(matches)}


def _temporal_field_matches(
    returned_value: Any, truth_value: str | None, commits: dict[str, Any]
) -> bool:
    if truth_value is None:
        return returned_value is None
    if returned_value is None:
        return False
    return _version_matches(str(returned_value), truth_value, commits)


def _validity_stats(
    matches: list[tuple[dict[str, Any], str]],
    expected: dict[str, TruthFact],
    commits: dict[str, Any],
) -> dict[str, int]:
    """Over matched facts whose TRUTH fact carries a valid_from or valid_to
    (facts with neither aren't "facts that carry" one, per the task, and are
    excluded from the denominator entirely). A fact counts correct only when
    both fields agree (compared by step id or by SHA via commits.json — see
    _version_matches; an open-ended None field on the truth side requires
    the returned field to also be None/absent)."""
    correct = 0
    total = 0
    for rf, fid in matches:
        truth_fact = expected[fid]
        if truth_fact.valid_from is None and truth_fact.valid_to is None:
            continue
        total += 1
        from_ok = _temporal_field_matches(rf.get("valid_from"), truth_fact.valid_from, commits)
        to_ok = _temporal_field_matches(rf.get("valid_to"), truth_fact.valid_to, commits)
        if from_ok and to_ok:
            correct += 1
    return {"correct": correct, "total": total}


def _entity_resolution_stats(
    matches: list[tuple[dict[str, Any], str]], expected: dict[str, TruthFact]
) -> dict[str, Any]:
    tp = 0
    returned_n = 0
    expected_n = 0
    unresolved: list[str] = []
    for rf, fid in matches:
        resolved_ids = set(rf.get("entities") or [])
        truth_ids = set(expected[fid].entities)
        tp += len(resolved_ids & truth_ids)
        returned_n += len(resolved_ids)
        expected_n += len(truth_ids)
        unresolved.extend(rf.get("_unresolved_entities") or [])
    return {"tp": tp, "returned": returned_n, "expected": expected_n, "unresolved": unresolved}


def classify_unmatched(
    unmatched: list[dict[str, Any]], all_facts: dict[str, TruthFact]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Splits returned facts that `match_facts` didn't match: a "hard false
    positive" shares an entity AND a cited document with some truth fact
    (anywhere in `all_facts` — see module docstring) but was rejected by
    `facts_match` on the number/negation/similarity check, i.e. it names the
    right thing at the wrong value; everything else is "unplanted" — an
    invented fact with no corresponding entity+document pair in the ground
    truth at all."""
    hard_fp: list[dict[str, Any]] = []
    unplanted: list[dict[str, Any]] = []
    for rf in unmatched:
        entities = set(rf.get("entities") or [])
        docs = {c["document"] for c in (rf.get("citations") or [])}
        shares = any(
            entities & set(tf.entities) and docs & {c.document for c in tf.carriers}
            for tf in all_facts.values()
        )
        (hard_fp if shares else unplanted).append(rf)
    return hard_fp, unplanted


def _rank_metrics(
    resolved: list[dict[str, Any]], matches: list[tuple[dict[str, Any], str]]
) -> dict[str, int]:
    """precision@5/recall@10 components, using `resolved`'s own order as
    rank. `p5_n` is min(5, len(resolved)) — see module docstring for why."""
    matched_obj_ids = {id(rf) for rf, _ in matches}
    top5 = resolved[:5]
    p5_hits = sum(1 for rf in top5 if id(rf) in matched_obj_ids)
    top10_ids = {id(rf) for rf in resolved[:10]}
    r10_hits = len({fid for rf, fid in matches if id(rf) in top10_ids})
    return {"p5_hits": p5_hits, "p5_n": len(top5), "r10_hits": r10_hits}


def score_fact_query(
    returned: list[dict[str, Any]],
    expected: dict[str, TruthFact],
    commits: dict[str, Any] | None = None,
    alias_index: dict[str, str] | None = None,
    all_facts: dict[str, TruthFact] | None = None,
) -> dict[str, Any]:
    alias_index = alias_index or {}
    all_facts = all_facts if all_facts is not None else expected
    resolved = [resolve_fact_entities(rf, alias_index) for rf in returned]
    matches, uncited = match_facts(resolved, expected, commits)
    matched_ids = {fid for _, fid in matches}
    matched_obj_ids = {id(rf) for rf, _ in matches}
    unmatched = [rf for rf in resolved if id(rf) not in matched_obj_ids]
    hard_fp, unplanted = classify_unmatched(unmatched, all_facts)

    return {
        "tp": len(matches),
        "returned": len(returned),
        "expected": len(expected),
        "uncited": uncited,
        "by_category": _by_category_counts(matched_ids, expected),
        "tier": _tier_stats(resolved, matches, expected),
        "category_accuracy": _category_accuracy(matches, expected),
        "validity": _validity_stats(matches, expected, commits or {}),
        "entity_resolution": _entity_resolution_stats(matches, expected),
        "hard_false_positives": len(hard_fp),
        "unplanted_facts": unplanted,
        "rank": _rank_metrics(resolved, matches),
    }


def score_ask_query(
    answer: dict[str, Any], expected: dict[str, TruthFact], citation_cap: int = 3
) -> dict[str, Any]:
    """A sentence is correct only if, among its citations (capped to the
    first `citation_cap`; extras ignored), at least one names a document
    that carries an expected fact whose statement the sentence's own text
    satisfies (`_statement_matches` — number-aware, negation-guarded), not
    merely a document that happens to carry *some* expected fact."""
    sentences = answer.get("sentences") or []
    doc_to_facts: dict[str, list[tuple[str, TruthFact]]] = {}
    for fid, fact in expected.items():
        for carrier in fact.carriers:
            doc_to_facts.setdefault(carrier.document, []).append((fid, fact))

    correct_sentences = 0
    covered_ids: set[str] = set()
    for sentence in sentences:
        citations = (sentence.get("citations") or [])[:citation_cap]
        if not citations:
            continue
        text = sentence.get("text", "")
        hit_ids: set[str] = set()
        for citation in citations:
            for fid, fact in doc_to_facts.get(citation["document"], []):
                if _statement_matches(text, fact.statement):
                    hit_ids.add(fid)
        if hit_ids:
            correct_sentences += 1
            covered_ids |= hit_ids

    return {
        "sentences": len(sentences),
        "correct_sentences": correct_sentences,
        "covered_facts": len(covered_ids),
        "expected": len(expected),
        "by_category": _by_category_counts(covered_ids, expected),
    }


def score_contradictions(
    returned: list[dict[str, Any]],
    expected: dict[str, Any],
    truth_facts: dict[str, TruthFact],
) -> dict[str, Any]:
    matched_ids: set[str] = set()
    winner_checked = 0
    winner_correct = 0
    for rc in returned:
        rc_a, rc_b = rc.get("a"), rc.get("b")
        if rc_a is None or rc_b is None:
            continue
        for xid, xc in expected.items():
            if xid in matched_ids:
                continue
            fa_id, fb_id = xc.facts
            truth_a, truth_b = truth_facts.get(fa_id), truth_facts.get(fb_id)
            if truth_a is None or truth_b is None:
                continue
            order1 = facts_match(rc_a, truth_a) and facts_match(rc_b, truth_b)
            order2 = facts_match(rc_a, truth_b) and facts_match(rc_b, truth_a)
            if not (order1 or order2):
                continue
            matched_ids.add(xid)
            if xc.winner is not None:
                winner_checked += 1
                expected_winner = truth_facts.get(xc.winner)
                returned_winner = rc.get("winner")
                if (
                    expected_winner is not None
                    and returned_winner is not None
                    and facts_match(returned_winner, expected_winner)
                ):
                    winner_correct += 1
            break
    return {
        "matched": len(matched_ids),
        "returned": len(returned),
        "expected": len(expected),
        "winner_checked": winner_checked,
        "winner_correct": winner_correct,
    }


def _step_dates(fixture_root: Path) -> dict[str, datetime]:
    steps_path = fixture_root / "system" / "history" / "steps.yaml"
    if not steps_path.is_file():
        return {}
    raw = yaml.safe_load(steps_path.read_text()) or []
    return {r["id"]: datetime.fromisoformat(r["date"]) for r in raw}


def _comparable(a: datetime, b: datetime) -> tuple[datetime, datetime]:
    """Drop tzinfo from both sides if only one is aware, so a date-only
    ``since`` (naive) can still be compared against an offset-aware step
    date; mixed naive/aware comparison otherwise raises TypeError."""
    if (a.tzinfo is None) != (b.tzinfo is None):
        return a.replace(tzinfo=None), b.replace(tzinfo=None)
    return a, b


def score_stale(
    returned: list[dict[str, Any]],
    since: datetime,
    stale_entries: dict[str, StaleEntry],
    step_dates: dict[str, datetime],
    truth_facts: dict[str, TruthFact],
) -> dict[str, Any]:
    """A returned fact credits EVERY still-unmatched expected entry whose
    document it cites AND whose `states` fact it matches (number-aware
    facts_match, not just a shared document — two entries can share a
    document, e.g. two stale claims on the same page, and only the one the
    returned fact's statement actually agrees with should be credited). One
    returned fact citing several such documents credits all of them, not
    just the first (a `break` here previously under-counted a flawless
    multi-citation answer)."""
    expected: dict[str, StaleEntry] = {}
    for sid, entry in stale_entries.items():
        step_date = step_dates.get(entry.changed_by)
        if step_date is None:
            continue
        step_date_cmp, since_cmp = _comparable(step_date, since)
        if step_date_cmp > since_cmp:
            expected[sid] = entry

    matched_ids: set[str] = set()
    for rf in returned:
        citations = rf.get("citations") or []
        if not citations:
            continue
        cited_docs = {c["document"] for c in citations}
        for sid, entry in expected.items():
            if sid in matched_ids:
                continue
            if entry.document not in cited_docs:
                continue
            states_fact = truth_facts.get(entry.states)
            if states_fact is not None and facts_match(rf, states_fact):
                matched_ids.add(sid)

    return {"tp": len(matched_ids), "returned": len(returned), "expected": len(expected)}


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def _merge(outcomes: list[dict[str, Any]], numeric_keys: tuple[str, ...]) -> dict[str, Any]:
    merged: dict[str, Any] = dict.fromkeys(numeric_keys, 0)
    by_category: dict[str, dict[str, int]] = {}
    for outcome in outcomes:
        for key in numeric_keys:
            merged[key] += outcome.get(key, 0)
        for cat, counts in outcome.get("by_category", {}).items():
            bucket = by_category.setdefault(cat, {"tp": 0, "expected": 0})
            bucket["tp"] += counts.get("tp", 0)
            bucket["expected"] += counts.get("expected", 0)
    merged["by_category"] = by_category
    return merged


def _merge_fact_surface(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Extends `_merge` with the tier/category/validity/entity-resolution/
    rank detail `score_fact_query` produces, all summed the same
    micro-averaged way, plus a concatenated `unplanted` audit list."""
    merged = _merge(outcomes, ("tp", "returned", "expected", "uncited", "hard_false_positives"))

    confusion: dict[str, dict[str, int]] = {}
    hard_errors = returned_executed = tp_executed = expected_executed = 0
    cat_correct = cat_total = 0
    val_correct = val_total = 0
    er_tp = er_returned = er_expected = 0
    unresolved: list[str] = []
    unplanted: list[dict[str, Any]] = []
    p5_hits = p5_n = r10_hits = 0

    for outcome in outcomes:
        tier = outcome.get("tier", {})
        for truth_tier, row in tier.get("confusion", {}).items():
            dest = confusion.setdefault(truth_tier, {})
            for returned_tier, count in row.items():
                dest[returned_tier] = dest.get(returned_tier, 0) + count
        hard_errors += tier.get("hard_errors", 0)
        returned_executed += tier.get("returned_executed", 0)
        tp_executed += tier.get("tp_executed", 0)
        expected_executed += tier.get("expected_executed", 0)

        cat = outcome.get("category_accuracy", {})
        cat_correct += cat.get("correct", 0)
        cat_total += cat.get("total", 0)

        val = outcome.get("validity", {})
        val_correct += val.get("correct", 0)
        val_total += val.get("total", 0)

        er = outcome.get("entity_resolution", {})
        er_tp += er.get("tp", 0)
        er_returned += er.get("returned", 0)
        er_expected += er.get("expected", 0)
        unresolved.extend(er.get("unresolved", []))

        unplanted.extend(outcome.get("unplanted_facts", []))

        rank = outcome.get("rank", {})
        p5_hits += rank.get("p5_hits", 0)
        p5_n += rank.get("p5_n", 0)
        r10_hits += rank.get("r10_hits", 0)

    merged["tier"] = {
        "confusion": confusion,
        "hard_errors": hard_errors,
        "precision": _ratio(tp_executed, returned_executed),
        "recall": _ratio(tp_executed, expected_executed),
        "returned_executed": returned_executed,
        "tp_executed": tp_executed,
        "expected_executed": expected_executed,
    }
    merged["category_accuracy"] = {
        "correct": cat_correct,
        "total": cat_total,
        "accuracy": _ratio(cat_correct, cat_total),
    }
    merged["validity"] = {
        "correct": val_correct,
        "total": val_total,
        "accuracy": _ratio(val_correct, val_total),
    }
    merged["entity_resolution"] = {
        "tp": er_tp,
        "returned": er_returned,
        "expected": er_expected,
        "precision": _ratio(er_tp, er_returned),
        "recall": _ratio(er_tp, er_expected),
        "unresolved": sorted(set(unresolved)),
    }
    merged["unplanted"] = unplanted
    merged["rank"] = {
        "precision_at_5": _ratio(p5_hits, p5_n),
        "recall_at_10": _ratio(r10_hits, merged["expected"]),
        "p5_hits": p5_hits,
        "p5_n": p5_n,
        "r10_hits": r10_hits,
    }
    return merged


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def f1_score(precision: float | None, recall: float | None) -> float | None:
    if precision is None and recall is None:
        return None
    if precision is None:
        return recall
    if recall is None:
        return precision
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def headline_contribution(precision: float | None, recall: float | None) -> float:
    """weight * F1, or weight * recall when precision is undefined (spec)."""
    if precision is None:
        return recall or 0.0
    score = f1_score(precision, recall)
    return score or 0.0


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


def latency_percentiles(queries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_surface: dict[str, list[float]] = {}
    for q in queries:
        by_surface.setdefault(q["surface"], []).append(q["latency_ms"])
    out: dict[str, dict[str, float]] = {}
    for surface, values in by_surface.items():
        values_sorted = sorted(values)
        out[surface] = {
            "p50_ms": _percentile(values_sorted, 50),
            "p95_ms": _percentile(values_sorted, 95),
            "n": len(values_sorted),
        }
    return out


def score(
    results: dict[str, Any],
    truth_root: Path,
    commits: dict[str, Any] | None = None,
    ask_citation_cap: int = 3,
) -> dict[str, Any]:
    truth = load_truth(truth_root)
    fixture_root = Path(results["fixture"])
    step_dates = _step_dates(fixture_root)
    weights = results.get("weights", {})
    commits = commits or {}
    alias_index = build_alias_index(truth)

    per_query: dict[str, list[dict[str, Any]]] = {s: [] for s in SURFACES}
    for q in results["queries"]:
        surface = q["surface"]
        params = q.get("params", {})
        if surface == "explain":
            raw_entity = params["entity"]
            resolved_ids, _ = align_entities([raw_entity], alias_index)
            entity_id = resolved_ids[0] if resolved_ids else None
            expected = {
                fid: f for fid, f in truth.facts.items() if entity_id and entity_id in f.entities
            }
            per_query["explain"].append(
                score_fact_query(q["result"], expected, commits, alias_index, truth.facts)
            )
        elif surface == "search":
            expects = params.get("expects") or []
            expected = {fid: truth.facts[fid] for fid in expects if fid in truth.facts}
            per_query["search"].append(
                score_fact_query(q["result"], expected, commits, alias_index, truth.facts)
            )
        elif surface == "ask":
            expects = params.get("expects") or []
            expected = {fid: truth.facts[fid] for fid in expects if fid in truth.facts}
            per_query["ask"].append(score_ask_query(q["result"], expected, ask_citation_cap))
        elif surface == "contradictions":
            raw_entity = params.get("entity")
            entity_id = None
            if raw_entity:
                resolved_ids, _ = align_entities([raw_entity], alias_index)
                entity_id = resolved_ids[0] if resolved_ids else None
            if raw_entity and entity_id:
                expected_x = {}
                for xid, xc in truth.contradictions.items():
                    # Tolerate a contradiction naming a fact id that doesn't
                    # resolve, like the unfiltered branch below does (a
                    # missing fact just contributes no entities, rather than
                    # raising) — a broken truth reference shouldn't crash
                    # scoring the surfaces that do resolve.
                    fact_a = truth.facts.get(xc.facts[0])
                    fact_b = truth.facts.get(xc.facts[1])
                    entities = (fact_a.entities if fact_a else ()) + (
                        fact_b.entities if fact_b else ()
                    )
                    if entity_id in entities:
                        expected_x[xid] = xc
            elif raw_entity and not entity_id:
                expected_x = {}
            else:
                expected_x = dict(truth.contradictions)
            resolved_result = [
                _resolve_contradiction_entities(rc, alias_index) for rc in q["result"]
            ]
            per_query["contradictions"].append(
                score_contradictions(resolved_result, expected_x, truth.facts)
            )
        elif surface == "stale":
            since = datetime.fromisoformat(params["since"])
            resolved_result = [resolve_fact_entities(rf, alias_index) for rf in q["result"]]
            per_query["stale"].append(
                score_stale(resolved_result, since, truth.stale, step_dates, truth.facts)
            )
        else:
            raise ValueError(f"unknown surface {surface!r} in results")

    surfaces: dict[str, Any] = {}

    for name in ("explain", "search"):
        m = _merge_fact_surface(per_query[name])
        precision, recall = _ratio(m["tp"], m["returned"]), _ratio(m["tp"], m["expected"])
        surfaces[name] = {
            **m,
            "precision": precision,
            "recall": recall,
            "f1": f1_score(precision, recall),
        }

    ask_keys = ("sentences", "correct_sentences", "covered_facts", "expected")
    m = _merge(per_query["ask"], ask_keys)
    precision = _ratio(m["correct_sentences"], m["sentences"])
    recall = _ratio(m["covered_facts"], m["expected"])
    surfaces["ask"] = {
        **m,
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
    }

    contradiction_keys = ("matched", "returned", "expected", "winner_checked", "winner_correct")
    m = _merge(per_query["contradictions"], contradiction_keys)
    precision = _ratio(m["matched"], m["returned"])
    recall = _ratio(m["matched"], m["expected"])
    winner_accuracy = _ratio(m["winner_correct"], m["winner_checked"])
    surfaces["contradictions"] = {
        **m,
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
        "winner_accuracy": winner_accuracy,
    }

    m = _merge(per_query["stale"], ("tp", "returned", "expected"))
    precision, recall = _ratio(m["tp"], m["returned"]), _ratio(m["tp"], m["expected"])
    surfaces["stale"] = {
        **m,
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
    }

    headline = sum(
        weights.get(name, 0)
        * headline_contribution(surfaces[name]["precision"], surfaces[name]["recall"])
        for name in SURFACES
    )
    headline_equal_weights = sum(
        headline_contribution(surfaces[name]["precision"], surfaces[name]["recall"])
        for name in SURFACES
    ) / len(SURFACES)

    return {
        "prototype": results.get("prototype"),
        "ingest": results.get("ingest"),
        "weights": weights,
        "surfaces": surfaces,
        "latency": latency_percentiles(results["queries"]),
        "headline": headline,
        "headline_equal_weights": headline_equal_weights,
        "by_query": per_query,
    }


# --------------------------------------------------------------------------
# Multiple runs and the paired-bootstrap comparison
# --------------------------------------------------------------------------

_MULTI_RUN_METRICS = ("precision", "recall", "f1")


def aggregate_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Median/min/max, across several independently-scored runs of the same
    arm, for each surface's precision/recall/f1 and (explain/search only)
    executed-tier precision. Per-run diagnostics (by-category, unplanted
    audit, entity resolution) are not re-aggregated here — see module
    docstring."""
    surfaces: dict[str, dict[str, dict[str, float]]] = {}
    for name in SURFACES:
        metrics: dict[str, dict[str, float]] = {}
        for metric in _MULTI_RUN_METRICS:
            values = [
                r["surfaces"][name].get(metric)
                for r in reports
                if r["surfaces"][name].get(metric) is not None
            ]
            if values:
                metrics[metric] = {
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values),
                }
        tier = [
            r["surfaces"][name]["tier"]["precision"]
            for r in reports
            if "tier" in r["surfaces"][name]
            and r["surfaces"][name]["tier"]["precision"] is not None
        ]
        if tier:
            metrics["executed_tier_precision"] = {
                "median": statistics.median(tier),
                "min": min(tier),
                "max": max(tier),
            }
        surfaces[name] = metrics
    return {"surfaces": surfaces}


_SURFACE_RATIO_KEYS: dict[str, tuple[str, str, str, str]] = {
    "explain": ("tp", "returned", "tp", "expected"),
    "search": ("tp", "returned", "tp", "expected"),
    "ask": ("correct_sentences", "sentences", "covered_facts", "expected"),
    "contradictions": ("matched", "returned", "matched", "expected"),
    "stale": ("tp", "returned", "tp", "expected"),
}


def _f1_from_samples(sample: list[dict[str, Any]], keys: tuple[str, str, str, str]) -> float:
    tp_p, denom_p, tp_r, denom_r = keys
    sp = sum(s.get(tp_p, 0) for s in sample)
    dp = sum(s.get(denom_p, 0) for s in sample)
    sr = sum(s.get(tp_r, 0) for s in sample)
    dr = sum(s.get(denom_r, 0) for s in sample)
    return f1_score(_ratio(sp, dp), _ratio(sr, dr)) or 0.0


def _executed_precision_from_samples(sample: list[dict[str, Any]]) -> float:
    tp = sum(s.get("tier", {}).get("tp_executed", 0) for s in sample)
    denom = sum(s.get("tier", {}).get("returned_executed", 0) for s in sample)
    return _ratio(tp, denom) or 0.0


def _bootstrap_diff(
    sample_fn: Any,
    a: list[dict[str, Any]],
    b: list[dict[str, Any]],
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    n = min(len(a), len(b))
    if n == 0:
        return {"point_diff": None, "ci_low": None, "ci_high": None, "excludes_zero": False, "n": 0}
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        sample_a = [a[i] for i in idx]
        sample_b = [b[i] for i in idx]
        diffs.append(sample_fn(sample_a) - sample_fn(sample_b))
    diffs.sort()
    point = sample_fn(a) - sample_fn(b)
    lo = _percentile(diffs, 2.5)
    hi = _percentile(diffs, 97.5)
    return {
        "point_diff": point,
        "ci_low": lo,
        "ci_high": hi,
        "excludes_zero": not (lo <= 0 <= hi),
        "n": n,
    }


def bootstrap_compare(
    per_query_a: dict[str, list[dict[str, Any]]],
    per_query_b: dict[str, list[dict[str, Any]]],
    iterations: int = 1000,
    seed: int = 0,
) -> dict[str, Any]:
    """A paired bootstrap (resampling query indices, with replacement, the
    same resample applied to both arms) over each surface's F1 and over
    executed-tier precision (pooling explain+search per-query counts — see
    module docstring). `iterations`/`seed` default to the task's own values
    (1000, fixed) but are exposed for the CLI and for faster tests."""
    result: dict[str, Any] = {"surfaces": {}}
    for surface, keys in _SURFACE_RATIO_KEYS.items():
        a = per_query_a.get(surface, [])
        b = per_query_b.get(surface, [])
        result["surfaces"][surface] = _bootstrap_diff(
            lambda s, k=keys: _f1_from_samples(s, k), a, b, iterations, seed
        )
    tier_a = per_query_a.get("explain", []) + per_query_a.get("search", [])
    tier_b = per_query_b.get("explain", []) + per_query_b.get("search", [])
    result["executed_precision"] = _bootstrap_diff(
        _executed_precision_from_samples, tier_a, tier_b, iterations, seed
    )
    return result


# --------------------------------------------------------------------------
# Matcher calibration
# --------------------------------------------------------------------------


def load_calibration(path: Path) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text()) or []


def calibrate(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Runs `_statement_matches(candidate, truth)` over a labelled set of
    {truth, candidate, expect} triples and reports the matcher's own
    precision/recall/f1, plus every misclassified pair for hand review."""
    tp = fp = fn = tn = 0
    misclassified: list[dict[str, Any]] = []
    for pair in pairs:
        predicted = _statement_matches(pair["candidate"], pair["truth"])
        expected = bool(pair["expect"])
        if predicted and expected:
            tp += 1
        elif predicted and not expected:
            fp += 1
            misclassified.append({**pair, "predicted": predicted})
        elif not predicted and expected:
            fn += 1
            misclassified.append({**pair, "predicted": predicted})
        else:
            tn += 1
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "n": len(pairs),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
        "misclassified": misclassified,
    }


def print_calibration_report(report: dict[str, Any]) -> None:
    print(
        f"calibration: n={report['n']} precision={_fmt(report['precision'])} "
        f"recall={_fmt(report['recall'])} f1={_fmt(report['f1'])}"
    )
    print(f"  tp={report['tp']} fp={report['fp']} fn={report['fn']} tn={report['tn']}")
    if report["misclassified"]:
        print(f"  {len(report['misclassified'])} misclassified:")
        for m in report["misclassified"]:
            print(
                f"    expect={m['expect']} predicted={m['predicted']} "
                f"truth={m['truth']!r} candidate={m['candidate']!r}"
            )


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _print_fact_surface_detail(s: dict[str, Any]) -> None:
    tier = s.get("tier", {})
    confusion = tier.get("confusion", {})
    if confusion:
        print("    tier confusion (rows=truth, cols=returned):")
        for truth_tier in sorted(confusion):
            row = confusion[truth_tier]
            row_str = " ".join(f"{k}={v}" for k, v in sorted(row.items()))
            print(f"      {truth_tier:<12} {row_str}")
    tp_executed = tier.get("tp_executed", 0)
    print(
        f"    tier executed: precision={_fmt(tier.get('precision'))} "
        f"({tp_executed}/{tier.get('returned_executed', 0)}) "
        f"recall={_fmt(tier.get('recall'))} ({tp_executed}/{tier.get('expected_executed', 0)}) "
        f"hard_errors={tier.get('hard_errors', 0)}"
    )
    cat = s.get("category_accuracy", {})
    print(
        f"    category accuracy={_fmt(cat.get('accuracy'))} "
        f"({cat.get('correct', 0)}/{cat.get('total', 0)})"
    )
    val = s.get("validity", {})
    print(
        f"    validity accuracy={_fmt(val.get('accuracy'))} "
        f"({val.get('correct', 0)}/{val.get('total', 0)})"
    )
    er = s.get("entity_resolution", {})
    print(
        f"    entity resolution: precision={_fmt(er.get('precision'))} "
        f"recall={_fmt(er.get('recall'))} unresolved={len(er.get('unresolved', []))}"
    )


def print_report(report: dict[str, Any], show_headline: bool = False) -> None:
    ingest = report.get("ingest") or {}
    print(f"prototype: {report.get('prototype')}")
    print("ingest:")
    print(
        f"  seconds={_fmt(ingest.get('seconds'))} input_tokens={_fmt(ingest.get('input_tokens'))} "
        f"output_tokens={_fmt(ingest.get('output_tokens'))} dollars={_fmt(ingest.get('dollars'))} "
        f"services={ingest.get('services')} documents={_fmt(ingest.get('documents'))}"
    )
    if ingest.get("model") is not None or ingest.get("calls"):
        print(
            f"  model={ingest.get('model')} embedder={ingest.get('embedder')} "
            f"calls={_fmt(ingest.get('calls'))} "
            f"embedding_tokens={_fmt(ingest.get('embedding_tokens'))} "
            f"cache_tokens={_fmt(ingest.get('cache_tokens'))}"
        )
    print()
    print(f"{'surface':<15}{'precision':<12}{'recall':<12}{'f1':<10}denominators")
    for name in SURFACES:
        s = report["surfaces"][name]
        if name == "ask":
            denom = (
                f"tp={s['correct_sentences']}/{s['sentences']} "
                f"covered={s['covered_facts']}/{s['expected']}"
            )
        elif name == "contradictions":
            denom = (
                f"matched={s['matched']}/{s['returned']} vs expected={s['expected']} "
                f"winner={s['winner_correct']}/{s['winner_checked']} "
                f"(winner_accuracy={_fmt(s['winner_accuracy'])})"
            )
        elif name in ("explain", "search"):
            denom = (
                f"tp={s['tp']}/{s['returned']} vs expected={s['expected']} uncited={s['uncited']} "
                f"hard_fp={s['hard_false_positives']} unplanted={len(s.get('unplanted', []))}"
            )
        else:
            denom = f"tp={s['tp']}/{s['returned']} vs expected={s['expected']}"
        line = f"{name:<15}{_fmt(s['precision']):<12}{_fmt(s['recall']):<12}{_fmt(s['f1']):<10}"
        print(line + denom)
        for cat, counts in sorted(s.get("by_category", {}).items()):
            print(f"    {cat:<20} tp={counts['tp']} expected={counts['expected']}")
        if name in ("explain", "search"):
            _print_fact_surface_detail(s)
        if name == "search":
            rank = s.get("rank", {})
            r10 = rank.get("r10_hits")
            print(
                f"    precision@5={_fmt(rank.get('precision_at_5'))} "
                f"({rank.get('p5_hits')}/{rank.get('p5_n')}) "
                f"recall@10={_fmt(rank.get('recall_at_10'))} ({r10}/{s['expected']})"
            )

    print()
    print(f"{'surface':<15}{'p50 (ms)':<12}{'p95 (ms)':<12}n")
    for name, lat in report["latency"].items():
        print(f"{name:<15}{lat['p50_ms']:<12.3f}{lat['p95_ms']:<12.3f}{lat['n']}")

    if show_headline:
        print()
        print(
            "headline (weighted sum of F1 / recall-where-precision-undefined): "
            f"{report['headline']:.4f}  |  equal-weights variant: "
            f"{report['headline_equal_weights']:.4f}"
        )
        print(f"weights: {report['weights']}")


def print_multi_report(reports: list[dict[str, Any]], show_headline: bool = False) -> None:
    print_report(reports[0], show_headline=show_headline)
    if len(reports) == 1:
        return
    print()
    print(f"-- across {len(reports)} runs: median / min / max --")
    agg = aggregate_reports(reports)
    print(f"{'surface':<15}{'metric':<26}{'median':<10}{'min':<10}max")
    for name in SURFACES:
        for metric, stats in agg["surfaces"].get(name, {}).items():
            print(
                f"{name:<15}{metric:<26}{_fmt(stats['median']):<10}"
                f"{_fmt(stats['min']):<10}{_fmt(stats['max'])}"
            )


def print_comparison(comparison: dict[str, Any]) -> None:
    print(f"{'surface':<20}{'diff':<10}{'ci_low':<10}{'ci_high':<10}excludes_zero")
    for name in SURFACES:
        c = comparison["surfaces"][name]
        print(
            f"{name:<20}{_fmt(c['point_diff']):<10}{_fmt(c['ci_low']):<10}{_fmt(c['ci_high']):<10}"
            f"{c['excludes_zero']} (n={c['n']} queries)"
        )
    c = comparison["executed_precision"]
    print(
        f"{'executed_precision':<20}{_fmt(c['point_diff']):<10}{_fmt(c['ci_low']):<10}"
        f"{_fmt(c['ci_high']):<10}{c['excludes_zero']} (n={c['n']} queries)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results", nargs="*", help="one or more results JSON files for a single arm"
    )
    parser.add_argument("--truth", default="truth", help="truth directory (default: truth)")
    parser.add_argument("--json", default=None, help="also write the score report as JSON")
    parser.add_argument(
        "--commits",
        default="build/commits.json",
        help=(
            "commits.json from bench/build.py, for step->SHA lookups when a "
            "returned code citation carries a SHA rather than a step id "
            "(default: build/commits.json; missing file is fine, disambiguation "
            "then falls back to plain string comparison)"
        ),
    )
    parser.add_argument(
        "--ask-citation-cap",
        type=int,
        default=3,
        help="citations considered per ask sentence, extras ignored (default: 3)",
    )
    parser.add_argument(
        "--headline",
        action="store_true",
        help=(
            "print the weighted headline (and equal-weights variant), "
            "dropped from the default output"
        ),
    )
    parser.add_argument(
        "--compare-with",
        nargs="+",
        default=None,
        metavar="FILE",
        help="a second arm's results file(s); prints a paired bootstrap against `results`",
    )
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    parser.add_argument(
        "--calibrate",
        nargs="?",
        const=DEFAULT_CALIBRATION,
        default=None,
        metavar="FILE",
        help=(
            f"run the matcher calibration set (default {DEFAULT_CALIBRATION}) and print its "
            "precision/recall; skips normal scoring"
        ),
    )
    args = parser.parse_args(argv)

    if args.calibrate is not None:
        pairs = load_calibration(Path(args.calibrate))
        print_calibration_report(calibrate(pairs))
        return 0

    if not args.results:
        parser.error("results: at least one results JSON file is required (or use --calibrate)")

    truth_root = Path(args.truth)
    commits_path = Path(args.commits)
    commits = json.loads(commits_path.read_text()) if commits_path.is_file() else {}

    results_a = [json.loads(Path(p).read_text()) for p in args.results]
    reports_a = [score(r, truth_root, commits, args.ask_citation_cap) for r in results_a]

    if args.compare_with:
        results_b = [json.loads(Path(p).read_text()) for p in args.compare_with]
        reports_b = [score(r, truth_root, commits, args.ask_citation_cap) for r in results_b]

        print(f"=== arm A: {results_a[0].get('prototype')} ===")
        print_multi_report(reports_a, show_headline=args.headline)
        print()
        print(f"=== arm B: {results_b[0].get('prototype')} ===")
        print_multi_report(reports_b, show_headline=args.headline)
        print()
        print("=== paired bootstrap (A - B), over queries ===")
        comparison = bootstrap_compare(
            reports_a[0]["by_query"],
            reports_b[0]["by_query"],
            args.bootstrap_iterations,
            args.bootstrap_seed,
        )
        print_comparison(comparison)

        if args.json:
            payload = {"a": reports_a, "b": reports_b, "comparison": comparison}
            Path(args.json).write_text(json.dumps(payload, indent=2) + "\n")
        return 0

    print_multi_report(reports_a, show_headline=args.headline)
    if args.json:
        payload = reports_a[0] if len(reports_a) == 1 else {"runs": reports_a}
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
