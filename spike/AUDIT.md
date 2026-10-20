# Stack B hand audit: the executed tier and hard false positives

This is a hand audit of Stack B's three overnight model runs for konyklabs/roadmap#154 (D-013). The runs are `build/results-b_postgres-model-{1,2,3}.json`: medium effort, complete, on `main` at ad73e93. They were scored by `bench/score.py` against `truth/`.

The fixture is Gearwell, an invented bike-share back office. Every name in this report belongs to it.

The audit is read-only. No fixture, scorer or pipeline file was changed, and no container or model call was used. All paths are relative to `spike/`. A path such as `tests/unit/test_memberships.py` or `dispatch/test/stormPause.test.ts` at a step or a SHA is a file in the built fixture repository, read with `git -C build/repo show <sha>:<path>`; its final version is under `system/`.

## Result

### Executed-tier precision, scorer against audit

| Reading | Scorer, runs 1, 2, 3 | Audited, runs 1, 2, 3 | Strict, runs 1, 2, 3 |
|---|---|---|---|
| Explain | 35/40, 36/42, 35/40 = 0.875, 0.857, 0.875 | 36/40, 38/42, 36/40 = 0.900, 0.905, 0.900 | 0.775, 0.786, 0.775 |
| Search | 6/17, 5/14, 5/15 = 0.353, 0.357, 0.333 | 16/17, 13/14, 15/15 = 0.941, 0.929, 1.000 | 0.765, 0.714, 0.800 |
| Pooled explain+search (as the paired bootstrap pools it) | 41/57, 41/56, 40/55 = 0.719, 0.732, 0.727 | 52/57, 51/56, 51/55 = 0.912, 0.911, 0.927 | 0.772, 0.768, 0.782 |
| Distinct executed facts, whatever query returned them | not computed by the scorer | 25/27 = 0.926 in every run | 20/27 = 0.741 |

- **Audited:**
  - each returned executed fact is judged true and proven by its cited passing run, or not;
  - counting (a)+(b) as correct and counting (a) alone give the same counts, because no uncredited executed row is (b);
  - over-claims (c) are counted wrong;
  - a planted fact returned for a query that did not expect it (a-scope) is counted correct.
- **Strict:** also counts wrong the five statements that do not state their fact on their own:
  - the value only in the claim: "Casual rate from 1st minute.", "Member rate after free minutes.", "Ebike surcharge when flag on.";
  - a clause or condition dropped: "3rd checkout refused.", "Checkin at full station refused.".
- **The scorer under-credits and over-credits.**
  - It misses 5 or 6 correct explain rows: test-name statements meet the number, negation and claim-attribute rules, plus two entity-scope exclusions.
  - It misses 8 to 10 correct search rows: planted facts outside the query's `expects`.
  - It credits 4 explain rows per run that over-claim.
