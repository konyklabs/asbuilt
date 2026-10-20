"""Tests for connectors.tests: skeleton collection, the rules extractor, the
evidence readers (one hand-written sample per format), and lifting on the
real fixture's planted runs (marked `fixture`, per tests/test_fixture.py's
convention)."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import connectors.tests.__main__ as main_module
from bench.build import Timeline
from bench.build import build as build_repo
from connectors.tests.__main__ import build_step_output
from connectors.tests.collect import (
    Skeleton,
    collect_from_timeline,
    collect_python,
    collect_typescript,
    cross_check,
)
from connectors.tests.evidence import (
    Outcome,
    read_junit_xml,
    read_pytest_json_report,
    read_pytest_reportlog,
    read_runs_directory,
    read_vitest_json,
)
from connectors.tests.extract_model import build_prompt, dry_run
from connectors.tests.extract_rules import extract, extract_all
from connectors.tests.lift import (
    build_contradiction_payload,
    exercised_paths,
    find_changed_constant,
    lift,
)
from tests._support import SPIKE_ROOT

FACTS_PATH = SPIKE_ROOT / "truth" / "facts.yaml"
PLANTED_RUNS_PATH = SPIKE_ROOT / "truth" / "planted-runs.yaml"

# --------------------------------------------------------- collect: Python


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_skeleton_constant_assertion(tmp_path: Path):
    _write(
        tmp_path / "tests" / "test_pricing.py",
        "from farebox.pricing import RATE\n\n"
        "def test_rate_is_fifteen_cents():\n"
        '    """The per-minute rate."""\n'
        "    assert RATE == 15\n",
    )
    skeletons = collect_python(tmp_path)
    assert len(skeletons) == 1
    s = skeletons[0]
    assert s.node_id == "tests/test_pricing.py::test_rate_is_fifteen_cents"
    assert s.docstring == "The per-minute rate."
    assert s.imports == ("farebox.pricing",)
    assert s.asserts[0].op == "=="
    assert s.asserts[0].right_literal == 15


def test_skeleton_boundary_test_no_literal_falls_back_to_docstring(tmp_path: Path):
    _write(
        tmp_path / "tests" / "test_boundary.py",
        "def test_cutoff_boundary():\n"
        '    """Exactly at the cutoff is still open; one unit later it closes."""\n'
        "    assert close(at_cutoff) == []\n"
        "    assert close(past_cutoff) == [1]\n",
    )
    skeletons = collect_python(tmp_path)
    assert len(skeletons) == 1
    assert skeletons[0].asserts[0].right_literal is None  # a List, not a Constant
    rule = extract(skeletons[0])
    # `statement` is the name sentence alone (third pass); with no literal-
    # bearing/status/error/event clause available, the docstring becomes
    # `detail` instead — same fallback role it always had, different field.
    assert rule.statement == "Cutoff boundary."
    assert rule.detail == "Exactly at the cutoff is still open; one unit later it closes."
    assert rule.claim is None


def test_skeleton_parametrized_yields_one_per_case(tmp_path: Path):
    # The assert compares against a fixed literal, not the parametrized
    # variable itself — a real per-case literal in the assert body (as
    # opposed to `== cents`, which is just a Name reference to the
    # parametrized argument, never a static literal regardless of which
    # case is running) is what a skeleton can actually see via AST.
    _write(
        tmp_path / "tests" / "test_param.py",
        "import pytest\n\n"
        '@pytest.mark.parametrize("minutes", [10, 20], ids=["ten", "twenty"])\n'
        "def test_rate_is_positive(minutes):\n"
        "    assert price(minutes) > 0\n",
    )
    skeletons = collect_python(tmp_path)
    assert [s.node_id for s in skeletons] == [
        "tests/test_param.py::test_rate_is_positive[ten]",
        "tests/test_param.py::test_rate_is_positive[twenty]",
    ]
    assert skeletons[0].parametrize_id == "ten"
    assert skeletons[0].asserts[0].right_literal == 0
    assert skeletons[1].parametrize_id == "twenty"


def test_skeleton_parametrized_approximates_ids_without_explicit_ids(tmp_path: Path):
    _write(
        tmp_path / "tests" / "test_param2.py",
        "import pytest\n\n"
        '@pytest.mark.parametrize("n", [1, 2])\n'
        "def test_n(n):\n"
        "    assert n > 0\n",
    )
    skeletons = collect_python(tmp_path)
    assert [s.node_id for s in skeletons] == [
        "tests/test_param2.py::test_n[1]",
        "tests/test_param2.py::test_n[2]",
    ]


def test_skeleton_fixture_heavy_records_parameters(tmp_path: Path):
    _write(
        tmp_path / "tests" / "test_fixtures.py",
        "def test_uses_two_fixtures(db_session, event_bus):\n    assert db_session.count == 0\n",
    )
    skeletons = collect_python(tmp_path)
    assert skeletons[0].fixtures == ("db_session", "event_bus")


def test_skeleton_skip_and_xfail_markers(tmp_path: Path):
    _write(
        tmp_path / "tests" / "test_marked.py",
        "import pytest\n\n"
        '@pytest.mark.skip(reason="not ready")\n'
        "def test_skipped():\n"
        "    assert 1 == 1\n\n"
        '@pytest.mark.xfail(reason="known bug")\n'
        "def test_expected_failure():\n"
        "    assert 1 == 2\n",
    )
    skeletons = {s.name: s for s in collect_python(tmp_path)}
    assert skeletons["test_skipped"].markers == ("skip:not ready",)
    assert skeletons["test_expected_failure"].markers == ("xfail:known bug",)


# ------------------------------------------------------ collect: TypeScript


def test_skeleton_typescript_nested_describe_it(tmp_path: Path):
    _write(
        tmp_path / "dispatch" / "test" / "sample.test.ts",
        'import { describe, it, expect } from "vitest";\n'
        'import { thing } from "../src/thing.js";\n\n'
        'describe("outer", () => {\n'
        '  it("does the thing", () => {\n'
        "    const result = thing();\n"
        "    expect(result).toBe(1);\n"
        "  });\n"
        "});\n",
    )
    skeletons = collect_typescript(tmp_path)
    assert len(skeletons) == 1
    s = skeletons[0]
    assert s.node_id == "outer > does the thing"
    assert s.language == "typescript"
    assert any("expect(result).toBe(1)" in a.source for a in s.asserts)
    assert "../src/thing.js" in s.imports


def test_skeleton_typescript_also_collects_spec_files(tmp_path: Path):
    """Review fix, point 6: `.spec.ts` is collected alongside `.test.ts` —
    the README's own documented convention, which the code didn't actually
    support until now."""
    _write(
        tmp_path / "dispatch" / "test" / "sample.spec.ts",
        'import { describe, it, expect } from "vitest";\n\n'
        'describe("outer", () => {\n'
        '  it("does the thing", () => {\n'
        "    expect(1).toBe(1);\n"
        "  });\n"
        "});\n",
    )
    skeletons = collect_typescript(tmp_path)
    assert len(skeletons) == 1
    assert skeletons[0].node_id == "outer > does the thing"


def test_cross_check_reports_differences():
    skeletons = [
        Skeleton(
            node_id="tests/x.py::test_a",
            file="tests/x.py",
            line=1,
            name="test_a",
            language="python",
        )
    ]
    collect_only_output = "tests/x.py::test_b\n1 test collected in 0.01s\n"
    diffs = cross_check(skeletons, collect_only_output)
    assert any("test_a" in d for d in diffs)
    assert any("test_b" in d for d in diffs)


# ------------------------------------------------------------ extract_rules


def test_extract_rules_real_fixture_lost_bike_fee():
    """The fourth pass's own two corrections, against the real fixture:
    `test_lost_bike_fee_150`'s trailing `_150` is KEPT in `statement`, then
    upgraded to its own primary assert's money value ("$150.00", not the
    bare "150") since that assert compares a cents-shaped expression;
    `detail` still carries the same clause in full. This test never names
    `LOST_BIKE_FEE` directly (only through the invoice total it computes),
    so no constant claim resolves — but the fallback claim now derives one
    from the test's own name instead of leaving it empty (module docstring
    point 2's addendum)."""
    system_tests = SPIKE_ROOT / "system" / "tests"
    if not system_tests.is_dir():
        pytest.skip(f"real fixture not present yet: no {system_tests}")
    skeletons = collect_python(SPIKE_ROOT / "system")
    target = next(s for s in skeletons if s.name == "test_lost_bike_fee_150")
    rule = extract(target)
    assert rule.statement == "Lost bike fee $150.00."
    assert rule.detail == "line.amount_cents - ride_charge_cents equals $150.00."
    assert rule.claim == {
        "entity": "lost bike fee",
        "attribute": "lost_bike_fee",
        "value": "$150.00",
        "unit": "usd",
    }


