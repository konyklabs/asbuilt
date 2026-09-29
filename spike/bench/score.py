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
* ``facts_match`` requires every number the truth statement names (money,
  percentages, times, decimals, integers — see ``_number_tokens``) to
  appear in the returned statement; text similarity alone is not enough.
  Without this, a superseded value ("45 minutes") matches its replacement
  ("30 minutes") on wording despite naming a different fact (measured: 0.959
  similarity for that pair, 0.648 for "$25.00" vs "$30.00" — both above the
  0.6 threshold). The returned statement may name MORE numbers (the HTTP
  code beside the fact's own value — konyklabs/asbuilt#17, below); it was
  equality of the two sets until the first model run. This also governs the winner check inside
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
  alias index registers each entity's ``name`` and every ``truth/
  aliases.yaml`` alias — never the entity's own ``E-`` id, which would let an
  arm "resolve" for free by simply echoing it back; ``queries/mix.yaml``'s
  entity fields are names too, so nothing needs id lookup to keep working.
  Entity-name normalisation (``norm_entity``) is case- and whitespace-only:
  ``-``/``_`` are kept as literal, distinct characters, because the real
  fixture uses both to name DIFFERENT entities that would otherwise collide
  (``ebike_surcharge`` the flag vs ``ebike-surcharge`` the rule) — unlike
  statement ``norm()``, which strips separators outright, and unlike an
  earlier version of this function, which folded them together. Resolution
  then tries three passes in order: an exact match on that separator-
  preserving key; if that misses, an exact match on a separator-FOLDED key
  (``-``/``_``/whitespace collapsed away entirely — see ``_fold_separators``)
  over the same name/alias pool, so a query spelled with the "wrong"
  separator (or none) still ties honestly against every candidate that
  shares its letters, rather than falling to fuzzy scoring, where one
  candidate's alias could outscore the tie by a hair of text similarity and
  resolve before disambiguation ever ran (measured: "ebike surcharge" used
  to resolve to the rule for every category, because its alias "e-bike
  surcharge" scored 0.968 against both canonical names' 0.933); only then,
  if neither exact pass found anything, ``_fuzzy_resolve``
  (``difflib.get_close_matches``, cutoff 0.88). Whichever pass produces more
  than one candidate id is handed to ``_disambiguate``, which resolves a tie
  only when the caller's ``category`` maps to a preferred entity ``kind`` —
  never a guess among still-tied candidates.
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
* The negation guard (``not``/``never``/``no``/``cannot`` and the ``n't``
  contractions, word-boundary, case-insensitive) is a hard veto in
  ``_statement_matches``: a mismatch on either side's negation blocks the
  match outright, before the number or similarity checks even run, since
  "free" and "not free" can otherwise still score above the similarity
  threshold. ``off`` was on the list until konyklabs/asbuilt#17 (below).
New in konyklabs/asbuilt#17 (calibrated on the first real model run of the
test connector, 2026-09-29 — ``tests/fixtures/calibration-model-run.yaml``,
72 judged pairs; the original 118 keep passing at 1.0/1.0):

* Numbers: containment, not equality — every truth number must appear in
  the returned statement; the returned statement may name more (a fuller
  statement carrying the HTTP code or the test's own quantities beside the
  fact's number is the same fact). A missing or different number still
  fails. Eight of the run's 24 facts had been vetoed on extra numbers.
* Flag state: ``off`` is a state, not a negation. ``_flag_states`` reads
  on/enabled and off/disabled where a sentence names a state at all, and
  ``_flag_state_conflict`` vetoes when both sides name a state and share
  none; a sentence naming no state never conflicts. Under the old list
  "the flag is off" was a negated sentence and a candidate saying the same
  thing without the word was vetoed as a polarity flip.
* Claims decide the match on their own only when they AGREE in full. A
  value conflict on the same quantity (attributes match) vetoes, as
  before. A claim that agrees on the value but names the entity, attribute
  or unit in its own vocabulary (the model's ``refund`` for the truth's
  rule entity, ``severityThresholdToPause`` for ``min_severity``, ``days``
  for ``day``) hands the decision to the statement rule instead of
  vetoing — unless its attribute shares no word with the fact at all
  (``retries`` against "first 30 minutes are free"), which is a different
  quantity and still a veto. Attributes are split at camelCase boundaries
  before comparison; money units fold cents to dollars
  (``_normalise_unit``) before values are compared.
* The judged set's own numbers are pinned in ``tests/test_score.py`` at
  precision 1.0 and a recall floor of 0.68, deliberately not 1.0: the
  remaining misses are narratives of the test scenario, a negated side
  clause, a missing number and two close paraphrases, and lifting them
  would mean tuning the matcher to one model's output. Every change here
  has a judged pair in each direction.
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

from bench.truth import StaleEntry, Truth, TruthContradiction, TruthFact, load_truth  # noqa: E402

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


_NEGATION_RE = re.compile(r"\b(not|never|no|cannot)\b|\w+n't\b", re.IGNORECASE)

# konyklabs/asbuilt#17: "off" left the negation list. It is a flag STATE, not
# a negation — "the overflow_parking flag is off" and "off by default" read
# as negated sentences under the old list, so a candidate that said the same
# thing without the word ("Checkin at full station refused.") was vetoed as
# a polarity flip, and the first model run lost three facts to it. The flag
# state is instead compared on its own: on/enabled against off/disabled,
# only where a sentence names a state at all.
_FLAG_STATE_RE = re.compile(
    r"\b(?:flag|flags|toggle|setting|feature)\b[^.;]{0,40}?\b(on|off|enabled|disabled)\b"
    r"|\b(on|off)\s+by\s+default\b"
    r"|\b(?:is|are|was|were|switched|turned|set|toggled|left)\s+(on|off)\b"
    r"|\b(enabled|disabled)\b",
    re.IGNORECASE,
)
_FLAG_STATE_WORD = {"on": "on", "enabled": "on", "off": "off", "disabled": "off"}


def _flag_states(text: str) -> set[str]:
    """The flag states a sentence names, each folded to "on" or "off";
    empty when it names none (see `_FLAG_STATE_RE`)."""
    states: set[str] = set()
    for match in _FLAG_STATE_RE.finditer(text):
        word = next(g for g in match.groups() if g)
        states.add(_FLAG_STATE_WORD[word.lower()])
    return states


def _flag_state_conflict(a: str, b: str) -> bool:
    """True when both sentences name a flag state and share none — "when
    the flag is on" against "even when the flag is off". A sentence naming
    no state never conflicts (the model's "set to False before any override"
    against the truth's "off by default" is decided by the words)."""
    states_a, states_b = _flag_states(a), _flag_states(b)
    return bool(states_a) and bool(states_b) and not (states_a & states_b)


def _has_negation(text: str) -> bool:
    """ "not"/"never"/"no"/"cannot", plus any "...n't" contraction
    (isn't, doesn't, won't, don't, ...) — "cannot" and the contractions are
    additions beyond the task's literal word list: `\\bnot\\b` never matches
    inside "cannot" (no word boundary before "not" there) or inside a
    contraction (the apostrophe isn't a word-breaking character to `\\b`
    either), so a paraphrase that contracts "does not" to "doesn't" would
    otherwise silently look like agreement instead of the negation match it
    needs to be (calibration measured this directly: "can unlock" vs
    "cannot unlock" scored 0.889 similarity with no numbers to catch it)."""
    return bool(_NEGATION_RE.search(text))


_MENTION_KINDS = {"team", "service", "integration", "queue", "job", "flag"}

# konyklabs/asbuilt#7 review: a bare single-word team name/alias ("fleet")
# is often an ordinary English word too — "the nightly rebalance of the
# fleet" mentions no team at all, but the bare-word rule read it as one,
# conflicting with a genuine "ops" mention elsewhere and rejecting a correct
# paraphrase (F-092). A single-word TEAM mention is only registered when
# immediately adjacent to one of these markers; a multi-word team alias
# ("the ops team") is unambiguous on its own and needs no marker.
_TEAM_MARKERS = (
    lambda a: rf"{a}\s+team",
    lambda a: rf"team\s+{a}",
    lambda a: rf"the\s+{a}\s+on-call",
    lambda a: rf"owned\s+by\s+{a}",
    lambda a: rf"{a}\s+owns",
)
# A team-marker match is always more specific than a bare-word match would
# have been (it required the surrounding phrase, not just the word), so it
# is sorted as if it were this much longer than the bare alias — ahead of
# any ordinary single-word mention it might otherwise tie or lose to.
_TEAM_MARKER_SORT_BOOST = 1000


def build_mention_index(truth: Truth) -> list[tuple[re.Pattern[str], str, str]]:
    """(compiled word-boundary pattern, entity id, kind) for every name/
    alias of every entity whose kind is one the mention guard checks (team,
    service, integration, queue, job, flag — the "who/what does X"
    attributions a text-similarity matcher can otherwise be fooled on),
    sorted longest/most-specific-first so `_mentioned_entities` prefers a
    more specific mention over a weaker one nested inside it. No hardcoded
    vocabulary: every name/alias comes straight from the given Truth's
    `entities`/`aliases` — the real fixture's for scoring and `--calibrate`,
    the mini fixture's in the harness's own tests.

    Two guards against an ordinary word being misread as an entity mention:
    single-word TEAM names/aliases require adjacency to a marker phrase (see
    `_TEAM_MARKERS`); for the other five kinds, a single-word ALIAS (not the
    entity's own canonical `name`) is dropped entirely — a canonical name
    ("farebox", "dispatch") is what a fact is actually likely to say, while
    an invented single-word alias is more likely to double as a common word
    the fixture's authors happened to reuse."""
    entries: list[tuple[int, re.Pattern[str], str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _emit(pattern_text: str, sort_len: int, entity_id: str, kind: str) -> None:
        dedup_key = (pattern_text.lower(), entity_id)
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        entries.append(
            (sort_len, re.compile(rf"\b{pattern_text}\b", re.IGNORECASE), entity_id, kind)
        )

    def _register(text: str, entity_id: str, kind: str, canonical: bool) -> None:
        text = text.strip()
        if not text:
            return
        multi_word = " " in text
        escaped = re.escape(text)
        if kind == "team":
            if multi_word:
                _emit(escaped, len(text), entity_id, kind)
            else:
                for marker in _TEAM_MARKERS:
                    _emit(marker(escaped), _TEAM_MARKER_SORT_BOOST + len(text), entity_id, kind)
        elif multi_word or canonical:
            _emit(escaped, len(text), entity_id, kind)
        # else: a single-word, non-canonical alias for a non-team kind — dropped.

    for entity in truth.entities.values():
        if entity.kind in _MENTION_KINDS:
            _register(entity.name, entity.id, entity.kind, canonical=True)
    for alias_entry in truth.aliases.values():
        entity = truth.entities.get(alias_entry.id)
        if entity is None or entity.kind not in _MENTION_KINDS:
            continue
        _register(alias_entry.name, alias_entry.id, entity.kind, canonical=True)
        for alias in alias_entry.aliases:
            _register(alias, alias_entry.id, entity.kind, canonical=False)

    entries.sort(key=lambda e: e[0], reverse=True)
    return [(pattern, entity_id, kind) for _, pattern, entity_id, kind in entries]


def _mentioned_entities(
    text: str, mention_index: list[tuple[re.Pattern[str], str, str]]
) -> dict[str, set[str]]:
    """Entity ids mentioned in `text`, grouped by kind. Scans longest-alias-
    first (see `build_mention_index`) and marks each matched span covered,
    so a shorter alias nested inside an already-matched longer one — e.g.
    "ops" inside an already-claimed "ops team" — is never matched again."""
    covered = [False] * len(text)
    by_kind: dict[str, set[str]] = {}
    for pattern, entity_id, kind in mention_index:
        for m in pattern.finditer(text):
            start, end = m.span()
            if any(covered[start:end]):
                continue
            for i in range(start, end):
                covered[i] = True
            by_kind.setdefault(kind, set()).add(entity_id)
    return by_kind


def _entity_mention_conflict(
    statement_a: str,
    statement_b: str,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None,
) -> bool:
    """True when both statements mention an entity of the SAME kind and,
    for that kind, the two mention sets are disjoint — "Skyglass is owned
    by the ops team" vs "...the fares team" both mention a `team`, and
    {E-team-ops} / {E-team-fares} share nothing, so they conflict even
    though the rest of the sentence is identical."""
    if not mention_index:
        return False
    mentions_a = _mentioned_entities(statement_a, mention_index)
    mentions_b = _mentioned_entities(statement_b, mention_index)
    for kind in _MENTION_KINDS:
        ids_a, ids_b = mentions_a.get(kind), mentions_b.get(kind)
        if ids_a and ids_b and ids_a.isdisjoint(ids_b):
            return True
    return False


def _numeric_claim_value(value: Any) -> float | None:
    """`value` as a float, tolerant of a `$`/`,`/`%` a connector's claim
    might still carry even though truth/SCHEMA.md fixes `value` as a plain
    number (konyklabs/asbuilt#8 trace: a real connector payload emitted
    "$150.00" for a usd claim, which bare `float()` rejects) — None if it
    isn't number-shaped at all."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.startswith("$"):
        text = text[1:]
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


_UNIT_SYNONYMS = {
    "usd": "usd",
    "dollar": "usd",
    "$": "usd",
    "usd_cent": "usd",
    "cent": "usd",
    "percent": "percent",
    "%": "percent",
    "pct": "percent",
}
_UNIT_FACTORS = {"usd_cent": 0.01, "cent": 0.01}


def _normalise_unit(unit: Any) -> tuple[str | None, float]:
    """A claim unit folded to its base spelling plus the factor that takes
    a value in it to the base unit (konyklabs/asbuilt#17: the model wrote
    `15000 usd_cents` where the truth says `150 usd`, and `days` where the
    truth says `day`; both are the same claim). Unknown units keep their
    destemmed lowercase spelling with factor 1."""
    if unit is None:
        return None, 1.0
    key = _destem(str(unit).strip().lower())
    return _UNIT_SYNONYMS.get(key, key), _UNIT_FACTORS.get(key, 1.0)


def _claim_values_match(
    returned_value: Any,
    truth_value: Any,
    returned_unit: Any = None,
    truth_unit: Any = None,
) -> bool:
    """ "Equal after unit normalisation": both number-shaped (30 == 30.0,
    "$150.00" == 150.0 — see `_numeric_claim_value`) -> compared as floats
    after each side's unit factor (cents to dollars, `_normalise_unit`);
    otherwise compared as text, case-insensitively (clock times, dates,
    codes)."""
    returned_number = _numeric_claim_value(returned_value)
    truth_number = _numeric_claim_value(truth_value)
    if returned_number is not None and truth_number is not None:
        _, returned_factor = _normalise_unit(returned_unit)
        _, truth_factor = _normalise_unit(truth_unit)
        return abs(returned_number * returned_factor - truth_number * truth_factor) < 1e-9
    return str(returned_value).strip().lower() == str(truth_value).strip().lower()


def _attributes_match(returned_attr: Any, truth_attr: Any) -> bool:
    """Snake-normalised equality, or >= 0.6 on the SAME word-overlap
    coefficent `_text_similarity` uses for statements (not a raw
    `difflib.SequenceMatcher` over the token lists: measured, that scores
    "cap" vs "single_ride_cap" at 0.5, below any 0.6 cutoff, while the task
    requires this pair to pass — the overlap coefficient scores it 1.0, and
    "member_free_minutes" vs "free_minutes" 1.0, and "fee" vs "retries"
    0.0, matching all three of the task's own worked examples)."""
    if returned_attr is None or truth_attr is None:
        return False
    a, b = _split_camel(str(returned_attr)).lower(), _split_camel(str(truth_attr)).lower()
    return a == b or _text_similarity(a, b) >= _SIMILARITY_THRESHOLD


def _attribute_about(returned_attr: Any, truth_statement: str, truth_attr: Any) -> bool:
    """Whether a returned claim's attribute is about the fact at all: at
    least one of its content words (three letters or more, after camelCase
    and snake_case splitting) occurs in the truth statement or the truth
    attribute. `eligible_window_days` is about "...more than 14 days after
    the ride ended..."; `retries` is not about "first 30 minutes are free"
    (konyklabs/asbuilt#17)."""
    if returned_attr is None:
        return False
    words = {w for w in _words(_split_camel(str(returned_attr))) if len(w) >= 3}
    target = set(_words(truth_statement)) | set(_words(_split_camel(str(truth_attr or ""))))
    return bool(words & target)


_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _split_camel(text: str) -> str:
    """ "severityThresholdToPause" -> "severity Threshold To Pause", so a
    TypeScript-style attribute compares word by word like a snake_case one
    (konyklabs/asbuilt#17: the model names attributes in the code's own
    convention, and one unsplit token scored 0.0 against `min_severity`)."""
    return _CAMEL_BOUNDARY.sub(" ", text.strip())


def _claims_match(returned_claim: dict[str, Any], truth_claim: dict[str, Any]) -> bool:
    """Both sides carry a claim (`{entity, attribute, value, unit}` —
    truth/SCHEMA.md): the claim entities resolve to the same id, values
    match (`_claim_values_match`), units agree when BOTH are set (an unset
    unit on either side never blocks a match), and attributes match
    (`_attributes_match`). `returned_claim["_resolved_entities"]` is
    populated by `resolve_fact_entities` the same way the fact's own
    top-level `entities` are — this function does no name alignment
    itself."""
    truth_entity = truth_claim.get("entity")
    if truth_entity is None or truth_entity not in (returned_claim.get("_resolved_entities") or []):
        return False
    returned_unit, truth_unit = returned_claim.get("unit"), truth_claim.get("unit")
    if not _claim_values_match(
        returned_claim.get("value"), truth_claim.get("value"), returned_unit, truth_unit
    ):
        return False
    if returned_unit is not None and truth_unit is not None:
        if _normalise_unit(returned_unit)[0] != _normalise_unit(truth_unit)[0]:
            return False
    return _attributes_match(returned_claim.get("attribute"), truth_claim.get("attribute"))


def _claim_value_as_number_token(value: Any, unit: str | None) -> str | None:
    """Renders a claim's `value` in the same normalised shape
    `_number_tokens` would produce from PROSE naming it — money gets a `$`
    prefix, a percentage a `%` suffix, everything else (including a clock
    string, already "HH:MM") passes through unchanged — so it can be
    checked for membership in a statement's own number-token set (see
    `_boundary_numbers_ok`). Returns None for a value that isn't number-
    shaped at all (`_normalize_number`/float conversion both fail)."""
    if value is None:
        return None
    text = str(value)
    if unit == "usd" and not text.startswith("$"):
        text = f"${text}"
    elif unit == "percent" and not text.endswith("%"):
        text = f"{text}%"
    return _normalize_number(text)


def _boundary_numbers_ok(
    returned_numbers: set[str],
    truth_numbers: set[str],
    returned_claim: dict[str, Any] | None,
    truth_claim: dict[str, Any] | None,
) -> bool:
    """Only reached when the two statements' own number sets are NOT equal
    and exactly one side carries a claim: that side's statement may name
    MORE numbers than the other (a boundary pair — "a 30-minute ride costs
    $0.00 and a 31-minute ride costs $0.15" against a truth statement/claim
    naming just "30") as long as (a) the claim's own value is among the
    OTHER side's numbers and (b) the claim-LESS side's numbers are still a
    subset of the claim-bearing side's — nothing it names goes
    unaccounted for."""
    if truth_claim is not None and returned_claim is None:
        value_token = _claim_value_as_number_token(
            truth_claim.get("value"), truth_claim.get("unit")
        )
        return (
            value_token is not None
            and value_token in returned_numbers
            and truth_numbers <= returned_numbers
        )
    if returned_claim is not None and truth_claim is None:
        value_token = _claim_value_as_number_token(
            returned_claim.get("value"), returned_claim.get("unit")
        )
        return (
            value_token is not None
            and value_token in truth_numbers
            and returned_numbers <= truth_numbers
        )
    return False


def _claim_is_comparable(returned_claim: dict[str, Any], truth_claim: dict[str, Any]) -> bool:
    """Whether the returned claim carries enough real signal to decide the
    match on its own (konyklabs/asbuilt#8 review): its entity must have
    resolved to at least one candidate id, and its value must be present.
    When truth's own value is number-shaped (its unit implies a number —
    everything but a text-shaped clock/code claim), the returned value
    must ALSO be number-shaped (`_numeric_claim_value`), since a numeric
    truth claim compared against an unparseable returned value can only
    ever disagree, and confidently rejecting the fact on that basis is
    worse than giving it another chance via the statement path below.
    Interpretation: "value is not numeric-comparable" is read as relative
    to truth's own claim type, not an unconditional numeric requirement —
    a valid clock/code claim (e.g. "03:00") would otherwise always fail
    this check and never get to use `_claims_match`'s string-equality
    branch at all."""
    if not returned_claim.get("_resolved_entities"):
        return False
    returned_value = returned_claim.get("value")
    if returned_value is None:
        return False
    if _numeric_claim_value(truth_claim.get("value")) is not None:
        return _numeric_claim_value(returned_value) is not None
    return True


def _statement_matches(
    returned_statement: str,
    truth_statement: str,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
    returned_claim: dict[str, Any] | None = None,
    truth_claim: dict[str, Any] | None = None,
) -> bool:
    """Number-aware, negation- and entity-mention-guarded text match, now
    claim-first (konyklabs/asbuilt#8: the truth author added a numeric
    `claim` to every numeric fact, and the test connector emits one too).
    Shared by `facts_match` (which additionally requires a shared entity
    and cited document) and `ask` sentence scoring (a Sentence carries no
    claim, so it always takes the plain-statement path). A negation
    mismatch or an entity-mention conflict vetoes the match outright,
    before anything claim- or number-related is even considered.

    When BOTH sides carry a claim AND the returned one is comparable (see
    `_claim_is_comparable` — reproduced bug: an unresolved returned entity
    used to reject the fact outright even when its plain entities,
    document and statement all agreed, since `_claims_match` alone decided
    the match with no way back), the match is decided ENTIRELY by
    `_claims_match` — no statement-similarity check at all, since the
    claim is the more precise signal. Otherwise (one side has no claim, or
    the returned claim isn't usable), the number check is relaxed via
    `_boundary_numbers_ok` (a superset, not exact equality, when justified
    by a claim's own value — an incomparable returned claim is treated the
    same as no claim at all here) before falling through to the ordinary
    similarity check; with no claims involved anywhere, this is unchanged
    from before claims existed."""
    if _has_negation(returned_statement) != _has_negation(truth_statement):
        return False
    if _flag_state_conflict(returned_statement, truth_statement):
        return False
    if _entity_mention_conflict(returned_statement, truth_statement, mention_index):
        return False

    if returned_claim is not None and truth_claim is not None:
        if _claim_is_comparable(returned_claim, truth_claim):
            # konyklabs/asbuilt#17: a claim decides the match on its own only
            # when it AGREES in full. A value conflict on the same quantity
            # (attributes match: the 30-vs-45 case) vetoes. A claim that
            # agrees on the value but names the entity, attribute or unit
            # in its own vocabulary (the model's `refund` for the truth's
            # rule entity, `severityThresholdToPause` for `min_severity`)
            # is no longer a veto: the statement decides, as if the
            # returned claim were absent. Five of the first model run's
            # facts were lost to that veto with statements at 0.42-0.91.
            if _claims_match(returned_claim, truth_claim):
                return True
            same_quantity = _attributes_match(
                returned_claim.get("attribute"), truth_claim.get("attribute")
            )
            values_agree = _claim_values_match(
                returned_claim.get("value"),
                truth_claim.get("value"),
                returned_claim.get("unit"),
                truth_claim.get("unit"),
            )
            if same_quantity and not values_agree:
                return False
            if not same_quantity and not _attribute_about(
                returned_claim.get("attribute"), truth_statement, truth_claim.get("attribute")
            ):
                # A claim on the same entity with the same number but an
                # attribute that shares no word with the fact (`retries`
                # against "first 30 minutes are free") is a different
                # quantity: still a veto, as the calibration set has always
                # required.
                return False
        returned_claim = None  # vocabulary-only disagreement -> the statement decides

    returned_numbers = _number_tokens(returned_statement)
    truth_numbers = _number_tokens(truth_statement)
    # konyklabs/asbuilt#17: the truth's numbers must all appear in the
    # returned statement (a superset passes), not the two sets be equal — a
    # fuller statement naming the HTTP code or the test's own quantities
    # beside the fact's number is not a different fact. A missing or
    # different number still fails (30 against 45; 30 against nothing).
    if truth_numbers and not truth_numbers <= returned_numbers:
        if not _boundary_numbers_ok(returned_numbers, truth_numbers, returned_claim, truth_claim):
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
    phrase ("member-free-minutes") must split the same way prose would
    ("free minutes" / "member free minutes"). This is a STATEMENT-similarity
    concern only, deliberately different from `norm_entity` (entity-name
    resolution), which keeps `-`/`_` literal and distinct — collapsing them
    there would conflate different real entities (see `norm_entity`'s
    docstring); collapsing them here only affects how alike two pieces of
    PROSE look, where no such identity collision exists. Plain `norm()`
    alone would keep "free_minutes" as one token (`_` is a regex word
    character) while never reassembling "->" into a separator (it's
    stripped with no space left behind but the words either side already
    had one), so a graph-edge candidate would share almost no tokens with a
    prose truth statement. A
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


def facts_match(
    returned: dict[str, Any],
    truth_fact: TruthFact,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
) -> bool:
    """(a) shared entity, (b) shared cited document, (c) `_statement_matches`
    on the two statements (number-aware, negation-, mention- and now
    claim-guarded — konyklabs/asbuilt#8). Entities here, and the claim's own
    entity if it carries one, are expected already resolved ids (see
    `resolve_fact_entities`) — `facts_match` itself does no name alignment,
    so a caller working directly with arm-returned names must resolve them
    first."""
    returned_docs = _citation_documents(returned.get("citations"))
    if not returned_docs:
        return False
    returned_entities = set(returned.get("entities") or [])
    if not returned_entities & set(truth_fact.entities):
        return False
    truth_docs = {c.document for c in truth_fact.carriers}
    if not returned_docs & truth_docs:
        return False
    return _statement_matches(
        returned.get("statement", ""),
        truth_fact.statement,
        mention_index,
        returned.get("claim"),
        truth_fact.claim,
    )


def _citation_documents(citations: list[dict[str, Any]] | None) -> set[str]:
    """Every `document` named by `citations`, skipping any citation dict
    that lacks that key rather than raising KeyError — a malformed citation
    (konyklabs/asbuilt#7 review) is treated the same as if it weren't cited
    at all, everywhere a returned fact's citations are read."""
    return {c["document"] for c in (citations or []) if "document" in c}


# --------------------------------------------------------------------------
# Entity alignment (arms return names; the scorer aligns them to ids)
# --------------------------------------------------------------------------

_ENTITY_PUNCT = re.compile(r"[^\w\s-]")
_ENTITY_WHITESPACE = re.compile(r"\s+")
_FUZZY_CUTOFF = 0.88

# konyklabs/asbuilt#7 review: `ebike_surcharge` (a flag) and `ebike-surcharge`
# (a rule) — likewise `refund_auto_approve`/`refund-auto-approve` — are two
# DIFFERENT entities in the real fixture (truth/entities.yaml) that would
# collide if `-`/`_` were folded to the same separator. When a name is still
# ambiguous after normalisation (an exact multi-id hit, or a fuzzy match tied
# between keys naming different entities), the returned fact's own category
# picks the entity whose `kind` matches — a technical-implementation fact
# about a flag, a business-logic fact about a rule.
_CATEGORY_PREFERRED_KIND = {
    "technical-implementation": "flag",
    "business-logic": "rule",
}


def norm_entity(text: str) -> str:
    """Entity-name normalisation: case-insensitive and whitespace-collapsing
    ONLY. `-` and `_` are kept as literal, distinct characters, unlike
    statement `norm()` (which strips punctuation outright) and unlike an
    earlier version of this function (which treated them as separators) —
    see `_CATEGORY_PREFERRED_KIND` above for why collapsing them is wrong
    for entity names specifically, even though it is fine (and used) for
    statement word-overlap in `_words()`."""
    text = text.lower().strip()
    text = _ENTITY_PUNCT.sub("", text)
    text = _ENTITY_WHITESPACE.sub(" ", text)
    return text.strip()


def build_alias_index(truth: Truth) -> dict[str, list[str]]:
    """Normalised name/alias -> every entity id registered under that exact
    string (almost always one; `truth/aliases.yaml`'s own rule is "no alias
    belongs to two entities", but the index stays multi-valued as a
    defensive measure and because two DIFFERENT normalised keys can still
    tie in `_fuzzy_resolve`/`_fold_index`, which reuse the same list shape).
    Registers each entity's `name` from `entities.yaml`, then every name/
    alias from `aliases.yaml` (tolerant of that file being absent — see
    `bench.truth.load_aliases`). The entity's own `E-` id is deliberately
    NOT registered (konyklabs/asbuilt#7 review): an arm that emitted ids
    directly could otherwise "resolve" perfectly for free, defeating the
    point of measuring entity resolution at all — `queries/mix.yaml`'s own
    entity fields are names too, so there is no longer a caller that needs
    id lookup to keep working."""
    index: dict[str, list[str]] = {}

    def _register(key: str, entity_id: str) -> None:
        ids = index.setdefault(norm_entity(key), [])
        if entity_id not in ids:
            ids.append(entity_id)

    for entity in truth.entities.values():
        _register(entity.name, entity.id)
    for entry in truth.aliases.values():
        for key in (entry.name, *entry.aliases):
            _register(key, entry.id)
    return index


_SEPARATOR_FOLD = re.compile(r"[-_\s]+")


def _fold_separators(key: str) -> str:
    """`-`, `_` and whitespace runs all collapsed away entirely (not to a
    single separator) — used only for the second, separator-INSENSITIVE
    exact-match pass in `align_entities`, so "ebike surcharge",
    "ebike_surcharge" and "ebike-surcharge" all fold to "ebikesurcharge" and
    tie exactly. Without this, a query with the "wrong" separator (or none)
    fell straight to `_fuzzy_resolve`, where one candidate's alias could
    outscore the tie by a hair (measured: the rule's alias "e-bike
    surcharge" at 0.968 vs both canonical names at 0.933) and resolve on
    text-similarity luck before category disambiguation ever got a turn."""
    return _SEPARATOR_FOLD.sub("", key)


def _fold_index(index: dict[str, list[str]]) -> dict[str, list[str]]:
    folded: dict[str, list[str]] = {}
    for key, ids in index.items():
        bucket = folded.setdefault(_fold_separators(key), [])
        for entity_id in ids:
            if entity_id not in bucket:
                bucket.append(entity_id)
    return folded


def _fuzzy_resolve(key: str, index: dict[str, list[str]]) -> list[str] | None:
    """The candidate id list for the closest key(s) within `_FUZZY_CUTOFF`,
    or None if nothing is close enough. When more than one DIFFERENT
    normalised key ties for the closest match — e.g. a query "ebike
    surcharge" (space) is equally one character away from both
    "ebike_surcharge" (the flag) and "ebike-surcharge" (the rule) —
    candidates from every tied key are combined, so the caller's
    category-vs-kind disambiguation (or an unresolved result) applies the
    same as it would to an exact multi-id hit."""
    candidates = difflib.get_close_matches(key, index.keys(), n=len(index), cutoff=_FUZZY_CUTOFF)
    if not candidates:
        return None
    best_ratio = difflib.SequenceMatcher(None, key, candidates[0]).ratio()
    ids: list[str] = []
    for candidate_key in candidates:
        if difflib.SequenceMatcher(None, key, candidate_key).ratio() != best_ratio:
            break  # get_close_matches returns matches best-first
        for entity_id in index[candidate_key]:
            if entity_id not in ids:
                ids.append(entity_id)
    return ids


def _disambiguate(
    candidates: list[str] | None,
    entities: dict[str, Any],
    category: str | None,
) -> str | None:
    """None candidates -> unresolved. One candidate -> it, unconditionally.
    More than one -> resolved only when `category` maps to a preferred
    `kind` (see `_CATEGORY_PREFERRED_KIND`) that exactly one candidate has;
    otherwise unresolved — never a guess among still-tied candidates."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    preferred_kind = _CATEGORY_PREFERRED_KIND.get(category or "")
    if preferred_kind is not None:
        matching = [
            c for c in candidates if getattr(entities.get(c), "kind", None) == preferred_kind
        ]
        if len(matching) == 1:
            return matching[0]
    return None


def align_entities(
    names: Iterable[str],
    index: dict[str, list[str]],
    entities: dict[str, Any] | None = None,
    category: str | None = None,
) -> tuple[list[str], list[str]]:
    """Resolves each name to an entity id in three passes, in order: (1) an
    exact match on the separator-preserving normalised key; (2) an exact
    match on the separator-FOLDED key (see `_fold_separators`) over the SAME
    name/alias pool — this is still an exact match, not a score, so it is
    tried before any fuzzy comparison can let one candidate's phrasing win
    by a whisker; (3) `_fuzzy_resolve`, only when neither exact pass found
    anything. `_disambiguate` (category-vs-kind) runs whenever any pass
    produces more than one candidate id. `entities` (truth.entities) and
    `category` (the fact's own claimed category) are only used for that
    disambiguation; both are optional; omitting them just means an
    ambiguous name is always unresolved rather than sometimes disambiguated.
    Returns (resolved ids, deduped, in first-seen order; unresolved names,
    in input order)."""
    entities = entities or {}
    folded_index = _fold_index(index)
    resolved: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for raw in names:
        key = norm_entity(str(raw))
        candidates = index.get(key)
        if candidates is None:
            candidates = folded_index.get(_fold_separators(key))
        if candidates is None:
            candidates = _fuzzy_resolve(key, index)
        entity_id = _disambiguate(candidates, entities, category)
        if entity_id is None:
            unresolved.append(raw)
        elif entity_id not in seen:
            resolved.append(entity_id)
            seen.add(entity_id)
    return resolved, unresolved


def resolve_fact_entities(
    fact: dict[str, Any], index: dict[str, list[str]], entities: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A shallow copy of `fact` with `entities` (arm-returned names)
    replaced by resolved truth ids; unresolved names are kept under the
    private `_unresolved_entities` key for the audit trail. Disambiguation
    context is the fact's OWN `category` field — self-contained, no
    chicken-and-egg dependency on which truth fact it might go on to match.
    A `claim` (konyklabs/asbuilt#8), if present, gets its own `entity` name
    resolved the same way, into `claim["_resolved_entities"]` — `_claims_match`
    reads that rather than doing its own alignment."""
    names = fact.get("entities") or []
    resolved, unresolved = align_entities(names, index, entities, fact.get("category"))
    out = dict(fact)
    out["entities"] = resolved
    out["_unresolved_entities"] = unresolved
    claim = fact.get("claim")
    if claim is not None:
        claim_resolved, _ = align_entities(
            [str(claim.get("entity", ""))], index, entities, fact.get("category")
        )
        out["claim"] = {**claim, "_resolved_entities": claim_resolved}
    return out


def _resolve_contradiction_entities(
    rc: dict[str, Any], index: dict[str, list[str]], entities: dict[str, Any] | None = None
) -> dict[str, Any]:
    out = dict(rc)
    for key in ("a", "b", "winner"):
        if rc.get(key) is not None:
            out[key] = resolve_fact_entities(rc[key], index, entities)
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
    `truth_fact`, with a matching version (see _version_matches) on ANY of
    the citations to that document — not just the last one. A fact re-cited
    across several commits (one citation per commit its test ran at, e.g.
    the same test file cited at c4, c5 and c6) previously kept only the
    last version seen for a given document (a dict comprehension overwrites
    on a repeated key), so disambiguating against an EARLIER-versioned
    truth carrier (e.g. c4) always missed, and two truth facts sharing a
    statement and document at different versions could be paired the wrong
    way round (konyklabs/asbuilt#4 review)."""
    citation_versions: dict[str, list[Any]] = {}
    for c in returned.get("citations") or []:
        if "document" in c:
            citation_versions.setdefault(c["document"], []).append(c.get("version"))
    for carrier in truth_fact.carriers:
        if carrier.version is None:
            continue
        for returned_version in citation_versions.get(carrier.document, []):
            if returned_version is not None and _version_matches(
                returned_version, carrier.version, commits
            ):
                return True
    return False


def match_facts(
    returned_facts: list[dict[str, Any]],
    expected: dict[str, TruthFact],
    commits: dict[str, Any] | None = None,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
) -> tuple[list[tuple[dict[str, Any], str]], int]:
    """One-to-one match; each expected fact matches at most once. When a
    returned fact could match more than one still-unmatched expected fact,
    prefer one whose carrier version agrees with the returned citation's
    version (see _shares_matching_version); otherwise take candidates in
    `expected`'s order (greedy first-match). Returns (matches, uncited_count).
    Entities on `returned_facts` are expected to already be resolved ids. A
    fact is "uncited" when it has no citation with a `document` key, not
    merely an empty citations list — a malformed citation is never a
    silent KeyError (see `_citation_documents`).
    """
    commits = commits or {}
    matched_ids: set[str] = set()
    matches: list[tuple[dict[str, Any], str]] = []
    uncited = 0
    for rf in returned_facts:
        if not _citation_documents(rf.get("citations")):
            uncited += 1
            continue
        candidates = [
            fid
            for fid, tf in expected.items()
            if fid not in matched_ids and facts_match(rf, tf, mention_index)
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


def _parse_datetime_loose(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _resolve_temporal_value_to_step(value: Any, commits: dict[str, Any]) -> str | None:
    """A validity field's value — a step id, a commit SHA, or an ISO
    datetime naming a commit's instant — resolved to the step id it names.
    A datetime is matched to the step whose `commits[step]["date"]` is the
    SAME INSTANT, not the same string: an arm's own ingest naturally
    serialises the commit timestamp in its own offset (measured: UTC
    "+00:00", against the fixture's own "-05:00"/"-04:00") rather than
    echoing the fixture's form, so string equality never matched
    (konyklabs/asbuilt#4 review). Tolerates up to a 1-second rounding
    difference. A value that isn't datetime-shaped and doesn't resolve via
    `commits` is returned UNCHANGED (the same "assume it's already a step
    id" fallback `_resolve_step_or_sha` uses) rather than None — with no
    `commits.json` at hand (or a minimal one, as in a unit test), a
    returned value that's already the literal correct step id must still
    compare equal, the same as before this function existed. A value that
    IS datetime-shaped but matches no known commit returns None: a
    plausible-looking but unrecognised instant is a real non-match, not a
    step id in disguise."""
    if value is None:
        return None
    if value in commits:
        return value
    for step, info in commits.items():
        if info.get("sha") == value:
            return step
    parsed = _parse_datetime_loose(value)
    if parsed is None:
        return value
    for step, info in commits.items():
        commit_dt = _parse_datetime_loose(info.get("date"))
        if commit_dt is None:
            continue
        try:
            close_enough = abs((parsed - commit_dt).total_seconds()) <= 1.0
        except TypeError:  # one aware, one naive -- not comparable, not a match
            continue
        if close_enough:
            return step
    return None


def _first_step(commits: dict[str, Any]) -> str | None:
    order = _step_order(commits)
    return min(order, key=order.get) if order else None


def _temporal_field_matches(
    returned_value: Any,
    truth_value: str | None,
    commits: dict[str, Any],
    first_step: str | None = None,
) -> bool:
    """Resolves `returned_value` to a step id (`_resolve_temporal_value_to_
    step`) and compares it to `truth_value` (already a step id). When
    `truth_value` is None, an absent `returned_value` matches; for the
    `valid_from` field specifically, `first_step` (the earliest commit) is
    also given, since a truth fact open from the very start of history
    reasonably gets ingested with a `valid_from` stamped to the first
    commit's own date rather than omitted (measured on a real arm's
    output) — `valid_to`'s caller leaves `first_step` at its default
    (None), where only an absent value still counts as open-ended."""
    if truth_value is None:
        if returned_value is None:
            return True
        return (
            first_step is not None
            and _resolve_temporal_value_to_step(returned_value, commits) == first_step
        )
    if returned_value is None:
        return False
    return _resolve_temporal_value_to_step(returned_value, commits) == truth_value


def _validity_stats(
    matches: list[tuple[dict[str, Any], str]],
    expected: dict[str, TruthFact],
    commits: dict[str, Any],
) -> dict[str, int]:
    """Over matched facts whose TRUTH fact carries a valid_from or valid_to
    (facts with neither aren't "facts that carry" one, per the task, and are
    excluded from the denominator entirely). A fact counts correct only when
    both fields agree (compared by step id, by SHA, or by the commit's own
    date-time instant via commits.json — see
    `_resolve_temporal_value_to_step`; an open-ended `valid_to` requires the
    returned field to be None/absent, and an open-ended `valid_from` also
    accepts the first commit's own date — see `_temporal_field_matches`)."""
    correct = 0
    total = 0
    first_step = _first_step(commits)
    for rf, fid in matches:
        truth_fact = expected[fid]
        if truth_fact.valid_from is None and truth_fact.valid_to is None:
            continue
        total += 1
        from_ok = _temporal_field_matches(
            rf.get("valid_from"), truth_fact.valid_from, commits, first_step
        )
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
        docs = _citation_documents(rf.get("citations"))
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
    alias_index: dict[str, list[str]] | None = None,
    all_facts: dict[str, TruthFact] | None = None,
    entities: dict[str, Any] | None = None,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
) -> dict[str, Any]:
    alias_index = alias_index or {}
    all_facts = all_facts if all_facts is not None else expected
    resolved = [resolve_fact_entities(rf, alias_index, entities) for rf in returned]
    matches, uncited = match_facts(resolved, expected, commits, mention_index)
    matched_ids = {fid for _, fid in matches}
    matched_obj_ids = {id(rf) for rf, _ in matches}
    # A fact with no (usable) citation is already counted once, as
    # `uncited` (match_facts never even tries to match it) — it must not
    # ALSO show up as "unplanted" here, which double-counted it before.
    unmatched = [
        rf
        for rf in resolved
        if id(rf) not in matched_obj_ids and _citation_documents(rf.get("citations"))
    ]
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
    answer: dict[str, Any],
    expected: dict[str, TruthFact],
    citation_cap: int = 3,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
) -> dict[str, Any]:
    """A sentence is correct only if, among its citations (capped to the
    first `citation_cap`; extras ignored), at least one names a document
    that carries an expected fact whose statement the sentence's own text
    satisfies (`_statement_matches` — number-aware, negation- and mention-
    guarded), not merely a document that happens to carry *some* expected
    fact."""
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
            document = citation.get("document")
            if document is None:
                continue
            for fid, fact in doc_to_facts.get(document, []):
                if _statement_matches(text, fact.statement, mention_index):
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
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
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
            order1 = facts_match(rc_a, truth_a, mention_index) and facts_match(
                rc_b, truth_b, mention_index
            )
            order2 = facts_match(rc_a, truth_b, mention_index) and facts_match(
                rc_b, truth_a, mention_index
            )
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
                    and facts_match(returned_winner, expected_winner, mention_index)
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
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
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
        cited_docs = _citation_documents(rf.get("citations"))
        if not cited_docs:
            continue
        for sid, entry in expected.items():
            if sid in matched_ids:
                continue
            if entry.document not in cited_docs:
                continue
            states_fact = truth_facts.get(entry.states)
            if states_fact is not None and facts_match(rf, states_fact, mention_index):
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


def _duplicate_count(fact_dicts: list[dict[str, Any]]) -> int:
    """Extra copies (beyond the first) of a (normalised statement, cited
    document) pair across every returned fact given — the D-013 incremental-
    ingest measure (konyklabs/asbuilt#7): a later re-ingest that reproduces
    a fact already extracted, citing the same document, is a duplicate. A
    fact citing several documents contributes one (statement, document) pair
    per citation, since "the same cited document" names one document at a
    time. Only computed when `results["phase"] == "incremental"` (see
    `score()`) — on a first/full ingest, restating the same fact from two
    different, genuinely separate documents is expected corroboration, not
    a duplicate, so this measure is meaningless there."""
    counts: Counter[tuple[str, str]] = Counter()
    for rf in fact_dicts:
        statement_key = norm(rf.get("statement", ""))
        for document in _citation_documents(rf.get("citations")):
            counts[(statement_key, document)] += 1
    return sum(count - 1 for count in counts.values() if count > 1)


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
    mention_index = build_mention_index(truth)
    phase = results.get("phase")
    all_returned_facts: list[dict[str, Any]] = []

    per_query: dict[str, list[dict[str, Any]]] = {s: [] for s in SURFACES}
    for q in results["queries"]:
        surface = q["surface"]
        params = q.get("params", {})
        if surface == "explain":
            raw_entity = params["entity"]
            resolved_ids, _ = align_entities([raw_entity], alias_index, truth.entities)
            entity_id = resolved_ids[0] if resolved_ids else None
            expected = {
                fid: f for fid, f in truth.facts.items() if entity_id and entity_id in f.entities
            }
            all_returned_facts.extend(q["result"])
            per_query["explain"].append(
                {
                    **score_fact_query(
                        q["result"],
                        expected,
                        commits,
                        alias_index,
                        truth.facts,
                        truth.entities,
                        mention_index,
                    ),
                    "_query_id": q["id"],
                }
            )
        elif surface == "search":
            expects = params.get("expects") or []
            expected = {fid: truth.facts[fid] for fid in expects if fid in truth.facts}
            all_returned_facts.extend(q["result"])
            per_query["search"].append(
                {
                    **score_fact_query(
                        q["result"],
                        expected,
                        commits,
                        alias_index,
                        truth.facts,
                        truth.entities,
                        mention_index,
                    ),
                    "_query_id": q["id"],
                }
            )
        elif surface == "ask":
            expects = params.get("expects") or []
            expected = {fid: truth.facts[fid] for fid in expects if fid in truth.facts}
            per_query["ask"].append(
                {
                    **score_ask_query(q["result"], expected, ask_citation_cap, mention_index),
                    "_query_id": q["id"],
                }
            )
        elif surface == "contradictions":
            raw_entity = params.get("entity")
            entity_id = None
            if raw_entity:
                resolved_ids, _ = align_entities([raw_entity], alias_index, truth.entities)
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
                    fact_entity_ids = (fact_a.entities if fact_a else ()) + (
                        fact_b.entities if fact_b else ()
                    )
                    if entity_id in fact_entity_ids:
                        expected_x[xid] = xc
            elif raw_entity and not entity_id:
                expected_x = {}
            else:
                expected_x = dict(truth.contradictions)
            resolved_result = [
                _resolve_contradiction_entities(rc, alias_index, truth.entities)
                for rc in q["result"]
            ]
            for rc in resolved_result:
                all_returned_facts.extend(rc[k] for k in ("a", "b", "winner") if rc.get(k))
            per_query["contradictions"].append(
                {
                    **score_contradictions(resolved_result, expected_x, truth.facts, mention_index),
                    "_query_id": q["id"],
                }
            )
        elif surface == "stale":
            since = datetime.fromisoformat(params["since"])
            resolved_result = [
                resolve_fact_entities(rf, alias_index, truth.entities) for rf in q["result"]
            ]
            all_returned_facts.extend(resolved_result)
            per_query["stale"].append(
                {
                    **score_stale(
                        resolved_result,
                        since,
                        truth.stale,
                        step_dates,
                        truth.facts,
                        mention_index,
                    ),
                    "_query_id": q["id"],
                }
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

    duplicates = _duplicate_count(all_returned_facts) if phase == "incremental" else None

    return {
        "prototype": results.get("prototype"),
        "ingest": results.get("ingest"),
        "weights": weights,
        "surfaces": surfaces,
        "latency": latency_percentiles(results["queries"]),
        "headline": headline,
        "headline_equal_weights": headline_equal_weights,
        "by_query": per_query,
        "phase": phase,
        "duplicates": duplicates,
    }


# --------------------------------------------------------------------------
# The test connector's bag of facts (konyklabs/asbuilt#8): no query
# structure — a flat list of candidate Facts extracted from pytest/Vitest
# collection plus run outcomes, scored directly against the truth facts a
# test carries, before any model spend. `spike/connectors/tests/` (owned
# separately) writes `build/connector/tests-<step>.json`; this module's own
# assumption about that file's shape (an object with `facts` and
# `contradiction_candidates`, or a bare list of facts with no candidates) is
# stated once, here, since no such file exists yet to confirm it against.
# --------------------------------------------------------------------------

_TRUTH_FILTER_PREFIXES: dict[str, tuple[str, ...]] = {
    "tests": ("code/tests/", "code/dispatch/test/"),
}


def _step_order(commits: dict[str, Any]) -> dict[str, int]:
    """step id -> its position in commit order, by `commits[step]["date"]"
    (not by parsing "c<N>" out of the id — a real ingest root's step names
    aren't guaranteed to follow that convention, only the fixture's do). A
    step entry with no "date" (a minimal/partial commits dict, e.g. in a
    unit test) sorts first rather than raising KeyError."""
    ordered = sorted(commits.items(), key=lambda kv: kv[1].get("date", ""))
    return {step: i for i, (step, _) in enumerate(ordered)}


def _resolve_step_or_sha(value: str, commits: dict[str, Any]) -> str:
    """`value` may already be a step id, or a commit SHA a citation/--step
    carries instead — resolves either to the step id via commits.json.
    Returns `value` unchanged if neither matches (the caller's step-order
    lookup then simply misses it, same as an unresolved step already does)."""
    if value in commits:
        return value
    for step, info in commits.items():
        if info.get("sha") == value:
            return step
    return value


def _current_at_step(tf: TruthFact, order: dict[str, int], step_rank: int | None) -> bool:
    """Closed validity window [valid_from, valid_to] at `step_rank`
    (konyklabs/asbuilt#8 review — this was half-open, excluding `valid_to`
    itself, until the reviewer's F-011/F-012 reproduction: "F-011 must be
    expected... at c5", exactly its own `valid_to`). This function's only
    caller needs "could the connector plausibly find evidence of this fact
    in the codebase at this step", not "there is exactly one current
    value" — at a fact's own retirement step, the OLD test's assertion is
    still literally in the codebase (now failing, demoted) and the NEW
    code's value isn't proven by a passing test yet; both are legitimate
    connector targets at once, so both must be in scope there, however
    "the current value" would be phrased elsewhere. `step_rank=None` (the
    step didn't resolve) skips the validity filter rather than excluding
    everything."""
    if step_rank is None:
        return True
    if tf.valid_from is not None and order.get(tf.valid_from, step_rank) > step_rank:
        return False
    if tf.valid_to is not None and order.get(tf.valid_to, step_rank) < step_rank:
        return False
    return True


def _has_test_carrier_by_step(
    tf: TruthFact,
    prefixes: tuple[str, ...],
    order: dict[str, int],
    step_rank: int | None,
) -> bool:
    """A test-shaped carrier (`prefixes`) whose OWN `version` is at or
    before `step_rank` — the connector can't see a test carrier that
    doesn't exist in the codebase until its own version (F-012's test
    carrier is version c6: it must not be in scope at c5, even though
    F-012 overall is a `code/tests/...`-carrying fact — konyklabs/
    asbuilt#8 review). A carrier with no `version` at all never counts
    (its own timing is unknown). `step_rank=None` falls back to "has one
    at all, any version"."""
    if step_rank is None:
        return any(c.document.startswith(prefixes) for c in tf.carriers)
    return any(
        c.document.startswith(prefixes)
        and c.version is not None
        and order.get(c.version, step_rank + 1) <= step_rank
        for c in tf.carriers
    )


def _expected_tier_at_step(tf: TruthFact, step_id: str) -> str:
    """`executed` if the fact has a `run/pytest-<step_id>` or
    `run/vitest-<step_id>` carrier — an EXACT match, or a "-rerun"-suffixed
    variant ("a rerun carrier counts" — konyklabs/asbuilt#8 review); `code`
    otherwise. Every fact `score_test_connector`'s `expected` can contain
    already carries a test-shaped `code/` document (that is what put it in
    scope at all — see `_has_test_carrier_by_step`), so `code` is always a
    meaningful fallback tier here, never `documented`."""
    for c in tf.carriers:
        for framework in ("pytest", "vitest"):
            prefix = f"run/{framework}-{step_id}"
            if c.document == prefix or c.document.startswith(prefix + "-"):
                return _EXECUTED
    return "code"


def _tier_precision_recall(
    resolved: list[dict[str, Any]],
    matches: list[tuple[dict[str, Any], str]],
    expected: dict[str, TruthFact],
    tier: str,
    step_id: str,
) -> dict[str, Any]:
    """Precision/recall for one tier in isolation: among ALL returned facts
    claiming `tier` (matched or not — an unmatched claim is still a wrong
    one), what fraction correctly matched a truth fact whose tier AT
    `step_id` (`_expected_tier_at_step`, not the static, eventual
    `TruthFact.tier` — konyklabs/asbuilt#8 review) is also `tier`; among
    truth facts at that per-step `tier` within `expected`, what fraction
    got matched with that same tier claimed."""
    returned_n = sum(1 for rf in resolved if rf.get("tier") == tier)
    expected_n = sum(1 for tf in expected.values() if _expected_tier_at_step(tf, step_id) == tier)
    tp = sum(
        1
        for rf, fid in matches
        if rf.get("tier") == tier and _expected_tier_at_step(expected[fid], step_id) == tier
    )
    return {
        "tp": tp,
        "returned": returned_n,
        "expected": expected_n,
        "precision": _ratio(tp, returned_n),
        "recall": _ratio(tp, expected_n),
    }


def _step_tier_confusion(
    resolved: list[dict[str, Any]],
    matches: list[tuple[dict[str, Any], str]],
    expected: dict[str, TruthFact],
    step_id: str,
) -> dict[str, Any]:
    """Like `_tier_stats` (shared by `score_fact_query`'s explain/search
    path, which has no step concept), but compares the returned tier
    against the fact's tier AT THIS STEP (`_expected_tier_at_step`), not
    its static, eventual `TruthFact.tier` — a fact's provenance strength
    changes across the history a connector ingests incrementally
    (konyklabs/asbuilt#8 review): F-011 is `code` at c5 (demoted) but was
    `executed` at c1..c4."""
    confusion: dict[str, dict[str, int]] = {}
    for rf, fid in matches:
        truth_tier = _expected_tier_at_step(expected[fid], step_id)
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
        1
        for rf, fid in matches
        if rf.get("tier") == _EXECUTED
        and _expected_tier_at_step(expected[fid], step_id) == _EXECUTED
    )
    expected_executed = sum(
        1 for tf in expected.values() if _expected_tier_at_step(tf, step_id) == _EXECUTED
    )
    return {
        "confusion": confusion,
        "hard_errors": hard_errors,
        "returned_executed": returned_executed,
        "tp_executed": tp_executed,
        "expected_executed": expected_executed,
    }


def _claim_metrics(
    resolved: list[dict[str, Any]],
    matches: list[tuple[dict[str, Any], str]],
    expected: dict[str, TruthFact],
) -> dict[str, Any]:
    """Two honest numbers (konyklabs/asbuilt#8 review), replacing the
    earlier "claim accuracy": that version only ever looked at facts that
    had ALREADY matched by claim, so re-applying `_claims_match` to them
    was tautologically 1.0.

    precision = returned claims with a resolvable entity that agree with
    the truth claim of whatever fact they matched, over EVERY returned
    claim with a resolvable entity — matched or not, and a resolvable
    claim on a fact that didn't match at all, or that matched but
    disagrees, counts against precision, not just towards a denominator it
    never reaches.

    recall = truth facts in `expected` that carry a claim, and got matched
    by a returned claim that agrees, over every truth fact in `expected`
    that carries a claim at all.

    Both numerators are the SAME underlying count (a matched pair where
    both sides have a claim and `_claims_match` — the same predicate
    `facts_match` used to decide the match — agrees), computed once and
    read as a numerator against two different denominators."""
    matched_fid_by_obj = {id(rf): fid for rf, fid in matches}
    claim_returned = agree = 0
    for rf in resolved:
        claim = rf.get("claim")
        if claim is None or not claim.get("_resolved_entities"):
            continue
        claim_returned += 1
        fid = matched_fid_by_obj.get(id(rf))
        truth_claim = expected[fid].claim if fid is not None else None
        if truth_claim is not None and _claims_match(claim, truth_claim):
            agree += 1
    claim_expected = sum(1 for tf in expected.values() if tf.claim is not None)
    return {
        "agree": agree,
        "returned": claim_returned,
        "expected": claim_expected,
        "precision": _ratio(agree, claim_returned),
        "recall": _ratio(agree, claim_expected),
    }


def score_test_connector(
    facts_payload: dict[str, Any] | list[dict[str, Any]],
    truth_root: Path,
    step: str,
    commits: dict[str, Any] | None = None,
    truth_filter: str = "tests",
) -> dict[str, Any]:
    """Scores a connector's flat bag of candidate Facts against the truth
    facts that carry a test-shaped document (`code/tests/...` or
    `code/dispatch/test/...` by default — see `_TRUTH_FILTER_PREFIXES`; only
    "tests" is defined so far) and are current (`_current_at_step`) at
    `step` (a step id or a commit SHA — resolved via `commits`).
    `facts_payload` is either a bare list of facts, or an object with
    `facts` and `contradiction_candidates` keys (see module docstring); a
    bare list skips contradiction-candidate scoring (reported as all-zero).
    `contradiction_candidates` entries are expected in `score_contradictions`'s
    own shape (`{"a": Fact, "b": Fact, "winner": Fact | None}`), scored
    against every `truth/contradictions.yaml` entry of kind `run-vs-code`."""
    commits = commits or {}
    if isinstance(facts_payload, list):
        facts, candidates = facts_payload, []
    else:
        facts, candidates = (
            facts_payload.get("facts", []),
            facts_payload.get("contradiction_candidates", []),
        )

    truth = load_truth(truth_root)
    alias_index = build_alias_index(truth)
    mention_index = build_mention_index(truth)
    entities = truth.entities

    prefixes = _TRUTH_FILTER_PREFIXES.get(truth_filter)
    if prefixes is None:
        raise ValueError(
            f"unknown --truth-filter {truth_filter!r}; known: {sorted(_TRUTH_FILTER_PREFIXES)}"
        )
    order = _step_order(commits)
    step_id = _resolve_step_or_sha(step, commits)
    step_rank = order.get(step_id)

    expected = {
        fid: tf
        for fid, tf in truth.facts.items()
        if _has_test_carrier_by_step(tf, prefixes, order, step_rank)
        and _current_at_step(tf, order, step_rank)
    }

    resolved = [resolve_fact_entities(rf, alias_index, entities) for rf in facts]
    matches, uncited = match_facts(resolved, expected, commits, mention_index)
    matched_ids = {fid for _, fid in matches}
    matched_obj_ids = {id(rf) for rf, _ in matches}
    unmatched = [
        rf
        for rf in resolved
        if id(rf) not in matched_obj_ids and _citation_documents(rf.get("citations"))
    ]
    hard_fp, unplanted = classify_unmatched(unmatched, truth.facts)

    precision, recall = _ratio(len(matches), len(facts)), _ratio(len(matches), len(expected))
    missed = [
        {
            "id": fid,
            "statement": tf.statement,
            "test": next(
                (c.location for c in tf.carriers if c.document.startswith(prefixes)), None
            ),
        }
        for fid, tf in expected.items()
        if fid not in matched_ids
    ]

    def _run_vs_code_in_scope(xc: TruthContradiction) -> bool:
        if xc.kind != "run-vs-code":
            return False
        if step_rank is None:
            return True
        if xc.opened_by is not None and order.get(xc.opened_by, step_rank + 1) > step_rank:
            return False
        if xc.resolved_by is not None and step_rank >= order.get(xc.resolved_by, step_rank):
            return False
        return True

    run_vs_code = {xid: xc for xid, xc in truth.contradictions.items() if _run_vs_code_in_scope(xc)}
    resolved_candidates = [
        _resolve_contradiction_entities(rc, alias_index, entities) for rc in candidates
    ]

    cat_stats = _category_accuracy(matches, expected)
    cat_stats["accuracy"] = _ratio(cat_stats["correct"], cat_stats["total"])
    er_stats = _entity_resolution_stats(matches, expected)
    er_stats["precision"] = _ratio(er_stats["tp"], er_stats["returned"])
    er_stats["recall"] = _ratio(er_stats["tp"], er_stats["expected"])
    # Claim-first matching (konyklabs/asbuilt#8): a match decided entirely
    # by _claims_match (both sides carry a claim) vs. one that fell through
    # to the statement rule (see _statement_matches) — post-hoc, from the
    # same "both sides have a claim" condition _statement_matches itself
    # branches on, not a second source of truth.
    matched_by_claim = sum(
        1 for rf, fid in matches if rf.get("claim") is not None and expected[fid].claim is not None
    )
    matched_by_statement = len(matches) - matched_by_claim

    return {
        "step": step_id,
        "truth_filter": truth_filter,
        "matched_by_claim": matched_by_claim,
        "matched_by_statement": matched_by_statement,
        "tp": len(matches),
        "returned": len(facts),
        "expected": len(expected),
        "uncited": uncited,
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
        "by_tier": {
            tier: _tier_precision_recall(resolved, matches, expected, tier, step_id)
            for tier in ("executed", "code")
        },
        "tier_confusion": _step_tier_confusion(resolved, matches, expected, step_id),
        "category_accuracy": cat_stats,
        "entity_resolution": er_stats,
        "claim": _claim_metrics(resolved, matches, expected),
        "hard_false_positives": len(hard_fp),
        "unplanted_facts": unplanted,
        "missed": missed,
        "contradiction_candidates": score_contradictions(
            resolved_candidates, run_vs_code, truth.facts, mention_index
        ),
    }


def print_test_connector_report(report: dict[str, Any]) -> None:
    print(f"step: {report['step']} (truth_filter={report['truth_filter']!r})")
    print(
        f"overall: precision={_fmt(report['precision'])} recall={_fmt(report['recall'])} "
        f"f1={_fmt(report['f1'])} tp={report['tp']}/{report['returned']} "
        f"vs expected={report['expected']} uncited={report['uncited']}"
    )
    print(
        f"  matched_by_claim={report['matched_by_claim']} "
        f"matched_by_statement={report['matched_by_statement']}"
    )
    for tier, t in report["by_tier"].items():
        print(
            f"  tier={tier:<9} precision={_fmt(t['precision'])} ({t['tp']}/{t['returned']}) "
            f"recall={_fmt(t['recall'])} ({t['tp']}/{t['expected']})"
        )
    confusion = report["tier_confusion"]["confusion"]
    if confusion:
        print("tier confusion (rows=truth, cols=returned):")
        for truth_tier in sorted(confusion):
            row = " ".join(f"{k}={v}" for k, v in sorted(confusion[truth_tier].items()))
            print(f"  {truth_tier:<12} {row}")
    print(f"executed-without-run hard errors: {report['tier_confusion']['hard_errors']}")
    cat = report["category_accuracy"]
    print(f"category accuracy: {_fmt(cat.get('accuracy'))} ({cat['correct']}/{cat['total']})")
    er = report["entity_resolution"]
    print(
        f"entity resolution: precision={_fmt(er['precision'])} recall={_fmt(er['recall'])} "
        f"unresolved={len(er['unresolved'])}"
    )
    claim = report["claim"]
    print(
        f"claim precision={_fmt(claim['precision'])} ({claim['agree']}/{claim['returned']}) "
        f"recall={_fmt(claim['recall'])} ({claim['agree']}/{claim['expected']})"
    )
    print(
        f"unmatched: hard_false_positives={report['hard_false_positives']} "
        f"unplanted={len(report['unplanted_facts'])}"
    )
    print(f"missed truth facts: {len(report['missed'])}")
    for m in report["missed"]:
        print(f"  {m['id']} ({m['test']}): {m['statement']}")
    cc = report["contradiction_candidates"]
    print(
        f"run-vs-code contradiction candidates: matched={cc['matched']}/{cc['returned']} "
        f"vs expected={cc['expected']}"
    )


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


def _paired_by_query_id(
    per_query_a: list[dict[str, Any]], per_query_b: list[dict[str, Any]], label: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Aligns two arms' per-query lists by the `_query_id` each entry
    carries (attached in `score()`), not by list position — a truncating
    `min(len(a), len(b))` would silently pair the wrong queries together,
    or hide a missing one, if either arm skipped a query or the two runs
    used different mixes. Raises ValueError, rather than truncating, when
    the two arms' query id SETS for `label` differ at all."""
    ids_a = [pq["_query_id"] for pq in per_query_a]
    ids_b = [pq["_query_id"] for pq in per_query_b]
    if set(ids_a) != set(ids_b):
        only_a = sorted(set(ids_a) - set(ids_b))
        only_b = sorted(set(ids_b) - set(ids_a))
        raise ValueError(
            f"bootstrap comparison ({label}): query id sets differ between arms "
            f"(only in A: {only_a}, only in B: {only_b})"
        )
    by_id_b = {pq["_query_id"]: pq for pq in per_query_b}
    return per_query_a, [by_id_b[qid] for qid in ids_a]


def bootstrap_compare(
    per_query_a: dict[str, list[dict[str, Any]]],
    per_query_b: dict[str, list[dict[str, Any]]],
    iterations: int = 1000,
    seed: int = 0,
) -> dict[str, Any]:
    """A paired bootstrap (resampling query indices, with replacement, the
    same resample applied to both arms) over each surface's F1 and over
    executed-tier precision (pooling explain+search per-query counts — see
    module docstring). The two arms are paired by query id, not list
    position (see `_paired_by_query_id`) — this raises ValueError if either
    surface's query id set differs between the two results files, rather
    than silently truncating to whichever ran fewer queries.
    `iterations`/`seed` default to the task's own values (1000, fixed) but
    are exposed for the CLI and for faster tests."""
    result: dict[str, Any] = {"surfaces": {}}
    for surface, keys in _SURFACE_RATIO_KEYS.items():
        a, b = _paired_by_query_id(
            per_query_a.get(surface, []), per_query_b.get(surface, []), surface
        )
        result["surfaces"][surface] = _bootstrap_diff(
            lambda s, k=keys: _f1_from_samples(s, k), a, b, iterations, seed
        )
    tier_a, tier_b = _paired_by_query_id(
        per_query_a.get("explain", []) + per_query_a.get("search", []),
        per_query_b.get("explain", []) + per_query_b.get("search", []),
        "explain+search",
    )
    result["executed_precision"] = _bootstrap_diff(
        _executed_precision_from_samples, tier_a, tier_b, iterations, seed
    )
    return result


# --------------------------------------------------------------------------
# Matcher calibration
# --------------------------------------------------------------------------


def load_calibration(path: Path) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text()) or []


def calibrate(
    pairs: list[dict[str, Any]],
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
    alias_index: dict[str, list[str]] | None = None,
    entities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Runs `_statement_matches(candidate, truth)` over a labelled set of
    {truth, candidate, expect} triples and reports the matcher's own
    precision/recall/f1, plus every misclassified pair for hand review.
    `mention_index` (see `build_mention_index`) is optional; the CLI builds
    one from `--truth` so the entity-mention conflict guard is exercised the
    same way it would be scoring a real prototype. A pair may also carry
    `truth_claim`/`candidate_claim` (konyklabs/asbuilt#8, the same shape as
    TruthFact.claim/Fact.claim) to exercise claim-first matching; the
    candidate claim's `entity` (a name) is resolved via `alias_index`/
    `entities` the same way `resolve_fact_entities` would, before
    `_statement_matches` ever sees it — `truth_claim.entity` is written as
    an id directly, matching how real truth facts store it."""
    tp = fp = fn = tn = 0
    misclassified: list[dict[str, Any]] = []
    for pair in pairs:
        candidate_claim = pair.get("candidate_claim")
        if candidate_claim is not None:
            resolved_ids, _ = align_entities(
                [str(candidate_claim.get("entity", ""))], alias_index or {}, entities
            )
            candidate_claim = {**candidate_claim, "_resolved_entities": resolved_ids}
        predicted = _statement_matches(
            pair["candidate"],
            pair["truth"],
            mention_index,
            candidate_claim,
            pair.get("truth_claim"),
        )
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


def _print_fact_surface_detail(s: dict[str, Any], phase: str | None = None) -> None:
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
    # D-013 incremental phase (konyklabs/asbuilt#7): the same valid_from/
    # valid_to check IS the supersession measure once a run advances an
    # existing store past a step that changed a fact's value — a correct
    # valid_to on the OLD value is exactly "the arm recognised it was
    # superseded", so this is a relabelling, not a different computation.
    label = "supersession" if phase == "incremental" else "validity"
    print(
        f"    {label} accuracy={_fmt(val.get('accuracy'))} "
        f"({val.get('correct', 0)}/{val.get('total', 0)})"
    )
    er = s.get("entity_resolution", {})
    print(
        f"    entity resolution: precision={_fmt(er.get('precision'))} "
        f"recall={_fmt(er.get('recall'))} unresolved={len(er.get('unresolved', []))}"
    )


def print_report(report: dict[str, Any], show_headline: bool = False) -> None:
    ingest = report.get("ingest") or {}
    phase = report.get("phase")
    print(f"prototype: {report.get('prototype')}")
    if phase is not None:
        print(f"phase: {phase}")
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
    if phase == "incremental":
        print(f"  duplicates={_fmt(report.get('duplicates'))}")
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
            _print_fact_surface_detail(s, phase)
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
    parser.add_argument(
        "--facts",
        default=None,
        metavar="FILE",
        help=(
            "score a test connector's bag of candidate Facts (konyklabs/asbuilt#8) "
            "against truth facts carrying a test document; skips normal scoring"
        ),
    )
    parser.add_argument(
        "--step",
        default=None,
        help="the commit step (or SHA) --facts was extracted at; required with --facts",
    )
    parser.add_argument(
        "--truth-filter",
        default="tests",
        help=(
            "which truth facts --facts is scored against "
            f"(default: tests; known: {sorted(_TRUTH_FILTER_PREFIXES)})"
        ),
    )
    args = parser.parse_args(argv)

    if args.calibrate is not None:
        pairs = load_calibration(Path(args.calibrate))
        truth = load_truth(Path(args.truth))
        mention_index = build_mention_index(truth)
        alias_index = build_alias_index(truth)
        print_calibration_report(calibrate(pairs, mention_index, alias_index, truth.entities))
        return 0

    if args.facts is not None:
        if not args.step:
            parser.error("--facts requires --step")
        commits_path = Path(args.commits)
        commits = json.loads(commits_path.read_text()) if commits_path.is_file() else {}
        facts_payload = json.loads(Path(args.facts).read_text())
        report = score_test_connector(
            facts_payload, Path(args.truth), args.step, commits, args.truth_filter
        )
        print_test_connector_report(report)
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
        return 0

    if not args.results:
        parser.error(
            "results: at least one results JSON file is required (or use --calibrate/--facts)"
        )

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
