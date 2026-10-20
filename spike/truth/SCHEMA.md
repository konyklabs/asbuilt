# Ground truth

Authored first. Every artefact under `system/`, `sources/` and `runs/` exists
to carry a fact listed here; the consistency test in `spike/tests` fails when
a fact has no carrier or a carrier does not resolve.

Ids: `E-` entities, `F-` facts, `X-` contradictions, `S-` stale pages.
Commits are referred to by history step id (`c1`, `c2`, ...); `bench/build.py`
resolves a step to its SHA (`spike/build/commits.json`) deterministically.

## entities.yaml

```yaml
- id: E-farebox
  kind: service            # service | table | rule | job | flag | integration | queue | team | endpoint
  name: farebox
  owner: E-team-fares      # optional
  summary: "Memberships, ride pricing, invoices, refunds."
  valid_from: c7           # optional: the step that adds the entity; every fact tagged with it is valid from then
```

## facts.yaml

```yaml
- id: F-001
  statement: "A member's first 30 minutes of every ride are free."
  category: business-logic           # business-logic | technical-implementation | operations | history
  entities: [E-farebox, E-rule-member-free-minutes, E-table-memberships]
  tier: executed                     # the strongest tier the fixture carries it at
  fidelity: in-process               # executed facts only: the strongest fidelity a cited run passed at
  valid_from: c4                     # the step that introduced it; omit when true from c1
  carriers:                          # every place the fixture states it; the first is primary
    - document: code/farebox/pricing.py
      location: MEMBER_FREE_MINUTES     # a symbol the file defines at that version
      version: c4
    - document: code/tests/e2e/test_pricing.py
      location: "tests/e2e/test_pricing.py::test_member_first_thirty_minutes_free"
      version: c4
    - document: run/pytest-c4
      location: "tests/e2e/test_pricing.py::test_member_first_thirty_minutes_free"
    - document: wiki/pricing-rules
      location: "#member-pricing"
      version: 5
```