def test_extract_rules_category_heuristic(tmp_path: Path):
    """A status-shaped token in the test's own name (never the file path)
    is the strongest, first-checked technical-implementation signal — see
    module docstring point 5 for why file path alone can't tell apart two
    near-identical tests in the same file."""
    _write(
        tmp_path / "tests" / "test_checkin.py",
        "def test_checkin_full_station_returns_409():\n    assert status == 409\n",
    )
    _write(
        tmp_path / "tests" / "test_flags.py",
        "def test_dynamic_pricing_off_by_default():\n    assert FLAGS['x'] is False\n",
    )
    skeletons = {s.name: s for s in collect_python(tmp_path)}
    assert (
        extract(skeletons["test_checkin_full_station_returns_409"]).category
        == "technical-implementation"
    )
    assert (
        extract(skeletons["test_dynamic_pricing_off_by_default"]).category
        == "technical-implementation"
    )


def test_extract_rules_avoids_capture_cap_false_positive(tmp_path: Path):
    """ "cap" in "capture" must not be read as the money word "cap"."""
    _write(
        tmp_path / "tests" / "test_capture.py",
        "def test_capture_retries_three_times_then_fails():\n    assert attempts == 3\n",
    )
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton)
    assert rule.detail == "attempts equals 3."  # not "$3.00"


def test_extract_all_skips_nothing_with_asserts_or_docstring(tmp_path: Path):
    """A test with no asserts and no docstring still gets a (thin but
    honest) statement: with nothing asserted, it says the test ran without
    raising, which is all its pass proves (fifth pass, asbuilt#36)."""
    _write(tmp_path / "tests" / "test_empty.py", "def test_nothing():\n    pass\n")
    skeletons = collect_python(tmp_path)
    rules = extract_all(skeletons)
    assert len(rules) == 1
    assert rules[0].statement == "Nothing runs without raising."
    assert rules[0].claim is None


def test_extract_rules_name_sentence_normalises_numbers_and_ordinals(tmp_path: Path):
    """Module docstring, fifth pass: number words in a supported name
    become digits (a closed compound too, "fortyfive" is 45), a `<number>
    dollar(s)` pair folds to `$x.00`, and ordinals stay words, a position
    rather than a quantity. Each body supports its name: the variables it
    uses, the 409 a refusal, the asserted 100 cents the words beside
    "$1.00"."""
    _write(
        tmp_path / "tests" / "test_words.py",
        "def test_member_first_thirty_minutes_free():\n"
        "    free_minutes = member_free_minutes()\n"
        "    assert free_minutes == 30\n\n"
        "def test_member_first_fortyfive_minutes_free():\n"
        "    free_minutes = member_free_minutes()\n"
        "    assert free_minutes == 45\n\n"
        "def test_third_checkout_refused():\n"
        "    third = checkout()\n"
        "    assert third == (409, {'error': 'checkout_limit_reached'})\n\n"
        "def test_casual_ride_charges_one_dollar_unlock_fee():\n"
        "    amount_cents = close_casual_ride()\n"
        "    assert amount_cents == 100\n",
    )
    skeletons = {s.name: s for s in collect_python(tmp_path)}

    def _statement(name: str) -> str:
        return extract(skeletons[name]).statement

    assert _statement("test_member_first_thirty_minutes_free") == "Member first 30 minutes free."
    assert _statement("test_member_first_fortyfive_minutes_free") == "Member first 45 minutes free."
    assert _statement("test_third_checkout_refused") == "Third checkout refused."
    assert (
        _statement("test_casual_ride_charges_one_dollar_unlock_fee")
        == "Casual ride charges $1.00 unlock fee."
    )


