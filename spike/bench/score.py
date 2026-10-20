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
89 judged pairs, precision 1.0 and recall 0.64 by design; the original 118
keep passing at 1.0/1.0):

* Numbers: HTTP status codes named as such, code classes ("4xx") and digit
  ordinals ("1st") are set aside first (``_without_http_codes``) — unless
  the truth fact itself names a code, in which case codes stay on both
  sides and compare like any number; then every truth number must appear in the
  returned statement, and the returned statement may add numbers only of a
  kind the fact does not use (the cents beside the dollars, the count
  beside the rate — ``_numbers_compatible``). A second value of the fact's
  own kind still fails on the statement path, and the boundary escape
  (`_boundary_numbers_ok`) admits extras of other kinds only: a hedge
  naming both 45 and 30 minutes, or both 3 and 2 bikes, matches neither
  fact, so the contradiction winner check cannot credit it (the first
  draft let it match both, the second allowed the claim value's immediate
  neighbour; two local lens rounds caught them). On the claim path a
  candidate whose own claim names the truth value is decided by that
  claim, as it always was. A fact naming no quantity admits none ("every
  2 hours" is not "every hour"). Eight of the run's 24 facts had been vetoed on the old
  set-equality rule; the ones vetoed on a competing count of the fact's
  own kind stay vetoed by design.
* Flag state: ``off`` is a state, not a negation. ``_flag_states`` reads
  on/enabled and off/disabled where a sentence names a state at all, and
  ``_flag_state_conflict`` vetoes when both sides name a state and share
  none; a sentence naming no state never conflicts. Under the old list
  "the flag is off" was a negated sentence and a candidate saying the same
  thing without the word was vetoed as a polarity flip.
* Claims decide the match on their own only when they AGREE in full. A
  value conflict on the same quantity (attributes match) vetoes, as
  before, whatever the attribute says (a claim of 45 on a statement that
  says 30 is a candidate at odds with itself, not a paraphrase); so does a
  different attribute (``retries``, or ``snapshot_interval`` against a
  snapshot-retention fact — a different quantity) or a different unit
  after folding. A claim that agrees on value, attribute (after camelCase
  splitting, ``faultReportLockThreshold`` for ``fault_reports``) and unit
  (``days`` for ``day``, cents for dollars) but names the ENTITY its own way
  (the model's ``refund`` table for the truth's rule entity) hands the
  decision to the statement rule instead of vetoing. A second local lens
  round showed that no word rule tells ``severityThresholdToPause`` from
  ``snapshot_interval`` against ``min_severity``/``snapshot_retention``, so
  attribute vocabulary is not forgiven and the first is a miss by design.
* The judged set's own numbers are pinned in ``tests/test_score.py`` at
  precision 1.0 and a recall floor, deliberately not 1.0: the remaining
  misses are narratives of the test scenario, a negated side clause, a
  missing or competing number and close paraphrases, and lifting them
  would mean tuning the matcher to one model's output. The run's own
  cross pairs all sit far below the similarity threshold, so they prove
  nothing about the loosened rules; the set therefore also carries
  targeted hard negatives written for each rule (the hedge, the numberless
  fact, the flag-state flip at high similarity, the wrong-unit claim, the
  foreign attribute) beside the positives each rule admits.
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

New in konyklabs/asbuilt#35 (the hand audit of stack B, spike/AUDIT.md;
D-014):

* Executed-tier precision over distinct facts (`distinct_executed`): every
  returned fact claiming `executed`, from explain and search, counted once
  by id or by statement and citations, and correct when it matches any
  truth fact valid by the run's step with a run carrier at or before it
  (`_executed_by_step`; the static tier when the step is unknown). Printed and stored beside
  the per-surface lines, which stay, under the strict and the lenient
  reading, each with n and a Wilson 95% lower bound.
* Compound number words ("forty-five", "forty five", "fortyfive") are one
  number, unless the unit word heads a hyphenated modifier ("forty
  five-minute rides"); opposite outcomes ("allowed"/"refused" and their
  kin) veto like a flag-state conflict, a permitted-side statement of a
  limit included (a known false negative, accepted).
* The strict reading, the default: a statement must name the quantity the
  truth's claim is about (`_names_quantity`, on every path and in either
  reading: "lapses 7 days after" is not a grace period); a claim that
  agrees in full decides, strictly, only when the statement names the
  fact's value; and a statement must carry the fact's flag condition
  (`_drops_condition`; a flag is named with its separators folded). The
  calibration pairs this relabels say so in their own comment or `why`.
* An unmatched fact that would match a truth fact its query already
  credited is `restated`, counted apart from hard false positives and
  unplanted facts.
* Contradictions: a side's entity names lose a known `<kind>:` prefix
  before alignment, and a side states a fact on its whole statement or on
  one clause split at ";" (`_side_matches`), under the same rules, unless
  it also states the pair's other fact.
* ``--calibrate`` reports the strict and the lenient reading; a pair's
  `lenient_expect`, where it has one, is its lenient label.

New in konyklabs/asbuilt#38 (backend fidelity, D-014; truth/fidelities.yaml):

* A returned executed fact claims a fidelity in its own `fidelity` field;
  one with none (or with a value that is not a string) is `unqualified`,
  its own bucket, never a hard error. A claim of F with no cited run at F
  is a hard error (`_citation_fidelities`, by the truth's mapping, the
  Playwright citation's `project` included): a citation counts only for a
  run the truth has by the run's step, at a test that passed there
  (`truth_runs`; lens round G2). The pre-existing executed-without-run
  hard error (`_has_run_citation`) is unchanged.
* Per fidelity, on explain and search over the truth's static `fidelity`
  (as the executed line reads the static tier), and on `--facts` over the
  runs that lift a fact at the step (`_expected_fidelity_at_step`):
  precision, recall, hard errors and a confusion matrix, grouped into the
  bands at or above the real backend and below it, read from the file.
* The step rules count a Playwright run at its project's fidelity, and a
  demoted fact (`TruthFact.demoted_by`) is not lifted by its passes below
  the demoting fidelity from the demoting run's step on (`_run_counts`;
  before that failure exists the lower pass did lift); from that step
  `--facts` expects its static tier, where the demotion landed it (F-123:
  `documented`). The distinct measure is reported per claimed fidelity,
  one judgement per fact and claimed fidelity (lens round G1).
* Contradictions are counted per truth kind (`by_kind`); the report
  prints the `fake-vs-real` line, found and winner, and `--facts` scores
  its candidates against those pairs too.

New in konyklabs/asbuilt#63 (found by #36's measurement):

