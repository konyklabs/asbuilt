from __future__ import annotations

import json
import shutil
from pathlib import Path

from bench.build import Timeline
from bench.truth import (
    Carrier,
    Fidelities,
    TruthFact,
    _check_code_carrier,
    _check_fidelity,
    _check_run_carrier,
    check_consistency,
    github_slugify,
    load_aliases,
    load_contradictions,
    load_entities,
    load_facts,
    load_fidelities,
    load_stale,
    load_truth,
    playwright_outcomes,
    resolve_step,
    summarize,
)
from tests._support import MINI_ROOT


def test_load_entities():
    entities = load_entities(MINI_ROOT / "truth" / "entities.yaml")
    assert set(entities) == {
        "E-farebox",
        "E-rule-member-free-minutes",
        "E-team-fares",
        "E-team-ops",
    }
    assert entities["E-rule-member-free-minutes"].owner == "E-farebox"


def test_load_facts_valid_from_and_valid_to():
    facts = load_facts(MINI_ROOT / "truth" / "facts.yaml")
    assert len(facts) == 13
    assert facts["F-001"].tier == "executed"
    assert facts["F-001"].valid_to == "c2"
    assert facts["F-002"].valid_from == "c2"
    assert facts["F-002"].valid_to == "c4"
    assert facts["F-003"].valid_from == "c4"
    assert facts["F-003"].valid_to is None
    # F-001 and F-003 share a statement and a code document at different
    # versions — the case score.py's version disambiguation exists for.
    assert facts["F-001"].statement == facts["F-003"].statement
    assert facts["F-001"].carriers[0].document == facts["F-003"].carriers[0].document
    assert facts["F-001"].carriers[0].version != facts["F-003"].carriers[0].version


def test_load_contradictions_and_stale():
    contradictions = load_contradictions(MINI_ROOT / "truth" / "contradictions.yaml")
    stale = load_stale(MINI_ROOT / "truth" / "stale.yaml")
    assert contradictions["X-001"].facts == ("F-005", "F-003")
    assert contradictions["X-001"].winner == "F-003"
    assert stale["S-001"].changed_by == "c4"
    assert stale["S-001"].states == "F-005"


def test_load_truth_bundles_all_four():
    truth = load_truth(MINI_ROOT / "truth")
    assert len(truth.entities) == 4
    assert len(truth.facts) == 13
    assert len(truth.contradictions) == 1
    assert len(truth.stale) == 1


def test_load_aliases():
    aliases = load_aliases(MINI_ROOT / "truth" / "aliases.yaml")
    assert set(aliases) == {
        "E-farebox",
        "E-rule-member-free-minutes",
        "E-team-fares",
        "E-team-ops",
    }
    assert aliases["E-farebox"].name == "farebox"
    assert "fare box" in aliases["E-farebox"].aliases


def test_load_aliases_tolerates_missing_file(tmp_path: Path):
    assert load_aliases(tmp_path / "no-such-aliases.yaml") == {}


def test_load_truth_includes_aliases():
    truth = load_truth(MINI_ROOT / "truth")
    assert len(truth.aliases) == 4
    assert truth.aliases["E-rule-member-free-minutes"].name == "member-free-minutes"


def test_resolve_step():
    commits = {"c1": {"sha": "deadbeef", "date": "2026-01-01T09:00:00-05:00", "message": "m"}}
    assert resolve_step("c1", commits)["sha"] == "deadbeef"
    try:
        resolve_step("c99", commits)
    except KeyError as exc:
        assert "c99" in str(exc)
    else:
        raise AssertionError("resolve_step should raise KeyError for an unknown step")


def test_github_slugify():
    assert github_slugify("Free minutes") == "free-minutes"
    assert github_slugify("Overview") == "overview"
    assert github_slugify("Refund policy") == "refund-policy"


def test_check_consistency_passes_on_mini():
    problems = check_consistency(MINI_ROOT)
    assert problems == [], summarize(problems)


def test_check_consistency_fails_on_broken_copy(tmp_path: Path):
    broken = tmp_path / "broken"
    shutil.copytree(MINI_ROOT, broken)

    # Break it two ways: a carrier document that no longer exists, and a
    # fact referencing an entity that does not exist.
    (broken / "sources" / "wiki" / "pricing-rules-2025.md").unlink()
    facts_path = broken / "truth" / "facts.yaml"
    facts_path.write_text(
        facts_path.read_text().replace(
            "entities: [E-farebox]", "entities: [E-farebox, E-does-not-exist]", 1
        )
    )

    problems = check_consistency(broken)
    assert problems
    joined = "\n".join(problems)
    assert "pricing-rules-2025" in joined
    assert "E-does-not-exist" in joined