def test_extract_rules_name_sentence_upgrades_trailing_number_to_money(tmp_path: Path):
    """Module docstring point 1's fourth-pass addendum: a trailing digit
    that names the same value a money/cents-shaped primary assert proves is
    upgraded to that assert's own properly formatted value, rather than
    staying a bare, differently-spelled duplicate of it."""
    _write(
        tmp_path / "tests" / "test_fee.py",
        "def test_lost_bike_fee_150():\n"
        "    line_amount_cents = 15000\n"
        "    ride_charge_cents = 0\n"
        "    assert line_amount_cents - ride_charge_cents == 15000\n",
    )
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton)
    assert rule.statement == "Lost bike fee $150.00."


def _lookup_for(files: dict[str, str]) -> Callable[[str], str | None]:
    def _lookup(path: str) -> str | None:
        return files.get(path)

    return _lookup


def test_extract_rules_constant_claim_from_source_and_assert_restriction(tmp_path: Path):
    """Module docstring point 2: a claim is only built from an ALL_CAPS name
    one of the test's OWN assertions mentions, resolved through the test's
    imports into a real scalar constant — a name used only in an unrelated
    setup call (here, `OTHER_HOURS`, mirroring the real fixture's
    `LOST_BIKE_HOURS` inside `test_lost_bike_fee_150`) must not become the
    claim just because it happens to be referenced somewhere in the body."""
    _write(
        tmp_path / "tests" / "test_fee.py",
        "from decimal import Decimal\n"
        "from pkg.money import FEE_AMOUNT, OTHER_HOURS\n\n"
        "def test_fee_charged():\n"
        "    now = start + OTHER_HOURS\n"
        "    assert FEE_AMOUNT == Decimal('12.50')\n",
    )
    source = 'FEE_AMOUNT = Decimal("12.50")  # USD\nOTHER_HOURS = 9  # hours\n'
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton, _lookup_for({"pkg/money.py": source}))
    assert rule.claim == {
        "entity": "FEE_AMOUNT",
        "attribute": "fee_amount",
        "value": "$12.50",
        "unit": "usd",
    }
    assert "OTHER_HOURS" not in rule.entities
    assert "FEE_AMOUNT" in rule.entities


def test_extract_rules_constant_claim_wins_over_fallback(tmp_path: Path):
    """Module docstring point 2's addendum, last line: a resolved constant
    claim is always primary — the fallback only fires when there is none."""
    _write(
        tmp_path / "tests" / "test_fee.py",
        "from decimal import Decimal\nfrom pkg.money import FEE_AMOUNT\n\n"
        "def test_fee_amount_charged_1250():\n    assert FEE_AMOUNT == Decimal('12.50')\n",
    )
    source = 'FEE_AMOUNT = Decimal("12.50")  # USD\n'
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton, _lookup_for({"pkg/money.py": source}))
    assert rule.claim["entity"] == "FEE_AMOUNT"  # not the fallback's "fee amount charged 1250"


def test_extract_rules_fallback_claim_non_money_needs_word_overlap(tmp_path: Path):
    """Module docstring point 2's fourth-pass rule: a non-money int literal
    is only trusted when the assert's own LEFT side shares a word with the
    test's name — `grace_period` does ("grace"/"period"), so this claim
    fires with a unit from the name's own words ("days")."""
    _write(
        tmp_path / "tests" / "test_grace.py",
        "def test_grace_period_7_days():\n"
        "    grace_period = compute_grace(lapsed_at, now)\n"
        "    assert grace_period == 7\n",
    )
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton)
    assert rule.claim == {
        "entity": "grace period 7 days",
        "attribute": "grace_period_7_days",
        "value": 7,
        "unit": "day",
    }


def test_extract_rules_fallback_claim_rejects_no_word_overlap(tmp_path: Path):
    """The same shape, but the compared expression ("remaining") shares no
    word with the test's own name — no claim, per the fourth-pass rule."""
    _write(
        tmp_path / "tests" / "test_grace2.py",
        "def test_grace_period_7_days():\n"
        "    remaining = compute_grace(lapsed_at, now)\n"
        "    assert remaining == 7\n",
    )
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton)
    assert rule.claim is None


def test_extract_rules_fallback_claim_rejects_http_status_and_ambiguous_money(tmp_path: Path):
    """Module docstring point 2's exclusions: an HTTP-status-shaped int
    (422) never becomes a claim value even with word overlap; a money/cents
    assert that ISN'T the test's only literal comparison, and whose own
    left side shares no word with the name, is rejected too (the real
    fixture's own "$0.15 for the 30-minute free rule" bug)."""
    _write(
        tmp_path / "tests" / "test_reject.py",
        "def test_refund_status_check():\n"
        "    refund_status = 422\n"
        "    assert refund_status == 422\n\n"
        "def test_member_first_thirty_minutes_free():\n"
        "    assert 1 == 1\n"
        "    assert body['amount_cents'] == 15\n",
    )
    skeletons = {s.name: s for s in collect_python(tmp_path)}
    assert extract(skeletons["test_refund_status_check"]).claim is None
    assert extract(skeletons["test_member_first_thirty_minutes_free"]).claim is None


def test_extract_rules_api_status_and_error_clauses(tmp_path: Path):
    """Module docstring point 1: a status+error pair folds into one API
    clause; a bare 2xx/3xx status with no error is dropped entirely (it
    carries no distinguishing content and only pollutes the statement's
    number set — see `_flush_status`'s own docstring); a tuple-shaped
    `(status, {'error': ...})` literal (not a literal `collect.py`'s
    `_literal()` recognises on its own) still contributes its status via
    the tuple-status fallback; repeats collapse to one clause each."""
    _write(
        tmp_path / "tests" / "test_api.py",
        "def test_third_checkout_refused():\n"
        "    first = checkout_endpoint()\n"
        "    second = checkout_endpoint()\n"
        "    third = checkout_endpoint()\n"
        "    assert first[0] == 201\n"
        "    assert second[0] == 201\n"
        "    assert third == (409, {'error': 'checkout_limit_reached'})\n",
    )
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton)
    assert "returns HTTP 201" not in rule.detail  # boilerplate success, dropped
    assert (
        "Checkout_endpoint returns HTTP 409 with error code checkout_limit_reached." in rule.detail
    )
    assert rule.detail.count("returns HTTP") == 1  # the 201/201 pair never duplicates either