Locations by document kind: `wiki/` and `doc/` use a heading anchor
(`#free-minutes`); `ticket/` uses `description` or `comment-<k>`; `pull/`
uses `body` or `comment-<k>`; `code/` uses a symbol the file defines
(`MEMBER_FREE_MINUTES`, `price_ride`, `FareboxClient.close_ride`), a pytest
node id (`tests/unit/test_pricing.py::test_single_ride_cap_30`) or a Vitest
title (`stormPause > pauses rebalancing while ...`) or a Playwright title path
(`fare preview › shows the farebox cap for a 200-minute casual ride`: the
`test.describe` titles and the `test` title, joined with " › ", without the
file, exactly the JUnit reporter's testcase name); `run/` uses the node id or
title of the test in that run. A Playwright run carrier also names its
`project` (`run/playwright-c7`, `project: real`): one report holds a run per
project, each at its own fidelity. Line ranges are not a location: they move.
Entities are ids from `entities.yaml` (`E-...`), never prose names.

Rules: a fact at tier `executed` carries a `run/` document and the test that
produced it; at tier `code`, a `code/` document; at `documented`, only
`wiki/`, `ticket/`, `doc/` or `pull/` documents. A fact present only in a PR
thread carries exactly one `pull/` document. Statements are one sentence, in
the present tense, and say exactly what the strongest carrier asserts, no
more (a passing test proves what it asserted; `executed-audit.md` records how
each executed statement was checked against its assertion).

Structured claims (D-013, "every fact has an identity"). A fact whose
statement carries a number, a money amount, a clock time or a duration (a
digit, a number word from "two" up, or "every hour" and the like) has exactly
one `claim`; a fact without one has none:

```yaml
  claim:
    entity: E-rule-single-ride-cap   # one of the fact's own entities
    attribute: cap                   # snake_case
    value: 30.0                      # a number (money in USD as a number), or a string for clock times, dates and codes
    unit: usd                        # usd | minute | day | hour | second | percent | count | clock | null
```

The value appears in the statement: as the same number, a number word, a
verbatim string, or 1 for "every <unit>". Facts about one attribute at
different times or in contradiction share `entity` and `attribute`, so a join
on the pair finds them: every contradiction and stale pair whose facts both
carry a claim shares both, with a different value or unit. When a claim is
about shared infrastructure (backups, deploys), it uses the fact's first
entity.

Run outcomes (D-013; the planted cases are in `planted-runs.yaml`):

- An `executed` fact cites the attempt-1 run of every step, within its
  validity, at which its test passes. Reruns (`run/<framework>-<step>-rerun`)
  are never cited.
- A later failure demotes: the fact drops to `code`, keeps its earlier passing
  runs as carriers, names the failing run in `demoted_by` (`document`,
  `location`), and a `run-vs-code` contradiction opens against what the code
  now says.
- A skipped (or expected-failure) test never lifts: it may be a `code/`
  carrier of a `code` fact, never a `run/` one.
- A step whose attempts disagree (flaky) is inconclusive: it neither lifts nor
  demotes, and neither of its runs is cited.

Backend fidelity (D-014, asbuilt#37; the vocabulary is `fidelities.yaml`):

- An executed fact cites every run, per step and per project, within its
  validity, at which its test passes, and its `fidelity` is the strongest of
  those runs' fidelities. A run's fidelity is the truth's: `fidelities.yaml`
  gives it by framework, and for Playwright by project.
- A failing run at a higher fidelity than every passing one demotes the fact
  to `code`: it keeps its passing runs (all below the failing one), names
  the failing run in `demoted_by` with its `project`, and a `fake-vs-real`
  contradiction opens, at that run's step, that the fact the higher-fidelity
  run proves wins.
- A failure at a lower fidelity than a pass does not demote.

## contradictions.yaml

```yaml
- id: X-001
  facts: [F-017, F-001]              # the two statements that cannot both hold
  kind: wiki-vs-test                 # wiki-vs-test | ticket-vs-code | page-vs-page | doc-vs-code | run-vs-code | fake-vs-real
  winner: F-001                      # D-014's order, then fidelity, then recency (below)
  label: refutes
```

Two optional fields bound when a contradiction is open, as step ids:
`opened_by` is the step at which it opens (none: open from the fixture's
start) and `resolved_by` the step at which it stops holding (none: still
open). A `run-vs-code` or `fake-vs-real` entry always has `opened_by`, the
step of the failing run; X-021 opens at c5 and is resolved at c6, when the
failing test is replaced; X-022 opens at c7 and stays open.

The winner follows D-014's order: an executed fact at or above the real
backend (`fidelities.yaml`), then a code fact, then an executed fact proven
only below the real backend, then a documented one; then the higher
fidelity; then recency. Every earlier pair resolves as it did by tier alone,
since their executed facts are all `in-process`, the real backend.

## fidelities.yaml

```yaml
ranked: [real, in-process, fake, mocked]   # highest first
real_backend: in-process                   # at or above it ranks above code
descriptions: {real: "...", in-process: "...", fake: "...", mocked: "..."}
run_fidelity:                              # every run document's fidelity
  pytest: in-process
  vitest: in-process
  playwright: {mocked: mocked, fake: fake, real: real}   # by project
```

`real`: Gearwell's own service code serving HTTP (`web/serve.py --backend
real`). `in-process`: the services' code wired in one process with external
integrations faked, which is what every pytest and Vitest run is. `fake`:
farebox replaced by a fake written from its documentation
(`web/fake_farebox.py`). `mocked`: `/api` routes intercepted in the browser.
`bench/truth.py` loads it (`Fidelities`); the scorer's per-fidelity lines
(asbuilt#38) read it rather than hard-coding the names.

## stale.yaml

```yaml
- id: S-001
  document: wiki/pricing-rules-2025  # the page that still states the old behaviour
  states: F-017                      # the fact it states
  changed_by: c4                     # the step that changed the code it describes
  superseded_by: F-001
```

## aliases.yaml

```yaml
- id: E-int-tollbooth-pay
  name: Tollbooth Pay                # the entity's name in entities.yaml
  aliases: [tollbooth, the payment provider, TollboothClient]   # 2 to 6
```

For the scorer only: it resolves the names in `queries/mix.yaml` and the
entity names an arm returns to ids. Arms never read it. Matching is
case-insensitive and no alias belongs to two entities.

## Other files here

- `PLAN.yaml`: the authoring plan for every source document, the system's
  code and tests, and the runs; derived from `facts.yaml`.
- `executed-audit.md`: one row per executed (or demoted) fact, verdict a
  (proven as written), b (narrowed) or c (boundary assertion to add).
- `planted-runs.yaml`: the failing, skipped and flaky tests and their effect,
  and the Playwright tests planted at c7 with their outcome per project.
- `validate.py`: checks all of the above against each other and the mix.

Counts: 125 facts across the four categories, 22 contradictions (20 between
sources, one opened by a planted failing run, one by a planted run at a
higher fidelity), 10 stale pages, 5 PR-only facts.