def test_check_consistency_catches_bad_heading_anchor_and_bad_symbol(tmp_path: Path):
    broken = tmp_path / "broken"
    shutil.copytree(MINI_ROOT, broken)

    # Rename the wiki heading F-004 anchors, so "#overview" no longer matches.
    wiki_path = broken / "sources" / "wiki" / "pricing-rules.md"
    wiki_path.write_text(wiki_path.read_text().replace("## Overview", "## Summary"))

    # Rename the code symbol F-001..F-003 point at, so it's no longer a word
    # in the materialised file at any version.
    for path in [
        broken / "system" / "farebox" / "pricing.py",
        broken / "system" / "history" / "c1" / "farebox" / "pricing.py",
        broken / "system" / "history" / "c3" / "farebox" / "pricing.py",
    ]:
        path.write_text(path.read_text().replace("FREE_MINUTES", "FREEBIE_MINUTES"))

    problems = check_consistency(broken)
    joined = "\n".join(problems)
    assert "wiki:wiki/pricing-rules:#overview" in joined
    assert any(p.startswith("code:code/farebox/pricing.py") for p in problems)


def test_check_consistency_catches_bad_vitest_title_and_bad_dotted_symbol(tmp_path: Path):
    broken = tmp_path / "broken"
    shutil.copytree(MINI_ROOT, broken)

    # F-012's location is "refundsWatcher > locks a bike ...": break the
    # describe() call's literal name so it no longer appears as a call.
    ts_path = broken / "system" / "dispatch" / "test" / "refundsWatcher.test.ts"
    ts_path.write_text(ts_path.read_text().replace("describe('refundsWatcher'", "describe('other'"))

    # F-013's location is "PricingClient.fetch_rate": rename the class.
    client_path = broken / "system" / "farebox" / "client.py"
    client_path.write_text(client_path.read_text().replace("PricingClient", "RenamedClient"))

    problems = check_consistency(broken)
    joined = "\n".join(problems)
    assert "describe('refundsWatcher')" in joined
    assert any("dotted symbol 'PricingClient.fetch_rate'" in p for p in problems)


def test_run_carrier_reconstructs_vitest_fullname_not_raw_field():
    """Vitest 5.0.2 joins ancestorTitles+title with a single space in its own
    `fullName` field (confirmed 2026-09-28 against real spike/system/dispatch
    output); truth's locations use " > ". check_consistency must reconstruct
    the join itself, never trust the raw `fullName`, or every vitest carrier
    in the real fixture would silently fail to resolve."""
    carrier = Carrier(
        document="run/vitest-c1",
        location="refunds > publishes a refund.completed event",
    )
    assert _check_run_carrier(carrier, MINI_ROOT) is None

    raw_fullname_carrier = Carrier(
        document="run/vitest-c1",
        location="refunds publishes a refund.completed event",  # the raw fullName
    )
    problem = _check_run_carrier(raw_fullname_carrier, MINI_ROOT)
    assert problem is not None
    assert "no passed vitest fullName match" in problem


def test_summarize_groups_by_kind():
    problems = ["wiki:a:b:not found", "wiki:c:d:not found", "fact: F-1 has no carriers"]
    report = summarize(problems)
    assert "3 problem(s)" in report
    assert "wiki: 2" in report
    assert "fact: 1" in report


