"""The deterministic ("rules") extractor: skeleton -> one candidate statement,
never past what the test's assertion actually proves (D-013: "a passing test
proves exactly what it asserted, extraction never generalises past the
assertion").

**Second pass** (asbuilt#8 integration review): the first pass templated a
Python statement from a single chosen literal (the last literal-bearing
assert), which guessed wrong often enough to be a majority of the returned
false positives. This pass never picks one literal arbitrarily:

1. **Third pass correction**: `Rule.statement` is ONE sentence, built only
   from the test's own *name* (`test_` stripped, underscores split, number
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
2. Claims come from module-level constants, not the primary-literal guess:
   every ALL_CAPS name the test's body references that resolves (through the
   test's own imports, followed one hop into the source tree via a caller-
   supplied `source_lookup`) to a scalar assignment becomes one claim
   (`entity` = the constant's own name, `attribute` = the constant's name
   lower-cased, `value` read from the source at the given step, `unit`
   inferred from the name and value type — see `infer_unit`). The first
   resolved constant's claim is `Rule.claim`; the rest are `Rule.claims`
   (the scorer only reads the singular field; the list is carried for
   completeness and for a future claim-first matcher). A test that
   references no resolvable constant carries no claim at all — this is a
   known, accepted gap for compound end-to-end tests that only prove a
   value through *behaviour* (e.g. a boundary probe), never by naming the
   constant; that gap is exactly the model extractor's job, not this one's.
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

from connectors.tests.collect import AssertExpr, Skeleton

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
    unrelated clause words piled on. `statement` is now the name sentence
    (Python) or "<describe> <it title>." (Vitest) alone; every assertion
    clause, the API/error clause and the event clause move to `detail` — a
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


def _ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _test_subject_phrase(skeleton: Skeleton) -> str:
    """The test's own name, humanised, trailing example value dropped —
    "lost bike fee" from `test_lost_bike_fee_100` — used as the entity/
    attribute source for the fallback claim (module docstring point 2's
    "third pass" addendum) and as the money-substitution context for
    `_name_sentence` below. Not the same as `_subject_noun` (the FILE's own
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


def _name_sentence(skeleton: Skeleton) -> str:
    """Sentence 1: the test's own name, humanised — see module docstring
    point 1. A trailing bare numeric token (`..._150`) is now KEPT as a
    plain digit ("Lost bike fee 150.") unless the test's own primary
    literal-bearing assert compares a money or cents-shaped expression, in
    which case the digit is replaced by that assert's own properly
    formatted money value ("Lost bike fee $150.00.") — the two are the same
    number by the fixture's own naming convention, and only the money form
    is what the second sentence's own clause repeats, so keeping the bare
    digit too would add a duplicate, differently-spelled number for no gain
    (third pass correction: the earlier version dropped the digit
    unconditionally, which meant a test whose only literal-bearing assert
    isn't itself money-shaped — a plain "$150.00 vs $100.00" example that
    happens to route through a computed expression — lost its number
    entirely)."""
    name = skeleton.name
    if name.startswith("test_"):
        name = name[len("test_") :]
    tokens = [t for t in name.split("_") if t]

    words: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in _NUMBER_WORDS:
            words.append(str(_NUMBER_WORDS[low]))
        elif low in _ORDINAL_WORDS:
            n = _ORDINAL_WORDS[low]
            words.append(f"{n}{_ordinal_suffix(n)}")
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

    text = " ".join(merged).strip()
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


def _fallback_claim(skeleton: Skeleton) -> dict[str, Any] | None:
    """Module docstring point 2's third-pass addendum: when no ALL_CAPS
    constant resolves (`_resolve_constants` returned nothing — kept as the
    PRIMARY claim whenever it does find one) but the test's own primary
    (last) literal-bearing assert compares a COMPUTED expression against a
    literal, a claim is still derived rather than left empty — entity and
    attribute from the test's own name (`_test_subject_phrase`, e.g. "lost
    bike fee"; the alias table resolves a name like this the same way it
    resolves a constant name), value from the literal (cents/100 when the
    non-literal side names "cents"; a `Decimal("x")`-wrapped string literal
    read as its float, same conversion `_format_literal` already does),
    unit "usd" for a money/cents context, else minute/day/hour/second from
    the test's own name, else "count"."""
    primary = _primary_literal_assert(skeleton)
    if primary is None:
        return None
    literal, other_side = _literal_side(primary)
    if isinstance(literal, bool) or not isinstance(literal, (int, float, str)):
        return None
    subject_phrase = _test_subject_phrase(skeleton)
    cents = _is_cents(other_side)
    money = cents or _is_money_context(other_side, subject_phrase)
    display, numeric = _format_literal(literal, money=money, cents=cents)
    value: Any = display if money else numeric
    unit = (
        "usd"
        if money
        else (_unit_from_words(subject_phrase) or _unit_from_words(other_side) or "count")
    )
    return {
        "entity": subject_phrase,
        "attribute": subject_phrase.replace(" ", "_"),
        "value": value,
        "unit": unit,
    }


# ------------------------------------------------------------------- top


def extract(skeleton: Skeleton, source_lookup: SourceLookup | None = None) -> Rule | None:
    """One Rule per skeleton, or None if there is nothing to extract from
    (no asserts and no docstring)."""
    service = _service_from_imports(skeleton.imports)
    category = _category(skeleton)
    constants = _resolve_constants(skeleton, source_lookup)
    claims = tuple(claim for _, claim, _ in constants)

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

    sentence1 = _name_sentence(skeleton)
    clauses, extra_entities = _assert_clauses(skeleton)
    detail = _join_detail(clauses)
    if not clauses and skeleton.docstring:
        detail = _clean_docstring(skeleton.docstring)
    statement = sentence1
    if not statement and skeleton.asserts:
        statement = f"The test asserts: {skeleton.asserts[-1].source}."
    if not statement:
        return None

    fallback_claim = None if claims else _fallback_claim(skeleton)
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