def test_extract_rules_event_clause(tmp_path: Path):
    """Module docstring point 1: a dotted event-type literal and a
    topic/queue-named literal fold into one "publishes X to Y" clause, and
    both values become entities (needed to align with a truth fact naming
    the queue, e.g. `ride.events`)."""
    _write(
        tmp_path / "tests" / "test_events.py",
        "def test_publishes_ride_completed():\n"
        "    topic, payload = bus.published[0]\n"
        "    assert topic == 'ride.events'\n"
        "    assert payload['type'] == 'ride.completed'\n",
    )
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton)
    assert rule.detail == "Publishes ride.completed to ride.events."
    assert "ride.events" in rule.entities
    assert "ride.completed" in rule.entities
    assert rule.category == "technical-implementation"  # name contains "publishes"


def test_extract_rules_typescript_filters_to_imported_calls(tmp_path: Path):
    """Module docstring point 4: entities are `dispatch`, the describe
    name, and every CALLED identifier the file actually imports — not
    every call the tolerant line scanner sees (vitest matchers, JS
    builtins)."""
    _write(
        tmp_path / "dispatch" / "test" / "widget.test.ts",
        'import { describe, it, expect } from "vitest";\n'
        'import { isReady } from "../src/widget.js";\n\n'
        'describe("widget", () => {\n'
        '  it("is ready after three retries", () => {\n'
        "    expect(isReady()).toBe(true);\n"
        "  });\n"
        "});\n",
    )
    skeleton = collect_typescript(tmp_path)[0]
    test_source = (tmp_path / "dispatch" / "test" / "widget.test.ts").read_text()
    rule = extract(skeleton, _lookup_for({"dispatch/test/widget.test.ts": test_source}))
    assert rule.statement == "widget is ready after 3 retries."
    assert "isReady" in rule.entities
    assert "toBe" not in rule.entities  # a vitest matcher, not an import


# ------------------------------- statements from assertions (asbuilt#36)
#
# D-013: a passing test proves exactly what it asserts. One test per
# assertion shape, each named for a behaviour its assertions do not check;
# the statement must not name it.


@pytest.mark.parametrize(
    ("step", "name", "days"),
    [
        ("c1", "test_membership_lapses_3_days_after_failed_renewal", 3),
        ("c6", "test_membership_lapses_7_days_after_failed_renewal", 7),
    ],
)
def test_statement_lapse_tests_narrow_to_the_grace_period(step: str, name: str, days: int):
    """The two lapse tests assert `GRACE_DAYS`, a `GRACE` status and a
    `grace_ends_at`; nothing lapses (F-015, F-016)."""
    if not (SPIKE_ROOT / "system" / "tests").is_dir():
        pytest.skip("real fixture not present")
    timeline = Timeline(SPIKE_ROOT)
    skeleton = next(s for s in collect_from_timeline(timeline, step) if s.name == name)
    statement = extract(skeleton, main_module._source_lookup(timeline, step)).statement
    assert statement == (
        f"After handle failed renewal, the grace is {days} days, the membership status is "
        f"grace and the membership grace ends {days} days after failed at."
    )
    assert "laps" not in statement.lower()


def test_statement_constant_names_its_own_quantity(tmp_path: Path):
    """A constant: `GRACE_DAYS == 7` names the 7, so the name's "lapses"
    beside the same 7 is not a label for it."""
    _write(
        tmp_path / "tests" / "test_memberships.py",
        "from pkg.memberships import GRACE_DAYS\n\n"
        "def test_membership_lapses_7_days_after_failed_renewal():\n"
        "    assert GRACE_DAYS == 7\n",
    )
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton, _lookup_for({"pkg/memberships.py": "GRACE_DAYS = 7\n"}))
    assert rule.statement == "The grace is 7 days."


def test_statement_states_an_asserted_constant_value(tmp_path: Path):
    """A constant the name does not number: its value goes into the
    statement, which then stands on its own without the claim."""
    _write(
        tmp_path / "tests" / "test_pricing.py",
        "from decimal import Decimal\n"
        "from pkg.pricing import MEMBER_FREE_MINUTES, MEMBER_RATE\n\n"
        "def test_member_rate_after_free_minutes():\n"
        "    assert MEMBER_RATE == Decimal('0.15')\n"
        "    assert price(MEMBER_FREE_MINUTES + 10) == 150\n",
    )
    source = 'MEMBER_RATE = Decimal("0.15")\nMEMBER_FREE_MINUTES = 30\n'
    skeleton = collect_python(tmp_path)[0]
    rule = extract(skeleton, _lookup_for({"pkg/pricing.py": source}))
    assert rule.statement == "The member rate after free minutes is $0.15."


def test_statement_bare_status_says_exactly_that(tmp_path: Path):
    """A status: a 422 checks a rejection, never that anything was logged;
    a bare status yields a statement about exactly the status."""
    _write(
        tmp_path / "tests" / "test_refunds.py",
        "def test_refund_rejected_and_logged():\n"
        "    status, body = create_refund()\n"
        "    assert status == 422\n\n"
        "def test_refund_rejected():\n"
        "    status, body = create_refund()\n"
        "    assert status == 422\n",
    )
    lookup = _lookup_for(
        {"tests/test_refunds.py": (tmp_path / "tests/test_refunds.py").read_text()}
    )
    skeletons = {s.name: s for s in collect_python(tmp_path)}
    logged = extract(skeletons["test_refund_rejected_and_logged"], lookup).statement
    assert logged == "After create refund, the status is 422."
    assert extract(skeletons["test_refund_rejected"], lookup).statement == "Refund rejected."


def test_statement_computed_date(tmp_path: Path):
    """A computed date: `X == FAILED_AT + timedelta(days=7)` is "7 days
    after failed at"; the name's week and email are not checked."""
    _write(
        tmp_path / "tests" / "test_grace.py",
        "from datetime import timedelta\n\n"
        "def test_grace_ends_a_week_after_failure_and_emails_rider():\n"
        "    membership = fail_renewal(FAILED_AT)\n"
        "    assert membership.grace_ends_at == FAILED_AT + timedelta(days=7)\n",
    )
    lookup = _lookup_for({"tests/test_grace.py": (tmp_path / "tests/test_grace.py").read_text()})
    statement = extract(collect_python(tmp_path)[0], lookup).statement
    assert statement == "After fail renewal, the membership grace ends 7 days after failed at."