def _playwright_report(tmp_path: Path) -> Path:
    """A minimal Playwright JSON report: one file suite, one describe, one
    test run in two projects, passing in one and failing in the other."""
    report = {
        "config": {"projects": [{"name": "fake"}, {"name": "real"}], "metadata": {}},
        "suites": [
            {
                "title": "fare-preview.spec.ts",
                "specs": [],
                "suites": [
                    {
                        "title": "fare preview",
                        "specs": [
                            {
                                "title": "shows the cap",
                                "tests": [
                                    {"projectName": "fake", "results": [{"status": "passed"}]},
                                    {"projectName": "real", "results": [{"status": "failed"}]},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "errors": [],
        "stats": {},
    }
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "playwright-c7.json").write_text(json.dumps(report))
    return tmp_path


def test_playwright_outcomes_joins_title_path_below_the_file_suite(tmp_path: Path):
    data = json.loads((_playwright_report(tmp_path) / "runs" / "playwright-c7.json").read_text())
    assert playwright_outcomes(data) == [
        ("fake", "fare preview › shows the cap", "passed"),
        ("real", "fare preview › shows the cap", "failed"),
    ]


def test_run_carrier_for_playwright_resolves_only_in_a_project_where_it_passed(tmp_path: Path):
    root = _playwright_report(tmp_path)
    location = "fare preview › shows the cap"
    passed = Carrier(document="run/playwright-c7", location=location, project="fake")
    failed = Carrier(document="run/playwright-c7", location=location, project="real")
    unknown = Carrier(document="run/playwright-c7", location=location, project="staging")
    assert _check_run_carrier(passed, root) is None
    assert "no passed playwright test in 'real'" in _check_run_carrier(failed, root)
    assert "no project 'staging'" in _check_run_carrier(unknown, root)


def test_code_carrier_with_a_playwright_title_path(tmp_path: Path):
    shutil.copytree(MINI_ROOT, tmp_path / "mini")
    root = tmp_path / "mini"
    spec = root / "system" / "web" / "tests" / "fare-preview.spec.ts"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        'test.describe("fare preview", () => {\n  test("shows the cap", async () => {});\n});\n'
    )
    timeline = Timeline(root)
    step = timeline.steps[-1].id
    good = Carrier(
        document="code/web/tests/fare-preview.spec.ts",
        location="fare preview › shows the cap",
        version=step,
    )
    bad = Carrier(document=good.document, location="fare preview › shows the floor", version=step)
    assert _check_code_carrier(good, root, timeline) is None
    assert "test('shows the floor') not found" in _check_code_carrier(bad, root, timeline)


def test_load_fidelities_and_the_fidelity_of_a_run_carrier(tmp_path: Path):
    (tmp_path / "fidelities.yaml").write_text(
        "ranked: [real, in-process, fake, mocked]\n"
        "real_backend: in-process\n"
        "run_fidelity:\n"
        "  pytest: in-process\n"
        "  playwright: {mocked: mocked, fake: fake, real: real}\n"
    )
    fidelities = load_fidelities(tmp_path / "fidelities.yaml")
    assert fidelities.rank("real") > fidelities.rank("in-process") > fidelities.rank("mocked")
    assert fidelities.rank("staging") == 0
    assert fidelities.at_or_above_real_backend("in-process")
    assert not fidelities.at_or_above_real_backend("fake")
    assert fidelities.of_carrier(Carrier(document="run/pytest-c5-rerun")) == "in-process"
    assert fidelities.of_carrier(Carrier(document="run/playwright-c7", project="fake")) == "fake"
    assert fidelities.of_carrier(Carrier(document="run/playwright-c7")) is None
    assert fidelities.of_carrier(Carrier(document="code/web/serve.py")) is None
    assert load_fidelities(tmp_path / "absent.yaml") is None


def test_check_fidelity_wants_the_strongest_passing_run(tmp_path: Path):
    fidelities = Fidelities(
        ranked=("real", "in-process", "fake", "mocked"),
        real_backend="in-process",
        run_fidelity={"pytest": "in-process", "playwright": {"fake": "fake", "real": "real"}},
    )
    runs = (
        Carrier(document="run/playwright-c7", location="t", project="fake"),
        Carrier(document="run/playwright-c7", location="t", project="real"),
    )

    def fact(tier: str, fidelity: str | None) -> TruthFact:
        return TruthFact(
            id="F-900",
            statement="s.",
            category="business-logic",
            entities=("E-x",),
            tier=tier,
            carriers=runs,
            fidelity=fidelity,
        )

    assert _check_fidelity(fact("executed", "real"), fidelities) == []
    assert (
        "strongest run carrier 'real'" in _check_fidelity(fact("executed", "fake"), fidelities)[0]
    )
    assert "carries no fidelity" in _check_fidelity(fact("code", "fake"), fidelities)[0]
    assert _check_fidelity(fact("code", None), fidelities) == []


def test_mini_truth_has_no_fidelities():
    assert load_truth(MINI_ROOT / "truth").fidelities is None
