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
```

## facts.yaml

```yaml
- id: F-001
  statement: "A member's first 30 minutes of every ride are free."
  category: business-logic           # business-logic | technical-implementation | operations | history
  entities: [E-farebox, E-rule-member-free-minutes, E-table-memberships]
  tier: executed                     # the strongest tier the fixture carries it at
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
title (`stormPause > pauses rebalancing while ...`); `run/` uses the node id
or title of the test in that run. Line ranges are not a location: they move.
Entities are ids from `entities.yaml` (`E-...`), never prose names.

Rules: a fact at tier `executed` carries a `run/` document and the test that
produced it; at tier `code`, a `code/` document; at `documented`, only
`wiki/`, `ticket/`, `doc/` or `pull/` documents. A fact present only in a PR
thread carries exactly one `pull/` document. Statements are one sentence, in
the present tense, and say exactly what the strongest carrier asserts, no
more (a passing test proves what it asserted).

## contradictions.yaml

```yaml
- id: X-001
  facts: [F-017, F-001]              # the two statements that cannot both hold
  kind: wiki-vs-test                 # wiki-vs-test | ticket-vs-code | page-vs-page | doc-vs-code
  winner: F-001                      # by tier (executed > code > documented), then by recency
  label: refutes
```

## stale.yaml

```yaml
- id: S-001
  document: wiki/pricing-rules-2025  # the page that still states the old behaviour
  states: F-017                      # the fact it states
  changed_by: c4                     # the step that changed the code it describes
  superseded_by: F-001
```

Counts (estimate from the tiering comment, until Oleg's local note reweights
them): about 120 facts across the four categories, 20 contradictions, 10
stale pages, 5 PR-only facts.