def test_statement_boundary(tmp_path: Path):
    """A boundary: closed one minute past 24 hours, open one minute short;
    no fine is asserted."""
    _write(
        tmp_path / "tests" / "test_lost.py",
        "from datetime import timedelta\n\n"
        "def test_ride_closed_as_lost_and_fined_after_24_hours():\n"
        "    closed = close_lost_rides(START + timedelta(hours=24, minutes=1))\n"
        "    assert closed == ['ride-1']\n"
        "    still_open = close_lost_rides(START + timedelta(hours=24) - timedelta(minutes=1))\n"
        "    assert still_open == []\n",
    )
    lookup = _lookup_for({"tests/test_lost.py": (tmp_path / "tests/test_lost.py").read_text()})
    statement = extract(collect_python(tmp_path)[0], lookup).statement
    assert statement == (
        "After close lost rides, the closed is ['ride-1'] and the still open is []."
    )
    assert "fine" not in statement


def test_statement_parametrised_case_states_its_values(tmp_path: Path):
    """A parametrised case: each case states its own value, and the name's
    points are never asserted."""
    _write(
        tmp_path / "tests" / "test_member.py",
        "import pytest\n\n"
        "@pytest.mark.parametrize('minutes', [10, 20])\n"
        "def test_member_rides_free_and_earn_points(minutes):\n"
        "    assert member_price(minutes) == 0\n",
    )
    test_source = (tmp_path / "tests" / "test_member.py").read_text()
    lookup = _lookup_for({"tests/test_member.py": test_source})
    statements = [extract(s, lookup).statement for s in collect_python(tmp_path)]
    assert statements == [
        "The member price is 0 for minutes 10.",
        "The member price is 0 for minutes 20.",
    ]


def test_statement_states_the_flag_condition_its_assertions_depend_on(tmp_path: Path):
    """The module's tests set `overflow_parking` both ways, so each
    statement carries its own setting; `dynamic_pricing`, off in every
    test, is background and is not stated."""
    source = (
        "def test_checkin_at_full_station_refused():\n"
        "    station = full_station()\n"
        "    status, body = checkin_endpoint(station, overflow_parking_enabled=False,"
        " dynamic_pricing_enabled=False)\n"
        "    assert status == 409\n\n"
        "def test_checkin_at_full_station_allowed_with_overflow_parking():\n"
        "    station = full_station()\n"
        "    status, body = checkin_endpoint(station, overflow_parking_enabled=True,"
        " dynamic_pricing_enabled=False)\n"
        "    assert status == 200\n"
    )
    _write(tmp_path / "tests" / "test_checkin.py", source)
    lookup = _lookup_for({"tests/test_checkin.py": source})
    statements = {s.name: extract(s, lookup).statement for s in collect_python(tmp_path)}
    assert statements == {
        "test_checkin_at_full_station_refused": (
            "Checkin at full station refused with overflow_parking off."
        ),
        "test_checkin_at_full_station_allowed_with_overflow_parking": (
            "Checkin at full station allowed with overflow parking on."
        ),
    }


def test_statement_states_the_calls_the_refused_one_depends_on(tmp_path: Path):
    """A setup condition: two check-outs succeed (201), the third is refused
    (409). The two earlier successes are what the refusal depends on,
    counted and named by the argument that differs between the calls
    (`bike_id`), so the statement says so."""
    source = (
        "from pkg.api import checkout_endpoint\n\n"
        "def test_third_checkout_refused():\n"
        "    first = checkout_endpoint(session, rider_id, 'bike-1')\n"
        "    second = checkout_endpoint(session, rider_id, 'bike-2')\n"
        "    third = checkout_endpoint(session, rider_id, 'bike-3')\n"
        "    assert first[0] == 201\n"
        "    assert second[0] == 201\n"
        "    assert third == (409, {'error': 'checkout_limit_reached'})\n"
    )
    _write(tmp_path / "tests" / "test_checkout.py", source)
    lookup = _lookup_for(
        {
            "tests/test_checkout.py": source,
            "pkg/api.py": "def checkout_endpoint(session, rider_id, bike_id):\n    pass\n",
        }
    )
    rule = extract(collect_python(tmp_path)[0], lookup)
    assert rule.statement == "Third checkout refused with 2 bikes checked out."


def test_claim_never_names_a_flag_for_a_value_constant(tmp_path: Path):
    """A claim entity: `EBIKE_SURCHARGE` is a dollar value, but its name is
    the flag the test's own call sets (`ebike_surcharge_enabled`), so a
    claim on it would give the flag a value of $0.10. It gets no claim and
    no fallback claim; the statement still states the value, and a constant
    named for no flag keeps its claim."""
    source = (
        "from decimal import Decimal\n"
        "from pkg.pricing import EBIKE_SURCHARGE, MEMBER_RATE, price_ride\n\n"
        "def test_ebike_surcharge_when_flag_on():\n"
        "    assert EBIKE_SURCHARGE == Decimal('0.10')\n"
        "    with_flag = price_ride(10, True)\n"
        "    without_flag = price_ride(10, False)\n"
        "    assert with_flag - without_flag == 100\n\n"
        "def test_member_rate():\n"
        "    assert MEMBER_RATE == Decimal('0.15')\n"
    )
    pricing = (
        'EBIKE_SURCHARGE = Decimal("0.10")\n'
        'MEMBER_RATE = Decimal("0.15")\n\n'
        "def price_ride(minutes, ebike_surcharge_enabled):\n    pass\n"
    )
    _write(tmp_path / "tests" / "test_pricing.py", source)
    lookup = _lookup_for({"tests/test_pricing.py": source, "pkg/pricing.py": pricing})
    rules = {s.name: extract(s, lookup) for s in collect_python(tmp_path)}
    ebike = rules["test_ebike_surcharge_when_flag_on"]
    assert ebike.claim is None
    assert ebike.claims == ()
    assert ebike.statement == "The ebike surcharge is $0.10 when flag on."
    assert rules["test_member_rate"].claim["entity"] == "MEMBER_RATE"


