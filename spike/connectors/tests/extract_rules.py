"""The deterministic ("rules") extractor: skeleton -> one candidate statement,
never past what the test's assertion actually proves (D-013: "a passing test
proves exactly what it asserted, extraction never generalises past the
assertion").

**Fifth pass** (asbuilt#36, D-014): a Python statement is built from what the
test's assertions assert, not from its name. The hand audit of stack B
(asbuilt#5) found the name sentence over-claiming: `test_membership_lapses_
7_days_after_failed_renewal` asserts `GRACE_DAYS == 7`, a `GRACE` status and
a `grace_ends_at`, yet the statement said "lapses". The rules, in
`_python_statement`:

- The name may choose words, never add a behaviour. Each content word of
  the name must be supported by the test's own code (`_test_vocabulary`:
  the names, attributes, keywords, string literals and callee parameter
  names it uses, the constants it references), by an outcome its
  assertions check (`_outcome_support`: a 4xx status or error code supports
  "refused", a 2xx "allowed", any status "returns", `is False` "off"), or,
  for an asserted value no constant names, by sitting next to that value in
  the name (`_label_words`: "unlock fee" beside the asserted $1.00). A
  number in the name must be one the test uses.
- A fully supported name is the statement, with every asserted constant's
  value stated in it (`_insert_values`: "The member rate after free minutes
  is $0.15.") and the flag conditions the assertions depend on
  (`_conditions`: "... with overflow_parking off"), and the earlier
  successful calls a refused call depends on (`_prior_calls_condition`:
  "Third checkout refused with 2 bikes checked out.").
- Otherwise the statement is the assertions themselves, rendered
  (`_assertion_sentence`): constants by name and value, computed dates as
  "N days after X", enum states, statuses and bare counts as exactly what
  they are, after the call the assertions read, under the same conditions.

Number words are digits and ordinals stay words ("first", "third": a
position, not a quantity). TypeScript statements are unchanged (the it-title).
A value constant named exactly as a flag the test's calls set
(`EBIKE_SURCHARGE` beside `ebike_surcharge_enabled`) gets no claim: the claim
would give the flag a dollar value, and the code has no other name for it.

**Second pass** (asbuilt#8 integration review): the first pass templated a
Python statement from a single chosen literal (the last literal-bearing
assert), which guessed wrong often enough to be a majority of the returned
false positives. This pass never picks one literal arbitrarily:

1. **Third pass correction** (its name sentence superseded by the fifth
   pass above; `detail` is unchanged): `Rule.statement` is ONE sentence,
   built only from the test's own *name* (`test_` stripped, underscores split, number
   words and ordinals normalised to digits — "thirty" -> 30, "third" ->
   "3rd" — and a `<number> dollar(s)` pair folded to `$x.00`; a bare
   trailing numeric token, usually the test's own example value, is
   dropped). The second pass appended every assertion clause to the
   statement itself, which pushed even a correct name sentence's word-
   overlap ratio below the matcher's threshold once enough unrelated clause
   words piled on (the matcher's similarity is an overlap coefficient over
   the WHOLE statement's words, not per-clause). Every clause instead goes
   into `Rule.detail` — a plain, semicolon-joined string carried in the
   output for arms and human readers, never matched against truth: one
   clause per distinct literal-bearing comparison (`"<lhs source text>
   equals <literal>"`, money as `$x.xx`), status-code and error-code
   comparisons folded into their own API clause (`"<endpoint> returns HTTP
   <status> with error code <code>"`, omitting whichever half is absent)
   instead of a generic clause, and a matched event-topic/event-type
   literal pair folded into `"publishes <event> to <queue>"` the same way.
   Never a single literal chosen arbitrarily — every distinct comparison
   the test makes becomes a clause in `detail`, deduplicated only when
   truly identical.
2. Claims come from module-level constants first, not a primary-literal
   guess: every ALL_CAPS name one of the test's own assertions mentions that
   resolves (through the test's own imports, followed one hop into the
   source tree via a caller-supplied `source_lookup`) to a scalar assignment
   becomes one claim (`entity` = the constant's own name, `attribute` = the
   constant's name lower-cased, `value` read from the source at the given
   step, `unit` inferred from the name and value type — see `infer_unit`).
   The first resolved constant's claim is `Rule.claim`; the rest are
   `Rule.claims` (the scorer only reads the singular field). When NO
   constant resolves, a conservative fallback (`_fallback_claim`) derives a
   claim from the test's own name instead of leaving it empty, but only
   when confident: the test's SOLE literal-bearing assert is a money/cents
   comparison, or any literal-bearing assert (money or a plain count) whose
   own left side shares a word with the test's name; never an HTTP-status-
   shaped int, a bare `len(...)`/`toHaveLength(...)` count unless the name
   itself says times/retries/attempts/count, or a bool; unit only "usd" for
   money or an explicit unit/count word in the name, never guessed from the
   assert's own expression text. A fourth-pass review found the PRIOR
   (unconditional, last-literal) version wrong on 12 of 13 fixture cases —
   entities that never resolve, an HTTP status read as a day count, a
   boundary probe's incidental per-minute charge attributed to a 30-minute
   threshold it never proves — and removing it raised true positives; this
   version is deliberately narrow rather than repeat that. Even so, most
   compound end-to-end tests that only prove a value through *behaviour*
   (a boundary probe, never naming or directly computing the value) still
   carry no claim at all — a known, accepted gap, and exactly the model
   extractor's job, not this one's.
3. Entities are the service (from the module path), every constant name a
   claim was built from, and the test file's own "subject noun" (its
   filename with `test_`/`.py` stripped and underscores turned to spaces —
   "pricing", "lost bikes", "tollbooth client", "close ride" — matching
   Vitest's `describe` block directly). The old test-name-derived slug
   entity is dropped: it was never a real, resolvable entity name and only
   added noise.
4. A Vitest statement is `"<describe> <it title>."`, the it title's own
   number words normalised the same way (most titles are already digit-based
   prose); its `detail` is the it-block's own `expect(...)` lines,
   semicolon-joined, same role as the Python clauses; entities are
   `dispatch`, the describe name itself, and every *called* imported
   identifier; claims come from ALL_CAPS names the it-block references,
   resolved the same one-hop way into `dispatch/src`.
5. Category is name/path heuristics, in priority order: an HTTP-status-shaped
   token in the test's own name ("409", "4xx") or the word "publish" always
   means technical-implementation (the test's own name says it is about the
   wire shape or the side effect, not the business value); failing that, a
   path hint (`flag`, `rideevents`/`consumer`, `stationstatus`) means
   technical-implementation; everything else defaults to business-logic —
   the fixture's own plurality category, and the same default the first pass
   used. This is a heuristic, not a real classifier: `test_tollbooth_client
   .py::test_capture_retries_three_times_then_fails` (a retry-count POLICY,
   category business-logic in truth) and `..._does_not_retry_a_4xx`
   (a mechanism, technical-implementation) live in the same file and would
   tie under any path-only rule — only the second carries a status-shaped
   token in its own name, which is exactly why status-shape-in-name is
   checked first and file path is only ever the fallback.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from connectors.tests.collect import (
    AssertExpr,
    Skeleton,
    _approximate_param_id,
    _decorator_name_and_call,
    _kw_value,
    _parametrize_cases,
)

SourceLookup = Callable[[str], "str | None"]

_STDLIB_OR_TEST_TOP_MODULES = {
    "__future__",
    "pytest",
    "decimal",
    "datetime",
    "vitest",
    "typing",
    "dataclasses",
    "json",
    "re",
    "os",
    "sys",
}


@dataclass(frozen=True)
class Rule:
    """A candidate statement over a skeleton — no tier, no citations: those
    need evidence (lift.py combines a Rule with `evidence.py`'s outcomes).
    `claim` is the first resolved constant's claim (or None); `claims`
    carries every resolved constant's claim, including the first — the
    scorer only reads `claim` today (see module docstring, point 2).

    Third pass (asbuilt#8 integration review): the schema's `statement` is
    ONE sentence, and the matcher's text similarity is an overlap
    coefficient over the statement's own words — appending every assertion
    clause to it (the second pass's design) pushed even a correct name
    sentence's overlap ratio below the match threshold once enough
    unrelated clause words piled on. `statement` is one sentence (Python:
    from the assertions, fifth pass; Vitest: "<describe> <it title>.");
    every assertion clause, the API/error clause and the event clause move
    to `detail` — a
    plain string, semicolon-joined, carried in the output for arms and
    human readers but never matched against truth."""

    node_id: str
    statement: str
    category: str
    entities: tuple[str, ...]
    claim: dict[str, Any] | None
    claims: tuple[dict[str, Any], ...] = ()
    detail: str = ""


# --------------------------------------------------------------- name words


_NUMBER_WORDS: dict[str, int] = {
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
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_ORDINAL_WORDS: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
}
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)
_TRAILING_NUMBER_RE = re.compile(r"_-?\d+$")


def _test_subject_phrase(skeleton: Skeleton) -> str:
    """The test's own name, humanised, trailing example value dropped —
    "lost bike fee" from `test_lost_bike_fee_100` — used as the entity/
    attribute source for the fallback claim (module docstring point 2's
    "third pass" addendum) and as the money-substitution context for
    `_name_words` below. Not the same as `_subject_noun` (the FILE's own
    name, e.g. "lost bikes") — this one is per-test."""
    name = skeleton.name
    if name.startswith("test_"):
        name = name[len("test_") :]
    name = _TRAILING_NUMBER_RE.sub("", name)
    return name.replace("_", " ").strip()


def _primary_literal_assert(skeleton: Skeleton) -> AssertExpr | None:
    """The LAST literal-bearing assert, in source order — reused for two
    narrow, deliberately single-pick purposes only (never for `detail`,
    which still keeps every clause per module docstring point 1): swapping
    a money value into the name sentence's own trailing digit, and, when no
    constant resolves, seeding the fallback claim (point 2's "third pass"
    addendum: "Lost bike fee 100." was never matchable against a $100.00
    truth fact; the test's own name already carries that number, so its
    LAST literal-bearing assert — often the test's own final, most
    outcome-relevant check, same reasoning the very first pass used — is
    read for what it says that number IS, once, as a targeted exception to
    "never pick one arbitrarily")."""
    for assertion in reversed(skeleton.asserts):
        if assertion.left_literal is not None or assertion.right_literal is not None:
            return assertion
    return None


_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_COMPOUND_NUMBER_WORD_RE = re.compile(
    "^(" + "|".join(_TENS) + ")(one|two|three|four|five|six|seven|eight|nine)$"
)


def _name_words(skeleton: Skeleton) -> list[str]:
    """The test's own name as words: `test_` stripped, number words as
    digits (a closed compound too: "fortyfive" is 45, as the scorer reads
    it), ordinals kept as words ("first", "third": a position, which the
    scorer does not count as a quantity), and `<number> dollar(s)` folded
    to `$x.00`. A trailing bare digit that names the value a money or
    cents-shaped assert proves becomes that value ("Lost bike fee
    $150.00"), as the third pass did."""
    name = skeleton.name
    if name.startswith("test_"):
        name = name[len("test_") :]

    words: list[str] = []
    for tok in (t for t in name.split("_") if t):
        low = tok.lower()
        compound = _COMPOUND_NUMBER_WORD_RE.match(low)
        if compound:
            words.append(str(_NUMBER_WORDS[compound.group(1)] + _NUMBER_WORDS[compound.group(2)]))
        elif low in _NUMBER_WORDS:
            words.append(str(_NUMBER_WORDS[low]))
        else:
            words.append(tok)

    merged: list[str] = []
    i = 0
    while i < len(words):
        if (
            i + 1 < len(words)
            and words[i].isdigit()
            and words[i + 1].lower() in ("dollar", "dollars")
        ):
            merged.append(f"${int(words[i])}.00")
            i += 2
        else:
            merged.append(words[i])
            i += 1

    if merged and merged[-1].isdigit():
        primary = _primary_literal_assert(skeleton)
        if primary is not None:
            literal, other_side = _literal_side(primary)
            cents = _is_cents(other_side)
            money = cents or _is_money_context(other_side, _test_subject_phrase(skeleton))
            if money and not isinstance(literal, bool) and isinstance(literal, (int, float, str)):
                display, _ = _format_literal(literal, money=True, cents=cents)
                if display.startswith("$"):
                    merged[-1] = display
    return merged


def _sentence(text: str) -> str:
    text = " ".join(text.split()).strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def _replace_number_words_in_text(text: str) -> str:
    return _NUMBER_WORD_RE.sub(lambda m: str(_NUMBER_WORDS[m.group(1).lower()]), text)


# ------------------------------------------------------------------ service


def _service_from_imports(imports: tuple[str, ...]) -> str | None:
    for imp in imports:
        top = imp.split(".")[0].split("/")[-1] if "/" in imp else imp.split(".")[0]
        top = top.lstrip("./").split("/")[0]
        if top and top not in _STDLIB_OR_TEST_TOP_MODULES:
            return top
    return None


def _subject_noun(skeleton: Skeleton) -> str:
    """The test file's own "subject noun" (module docstring point 3):
    its filename, `test_`/extension stripped, underscores humanised —
    "test_lost_bikes.py" -> "lost bikes", matching a Vitest `describe`
    block directly (no stripping needed there, see `_ts_entities`)."""
    stem = Path(skeleton.file).stem
    if stem.startswith("test_"):
        stem = stem[len("test_") :]
    return stem.replace("_", " ").strip()


# --------------------------------------------------------- word/segment aid

_WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _segments(text: str) -> set[str]:
    return set(_WORD_SPLIT_RE.split(text.lower()))


def _has_word(text: str, word: str) -> bool:
    """True if `word` (or its simple plural) is a whole underscore/space/
    hyphen-delimited segment of `text` — "cent" matches "amount_cents" (a
    real sub-word split on "_"), but "cap" does not match "capture" (not a
    segment boundary at all, just a shared prefix)."""
    segments = _segments(text)
    return word in segments or f"{word}s" in segments


def _has_word_stem(text: str, stem: str) -> bool:
    """True if some whole segment of `text` starts with `stem` — for a verb
    like "publish" whose real forms ("publishes", "published") a simple-
    plural `_has_word` doesn't cover (`test_close_ride_publishes_ride_
    completed`'s own "publishes" segment isn't "publish" or "publishs").
    Matching on a whole SEGMENT's prefix, not a bare substring anywhere in
    `text`, keeps the same false-positive guard `_has_word` has: "publish"
    matches the segment "publishes", but would not match "unpublished" as
    one word ("un" starts the segment, not "publish") the way an unanchored
    substring search would risk elsewhere."""
    return any(segment.startswith(stem) for segment in _segments(text))


# ----------------------------------------------------------------- category

_HTTP_STATUS_IN_NAME_RE = re.compile(r"(?<!\d)[2-5](?:\d{2}|xx)(?!\d)", re.IGNORECASE)
_TECHNICAL_PATH_HINTS = ("flag", "rideevents", "consumer", "stationstatus")


def _category(skeleton: Skeleton) -> str:
    name_low = skeleton.name.lower()
    if _HTTP_STATUS_IN_NAME_RE.search(name_low):
        return "technical-implementation"
    if _has_word_stem(name_low, "publish"):
        return "technical-implementation"
    path_low = re.sub(r"[^a-z0-9]", "", skeleton.file.lower())
    if any(hint in path_low for hint in _TECHNICAL_PATH_HINTS):
        return "technical-implementation"
    return "business-logic"


# -------------------------------------------------------------- money/unit


def _is_cents(text: str) -> bool:
    return _has_word(text, "cent")


_MONEY_HINTS = ("rate", "fee", "cap", "surcharge", "price", "cost", "unlock")


def _is_money_context(*texts: str) -> bool:
    return any(_has_word(t, hint) for t in texts for hint in _MONEY_HINTS)


def _format_money(dollars: float) -> str:
    return f"${dollars:.2f}"


def _format_literal(value: Any, *, money: bool, cents: bool) -> tuple[str, Any]:
    """Returns (display text, the value normalised for reuse in a claim). A
    `Decimal("0.15")`-shaped literal comes out of `collect.py`'s own
    `_literal()` as the STRING "0.15" (the wrapper call's own argument,
    never evaluated) — coerced to a float here so a money/cents context
    still formats it as `$x.xx` instead of leaving the raw digit string
    unformatted."""
    if isinstance(value, bool):
        return str(value), value
    numeric = value
    if isinstance(numeric, str):
        try:
            numeric = float(numeric)
        except ValueError:
            return str(value), value
    if isinstance(numeric, (int, float)) and (cents or money):
        dollars = (numeric / 100) if (cents and isinstance(value, int)) else float(numeric)
        return _format_money(dollars), _format_money(dollars)
    return str(value), value


# --------------------------------------------------------- assertion clauses


def _literal_side(assertion: AssertExpr) -> tuple[Any, str]:
    """(literal value, the OTHER side's source text) for a literal-bearing
    comparison — right literal preferred (the common `expr == literal`
    shape), left otherwise."""
    if assertion.right_literal is not None:
        return assertion.right_literal, assertion.left or ""
    return assertion.left_literal, assertion.right or ""


def _generic_clause(assertion: AssertExpr) -> str:
    literal, other_side = _literal_side(assertion)
    money = _is_money_context(other_side)
    cents = _is_cents(other_side)
    display, _ = _format_literal(literal, money=money, cents=cents)
    return f"{other_side} equals {display}."


_ERROR_DICT_RE = re.compile(r"""['"]error['"]\s*:\s*['"]([A-Za-z_][\w]*)['"]""")
_EVENT_LITERAL_RE = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-z0-9]*$")
_TUPLE_STATUS_RE = re.compile(r"\(\s*([1-5]\d{2})\s*,")


def _looks_like_status_slot(text: str) -> bool:
    """`status == 200` (the word) or `first[0] == 200` (this fixture's own
    `(status, body)`-tuple-return convention, index 0 always the status) —
    both name "the status", not just any int."""
    return _has_word(text, "status") or text.rstrip().endswith("[0]")


def _extract_tuple_status(text: str) -> int | None:
    """A leading HTTP-status-shaped int inside an unparsed tuple literal,
    e.g. `(409, {'error': 'checkout_limit_reached'})` — the whole tuple
    isn't a literal `collect.py`'s own `_literal()` recognises, so this is
    the fallback that lets a `third == (409, {...})`-shaped assert still
    contribute its status instead of only its error code."""
    m = _TUPLE_STATUS_RE.search(text)
    return int(m.group(1)) if m else None


def _api_like_call(calls: tuple[str, ...]) -> str | None:
    for call in calls:
        if "endpoint" in call.lower():
            return call
    return None


def _api_clause(subject: str | None, status: int | None, error: str | None) -> str:
    parts = [subject or "the endpoint", "returns"]
    parts.append(f"HTTP {status}" if status is not None else "a response")
    if error is not None:
        parts.append(f"with error code {error}")
    text = " ".join(parts) + "."
    return text[0].upper() + text[1:]


def _event_clause(event: str | None, queue: str | None) -> str | None:
    if event is None and queue is None:
        return None
    if event and queue:
        return f"Publishes {event} to {queue}."
    if event:
        return f"Publishes {event}."
    return f"Publishes to {queue}."


def _assert_clauses(skeleton: Skeleton) -> tuple[list[str], list[str]]:
    """The second sentence's clauses, in source order, plus any event/queue
    VALUES an event clause used (e.g. "ride.events", "ride.completed") —
    these need to be carried as entities too (module docstring point 3
    doesn't otherwise mention them, but a returned fact with no entity
    naming the queue/event it's about can never align with a truth fact
    that has one). See module docstring point 1 for the three clause kinds
    and the dedup/pairing rules."""
    api_subject = _api_like_call(skeleton.calls)
    generic: list[str] = []
    seen_generic: set[tuple[str, str, str]] = set()

    pending_status: int | None = None
    pending_error: str | None = None
    status_pending = False
    emitted_pairs: set[tuple[int | None, str | None]] = set()
    api_clauses: list[str] = []

    def _flush_status() -> None:
        nonlocal pending_status, pending_error, status_pending
        # A bare "it succeeded" status (2xx/3xx, no error code) carries no
        # distinguishing content — nearly every e2e test asserts one on its
        # happy path, and its status number (200, 201, ...) only pollutes
        # the statement's number set against a truth fact that never
        # mentions it (measured against the real fixture: every pricing
        # e2e test's own "$1.00"/"$0.15"-shaped truth fact was rejected by
        # the number-set-equality check purely because of an unrelated
        # "200" this clause would otherwise have added). Only a status paired
        # with an error, or a non-2xx/3xx status on its own, is worth a clause.
        boilerplate_success = (
            pending_error is None and pending_status is not None and 200 <= pending_status < 400
        )
        if status_pending and not boilerplate_success:
            pair = (pending_status, pending_error)
            if pair not in emitted_pairs:
                emitted_pairs.add(pair)
                api_clauses.append(_api_clause(api_subject, pending_status, pending_error))
        pending_status, pending_error, status_pending = None, None, False

    pending_event: str | None = None
    pending_queue: str | None = None
    event_pending = False
    emitted_event_pairs: set[tuple[str | None, str | None]] = set()
    event_clauses: list[str] = []
    entities: list[str] = []

    def _flush_event() -> None:
        nonlocal pending_event, pending_queue, event_pending
        if event_pending:
            pair = (pending_event, pending_queue)
            if pair not in emitted_event_pairs:
                emitted_event_pairs.add(pair)
                clause = _event_clause(pending_event, pending_queue)
                if clause:
                    event_clauses.append(clause)
                    entities.extend(v for v in (pending_event, pending_queue) if v)
        pending_event, pending_queue, event_pending = None, None, False

    for assertion in skeleton.asserts:
        left_text, right_text = assertion.left or "", assertion.right or ""

        is_status = assertion.op == "==" and (
            (
                isinstance(assertion.right_literal, int)
                and not isinstance(assertion.right_literal, bool)
                and _looks_like_status_slot(left_text)
            )
            or (
                isinstance(assertion.left_literal, int)
                and not isinstance(assertion.left_literal, bool)
                and _looks_like_status_slot(right_text)
            )
        )
        if is_status:
            status_value = (
                assertion.right_literal
                if isinstance(assertion.right_literal, int)
                and not isinstance(assertion.right_literal, bool)
                else assertion.left_literal
            )
            if status_pending:
                _flush_status()
            pending_status = status_value
            status_pending = True
            continue

        error_value: str | None = None
        if (
            assertion.op == "=="
            and isinstance(assertion.right_literal, str)
            and _has_word(left_text, "error")
        ):
            error_value = assertion.right_literal
        elif (
            assertion.op == "=="
            and isinstance(assertion.left_literal, str)
            and _has_word(right_text, "error")
        ):
            error_value = assertion.left_literal
        else:
            m = _ERROR_DICT_RE.search(right_text) or _ERROR_DICT_RE.search(left_text)
            if assertion.op == "==" and m:
                error_value = m.group(1)
        if error_value is not None:
            tuple_status = _extract_tuple_status(right_text) or _extract_tuple_status(left_text)
            if tuple_status is not None:
                if status_pending:
                    _flush_status()
                pending_status = tuple_status
            pending_error = error_value
            status_pending = True
            continue

        if (
            assertion.op == "=="
            and isinstance(assertion.right_literal, str)
            and _EVENT_LITERAL_RE.match(assertion.right_literal)
        ):
            value = assertion.right_literal
            if (
                _has_word(left_text, "topic")
                or _has_word(left_text, "queue")
                or _has_word(left_text, "bus")
            ):
                if event_pending and pending_queue is not None:
                    _flush_event()
                pending_queue = value
                event_pending = True
                continue
            if _has_word(left_text, "type") or _has_word(left_text, "event"):
                if event_pending and pending_event is not None:
                    _flush_event()
                pending_event = value
                event_pending = True
                continue

        if assertion.left_literal is not None or assertion.right_literal is not None:
            key = (assertion.op or "", left_text, right_text)
            if key in seen_generic:
                continue
            seen_generic.add(key)
            generic.append(_generic_clause(assertion))

    _flush_status()
    _flush_event()
    return generic + api_clauses + event_clauses, entities


def _clean_docstring(docstring: str) -> str:
    text = " ".join(docstring.split())
    return text if text.endswith((".", "!", "?")) else text + "."


def _join_detail(clauses: list[str]) -> str:
    """`detail`'s own join: each clause already ends with its own "." (see
    `_generic_clause`/`_api_clause`/`_event_clause`) — stripped and rejoined
    with "; " so `detail` reads as one semicolon-separated line instead of
    several standalone sentences, then one closing "." is added back."""
    if not clauses:
        return ""
    stripped = [c[:-1] if c.endswith(".") else c for c in clauses]
    return "; ".join(stripped) + "."


# -------------------------------------------------------------- TS support


def _ts_describe(skeleton: Skeleton) -> str:
    return skeleton.node_id.split(" > ")[0]


def _ts_statement(skeleton: Skeleton) -> str:
    describe = _ts_describe(skeleton)
    title = _replace_number_words_in_text(skeleton.name)
    text = f"{describe} {title}".strip()
    return text if text.endswith((".", "!", "?")) else text + "."


_TS_IMPORT_BLOCK_RE = re.compile(r"import\s+(type\s+)?\{([^}]*)\}\s*from")


def _ts_imported_names(source: str) -> set[str]:
    """Every value (non-`import type`) named import in `source` — module
    docstring point 4's "every imported identifier that is called" needs
    this because `skeleton.calls` (from `collect.py`'s tolerant line scan)
    is every call anywhere in the it-block, vitest matchers (`toEqual`,
    `toHaveLength`) and JS builtins (`Date`, `async`) included; without this
    filter those would show up as noise entities that can never resolve."""
    names: set[str] = set()
    for is_type, group in _TS_IMPORT_BLOCK_RE.findall(source):
        if is_type:
            continue
        for part in group.split(","):
            part = part.strip()
            if not part:
                continue
            names.add(part.split(" as ")[-1].strip())
    return names


# --------------------------------------------------------------- constants

_UNIT_SUFFIXES = (
    ("_MINUTES", "minute"),
    ("_MINUTE", "minute"),
    ("_DAYS", "day"),
    ("_DAY", "day"),
    ("_HOURS", "hour"),
    ("_HOUR", "hour"),
    ("_SECONDS", "second"),
    ("_SECOND", "second"),
)
_MONEY_NAME_HINTS = ("FEE", "CAP", "RATE", "PRICE")
_COUNT_NAME_HINTS = ("RETRIES", "RETRY", "MAX", "LIMIT")


def infer_unit(name: str, *, is_decimal: bool) -> str | None:
    upper = name.upper()
    for suffix, unit in _UNIT_SUFFIXES:
        if upper.endswith(suffix):
            return unit
    if is_decimal or any(hint in upper for hint in _MONEY_NAME_HINTS):
        return "usd"
    if any(hint in upper for hint in _COUNT_NAME_HINTS):
        return "count"
    return None


def _python_scalar_literal(node: ast.expr) -> tuple[bool, Any, bool]:
    """(found, value, is_decimal) for a module-level constant's own RHS —
    a bare Constant, a negated Constant, or a `Decimal("x")`/`Decimal(x)`
    wrapper call."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, bool, str)):
        return True, node.value, False
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        found, value, is_decimal = _python_scalar_literal(node.operand)
        return (found, -value, is_decimal) if found else (False, None, False)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Decimal"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ):
        try:
            return True, float(Decimal(str(node.args[0].value))), True
        except Exception:  # noqa: BLE001 - a malformed Decimal literal just isn't resolvable
            return False, None, False
    return False, None, False


def find_python_constant(source: str, name: str) -> tuple[Any, bool] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        targets: list[ast.expr] = []
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value_node = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value_node = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                found, value, is_decimal = _python_scalar_literal(value_node)
                if found:
                    return value, is_decimal
    return None


_TS_CONST_RE_TEMPLATE = r"export\s+const\s+{name}\s*=\s*([^;]+);"


def _find_ts_constant(source: str, name: str) -> tuple[Any, bool] | None:
    m = re.search(_TS_CONST_RE_TEMPLATE.format(name=re.escape(name)), source)
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        value: Any = int(raw)
    except ValueError:
        try:
            value = float(raw)
        except ValueError:
            if raw in ("true", "false"):
                value = raw == "true"
            elif raw.startswith(('"', "'")):
                value = raw.strip("'\"")
            else:
                return None
    return value, False


def _candidate_paths(skeleton: Skeleton) -> list[str]:
    if skeleton.language == "python":
        return [
            imp.replace(".", "/") + ".py"
            for imp in skeleton.imports
            if imp not in _STDLIB_OR_TEST_TOP_MODULES
        ]
    test_dir = Path(skeleton.file).parent
    paths = []
    for imp in skeleton.imports:
        if not imp.startswith("."):
            continue
        resolved = (test_dir / imp).as_posix()
        if resolved.endswith(".js"):
            resolved = resolved[: -len(".js")] + ".ts"
        paths.append(resolved)
    return paths


def build_constant_claim(name: str, value: Any, is_decimal: bool, document: str) -> dict[str, Any]:
    unit = infer_unit(name, is_decimal=is_decimal)
    display_value: Any = _format_money(float(value)) if unit == "usd" else value
    return {
        "entity": name,
        "attribute": name.lower(),
        "value": display_value,
        "unit": unit,
    }, document


_ALL_CAPS_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9_]{1,}\b")


def _constants_in_asserts(skeleton: Skeleton) -> list[str]:
    """The subset of `skeleton.constants` that actually appears in one of
    the test's own assertions, in first-appearance (source) order — not
    every ALL_CAPS name anywhere in the function body. `skeleton.constants`
    is collected from the WHOLE body (module docstring point 2's "imports
    or references"), which over-collects: a name used only in setup, never
    compared, isn't what the test is proving. Restricting to names an
    assertion itself mentions fixes two real cases found against the real
    fixture: `test_lost_bike_fee_150` (which never names `LOST_BIKE_FEE` at
    all, only `LOST_BIKE_HOURS` in an unrelated `timedelta(...)` setup call —
    now correctly gets NO claim, rather than a wrong one) and
    `test_member_rate_after_free_minutes` (which references `MEMBER_RATE` in
    its assert but `MEMBER_FREE_MINUTES` only in a setup line — the ordering
    also matters here: `skeleton.constants` is alphabetised by `collect.py`,
    which put `MEMBER_FREE_MINUTES` first and made it the Fact's primary
    claim over the test's actual subject, `MEMBER_RATE`)."""
    known = set(skeleton.constants)
    seen: list[str] = []
    for assertion in skeleton.asserts:
        for text in (assertion.source, assertion.left or "", assertion.right or ""):
            for token in _ALL_CAPS_TOKEN_RE.findall(text):
                if token in known and token not in seen:
                    seen.append(token)
    return seen


def _resolve_constants(
    skeleton: Skeleton, source_lookup: SourceLookup | None
) -> list[tuple[str, dict[str, Any], str]]:
    """Every ALL_CAPS name one of the test's own assertions mentions (see
    `_constants_in_asserts`) that resolves, through one of the skeleton's
    own imports, to a scalar module-level constant — see module docstring
    point 2. Returns (name, claim, citation-document) triples, in
    first-assertion order, one per resolvable name."""
    if source_lookup is None:
        return []
    names = _constants_in_asserts(skeleton)
    if not names:
        return []
    finder = find_python_constant if skeleton.language == "python" else _find_ts_constant
    resolved: list[tuple[str, dict[str, Any], str]] = []
    for name in names:
        for path in _candidate_paths(skeleton):
            source = source_lookup(path)
            if source is None:
                continue
            found = finder(source, name)
            if found is None:
                continue
            value, is_decimal = found
            claim, document = build_constant_claim(name, value, is_decimal, path)
            resolved.append((name, claim, document))
            break
    return resolved


_UNIT_WORD_HINTS = (("minute", "minute"), ("day", "day"), ("hour", "hour"), ("second", "second"))


def _unit_from_words(text: str) -> str | None:
    for hint, unit in _UNIT_WORD_HINTS:
        if _has_word(text, hint):
            return unit
    return None


_COUNT_NAME_WORDS = ("time", "times", "retry", "retries", "attempt", "attempts", "count")
_LENGTH_CALL_HINTS = ("len(", "tohavelength(")


def _is_http_status_shaped(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599


def _is_length_call(text: str) -> bool:
    low = text.lower()
    return any(hint in low for hint in _LENGTH_CALL_HINTS)


def _shares_word(a: str, b: str) -> bool:
    return bool(_segments(a) & _segments(b))


def _fallback_claim(skeleton: Skeleton) -> dict[str, Any] | None:
    """Fourth-pass review correction: the earlier version fired on the
    test's LAST literal-bearing assert unconditionally, which produced
    wrong data for most tests it touched — a compound e2e test's status
    code read as a claim value with a nonsense unit, or a boundary probe's
    incidental per-minute charge ($0.15) attributed to the test's OWN named
    subject (30-minute-free), which it never actually proves. Now
    conservative, in order:

    1. Only the test's SOLE literal-bearing assert is trusted when it's a
       money literal (`Decimal("x")`, `$x.xx`) or a `_cents`-named
       expression — no ambiguity about which of several branches it
       belongs to, since there IS only one (this is exactly
       `test_lost_bike_fee_150`'s shape: one assert, no constant, a cents
       expression). A money/cents assert among several in the SAME test is
       trusted only if its own left side shares a word with the test's own
       name (subject phrase) — the case that rejects the $0.15 boundary
       probe, whose `body["amount_cents"]` shares nothing with "member
       first thirty minutes free".
    2. A non-money integer literal is trusted only with that same word-
       overlap requirement, always — no "sole assert" exception, since an
       arbitrary count has no other signal tying it to the test's subject.
    3. Even then, the literal is rejected if it's HTTP-status-shaped (a
       plain int 100-599 — a status code masquerading as a business value),
       or came from a `len(...)`/`toHaveLength(...)` call UNLESS the test's
       own name says times/retries/attempts/count (a bare length is
       usually incidental, not the thing being tested), or is a bool.
    4. Unit comes from exactly two places: "usd" for a money/cents context,
       or an explicit unit/count word in the test's own name — never from
       the assert's own non-literal side text (that produced "day" for a
       422 status code once, from an unrelated "days" elsewhere in the
       name — the bug this whole rewrite exists to fix). No matching word
       means no unit, not a guessed "count"."""
    literal_asserts = [
        a for a in skeleton.asserts if a.left_literal is not None or a.right_literal is not None
    ]
    if not literal_asserts:
        return None
    primary = literal_asserts[-1]
    literal, other_side = _literal_side(primary)
    if isinstance(literal, bool) or not isinstance(literal, (int, float, str)):
        return None

    subject_phrase = _test_subject_phrase(skeleton)
    left_text = primary.left or ""
    cents = _is_cents(other_side)
    money = cents or _is_money_context(other_side, subject_phrase)

    if money:
        if len(literal_asserts) > 1 and not _shares_word(left_text, subject_phrase):
            return None
    elif not _shares_word(left_text, subject_phrase):
        return None

    if (
        isinstance(literal, int)
        and not isinstance(literal, bool)
        and _is_http_status_shaped(literal)
    ):
        return None
    if _is_length_call(left_text) and not any(
        _has_word(subject_phrase, w) for w in _COUNT_NAME_WORDS
    ):
        return None

    display, numeric = _format_literal(literal, money=money, cents=cents)
    if money:
        value: Any = display
        unit = "usd"
    else:
        value = numeric
        unit = _unit_from_words(subject_phrase)
        if unit is None and any(_has_word(subject_phrase, w) for w in _COUNT_NAME_WORDS):
            unit = "count"

    return {
        "entity": subject_phrase,
        "attribute": subject_phrase.replace(" ", "_"),
        "value": value,
        "unit": unit,
    }


# ------------------------------------------- the statement (fifth pass, #36)

# Words a test's name may use without its code saying them: articles,
# prepositions, connectives, negation and positions ("first", "third").
_FUNCTION_WORDS = frozenset(
    {
        "a", "an", "the", "at", "of", "to", "for", "from", "in", "into", "with",
        "without", "after", "before", "when", "while", "if", "unless", "under", "over",
        "past", "by", "as", "then", "and", "or", "is", "are", "be", "not", "no", "never",
        "does", "do", "every", "each", "per", "than", "more", "less", "least", "most",
        "only", "any", "all", "within", "until", "times", "once", "twice",
        *_ORDINAL_WORDS,
    }
)  # fmt: skip
# An outcome the name states is supported when an assertion checks it: a
# 4xx/5xx status, an error code or `pytest.raises` checks a refusal; a 2xx
# status checks an acceptance; any status checks a response.
_REFUSAL_STEMS = frozenset({"refus", "reject", "deny", "deni", "declin", "fail", "error"})
_ALLOW_STEMS = frozenset({"allow", "accept", "approv", "succeed", "permit"})
_RESPONSE_STEMS = frozenset({"return", "respond", "report"})
_CONDITION_WORDS = ("when", "while", "if", "unless", "with")
_IDENT_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")
_FLAG_PARAM_SUFFIX = "_enabled"


def _stem(word: str) -> str:
    """A deliberately tiny stemmer for comparing a name's word with the
    code's: "refused"/"refuse", "retries"/"retry", "closed"/"close" agree;
    "checkin" and "checkout" do not."""
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            break
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def _ident_words(text: str) -> list[str]:
    return [w.lower() for w in _IDENT_SPLIT_RE.split(text) if w]


def _test_function(
    skeleton: Skeleton, source_lookup: SourceLookup | None
) -> tuple[ast.FunctionDef | None, ast.Module | None]:
    """The test's own function and module, parsed from the step's source;
    (None, None) without a lookup (the statement then rests on the
    skeleton's assertions alone)."""
    source = source_lookup(skeleton.file) if source_lookup else None
    if source is None:
        return None, None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == skeleton.name:
            return node, tree
    return None, tree


def _callee_params(
    name: str,
    skeleton: Skeleton,
    module: ast.Module | None,
    source_lookup: SourceLookup | None,
) -> list[str]:
    """The parameter names of `name`, defined in the test's module or one
    hop into an imported module, so a positional `True` reads as the
    parameter it binds (`ebike_surcharge_enabled`)."""
    trees = [module] if module is not None else []
    for path in _candidate_paths(skeleton) if source_lookup else []:
        source = source_lookup(path)
        if source is None:
            continue
        try:
            trees.append(ast.parse(source))
        except SyntaxError:
            continue
    for tree in trees:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return [a.arg for a in node.args.args]
    return []


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _flag_settings(call: ast.Call, params: list[str]) -> dict[str, bool]:
    """Flags a call sets: a `<flag>_enabled` parameter given a bool literal,
    by keyword or by position."""
    settings: dict[str, bool] = {}
    for kw in call.keywords:
        if (
            kw.arg
            and kw.arg.endswith(_FLAG_PARAM_SUFFIX)
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, bool)
        ):
            settings[kw.arg[: -len(_FLAG_PARAM_SUFFIX)]] = kw.value.value
    for param, arg in zip(params, call.args, strict=False):
        if (
            param.endswith(_FLAG_PARAM_SUFFIX)
            and isinstance(arg, ast.Constant)
            and isinstance(arg.value, bool)
        ):
            settings[param[: -len(_FLAG_PARAM_SUFFIX)]] = arg.value
    return settings


def _code_of(func: ast.FunctionDef) -> list[ast.AST]:
    """The test's code: its parameters and body, never its docstring (prose
    the test does not check) or its decorators (a skip reason)."""
    body = func.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return [func.args, *body]


def _test_calls(func: ast.FunctionDef) -> list[ast.Call]:
    return [n for root in _code_of(func) for n in ast.walk(root) if isinstance(n, ast.Call)]


def _settings_reader(
    skeleton: Skeleton, module: ast.Module | None, source_lookup: SourceLookup | None
) -> Callable[[ast.Call], dict[str, bool]]:
    params_cache: dict[str, list[str]] = {}

    def settings_of(call: ast.Call) -> dict[str, bool]:
        name = _call_name(call)
        if name not in params_cache:
            params_cache[name] = _callee_params(name, skeleton, module, source_lookup)
        return _flag_settings(call, params_cache[name])

    return settings_of


def _flags_set(skeleton: Skeleton, source_lookup: SourceLookup | None) -> set[str]:
    """Every flag a call in the test sets, either way."""
    func, module = _test_function(skeleton, source_lookup)
    if func is None:
        return set()
    settings_of = _settings_reader(skeleton, module, source_lookup)
    return {flag for call in _test_calls(func) for flag in settings_of(call)}


def _conditions(
    skeleton: Skeleton,
    func: ast.FunctionDef | None,
    module: ast.Module | None,
    source_lookup: SourceLookup | None,
) -> dict[str, bool]:
    """The flag conditions the test sets up: a flag a call in this test
    sets, where the module's tests set it both ways (a flag held one way
    across the whole module is the fixture's background, not a condition
    under test). A flag set both ways in this test takes its first
    setting, the test's leading scenario."""
    if func is None or module is None:
        return {}
    settings_of = _settings_reader(skeleton, module, source_lookup)
    seen: dict[str, set[bool]] = {}
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            for call in _test_calls(node):
                for flag, value in settings_of(call).items():
                    seen.setdefault(flag, set()).add(value)
    conditions: dict[str, bool] = {}
    for call in sorted(_test_calls(func), key=lambda c: (c.lineno, c.col_offset)):
        for flag, value in settings_of(call).items():
            if seen.get(flag) == {True, False}:
                conditions.setdefault(flag, value)
    return conditions


def _parametrize_binding(skeleton: Skeleton, func: ast.FunctionDef | None) -> dict[str, Any]:
    """This case's parameter values, matched on the case id `collect.py`
    gave it."""
    if func is None or skeleton.parametrize_id is None:
        return {}
    for dec in func.decorator_list:
        name, call = _decorator_name_and_call(dec)
        if not name.endswith("parametrize") or call is None or not call.args:
            continue
        cases = _parametrize_cases(call) or []
        ids = _kw_value(call, "ids")
        try:
            argnames = ast.literal_eval(call.args[0])
        except (ValueError, TypeError):
            return {}
        names = (
            [n.strip() for n in argnames.split(",")]
            if isinstance(argnames, str)
            else list(argnames)
        )
        for i, case in enumerate(cases):
            case_id = (
                str(ids[i])
                if isinstance(ids, (list, tuple)) and i < len(ids)
                else _approximate_param_id(case)
            )
            if case_id != skeleton.parametrize_id:
                continue
            values = case.elts if isinstance(case, ast.Tuple) and len(names) > 1 else [case]
            binding: dict[str, Any] = {}
            for argname, value in zip(names, values, strict=False):
                try:
                    binding[argname] = ast.literal_eval(value)
                except (ValueError, TypeError):
                    binding[argname] = ast.unparse(value)
            return binding
    return {}


def _constant_values(
    skeleton: Skeleton, source_lookup: SourceLookup | None
) -> dict[str, tuple[Any, str | None]]:
    """Every ALL_CAPS name the test uses that resolves to a scalar, with
    its unit: the asserted constants' values go into the statement, and any
    of them backs a number the test's name states."""
    if source_lookup is None:
        return {}
    finder = find_python_constant if skeleton.language == "python" else _find_ts_constant
    values: dict[str, tuple[Any, str | None]] = {}
    for name in skeleton.constants:
        for path in _candidate_paths(skeleton):
            source = source_lookup(path)
            found = finder(source, name) if source is not None else None
            if found is not None:
                value, is_decimal = found
                values[name] = (value, infer_unit(name, is_decimal=is_decimal))
                break
    return values


def _numbers_in(nodes: list[ast.AST], constants: dict[str, tuple[Any, str | None]]) -> set[float]:
    """Every number written in `nodes` (a `Decimal("0.15")` string too) and
    every resolved constant they name; an integer also counts as cents
    (15000 backs a name's "$150.00")."""
    numbers: set[float] = set()

    def add(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            numbers.add(float(value))
            if isinstance(value, int):
                numbers.add(value / 100)
        elif isinstance(value, str):
            try:
                numbers.add(float(value))
            except ValueError:
                pass

    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Constant):
                add(node.value)
            elif isinstance(node, ast.Name) and node.id in constants:
                add(constants[node.id][0])
    return numbers


def _parse_asserts(skeleton: Skeleton) -> list[ast.expr]:
    parsed = []
    for assertion in skeleton.asserts:
        try:
            parsed.append(ast.parse(assertion.source, mode="eval").body)
        except SyntaxError:
            continue
    return parsed


def _status_values(skeleton: Skeleton) -> list[int]:
    statuses: list[int] = []
    for assertion in skeleton.asserts:
        left, right = assertion.left or "", assertion.right or ""
        for literal, other in (
            (assertion.right_literal, left),
            (assertion.left_literal, right),
        ):
            if (
                isinstance(literal, int)
                and not isinstance(literal, bool)
                and _is_http_status_shaped(literal)
                and _looks_like_status_slot(other)
            ):
                statuses.append(literal)
        tuple_status = _extract_tuple_status(right) or _extract_tuple_status(left)
        if tuple_status is not None:
            statuses.append(tuple_status)
    return statuses


def _outcome_support(skeleton: Skeleton, func: ast.FunctionDef | None) -> set[str]:
    """Stems of the outcome words the assertions check (module docstring,
    fifth pass)."""
    stems: set[str] = set()
    statuses = _status_values(skeleton)
    if statuses:
        stems |= _RESPONSE_STEMS
    if any(400 <= s < 600 for s in statuses):
        stems |= _REFUSAL_STEMS
    if any(200 <= s < 300 for s in statuses):
        stems |= _ALLOW_STEMS
    if any(
        _ERROR_DICT_RE.search(a.source) or (_has_word(a.left or "", "error") and a.right_literal)
        for a in skeleton.asserts
    ):
        stems |= _REFUSAL_STEMS
    if func is not None and any(_call_name(c) == "raises" for c in _test_calls(func)):
        stems |= _REFUSAL_STEMS
    for node in _parse_asserts(skeleton):
        if isinstance(node, ast.Compare) and isinstance(node.comparators[-1], ast.Constant):
            value = node.comparators[-1].value
            if value is False:
                stems |= {"off", "disabl", "fals"}
            elif value is True:
                stems |= {"on", "enabl", "tru"}
    return stems


def _test_vocabulary(
    skeleton: Skeleton,
    func: ast.FunctionDef | None,
    module: ast.Module | None,
    source_lookup: SourceLookup | None,
    conditions: dict[str, bool],
    binding: dict[str, Any],
) -> set[str]:
    """Stems of every word the test's own code uses: assertion text, called
    names, constants, parameters, the test module's own subject ("close
    ride" for `test_close_ride.py`) and, with the source, every name,
    attribute, keyword, string literal and the parameter names its
    positional arguments bind. A flag condition supports "flag" and its
    state."""
    texts: list[str] = [a.source for a in skeleton.asserts]
    texts += [*skeleton.calls, *skeleton.constants, *skeleton.fixtures, *binding]
    texts.append(_subject_noun(skeleton))
    if func is not None:
        for node in (n for root in _code_of(func) for n in ast.walk(root)):
            if isinstance(node, ast.Name):
                texts.append(node.id)
            elif isinstance(node, ast.Attribute):
                texts.append(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                texts.append(node.arg)
            elif isinstance(node, ast.arg):
                texts.append(node.arg)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                texts.append(node.value)
            elif isinstance(node, ast.Call):
                params = _callee_params(_call_name(node), skeleton, module, source_lookup)
                texts.extend(params[: len(node.args)])
    stems = {_stem(w) for text in texts for w in _ident_words(text)}
    if conditions:
        stems.add("flag")
        stems |= {"on" if value else "off" for value in conditions.values()}
    return stems


_NAME_NUMBER_RE = re.compile(r"^\$?(\d+(?:\.\d+)?)$")
_STATUS_CLASS_RE = re.compile(r"^([1-5])xx$", re.IGNORECASE)


def _number_value(word: str) -> float | None:
    m = _NAME_NUMBER_RE.match(word)
    return float(m.group(1)) if m else None


def _number_supported(word: str, numbers: set[float]) -> bool:
    cls = _STATUS_CLASS_RE.match(word)
    if cls:
        low = int(cls.group(1)) * 100
        return any(low <= n < low + 100 for n in numbers)
    value = _number_value(word)
    return value is not None and any(abs(value - n) < 1e-9 for n in numbers)


def _is_content(word: str) -> bool:
    return (
        word.lower() not in _FUNCTION_WORDS
        and _number_value(word) is None
        and not _STATUS_CLASS_RE.match(word)
    )


def _label_words(
    words: list[str],
    supported: list[bool],
    asserted: set[float],
    constant_asserted: set[float],
) -> list[bool]:
    """A number in the name that an assertion proves, and that no asserted
    constant names, lends support to the run of content words beside it, up
    to a function word or another number: they label the value ("charges
    $1.00 unlock fee" for an asserted amount of 100 cents). A value an
    asserted constant names is labelled by the constant, never by the name:
    "lapses 7 days" beside `GRACE_DAYS == 7` stays unsupported."""
    out = list(supported)
    for i, word in enumerate(words):
        value = _number_value(word)
        if value is None or not any(abs(value - n) < 1e-9 for n in asserted):
            continue
        if any(abs(value - n) < 1e-9 for n in constant_asserted):
            continue
        for step in (-1, 1):
            j = i + step
            while 0 <= j < len(words) and _is_content(words[j]):
                out[j] = True
                j += step
    return out


def _constant_clauses(
    skeleton: Skeleton, constants: dict[str, tuple[Any, str | None]]
) -> list[tuple[str, Any, str | None]]:
    """(name, value, unit) for each `CONSTANT == literal` assertion, in
    source order: the constant names the quantity, the test pins its value."""
    found: list[tuple[str, Any, str | None]] = []
    for assertion in skeleton.asserts:
        if assertion.op != "==":
            continue
        for side, literal in (
            (assertion.left, assertion.right_literal),
            (assertion.right, assertion.left_literal),
        ):
            name = (side or "").strip()
            if literal is not None and name in constants and name not in [n for n, _, _ in found]:
                value, unit = constants[name]
                found.append((name, value, unit))
    return found


_UNIT_PLURAL = {"day": "days", "hour": "hours", "minute": "minutes", "second": "seconds"}


def _value_text(value: Any, unit: str | None) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if unit == "usd" and isinstance(value, (int, float)):
        return _format_money(float(value))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if unit in _UNIT_PLURAL:
        return f"{value} {unit if value == 1 else _UNIT_PLURAL[unit]}"
    return str(value)


def _constant_phrase(name: str, unit: str | None) -> str:
    words = _ident_words(name)
    for suffix, suffix_unit in _UNIT_SUFFIXES:
        if suffix_unit == unit and name.upper().endswith(suffix):
            words = _ident_words(name[: -len(suffix)])
            break
    return " ".join(words)


# --------------------------------------------------- rendering an assertion

_TIMEDELTA_UNITS = ("weeks", "days", "hours", "minutes", "seconds")
_COMPARE_WORDS: dict[type, str] = {
    ast.Eq: "is",
    ast.NotEq: "is not",
    ast.Lt: "is under",
    ast.LtE: "is at most",
    ast.Gt: "is over",
    ast.GtE: "is at least",
    ast.In: "is in",
    ast.NotIn: "is not in",
    ast.Is: "is",
    ast.IsNot: "is not",
}


class _Renderer:
    """An assertion as words: names split and lower-cased, resolved
    constants and parametrize values as their values, `timedelta(days=N)`
    as "N days", `X + timedelta(...)` as "N days after X", an enum member
    as its own name, cents as dollars."""

    def __init__(self, constants: dict[str, tuple[Any, str | None]], binding: dict[str, Any]):
        self.constants = constants
        self.binding = binding

    def expr(self, node: ast.expr) -> str:
        if isinstance(node, ast.Constant):
            return str(node.value).lower() if isinstance(node.value, bool) else str(node.value)
        if isinstance(node, ast.Name):
            if node.id in self.binding:
                return str(self.binding[node.id])
            if node.id in self.constants:
                return _value_text(*self.constants[node.id])
            return " ".join(_ident_words(node.id))
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id[:1].isupper()
                and node.attr.isupper()
            ):
                return node.attr.lower()
            return f"{self.expr(node.value)} {' '.join(_ident_words(node.attr))}"
        if isinstance(node, ast.Subscript):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                return f"{self.expr(node.value)} {key.value}"
            return ast.unparse(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            if isinstance(node.right, ast.Call) and _call_name(node.right) == "timedelta":
                word = "after" if isinstance(node.op, ast.Add) else "before"
                return f"{self.call(node.right)} {word} {self.expr(node.left)}"
            word = "plus" if isinstance(node.op, ast.Add) else "minus"
            return f"{self.expr(node.left)} {word} {self.expr(node.right)}"
        return ast.unparse(node)

    def call(self, node: ast.Call) -> str:
        name = _call_name(node)
        if name == "timedelta":
            parts = []
            for kw in node.keywords:
                if kw.arg in _TIMEDELTA_UNITS:
                    amount = self.expr(kw.value).split(" ")[0]
                    unit = kw.arg if amount != "1" else kw.arg[:-1]
                    parts.append(f"{amount} {unit}")
            return " and ".join(parts) or ast.unparse(node)
        if name == "Decimal" and node.args:
            return self.expr(node.args[0])
        if name == "len" and node.args:
            return f"the number of {self.expr(node.args[0])}"
        return " ".join(_ident_words(name))

    def compare(self, node: ast.Compare) -> str:
        if len(node.ops) != 1:
            return ast.unparse(node)
        left, right, op = node.left, node.comparators[0], type(node.ops[0])
        verb = _COMPARE_WORDS.get(op, "is")
        if (
            isinstance(left, ast.Name)
            and left.id in self.constants
            and isinstance(right, (ast.Constant, ast.Call))
        ):
            value, unit = self.constants[left.id]
            return f"the {_constant_phrase(left.id, unit)} {verb} {_value_text(value, unit)}"
        left_text, right_text = self.expr(left), self.expr(right)
        cents_literal = (
            isinstance(right, ast.Constant)
            and isinstance(right.value, int)
            and not isinstance(right.value, bool)
        )
        if cents_literal and _is_cents(left_text):
            right_text = _format_money(right.value / 100)
            left_text = " ".join(w for w in left_text.split() if w not in ("cent", "cents"))
        article = "the " if left_text[:1].isalpha() and not isinstance(left, ast.Constant) else ""
        if verb == "is" and left_text.endswith(" at"):
            return f"{article}{left_text[: -len(' at')]} {right_text}"
        return f"{article}{left_text} {verb} {right_text}"

    def assertion(self, node: ast.expr) -> str:
        if isinstance(node, ast.Compare):
            return self.compare(node)
        return f"{self.expr(node)} holds"


def _raises_clauses(func: ast.FunctionDef | None, renderer: _Renderer) -> list[str]:
    """`with pytest.raises(E): x.f(...)` checks that f raises E."""
    clauses: list[str] = []
    if func is None:
        return clauses
    for node in ast.walk(func):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Call) and _call_name(ctx) == "raises" and ctx.args:
                inner = [c for stmt in node.body for c in ast.walk(stmt) if isinstance(c, ast.Call)]
                subject = renderer.call(inner[0]) if inner else "the call"
                clauses.append(f"{subject} raises {ast.unparse(ctx.args[0])}")
    return clauses


def _action(func: ast.FunctionDef | None, skeleton: Skeleton) -> str | None:
    """The call the assertions read, rendered as "after <call>": the last
    top-level call before the first assertion whose result an assertion
    reads or which is handed a name an assertion reads."""
    if func is None:
        return None
    read: set[str] = set()
    for node in _parse_asserts(skeleton):
        read |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    action = None
    for stmt in func.body:
        if isinstance(stmt, ast.Assert):
            break
        call = getattr(stmt, "value", None)
        if not isinstance(call, ast.Call):
            continue
        targets: set[str] = set()
        if isinstance(stmt, ast.Assign):
            targets = {n.id for t in stmt.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
        args = {n.id for a in call.args for n in ast.walk(a) if isinstance(n, ast.Name)}
        if targets & read or (isinstance(stmt, ast.Expr) and args & read):
            action = " ".join(_ident_words(_call_name(call)))
    return action


_CALL_SUFFIX_WORDS = ("endpoint", "handler", "view", "route", "api")
_PARTICLES = ("out", "in", "up", "off", "on", "down")


def _participle(call_words: list[str]) -> str | None:
    """A call named for a verb and its particle as the state it leaves:
    `checkout` -> "checked out", `checkin` -> "checked in". Only a regular
    verb with a particle: anything else has no participle here."""
    if len(call_words) != 1:
        return None
    word = call_words[0]
    for particle in _PARTICLES:
        verb = word[: -len(particle)]
        if word.endswith(particle) and len(verb) >= 3:
            return f"{verb}{'d' if verb.endswith('e') else 'ed'} {particle}"
    return None


def _status_of(node: ast.expr) -> tuple[str, int] | None:
    """(name, status) for an assertion on a call's status: `first[0] == 201`,
    `third == (409, {...})`, or `status == 409` where `status` is unpacked
    from the call."""
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return None
    if not isinstance(node.ops[0], ast.Eq):
        return None
    left, right = node.left, node.comparators[0]
    if isinstance(right, ast.Tuple) and right.elts:
        right = right.elts[0]
    if not (
        isinstance(right, ast.Constant)
        and isinstance(right.value, int)
        and not isinstance(right.value, bool)
        and _is_http_status_shaped(right.value)
    ):
        return None
    if isinstance(left, ast.Subscript):
        left = left.value
    return (left.id, right.value) if isinstance(left, ast.Name) else None


def _prior_calls_condition(
    skeleton: Skeleton,
    func: ast.FunctionDef | None,
    module: ast.Module | None,
    source_lookup: SourceLookup | None,
) -> str | None:
    """The calls a refused call depends on: when the test asserts that
    several calls of one function succeed (2xx) and the next is refused
    (4xx), the earlier successes are the condition it sets up, counted and
    named by the argument that differs between the calls ("2 bikes checked
    out" for `checkout_endpoint(..., "bike-1", ...)`, `"bike-2"`; the
    parameter is `bike_id`)."""
    if func is None:
        return None
    produced: dict[str, ast.Call] = {}
    statuses: dict[int, tuple[ast.Call, int]] = {}  # by call, in assertion order
    for stmt in func.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            for target in stmt.targets:
                for name in (n for n in ast.walk(target) if isinstance(n, ast.Name)):
                    produced[name.id] = stmt.value
        elif isinstance(stmt, ast.Assert):
            found = _status_of(stmt.test)
            if found and found[0] in produced:
                call = produced[found[0]]
                statuses.setdefault(id(call), (call, found[1]))
    sequence = list(statuses.values())
    if len(sequence) < 2:
        return None
    *earlier, (last_call, last_status) = sequence
    name = _call_name(last_call)
    if not 400 <= last_status < 500:
        return None
    if any(_call_name(c) != name or not 200 <= st < 300 for c, st in earlier):
        return None
    calls = [c for c, _ in earlier] + [last_call]
    params = _callee_params(name, skeleton, module, source_lookup)
    varying = [
        i
        for i in range(min(len(c.args) for c in calls))
        if len({ast.unparse(c.args[i]) for c in calls}) == len(calls)
    ]
    if not varying or varying[0] >= len(params):
        return None
    noun_words = [w for w in _ident_words(params[varying[0]]) if w != "id"]
    call_words = [w for w in _ident_words(name) if w not in _CALL_SUFFIX_WORDS]
    participle = _participle(call_words)
    if not noun_words or participle is None:
        return None
    count = len(earlier)
    noun = " ".join(noun_words) + ("" if count == 1 else "s")
    return f"{count} {noun} {participle}"


def _condition_text(conditions: dict[str, bool]) -> str:
    return " and ".join(f"{flag} {'on' if value else 'off'}" for flag, value in conditions.items())


def _assertion_sentence(
    skeleton: Skeleton,
    func: ast.FunctionDef | None,
    constants: dict[str, tuple[Any, str | None]],
    binding: dict[str, Any],
    conditions: dict[str, bool],
    prior: str | None = None,
) -> str:
    """The statement when the name says more than the assertions check:
    every assertion, rendered, after the call they read, under the test's
    conditions and parametrize values. A bare status or count is stated as
    exactly that."""
    renderer = _Renderer(constants, binding)
    clauses: list[str] = []
    for node in _parse_asserts(skeleton):
        clause = renderer.assertion(node)
        if clause not in clauses:
            clauses.append(clause)
    clauses += _raises_clauses(func, renderer)
    if not clauses:
        return ""
    body = clauses[0] if len(clauses) == 1 else ", ".join(clauses[:-1]) + " and " + clauses[-1]
    action = _action(func, skeleton)
    text = f"after {action}, {body}" if action else body
    if conditions:
        text += f" with {_condition_text(conditions)}"
    if prior:
        text += f" {'and' if conditions else 'with'} {prior}"
    if binding:
        text += " for " + " and ".join(f"{k} {v}" for k, v in binding.items())
    return _sentence(text)


def _with_conditions(words: list[str], conditions: dict[str, bool]) -> list[str]:
    """The conditions said in the name's own words where it names the flag
    ("allowed with overflow parking" -> "... overflow parking on"), else
    appended; a name that already says "flag on/off" keeps its own."""
    out = list(words)
    lowered = [w.lower() for w in out]
    if "flag" in lowered and any(w in ("on", "off") for w in lowered):
        return out
    rest: dict[str, bool] = {}
    for flag, value in conditions.items():
        flag_words = flag.lower().split("_")
        n = len(flag_words)
        at = next(
            (i for i in range(len(lowered) - n + 1) if lowered[i : i + n] == flag_words), None
        )
        if at is None:
            rest[flag] = value
        else:
            out.insert(at + n, "on" if value else "off")
            lowered.insert(at + n, "on" if value else "off")
    if rest:
        out += ["with", _condition_text(rest)]
    return out


def _insert_values(words: list[str], clauses: list[tuple[str, Any, str | None]]) -> list[str]:
    """Each asserted constant's value in the name sentence: a number the name
    already states becomes the constant's formatted value ("cap 30" ->
    "cap $30.00"); otherwise "is <value>" goes before the name's condition
    ("The ebike surcharge is $0.10 when flag on")."""
    out = list(words)
    pending: list[str] = []
    for _, value, unit in clauses:
        numeric = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        at = next(
            (
                i
                for i, w in enumerate(out)
                if numeric is not None
                and _number_value(w) is not None
                and abs(_number_value(w) - float(numeric)) < 1e-9
            ),
            None,
        )
        if at is not None:
            out[at] = _value_text(value, unit) if unit == "usd" else out[at]
        else:
            pending.append(_value_text(value, unit))
    if not pending:
        return out
    cut = next((i for i, w in enumerate(out) if i > 0 and w.lower() in _CONDITION_WORDS), len(out))
    return ["the", *out[:cut], "is", " and ".join(pending), *out[cut:]]


def _python_statement(skeleton: Skeleton, source_lookup: SourceLookup | None) -> str:
    """The statement from what the assertions assert (module docstring,
    fifth pass)."""
    func, module = _test_function(skeleton, source_lookup)
    constants = _constant_values(skeleton, source_lookup)
    binding = _parametrize_binding(skeleton, func)
    conditions = _conditions(skeleton, func, module, source_lookup)
    prior = _prior_calls_condition(skeleton, func, module, source_lookup)
    constant_clauses = _constant_clauses(skeleton, constants)

    words = _name_words(skeleton)
    vocabulary = _test_vocabulary(skeleton, func, module, source_lookup, conditions, binding)
    vocabulary |= _outcome_support(skeleton, func)
    numbers = _numbers_in(
        _code_of(func) if func is not None else _parse_asserts(skeleton), constants
    )
    numbers |= {float(v) for v in binding.values() if isinstance(v, (int, float))}
    asserted = _numbers_in(_parse_asserts(skeleton), constants)
    constant_asserted = {float(v) for _, v, _ in constant_clauses if isinstance(v, (int, float))}

    def is_supported(word: str) -> bool:
        if _number_value(word) is not None or _STATUS_CLASS_RE.match(word):
            return _number_supported(word, numbers)
        return not _is_content(word) or _stem(word) in vocabulary

    supported = _label_words(words, [is_supported(w) for w in words], asserted, constant_asserted)

    if words and all(supported) and any(_is_content(w) for w in words):
        words = _insert_values(words, constant_clauses)
        if not constant_clauses:
            # A constant's value holds whatever the calls set up; only an
            # assertion on a call's result depends on the call's flags.
            words = _with_conditions(words, conditions)
            if prior:
                words += ["and" if words[-2:-1] == ["with"] else "with", prior]
        if binding:
            words += ["for", " and ".join(f"{k} {v}" for k, v in binding.items())]
        return _sentence(" ".join(words))
    statement = _assertion_sentence(skeleton, func, constants, binding, conditions, prior)
    if statement:
        return statement
    return _sentence(" ".join(words) + " runs without raising") if words else ""


# ------------------------------------------------------------------- top


def extract(skeleton: Skeleton, source_lookup: SourceLookup | None = None) -> Rule | None:
    """One Rule per skeleton, or None if there is nothing to extract from
    (no asserts and no docstring)."""
    service = _service_from_imports(skeleton.imports)
    category = _category(skeleton)
    constants = _resolve_constants(skeleton, source_lookup)
    flags = _flags_set(skeleton, source_lookup) if skeleton.language == "python" else set()
    # A value constant named exactly as a flag the test's calls set
    # (`EBIKE_SURCHARGE` beside `ebike_surcharge_enabled`) would claim its
    # value for the flag, which is on or off, never $0.10. The code gives the
    # value no other name, so it gets no claim (asbuilt#36); the statement
    # still states the value.
    flag_named = {name for name, _, _ in constants if name.lower() in flags}
    claims = tuple(claim for name, claim, _ in constants if name not in flag_named)

    if skeleton.language != "python":
        statement = _ts_statement(skeleton)
        detail = "; ".join(a.source for a in skeleton.asserts if a.source)
        test_source = source_lookup(skeleton.file) if source_lookup else None
        imported = _ts_imported_names(test_source) if test_source else set(skeleton.calls)
        called_imports = [c for c in skeleton.calls if c in imported]
        ts_entities = tuple(
            dict.fromkeys([e for e in ("dispatch", _ts_describe(skeleton), *called_imports) if e])
        )
        return Rule(
            node_id=skeleton.node_id,
            statement=statement,
            category=category,
            entities=ts_entities,
            claim=claims[0] if claims else None,
            claims=claims,
            detail=detail,
        )

    clauses, extra_entities = _assert_clauses(skeleton)
    detail = _join_detail(clauses)
    if not clauses and skeleton.docstring:
        detail = _clean_docstring(skeleton.docstring)
    statement = _python_statement(skeleton, source_lookup)
    if not statement and skeleton.asserts:
        statement = f"The test asserts: {skeleton.asserts[-1].source}."
    if not statement:
        return None

    fallback_claim = None if claims or flag_named else _fallback_claim(skeleton)
    if fallback_claim is not None:
        claims = (fallback_claim,)

    entities = tuple(
        dict.fromkeys(
            [
                e
                for e in (
                    service,
                    *[name for name, _, _ in constants],
                    *extra_entities,
                    (fallback_claim["entity"] if fallback_claim else None),
                    _subject_noun(skeleton),
                )
                if e
            ]
        )
    )

    return Rule(
        node_id=skeleton.node_id,
        statement=statement,
        category=category,
        entities=entities,
        claim=claims[0] if claims else None,
        claims=claims,
        detail=detail,
    )


def extract_all(skeletons: list[Skeleton], source_lookup: SourceLookup | None = None) -> list[Rule]:
    rules = []
    for skeleton in skeletons:
        rule = extract(skeleton, source_lookup)
        if rule is not None:
            rules.append(rule)
    return rules