- **The only wrong executed facts:** "Membership lapses 3 days after failed renewal." and "Membership lapses 7 days after failed renewal." (F-015, F-016). The tests assert a grace deadline (`tests/unit/test_memberships.py:27-29`), no code lapses a membership, and the truth narrowed both facts for exactly this reason (`truth/executed-audit.md`). The two are the same in every run. Removing or narrowing them puts every reading at 1.000.
- **The 0.95 bar** (D-013: "the tests-as-evidence claim is not published while executed-tier precision on the fixture is below 0.95") is **missed on every reading that measures tier correctness**: distinct 0.926, explain 0.900–0.905, pooled 0.911–0.927.
  - Search reaches 1.000 in run 3 only because the lapse statement was not among its results, and search measures retrieval relevance (its expected set is the 1–3 facts a query's `expects` names), not tier.
  - The reading to judge the bar on is the distinct-fact one. Until the scorer computes it, quote explain.

### Hard false positives, run 1 explain

The scorer counts 470: 463 documented, 5 executed and 2 code. A stratified sample of 40 (seed 154, proportional by category) found:
- (a) 16: a planted fact the scorer did not pair (7 full, 8 partial, 1 scope);
- (b) 22: true but unplanted;
- (c) 2: right fact, wrong category;
- (d) 0: false or unsupported.

Estimated true-but-unplanted share: 0.55 for (b) (Wilson 95% 0.40 to 0.69), 0.60 for (b)+(c) (0.45 to 0.74). False: 0/40, Wilson upper bound 0.09. These are estimates from a sample of 40.

The scorer's "hard false positive" is structural (an unmatched fact sharing an entity and a cited document with any truth fact), not a finding of falsity.

### Causes

1. **The test connector writes statements from test names.** `connectors/tests/extract_rules.py:242-302` (`_name_sentence`, used at `:1018`) produces the executed statement. The asserted values land in the claim, or in `detail`, which is never matched. That gives:
   - the "lapses" over-claim, against the module's own promise "never past what the test's assertion actually proves" (`connectors/tests/extract_rules.py:1-4`);
   - statements the matcher cannot read: "fortyfive", "3rd", and values held only in the claim.
2. **Entity scope.**
   - `_service_from_imports` (`connectors/tests/extract_rules.py:312`) tags the close-ride test `dockyard`.
   - Query-time resolution (`pipeline/resolve.py:143-154`) resolved "POST /refunds" differently in each run.
3. **Duplicates without claims.** `pipeline/store.py:235-243` (`base_fact_id`) keys a fact without a claim by its normalised statement. A page's sentence and a test's sentence for one rule stay two rows, and the second is a false positive under one-to-one matching: 9 of the 16 sampled (a) rows.
4. **Category labels.** Category labels come from the model in document extraction (`prototypes/b_postgres/extract.py:126-128` and `:233`). Both sampled (c) rows are of this kind.

### Findings for the scorer and the fixture

Each is a change to the exam or the marking, so each needs the review round.

- **Number words** (`bench/score.py:342-378`).
  - Compound words are not composed: "forty-five" yields {40, 5} and "twenty-four" yields {20, 4}.
  - "fortyfive" is not read at all.
  - "one" counts as a number, so "one more unit", "the one alert" and "every one of the three jobs" fail the number rule.
- **Polarity hard negative missing.**
  - "Checkin at full station allowed with overflow parking." matches F-017 ("... refused when the overflow_parking flag is off"), similarity 0.62.
  - "Checkin at full station refused." matches F-018, similarity 0.60.
  - In these runs, pairing in expected order landed each on its own fact; a query returning one of them alone would credit it against its opposite.
- **Claim-credited over-claims.** A claim that agrees in full decides a match on its own, so "Membership lapses 7 days after failed renewal." (claim GRACE_DAYS = 7 days) is credited as F-016, a grace period that ends 7 days after the failure. The statement path agrees too (similarity 0.86); neither can see "lapses".
- **The negation veto against the truth's own wording.** F-010 says "not docked within 24 hours", so no positive paraphrase ("open past 24 hours") can match it.
- **F-007's truth steps.**
  - `truth/executed-audit.md` adds the member-ride boundary assertion to `test_ebike_surcharge_when_flag_on` at c1–c6.
  - The built repository has it at c5 and c6 only; `system/history/c4/tests/unit/test_pricing.py` lacks it.
  - F-007 ("every charged minute of an e-bike ride") therefore cites run/pytest-c1..c4 for a test that exercised only a casual ride at those steps.
- **Duplicates without claims.** As in cause 3, a design question for the store as well as for one-to-one matching.

## Method

The scripts below are reproduced in the appendix, as run except that `ruff format` (the repository check formats Python blocks in Markdown) re-wrapped their lines; nothing else changed. They are not committed as files; to rerun, save each to `build/audit/<name>.py` (`build/` is ignored by git) and run it from `spike/` with `.venv/bin/python`, never `uv run`. Each uses the scorer's own functions from `bench/score.py` and `bench/truth.py` rather than reimplementing the matcher.

| Script | What it does |
|---|---|
| `misses.py` | Calls `bench.score.score()` for the scorer's totals, then re-runs the explain path with `align_entities`, `resolve_fact_entities`, `match_facts`, `classify_unmatched` and `facts_match`. It dumps each executed-tier return not matched to an executed truth fact, and each hard false positive |
| `diagnose.py` | Steps through `facts_match` (negation, flag state, mention, numbers, similarity, claim) for each executed miss against the planted facts on the same test |
| `veto.py` | The same step-through for sampled rows against a named planted fact. It reports whether that fact is in the query's expected set and whether it was already matched in the query |
| `sample.py` | The stratified sample (seed 154) with the cited passage of each citation read from `sources/` |
| `siblings.py` | Checks each sampled text citation's version against the document on disk, and lists the planted facts that share an entity and a document with the row |
| `extras.py` | The Wilson intervals and the compound-number-word scan |
| `tiers.py` | Executed-tier misses on explain and search; search's expected set is the query's `expects`, as `score()` builds it |
| `readings.py` | Executed-tier precision for explain, search, pooled and distinct facts under the audit |
| `evidence.py` | The point checks: run outcomes of each cited test, the matcher helpers behind each veto, the assertions present at each commit, the over-claim and the polarity checks |

`build/results-b_postgres-model-N.json` are byte-identical to the overnight run's copies (`cmp`, no output for any of the three).

## Commands and outputs

```
$ mkdir -p build/audit
$ for n in 1 2 3; do echo "=== run $n"; .venv/bin/python build/audit/misses.py build/results-b_postgres-model-$n.json --dump build/audit/run$n.json | grep -v "^   \|^- "; done
=== run 1
scorer explain: tp=79 returned=620 hard_fp=470 unplanted=0
scorer executed: tp=35 returned=40 expected=62 hard_errors=0
recomputed explain: tp=79 returned=620 hard_fp=470 unplanted=71 executed tp=35 returned=40
executed misses: 5
=== run 2
scorer explain: tp=88 returned=680 hard_fp=528 unplanted=0
scorer executed: tp=36 returned=42 expected=62 hard_errors=0
recomputed explain: tp=88 returned=680 hard_fp=528 unplanted=64 executed tp=36 returned=42
executed misses: 6
=== run 3
scorer explain: tp=83 returned=652 hard_fp=499 unplanted=0
scorer executed: tp=35 returned=40 expected=62 hard_errors=0
recomputed explain: tp=83 returned=652 hard_fp=499 unplanted=70 executed tp=35 returned=40
executed misses: 5
```

The reproduction matches the scorer exactly. The scorer's merged report carries no list of unplanted facts, so its `unplanted=0` is an artefact; the recomputed 71, 64 and 70 are the figures. Every executed miss is an executed return that matched nothing; none matched a truth fact of a lower tier. The grep hides the per-miss detail lines, which are in the Task 1 tables.

`diagnose.py` on run 2, whose six misses include run 1's and run 3's five, keeping each miss's line against its own planted fact. The full output also lists every other planted fact on the same test or anchor.

```
$ .venv/bin/python build/audit/diagnose.py build/audit/run2.json build/results-b_postgres-model-2.json > build/audit/diagnose.out
$ awk '/^q-explain/{q=$0; print; next} /vs F-002 \[/ && q~/fortyfive/ {print; next} /vs F-010 \[/ && q~/24 hours/ {print; next} /vs F-007 \[/ && q~/Ebike/ {print; next} /vs F-050 \[/ && q~/Close ride/ {print; next} /vs F-019 \[/ && q~/checkout/ {print; next} /vs F-014 \[/ && q~/Refund/ {print; next}' build/audit/diagnose.out | grep -v "^="
q-explain-01 query entity farebox -> E-farebox | stmt: Member 1st fortyfive minutes free.
  vs F-002 [executed] in_expected=True entity_overlap=True neg_mismatch=False flag_conflict=False mention_conflict=False nums r=[] t=['45'] sim=0.600 stmt_match=False facts_match=False
q-explain-01 query entity farebox -> E-farebox | stmt: Ride open past 24 hours closed as lost.
  vs F-010 [executed] in_expected=True entity_overlap=True neg_mismatch=True flag_conflict=False mention_conflict=False nums r=['24'] t=['24'] sim=0.750 stmt_match=False facts_match=False
q-explain-01 query entity farebox -> E-farebox | stmt: Ebike surcharge when flag on.
  vs F-007 [executed] in_expected=True entity_overlap=True neg_mismatch=False flag_conflict=False mention_conflict=False nums r=[] t=['$0.1'] sim=1.000 stmt_match=False facts_match=False
q-explain-02 query entity dockyard -> E-dockyard | stmt: Close ride publishes ride completed.
  vs F-050 [executed] in_expected=False entity_overlap=True neg_mismatch=False flag_conflict=False mention_conflict=False nums r=[] t=[] sim=0.600 stmt_match=True facts_match=True
q-explain-02 query entity dockyard -> E-dockyard | stmt: 3rd checkout refused.
  vs F-019 [executed] in_expected=True entity_overlap=True neg_mismatch=False flag_conflict=False mention_conflict=False nums r=[] t=['2'] sim=0.333 stmt_match=False facts_match=False
q-explain-20 query entity POST /refunds -> E-endpoint-refund | stmt: Refund under $5.00 auto approved when flag on.
  vs F-014 [executed] in_expected=False entity_overlap=True neg_mismatch=False flag_conflict=False mention_conflict=False nums r=['$5'] t=['$5'] sim=1.000 stmt_match=True facts_match=True
```

```
$ .venv/bin/python build/audit/evidence.py
== run outcomes (runs/pytest-cN.json, runs/vitest-cN.json)
  test_member_first_fortyfive_minutes_free                     c1=absent c2=passed c3=passed c4=absent c5=absent c6=absent
  test_ride_open_past_24_hours_closed_as_lost                  c1=passed c2=passed c3=passed c4=passed c5=passed c6=passed
  test_ebike_surcharge_when_flag_on                            c1=passed c2=passed c3=passed c4=passed c5=passed c6=passed
  test_close_ride_publishes_ride_completed                     c1=passed c2=passed c3=passed c4=passed c5=passed c6=failed
  test_third_checkout_refused                                  c1=passed c2=passed c3=passed c4=passed c5=passed c6=passed
  test_refund_under_five_dollars_auto_approved_when_flag_on    c1=absent c2=absent c3=absent c4=absent c5=absent c6=passed
  test_single_ride_cap_30                                      c1=absent c2=absent c3=absent c4=absent c5=passed c6=passed
  test_casual_ride_charges_one_dollar_unlock_fee               c1=passed c2=passed c3=passed c4=passed c5=passed c6=passed
  test_casual_rate_from_first_minute                           c1=passed c2=passed c3=passed c4=passed c5=passed c6=passed
  test_lost_bike_fee_150                                       c1=absent c2=absent c3=absent c4=absent c5=absent c6=passed
  test_station_status_reports_fill_ratio                       c1=passed c2=passed c3=passed c4=passed c5=passed c6=passed
  test_checkin_at_full_station_allowed_with_overflow_parking   c1=passed c2=passed c3=passed c4=passed c5=passed c6=passed
  test_membership_lapses_3_days_after_failed_renewal           c1=passed c2=passed c3=absent c4=absent c5=absent c6=absent
  test_membership_lapses_7_days_after_failed_renewal           c1=absent c2=absent c3=passed c4=passed c5=passed c6=passed
  rideEvents > counts ride.completed toward the return station's demand c1=passed c2=passed c3=passed c4=passed c5=passed c6=passed
== matcher helpers behind each veto
  _number_tokens('Member 1st fortyfive minutes free.') = set()
  _number_tokens("A member's first forty-five minutes are free.") = {'5', '40'}
  _has_negation(F-010) = True | _has_negation('Ride open past 24 hours closed as lost.') = False
  F-007 echo claim: resolves ['E-flag-ebike-surcharge'] | comparable True | claims_match False | values agree True | attributes_match False
  F-019 echo: sim 0.333, words ['3rd', 'checkout', 'refused']
== over-claim: 'Membership lapses N days after failed renewal.' against F-015/F-016
  F-015: claims_match True | statement match True sim 0.86 | truth: A failed renewal gives a membership a grace period that ends 3 days after the failure.
  F-016: claims_match True | statement match True sim 0.86 | truth: A failed renewal gives a membership a grace period that ends 7 days after the failure.
== polarity: allowed/refused against F-017/F-018
  'Checkin at full station allowed with overflow parking.' vs F-017: statement match True sim 0.62
  'Checkin at full station allowed with overflow parking.' vs F-018: statement match True sim 0.62
  'Checkin at full station refused.' vs F-017: statement match True sim 0.80
  'Checkin at full station refused.' vs F-018: statement match True sim 0.60
== assertions present per commit (git -C build/repo show <sha>:<path>, count of matching lines)
  tests/e2e/test_pricing.py 'minutes=46': c2:1 c3:1
  tests/e2e/test_pricing.py 'minutes=31': c1:1 c2:0 c3:0 c4:1 c5:1 c6:1
  tests/unit/test_lost_bikes.py 'just_under': c1:2 c2:2 c3:2 c4:2 c5:2 c6:2
  tests/unit/test_pricing.py 'EBIKE_SURCHARGE == Decimal("0.10")': c1:1 c2:1 c3:1 c4:1 c5:1 c6:1
  tests/unit/test_pricing.py 'at_threshold': c1:0 c2:0 c3:0 c4:0 c5:2 c6:2
  tests/e2e/test_close_ride.py 'payload["type"] == "ride.completed"': c1:1 c2:1 c3:1 c4:1 c5:1
  tests/e2e/test_checkout.py 'checkout_limit_reached': c1:1 c2:1 c3:1 c4:1 c5:1 c6:1
  tests/e2e/test_refunds.py 'body["status"] == "approved"': c6:1
  tests/e2e/test_refunds.py 'timedelta(days=14, minutes=1)': c1:1 c2:1 c3:1 c4:1 c5:1 c6:1
  dispatch/test/nightlyRebalance.test.ts 'station-low-edge': c1:1 c2:1 c3:1 c4:1 c5:1 c6:1
  tests/unit/test_tollbooth_client.py '== 4': c1:1 c2:1 c3:1 c4:1 c5:1 c6:1
  dispatch/test/maintenanceSweep.test.ts 'expect(openedTickets).toHaveLength(1)': c1:1 c2:1 c3:1 c4:1 c5:1 c6:1
  dispatch/test/stormPause.test.ts 'severity: 1, observedAt: now': c6:1
  tests/unit/test_memberships.py 'MembershipStatus.GRACE': c1:1 c2:1 c3:1 c4:1 c5:1 c6:1
  tests/unit/test_memberships.py 'LAPSED': c1:0 c2:0 c3:0 c4:0 c5:0 c6:0
  git grep LAPSED farebox @c6: 1ab33e0:farebox/models/membership.py:15:    LAPSED = "lapsed"
```

The thirty-minute test's 31-minute boundary is absent at c2 and c3 because that test is not the active one there: F-001 is valid at c1, F-002 (45 minutes) at c2–c3, and F-003 at c4–c6. `LAPSED` appears only as the enum value in `farebox/models/membership.py`; no code moves a membership to it.

## Task 1: executed-tier misses

Classes: **a** = the matcher missed a planted fact; **b** = true but not planted; **c** = wrong tier (the test does not prove it); **d** = false. I split (a) three ways:
- **a-full**: the statement says the whole planted fact.
- **a-partial**: it says part of the planted fact, usually without its number.
- **a-scope**: `facts_match` pairs it with a planted fact, but that fact is outside the explain query's entity-scoped expected set.

### Run 1 (35/40 by the scorer)

| Query | Statement (fact id) | Citations | Class | Evidence |
|---|---|---|---|---|
| q-explain-01 farebox | Member 1st fortyfive minutes free. (f-573a52ca9d265d95) | test_pricing.py@c2,c3 + run/pytest-c2, c3 | a-full, F-002 | The test asserts 40, 45 and 46 minutes (`tests/e2e/test_pricing.py:51-95` at dccd9d1 and ebb11d6); runs c2 and c3 passed. The veto is on numbers: "fortyfive" is one token from the test name, so no 45 is read |
| q-explain-01 farebox | Ride open past 24 hours closed as lost. (f-ba2639ad84d8b92c) | test_lost_bikes.py + run/pytest-c1..c6 | a-full, F-010 | `tests/unit/test_lost_bikes.py:31-42` asserts 24h+1m closed and 24h-1m not; all six runs passed. The veto is negation: the truth wording is "not docked within 24 hours" |
| q-explain-01 farebox | Ebike surcharge when flag on. claim {EBIKE_SURCHARGE, ebike_surcharge, 0.1, usd} (f-e9850ebdcf9d4b4d) | test_pricing.py + run/pytest-c1..c6, plus wiki/ebike-surcharge, fares-overview, doc/fares-price-sheet, GW-105 | a-full, F-007 (the value is in the claim only) | `tests/unit/test_pricing.py:38-43` asserts `EBIKE_SURCHARGE == Decimal("0.10")` and +100 cents on a 10-minute ride, at all six steps. Similarity is 1.0, but the statement has no number and the claim attribute fails `_attributes_match` (veto by design, score.py docstring) |
| q-explain-02 dockyard | Close ride publishes ride completed. (f-27ce3c046f7fab7c) | test_close_ride.py + run/pytest-c1..c5 | a-scope, F-050 | `facts_match` is True. F-050's entities are farebox, ride.events and rides, not dockyard, so the fact is not expected for `dockyard`. The test drives dockyard's `checkin_endpoint`, and farebox's bus receives the event (`tests/e2e/test_close_ride.py:40-52`). Tier is right: the flaky c6 is excluded |
| q-explain-02 dockyard | 3rd checkout refused. (f-bf501b7050f91944) | test_checkout.py + run/pytest-c1..c6 | a-partial, F-019 (the "third check-out is refused" clause) | `tests/e2e/test_checkout.py:22-35` asserts 201, 201, 409 `checkout_limit_reached`. It fails on the missing truth number 2 and on similarity 0.333 ("checkout" against "check out"). The weakest (a): the statement omits the 2-bike limit and reads as "third concurrent check-out" only through the test's context |

### Run 2 (36/42 by the scorer)

The first five rows are identical to run 1: same query, statement, fact id and citations. This is verified in the `misses.py` dump (`build/audit/run2.json`) rather than repeated here. One more:

| Query | Statement (fact id) | Citations | Class | Evidence |
|---|---|---|---|---|
| q-explain-20 POST /refunds | Refund under $5.00 auto approved when flag on. (f-78254ad3ebaffeb4) | test_refunds.py@c6 + run/pytest-c6 | a-scope, F-014 | `facts_match` is True, but F-014's entities do not include E-endpoint-refund. In run 2, explain("POST /refunds") resolved to B's `refunds` entity and returned 43 facts. In run 1 it resolved to a `POST /refunds` entity (4 facts, none executed); in run 3 it returned 0 facts. The same fact matched F-014 under q-explain-01 in all three runs |

### Run 3 (35/40 by the scorer)

Identical to run 1: the same five rows, with the same query, statement, fact id and citations (`build/audit/run3.json`), and the same classes.

**Repeats:** all five run-1 misses recur in every run with the same fact id and statement, because they come from the rules extractor, which uses no model. Only the run-2 sixth miss varies, and it varies through query-time entity resolution. None of the six is (b), (c) or (d). Every cited run passed, every cited assertion exists at its commit, and no hard errors (executed without a `run/` citation) occurred.

## Task 2: executed-tier precision, recomputed

**Credited rows that over-claim.** An earlier draft of this audit trusted the scorer's credited rows and reported 1.000 on explain. Two of the credited facts claim more than their test asserts: "Membership lapses 3 days after failed renewal." (F-015) and "Membership lapses 7 days after failed renewal." (F-016). That is 4 credited explain rows in every run. Both tests assert only `GRACE_DAYS`, the move to `GRACE` and `grace_ends_at`:

```
tests/unit/test_memberships.py:27-29, at c1-c2 (test_membership_lapses_3_days_...) and c3-c6 (..._7_days_...), quoted:
    assert GRACE_DAYS == 3          (7 from c3)
    assert membership.status == MembershipStatus.GRACE
    assert membership.grace_ends_at == FAILED_AT + timedelta(days=GRACE_DAYS)
```

`truth/executed-audit.md` narrowed F-015 and F-016 for exactly this reason (verdict b: "no code moves a membership from grace to lapsed, so an assertion cannot prove 'lapses'"). The scorer credits B's echo anyway, through the claim and through the statement:

```
$ .venv/bin/python build/audit/evidence.py   # the relevant lines
  F-015: claims_match True | statement match True sim 0.86 | truth: A failed renewal gives a membership a grace period that ends 3 days after the failure.
  F-016: claims_match True | statement match True sim 0.86 | truth: A failed renewal gives a membership a grace period that ends 7 days after the failure.
  tests/unit/test_memberships.py 'MembershipStatus.GRACE': c1:1 c2:1 c3:1 c4:1 c5:1 c6:1
  tests/unit/test_memberships.py 'LAPSED': c1:0 c2:0 c3:0 c4:0 c5:0 c6:0
  git grep LAPSED farebox @c6: 1ab33e0:farebox/models/membership.py:15:    LAPSED = "lapsed"
```

The rows are class (c). The lapse is the documented behaviour: `sources/wiki/membership-faq.md` #grace says the grace period comes "before anything lapses", and `sources/wiki/membership-lifecycle.md:28` says "7 days from the failed renewal before the membership actually lapses". The cited test does not prove it, and no code implements it.

Every other credited executed fact was checked against its assertion at every cited step; all hold:
- 23 distinct statement and truth pairs per run;
- the boundary checks for F-001 and F-003 (30 → 0, 31 → 15 at c1 and c4–c6), F-013, F-020 (ticket asserted at every step), F-021, F-022 (latest reading, c6) and F-023 (`calls == 4`) are present at every step (the `evidence.py` output under Commands and outputs);
- the run outcomes are as cited.

The search and pooled readings, and the full table of all three readings, are in Task 5.

## Task 3: sample of run-1 hard false positives

Population: the 470 rows the scorer counts (its denominator, with repeats across queries kept): 351 distinct statements. By returned category: business-logic 166, technical-implementation 131, history 89, operations 84. By tier: documented 463, executed 5, code 2.

```
$ .venv/bin/python build/audit/sample.py build/audit/run1.json build/audit/sample.json > build/audit/sample.txt; head -3 build/audit/sample.txt
population 470 {'business-logic': 166, 'technical-implementation': 131, 'operations': 84, 'history': 89}
allocation {'business-logic': 14, 'technical-implementation': 11, 'operations': 7, 'history': 8} seed 154
distinct statements in sample 39 repeats 1
```

The sample is proportional by returned category, using largest-remainder allocation and `random.Random(154)` over each stratum sorted by (query, index).

Every text citation's version equals the on-disk version:

```
$ .venv/bin/python build/audit/siblings.py build/audit/sample.json --quiet
text citations checked: 42, version mismatches: 0
```

Without `--quiet`, it lists each row's planted siblings. Each row was read against the cited passage.

The scorer's "hard FP" label is structural (`classify_unmatched`, `bench/score.py:1558-1578`). It counts an unmatched fact that shares any entity and any cited document with any truth fact. It is not a judgement of falsity.

**Rules for (c).** I counted (c) only where the category is wrong under both the extraction prompt's own definitions (`prototypes/b_postgres/extract.py:126-128`: "history (decisions, product history, ownership, glossary)") and the truth's usage. I recorded category disagreement on (a) rows separately.

| # | Query | Cat/tier | Statement | Cited | Class | Evidence / note |
|---|---|---|---|---|---|---|
| 1 | q-explain-03 dispatch | BL/doc | For every ride.completed event it sees, dispatch credits that ride's return station with one more unit of demand. | wiki/ride-events v3 #consumers | a-full F-053 | Numbers veto: "one more unit" becomes 1, and the truth has none. F-053 was already matched in this query (a duplicate). The truth category is TI |
| 2 | q-explain-09 storm-pause | BL/doc | The storm pause threshold is a Skyglass severity reading of 3 or higher at the nearest station. | wiki/storm-pause v1 #rule (+storm-policy, GW-170, pull/19) | a-full F-022 | Claim-attribute veto: severity_threshold against min_severity. Duplicate |
| 3 | q-explain-14 ride.events | BL/doc | A ride.refunded message goes out on the ride.events queue separately whenever a refund actually gets paid. | wiki/ride-events v3 #producers | a-full F-056 | Similarity 0.57 < 0.6. Not matched in the query (a recall loss). Truth category is TI |
| 4 | q-explain-03 | BL/doc | dispatch can't touch a dockyard row directly. | wiki/data-model v6 #access | b | Verbatim. One instance of F-086, not F-086 itself |
| 5 | q-explain-13 Skyglass | BL/doc | The stormPause rule is what consumes the readings from the Skyglass integration. | wiki/skyglass v3 #related-pages | b | "Storm pause is the rule that consumes these readings" |
| 6 | q-explain-17 nightly-rebalance | BL/doc | The nightly rebalance job failure is the one alert on the rota's list that skips straight to a page ... | doc/oncall-rota #escalation | a-partial F-098 | Numbers veto ("the one alert" becomes 1). Duplicate. Truth category is OPS |
| 7 | q-explain-01 farebox | BL/executed | Ride open past 24 hours closed as lost. | test + run c1-c6 | a-full F-010 | Task-1 miss, negation veto |
| 8 | q-explain-13 | BL/doc | The 3-second timeout on GET /v2/severity is tight enough that a slow Skyglass response doesn't back up the weather poll job behind it. | wiki/skyglass v3 #endpoint | c | True as stated. It is the rationale for a technical parameter, labelled business-logic; the same-passage F-068 is TI |
| 9 | q-explain-05 single-ride-cap | BL/doc | Finance and fleet both want the ceiling on what a single ride can cost raised for the summer season. | ticket/GW-162 description | c | True as stated. It is a request or motive (history by the prompt's definition), labelled business-logic |
| 10 | q-explain-10 fault-threshold | BL/doc | A stale open maintenance ticket throws off the fault-report count if the bike gets flagged again later. | wiki/runbook-maintenance-sweep v2 #returning-bikes | b | |
| 11 | q-explain-12 Tollbooth Pay | BL/doc | Captured funds don't land in the company's account instantly; Tollbooth Pay settles two business days after the capture. claim {settlement_delay, 2, day} | doc/tollbooth-integration #settlement | a-full F-082 | The negation veto ("don't") fires before the claim check, and the claim agrees in full. Not matched in the query. Truth category is TI |
| 12 | q-explain-alias-04 grace period | BL/doc | When a member's card fails, the member does not lose their membership right away. | wiki/membership-faq v2 #grace | a-partial F-037 | Drops "3-day". Negation veto. Duplicate |
| 13 | q-explain-18 maintenance-sweep | BL/doc | When a bike crosses the fault-report threshold, the sweep locks the bike so it can't be checked out again. | wiki/runbook-maintenance-sweep v2 #threshold | a-partial F-020 | Drops 3 and 7 days. Negation ("can't"). Duplicate |
| 14 | q-explain-01 farebox | BL/doc | Past the 14-day window, farebox rejects the refund request outright. | wiki/refunds-process v3 #window | a-full F-013 | Similarity 0.36. Duplicate |
| 15 | q-explain-09 | H/doc | The storm-pause behavior codifies what the ops team was previously doing manually. | pull/19 comment-1 | a-partial F-114 | Drops severity 3. Duplicate |
| 16 | q-explain-13 | H/doc | Dispatch pulls weather data from Skyglass, the storm-severity provider. | wiki/skyglass v3 (intro) | b | Category borderline (glossary-like) |
| 17 | q-explain-01 | H/doc | farebox is owned by the fares team. | wiki/gearwell-overview v7 #services | b | Agrees with entities.yaml (E-farebox owner E-team-fares). Ownership is history per the prompt |
| 18 | q-explain-06 lost-bike-fee | H/doc | Finance requested the lost-bike fee increase to reflect current replacement cost. | ticket/GW-163 description | b | |
| 19 | q-explain-13 | H/doc | The root cause of the outage was a Skyglass API key rotation that went out without a matching update to dispatch's own configuration. | wiki/incident-2026-08-12-weather-poll v1 #summary | a-partial F-110 | Drops "6 hours" and the date. Duplicate. Truth category is OPS |
| 20 | q-explain-06 | H/doc | The Refunds process page covers how a refund on a lost-bike fee actually gets processed once support approves it. | wiki/lost-and-stolen-bikes v2 #related-pages | b (meta) | A statement about the docs, not the system |
| 21 | q-explain-12 | H/doc | The proposed retry increase is aimed at riding out longer brownouts like the one in incident GW-167. | pull/16 body | b | GW-167 is a bug ticket about capture failures during brownouts; PR 16 was not merged, and the statement says "proposed" |
| 22 | q-explain-16 feature_flags | H/doc | The Feature flags page has the general mechanics of how the dynamic_pricing flag gets read and cached. | wiki/dynamic-pricing v2 #related-pages | b (meta) | |
| 23 | q-explain-01 | OPS/doc | After the waiver window has passed, support is expected to escalate the case to the fares team instead. | wiki/support-playbook v6 #lost-bike-waiver | b | The other half of the passage from F-048 |
| 24 | q-explain-03 | OPS/doc | If the nightly rebalance job fails, on-call should check dispatch's error logs for the stack trace first. | wiki/runbook-nightly-rebalance v5 #rerun | b | Beside F-092, not F-092 |
| 25 | q-explain-03 | OPS/doc | The Dispatch scheduled jobs page covers what runs on a timer and how the jobs avoid stepping on each other. | wiki/gearwell-overview v7 #where-to-look-next | b (meta) | |
| 26 | q-explain-02 dockyard | OPS/doc | When a rider says the app is wrong, the account's open rides should be checked first. | wiki/checkout-rules v2 | b | |
| 27 | q-explain-01 | OPS/doc | Support and other teams can flag a refund case that seems to fall through the cracks, but the policy's wording only changes with fares sign-off. | doc/refund-policy #ownership | b | |
| 28 | q-explain-06 | OPS/doc | (same statement as #23) | same | b | The one repeat in the sample |
| 29 | q-explain-03 | OPS/doc | Because write access is enforced at the database level, a bug in one service can't silently corrupt another service's data. | wiki/gearwell-overview v7 #data | b | Category borderline |
| 30 | q-explain-01 | TI/doc | Three services split the work of the Gearwell platform, one per team. | wiki/gearwell-overview v7 (intro) | b | |
| 31 | q-explain-18 | TI/doc | Every one of the three jobs takes out a database lock named after itself before doing any work. | wiki/dispatch-jobs v3 #locking | a-full F-090 | Numbers ("one" and "three" against the truth's "one instance"); similarity 0.44. Not matched in the query. Truth category is OPS |
| 32 | q-explain-02 | TI/doc | Every write dockyard makes goes through its own database user, scoped only to the tables listed in the document, and no other service reaches in directly. | doc/dockyard-design #design | b | dockyard's instance of F-086. This doc is not an F-086 carrier |
| 33 | q-explain-01 | TI/doc | Farebox backs off a bit longer between each retry attempt to Tollbooth Pay. | wiki/tollbooth-pay v4 #retries | a-partial F-023 (weak) | Drops "3 times". Duplicate. Truth category is BL |
| 34 | q-explain-03 | TI/doc | The job names dispatch owns carried over unchanged through the rewrite. | wiki/dispatch-history v1 | b | |
| 35 | q-explain-03 | TI/doc | The services share one database cluster but not write access to it. | wiki/gearwell-overview v7 #data | a-partial F-086 | Negation, numbers ("one cluster"), similarity. Not matched in the query |
| 36 | q-explain-02 | TI/doc | The restriction on cross-service writes is enforced at the database level, not just by convention. | wiki/gearwell-overview v7 #data | b | |
| 37 | q-explain-01 | TI/doc | A failed renewal is not something the system has to poll for. | ticket/GW-136 comment-1 | b | The implication beside F-085, not F-085 |
| 38 | q-explain-10 | TI/doc | Mechanically a fault report is just a maintenance_tickets row with its kind set to fault_report. | wiki/glossary v8 #fault-report | a-scope F-073 | `facts_match` is True. F-073 is not expected for fault-threshold |
| 39 | q-explain-01 | TI/doc | Each service connects to the shared database with a database user of its own. | wiki/gearwell-overview v7 #data | a-partial F-086 | Similarity 0.43. Not matched in the query |
| 40 | q-explain-12 | TI/doc | Each retry gap roughly doubles the one before it so the three attempts spread out without stalling the caller for too long overall. | doc/tollbooth-integration #retries | b | The rationale beside F-061 |

`veto.py` output for the (a) rows:

```
$ .venv/bin/python build/audit/veto.py build/audit/sample.json build/results-b_postgres-model-1.json 1:F-053 2:F-022 3:F-056 6:F-098 7:F-010 11:F-082 12:F-037 13:F-020 14:F-013 15:F-114 19:F-110 31:F-090 33:F-023 35:F-086 38:F-073 39:F-086 | sed -E 's/ returned_cat=.*//'
#1 vs F-053: facts_match=False fails_on=["numbers(r=['1'] t=[])"] in_expected=True already_matched_in_query=True
#2 vs F-022: facts_match=False fails_on=['claim-attribute-veto(severity_threshold vs min_severity)'] in_expected=True already_matched_in_query=True
#3 vs F-056: facts_match=False fails_on=['similarity 0.57<0.6'] in_expected=True already_matched_in_query=False
#6 vs F-098: facts_match=False fails_on=["numbers(r=['1'] t=[])"] in_expected=True already_matched_in_query=True
#7 vs F-010: facts_match=False fails_on=['negation-veto'] in_expected=True already_matched_in_query=False
#11 vs F-082: facts_match=False fails_on=['negation-veto'] in_expected=True already_matched_in_query=False
#12 vs F-037: facts_match=False fails_on=['negation-veto', "numbers(r=[] t=['3'])", 'similarity 0.29<0.6'] in_expected=True already_matched_in_query=True
#13 vs F-020: facts_match=False fails_on=['negation-veto', "numbers(r=[] t=['3', '7'])", 'similarity 0.25<0.6'] in_expected=True already_matched_in_query=True
#14 vs F-013: facts_match=False fails_on=['similarity 0.36<0.6'] in_expected=True already_matched_in_query=True
#15 vs F-114: facts_match=False fails_on=["numbers(r=[] t=['3'])", 'similarity 0.38<0.6'] in_expected=True already_matched_in_query=True
#19 vs F-110: facts_match=False fails_on=["numbers(r=[] t=['08', '12', '2026', '6'])", 'similarity 0.39<0.6'] in_expected=True already_matched_in_query=True
#31 vs F-090: facts_match=False fails_on=["numbers(r=['1', '3'] t=['1'])", 'similarity 0.44<0.6'] in_expected=True already_matched_in_query=False
#33 vs F-023: facts_match=False fails_on=["numbers(r=[] t=['3'])", 'similarity 0.23<0.6'] in_expected=True already_matched_in_query=True
#35 vs F-086: facts_match=False fails_on=['negation-veto', "numbers(r=['1'] t=[])", 'similarity 0.25<0.6'] in_expected=True already_matched_in_query=False
#38 vs F-073: facts_match=True fails_on=['-'] in_expected=False already_matched_in_query=False
#39 vs F-086: facts_match=False fails_on=['similarity 0.43<0.6'] in_expected=True already_matched_in_query=False
```

### Counts

| Class | n / 40 | Share | Wilson 95% |
|---|---|---|---|
| (a) planted fact the scorer did not pair | 16 (7 full, 8 partial, 1 scope) | 0.40 | 0.26 to 0.55 |
| (b) true but unplanted | 22 (3 of them meta statements about the docs) | 0.55 | 0.40 to 0.69 |
| (c) right fact, wrong category (no tier errors seen) | 2 | 0.05 | 0.01 to 0.17 |
| (d) false or unsupported by its citation | 0 | 0.00 | 0.00 to 0.09 |
| True but unplanted, (b)+(c) | 24 | 0.60 | 0.45 to 0.74 |
| True as stated against the citation, (a)+(b)+(c) | 40 | 1.00 | 0.91 to 1.00 |

```
$ .venv/bin/python build/audit/extras.py build
a 16/40 share, wilson95 lo, hi = (0.4, 0.263, 0.554)
b 22/40 share, wilson95 lo, hi = (0.55, 0.398, 0.693)
c 2/40 share, wilson95 lo, hi = (0.05, 0.014, 0.165)
d 0/40 share, wilson95 lo, hi = (0.0, 0.0, 0.088)
b+c 24/40 share, wilson95 lo, hi = (0.6, 0.446, 0.737)
a+b+c 40/40 share, wilson95 lo, hi = (1.0, 0.912, 1.0)
run 1 compound number words in explain/search statements: 2 ['Member 1st fortyfive minutes free.', 'The $12.25 forty-five-minute example ride is comfortably under the $30.00 single-ride cap.']
run 2 compound number words in explain/search statements: 2 ["A forty-five-minute casual ride's total fare of $12.25 is comfortably under the cap.", 'Member 1st fortyfive minutes free.']
run 3 compound number words in explain/search statements: 2 ["A forty-five-minute casual ride's $12.25 total is comfortably under the cap.", 'Member 1st fortyfive minutes free.']
```

These are estimates from a sample of 40. Applied to the 470 rows, the (b) share suggests roughly 190 to 325 true-but-unplanted rows; that is an extrapolation, not a count.

Of the 16 (a) rows, 9 restate a planted fact already credited in the same query: #1, #2, #6, #12, #13, #14, #15, #19 and #33. Under one-to-one matching they would stay false positives with any matcher, because they are duplicates, not recall losses. Only #3, #7, #11, #31, #35 and #39, plus scope row #38, would have added a true positive.

The returned category differs from the planted fact's in 7 of the 16 (a) rows: #1, #3, #6, #11, #19, #31 and #33. The scorer's `category_accuracy` only sees matched facts.

## Task 4: causes

**(c) on the executed tier.**

- **Stage:** the test connector's rules extractor. `connectors/tests/extract_rules.py:242-302` (`_name_sentence`), used at `:1018`, takes the statement from the test's name, and `test_membership_lapses_N_days_after_failed_renewal` says "lapses", which its assertions do not prove (`tests/unit/test_memberships.py:27-29`).
- **Scorer:** the matcher credits it. The claim decides on its own when it agrees in full (`bench/score.py` `_statement_matches`, the `_claims_match` branch), and the statement path agrees too (similarity 0.86); neither can tell "lapses" from "a grace period that ends".
- **Store:** nothing in entity resolution or merging is involved.

**(c) and (d) elsewhere.** Among the executed misses on explain, nothing else is (c) or (d). The sample has no (d). Its two (c) rows are category labels chosen by the model in document extraction (`prototypes/b_postgres/extract.py:126-128` gives the definitions; `:233` sets the category and falls back to business-logic when the model's value is outside the four). Both rows had a valid enum value, so the fallback did not fire there. A rationale (#8) and a request (#9) were labelled business-logic. No stage produced a false statement in what I checked.

**Causes of the misses** (none is a wrong fact):

1. **Test connector statement builder.** `connectors/tests/extract_rules.py:242-302` (`_name_sentence`) and `:1018` make the executed statement the humanised test name. The asserted values go to `detail`, which is never matched (module docstring, points 1 and 2), or into a constant claim. That yields:
   - "fortyfive" as a single token, since only single number words are mapped;
   - "third" turned into "3rd", which the scorer then sets aside as an ordinal (`_DIGIT_ORDINAL_RE`, `bench/score.py:916`);
   - statements without the planted value: F-019's 2 bikes, and F-007's $0.10, which is only in the claim.

   Stack B uses the rules extractor for tests (`prototypes/b_postgres/__init__.py:17,68`).
2. **Scorer vetoes meeting this wording.**
   - The negation veto (`bench/score.py:824-825`) fires against F-010's own truth wording "not docked within" and against doc sentences with "don't" or "can't".
   - "one" read as a number (`bench/score.py:342-378`) vetoes "one more unit", "the one alert" and "every one of".
   - The claim-attribute veto (`bench/score.py:856-863`) is by design.
3. **Entity scope.**
   - `connectors/tests/extract_rules.py:312` (`_service_from_imports`) tags the close-ride test with `dockyard`, because it imports `dockyard.api.rides.checkin_endpoint`, so explain(dockyard) returns F-050.
   - At query time, `pipeline/resolve.py:143-154` (exact match, else nearest embedding above a threshold) resolved "POST /refunds" differently in each run: to `refunds` in run 2, to its own entity in run 1, and to nothing in run 3.
4. **Duplicates (precision only).** `pipeline/store.py:235-243` (`base_fact_id`) identifies a fact without a claim by its normalised statement. A page's sentence and a test's sentence for one rule therefore stay two rows, and the second counts as a false positive. This covers 9 of the 16 sampled (a) rows.

**Scorer observation, polarity (not a Stack B defect).** `_statement_matches` accepts "Checkin at full station allowed with overflow parking." against F-017 ("... is refused when the overflow_parking flag is off", similarity 0.62). It also accepts "Checkin at full station refused." against F-018 ("... can be checked in ...", similarity 0.60). A sentence that names no flag state never conflicts, and "refused" against "allowed" is not a negation. In these runs, one-to-one pairing in expected order happened to land each on its own fact, but a query returning only one of the two would credit it against its opposite. It needs a hard negative in the calibration set; that is a change to the marking.

**Scorer observation, compound numbers (not a Stack B defect).** `_replace_number_words` (`bench/score.py:376`) does not compose compound number words: "forty-five" yields {40, 5} and "twenty-four" yields {20, 4}. It touched one other returned statement per run here ("forty-five-minute example ride"), so its effect on these numbers is small, but it is a defect in the marking.

**Fixture observation, which I could not reconcile.** `truth/executed-audit.md`'s F-007 row says the member-ride assertion is added "c1-c6". The built repo has it only at c5 and c6: `at_threshold` counts are 0 at 638dffb, dccd9d1, ebb11d6 and dc19c79, and 2 at 710c965 and 1ab33e0. `system/history/c4/tests/unit/test_pricing.py` lacks it. So the truth's F-007 ("every charged minute of an e-bike ride") cites run/pytest-c1..c4 for a test that exercised only a casual ride at those steps. This is a change to the exam and needs Oleg's review round; it does not affect Stack B's returned fact, whose claim ($0.10 per minute) the constant assertion proves at all six steps.

## Task 5: search and pooled

This uses the same classes and method as Task 1. Search's expected set is the query's `expects` list, as `bench.score.score()` builds it. Pooled is explain and search rows summed, as `bootstrap_compare` pools them (`_executed_precision_from_samples`).

### Search: uncredited executed rows, classified

`tiers.py` uses the scorer's own functions, with search's expected set taken from the query's `expects`, exactly as `score()` builds it. Below are the first three lines per run; the per-row lines are summarised in the table:

```
$ for n in 1 2 3; do .venv/bin/python build/audit/tiers.py build/results-b_postgres-model-$n.json --dump build/audit/tiers$n.json | head -3; done
scorer explain: executed tp=35 returned=40 hard_errors=0
scorer search: executed tp=6 returned=17 hard_errors=0
recomputed: {'explain': '35/40', 'search': '6/17'} pooled 41/57
scorer explain: executed tp=36 returned=42 hard_errors=0
scorer search: executed tp=5 returned=14 hard_errors=0
recomputed: {'explain': '36/42', 'search': '5/14'} pooled 41/56
scorer explain: executed tp=35 returned=40 hard_errors=0
scorer search: executed tp=5 returned=15 hard_errors=0
recomputed: {'explain': '35/40', 'search': '5/15'} pooled 40/55
```

| Query (expects) | Statement | Runs present | Class | Evidence |
|---|---|---|---|---|
| q-search-01 (F-003, F-005, F-029) | Single ride cap $30.00. | 1, 2, 3 | a-scope F-009 | `facts_match` is True. test_single_ride_cap_30 passed at c5 and c6, which are the runs cited |
| q-search-01 | Casual ride charges $1.00 unlock fee. | 1, 3 | a-scope F-004 | `facts_match` is True; passed c1–c6 |
| q-search-02 (F-004) | Casual rate from 1st minute. | 1, 2, 3 | a-scope F-006 | `facts_match` is True through the claim CASUAL_RATE 0.25; passed c1–c6 |
| q-search-02 | Membership lapses 7 days after failed renewal. | 1, 2 | **c** (F-016 over-claim) | As above |
| q-search-02 | Lost bike fee $150.00. | 1, 3 | a-scope F-012 | `facts_match` is True; c6 only, which is correct per P-1 |
| q-search-03 (F-007, F-025) | Ebike surcharge when flag on. | 1, 2, 3 | a-full F-007 (value in the claim) | **In scope**: the claim-attribute veto, as on explain |
| q-search-04 (F-010, F-012, F-026) | Ebike surcharge when flag on. | 1, 2, 3 | a-scope F-007 (and the same veto) | |
| q-search-06 (F-050, F-057) | rideEvents counts ride.completed toward the return station's demand. | 1, 2, 3 | a-scope F-053 | vitest c1–c6 passed |
| q-search-09 (F-054) | rideEvents counts ride.completed toward the return station's demand. | 1, 2, 3 | a-scope F-053 | |
| q-search-09 | Station status reports fill ratio. | 1, 2, 3 | a-scope F-052 | Passed c1–c6 |
| q-impact-05 (F-017, F-051) | Checkin at full station allowed with overflow parking. | 1, 2, 3 | a-scope F-018 | `facts_match` also pairs it with F-017, which was already matched (see the scorer observation) |

That gives 11, 9 and 10 rows. Of these, one per run is in scope (q-search-03). Runs 1 and 2 have one (c); the rest are planted executed facts, correctly tiered, returned for a query whose 1–3 expected facts did not include them.

### Recomputed precision, three readings plus one

```
$ .venv/bin/python build/audit/readings.py build
=== run 1
  explain  scorer 35/40 = 0.875 | audit (a)+(b) 36/40 = 0.900 | audit (a) only 36/40 = 0.900 | strict (terse echoes wrong) 31/40 = 0.775 | classes {'credited': 31, 'c': 4, 'a': 5}
  search   scorer 6/17 = 0.353 | audit (a)+(b) 16/17 = 0.941 | audit (a) only 16/17 = 0.941 | strict (terse echoes wrong) 13/17 = 0.765 | classes {'a': 10, 'c': 1, 'credited': 6}
  pooled   scorer 41/57 = 0.719 | audit (a)+(b) 52/57 = 0.912 | audit (a) only 52/57 = 0.912 | strict (terse echoes wrong) 44/57 = 0.772 | classes {'credited': 37, 'c': 5, 'a': 15}
  distinct executed-labelled facts (explain+search, by fact id): audit 25/27 = 0.926 | strict 20/27 = 0.741 | c: ['Membership lapses 3 days after failed renewal.', 'Membership lapses 7 days after failed renewal.']
  credited rows that are c (scorer over-credit): 4 ({'explain': 4})
=== run 2
  explain  scorer 36/42 = 0.857 | audit (a)+(b) 38/42 = 0.905 | audit (a) only 38/42 = 0.905 | strict (terse echoes wrong) 33/42 = 0.786 | classes {'credited': 32, 'c': 4, 'a': 6}
  search   scorer 5/14 = 0.357 | audit (a)+(b) 13/14 = 0.929 | audit (a) only 13/14 = 0.929 | strict (terse echoes wrong) 10/14 = 0.714 | classes {'a': 8, 'c': 1, 'credited': 5}
  pooled   scorer 41/56 = 0.732 | audit (a)+(b) 51/56 = 0.911 | audit (a) only 51/56 = 0.911 | strict (terse echoes wrong) 43/56 = 0.768 | classes {'credited': 37, 'c': 5, 'a': 14}
  distinct executed-labelled facts (explain+search, by fact id): audit 25/27 = 0.926 | strict 20/27 = 0.741 | c: ['Membership lapses 3 days after failed renewal.', 'Membership lapses 7 days after failed renewal.']
  credited rows that are c (scorer over-credit): 4 ({'explain': 4})
=== run 3
  explain  scorer 35/40 = 0.875 | audit (a)+(b) 36/40 = 0.900 | audit (a) only 36/40 = 0.900 | strict (terse echoes wrong) 31/40 = 0.775 | classes {'credited': 31, 'c': 4, 'a': 5}
  search   scorer 5/15 = 0.333 | audit (a)+(b) 15/15 = 1.000 | audit (a) only 15/15 = 1.000 | strict (terse echoes wrong) 12/15 = 0.800 | classes {'a': 10, 'credited': 5}
  pooled   scorer 40/55 = 0.727 | audit (a)+(b) 51/55 = 0.927 | audit (a) only 51/55 = 0.927 | strict (terse echoes wrong) 43/55 = 0.782 | classes {'credited': 36, 'c': 4, 'a': 15}
  distinct executed-labelled facts (explain+search, by fact id): audit 25/27 = 0.926 | strict 20/27 = 0.741 | c: ['Membership lapses 3 days after failed renewal.', 'Membership lapses 7 days after failed renewal.']
  credited rows that are c (scorer over-credit): 4 ({'explain': 4})
```

| Reading | Scorer (runs 1, 2, 3) | Audit (a)+(b) | Audit (a) only | Strict |
|---|---|---|---|---|
| Explain | 0.875, 0.857, 0.875 | 0.900, 0.905, 0.900 | same | 0.775, 0.786, 0.775 |
| Search | 0.353, 0.357, 0.333 | 0.941, 0.929, 1.000 | same | 0.765, 0.714, 0.800 |
| Pooled explain+search (the bootstrap's) | 0.719, 0.732, 0.727 | 0.912, 0.911, 0.927 | same | 0.772, 0.768, 0.782 |
| Distinct executed facts, query-independent | (no scorer reading) | 0.926 (25/27) in every run | same | 0.741 (20/27) |

- **(a)+(b) and (a) only are equal everywhere** because no uncredited executed row is (b).
- **Audit columns:** the 4 to 5 over-claiming "lapses" rows are counted wrong; a-scope rows are counted right, since each is a planted fact proven by its run.
- **Strict column:** also counts wrong the five statements that do not state their fact on their own:
  - the value only in the claim: "Casual rate from 1st minute.", "Member rate after free minutes.", "Ebike surcharge when flag on.";
  - a dropped clause or condition: "3rd checkout refused.", "Checkin at full station refused.".
- **The scorer's errors partly cancel:** it misses 5 or 6 correct rows on explain and over-credits 4 wrong ones.

### Which reading the bar should be judged on

D-013 defines the measure as tier accuracy: "executed-tier precision first (a fact claimed executed without a passing run is a hard error)". The bar gates "the tests-as-evidence claim". That is a property of the facts B labels executed, not of which query surfaced them. So the bar should be judged on a reading that measures tier correctness and nothing else.

- **Search is a relevance measure, not a tier measure.** Its expected set is the 1–3 facts a query's `expects` names. In run 1, 9 of its 11 uncredited rows are correct executed facts that were simply not on the list. Its 0.33–0.36 measures retrieval, and judging the tests-as-evidence bar on it would be wrong.
- **Pooled inherits that relevance penalty.** 17, 14 and 15 of its 57, 56 and 55 rows are search rows. It is the right input for the paired bootstrap's arm comparison only if both arms are read as retrieval-and-tier combined, and that should be stated wherever the +0.60 is quoted.
- **Explain is the closest of the scorer's readings.** Its expected set is every truth fact about the entity, so scope effects are small: 1–2 rows per run. It still weights each fact by how many queries surface it; "lapses" counts 4 times.
- **Recommendation: a distinct-fact reading.** Each distinct executed-labelled fact counts once, judged against truth whatever the query: 27 per run here. This is query-independent and deterministic, because the rules extractor produces the same executed set every run. The scorer does not compute it today. Adding it is a change to the scorer and needs a review round, so it is Oleg's call. Until then, explain is the reading to quote.

On either the recommended reading or explain, the audited value is below the bar: 0.926, or 0.900–0.905. So is pooled (0.911–0.927). Only search run 3 (15/15) reaches it, and search is the wrong reading.

## What this means for the 0.95 bar

An earlier draft of this audit said the bar was met under audit; it had trusted the scorer's credited rows (Task 2).

**Under the scorer**, Stack B misses the bar on every reading:
- explain: 0.857–0.875;
- search: 0.333–0.357;
- pooled: 0.719–0.732.

**Under this audit**, counting (a)+(b) correct (identical to (a) only), it still misses on every reading that measures tier correctness:
- distinct facts: 0.926 in all three runs (25 of 27);
- explain: 0.900, 0.905, 0.900;
- pooled: 0.912, 0.911, 0.927.

Search alone audits at 0.941, 0.929 and 1.000. It is the only reading that reaches the bar (run 3, 15/15), but it is a relevance reading (Task 5), and it reaches 1.000 in run 3 only because the "lapses" statement happened not to come up in that run's search results.

The gap now has two parts:

1. **The scorer under-credits correct rows.** The matcher's statement rules meet test-name statements, and search and pooled readings are entity- or `expects`-scoped. This moved search from about 0.35 to 0.93–1.00 and pooled from about 0.72 to about 0.91.
2. **Two genuine over-claims.** The rules extractor turns `test_membership_lapses_{3,7}_days_after_failed_renewal` into "Membership lapses N days after failed renewal." The tests assert a grace deadline; no code lapses a membership. These are the only wrong executed facts in B's returns, and they are deterministic: the same two in every run. The scorer currently credits them, which hides the problem.

Removing those two from the extractor's output, or narrowing them to what the test asserts, would put every reading at 1.000: distinct 25/25; explain 36/36, 38/38 and 36/36; search 16/16, 13/13 and 15/15; pooled 52/52, 51/51 and 51/51.

The **strict sensitivity**, with statements that do not state their fact on their own also counted wrong, shows the rest of the margin: distinct 0.741; explain 0.775, 0.786, 0.775; search 0.765, 0.714, 0.800; pooled 0.772, 0.768, 0.782. Five of the 27 distinct executed facts carry their value only in the claim, or drop a condition.

**What to fix, and whose call it is:**
- **Connector (B's to fix).** The fix is in the connector's statement builder, `extract_rules._name_sentence`. Build the statement from what the assertions prove, using the `detail` clauses and the claim, never from words in the test name the assertions do not prove. As written it breaks its own module promise ("never past what the test's assertion actually proves", `connectors/tests/extract_rules.py:1-4`).
- **Scorer (Oleg's call; each needs a review round).** Whether the scorer should score executed-tier precision per distinct fact rather than per query row; whether the bootstrap should keep pooling search into it; and the matcher's polarity gap (Result, Findings).

## Not verified

- Scope. The a-scope rows (on explain, F-050 under `dockyard` and F-014 under `POST /refunds` in run 2; on search, nine of 11, 7 of 9 and nine of 10) count as correct for executed-tier precision, because each fact is planted and proven by its run. They are still off-target returns for the query they appeared under. The audited figures in Tasks 2 and 5 say whether the executed claims are right; they say nothing about retrieval relevance.
- Truth of documented-tier rows against the code. I checked them against the cited passage only, which is what the documented tier asserts.
- Earlier versions of wiki pages or docs. Each document has one version on disk, and every sampled citation named that version.
- Executed facts B holds but never returned in any query: the results files carry returned facts only. (The returned and credited ones are checked: 23 distinct pairs per run, against their assertions and runs; that check found the F-015/F-016 over-claim.)
- Runs 2 and 3's hard false positives. Only run 1 was sampled.
- Category judgements. These are mine. For that reason the (b)+(c) share is the more robust "true but unplanted" figure, and I report (b) alone beside it.

## Appendix: the audit scripts

As run, re-wrapped by `ruff format` only. Save each to `build/audit/<name>.py` and run from `spike/`. `misses.py` comes first: `diagnose.py`, `sample.py` and `veto.py` read its dumps, and `siblings.py` and `veto.py` read `sample.py`'s output.

### `misses.py`

```
$ for n in 1 2 3; do .venv/bin/python build/audit/misses.py build/results-b_postgres-model-$n.json --dump build/audit/run$n.json; done
```

```python
"""Executed-tier misses and unmatched hard false positives, reproduced with
the scorer's own functions (bench/score.py), not a reimplementation.

Run from spike/: .venv/bin/python <this> RESULTS.json [--dump OUT.json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from bench import score as S  # noqa: E402
from bench.truth import load_truth  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--dump")
    a = ap.parse_args()
    results = json.loads(Path(a.results).read_text())
    commits = json.loads(Path("build/commits.json").read_text())
    truth = load_truth(Path("truth"))
    rep = S.score(results, Path("truth"), commits)
    ex = rep["surfaces"]["explain"]
    print(
        "scorer explain: tp=%s returned=%s hard_fp=%s unplanted=%s"
        % (
            ex["tp"],
            ex["returned"],
            ex.get("hard_false_positives"),
            len(ex.get("unplanted_facts") or []),
        )
    )
    t = ex["tier"]
    print(
        "scorer executed: tp=%s returned=%s expected=%s hard_errors=%s"
        % (t["tp_executed"], t["returned_executed"], t["expected_executed"], t["hard_errors"])
    )

    alias_index = S.build_alias_index(truth)
    mention_index = S.build_mention_index(truth)
    out = {"executed_misses": [], "hard_fp": [], "tally": {}}
    tp = ret = hfp = unp = tpe = rete = 0
    for q in results["queries"]:
        if q["surface"] != "explain":
            continue
        raw_entity = q["params"]["entity"]
        ids, _ = S.align_entities([raw_entity], alias_index, truth.entities)
        entity_id = ids[0] if ids else None
        expected = {
            fid: f for fid, f in truth.facts.items() if entity_id and entity_id in f.entities
        }
        resolved = [S.resolve_fact_entities(rf, alias_index, truth.entities) for rf in q["result"]]
        matches, _unc = S.match_facts(resolved, expected, commits, mention_index)
        by_obj = {id(rf): fid for rf, fid in matches}
        unmatched = [
            rf
            for rf in resolved
            if id(rf) not in by_obj and S._citation_documents(rf.get("citations"))
        ]
        hard, unpl = S.classify_unmatched(unmatched, truth.facts)
        hard_ids = {id(x) for x in hard}
        tp += len(matches)
        ret += len(resolved)
        hfp += len(hard)
        unp += len(unpl)
        matched_ids = set(by_obj.values())
        for i, rf in enumerate(resolved):
            # every truth fact facts_match would accept, ignoring the query's expected subset
            any_match = [
                fid for fid, tf in truth.facts.items() if S.facts_match(rf, tf, mention_index)
            ]
            row = {
                "query": q["id"],
                "query_entity": raw_entity,
                "index": i,
                "statement": rf.get("statement"),
                "category": rf.get("category"),
                "tier": rf.get("tier"),
                "entities": rf.get("entities"),
                "unresolved": rf.get("_unresolved_entities"),
                "raw_entities": q["result"][i].get("entities"),
                "claim": q["result"][i].get("claim"),
                "citations": rf.get("citations"),
                "id": rf.get("id"),
                "matched_to": by_obj.get(id(rf)),
                "matched_tier": truth.facts[by_obj[id(rf)]].tier if id(rf) in by_obj else None,
                "facts_match_any": any_match,
                "facts_match_in_expected_already_matched": [
                    f
                    for f in any_match
                    if f in expected and f in matched_ids and f != by_obj.get(id(rf))
                ],
                "facts_match_outside_expected": [f for f in any_match if f not in expected],
                "class": "matched"
                if id(rf) in by_obj
                else (
                    "hard_fp"
                    if id(rf) in hard_ids
                    else (
                        "uncited" if not S._citation_documents(rf.get("citations")) else "unplanted"
                    )
                ),
            }
            if rf.get("tier") == S._EXECUTED:
                rete += 1
                mt = row["matched_tier"]
                if mt == S._EXECUTED:
                    tpe += 1
                else:
                    out["executed_misses"].append(row)
            if row["class"] == "hard_fp":
                out["hard_fp"].append(row)
    print(
        "recomputed explain: tp=%d returned=%d hard_fp=%d unplanted=%d executed tp=%d returned=%d"
        % (tp, ret, hfp, unp, tpe, rete)
    )
    if a.dump:
        Path(a.dump).write_text(json.dumps(out, indent=1, default=str))
    print("executed misses: %d" % len(out["executed_misses"]))
    for r in out["executed_misses"]:
        docs = [
            "%s@%s:%s" % (c.get("document"), (c.get("version") or "")[:7], c.get("location"))
            for c in r["citations"]
        ]
        print(
            "-",
            r["query"],
            "|",
            r["statement"],
            "| ents",
            r["entities"],
            "unres",
            r["unresolved"],
            "| matched_to",
            r["matched_to"],
            r["matched_tier"],
            "| any",
            r["facts_match_any"],
            "| cls",
            r["class"],
        )
        print("   claim", r["claim"])
        for d in docs:
            print("   ", d)


main()
```

### `diagnose.py`

```
$ .venv/bin/python build/audit/diagnose.py build/audit/run2.json build/results-b_postgres-model-2.json
```

```python
"""For a dumped row, step through facts_match against named truth facts using
the scorer's own helpers.
Run from spike/: python diagnose.py runN.json RESULTS.json"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from bench import score as S  # noqa: E402
from bench.truth import load_truth  # noqa: E402

truth = load_truth(Path("truth"))
mi = S.build_mention_index(truth)
ai = S.build_alias_index(truth)
rows = json.loads(Path(sys.argv[1]).read_text())["executed_misses"]
results = json.loads(Path(sys.argv[2]).read_text())
qents = {q["id"]: q["params"].get("entity") for q in results["queries"]}
# candidate truth facts: every executed (or demoted) truth fact sharing a cited document
for r in rows:
    qe = qents[r["query"]]
    qid = (S.align_entities([qe], ai, truth.entities)[0] or [None])[0]
    print("=" * 100)
    print(r["query"], "query entity", qe, "->", qid, "| stmt:", r["statement"])
    print(
        "  raw entities",
        r["raw_entities"],
        "-> resolved",
        r["entities"],
        "unresolved",
        r["unresolved"],
    )
    rdocs = S._citation_documents(r["citations"])
    rf = {k: r[k] for k in ("statement", "entities", "citations")}
    claim = r["claim"]
    if claim is not None:
        cr, _ = S.align_entities([str(claim.get("entity", ""))], ai, truth.entities, r["category"])
        rf["claim"] = {**claim, "_resolved_entities": cr}
    for fid, tf in truth.facts.items():
        tdocs = {c.document for c in tf.carriers}
        rlocs = {c.get("location") for c in r["citations"]}
        if not any(
            c.location in rlocs or (c.location or "").split("::")[-1] in rlocs for c in tf.carriers
        ):
            continue
        if not (rdocs & tdocs) or not any(
            d.startswith("code/tests") or d.startswith("run/") for d in rdocs & tdocs
        ):
            continue
        ent = bool(set(r["entities"]) & set(tf.entities))
        neg = S._has_negation(r["statement"]) != S._has_negation(tf.statement)
        flag = S._flag_state_conflict(r["statement"], tf.statement)
        ment = S._entity_mention_conflict(r["statement"], tf.statement, mi)
        if S._names_http_code(tf.statement):
            rn = S._number_tokens(S._DIGIT_ORDINAL_RE.sub(" ", r["statement"]))
            tn = S._number_tokens(S._DIGIT_ORDINAL_RE.sub(" ", tf.statement))
        else:
            rn = S._number_tokens(S._without_http_codes(r["statement"]))
            tn = S._number_tokens(S._without_http_codes(tf.statement))
        sim = S._text_similarity(r["statement"], tf.statement)
        sm = S._statement_matches(r["statement"], tf.statement, mi, rf.get("claim"), tf.claim)
        print(
            f"  vs {fid} [{tf.tier}] in_expected={qid in tf.entities} entity_overlap={ent} "
            f"neg_mismatch={neg} flag_conflict={flag} mention_conflict={ment} "
            f"nums r={sorted(rn)} t={sorted(tn)} sim={sim:.3f} stmt_match={sm} "
            f"facts_match={S.facts_match(rf, tf, mi)}"
        )
        print(f"     truth: {tf.statement}")
        print(f"     truth entities {list(tf.entities)} claim {tf.claim}")
```

### `sample.py`

```
$ .venv/bin/python build/audit/sample.py build/audit/run1.json build/audit/sample.json > build/audit/sample.txt
```

```python
"""Stratified sample of run-1 explain hard false positives (as the scorer
counts them: 470 rows, duplicates across queries included), proportional to
the returned fact's category, largest-remainder allocation, fixed seed.
Run from spike/: python sample.py run1.json OUT.json"""

import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SEED = 154
N = 40
rows = json.loads(Path(sys.argv[1]).read_text())["hard_fp"]
by_cat = defaultdict(list)
for r in rows:
    by_cat[r["category"]].append(r)
total = len(rows)
quota = {c: N * len(v) / total for c, v in by_cat.items()}
alloc = {c: int(q) for c, q in quota.items()}
for c in sorted(quota, key=lambda c: quota[c] - alloc[c], reverse=True)[: N - sum(alloc.values())]:
    alloc[c] += 1
print("population", total, {c: len(v) for c, v in by_cat.items()})
print("allocation", alloc, "seed", SEED)
rng = random.Random(SEED)
sample = []
for c in sorted(by_cat):
    pool = sorted(by_cat[c], key=lambda r: (r["query"], r["index"]))
    sample.extend(rng.sample(pool, alloc[c]))
stmts = Counter(r["statement"] for r in sample)
print("distinct statements in sample", len(stmts), "repeats", sum(v - 1 for v in stmts.values()))


def section(md: str, anchor: str) -> str:
    lines = md.splitlines()
    want = anchor.lstrip("#")
    out, on, level = [], False, 0
    for ln in lines:
        m = re.match(r"^(#+)\s+(.*)", ln)
        if m:
            slug = re.sub(r"[^\w\- ]", "", m.group(2).strip().lower()).replace(" ", "-")
            if on and len(m.group(1)) <= level:
                break
            if slug == want:
                on, level = True, len(m.group(1))
        if on:
            out.append(ln)
    return "\n".join(out).strip() or "(anchor not found)"


def cited_text(c):
    doc, loc = c.get("document", ""), c.get("location") or ""
    kind, _, rest = doc.partition("/")
    root = Path("sources")
    try:
        if kind in ("wiki", "doc"):
            p = root / ("wiki" if kind == "wiki" else "docs") / f"{rest}.md"
            md = p.read_text()
            ver = re.search(r"^version:\s*(.*)$", md, re.M)
            return f"[on-disk version {ver.group(1) if ver else '?'}] " + section(md, loc)
        if kind in ("ticket", "pull"):
            p = root / ("tickets" if kind == "ticket" else "pulls") / f"{rest}.json"
            d = json.loads(p.read_text())
            if loc in ("description", "body"):
                return d.get(loc) or ""
            m = re.match(r"comment-(\d+)", loc)
            if m:
                cs = d.get("comments") or []
                k = int(m.group(1))
                for cm in cs:
                    if cm.get("id") == loc:
                        return json.dumps(cm)
                return json.dumps(cs[k - 1]) if 0 < k <= len(cs) else "(comment not found)"
            return "(location kind not handled)"
    except FileNotFoundError:
        return "(document not found)"
    return "(not a text document)"


for i, r in enumerate(sample, 1):
    r["sample_no"] = i
    r["cited"] = [{**c, "text": cited_text(c)} for c in r["citations"]]
Path(sys.argv[2]).write_text(json.dumps(sample, indent=1))
for r in sample:
    print(
        f"\n#{r['sample_no']} [{r['category']}/{r['tier']}] {r['query']}({r['query_entity']}) :: {r['statement']}"
    )
    print(
        f"   entities {r['raw_entities']} -> {r['entities']}; claim {r['claim']}; facts_match_any {r['facts_match_any']}"
    )
    for c in r["cited"]:
        print(f"   - {c['document']}@{c.get('version')} {c.get('location')}: {c['text'][:700]!r}")
```

### `siblings.py`

```
$ .venv/bin/python build/audit/siblings.py build/audit/sample.json   # add --quiet for the version check alone
```

```python
"""For each sampled row: check every text citation's version against the
on-disk document version, and list the planted facts that share an entity
and a document with it (why the scorer calls it a hard FP).
Run from spike/: python siblings.py sample.json [--quiet]"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from bench import score as S  # noqa: E402
from bench.truth import load_truth  # noqa: E402

t = load_truth(Path("truth"))
smp = json.loads(Path(sys.argv[1]).read_text())
quiet = "--quiet" in sys.argv


def ondisk(doc):
    kind, _, rest = doc.partition("/")
    p = {
        "wiki": Path("sources/wiki") / f"{rest}.md",
        "doc": Path("sources/docs") / f"{rest}.md",
        "ticket": Path("sources/tickets") / f"{rest}.json",
        "pull": Path("sources/pulls") / f"{rest}.json",
    }.get(kind)
    if not p or not p.exists():
        return None
    s = p.read_text()
    if kind == "wiki":
        return re.search(r"^version:\s*(.*)$", s, re.M).group(1)
    if kind == "doc":
        return re.search(r"^headRevisionId:\s*'?([^'\n]*)", s, re.M).group(1)
    d = json.loads(s)
    return d.get("updated") or d.get("closed")


checked = mismatched = 0
for r in smp:
    vm = [
        (c["document"], c.get("version"), ondisk(c["document"]))
        for c in r["citations"]
        if not c["document"].startswith(("code/", "run/"))
    ]
    checked += len(vm)
    bad = [v for v in vm if str(v[1]) != str(v[2])]
    mismatched += len(bad)
    if quiet:
        continue
    docs = {c["document"] for c in r["citations"]}
    print(f"#{r['sample_no']} {r['statement'][:90]}")
    if bad:
        print("   VERSION MISMATCH", bad)
    for fid, tf in t.facts.items():
        if set(r["entities"]) & set(tf.entities) and docs & {c.document for c in tf.carriers}:
            print(
                f"   ~ {fid} [{tf.category}/{tf.tier}] sim={S._text_similarity(r['statement'], tf.statement):.2f}: {tf.statement}"
            )
print(f"text citations checked: {checked}, version mismatches: {mismatched}")
```

### `veto.py`

```
$ .venv/bin/python build/audit/veto.py build/audit/sample.json build/results-b_postgres-model-1.json 1:F-053 2:F-022 ...   # pairs as in Task 3
```

```python
"""Which facts_match step rejects a sampled row against a named planted fact,
and whether that fact was in the query's expected set / already matched there.
Run from spike/: python veto.py sample.json RESULTS.json N:F-xxx ..."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from bench import score as S  # noqa: E402
from bench.truth import load_truth  # noqa: E402

t = load_truth(Path("truth"))
mi, ai = S.build_mention_index(t), S.build_alias_index(t)
commits = json.loads(Path("build/commits.json").read_text())
smp = {r["sample_no"]: r for r in json.loads(Path(sys.argv[1]).read_text())}
res = json.loads(Path(sys.argv[2]).read_text())
qs = {q["id"]: q for q in res["queries"]}


def matched_in_query(qid):
    q = qs[qid]
    eid = (S.align_entities([q["params"]["entity"]], ai, t.entities)[0] or [None])[0]
    exp = {f: tf for f, tf in t.facts.items() if eid and eid in tf.entities}
    resolved = [S.resolve_fact_entities(rf, ai, t.entities) for rf in q["result"]]
    m, _ = S.match_facts(resolved, exp, commits, mi)
    return exp, {fid for _, fid in m}


for arg in sys.argv[3:]:
    n, fid = arg.split(":")
    r = smp[int(n)]
    tf = t.facts[fid]
    rf = {"statement": r["statement"], "entities": r["entities"], "citations": r["citations"]}
    if r["claim"] is not None:
        cr, _ = S.align_entities([str(r["claim"].get("entity", ""))], ai, t.entities, r["category"])
        rf["claim"] = {**r["claim"], "_resolved_entities": cr}
    rs, ts = r["statement"], tf.statement
    steps = []
    if S._has_negation(rs) != S._has_negation(ts):
        steps.append("negation-veto")
    if S._flag_state_conflict(rs, ts):
        steps.append("flag-state-veto")
    if S._entity_mention_conflict(rs, ts, mi):
        steps.append("mention-veto")
    rc, tc = rf.get("claim"), tf.claim
    if rc and tc and S._claim_is_comparable(rc, tc) and not S._claims_match(rc, tc):
        if not S._claim_values_match(
            rc.get("value"), tc.get("value"), rc.get("unit"), tc.get("unit")
        ):
            steps.append("claim-value-veto")
        elif not S._attributes_match(rc.get("attribute"), tc.get("attribute")):
            steps.append(f"claim-attribute-veto({rc.get('attribute')} vs {tc.get('attribute')})")
    if S._names_http_code(ts):
        rn = S._number_tokens(S._DIGIT_ORDINAL_RE.sub(" ", rs))
        tn = S._number_tokens(S._DIGIT_ORDINAL_RE.sub(" ", ts))
    else:
        rn = S._number_tokens(S._without_http_codes(rs))
        tn = S._number_tokens(S._without_http_codes(ts))
    if not S._numbers_compatible(rn, tn):
        steps.append(f"numbers(r={sorted(rn)} t={sorted(tn)})")
    sim = S._text_similarity(rs, ts)
    if sim < S._SIMILARITY_THRESHOLD:
        steps.append(f"similarity {sim:.2f}<0.6")
    exp, matched = matched_in_query(r["query"])
    print(
        f"#{n} vs {fid}: facts_match={S.facts_match(rf, tf, mi)} fails_on={steps or ['-']} "
        f"in_expected={fid in exp} already_matched_in_query={fid in matched} "
        f"returned_cat={r['category']} truth_cat={tf.category} truth_tier={tf.tier} claim_r={r['claim']} claim_t={tc}"
    )
```

### `extras.py`

```
$ .venv/bin/python build/audit/extras.py build
```

```python
"""Wilson intervals for the sample counts, and the compound-number-word scan.
Run from spike/: python extras.py RESULTS_DIR"""

import json
import math
import re
import sys


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(p, 3), round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)


for lab, k in [("a", 16), ("b", 22), ("c", 2), ("d", 0), ("b+c", 24), ("a+b+c", 40)]:
    print(lab, f"{k}/40", "share, wilson95 lo, hi =", wilson(k, 40))
pat = re.compile(
    r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ]?(one|two|three|four|five|six|seven|eight|nine)\b",
    re.I,
)
for n in (1, 2, 3):
    r = json.load(open(f"{sys.argv[1]}/results-b_postgres-model-{n}.json"))
    hits = sorted(
        {
            f["statement"]
            for q in r["queries"]
            if q["surface"] in ("explain", "search")
            for f in q["result"]
            if pat.search(f["statement"])
        }
    )
    print(f"run {n} compound number words in explain/search statements: {len(hits)} {hits}")
```

### `tiers.py`

```
$ for n in 1 2 3; do .venv/bin/python build/audit/tiers.py build/results-b_postgres-model-$n.json --dump build/audit/tiers$n.json; done
```

```python
"""Executed-tier misses on explain AND search, with the scorer's own
functions (same method as misses.py; search's expected set is the query's
`expects`, exactly as bench.score.score() builds it).
Run from spike/: python tiers.py RESULTS.json --dump OUT.json"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from bench import score as S  # noqa: E402
from bench.truth import load_truth  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("results")
ap.add_argument("--dump")
a = ap.parse_args()
results = json.loads(Path(a.results).read_text())
commits = json.loads(Path("build/commits.json").read_text())
truth = load_truth(Path("truth"))
rep = S.score(results, Path("truth"), commits)
ai, mi = S.build_alias_index(truth), S.build_mention_index(truth)
for s in ("explain", "search"):
    t = rep["surfaces"][s]["tier"]
    print(
        f"scorer {s}: executed tp={t['tp_executed']} returned={t['returned_executed']} hard_errors={t['hard_errors']}"
    )
out = {"explain": [], "search": []}
tot = {}
for q in results["queries"]:
    s = q["surface"]
    if s not in ("explain", "search"):
        continue
    if s == "explain":
        ids, _ = S.align_entities([q["params"]["entity"]], ai, truth.entities)
        eid = ids[0] if ids else None
        expected = {f: tf for f, tf in truth.facts.items() if eid and eid in tf.entities}
    else:
        expected = {
            f: truth.facts[f] for f in (q["params"].get("expects") or []) if f in truth.facts
        }
    resolved = [S.resolve_fact_entities(rf, ai, truth.entities) for rf in q["result"]]
    matches, _ = S.match_facts(resolved, expected, commits, mi)
    by_obj = {id(rf): fid for rf, fid in matches}
    matched = set(by_obj.values())
    tp_e = ret_e = 0
    for i, rf in enumerate(resolved):
        if rf.get("tier") != S._EXECUTED:
            continue
        ret_e += 1
        fid = by_obj.get(id(rf))
        if fid and truth.facts[fid].tier == S._EXECUTED:
            tp_e += 1
            continue
        anym = [f for f, tf in truth.facts.items() if S.facts_match(rf, tf, mi)]
        out[s].append(
            {
                "query": q["id"],
                "params": q["params"],
                "statement": rf["statement"],
                "id": rf.get("id"),
                "entities": rf["entities"],
                "unresolved": rf.get("_unresolved_entities"),
                "claim": q["result"][i].get("claim"),
                "citations": rf.get("citations"),
                "matched_to": fid,
                "matched_tier": truth.facts[fid].tier if fid else None,
                "facts_match_any": anym,
                "any_in_expected": [f for f in anym if f in expected],
                "any_already_matched_in_query": [f for f in anym if f in matched],
                "expects": sorted(expected),
            }
        )
    t = tot.setdefault(s, [0, 0])
    t[0] += tp_e
    t[1] += ret_e
print(
    "recomputed:",
    {s: f"{v[0]}/{v[1]}" for s, v in tot.items()},
    "pooled",
    f"{tot['explain'][0] + tot['search'][0]}/{tot['explain'][1] + tot['search'][1]}",
)
for r in out["search"]:
    runs = sorted({c["document"] for c in r["citations"] if c["document"].startswith("run/")})
    print(
        f"- {r['query']} | {r['statement']} | id {r['id']} | any {r['facts_match_any']} in_exp {r['any_in_expected']} "
        f"already {r['any_already_matched_in_query']} | expects {r['expects']} | runs {runs}"
    )
if a.dump:
    Path(a.dump).write_text(json.dumps(out, indent=1, default=str))
```

### `readings.py`

```
$ .venv/bin/python build/audit/readings.py build
```

```python
"""Executed-tier precision under the audit, three readings (explain, search,
pooled explain+search, as the bootstrap pools them) plus a query-independent
distinct-fact reading. Every executed-labelled row is classed:
  credited  - scorer matched it to an executed truth fact (tp_executed)
  a         - uncredited, a planted executed fact (a-full/partial/scope, see AUDIT.md)
  c         - claims past its test's assertion (the 'Membership lapses N days' echoes:
              truth/executed-audit.md F-015/F-016 verdict b)
A credited row whose statement is one of the C_STATEMENTS is re-classed c.
Run from spike/: python readings.py RESULTS_DIR"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from bench import score as S  # noqa: E402
from bench.truth import load_truth  # noqa: E402

C_STATEMENTS = {
    "Membership lapses 3 days after failed renewal.",
    "Membership lapses 7 days after failed renewal.",
}
# Statements that do not state their fact on their own, for the strict
# sensitivity row: the value only in the claim (0.25, 0.10, 0.15), or a
# dropped clause or condition (the 2-bike limit; the overflow flag being off).
TERSE = {
    "Casual rate from 1st minute.",
    "Ebike surcharge when flag on.",
    "Member rate after free minutes.",
    "3rd checkout refused.",
    "Checkin at full station refused.",
}
t = load_truth(Path("truth"))
ai, mi = S.build_alias_index(t), S.build_mention_index(t)
commits = json.loads(Path("build/commits.json").read_text())


def classify(results):
    rows = []
    for q in results["queries"]:
        s = q["surface"]
        if s not in ("explain", "search"):
            continue
        if s == "explain":
            ids, _ = S.align_entities([q["params"]["entity"]], ai, t.entities)
            eid = ids[0] if ids else None
            exp = {f: tf for f, tf in t.facts.items() if eid and eid in tf.entities}
        else:
            exp = {f: t.facts[f] for f in (q["params"].get("expects") or []) if f in t.facts}
        res = [S.resolve_fact_entities(rf, ai, t.entities) for rf in q["result"]]
        m, _ = S.match_facts(res, exp, commits, mi)
        by = {id(rf): fid for rf, fid in m}
        for rf in res:
            if rf.get("tier") != S._EXECUTED:
                continue
            fid = by.get(id(rf))
            credited = bool(fid) and t.facts[fid].tier == S._EXECUTED
            if rf["statement"] in C_STATEMENTS:
                cls = "c"
            elif credited:
                cls = "credited"
            else:
                cls = "a"  # every uncredited row was read by hand; see AUDIT.md tables
            rows.append(
                {
                    "surface": s,
                    "query": q["id"],
                    "statement": rf["statement"],
                    "id": rf.get("id"),
                    "credited": credited,
                    "cls": cls,
                }
            )
    return rows


def ratio(rows, ok):
    n = len(rows)
    k = sum(1 for r in rows if ok(r))
    return f"{k}/{n} = {k / n:.3f}" if n else "n/a"


for n in (1, 2, 3):
    res = json.loads(Path(f"{sys.argv[1]}/results-b_postgres-model-{n}.json").read_text())
    rows = classify(res)
    print(f"=== run {n}")
    for name, sel in (
        ("explain", lambda r: r["surface"] == "explain"),
        ("search", lambda r: r["surface"] == "search"),
        ("pooled", lambda r: True),
    ):
        rs = [r for r in rows if sel(r)]
        print(
            f"  {name:8s} scorer {ratio(rs, lambda r: r['credited'])} | audit (a)+(b) {ratio(rs, lambda r: r['cls'] in ('credited', 'a'))}"
            f" | audit (a) only {ratio(rs, lambda r: r['cls'] in ('credited', 'a'))}"
            f" | strict (terse echoes wrong) {ratio(rs, lambda r: r['cls'] in ('credited', 'a') and r['statement'] not in TERSE)}"
            f" | classes {dict(Counter(r['cls'] for r in rs))}"
        )
    distinct = {}
    for r in rows:
        distinct.setdefault(r["id"], r)
    d = list(distinct.values())
    print(
        f"  distinct executed-labelled facts (explain+search, by fact id): audit {ratio(d, lambda r: r['cls'] != 'c')}"
        f" | strict {ratio(d, lambda r: r['cls'] != 'c' and r['statement'] not in TERSE)}"
        f" | c: {sorted({r['statement'] for r in d if r['cls'] == 'c'})}"
    )
    print(
        f"  credited rows that are c (scorer over-credit): {sum(1 for r in rows if r['cls'] == 'c' and r['credited'])}"
        f" ({dict(Counter(r['surface'] for r in rows if r['cls'] == 'c' and r['credited']))})"
    )
```

### `evidence.py`

```
$ .venv/bin/python build/audit/evidence.py
```

```python
"""The audit's point checks in one place: run outcomes of every test an
uncredited or questioned executed row cites, the matcher helpers behind each
veto, the assertions present at each commit of the built fixture repo, and
the over-claim and polarity checks. Run from spike/: python evidence.py"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from bench import score as S  # noqa: E402
from bench.truth import load_truth  # noqa: E402

t = load_truth(Path("truth"))
mi, ai = S.build_mention_index(t), S.build_alias_index(t)
commits = json.loads(Path("build/commits.json").read_text())
STEPS = ["c1", "c2", "c3", "c4", "c5", "c6"]
SHA = {s: commits[s]["sha"][:7] for s in STEPS}

print("== run outcomes (runs/pytest-cN.json, runs/vitest-cN.json)")
PYTESTS = [
    "tests/e2e/test_pricing.py::test_member_first_fortyfive_minutes_free",
    "tests/unit/test_lost_bikes.py::test_ride_open_past_24_hours_closed_as_lost",
    "tests/unit/test_pricing.py::test_ebike_surcharge_when_flag_on",
    "tests/e2e/test_close_ride.py::test_close_ride_publishes_ride_completed",
    "tests/e2e/test_checkout.py::test_third_checkout_refused",
    "tests/e2e/test_refunds.py::test_refund_under_five_dollars_auto_approved_when_flag_on",
    "tests/unit/test_pricing.py::test_single_ride_cap_30",
    "tests/e2e/test_pricing.py::test_casual_ride_charges_one_dollar_unlock_fee",
    "tests/unit/test_pricing.py::test_casual_rate_from_first_minute",
    "tests/unit/test_lost_bikes.py::test_lost_bike_fee_150",
    "tests/e2e/test_station_status.py::test_station_status_reports_fill_ratio",
    "tests/e2e/test_checkin.py::test_checkin_at_full_station_allowed_with_overflow_parking",
    "tests/unit/test_memberships.py::test_membership_lapses_3_days_after_failed_renewal",
    "tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal",
]
for node in PYTESTS:
    row = []
    for s in STEPS:
        d = json.loads(Path(f"runs/pytest-{s}.json").read_text())
        row.append(f"{s}={ {x['nodeid']: x['outcome'] for x in d['tests']}.get(node, 'absent') }")
    print(f"  {node.split('::')[1]:60s} {' '.join(row)}")
title = "counts ride.completed toward the return station's demand"
row = []
for s in STEPS:
    d = json.loads(Path(f"runs/vitest-{s}.json").read_text())
    found = "absent"
    for f in d.get("testResults", []):
        for a in f.get("assertionResults", []):
            if a.get("title") == title:
                found = a.get("status")
    row.append(f"{s}={found}")
print(f"  {'rideEvents > ' + title:60s} {' '.join(row)}")

print("== matcher helpers behind each veto")
print(
    "  _number_tokens('Member 1st fortyfive minutes free.') =",
    S._number_tokens(S._without_http_codes("Member 1st fortyfive minutes free.")),
)
print(
    '  _number_tokens("A member\'s first forty-five minutes are free.") =',
    S._number_tokens("A member's first forty-five minutes are free."),
)
print(
    "  _has_negation(F-010) =",
    S._has_negation(t.facts["F-010"].statement),
    "| _has_negation('Ride open past 24 hours closed as lost.') =",
    S._has_negation("Ride open past 24 hours closed as lost."),
)
rc = {"entity": "EBIKE_SURCHARGE", "attribute": "ebike_surcharge", "value": 0.1, "unit": "usd"}
rc["_resolved_entities"] = S.align_entities(["EBIKE_SURCHARGE"], ai, t.entities, "business-logic")[
    0
]
tc = t.facts["F-007"].claim
print(
    "  F-007 echo claim: resolves",
    rc["_resolved_entities"],
    "| comparable",
    S._claim_is_comparable(rc, tc),
    "| claims_match",
    S._claims_match(rc, tc),
    "| values agree",
    S._claim_values_match(0.1, tc["value"], "usd", tc["unit"]),
    "| attributes_match",
    S._attributes_match("ebike_surcharge", tc["attribute"]),
)
print(
    "  F-019 echo: sim %.3f, words %s"
    % (
        S._text_similarity("3rd checkout refused.", t.facts["F-019"].statement),
        S._words("3rd checkout refused."),
    )
)

print("== over-claim: 'Membership lapses N days after failed renewal.' against F-015/F-016")
for n, fid in ((3, "F-015"), (7, "F-016")):
    st = f"Membership lapses {n} days after failed renewal."
    c = {"entity": "GRACE_DAYS", "attribute": "grace_days", "value": n, "unit": "day"}
    c["_resolved_entities"] = S.align_entities(["GRACE_DAYS"], ai, t.entities, "business-logic")[0]
    print(
        f"  {fid}: claims_match {S._claims_match(c, t.facts[fid].claim)} | statement match {S._statement_matches(st, t.facts[fid].statement, mi)}"
        f" sim {S._text_similarity(st, t.facts[fid].statement):.2f} | truth: {t.facts[fid].statement}"
    )

print("== polarity: allowed/refused against F-017/F-018")
for st in (
    "Checkin at full station allowed with overflow parking.",
    "Checkin at full station refused.",
):
    for fid in ("F-017", "F-018"):
        print(
            f"  {st!r} vs {fid}: statement match {S._statement_matches(st, t.facts[fid].statement, mi)} sim {S._text_similarity(st, t.facts[fid].statement):.2f}"
        )


def show(sha, path):
    r = subprocess.run(
        ["git", "-C", "build/repo", "show", f"{sha}:{path}"], capture_output=True, text=True
    )
    return r.stdout


print(
    "== assertions present per commit (git -C build/repo show <sha>:<path>, count of matching lines)"
)
CHECKS = [
    ("tests/e2e/test_pricing.py", "minutes=46", ["c2", "c3"]),
    ("tests/e2e/test_pricing.py", "minutes=31", STEPS),
    ("tests/unit/test_lost_bikes.py", "just_under", STEPS),
    ("tests/unit/test_pricing.py", 'EBIKE_SURCHARGE == Decimal("0.10")', STEPS),
    ("tests/unit/test_pricing.py", "at_threshold", STEPS),
    ("tests/e2e/test_close_ride.py", 'payload["type"] == "ride.completed"', STEPS[:5]),
    ("tests/e2e/test_checkout.py", "checkout_limit_reached", STEPS),
    ("tests/e2e/test_refunds.py", 'body["status"] == "approved"', ["c6"]),
    ("tests/e2e/test_refunds.py", "timedelta(days=14, minutes=1)", STEPS),
    ("dispatch/test/nightlyRebalance.test.ts", "station-low-edge", STEPS),
    ("tests/unit/test_tollbooth_client.py", "== 4", STEPS),
    ("dispatch/test/maintenanceSweep.test.ts", "expect(openedTickets).toHaveLength(1)", STEPS),
    ("dispatch/test/stormPause.test.ts", "severity: 1, observedAt: now", ["c6"]),
    ("tests/unit/test_memberships.py", "MembershipStatus.GRACE", STEPS),
    ("tests/unit/test_memberships.py", "LAPSED", STEPS),
]
for path, pat, steps in CHECKS:
    counts = " ".join(
        f"{s}:{sum(1 for ln in show(SHA[s], path).splitlines() if pat in ln)}" for s in steps
    )
    print(f"  {path} {pat!r}: {counts}")
lapsed = subprocess.run(
    ["git", "-C", "build/repo", "grep", "-n", "LAPSED", SHA["c6"], "--", "farebox"],
    capture_output=True,
    text=True,
).stdout
print("  git grep LAPSED farebox @c6:", lapsed.strip().replace("\n", " | "))
```