# ----------------------------------------------------------- extract_model


def test_extract_model_dry_run_makes_no_call_and_counts_tokens(tmp_path: Path):
    _write(
        tmp_path / "tests" / "test_x.py",
        "def test_x():\n    assert 1 == 1\n",
    )
    skeletons = collect_python(tmp_path)
    rules = {r.node_id: r for r in extract_all(skeletons)}
    result = dry_run(skeletons, rules)
    assert result.prompts == 1
    assert result.estimated_input_tokens > 0
    assert result.estimated_dollars > 0


def test_extract_model_build_prompt_never_exceeds_the_assertion():
    skeleton = Skeleton(
        node_id="t::x", file="t.py", line=1, name="test_x", language="python", docstring="doc"
    )
    prompt = build_prompt(skeleton, None)
    assert "doc" in prompt
    assert "Rules-extractor guess" not in prompt  # no rule given


# --------------------------------------------------------------- evidence


def test_read_pytest_json_report(tmp_path: Path):
    report = tmp_path / "pytest-c1.json"
    report.write_text(
        json.dumps(
            {
                "metadata": {"step": "c1", "commit": "abc123"},
                "tests": [{"nodeid": "tests/x.py::test_a", "outcome": "passed"}],
            }
        )
    )
    outcomes = read_pytest_json_report(report)
    assert outcomes == [
        Outcome(
            node_id="tests/x.py::test_a",
            outcome="passed",
            step="c1",
            commit="abc123",
            attempt=1,
            run_id="pytest-c1",
        )
    ]


def test_read_pytest_reportlog_sample(tmp_path: Path):
    """A hand-written pytest-reportlog sample (JSON lines), labelled: this
    is the real shape pytest-reportlog writes for a TestReport event, with
    only the fields this reader uses kept."""
    lines = [
        json.dumps(
            {
                "$report_type": "TestReport",
                "nodeid": "tests/x.py::test_a",
                "when": "setup",
                "outcome": "passed",
            }
        ),
        json.dumps(
            {
                "$report_type": "TestReport",
                "nodeid": "tests/x.py::test_a",
                "when": "call",
                "outcome": "passed",
            }
        ),
        json.dumps(
            {
                "$report_type": "TestReport",
                "nodeid": "tests/x.py::test_b",
                "when": "setup",
                "outcome": "skipped",
            }
        ),
        json.dumps(
            {"$report_type": "CollectReport", "nodeid": "tests/x.py"}
        ),  # ignored: not a TestReport
    ]
    path = tmp_path / "reportlog.jsonl"
    path.write_text("\n".join(lines) + "\n")

    outcomes = {
        o.node_id: o.outcome for o in read_pytest_reportlog(path, step="c2", commit="deadbeef")
    }
    assert outcomes == {"tests/x.py::test_a": "passed", "tests/x.py::test_b": "skipped"}


def test_read_junit_xml_sample(tmp_path: Path):
    """A hand-written JUnit XML sample (pytest's own --junitxml shape:
    <testsuites><testsuite><testcase>), labelled, with a <properties><
    property name="commit"> for the commit."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="3">
    <properties>
      <property name="commit" value="cafef00d"/>
    </properties>
    <testcase classname="tests.x" name="test_pass" time="0.01"/>
    <testcase classname="tests.x" name="test_fail" time="0.01">
      <failure message="assert 1 == 2">AssertionError</failure>
    </testcase>
    <testcase classname="tests.x" name="test_skip" time="0.00">
      <skipped message="not ready"/>
    </testcase>
  </testsuite>
</testsuites>"""
    path = tmp_path / "junit.xml"
    path.write_text(xml)

    outcomes = {o.node_id: (o.outcome, o.commit) for o in read_junit_xml(path)}
    assert outcomes == {
        "tests.x::test_pass": ("passed", "cafef00d"),
        "tests.x::test_fail": ("failed", "cafef00d"),
        "tests.x::test_skip": ("skipped", "cafef00d"),
    }


def test_read_junit_xml_generic_shape_and_sidecar_commit(tmp_path: Path):
    """The generic bare-<testsuite> shape, with no <properties> at all —
    the commit comes from the sidecar file instead."""
    xml = """<testsuite name="generic" tests="1">
  <testcase classname="x" name="test_a"/>
</testsuite>"""
    path = tmp_path / "generic.xml"
    path.write_text(xml)
    (tmp_path / "generic.xml.commit.txt").write_text("sidecarsha\n")

    outcomes = read_junit_xml(path)
    assert outcomes[0].commit == "sidecarsha"
    assert outcomes[0].outcome == "passed"


def test_read_vitest_json_reconstructs_fullname_not_raw_field(tmp_path: Path):
    data = {
        "metadata": {"step": "c1", "commit": "abc"},
        "testResults": [
            {
                "assertionResults": [
                    {
                        "ancestorTitles": ["suite"],
                        "title": "does the thing",
                        "fullName": "suite does the thing",  # single space, must be ignored
                        "status": "passed",
                    }
                ]
            }
        ],
    }
    path = tmp_path / "vitest-c1.json"
    path.write_text(json.dumps(data))
    outcomes = read_vitest_json(path)
    assert outcomes[0].node_id == "suite > does the thing"


def test_read_runs_directory_dispatches_by_shape(tmp_path: Path):
    (tmp_path / "pytest-c1.json").write_text(
        json.dumps({"metadata": {"step": "c1"}, "tests": [{"nodeid": "t::a", "outcome": "passed"}]})
    )
    (tmp_path / "vitest-c1.json").write_text(
        json.dumps(
            {
                "metadata": {"step": "c1"},
                "testResults": [
                    {"assertionResults": [{"ancestorTitles": [], "title": "b", "status": "passed"}]}
                ],
            }
        )
    )
    (tmp_path / "pytest-c1-rerun.json").write_text(
        json.dumps({"metadata": {"step": "c1"}, "tests": [{"nodeid": "t::a", "outcome": "passed"}]})
    )
    outcomes = read_runs_directory(tmp_path)
    assert {o.run_id for o in outcomes} == {"pytest-c1", "vitest-c1", "pytest-c1-rerun"}
    assert next(o.attempt for o in outcomes if o.run_id == "pytest-c1-rerun") == 2