* Under `--facts` a fact is executed at a step when a run at or before
  the step lifts it and no demotion applies by then (`_runs_at_step`), the
  distinct measure's rule: F-050's flaky c6 keeps it executed on c1 to c5.
  Runs lift a fact only before its `valid_to`: at that step (in scope
  under the closed window then, out of scope since #66) a retired fact is
  `code`, as before.

New in konyklabs/asbuilt#66 (found while building #63):

* Under `--facts` a fact is current at step S when `valid_from` <= S <
  `valid_to` (`_current_at_step`), the fixture's own half-open window:
  the step that superseded a fact no longer expects it. Explain's
  whole-history expectation (`_fact_by_step`) is unchanged.
* Bound directions agree, negated or not (`_bound_direction_conflict`, a
  veto before the claim path): where both statements state a duration
  bound on the same number and unit, the directions they state there
  (inside: within, less than, under, up to, at most; beyond: past, after,
  more than, beyond, longer than; "over N" and "the past N" are windows,
  not read) must be the same. "A refund
  requested within 14 days is rejected." no longer matches F-013. A
  duration with no direction word states no direction and never vetoes,
  so a flip written as a window ("requested in the past 14 days") is
  credited as before. The veto refuses at the statement level only: the
  contradiction side's opposing guard credits on a non-match, so it runs
  without it (`direction_vetoes=False`, the loosest matcher), and a
  refusal never becomes a credit there (#66's lens round, X-020).
* Negation scope is not read: the plain negation veto still asks only
  whether each side is negated, so one negation for another is credited
  ("A ride is not closed as lost within 24 hours." against F-010). Two
  designs that read what a negation governs, one-way and two-way, each
  refused correct statements main credits ("A flag with no feature_flags
  row is treated as off.", F-064), so neither landed (#66's lens round).
  Of the 22 pairs written for #63, the hard negatives the bound rule or
  main refuses and the 2 positives still credited are in the calibration
  set; the three moved negations and "not docked within 24 minutes" (units
  are not compared) are known false positives, and the five complement
  paraphrases stay refused, all pinned in tests/test_score.py.
"""

from __future__ import annotations

import argparse
import difflib
import functools
import json
import math
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

from bench.truth import (  # noqa: E402
    Carrier,
    Fidelities,
    StaleEntry,
    Truth,
    TruthContradiction,
    TruthFact,
    load_truth,
)

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
# konyklabs/asbuilt#35: a tens word and a unit word make one number, joined
# by a hyphen, a space or nothing ("forty-five", "forty five", "fortyfive"
# are 45, not 40 and 5). Composed before the single words are read. A
# spaced pair does not merge where the unit word heads a hyphenated
# modifier: "forty five-minute rides" are 40 rides of 5 minutes, while the
# hyphenated "forty-five-minute" and the closed "fortyfive-minute", which
# have no space to split at, are still 45.
_TENS_WORDS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_UNIT_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_TENS_ALT = "|".join(_TENS_WORDS)
_UNITS_ALT = "|".join(_UNIT_WORDS)
_COMPOUND_NUMBER_RE = re.compile(
    rf"\b({_TENS_ALT})(?:-?({_UNITS_ALT})\b|\s+({_UNITS_ALT})\b(?!-))",
    re.IGNORECASE,
)


def _replace_number_words(text: str) -> str:
    text = _COMPOUND_NUMBER_RE.sub(
        lambda m: str(
            _NUMBER_WORDS[m.group(1).lower()] + _NUMBER_WORDS[(m.group(2) or m.group(3)).lower()]
        ),
        text,
    )
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
# A state word counts only where it ends its phrase — before punctuation,
# the end of the sentence, "by default" or a conjunction — never where it
# leads into a noun ("is on the invoice", "was disabled for maintenance"
# name no flag state; a local lens round reproduced both as false vetoes).
_STATE_END = (
    r"(?=\s*(?:[,.;:)]|$)"
    r"|\s+(?:by\s+default|and|or|when|while|then|unless|until|so|in|at|during|since|after|before|within)\b)"
)
_FLAG_STATE_RE = re.compile(
    r"\b(?:flag|flags|toggle|setting|feature)\b[^.;]{0,40}?\b(on|off|enabled|disabled)\b"
    + _STATE_END
    + r"|\b(on|off)\s+by\s+default\b"
    + r"|\b(?:is|are|was|were|switched|turned|set|toggled|left)\s+(on|off|enabled|disabled)\b"
    + _STATE_END,
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


@functools.lru_cache(maxsize=8)
def _flag_name_patterns(entries: tuple[tuple[str, str], ...]) -> list[tuple[re.Pattern[str], str]]:
    """konyklabs/asbuilt#35, lens round: every flag name and alias of the
    mention index as a pattern with separators folded, so `ebike_surcharge`
    reads "e-bike surcharge" and "ebike surcharge" too."""
    out = []
    for pattern_text, entity_id in entries:
        name = re.sub(r"\\(.)", r"\1", pattern_text.removeprefix(r"\b").removesuffix(r"\b"))
        letters = _SEPARATOR_FOLD.sub("", name.lower())
        if letters:
            body = r"[-_\s]*".join(re.escape(ch) for ch in letters)
            out.append((re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE), entity_id))
    return out


def _named_flags(
    text: str, mention_index: list[tuple[re.Pattern[str], str, str]] | None
) -> dict[str, list[re.Match[str]]]:
    """Flag entity id -> where `text` names it, separators folded."""
    if not mention_index:
        return {}
    entries = tuple((p.pattern, eid) for p, eid, kind in mention_index if kind == "flag")
    found: dict[str, list[re.Match[str]]] = {}
    for pattern, entity_id in _flag_name_patterns(entries):
        for m in pattern.finditer(text):
            found.setdefault(entity_id, []).append(m)
    return found


_NAMED_FLAG_STATE_RE = re.compile(
    r"\s*(?:(?:flag|toggle|setting)\s+)?(?:(?:is|are|was|were|turned|switched|set|toggled)\s+)?"
    r"(on|off|enabled|disabled)\b" + _STATE_END,
    re.IGNORECASE,
)


def _named_flag_states(
    text: str, mention_index: list[tuple[re.Pattern[str], str, str]] | None
) -> set[str]:
    """The state a sentence gives a flag it names without the word "flag"
    ("With the e-bike surcharge enabled, ..."), folded to "on"/"off"."""
    states: set[str] = set()
    for matches in _named_flags(text, mention_index).values():
        for m in matches:
            after = _NAMED_FLAG_STATE_RE.match(text, m.end())
            if after:
                states.add(_FLAG_STATE_WORD[after.group(1).lower()])
    return states


def _flag_state_conflict(
    a: str, b: str, mention_index: list[tuple[re.Pattern[str], str, str]] | None = None
) -> bool:
    """True when both sentences name a flag state and share none — "when
    the flag is on" against "even when the flag is off". A sentence naming
    no state never conflicts (the model's "set to False before any override"
    against the truth's "off by default" is decided by the words). A state
    given to a named flag counts too (`_named_flag_states`)."""
    states_a = _flag_states(a) | _named_flag_states(a, mention_index)
    states_b = _flag_states(b) | _named_flag_states(b, mention_index)
    return bool(states_a) and bool(states_b) and not (states_a & states_b)


# konyklabs/asbuilt#35: "allowed" and "refused" are opposite outcomes, not a
# negation, so the negation guard never saw them: "Checkin at full station
# allowed with overflow parking." matched "... is refused when the
# overflow_parking flag is off" at 0.62. Each word is folded to the outcome
# it names, and two sentences naming outcomes with none in common conflict.
_OUTCOME_RE = re.compile(
    r"\b(?:(allow(?:s|ed|ing)?|accept(?:s|ed|ing)?|permit(?:s|ted|ting)?|approv(?:e|es|ed|ing))"
    r"|(refus(?:e|es|ed|ing)|reject(?:s|ed|ing)?|den(?:y|ies|ied|ying)|declin(?:e|es|ed|ing)))\b",
    re.IGNORECASE,
)


def _outcomes(text: str) -> set[str]:
    """The outcomes a sentence names: "allowed" for allow/accept/permit/
    approve, "refused" for refuse/reject/deny/decline, in any inflection."""
    return {"allowed" if m.group(1) else "refused" for m in _OUTCOME_RE.finditer(text)}


def _outcome_conflict(a: str, b: str) -> bool:
    """True when both sentences name an outcome and share none ("allowed"
    against "refused"); a sentence naming no outcome never conflicts. The
    veto is lexical, so it also refuses a correct statement of a limit from
    its permitted side ("allowed to hold at most 2 bikes" against "a third
    check-out is refused"): a known false negative, accepted, because two
    exceptions for it each let a flipped outcome through (asbuilt#35 lens
    round)."""
    outcomes_a, outcomes_b = _outcomes(a), _outcomes(b)
    return bool(outcomes_a) and bool(outcomes_b) and not (outcomes_a & outcomes_b)


# konyklabs/asbuilt#66: a duration bound is a number and a time unit after a
# direction word, inside (`within`, `less than`, `under`, `up to`, `at most`)
# or beyond (`past`, `after`, `more than`, `beyond`, `longer than`): the
# reader of #63's withdrawn design, on the raw words, with no negation read
# into the direction. "the past 7 days" names a window, the last seven days,
# not a bound beyond them, so `past` after "the" is not read; "over" is not
# read at all, because "over N" names a window in this fixture as often as a
# bound beyond it (F-099's own truth, "above 5% over 10 minutes"; "3 fault
# reports over 7 days" for F-020's "within 7 days"), found by #66's lens
# round.
_DURATION = r"(?P<n>\d+(?:\.\d+)?)\s+(?P<unit>second|minute|hour|day|week|month|year)s?\b"
_INSIDE_WORDS = ("within", "less than", "under", "up to", "at most")
_BEYOND_WORDS = ("past", "after", "more than", "beyond", "longer than")
_BOUND_RE = re.compile(
    r"(?<!\bthe\s)\b(?P<dir>" + "|".join(_INSIDE_WORDS + _BEYOND_WORDS) + r")\s+" + _DURATION,
    re.IGNORECASE,
)


def _bound_directions(text: str) -> dict[tuple[str, str], set[str]]:
    """(number, unit) -> the directions `text` states a duration bound in
    there, "inside" or "beyond" (`_BOUND_RE`, after number words are read
    as digits)."""
    bounds: dict[tuple[str, str], set[str]] = {}
    for m in _BOUND_RE.finditer(_prenormalize_numeric_prose(text)):
        direction = "inside" if m.group("dir").lower() in _INSIDE_WORDS else "beyond"
        key = (_normalize_number(m.group("n")), m.group("unit").lower())
        bounds.setdefault(key, set()).add(direction)
    return bounds


def _bound_direction_conflict(a: str, b: str) -> bool:
    """konyklabs/asbuilt#66: True when both sentences state a duration
    bound on the same number and unit and the directions they state there
    differ ("A refund requested within 14 days is rejected." against "more
    than 14 days after"; "after 7 days is locked" against "within 7 days").
    The polarity and negation rules compare outcome words and negation, so
    a flipped bound that keeps the truth's words passed them; a flip
    written as a window the reader does not take for a bound ("requested
    in the past 14 days"; "over N" is not read either) still passes, as on
    main. It refuses at the
    statement level only (see `_side_matches`). Negated or
    not, the words decide: "not docked within 24 hours" is an inside bound
    here, so the complement "open past 24 hours" conflicts. The plain
    negation veto refuses it (F-010, #63) unless an unrelated negation
    elsewhere in the sentence pairs with the truth's: the baseline's "open
    more than 24 hours without the bike being docked ... rides aren't
    flagged" was credited that way, and is now refused, a correct statement
    refused (a known cost, counted as a hard false positive; F-010's
    complement stays its recorded false negative, credited by no rule
    rather than by accident). A duration with no
    direction word before it ("open for 24 hours", "a 7-day window",
    "older than 60 minutes") states no known direction and never conflicts:
    such a pair is left to the other rules. Known costs, each a correct
    statement refused; an unmatched correct statement counts as a hard
    false positive, so each costs precision as well as recall:
    - the inside-phrased complement of a beyond fact, which states the
      same boundary from the other side through a connective the reader
      does not follow: "must be requested within 14 days ... or it is
      rejected" (F-013), "times out unless it answers within 5 seconds",
      "waits at most 5 seconds before it times out" (F-060), "must be
      filed within 14 days ...; otherwise ... 422" (F-071). No connective
      rule is tried; a follow-up issue owns it, with units and bounds on
      money or counts;
    - a statement naming both sides of one boundary ("within 14 days ...
      more than 14 days") against a fact stating one side: the direction
      sets must be equal, so a statement still matches itself, and "past 24
      hours ... unless it is not docked within 24 hours" is refused against
      "not docked within 24 hours".
    Units are not compared ("within 24 minutes" against "within 24 hours"
    is another key, so no conflict), and bounds on money or counts are not
    read."""
    bounds_a, bounds_b = _bound_directions(a), _bound_directions(b)
    return any(bounds_a[key] != bounds_b[key] for key in bounds_a.keys() & bounds_b.keys())


def _names_quantity(
    returned_statement: str, truth_statement: str, truth_claim: dict[str, Any] | None
) -> bool:
    """konyklabs/asbuilt#35: the words of the truth claim's attribute that
    the truth statement itself uses name what the fact is about ("grace"
    for a grace period; "fee" for a fee). A returned statement naming none
    of them is about something else, however close its wording and values:
    "Membership lapses 7 days after failed renewal." against "... a grace
    period that ends 7 days after the failure" claims a lapse the grace
    period's assertions never prove. A fact whose statement uses none of
    its attribute's words ("cap" against "costs at most"), or that carries
    no claim, asks for nothing. Words compare on their first four letters,
    so "owner", "owned" and "ownership" name one quantity."""
    attribute = (truth_claim or {}).get("attribute")
    if not attribute:
        return True

    def stems(text: str) -> set[str]:
        return {w[:4] for w in _words(text)}

    named = stems(_split_camel(str(attribute))) & stems(truth_statement)
    return not named or bool(named & stems(returned_statement))


_FLAG_WORD_RE = re.compile(
    r"\b(?:flag|flags|toggle|enabled|disabled|(?:turned|switched)\s+(?:on|off))\b",
    re.IGNORECASE,
)


def _drops_condition(
    returned_statement: str,
    truth_statement: str,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None,
) -> bool:
    """konyklabs/asbuilt#35: the truth holds only under a flag state ("when
    the overflow_parking flag is on") and the returned statement carries no
    condition at all: it names no flag state and none of the flags the
    truth names, and does not say "flag" (the model's "with the
    auto-approval flag on returns 201" names its state mid-phrase, where
    `_flag_states` does not read one). "Checkin at full station refused."
    drops the condition of both F-017 (refused when the flag is off) and
    F-018 (allowed when it is on); "... allowed with overflow parking."
    keeps it by naming the flag. A flag is named with its separators
    folded ("With the e-bike surcharge enabled, ..." names ebike_surcharge),
    and "enabled"/"disabled"/"turned on"/"turned off" count as states. A
    conflicting state is `_flag_state_conflict`'s veto, not this one."""
    if not _flag_states(truth_statement) or _flag_states(returned_statement):
        return False
    if _FLAG_WORD_RE.search(returned_statement):
        return False
    if not mention_index:
        return True
    truth_flags = _mentioned_entities(truth_statement, mention_index).get("flag", set())
    truth_flags |= set(_named_flags(truth_statement, mention_index))
    returned_flags = _mentioned_entities(returned_statement, mention_index).get("flag", set())
    returned_flags |= set(_named_flags(returned_statement, mention_index))
    return not (truth_flags & returned_flags)


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
            and _extras_of_other_kinds(returned_numbers - truth_numbers, truth_numbers)
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


def _extras_of_other_kinds(extras: set[str], truth_numbers: set[str]) -> bool:
    """konyklabs/asbuilt#17: the boundary pair a claim justifies ("a
    30-minute ride costs $0.00 and a 31-minute ride costs $0.15" against
    "30") may add numbers of another kind (the amounts), never a second
    number of the claim's own kind: a first draft allowed the claim value's
    immediate neighbour (31), and a second local lens round showed that
    re-admits the hedge for every contradiction whose two values differ by
    one (3 against 2 bikes). The boundary sentence's "31 minutes" is then a
    miss by design — a token matcher cannot tell it from a competing value."""
    truth_kinds = {_number_kind(t) for t in truth_numbers}
    return all(_number_kind(extra) not in truth_kinds for extra in extras)


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
    strict: bool = True,
    direction_vetoes: bool = True,
) -> bool:
    """Number-aware, negation- and entity-mention-guarded text match, now
    claim-first (konyklabs/asbuilt#8: the truth author added a numeric
    `claim` to every numeric fact, and the test connector emits one too).
    Shared by `facts_match` (which additionally requires a shared entity
    and cited document) and `ask` sentence scoring (a Sentence carries no
    claim, so it always takes the plain-statement path). A negation
    mismatch or an entity-mention conflict vetoes the match outright,
    before anything claim- or number-related is even considered; so, since
    konyklabs/asbuilt#66, does a duration bound stated in the other
    direction (`_bound_direction_conflict`), unless
    `direction_vetoes=False`. A refusal is a refusal only where a match
    credits: a caller that credits on a NON-match (the contradiction
    side's opposing guard, `_side_matches`) passes `direction_vetoes=False`,
    the loosest matcher, so that a new refusal can never turn into a credit
    there.

    When BOTH sides carry a claim AND the returned one is comparable (see
    `_claim_is_comparable` — reproduced bug: an unresolved returned entity
    used to reject the fact outright even when its plain entities,
    document and statement all agreed), a claim that agrees in full decides
    the match on its own; a value conflict on the same quantity, or an
    attribute about something else entirely, vetoes it; any other
    disagreement (the candidate's own entity, attribute or unit vocabulary)
    hands the decision to the statement path, as if the returned claim were
    absent (konyklabs/asbuilt#17). On that path the numbers must be
    compatible (`_numbers_compatible`: HTTP codes aside, the truth's
    numbers all present, extras only of a kind the fact does not use), with
    `_boundary_numbers_ok` as the one escape when a claim on exactly one
    side justifies a boundary pair; then the word-overlap similarity
    decides.

    konyklabs/asbuilt#35, the strict reading: a statement is credited only
    when it states the fact on its own. A statement that does not name the
    quantity the truth's claim is about (`_names_quantity`) says something
    else, usually more ("lapses 7 days after" for a grace period that ends
    7 days after), and is vetoed in either reading, whether or not it
    carries a claim of its own. Under `strict` (the default) the statement
    must also carry the fact's flag condition (`_drops_condition`), and an
    agreeing claim decides only when the statement names the value too: a
    claim of 0.25 does not make "Casual rate from 1st minute." say $0.25 per
    minute. `strict=False` is the lenient reading, kept for the distinct
    executed precision's comparison line only."""
    if _has_negation(returned_statement) != _has_negation(truth_statement):
        return False
    if _flag_state_conflict(returned_statement, truth_statement, mention_index):
        return False
    if _outcome_conflict(returned_statement, truth_statement):
        return False
    if direction_vetoes and _bound_direction_conflict(returned_statement, truth_statement):
        # konyklabs/asbuilt#66: before the claim path, so an agreeing claim
        # does not credit a flipped bound either.
        return False
    if _entity_mention_conflict(returned_statement, truth_statement, mention_index):
        return False
    if not _names_quantity(returned_statement, truth_statement, truth_claim):
        # On every path, claim or none: whether an arm sent a claim does
        # not decide whether its statement over-claims (lens round).
        return False
    if strict and _drops_condition(returned_statement, truth_statement, mention_index):
        return False

    if _names_http_code(truth_statement):
        # The fact is about the response: its code is a value to agree on
        # (409 against 404 is a different fact), so codes stay on both sides
        # and compare like any other number; only ordinals are set aside.
        returned_numbers = _number_tokens(_DIGIT_ORDINAL_RE.sub(" ", returned_statement))
        truth_numbers = _number_tokens(_DIGIT_ORDINAL_RE.sub(" ", truth_statement))
    else:
        returned_numbers = _number_tokens(_without_http_codes(returned_statement))
        truth_numbers = _number_tokens(_without_http_codes(truth_statement))

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
                # konyklabs/asbuilt#35: the over-claim check above has run
                # (`_names_quantity`). Strict: the claim decides
                # only when the statement names the value as well; one that
                # leaves the value to its claim does not state the fact on
                # its own. Naming more numbers is fine here (the claim has
                # pinned the quantity): "every 15 minutes" with "the three
                # jobs" beside it still states 15.
                return not strict or truth_numbers <= returned_numbers
            values_agree = _claim_values_match(
                returned_claim.get("value"),
                truth_claim.get("value"),
                returned_claim.get("unit"),
                truth_claim.get("unit"),
            )
            if not values_agree:
                # A comparable claim whose value disagrees with the fact's
                # always vetoes (30 against 45; a claim of 45 on a statement
                # that says 30 is a candidate at odds with itself, not a
                # paraphrase — a second local lens round's case).
                return False
            if not _attributes_match(returned_claim.get("attribute"), truth_claim.get("attribute")):
                # Same entity, same number, another attribute: a different
                # quantity (`retries`; `snapshot_interval` against a
                # retention fact) — still a veto, as on main. No word rule
                # tells `severityThresholdToPause` from `snapshot_interval`
                # against `min_severity`/`snapshot_retention` (both share one
                # word of two), so the first is a miss by design.
                return False
            returned_unit, truth_unit = returned_claim.get("unit"), truth_claim.get("unit")
            if (
                returned_unit is not None
                and truth_unit is not None
                and _normalise_unit(returned_unit)[0] != _normalise_unit(truth_unit)[0]
            ):
                return False
        # Value, attribute and unit agree; only the claim's ENTITY is the
        # candidate's own (the model's `refund` for the truth's rule entity):
        # the statement decides, as if the returned claim were absent.
        returned_claim = None

    if not _numbers_compatible(returned_numbers, truth_numbers):
        if not _boundary_numbers_ok(returned_numbers, truth_numbers, returned_claim, truth_claim):
            return False
    return _text_similarity(returned_statement, truth_statement) >= _SIMILARITY_THRESHOLD


# konyklabs/asbuilt#17. An HTTP status code named as one ("HTTP 409",
# "returns 422 with", "with a 200 response", "refused with a 409
# checkout_limit_reached error") is a code, not a quantity: it is set aside
# before the two statements' numbers are compared, so a fuller statement
# naming the response code beside the fact's own number is not a different
# fact, and a truth fact about the response ("returns HTTP 409") compares
# on its words. Everything else the regex leaves is a quantity.
# Without "HTTP", a three-digit number after "returns"/"with a" is a code
# only where a code reads as one: followed by punctuation, the end, or a
# response word — never by a unit or a noun ("with a 250 limit", "with a
# 300 second delay" are quantities; a second local lens round's case).
_CODE_END = (
    r"(?=\s*(?:[,.;:)]|$)"
    r"|\s+(?:response|status|error|with|and|or|body|returning|because|when|so|then|for|to|if)\b)"
)
_HTTP_CODE_RE = re.compile(
    r"\bHTTP\s+[1-5]\d\d\b"
    r"|\b(?:returns?|returning|returned|responds?\s+with|succeeds?\s+with|refused\s+with|"
    r"rejected\s+with|fails?\s+with|with\s+an?|an?\s+status(?:\s+code)?(?:\s+of)?|status\s+code)"
    r"\s+[1-5]\d\d\b" + _CODE_END,
    re.IGNORECASE,
)


_HTTP_CODE_CLASS_RE = re.compile(r"\b[1-5]xx\b", re.IGNORECASE)
_DIGIT_ORDINAL_RE = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)


def _without_http_codes(text: str) -> str:
    """Status codes named as such, code classes ("4xx") and digit ordinals
    ("1st", "3rd" — a position, not a quantity, exactly as the spelled-out
    "first"/"third" already count for nothing) removed ahead of number
    extraction."""
    return _DIGIT_ORDINAL_RE.sub(" ", _HTTP_CODE_CLASS_RE.sub(" ", _HTTP_CODE_RE.sub(" ", text)))


def _names_http_code(text: str) -> bool:
    return bool(_HTTP_CODE_RE.search(text) or _HTTP_CODE_CLASS_RE.search(text))


def _number_kind(token: str) -> str:
    if token.startswith("$"):
        return "money"
    if token.endswith("%"):
        return "percent"
    if ":" in token:
        return "time"
    return "plain"


def _numbers_compatible(returned_numbers: set[str], truth_numbers: set[str]) -> bool:
    """Whether the returned statement's numbers are the truth's, allowing a
    fuller statement its extra numbers of a kind the fact does not use — the
    cents beside the dollars, the count beside the rate — but never a second
    value of the kind the fact is about (a hedge naming both 45 and 30
    minutes must match neither the 30 fact nor the 45 fact, or the
    contradiction winner check would credit it), and never any quantity at
    all against a fact that names none ("runs every 2 hours" is not "runs
    every hour"). HTTP codes were set aside by the caller."""
    if not truth_numbers:
        return not returned_numbers
    if not truth_numbers <= returned_numbers:
        return False
    truth_kinds = {_number_kind(t) for t in truth_numbers}
    return all(_number_kind(t) not in truth_kinds for t in returned_numbers - truth_numbers)


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
    strict: bool = True,
    direction_vetoes: bool = True,
) -> bool:
    """(a) shared entity, (b) shared cited document, (c) `_statement_matches`
    on the two statements (number-aware, negation-, mention- and now
    claim-guarded — konyklabs/asbuilt#8; `strict` as there, #35;
    `direction_vetoes` as there, #66). Entities
    here, and the claim's own entity if it carries one, are expected
    already resolved ids (see `resolve_fact_entities`) — `facts_match`
    itself does no name alignment, so a caller working directly with
    arm-returned names must resolve them first."""
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
        strict,
        direction_vetoes,
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


def _strip_kind_prefix(name: Any, kinds: set[str]) -> Any:
    """ "rule:checkout-limit" -> "checkout-limit" when "rule" is an entity
    kind of the truth; any other name unchanged (konyklabs/asbuilt#35)."""
    if isinstance(name, str) and ":" in name:
        prefix, rest = name.split(":", 1)
        if prefix.strip().lower() in kinds and rest.strip():
            return rest.strip()
    return name


def _resolve_contradiction_entities(
    rc: dict[str, Any], index: dict[str, list[str]], entities: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Each side resolved like any returned fact, after a known `<kind>:`
    prefix is stripped from its entity names and its claim's entity
    (konyklabs/asbuilt#35: the baseline names a side's entity
    "rule:checkout-limit", which no alias spells)."""
    kinds = {str(getattr(e, "kind", "")).lower() for e in (entities or {}).values()}
    out = dict(rc)
    for key in ("a", "b", "winner"):
        side = rc.get(key)
        if side is None:
            continue
        side = {
            **side,
            "entities": [_strip_kind_prefix(n, kinds) for n in side.get("entities") or []],
        }
        if side.get("claim") is not None:
            claim = side["claim"]
            side["claim"] = {**claim, "entity": _strip_kind_prefix(claim.get("entity"), kinds)}
        out[key] = resolve_fact_entities(side, index, entities)
    return out


def _side_matches(
    side: dict[str, Any],
    truth_fact: TruthFact,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
    opposing: TruthFact | None = None,
) -> bool:
    """A contradiction side states `truth_fact` when `facts_match` holds on
    its whole statement or on one of its clauses split at ";": a side's
    longer wording ("GRACE_DAYS is 7; a lapsed-payment membership stays in
    grace for 7 days after a failed renewal.") often carries the fact in
    one clause. Each clause goes through the same rules unchanged; nothing
    is loosened for contradictions (konyklabs/asbuilt#35). A clause credits
    the side only when neither the whole statement nor any clause also
    states `opposing`, the pair's other fact: a winner saying "up to 3
    bikes; the code's limit of 2 is a regression" states both sides and
    picks neither (lens round). That guard credits on a NON-match, so it
    uses the loosest matcher, `direction_vetoes=False` (konyklabs/asbuilt#66):
    a check whose negative result credits must never gain a refusal, or the
    bound direction veto, refusing the opposing clause, would turn "states
    both, picks neither" into a credit (X-020's hedge, "times out after 5
    seconds; ... waits up to 10 seconds before it times out", found by
    #66's lens round). It still runs the strict reading, `facts_match`'s
    default, as it has since #35."""
    if facts_match(side, truth_fact, mention_index):
        return True
    clauses = [c.strip() for c in str(side.get("statement", "")).split(";")]
    clauses = [c for c in clauses if c]
    if len(clauses) < 2:
        return False
    if not any(facts_match({**side, "statement": c}, truth_fact, mention_index) for c in clauses):
        return False
    if opposing is None:
        return True
    return not any(
        facts_match({**side, "statement": text}, opposing, mention_index, direction_vetoes=False)
        for text in [side.get("statement", ""), *clauses]
    )


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
_OTHER_TIERS = ("code", "documented")


def _has_run_citation(rf: dict[str, Any]) -> bool:
    return any(str(c.get("document", "")).startswith("run/") for c in (rf.get("citations") or []))


# Backend fidelity (konyklabs/asbuilt#38, D-014): the vocabulary, its order
# and the real backend are `truth/fidelities.yaml`'s (`Truth.fidelities`); a
# truth directory without one (the mini fixture) gets no fidelity lines.
_UNQUALIFIED = "unqualified"
_FIDELITY_COUNTS = ("returned", "tp", "expected", "hard_errors")
_NOT_EXECUTED = "none"
_FAKE_VS_REAL = "fake-vs-real"


def _fidelity_row() -> dict[str, Any]:
    return dict.fromkeys(_FIDELITY_COUNTS, 0)


def _claimed_fidelity(rf: dict[str, Any]) -> str | None:
    """A returned fact's own `fidelity`; a value that is not a string (a
    list, a number) is treated as absent, never a crash."""
    claimed = rf.get("fidelity")
    return claimed if isinstance(claimed, str) else None


# (run document, project) -> the test locations that passed in that run.
TruthRuns = dict[tuple[str, str | None], set[str | None]]


def truth_runs(
    truth_facts: dict[str, TruthFact], order: dict[str, int] | None, rank: int | None
) -> TruthRuns:
    """Every run the truth has at or before the step of `rank`, from its
    run carriers, with the tests that passed there: a truth run carrier is
    a passing run by construction (truth/SCHEMA.md). Reruns are never
    cited, so they are not here."""
    runs: TruthRuns = {}
    for tf in truth_facts.values():
        for c in tf.carriers:
            m = _RUN_CARRIER_RE.fullmatch(c.document)
            if m and _at_or_before(m.group(1), order or {}, rank):
                runs.setdefault((c.document, c.project), set()).add(c.location)
    return runs


def _citation_fidelities(rf: dict[str, Any], fidelities: Fidelities, runs: TruthRuns) -> set[str]:
    """The fidelities of the runs a returned fact cites, by the truth's
    mapping (`Fidelities.of_carrier`: the runner, and for Playwright the
    citation's `project`); the fact's own `fidelity` never decides it. A
    citation counts only when it names a run the truth has (`truth_runs`:
    at or before the run's step), and, when it names a test (`location`),
    one that passed there: a failed run, a run that does not exist and a
    run after the step count at no fidelity. A `project` or `location` that
    is not a string is treated as absent."""
    out: set[str] = set()
    for c in rf.get("citations") or []:
        project = c.get("project") if isinstance(c.get("project"), str) else None
        location = c.get("location") if isinstance(c.get("location"), str) else None
        document = str(c.get("document", ""))
        passed = runs.get((document, project))
        if passed is None or (location is not None and location not in passed):
            continue
        fidelity = fidelities.of_carrier(Carrier(document=document, project=project))
        if fidelity is not None:
            out.add(fidelity)
    return out


def _demoted_by_step(tf: TruthFact, order: dict[str, int] | None, rank: int | None) -> bool:
    """`tf` has a `demoted_by` run at or before the step of `rank`
    (`_at_or_before`: with no rank, a demotion always applies)."""
    if tf.demoted_by is None:
        return False
    m = _RUN_CARRIER_RE.fullmatch(tf.demoted_by.document)
    return m is not None and _at_or_before(m.group(1), order or {}, rank)


def _run_counts(
    tf: TruthFact,
    carrier: Carrier,
    fidelities: Fidelities | None,
    order: dict[str, int] | None = None,
    rank: int | None = None,
) -> bool:
    """A passing run carrier lifts its fact, unless the fact was demoted by
    a failing run at a higher fidelity (`demoted_by`) at or before the step
    of `rank`: F-123's mocked and fake passes never make it executed once
    the real run failed, and before that failure exists the lower pass did
    lift. A demotion at the same fidelity (F-011's, a later pytest run)
    leaves the earlier passes standing."""
    if fidelities is None or not _demoted_by_step(tf, order, rank):
        return True
    return fidelities.rank(fidelities.of_carrier(carrier)) >= fidelities.rank(
        fidelities.of_carrier(tf.demoted_by)
    )


def _fidelity_counts(
    resolved: list[dict[str, Any]],
    matches: list[tuple[dict[str, Any], str]],
    truth_fidelity: dict[str, str | None],
    fidelities: Fidelities,
    runs: TruthRuns,
) -> dict[str, Any]:
    """Executed-tier counts per backend fidelity (konyklabs/asbuilt#38).
    `truth_fidelity` maps every expected fact id to its fidelity when it is
    an executed target, else None. A returned fact claiming `executed`
    claims its own `fidelity`; with none it is `unqualified`, its own
    bucket (tp: matched to an executed target of any fidelity). Per claimed
    fidelity F: `returned`, `tp` (matched to an executed target of fidelity
    F), `expected` (targets of fidelity F) and `hard_errors` (claims F with
    no citation of a passing truth run at F, `_citation_fidelities`). The
    confusion matrix is over matched facts claiming `executed`: rows the
    truth fidelity (`none` for a fact that is not an executed target),
    columns the claimed one."""
    by_fidelity: dict[str, dict[str, int]] = {f: _fidelity_row() for f in fidelities.ranked}
    unqualified = {"returned": 0, "tp": 0}
    for rf in resolved:
        if rf.get("tier") != _EXECUTED:
            continue
        claimed = _claimed_fidelity(rf)
        if claimed is None:
            unqualified["returned"] += 1
            continue
        bucket = by_fidelity.setdefault(claimed, _fidelity_row())
        bucket["returned"] += 1
        if claimed not in _citation_fidelities(rf, fidelities, runs):
            bucket["hard_errors"] += 1
    for fidelity in truth_fidelity.values():
        if fidelity is not None:
            by_fidelity.setdefault(fidelity, _fidelity_row())["expected"] += 1
    confusion: dict[str, dict[str, int]] = {}
    for rf, fid in matches:
        if rf.get("tier") != _EXECUTED:
            continue
        claimed = _claimed_fidelity(rf)
        truth = truth_fidelity.get(fid)
        if claimed is None:
            unqualified["tp"] += truth is not None
        elif truth == claimed:
            by_fidelity[claimed]["tp"] += 1
        row = confusion.setdefault(truth or _NOT_EXECUTED, {})
        col = _UNQUALIFIED if claimed is None else claimed
        row[col] = row.get(col, 0) + 1
    return {"by_fidelity": by_fidelity, _UNQUALIFIED: unqualified, "confusion": confusion}


def _fidelity_bands(fidelities: Fidelities) -> list[tuple[str, list[str]]]:
    """D-014's two bands, in `fidelities.yaml`'s order: at or above the
    real backend (these outrank code) and below it (code outranks these)."""
    above = [f for f in fidelities.ranked if fidelities.at_or_above_real_backend(f)]
    return [("at_or_above", above), ("below", [f for f in fidelities.ranked if f not in above])]


def _merge_fidelity_counts(counts: list[dict[str, Any]], fidelities: Fidelities) -> dict[str, Any]:
    """Sums `_fidelity_counts` across queries (micro-averaged, as every
    other line), adds precision and recall, and groups the per-fidelity
    lines into D-014's two bands: at or above the real backend (these
    outrank code) and below it (code outranks these)."""
    by_fidelity: dict[str, dict[str, Any]] = {f: _fidelity_row() for f in fidelities.ranked}
    unqualified = {"returned": 0, "tp": 0}
    confusion: dict[str, dict[str, int]] = {}
    for c in counts:
        for f, row in c.get("by_fidelity", {}).items():
            dest = by_fidelity.setdefault(f, _fidelity_row())
            for key in dest:
                dest[key] += row.get(key, 0)
        for key in unqualified:
            unqualified[key] += c.get(_UNQUALIFIED, {}).get(key, 0)
        for truth, row in c.get("confusion", {}).items():
            dest_row = confusion.setdefault(truth, {})
            for claimed, n in row.items():
                dest_row[claimed] = dest_row.get(claimed, 0) + n
    for row in by_fidelity.values():
        row["precision"] = _ratio(row["tp"], row["returned"])
        row["recall"] = _ratio(row["tp"], row["expected"])
    unqualified_out: dict[str, Any] = {
        **unqualified,
        "precision": _ratio(unqualified["tp"], unqualified["returned"]),
    }
    bands: dict[str, dict[str, Any]] = {}
    for band, members in _fidelity_bands(fidelities):
        totals = {key: sum(by_fidelity[f][key] for f in members) for key in _FIDELITY_COUNTS}
        bands[band] = {
            "fidelities": members,
            **totals,
            "precision": _ratio(totals["tp"], totals["returned"]),
            "recall": _ratio(totals["tp"], totals["expected"]),
        }
    return {
        "ranked": list(fidelities.ranked),
        "real_backend": fidelities.real_backend,
        "by_fidelity": by_fidelity,
        "bands": bands,
        _UNQUALIFIED: unqualified_out,
        "confusion": confusion,
    }


def _tier_stats(
    resolved: list[dict[str, Any]],
    matches: list[tuple[dict[str, Any], str]],
    expected: dict[str, TruthFact],
    fidelities: Fidelities | None = None,
    runs: TruthRuns | None = None,
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

    stats: dict[str, Any] = {
        "confusion": confusion,
        "hard_errors": hard_errors,
        "returned_executed": returned_executed,
        "tp_executed": tp_executed,
        "expected_executed": expected_executed,
    }
    # The other tiers' lines (konyklabs/asbuilt#34), counted exactly as the
    # executed line is: every returned fact claiming the tier, matched or
    # not, over the static truth tier of what it matched.
    for tier in _OTHER_TIERS:
        stats[f"returned_{tier}"] = sum(1 for rf in resolved if rf.get("tier") == tier)
        stats[f"tp_{tier}"] = sum(
            1 for rf, fid in matches if rf.get("tier") == tier and expected[fid].tier == tier
        )
        stats[f"expected_{tier}"] = sum(1 for f in expected.values() if f.tier == tier)
    # Per backend fidelity (konyklabs/asbuilt#38), over the static truth tier
    # and fidelity, as the executed line above.
    if fidelities is not None:
        stats["fidelity"] = _fidelity_counts(
            resolved,
            matches,
            {fid: f.fidelity if f.tier == _EXECUTED else None for fid, f in expected.items()},
            fidelities,
            runs or {},
        )
    return stats


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
    fidelities: Fidelities | None = None,
    runs: TruthRuns | None = None,
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
    restated, unmatched = _split_restated(unmatched, matched_ids, expected, mention_index)
    hard_fp, unplanted = classify_unmatched(unmatched, all_facts)

    return {
        "tp": len(matches),
        "returned": len(returned),
        "expected": len(expected),
        "uncited": uncited,
        "by_category": _by_category_counts(matched_ids, expected),
        "tier": _tier_stats(resolved, matches, expected, fidelities, runs),
        "category_accuracy": _category_accuracy(matches, expected),
        "validity": _validity_stats(matches, expected, commits or {}),
        "entity_resolution": _entity_resolution_stats(matches, expected),
        "hard_false_positives": len(hard_fp),
        "restated": len(restated),
        "unplanted_facts": unplanted,
        "rank": _rank_metrics(resolved, matches),
    }


def _split_restated(
    unmatched: list[dict[str, Any]],
    matched_ids: set[str],
    expected: dict[str, TruthFact],
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """konyklabs/asbuilt#35: (restated, the rest) of the facts `match_facts`
    left unmatched. A restated fact would match a truth fact this query
    already credited (`facts_match`): a page's sentence and a test's
    sentence for one rule, both returned, where one-to-one matching can
    credit only one. It is neither a hard false positive nor unplanted, so
    it is counted apart from both; it is the measure a near-duplicate merge
    in the store is held to."""
    credited = [expected[fid] for fid in matched_ids]
    restated: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for rf in unmatched:
        if any(facts_match(rf, tf, mention_index) for tf in credited):
            restated.append(rf)
        else:
            rest.append(rf)
    return restated, rest


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


_KIND_COUNTS = ("matched", "expected", "winner_checked", "winner_correct")


def score_contradictions(
    returned: list[dict[str, Any]],
    expected: dict[str, Any],
    truth_facts: dict[str, TruthFact],
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
) -> dict[str, Any]:
    matched_ids: set[str] = set()
    winner_checked = 0
    winner_correct = 0
    # Per truth kind (konyklabs/asbuilt#38: `fake-vs-real` found, and its
    # winner, the higher-fidelity run's fact, checked).
    by_kind: dict[str, dict[str, int]] = {}
    for xc in expected.values():
        by_kind.setdefault(xc.kind, dict.fromkeys(_KIND_COUNTS, 0))["expected"] += 1
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
            order1 = _side_matches(rc_a, truth_a, mention_index, truth_b) and _side_matches(
                rc_b, truth_b, mention_index, truth_a
            )
            order2 = _side_matches(rc_a, truth_b, mention_index, truth_a) and _side_matches(
                rc_b, truth_a, mention_index, truth_b
            )
            if not (order1 or order2):
                continue
            matched_ids.add(xid)
            kind = by_kind[xc.kind]
            kind["matched"] += 1
            if xc.winner is not None:
                winner_checked += 1
                kind["winner_checked"] += 1
                expected_winner = truth_facts.get(xc.winner)
                returned_winner = rc.get("winner")
                if (
                    expected_winner is not None
                    and returned_winner is not None
                    and _side_matches(
                        returned_winner,
                        expected_winner,
                        mention_index,
                        truth_b if expected_winner is truth_a else truth_a,
                    )
                ):
                    winner_correct += 1
                    kind["winner_correct"] += 1
            break
    return {
        "matched": len(matched_ids),
        "returned": len(returned),
        "expected": len(expected),
        "winner_checked": winner_checked,
        "winner_correct": winner_correct,
        "by_kind": by_kind,
    }


def _merge_by_kind(outcomes: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_kind: dict[str, dict[str, int]] = {}
    for outcome in outcomes:
        for kind, counts in outcome.get("by_kind", {}).items():
            dest = by_kind.setdefault(kind, dict.fromkeys(_KIND_COUNTS, 0))
            for key in _KIND_COUNTS:
                dest[key] += counts.get(key, 0)
    return by_kind


def _step_dates(fixture_root: Path) -> dict[str, datetime]:
    steps_path = fixture_root / "system" / "history" / "steps.yaml"
    if not steps_path.is_file():
        return {}
    raw = yaml.safe_load(steps_path.read_text()) or []
    return {r["id"]: datetime.fromisoformat(r["date"]) for r in raw}


def _run_step_rank(
    through_step: str | None, step_dates: dict[str, datetime], commits: dict[str, Any]
) -> tuple[dict[str, int], int | None]:
    """The step order and the rank of the step a run was ingested through
    (konyklabs/asbuilt#34). Order comes from the fixture's own steps.yaml
    dates, which is what `bench/run.py` took `through_step` from, and from
    commits.json only when the fixture has no steps.yaml. A results file
    with no `through_step`, or one naming a step neither knows, gets rank
    None: nothing is held back, which is how every results file was scored
    before the rule existed."""
    if step_dates:
        ordered = sorted(step_dates, key=step_dates.__getitem__)
        order = {step: i for i, step in enumerate(ordered)}
    else:
        order = _step_order(commits)
    return order, order.get(through_step) if through_step else None


def _at_or_before(step: str | None, order: dict[str, int], rank: int | None) -> bool:
    """`step` is at or before `rank`. No rank or no step never holds a truth
    entry back. A step the run's fixture doesn't list does, once the rank
    is known: a truth checkout ahead of the run's fixture (a seventh step
    the run never saw) must not be expected of it. `_warn_unknown_steps`
    says so on stderr."""
    if rank is None or step is None:
        return True
    return step in order and order[step] <= rank


def _unknown_step(step: str | None, order: dict[str, int], rank: int | None) -> bool:
    return rank is not None and step is not None and step not in order


def _warn_unknown_steps(
    truth: Truth, order: dict[str, int], rank: int | None, through_step: str | None
) -> None:
    """One stderr line naming the truth steps the run's fixture doesn't list
    and what `_at_or_before` held back for that reason; stdout, and so the
    report, is unchanged."""
    fact_steps = {
        fid: f.valid_from
        for fid, f in truth.facts.items()
        if _unknown_step(f.valid_from, order, rank)
    }
    contradictions = [
        xid
        for xid, xc in truth.contradictions.items()
        if any(fid in fact_steps for fid in xc.facts)
    ]
    stale_steps = [
        e.changed_by for e in truth.stale.values() if _unknown_step(e.changed_by, order, rank)
    ]
    steps = sorted({*fact_steps.values(), *stale_steps})
    if not steps:
        return
    print(
        f"warning: truth names step(s) {', '.join(steps)} that the run's fixture does not "
        f"list; held back as later than through_step {through_step}: {len(fact_steps)} "
        f"facts, {len(contradictions)} contradictions, {len(stale_steps)} stale pages",
        file=sys.stderr,
    )


def _fact_by_step(tf: TruthFact | None, order: dict[str, int], rank: int | None) -> bool:
    """A truth fact is expected of a run only once it is valid: `valid_from`
    at or before the run's step. `valid_to` is deliberately not checked —
    explain expects a fact's whole history, retired values included. A
    missing fact (a contradiction naming an unknown id) is not held back."""
    return tf is None or _at_or_before(tf.valid_from, order, rank)


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


def _merge_fact_surface(
    outcomes: list[dict[str, Any]], fidelities: Fidelities | None = None
) -> dict[str, Any]:
    """Extends `_merge` with the tier/category/validity/entity-resolution/
    rank detail `score_fact_query` produces, all summed the same
    micro-averaged way, plus a concatenated `unplanted` audit list."""
    merged = _merge(
        outcomes, ("tp", "returned", "expected", "uncited", "hard_false_positives", "restated")
    )

    confusion: dict[str, dict[str, int]] = {}
    hard_errors = returned_executed = tp_executed = expected_executed = 0
    cat_correct = cat_total = 0
    val_correct = val_total = 0
    er_tp = er_returned = er_expected = 0
    unresolved: list[str] = []
    unplanted: list[dict[str, Any]] = []
    p5_hits = p5_n = r10_hits = 0
    other_tiers = {
        f"{count}_{t}": 0 for t in _OTHER_TIERS for count in ("returned", "tp", "expected")
    }

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
        for key in other_tiers:
            other_tiers[key] += tier.get(key, 0)

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
        **other_tiers,
    }
    for t in _OTHER_TIERS:
        tp = other_tiers[f"tp_{t}"]
        merged["tier"][f"precision_{t}"] = _ratio(tp, other_tiers[f"returned_{t}"])
        merged["tier"][f"recall_{t}"] = _ratio(tp, other_tiers[f"expected_{t}"])
    if fidelities is not None:
        merged["tier"]["fidelity"] = _merge_fidelity_counts(
            [o.get("tier", {}).get("fidelity", {}) for o in outcomes], fidelities
        )
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


def _distinct_key(rf: dict[str, Any]) -> tuple[Any, ...]:
    """A returned fact's identity across queries: its id, or else its
    normalised statement with the documents and versions it cites."""
    if rf.get("id"):
        return ("id", rf["id"])
    citations = sorted(
        (str(c.get("document")), str(c.get("version"))) for c in rf.get("citations") or []
    )
    return ("statement", norm(rf.get("statement", "")), tuple(citations))


def wilson_lower_bound(successes: int, n: int, z: float = 1.96) -> float | None:
    """The lower bound of the Wilson score interval (95% at the default z)
    for `successes` of `n`: 26 of 27 gives 0.817."""
    if not n:
        return None
    p = successes / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


_RUN_CARRIER_RE = re.compile(r"run/(?:pytest|vitest|playwright)-(.+?)(?:-rerun)?")


def _runs_by_step(
    tf: TruthFact,
    order: dict[str, int],
    rank: int,
    fidelities: Fidelities | None = None,
) -> list[Carrier]:
    """`tf`'s run carriers at the step of `rank` or an earlier one that lift
    it (`_run_counts`): a Playwright run counts at its project's fidelity
    (konyklabs/asbuilt#38)."""
    runs = []
    for carrier in tf.carriers:
        m = _RUN_CARRIER_RE.fullmatch(carrier.document)
        if (
            m
            and m.group(1) in order
            and order[m.group(1)] <= rank
            and _run_counts(tf, carrier, fidelities, order, rank)
        ):
            runs.append(carrier)
    return runs


def _executed_by_step(
    tf: TruthFact,
    order: dict[str, int],
    rank: int | None,
    fidelities: Fidelities | None = None,
) -> bool:
    """Whether `tf` is an executed target for a run ingested through the
    step of `rank`: it has a run carrier at that step or an earlier one
    (konyklabs/asbuilt#35, lens round: F-007, proven by its test from c5
    only, is not one for a run through c4). A fact proven at an earlier
    step and retired since (F-002's 45 minutes, c2 to c3) still is: the run
    holds the history. With no rank, the static tier decides, as before.
    Since konyklabs/asbuilt#38 a Playwright run carrier counts, and a
    demoted fact's passes below the demoting fidelity do not (F-123)."""
    if rank is None:
        return tf.tier == _EXECUTED
    return bool(_runs_by_step(tf, order, rank, fidelities))


def _fidelity_by_step(
    tf: TruthFact,
    order: dict[str, int],
    rank: int | None,
    fidelities: Fidelities,
) -> str | None:
    """An executed target's fidelity for a run through the step of `rank`:
    the strongest of the runs that lift it by then (truth/SCHEMA.md); with
    no rank, the fact's own `fidelity`. None when it is not a target."""
    if rank is None:
        return tf.fidelity if tf.tier == _EXECUTED else None
    runs = _runs_by_step(tf, order, rank, fidelities)
    return max((fidelities.of_carrier(c) for c in runs), key=fidelities.rank, default=None)


def distinct_executed(
    returned_facts: list[dict[str, Any]],
    truth_facts: dict[str, TruthFact],
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
    order: dict[str, int] | None = None,
    rank: int | None = None,
    fidelities: Fidelities | None = None,
) -> dict[str, Any]:
    """Executed-tier precision over distinct facts (konyklabs/asbuilt#35,
    D-014): every returned fact claiming `executed`, from any query, counted
    once (`_distinct_key`), and correct when it matches any executed fact
    of `truth_facts` (`facts_match`; `score()` passes the facts valid by
    the run's step) — not only one its query expected,
    so a planted fact surfaced by a query that did not ask for it counts,
    and a fact surfaced by four queries counts once. D-013's measure is tier
    accuracy, which is a property of the facts, not of which query returned
    them. Scored under the strict reading and, for comparison, the lenient
    one (`_statement_matches`); each with its n, its Wilson 95% lower bound
    and the statements judged wrong. `order`/`rank` place the run on the
    history (`_run_step_rank`); the targets are `_executed_by_step`."""
    executed = [
        tf for tf in truth_facts.values() if _executed_by_step(tf, order or {}, rank, fidelities)
    ]
    return _distinct_readings(
        list(_distinct_executed_facts(returned_facts)), executed, mention_index
    )


def _distinct_executed_facts(returned_facts: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    distinct: dict[tuple[Any, ...], dict[str, Any]] = {}
    for rf in returned_facts:
        if rf.get("tier") == _EXECUTED:
            distinct.setdefault(_distinct_key(rf), rf)
    return distinct.values()


def _distinct_readings(
    facts: list[dict[str, Any]],
    targets: list[TruthFact],
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
) -> dict[str, Any]:
    """`facts` judged against `targets` under the strict and the lenient
    reading: tp, n, precision, the Wilson 95% lower bound and the wrong."""
    out: dict[str, Any] = {}
    for reading, strict in (("strict", True), ("lenient", False)):
        wrong = [
            rf.get("statement", "")
            for rf in facts
            if not any(facts_match(rf, tf, mention_index, strict) for tf in targets)
        ]
        n = len(facts)
        tp = n - len(wrong)
        out[reading] = {
            "tp": tp,
            "n": n,
            "precision": _ratio(tp, n),
            "wilson_lower": wilson_lower_bound(tp, n),
            "wrong": wrong,
        }
    return out


def distinct_executed_by_fidelity(
    returned_facts: list[dict[str, Any]],
    truth_facts: dict[str, TruthFact],
    fidelities: Fidelities,
    mention_index: list[tuple[re.Pattern[str], str, str]] | None = None,
    order: dict[str, int] | None = None,
    rank: int | None = None,
) -> dict[str, Any]:
    """`distinct_executed` per claimed fidelity (konyklabs/asbuilt#38): the
    distinct facts claiming fidelity F, correct when they match an executed
    target whose fidelity by the run's step (`_fidelity_by_step`) is F. A
    fact claiming `executed` with no fidelity is `unqualified`, judged
    against every target. Grouped, as the per-surface lines, into the bands
    at or above the real backend and below it."""
    targets = {
        fid: _fidelity_by_step(tf, order or {}, rank, fidelities)
        for fid, tf in truth_facts.items()
        if _executed_by_step(tf, order or {}, rank, fidelities)
    }
    # One judgement per (fact, claimed fidelity): the same fact claimed at
    # two fidelities is two claims, whatever order the queries return them.
    distinct: dict[tuple[Any, ...], dict[str, Any]] = {}
    for rf in returned_facts:
        if rf.get("tier") == _EXECUTED:
            distinct.setdefault((_distinct_key(rf), _claimed_fidelity(rf)), rf)
    claims: dict[str, list[dict[str, Any]]] = {f: [] for f in fidelities.ranked}
    unqualified: list[dict[str, Any]] = []
    for (_, claimed), rf in distinct.items():
        if claimed is None:
            unqualified.append(rf)
        else:
            claims.setdefault(claimed, []).append(rf)

    def judged(facts: list[dict[str, Any]], fidelity: str | None) -> dict[str, Any]:
        kept = [truth_facts[fid] for fid, f in targets.items() if fidelity is None or f == fidelity]
        return _distinct_readings(facts, kept, mention_index)

    by_fidelity = {f: judged(facts, f) for f, facts in claims.items()}
    bands: dict[str, Any] = {}
    for band, members in _fidelity_bands(fidelities):
        totals: dict[str, Any] = {"fidelities": members}
        for reading in ("strict", "lenient"):
            tp = sum(by_fidelity[f][reading]["tp"] for f in members)
            n = sum(by_fidelity[f][reading]["n"] for f in members)
            totals[reading] = {
                "tp": tp,
                "n": n,
                "precision": _ratio(tp, n),
                "wilson_lower": wilson_lower_bound(tp, n),
            }
        bands[band] = totals
    return {
        "by_fidelity": by_fidelity,
        "bands": bands,
        _UNQUALIFIED: judged(unqualified, None),
    }


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
    explain_search_facts: list[dict[str, Any]] = []
    # Expected sets honour the step the run was ingested through
    # (konyklabs/asbuilt#34): see `_run_step_rank` for the default.
    order, run_rank = _run_step_rank(results.get("through_step"), step_dates, commits)
    _warn_unknown_steps(truth, order, run_rank, results.get("through_step"))
    runs_by_step = truth_runs(truth.facts, order, run_rank)
    facts_by_step = {fid: f for fid, f in truth.facts.items() if _fact_by_step(f, order, run_rank)}
    contradictions_by_step = {
        xid: xc
        for xid, xc in truth.contradictions.items()
        if all(_fact_by_step(truth.facts.get(fid), order, run_rank) for fid in xc.facts)
    }
    stale_by_step = {
        sid: entry
        for sid, entry in truth.stale.items()
        if _at_or_before(entry.changed_by, order, run_rank)
    }

    per_query: dict[str, list[dict[str, Any]]] = {s: [] for s in SURFACES}
    for q in results["queries"]:
        surface = q["surface"]
        params = q.get("params", {})
        if surface == "explain":
            raw_entity = params["entity"]
            resolved_ids, _ = align_entities([raw_entity], alias_index, truth.entities)
            entity_id = resolved_ids[0] if resolved_ids else None
            expected = {
                fid: f for fid, f in facts_by_step.items() if entity_id and entity_id in f.entities
            }
            all_returned_facts.extend(q["result"])
            explain_search_facts.extend(q["result"])
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
                        truth.fidelities,
                        runs_by_step,
                    ),
                    "_query_id": q["id"],
                }
            )
        elif surface == "search":
            expects = params.get("expects") or []
            expected = {fid: facts_by_step[fid] for fid in expects if fid in facts_by_step}
            all_returned_facts.extend(q["result"])
            explain_search_facts.extend(q["result"])
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
                        truth.fidelities,
                        runs_by_step,
                    ),
                    "_query_id": q["id"],
                }
            )
        elif surface == "ask":
            expects = params.get("expects") or []
            expected = {fid: facts_by_step[fid] for fid in expects if fid in facts_by_step}
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
                for xid, xc in contradictions_by_step.items():
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
                expected_x = dict(contradictions_by_step)
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
                        stale_by_step,
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
        m = _merge_fact_surface(per_query[name], truth.fidelities)
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
    m["by_kind"] = _merge_by_kind(per_query["contradictions"])
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
    explain_search_resolved = [
        resolve_fact_entities(rf, alias_index, truth.entities) for rf in explain_search_facts
    ]
    distinct = distinct_executed(
        explain_search_resolved,
        facts_by_step,
        mention_index,
        order,
        run_rank,
        truth.fidelities,
    )
    distinct_by_fidelity = (
        distinct_executed_by_fidelity(
            explain_search_resolved,
            facts_by_step,
            truth.fidelities,
            mention_index,
            order,
            run_rank,
        )
        if truth.fidelities is not None
        else None
    )

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
        "distinct_executed": distinct,
        **({"distinct_executed_by_fidelity": distinct_by_fidelity} if distinct_by_fidelity else {}),
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

# `code/web/tests/` holds the rider portal's Playwright specs (c7,
# konyklabs/asbuilt#38): test carriers, so out of `code` through the exclude.
_TRUTH_FILTER_PREFIXES: dict[str, tuple[str, ...]] = {
    "tests": ("code/tests/", "code/dispatch/test/", "code/web/tests/"),
    "code": ("code/",),
    "documents": ("wiki/", "doc/", "ticket/", "pull/"),
}
# `code` is the code outside the test directories (konyklabs/asbuilt#34).
_TRUTH_FILTER_EXCLUDES: dict[str, tuple[str, ...]] = {
    "code": _TRUTH_FILTER_PREFIXES["tests"],
}
# Filters whose carriers' `version` is a history step. A `documents`
# carrier's is not: a wiki or doc `version` is the page's own revision, and
# ticket and pull carriers have none.
_STEP_VERSIONED_FILTERS = frozenset({"tests", "code"})
# The tier lines `--facts` prints: a `documented` line only where a
# documented fact can be expected at all.
_FILTER_TIERS: dict[str, tuple[str, ...]] = {
    "tests": ("executed", "code"),
    "code": ("executed", "code"),
    "documents": ("executed", "code", "documented"),
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
    """Half-open validity window [valid_from, valid_to) at `step_rank`
    (konyklabs/asbuilt#66): `valid_to` is the step that superseded the
    fact, so the fact is not current there. F-001 (`valid_to: c2`) and
    F-002 (`valid_from: c2`) are not both expected at c2. It is the
    fixture's own definition: `truth/validate.py`'s `steps_between` is
    half-open (`STEPS[i:j]`), and it requires a code carrier's PLAN `steps`
    to equal `steps_between(version, valid_to)`; `truth/PLAN.yaml` lists
    F-011 on `LOST_BIKE_FEE` at `[c1, c2, c3, c4]`, and
    `test_lost_bike_fee_100` asserting it at `[c1, c2, c3, c4]` with
    `fails_in: [c5]`. The truth never carries a fact at its own `valid_to`.
    The window was closed from the konyklabs/asbuilt#8 review, whose
    reproduction read "F-011 must be expected... at c5", exactly its own
    `valid_to`, holding the failing old test and the new code to be both
    legitimate connector targets there; that reading is superseded by the
    definition above, because the failing test's value is a contradiction
    candidate, not a current fact: the truth records it as X-021
    (run-vs-code, F-011 against F-012, winner F-012, opened at c5). So a
    statement of a failing test's superseded value at the fact's
    `valid_to` step ("Lost bike fee $100.00." at c5) is now unmatched, a
    hard false positive, and counts against `--facts` precision there; it
    is `code` tier, so executed-tier precision does not move. Used only by
    `score_test_connector`; explain's whole-history expectation is
    `_fact_by_step`. `step_rank=None` (the step didn't resolve) skips the
    validity filter rather than excluding everything, and a `valid_from`
    or `valid_to` the order doesn't know holds nothing back."""
    if step_rank is None:
        return True
    if tf.valid_from is not None and order.get(tf.valid_from, step_rank) > step_rank:
        return False
    if tf.valid_to is not None and order.get(tf.valid_to, step_rank + 1) <= step_rank:
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


def _in_truth_filter(document: str, truth_filter: str) -> bool:
    return document.startswith(_TRUTH_FILTER_PREFIXES[truth_filter]) and not document.startswith(
        _TRUTH_FILTER_EXCLUDES.get(truth_filter, ())
    )


def _has_filter_carrier_by_step(
    tf: TruthFact,
    truth_filter: str,
    order: dict[str, int],
    step_rank: int | None,
) -> bool:
    """A carrier of the kind `truth_filter` names (`_in_truth_filter`),
    held to `_has_test_carrier_by_step`'s rule where the filter's carrier
    versions are history steps (`tests`, `code`). A `documents` carrier
    can't be placed on the history that way, so any one counts and only
    the fact's own validity window (`_current_at_step`) places it at a
    step (konyklabs/asbuilt#34)."""
    kept = [c for c in tf.carriers if _in_truth_filter(c.document, truth_filter)]
    if step_rank is None or truth_filter not in _STEP_VERSIONED_FILTERS:
        return bool(kept)
    return any(
        c.version is not None and order.get(c.version, step_rank + 1) <= step_rank for c in kept
    )


def _expected_tier_at_step(
    tf: TruthFact,
    step_id: str,
    fidelities: Fidelities | None = None,
    order: dict[str, int] | None = None,
) -> str:
    """`executed` when a run lifts the fact at the step (`_runs_at_step`);
    otherwise `code`, when the fact has a `code/` carrier. Under the `tests`
    and `code` filters every expected fact has one (that is what put it in
    scope); under `documents` a fact with none keeps its own static tier,
    `documented` in the fixture, rather than being labelled `code`
    (konyklabs/asbuilt#34). A fact demoted at or before the step (its
    `demoted_by` run's step) keeps its static tier, which is where the
    demotion landed it: F-123 is `documented` at c7, not `code` through its
    test file (konyklabs/asbuilt#37)."""
    if _runs_at_step(tf, step_id, fidelities, order):
        return _EXECUTED
    if _demoted_by_step(tf, order, (order or {}).get(step_id)):
        return tf.tier
    if not any(c.document.startswith("code/") for c in tf.carriers):
        return tf.tier
    return "code"


def _runs_at_step(
    tf: TruthFact,
    step_id: str,
    fidelities: Fidelities | None = None,
    order: dict[str, int] | None = None,
) -> list[Carrier]:
    """The runs that lift `tf` at `step_id`. With the step on the history
    (konyklabs/asbuilt#63), the distinct measure's rule: a run carrier at or
    before the step that lifts it (`_runs_by_step`), and none once a
    demotion applies at or before it, or once the step reaches the fact's
    `valid_to` (`_retired_by_step`: its runs no longer prove it there;
    F-001 is `code` at c2, as before, though since konyklabs/asbuilt#66
    `--facts` no longer has it in scope at its `valid_to`, see
    `_current_at_step`). F-050's flaky c6 is
    inconclusive and cites no run, so its c1 to c5 runs keep it executed
    at c6; F-007, proven from c5, is `code` at c1 to c4; F-011, demoted at
    c5, is `code` from c5. With no step order, a run carrier at exactly
    the step, or a "-rerun" of it ("a rerun carrier counts",
    konyklabs/asbuilt#8 review), as before."""
    rank = (order or {}).get(step_id)
    if rank is not None:
        if _demoted_by_step(tf, order, rank) or _retired_by_step(tf, order or {}, rank):
            return []
        return _runs_by_step(tf, order or {}, rank, fidelities)
    runs = []
    for c in tf.carriers:
        for framework in ("pytest", "vitest", "playwright"):
            prefix = f"run/{framework}-{step_id}"
            if (c.document == prefix or c.document.startswith(prefix + "-")) and _run_counts(
                tf, c, fidelities, order, rank
            ):
                runs.append(c)
    return runs


def _retired_by_step(tf: TruthFact, order: dict[str, int], rank: int) -> bool:
    """The step of `rank` is at or after `tf`'s `valid_to`."""
    return tf.valid_to is not None and tf.valid_to in order and order[tf.valid_to] <= rank


def _expected_fidelity_at_step(
    tf: TruthFact,
    step_id: str,
    fidelities: Fidelities,
    order: dict[str, int] | None = None,
) -> str | None:
    """The strongest fidelity of the runs that lift `tf` at `step_id`
    (konyklabs/asbuilt#38, `_runs_at_step`); None when none does."""
    return max(
        (fidelities.of_carrier(c) for c in _runs_at_step(tf, step_id, fidelities, order)),
        key=fidelities.rank,
        default=None,
    )


def _tier_precision_recall(
    resolved: list[dict[str, Any]],
    matches: list[tuple[dict[str, Any], str]],
    expected: dict[str, TruthFact],
    tier: str,
    step_id: str,
    fidelities: Fidelities | None = None,
    order: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Precision/recall for one tier in isolation: among ALL returned facts
    claiming `tier` (matched or not — an unmatched claim is still a wrong
    one), what fraction correctly matched a truth fact whose tier AT
    `step_id` (`_expected_tier_at_step`, not the static, eventual
    `TruthFact.tier` — konyklabs/asbuilt#8 review) is also `tier`; among
    truth facts at that per-step `tier` within `expected`, what fraction
    got matched with that same tier claimed."""

    def tier_at(tf: TruthFact) -> str:
        return _expected_tier_at_step(tf, step_id, fidelities, order)

    returned_n = sum(1 for rf in resolved if rf.get("tier") == tier)
    expected_n = sum(1 for tf in expected.values() if tier_at(tf) == tier)
    tp = sum(1 for rf, fid in matches if rf.get("tier") == tier and tier_at(expected[fid]) == tier)
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
    fidelities: Fidelities | None = None,
    order: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Like `_tier_stats` (shared by `score_fact_query`'s explain/search
    path, which has no step concept), but compares the returned tier
    against the fact's tier AT THIS STEP (`_expected_tier_at_step`), not
    its static, eventual `TruthFact.tier` — a fact's provenance strength
    changes across the history a connector ingests incrementally
    (konyklabs/asbuilt#8 review): F-011 is `code` at c5 (demoted) but was
    `executed` at c1..c4."""

    def tier_at(tf: TruthFact) -> str:
        return _expected_tier_at_step(tf, step_id, fidelities, order)

    confusion: dict[str, dict[str, int]] = {}
    for rf, fid in matches:
        truth_tier = tier_at(expected[fid])
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
        if rf.get("tier") == _EXECUTED and tier_at(expected[fid]) == _EXECUTED
    )
    expected_executed = sum(1 for tf in expected.values() if tier_at(tf) == _EXECUTED)
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
    `code/dispatch/test/...` by default — see `_TRUTH_FILTER_PREFIXES`;
    `code` is a `code/` carrier outside those and `documents` a wiki, doc,
    ticket or pull carrier, konyklabs/asbuilt#34) and are current
    (`_current_at_step`) at `step` (a step id or a commit SHA — resolved
    via `commits`).
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
    fidelities = truth.fidelities
    alias_index = build_alias_index(truth)
    mention_index = build_mention_index(truth)
    entities = truth.entities

    if truth_filter not in _TRUTH_FILTER_PREFIXES:
        raise ValueError(
            f"unknown --truth-filter {truth_filter!r}; known: {sorted(_TRUTH_FILTER_PREFIXES)}"
        )
    order = _step_order(commits)
    step_id = _resolve_step_or_sha(step, commits)
    step_rank = order.get(step_id)

    expected = {
        fid: tf
        for fid, tf in truth.facts.items()
        if _has_filter_carrier_by_step(tf, truth_filter, order, step_rank)
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
                (c.location for c in tf.carriers if _in_truth_filter(c.document, truth_filter)),
                None,
            ),
        }
        for fid, tf in expected.items()
        if fid not in matched_ids
    ]

    def _contradiction_in_scope(xc: TruthContradiction, kind: str = "run-vs-code") -> bool:
        if xc.kind != kind:
            return False
        if step_rank is None:
            return True
        if xc.opened_by is not None and order.get(xc.opened_by, step_rank + 1) > step_rank:
            return False
        if xc.resolved_by is not None and step_rank >= order.get(xc.resolved_by, step_rank):
            return False
        return True

    run_vs_code = {
        xid: xc for xid, xc in truth.contradictions.items() if _contradiction_in_scope(xc)
    }
    fake_vs_real = {
        xid: xc
        for xid, xc in truth.contradictions.items()
        if _contradiction_in_scope(xc, _FAKE_VS_REAL)
    }
    resolved_candidates = [
        _resolve_contradiction_entities(rc, alias_index, entities) for rc in candidates
    ]
    tier_args = (fidelities, order)
    fidelity_report: dict[str, Any] = {}
    if fidelities is not None:
        fidelity_report["fidelity"] = _merge_fidelity_counts(
            [
                _fidelity_counts(
                    resolved,
                    matches,
                    {
                        fid: _expected_fidelity_at_step(tf, step_id, fidelities, order)
                        for fid, tf in expected.items()
                    },
                    fidelities,
                    truth_runs(truth.facts, order, step_rank),
                )
            ],
            fidelities,
        )

    cat_stats = _category_accuracy(matches, expected)
    cat_stats["accuracy"] = _ratio(cat_stats["correct"], cat_stats["total"])
    er_stats = _entity_resolution_stats(matches, expected)
    er_stats["precision"] = _ratio(er_stats["tp"], er_stats["returned"])
    er_stats["recall"] = _ratio(er_stats["tp"], er_stats["expected"])
    # Claim-first matching (konyklabs/asbuilt#8, narrowed by #17): a match
    # the claim decided on its own (both sides carry one, comparable, and
    # `_claims_match` agrees in full) vs. one the statement rule decided —
    # since #17 a both-claims pair can fall through to the statement, so
    # "both have a claim" no longer means "decided by the claim".
    matched_by_claim = sum(
        1
        for rf, fid in matches
        if rf.get("claim") is not None
        and expected[fid].claim is not None
        and _claim_is_comparable(rf["claim"], expected[fid].claim)
        and _claims_match(rf["claim"], expected[fid].claim)
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
            tier: _tier_precision_recall(resolved, matches, expected, tier, step_id, *tier_args)
            for tier in _FILTER_TIERS[truth_filter]
        },
        "tier_confusion": _step_tier_confusion(resolved, matches, expected, step_id, *tier_args),
        **fidelity_report,
        "category_accuracy": cat_stats,
        "entity_resolution": er_stats,
        "claim": _claim_metrics(resolved, matches, expected),
        "hard_false_positives": len(hard_fp),
        "unplanted_facts": unplanted,
        "missed": missed,
        "contradiction_candidates": score_contradictions(
            resolved_candidates, run_vs_code, truth.facts, mention_index
        ),
        "fake_vs_real_candidates": score_contradictions(
            resolved_candidates, fake_vs_real, truth.facts, mention_index
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
    if "fidelity" in report:
        _print_fidelity_block(report["fidelity"], "")
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
    fr = report["fake_vs_real_candidates"]
    print(
        f"fake-vs-real contradiction candidates: matched={fr['matched']}/{fr['returned']} "
        f"vs expected={fr['expected']} winner={fr['winner_correct']}/{fr['winner_checked']}"
    )


# --------------------------------------------------------------------------
# Multiple runs and the paired-bootstrap comparison
# --------------------------------------------------------------------------

_MULTI_RUN_METRICS = ("precision", "recall", "f1")


def aggregate_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Median/min/max, across several independently-scored runs of the same
    arm, for each surface's precision/recall/f1 and (explain/search only)
    executed-tier precision and the code and documented tiers' precision
    and recall (konyklabs/asbuilt#34), plus the distinct executed-tier
    precision under both readings (#35). Per-run diagnostics (by-category,
    unplanted audit, entity resolution) are not re-aggregated here — see
    module docstring."""
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
        for t in _OTHER_TIERS:
            for ratio in ("precision", "recall"):
                values = [
                    r["surfaces"][name]["tier"][f"{ratio}_{t}"]
                    for r in reports
                    if r["surfaces"][name].get("tier", {}).get(f"{ratio}_{t}") is not None
                ]
                if values:
                    metrics[f"{t}_tier_{ratio}"] = {
                        "median": statistics.median(values),
                        "min": min(values),
                        "max": max(values),
                    }
        surfaces[name] = metrics
    distinct: dict[str, dict[str, float]] = {}
    for reading in ("strict", "lenient"):
        values = [
            r["distinct_executed"][reading]["precision"]
            for r in reports
            if r.get("distinct_executed", {}).get(reading, {}).get("precision") is not None
        ]
        if values:
            distinct[reading] = {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
    return {"surfaces": surfaces, "distinct_executed": distinct}


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
    strict: bool = True,
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
    an id directly, matching how real truth facts store it. `strict=False`
    calibrates the lenient reading (konyklabs/asbuilt#35): a pair's
    `lenient_expect`, where it has one, is its label there."""
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
            strict,
        )
        expected = bool(pair["expect"] if strict else pair.get("lenient_expect", pair["expect"]))
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
        "reading": "strict" if strict else "lenient",
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
        f"calibration ({report['reading']}): n={report['n']} "
        f"precision={_fmt(report['precision'])} "
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


_BAND_LABELS = {
    "at_or_above": "at or above the real backend (outranks code)",
    "below": "below the real backend (code outranks)",
}


def _fidelity_line(name: str, row: dict[str, Any]) -> str:
    return (
        f"{name}: precision={_fmt(row['precision'])} ({row['tp']}/{row['returned']}) "
        f"recall={_fmt(row['recall'])} ({row['tp']}/{row['expected']}) "
        f"hard_errors={row['hard_errors']}"
    )


def _print_fidelity_block(fidelity: dict[str, Any], indent: str) -> None:
    """The executed tier per backend fidelity (konyklabs/asbuilt#38), in
    `fidelities.yaml`'s order, grouped into D-014's two bands; a claimed
    fidelity the vocabulary does not have is printed after them."""
    print(f"{indent}tier executed by fidelity (real backend: {fidelity['real_backend']}):")
    for band, totals in fidelity["bands"].items():
        print(f"{indent}  {_fidelity_line(_BAND_LABELS[band], totals)}")
        for name in totals["fidelities"]:
            print(f"{indent}    {_fidelity_line(name, fidelity['by_fidelity'][name])}")
    for name, row in fidelity["by_fidelity"].items():
        if name not in fidelity["ranked"]:
            print(f"{indent}  {_fidelity_line(f'{name} (not in fidelities.yaml)', row)}")
    u = fidelity[_UNQUALIFIED]
    print(
        f"{indent}  unqualified (executed, no fidelity): precision={_fmt(u['precision'])} "
        f"({u['tp']}/{u['returned']})"
    )
    if fidelity["confusion"]:
        print(f"{indent}  fidelity confusion (rows=truth, cols=returned):")
        for truth in sorted(fidelity["confusion"]):
            row = " ".join(f"{k}={v}" for k, v in sorted(fidelity["confusion"][truth].items()))
            print(f"{indent}    {truth:<12} {row}")


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
    for t in _OTHER_TIERS:
        tp = tier.get(f"tp_{t}", 0)
        print(
            f"    tier {t}: precision={_fmt(tier.get(f'precision_{t}'))} "
            f"({tp}/{tier.get(f'returned_{t}', 0)}) "
            f"recall={_fmt(tier.get(f'recall_{t}'))} ({tp}/{tier.get(f'expected_{t}', 0)})"
        )
    if "fidelity" in tier:
        _print_fidelity_block(tier["fidelity"], "    ")
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


def _distinct_executed_line(distinct: dict[str, Any]) -> str:
    parts = [
        f"{reading} precision={_fmt(d['precision'])} ({d['tp']}/{d['n']}, "
        f"Wilson 95% lower={_fmt(d['wilson_lower'])})"
        for reading, d in distinct.items()
    ]
    return "executed tier, distinct facts (explain+search): " + " | ".join(parts)


def _distinct_readings_line(name: str, readings: dict[str, Any]) -> str:
    return f"{name}: " + " | ".join(
        f"{reading} precision={_fmt(readings[reading]['precision'])} "
        f"({readings[reading]['tp']}/{readings[reading]['n']}, "
        f"Wilson 95% lower={_fmt(readings[reading]['wilson_lower'])})"
        for reading in ("strict", "lenient")
    )


def _print_distinct_by_fidelity(by_fidelity: dict[str, Any]) -> None:
    print("executed tier, distinct facts by fidelity (explain+search):")
    for band, totals in by_fidelity["bands"].items():
        print(f"  {_distinct_readings_line(_BAND_LABELS[band], totals)}")
        for name in totals["fidelities"]:
            print(f"    {_distinct_readings_line(name, by_fidelity['by_fidelity'][name])}")
    for name, readings in by_fidelity["by_fidelity"].items():
        if not any(name in t["fidelities"] for t in by_fidelity["bands"].values()):
            print(f"  {_distinct_readings_line(f'{name} (not in fidelities.yaml)', readings)}")
    print(f"  {_distinct_readings_line('unqualified (no fidelity)', by_fidelity[_UNQUALIFIED])}")


def _kind_line(by_kind: dict[str, dict[str, int]], kind: str) -> str:
    k = by_kind.get(kind, dict.fromkeys(_KIND_COUNTS, 0))
    return (
        f"kind {kind}: matched={k['matched']} vs expected={k['expected']} "
        f"recall={_fmt(_ratio(k['matched'], k['expected']))} "
        f"winner={k['winner_correct']}/{k['winner_checked']}"
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
                f"hard_fp={s['hard_false_positives']} restated={s.get('restated', 0)} "
                f"unplanted={len(s.get('unplanted', []))}"
            )
        else:
            denom = f"tp={s['tp']}/{s['returned']} vs expected={s['expected']}"
        line = f"{name:<15}{_fmt(s['precision']):<12}{_fmt(s['recall']):<12}{_fmt(s['f1']):<10}"
        print(line + denom)
        for cat, counts in sorted(s.get("by_category", {}).items()):
            print(f"    {cat:<20} tp={counts['tp']} expected={counts['expected']}")
        if name in ("explain", "search"):
            _print_fact_surface_detail(s, phase)
        if name == "contradictions":
            print(f"    {_kind_line(s.get('by_kind', {}), _FAKE_VS_REAL)}")
        if name == "search":
            rank = s.get("rank", {})
            r10 = rank.get("r10_hits")
            print(
                f"    precision@5={_fmt(rank.get('precision_at_5'))} "
                f"({rank.get('p5_hits')}/{rank.get('p5_n')}) "
                f"recall@10={_fmt(rank.get('recall_at_10'))} ({r10}/{s['expected']})"
            )

    distinct = report.get("distinct_executed")
    if distinct:
        print(_distinct_executed_line(distinct))
    if report.get("distinct_executed_by_fidelity"):
        _print_distinct_by_fidelity(report["distinct_executed_by_fidelity"])

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
    for reading, stats in agg.get("distinct_executed", {}).items():
        metric = f"distinct_executed_{reading}"
        print(
            f"{'explain+search':<15}{metric:<26}{_fmt(stats['median']):<10}"
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
            "against truth facts carrying a test document, or the carriers "
            "--truth-filter names; skips normal scoring"
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
        for strict in (True, False):
            print_calibration_report(
                calibrate(pairs, mention_index, alias_index, truth.entities, strict)
            )
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