# ------------------------------------------------------------------- lift


def test_exercised_paths_python():
    skeleton = Skeleton(
        node_id="t::x",
        file="tests/unit/test_pricing.py",
        line=1,
        name="test_x",
        language="python",
        imports=("farebox.pricing", "pytest", "__future__"),
    )
    paths = exercised_paths(skeleton)
    assert "farebox/pricing.py" in paths
    assert "tests/unit/test_pricing.py" in paths
    assert not any("pytest" in p for p in paths)


def test_exercised_paths_typescript_normalises_relative_import():
    """Review fix: "dispatch/test/../src/rules/stormPause.ts" (the raw join
    of the test's own directory and its own relative import) is never a
    path `git diff --name-only` would report — only the normalised
    "dispatch/src/rules/stormPause.ts" is, so the staleness check in
    `lift()` must compare against that form, not the un-collapsed one."""
    skeleton = Skeleton(
        node_id="t::x",
        file="dispatch/test/stormPause.test.ts",
        line=1,
        name="x",
        language="typescript",
        imports=("../src/rules/stormPause.js",),
    )
    paths = exercised_paths(skeleton)
    assert "dispatch/src/rules/stormPause.ts" in paths
    assert not any(".." in p for p in paths)


def test_lift_contradiction_persists_then_closes(tmp_path: Path):
    """Review fix, point 3: a demotion opened at "s2" persists at "s3" (no
    run recorded there at all — the test simply wasn't rerun) with the SAME
    `opened_step` and the failing run id carried from "s2", then closes
    outright once "s4" records a pass. None of these target steps ever
    needs `git diff` (a demotion never reaches the backward search; a pass
    AT the target step itself short-circuits it), so a real repo isn't
    needed here."""
    skeleton = Skeleton(
        node_id="tests/x.py::test_x", file="tests/x.py", line=1, name="test_x", language="python"
    )
    step_order = ["s1", "s2", "s3", "s4"]
    commits = {s: {"sha": s} for s in step_order}
    repo = tmp_path  # never touched: see the docstring above
    outcomes_by_step = {
        "s1": [Outcome("tests/x.py::test_x", "passed", "s1", None, 1, "run-s1")],
        "s2": [Outcome("tests/x.py::test_x", "failed", "s2", None, 1, "run-s2")],
        "s4": [Outcome("tests/x.py::test_x", "passed", "s4", None, 1, "run-s4")],
    }

    demoted = lift(skeleton, outcomes_by_step, step_order, "s2", repo, commits)
    assert demoted.tier == "code"
    assert demoted.contradiction_candidate.opened_step == "s2"
    assert demoted.contradiction_candidate.failing_run_id == "run-s2"

    carried = lift(skeleton, outcomes_by_step, step_order, "s3", repo, commits)
    assert carried.tier == "code"
    assert carried.contradiction_candidate.opened_step == "s2"  # inherited, not reset to "s3"
    assert carried.contradiction_candidate.failing_run_id == "run-s2"  # no fresher run to update it

    closed = lift(skeleton, outcomes_by_step, step_order, "s4", repo, commits)
    assert closed.tier == "executed"
    assert closed.contradiction_candidate is None


def test_lift_never_imports_truth_or_yaml_at_runtime():
    """lift.py's module docstring promises it never reads truth/
    planted-runs.yaml at runtime (only this package's own tests do) — a
    grep of everything after the module docstring is the simplest honest
    check that no such import or open crept in. A code *comment* is free to
    name truth/planted-runs.yaml in prose (explaining the flaky rule's
    provenance) without violating the promise — only an actual read does."""
    import connectors.tests.lift as lift_module

    source = Path(inspect.getsourcefile(lift_module)).read_text()
    _, _, body = source.partition('"""')
    _, _, body = body.partition('"""')
    assert "import yaml" not in body
    assert "open(" not in body
    code_lines = [line for line in body.splitlines() if not line.strip().startswith("#")]
    assert "truth" not in "\n".join(code_lines).lower()


def _fake_model_client_factory():
    """A fake `client_factory` (the `anthropic`-shaped call convention
    `extract_with_model` always uses regardless of provider) that always
    returns the same canned statement, distinguishable from any real
    rules-extractor guess — used to prove `--limit` behaviour without
    calling any real provider."""

    class _Messages:
        def create(self, **kwargs):
            payload = {
                "statement": "Model said so.",
                "category": "business-logic",
                "entities": [],
                "claim": None,
            }
            usage = SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
            return SimpleNamespace(
                usage=usage, content=[SimpleNamespace(type="tool_use", input=payload)]
            )

    class _Client:
        def __init__(self):
            self.messages = _Messages()

    return _Client()


@pytest.mark.fixture
def test_build_step_output_limit_keeps_full_output_and_only_calls_model_for_n(
    monkeypatch: pytest.MonkeyPatch,
):
    """Review fix, point 3: `--limit N` caps only how many skeletons get a
    real model call — the written output still covers every test in the
    step (facts/counts/candidates), not just N. Reproduces the bug directly:
    before the fix, `skeletons` itself was rebound to the capped list, so
    the facts loop only ever saw N tests at all."""
    fixture_root = SPIKE_ROOT
    facts_path = fixture_root / "truth" / "facts.yaml"
    if not facts_path.is_file():
        pytest.skip(f"real fixture not present yet: no {facts_path}")
    build_out = fixture_root / "build" / "test-connector-limit"
    commits = build_repo(fixture_root, build_out)
    repo = build_out / "repo"
    step_order = list(commits)
    outcomes_by_step: dict[str, list[Outcome]] = {}
    for o in read_runs_directory(fixture_root / "runs"):
        if o.step:
            outcomes_by_step.setdefault(o.step, []).append(o)

    full_output = build_step_output(
        fixture_root, "c6", repo, commits, outcomes_by_step, step_order, extractor="rules"
    )
    monkeypatch.setitem(main_module.PROVIDERS, "claude-code", _fake_model_client_factory)
    limited_output = build_step_output(
        fixture_root,
        "c6",
        repo,
        commits,
        outcomes_by_step,
        step_order,
        extractor="model",
        limit=3,
    )

    assert len(limited_output["facts"]) == len(full_output["facts"])  # every test, not just 3
    model_facts = [f for f in limited_output["facts"] if f["statement"] == "Model said so."]
    assert len(model_facts) == 3


@pytest.mark.fixture
def test_main_limit_writes_a_separate_file_without_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Review fix, point 3: a `--limit`ed smoke-test run must never
    overwrite a full run's own `tests-<step>.json` — it writes
    `tests-<step>-limit<N>.json` instead, only when `--out` wasn't given."""
    fixture_root = SPIKE_ROOT
    if not (fixture_root / "truth" / "facts.yaml").is_file():
        pytest.skip(f"real fixture not present yet: no {fixture_root}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(main_module.PROVIDERS, "claude-code", _fake_model_client_factory)

    assert (
        main_module.main(["--fixture", str(fixture_root), "--step", "c6", "--extractor", "rules"])
        == 0
    )
    full_path = tmp_path / "build" / "connector" / "tests-c6.json"
    assert full_path.is_file()
    full_before = full_path.read_text()

    assert (
        main_module.main(
            ["--fixture", str(fixture_root), "--step", "c6", "--extractor", "model", "--limit", "2"]
        )
        == 0
    )
    limited_path = tmp_path / "build" / "connector" / "tests-c6-limit2.json"
    assert limited_path.is_file()
    assert full_path.read_text() == full_before  # untouched by the limited run


@pytest.mark.fixture
def test_fact_citations_carry_sha_and_step():
    """Review fix, point 5: a Fact's code citation writes `version` as the
    step's SHA (README and the CLI docstring's own promise — the scorer
    accepts either a step id or a SHA, but only the SHA was ever documented
    as the real shape), with `step` written alongside for a human reader."""
    fixture_root = SPIKE_ROOT
    facts_path = fixture_root / "truth" / "facts.yaml"
    if not facts_path.is_file():
        pytest.skip(f"real fixture not present yet: no {facts_path}")
    build_out = fixture_root / "build" / "test-connector-citations"
    commits = build_repo(fixture_root, build_out)
    repo = build_out / "repo"
    step_order = list(commits)
    outcomes_by_step: dict[str, list[Outcome]] = {}
    for o in read_runs_directory(fixture_root / "runs"):
        if o.step:
            outcomes_by_step.setdefault(o.step, []).append(o)

    output = build_step_output(fixture_root, "c6", repo, commits, outcomes_by_step, step_order)
    fact = output["facts"][0]
    code_citation = next(c for c in fact["citations"] if c["document"].startswith("code/"))
    assert code_citation["version"] == commits["c6"]["sha"]
    assert code_citation["step"] == "c6"


@pytest.mark.fixture
def test_lift_planted_runs_on_the_real_fixture():
    if not PLANTED_RUNS_PATH.is_file() or not FACTS_PATH.is_file():
        pytest.skip(f"real fixture not present yet: no {PLANTED_RUNS_PATH}")

    planted = yaml.safe_load(PLANTED_RUNS_PATH.read_text())
    fixture_root = SPIKE_ROOT
    build_out = fixture_root / "build" / "test-connector-lift"
    commits = build_repo(fixture_root, build_out)
    repo = build_out / "repo"
    step_order = list(commits)
    timeline = Timeline(fixture_root)

    outcomes = read_runs_directory(fixture_root / "runs")
    outcomes_by_step: dict[str, list[Outcome]] = {}
    for o in outcomes:
        if o.step:
            outcomes_by_step.setdefault(o.step, []).append(o)

    def skeleton_for(node_id: str, step: str) -> Skeleton:
        skeletons = collect_from_timeline(timeline, step)
        return next(s for s in skeletons if s.node_id == node_id)

    p1 = next(e for e in planted["planted"] if e["id"] == "P-1")
    p2 = next(e for e in planted["planted"] if e["id"] == "P-2")
    p3 = next(e for e in planted["planted"] if e["id"] == "P-3")

    # P-1: demoted at c5, with a contradiction candidate.
    s1 = skeleton_for(p1["test"], "c5")
    lifted1 = lift(s1, outcomes_by_step, step_order, "c5", repo, commits)
    assert lifted1.tier == "code"
    assert lifted1.contradiction_candidate is not None

    # asbuilt#8 second pass: the full {a, b, winner, reason} payload the
    # scorer reads (module docstring's point 6) — `b` names the CURRENT
    # code value ($150.00, from farebox/pricing.py's LOST_BIKE_FEE at c5),
    # correctly disambiguated from SINGLE_RIDE_CAP (which changed in the
    # very same file at the very same step, per the real fixture) by name
    # overlap with the demoted test's own name.
    rule1 = extract(s1)
    assert lifted1.contradiction_candidate.opened_step == "c5"
    good_step = step_order[step_order.index("c5") - 1]
    changed = find_changed_constant(s1, good_step, "c5", timeline)
    assert changed is not None
    assert changed[0] == "LOST_BIKE_FEE"  # not SINGLE_RIDE_CAP, also changed c4->c5
    payload = build_contradiction_payload(
        s1, rule1, lifted1.contradiction_candidate, step_order, timeline, commits
    )
    assert payload is not None
    assert payload["b"]["claim"] == {
        "entity": "LOST_BIKE_FEE",
        "attribute": "lost_bike_fee",
        "value": "$150.00",
        "unit": "usd",
    }
    assert payload["b"]["citations"][0]["document"] == "code/farebox/pricing.py"
    assert payload["b"]["citations"][0]["version"] == commits["c5"]["sha"]  # SHA, not "c5"
    assert payload["b"]["citations"][0]["step"] == "c5"
    assert payload["winner"] is payload["b"]
    assert "pytest-c5" in payload["reason"]

    # P-2: never lifts (always skipped) at any step it exists.
    s2 = skeleton_for(p2["test"], "c6")
    lifted2 = lift(s2, outcomes_by_step, step_order, "c6", repo, commits)
    assert lifted2.tier == "code"

    # P-3: flaky at c6, but the statement is still executed from c5 (the
    # latest conclusive step) since the code is unchanged since then.
    s3 = skeleton_for(p3["test"], "c6")
    lifted3 = lift(s3, outcomes_by_step, step_order, "c6", repo, commits)
    assert lifted3.flaky is True
    assert lifted3.tier == "executed"
    assert lifted3.valid_from_step == "c5"
