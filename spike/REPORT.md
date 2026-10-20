# The extraction-pipeline benchmark: report

What D-013's benchmark measured, from the overnight run of 2026-10-20 on
asbuilt main `ad73e93`: stack B three times from an empty store, the
no-store baseline once, all scored against the invented system Gearwell
(`README.md`). Build issue: konyklabs/asbuilt#5; spike:
konyklabs/roadmap#154; decision and rule: D-013 in `konyklabs/roadmap`.
Every number below comes from `bench/score.py` at `ad73e93`, from the
commands and the two scratch scripts in Appendix B, or, for the stopped run
of 2026-10-19, from its stop file (Appendix B.1) and the checkpoint comments
on konyklabs/roadmap#154. Each table names its source; the appendices hold
the commands and their output.

## What was decided, and the numbers it rests on

Oleg's decisions of 2026-10-20 (konyklabs/roadmap#154), which the engine ADR
is to record:

- **Stack B is the pipeline.** Under D-013's rule ties go to B, and stack A
  was not run (section 9).
- **Executed-tier precision is below 0.95 on every reading**: 0.857 to 0.875
  on `explain`, 0.333 to 0.357 on `search`, 0.719 to 0.732 pooled (section
  1); audited, 0.926 on distinct `executed` facts (Hand audit). B made
  no hard tier error in any run. The tests-as-evidence claim is
  not made.
- **On answer quality the fixture cannot separate B from the baseline.**
  `explain` and `search` F1 tie (every interval includes zero); `ask`
  favours the baseline, -0.14 to -0.17 with intervals excluding zero
  (section 5). That is the outcome D-013 registered for a baseline that
  matches B: the fixture cannot decide, and the product proves itself at a
  scale where the corpus does not fit a context window. Here it fits: the
  baseline's corpus is about 109k tokens by its own estimate, under its
  150k fallback threshold, so every baseline query had the whole corpus in
  its prompt.
- **B is chosen on what the baseline cannot do**: executed-tier precision
  +0.60 [0.43, 0.74] pooled, 0 hard tier errors against 17, 5 of the 20
  expected stale entries found against 0, `explain` in about 2 ms against 31 s at the
  median, and a store that does not depend on the corpus fitting a prompt.
- **Code extraction (D-013 stage 2b) is not built in the spike** and goes in
  the first product slice: of the code-tier facts B matched on `explain`,
  16 of 18, 23 of 25 and 21 of 23 (runs 1, 2, 3) came back `documented`
  (section 3).
- **`spike/` is promoted**: the Gearwell fixture and the calibrated scorer
  move to `tests/fixtures/` as the regression benchmark and demo system.

## How the numbers were produced

| results file | arm | effort | complete | queries | failed | warm repeats | ran (UTC, 2026-10-20) |
|---|---|---|---|---|---|---|---|
| `results-b_postgres-model-1.json` | stack B | medium | true | 62 | 0 | 3 | 06:17 to 06:55 |
| `results-b_postgres-model-2.json` | stack B | medium | true | 62 | 0 | 3 | 06:55 to 07:34 |
| `results-b_postgres-model-3.json` | stack B | medium | true | 62 | 0 | 3 | 07:34 to 08:11 |
| `results-baseline-model-1.json` | baseline (`full`) | medium | true | 62 | 0 | 0 | 08:11 to 08:43 |

- **Runs.** `run-arms.sh overnight` (Oleg's local runner, not in this
  repository) ran, from `spike/` on main `ad73e93` with a clean tree:
  `uv run --extra pipeline python bench/run.py --prototype b_postgres
  --fixture . --reset --repeats 3 --budget-dollars 50` three times, then
  `ASBUILT_BASELINE_VARIANT=full uv run python bench/run.py --prototype
  baseline --fixture . --repeats 0 --budget-dollars 50`. The run times are
  the runner's log lines; `effort`, `complete`, the query count and the
  repeats are read from the results files (Appendix B.1).
- **Model and settings.** Every `claude -p` call ran with
  `--setting-sources ""` and `--effort medium` (konyklabs/asbuilt#31), so no
  setting of the machine reached the extraction. Model `claude-sonnet-5`;
  embedder `sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4`; NLI
  pre-filter `cross-encoder/nli-deberta-v3-base@6c749ce3425c`.
- **Files.** The results are under `spike/build/` (gitignored) and copied
  to Oleg's local `.local/overnight-2026-10-20T0217/`; `cmp` shows the
  copies byte-identical (Appendix B.1).
- **Scoring.** `uv run --extra pipeline python bench/score.py <results...>`
  from `spike/`, re-run for this report; its output matches the checkpoint
  comments posted on konyklabs/roadmap#154 during the night (Appendix A).
- **Only these runs count.** The 2026-10-06 runs predate
  konyklabs/asbuilt#31 and did not isolate the machine's own Claude Code
  settings; the 2026-10-19 run stopped at the budget cap for that reason
  (section 11). Neither is used here.
- **Counts are summed over queries**, never re-deduplicated (the scorer's
  micro-averaging; `bench/score.py`'s docstring). Fixed against the planted
  truth (`README.md`: 120 facts, 27 of them `executed`, 21 contradictions,
  10 stale pages), the query mix's denominators are larger: `explain`
  expects 279 facts over its 25 queries (a fact counts once per queried
  entity it carries), 62 of them `executed`; `contradictions` expects 27
  over 4 queries; `stale` expects 20 over 3 queries with different `since`
  dates.

## The matcher, calibrated

Every precision and recall below depends on `bench/score.py`'s statement
matcher, so its own calibration comes first (Appendix A.1).

| labelled set | pairs | tp | fp | fn | tn | precision | recall |
|---|---|---|---|---|---|---|---|
| `tests/fixtures/calibration.yaml` (hand-written paraphrases and hard negatives on polarity, owner, unit, near number, rule) | 118 | 64 | 0 | 0 | 54 | 1.000 | 1.000 |
| `tests/fixtures/calibration-model-run.yaml` (pairs judged from the first model run of the test connector, 2026-09-29, plus targeted hard negatives) | 90 | 35 | 0 | 20 | 35 | 1.000 | 0.636 |

Read it this way: across 208 labelled pairs the matcher never credited a
wrong statement, so a match the scorer counts is a real match. On
model-written statements it misses about a third of true paraphrases, so
every recall and precision below is a floor, and an unmatched fact is not
necessarily a wrong one. Four of the 20 misses are in exactly the terse
style of the test connector's rules extractor (`3rd checkout refused.`),
which is where B's `executed` statements come from: B calls the connector
with its default `extractor="rules"`, in model mode too (Appendix B.1). The hand audit (below)
reads a sample of the unmatched facts to put a number on it. The scorer's
docstring says 89 judged pairs for the second set; the file has 90, the
count printed here.

## 1. Executed-tier precision

Precision is the share of returned facts claiming `executed` that matched a
truth fact whose tier is `executed`; a hard error is a fact claiming
`executed` with no `run/` citation, D-013's "a fact claimed executed without
a passing run" (`bench/score.py`, `_tier_stats`). Explain and search from
the scorer (Appendix A.2 to A.6); the pooled row from Appendix B.2.

| run | `explain` precision | `search` precision | pooled | `explain` recall | hard errors | `executed` claims not credited (explain + search) |
|---|---|---|---|---|---|---|
| B 1 | 0.875 (35/40) | 0.353 (6/17) | 0.719 (41/57) | 0.565 (35/62) | 0 | 5 + 11 |
| B 2 | 0.857 (36/42) | 0.357 (5/14) | 0.732 (41/56) | 0.581 (36/62) | 0 | 6 + 9 |
| B 3 | 0.875 (35/40) | 0.333 (5/15) | 0.727 (40/55) | 0.565 (35/62) | 0 | 5 + 10 |
| B median (min to max) | 0.875 (0.857 to 0.875) | 0.353 (0.333 to 0.357) | 0.727 (0.719 to 0.732) | 0.565 (0.565 to 0.581) | 0 | |
| baseline | 0.114 (5/44) | 0.133 (2/15) | 0.119 (7/59) | 0.081 (5/62) | 17 (11 + 6) | 39 + 13 |
| B, no model (2026-09-29, section 6) | 0.842 (32/38) | 0.261 (12/46) | 0.524 (44/84) | 0.516 (32/62) | 0 | 6 + 34 |

- **Which figure is which.** The decisions comment quoted `explain`'s 0.857
  to 0.875. The paired bootstrap's `executed_precision` pools `explain` and
  `search` (0.719 to 0.732; B run 1 minus the baseline, 0.719 - 0.119, is
  its +0.601). `explain` is the cleaner reading: its expected set is every
  fact carrying the entity, while a `search` query expects only the few
  facts it lists, so a correctly tiered fact that is simply not one of them
  counts against `search`'s precision. The `search` figure mixes retrieval
  relevance with tier correctness.
- **No matched fact was promoted.** B made no hard error in any run, and
  among matched facts no truth `code` or `documented` fact came back as
  `executed` (section 3's confusion). The 5 or 6 uncredited `explain`
  claims per run matched no truth fact at all, so their tier cannot be
  checked against the truth; with the matcher's recall on terse
  statements, some may be true facts correctly tiered. They are what the
  hand audit reads first.
- **The tier comes from the shared test connector.** With no model call at
  all, the 2026-09-29 no-model run reached 0.842 on `explain`, the same
  level as model mode: the `executed` facts come from the test connector's
  rules extractor and the tier rule, which D-013 has every arm share.
- **The bar.** Every reading is below D-013's 0.95, so the tests-as-evidence
  claim is not published.

## 2. The five surfaces

From the scorer (Appendix A.2 to A.4); the median row is the scorer's own
three-run table. No arm returned an uncited fact on `explain` or `search`,
the two surfaces the scorer counts it on (`uncited=0`). A hard false positive is an unmatched fact that shares an
entity and a cited document with some truth fact; an unplanted one shares
neither. Both are unmatched, not judged wrong: see the calibration above
and the hand audit.

**`explain`** (25 queries, 279 expected)

| run | precision | recall | F1 | tp / returned | hard FP | unplanted |
|---|---|---|---|---|---|---|
| B 1 | 0.127 | 0.283 | 0.176 | 79 / 620 | 470 | 71 |
| B 2 | 0.129 | 0.315 | 0.184 | 88 / 680 | 528 | 64 |
| B 3 | 0.127 | 0.297 | 0.178 | 83 / 652 | 499 | 70 |
| B median (min to max) | 0.127 (0.127 to 0.129) | 0.297 (0.283 to 0.315) | 0.178 (0.176 to 0.184) | | | |
| baseline | 0.136 | 0.208 | 0.165 | 58 / 425 | 297 | 70 |

**`search`** (17 queries, 38 expected)

| run | precision | recall | F1 | tp / returned | hard FP | unplanted | precision@5 | recall@10 |
|---|---|---|---|---|---|---|---|---|
| B 1 | 0.047 | 0.211 | 0.077 | 8 / 170 | 107 | 55 | 0.047 (4/85) | 0.211 (8/38) |
| B 2 | 0.041 | 0.184 | 0.068 | 7 / 169 | 116 | 46 | 0.047 (4/85) | 0.184 (7/38) |
| B 3 | 0.053 | 0.237 | 0.087 | 9 / 170 | 105 | 56 | 0.059 (5/85) | 0.237 (9/38) |
| B median (min to max) | 0.047 (0.041 to 0.053) | 0.211 (0.184 to 0.237) | 0.077 (0.068 to 0.087) | | | | | |
| baseline | 0.043 | 0.184 | 0.069 | 7 / 164 | 66 | 91 | 0.071 (6/85) | 0.184 (7/38) |

**`ask`** (13 queries, 27 expected facts; citations capped at 3 per sentence)

| run | precision | recall | F1 | correct sentences / sentences | facts covered / expected |
|---|---|---|---|---|---|
| B 1 | 0.122 | 0.185 | 0.147 | 5 / 41 | 5 / 27 |
| B 2 | 0.108 | 0.148 | 0.125 | 4 / 37 | 4 / 27 |
| B 3 | 0.103 | 0.148 | 0.121 | 4 / 39 | 4 / 27 |
| B median (min to max) | 0.108 (0.103 to 0.122) | 0.148 (0.148 to 0.185) | 0.125 (0.121 to 0.147) | | |
| baseline | 0.257 | 0.333 | 0.290 | 9 / 35 | 9 / 27 |

**`contradictions`** (4 queries, 27 expected)

| run | precision | recall | F1 | matched / returned | winner correct |
|---|---|---|---|---|---|
| B 1 | 0.174 | 0.148 | 0.160 | 4 / 23 | 4 of 4 |
| B 2 | 0.147 | 0.185 | 0.164 | 5 / 34 | 5 of 5 |
| B 3 | 0.185 | 0.185 | 0.185 | 5 / 27 | 5 of 5 |
| B median (min to max) | 0.174 (0.147 to 0.185) | 0.185 (0.148 to 0.185) | 0.164 (0.160 to 0.185) | | |
| baseline | 0.053 | 0.037 | 0.043 | 1 / 19 | 1 of 1 |

Each B ingest made 198 model calls for 138 extracted documents. The other 60
equal the prose contradiction pass's verdict cap (`DEFAULT_MAX_VERDICTS =
60` in `pipeline/contradict.py`), with 6,306 to 6,906 prose pairs entering
the NLI pre-filter (the runner's log), so the cap was most likely reached in
every run. The results do not count verdicts separately: this is inferred,
not recorded.

**`stale`** (3 queries, 20 expected)

| run | precision | recall | F1 | tp / returned |
|---|---|---|---|---|
| B 1 | 0.143 | 0.250 | 0.182 | 5 / 35 |
| B 2 | 0.132 | 0.250 | 0.172 | 5 / 38 |
| B 3 | 0.125 | 0.250 | 0.167 | 5 / 40 |
| B median (min to max) | 0.132 (0.125 to 0.143) | 0.250 (0.250 to 0.250) | 0.172 (0.167 to 0.182) | |
| baseline | 0.000 | 0.000 | 0.000 | 0 / 25 |

**By category**, true positives against the truth fact's category (the
scorer's breakdown; Appendix B.2 lays the runs side by side)

| surface | category (expected) | B 1 | B 2 | B 3 | baseline |
|---|---|---|---|---|---|
| `explain` | business-logic (108) | 39 | 43 | 39 | 18 |
| `explain` | technical-implementation (100) | 28 | 35 | 35 | 26 |
| `explain` | operations (44) | 8 | 7 | 7 | 12 |
| `explain` | history (27) | 4 | 3 | 2 | 2 |
| `search` | business-logic (19) | 6 | 5 | 5 | 6 |
| `search` | technical-implementation (11) | 2 | 1 | 2 | 1 |
| `search` | operations (7) | 0 | 1 | 2 | 0 |
| `search` | history (1) | 0 | 0 | 0 | 0 |
| `ask` | business-logic (14) | 3 | 3 | 1 | 5 |
| `ask` | technical-implementation (6) | 1 | 1 | 1 | 2 |
| `ask` | history (5) | 1 | 0 | 2 | 1 |
| `ask` | operations (2) | 0 | 0 | 0 | 1 |

## 3. Tier confusion, category, validity, entity resolution

**Tier confusion on `explain`**, rows the truth tier, columns the tier B
returned, over matched facts (the scorer, Appendix A.2 to A.4)

| truth tier | B 1 | B 2 | B 3 | baseline |
|---|---|---|---|---|
| `executed` | executed 35, documented 2 | executed 36, documented 1 | executed 35, documented 1 | executed 5, code 5, documented 5 |
| `code` | code 2, documented 16 | code 2, documented 23 | code 2, documented 21 | code 14, documented 9, executed 3 |
| `documented` | documented 24 | documented 26 | documented 24 | documented 17 |

On `search` the matched sets are 7 to 9 facts per run: B returned
`executed` 5 or 6 times and `documented` otherwise, never `code`; the
baseline returned 2 of its 7 as `executed`, 3 as `code` and 2 as
`documented` (Appendix A).

B's `code` row is the stage-2b gap: B has no code extractor, so a fact the
fixture carries in code reaches B only through a page or ticket that
restates it, and comes back `documented`. The baseline, reading code
directly in its prompt, gets the `code` tier right 14 times of 26 but also
promotes 3 `code` facts to `executed` and demotes 10 `executed` ones.

**Category, validity and entity resolution**, over matched facts (the
scorer; medians from Appendix B.2)

| surface | run | category accuracy | validity accuracy | entity resolution precision | recall | unresolved names |
|---|---|---|---|---|---|---|
| `explain` | B 1 | 0.899 (71/79) | 0.545 (12/22) | 0.973 | 0.609 | 21 |
| `explain` | B 2 | 0.841 (74/88) | 0.522 (12/23) | 0.982 | 0.590 | 22 |
| `explain` | B 3 | 0.880 (73/83) | 0.500 (12/24) | 0.955 | 0.594 | 23 |
| `explain` | B median (min to max) | 0.880 (0.841 to 0.899) | 0.522 (0.500 to 0.545) | 0.973 (0.955 to 0.982) | 0.594 (0.590 to 0.609) | |
| `explain` | baseline | 0.534 (31/58) | 0.000 (0/11) | 0.973 | 0.416 | 9 |
| `search` | B 1 | 1.000 (8/8) | 0.000 (0/1) | 0.917 | 0.379 | 11 |
| `search` | B 2 | 0.857 (6/7) | 0.500 (1/2) | 0.846 | 0.423 | 9 |
| `search` | B 3 | 0.889 (8/9) | 0.333 (1/3) | 0.882 | 0.484 | 11 |
| `search` | baseline | 1.000 (7/7) | 0.000 (0/2) | 0.917 | 0.393 | 6 |

Validity counts a matched fact whose truth carries a `valid_from` or
`valid_to` as correct only when both agree. B dates about half of those
right; the baseline none of 11. Entity resolution is the scorer aligning
each arm's own entity names to the truth through an alias table the arms
never see: B's names, when it resolves them, are almost always right
(precision 0.955 to 0.982), and it resolves about 60% of what it should.

## 4. The winner under both weightings

The scorer's `--headline` line per run (Appendix A), the weighted sum
divided by 100 because the weights are percentages, so both columns are on
0 to 1. Each surface contributes its F1, or its recall where precision is
undefined.

| run | 40/25/15/10/10 | equal weights |
|---|---|---|
| B 1 | 0.1458 | 0.1483 |
| B 2 | 0.1427 | 0.1425 |
| B 3 | 0.1463 | 0.1476 |
| B median (min to max) | 0.146 (0.143 to 0.146) | 0.148 (0.143 to 0.148) |
| baseline | 0.1311 | 0.1136 |
| B, no model (2026-09-29, section 6) | 0.2060 | 0.1730 |

Between the two arms run, B is ahead of the baseline under both weightings
in every run, by more under equal weights (where `contradictions` and
`stale`, the baseline's weakest, count as much as `explain`). The scorer
gives no interval on this sum, so the margin is not tested against noise;
the per-surface intervals are section 5's. The no-model run outranks both
under both weightings; section 6 says why and why it is not a like-for-like
arm.

## 5. B against the baseline: the paired bootstrap

`bench/score.py <B run> --compare-with results-baseline-model-1.json`: 1,000
resamples of the queries, seed 0, the two arms paired by query id; F1
difference per surface (B minus baseline), executed-tier precision pooled
over `explain` and `search`, 95% intervals (Appendix A.5). The decisions
comment used the run-1 pairing; the other two agree in every direction.

| measure | B 1 - baseline | B 2 - baseline | B 3 - baseline |
|---|---|---|---|
| `explain` F1 (25 queries) | +0.011 [-0.056, 0.073] | +0.019 [-0.058, 0.094] | +0.014 [-0.056, 0.075] |
| `search` F1 (17) | +0.008 [-0.048, 0.060] | -0.002 [-0.052, 0.040] | +0.017 [-0.040, 0.065] |
| `ask` F1 (13) | **-0.143 [-0.284, -0.008]** | **-0.165 [-0.297, -0.055]** | **-0.169 [-0.312, -0.011]** |
| `contradictions` F1 (4) | +0.117 [-0.286, 0.182] | +0.120 [-0.286, 0.189] | +0.142 [0.000, 0.170] |
| `stale` F1 (3) | **+0.182 [0.105, 0.231]** | **+0.172 [0.098, 0.222]** | **+0.167 [0.103, 0.207]** |
| executed-tier precision (42 queries) | **+0.601 [0.428, 0.739]** | **+0.613 [0.444, 0.732]** | **+0.609 [0.427, 0.743]** |

Bold: the interval excludes zero. Two of these rest on very few queries.
`contradictions` has 4, which is why its interval is so wide. `stale` has
3, and the baseline matched none of its 25 returned entries, so its
interval mostly restates that the baseline's `stale` F1 is zero on every
query.

Read against D-013: on `explain` and `search`, 42 of the 62 queries and 65%
of the weight, the baseline matches B; on `ask` it beats B. That is "the
no-store baseline matches B on this fixture", so the fixture cannot decide
on answer quality, as D-013 registered in advance. B is ahead where a store
is the point: the `executed` tier, staleness, and latency (section 7).

## 6. The no-model run

Stack B with `ASBUILT_B_NO_MODEL=1`: no document extraction (the 138 text
documents stay pending), no prose verdicts, `ask` composed deterministically
from the top facts. What remains is the test connector's `executed` and
`code` facts, the run-versus-code contradiction and supersession; there are
no `documented` facts, so `stale` is empty by construction (`README.md`,
"Stack B").

- **Its score is the current scorer's**, re-run for this report (Appendix
  A.6). **The run is not current**: `results-b_postgres-nomodel.json` was
  written on 2026-09-29 at 06:03 local time, three minutes after stack B's
  pull request (#14, for konyklabs/asbuilt#4) merged as `7872ac8`, so by
  that prototype or its branch, and before every later spike pull request
  (#16 to #31). It registered 120 documents, made no model call, and
  ingested in 53.5 s (Appendix B.1).

| surface | B 1 F1 | no-model F1 | B 1 - no model [95% interval] |
|---|---|---|---|
| `explain` | 0.176 | 0.212 | -0.037 [-0.076, 0.040] |
| `search` | 0.077 | 0.267 | **-0.190 [-0.277, -0.110]** |
| `ask` | 0.147 | 0.314 | **-0.167 [-0.319, -0.021]** |
| `contradictions` | 0.160 | 0.071 | +0.089 [0.000, 0.095] |
| `stale` | 0.182 | 0.000 | **+0.182 [0.105, 0.231]** |
| executed-tier precision, pooled | 0.719 | 0.524 | **+0.195 [0.079, 0.290]** |

Model extraction more than doubles `explain` recall (0.122 to 0.283 to
0.315), finds the contradictions beyond the one run-versus-code pair (1 of
27 without it, 4 or 5 with it), and is the only way B finds stale pages at
all. It costs precision: `explain` falls from 0.829 (34/41) to 0.127 to
0.129, with 470 to 528 unmatched facts per run, and `search` and `ask` F1
fall with it. That is why the no-model run tops both weightings in section
4: F1 rewards its precision, and the weightings do not price what it cannot
answer. For the product, the test connector alone is a high-precision
source, and precision is lost where the document extraction pass starts;
how much of that loss is real rather than unmatched paraphrase is the hand
audit's question.

## 7. Latency

The scorer's latency table is over each query's first call, kept as the
result (`latency_ms` equals `cold_ms` in `bench/run.py`): p50 and p95 across
the surface's queries, in milliseconds (Appendix A). Warm repeats are
stored per query in the results files and are not printed by the scorer;
Appendix B.2 reads them.

| surface (queries) | B cold p50, runs 1 to 3 | B cold p95 | baseline cold p50 | baseline cold p95 |
|---|---|---|---|---|
| `explain` (25) | 2.2 to 2.4 | 9.3 to 10.7 | 31,184 | 68,861 |
| `search` (17) | 9.9 to 10.2 | 48.3 to 81.8 | 18,936 | 54,116 |
| `ask` (13) | 4,450 to 5,718 | 6,622 to 8,185 | 7,605 | 11,650 |
| `contradictions` (4) | 8.1 to 8.8 | 31.2 to 38.5 | 30,680 | 76,216 |
| `stale` (3) | 18.9 to 21.5 | 21.4 to 25.1 | 91,482 | 122,650 |

B's warm repeats, the median over queries of each query's p50: `explain`
2.0 to 2.1 ms, `search` 8.5 to 9.0, `contradictions` 6.1 to 7.5, `stale`
18.9 to 21.3. `ask`'s warm figure, 0.001 ms, is not a measurement: the
prototype memoises each question's answer (`self._answers` in
`prototypes/b_postgres/__init__.py`), so a repeat is a dictionary lookup,
and the cold figure, one model call composing the answer, is the real one.
Summed over its 62 queries, B's cold calls took 63 to 74 s per run; the
baseline's took 1,926 s.

Caveats. Three warm repeats per B query where D-013 asks for twenty, and
none for the baseline, whose every repeat would be another model call over
the whole corpus. "Cold" here is a query's first call in the process that
just ran the ingest, with Postgres already up, not a process or container
cold start; cold starts in that sense were not measured.

## 8. Ingest cost

From the results files' `ingest` block as the scorer prints it (Appendix A);
per-call figures and the medians from Appendix B.2.

| run | seconds | model calls | input tokens | output tokens | cache tokens | embedding tokens | dollars, token-priced | services | documents |
|---|---|---|---|---|---|---|---|---|---|
| B 1 | 2,217.5 | 198 | 398 | 222,005 | 654,851 | 16,088 | 5.772 | postgres | 258 |
| B 2 | 2,253.2 | 198 | 396 | 221,952 | 643,407 | 15,304 | 5.743 | postgres | 258 |
| B 3 | 2,127.2 | 198 | 396 | 211,935 | 651,883 | 16,153 | 5.614 | postgres | 258 |
| B median (min to max) | 2,217.5 (2,127.2 to 2,253.2) | 198 | | 221,952 (211,935 to 222,005) | 651,883 (643,407 to 654,851) | | 5.743 (5.614 to 5.772) | | |
| baseline | 0.0 | 0 | 0 | 0 | 0 | 0 | 0.000 | none | 258 |

- **Per call**, B spent 10.7 to 11.4 s of ingest wall clock, 1,070 to 1,121
  output tokens, about 3,300 cache tokens and $0.028 to $0.029. The seconds
  also cover the embedder, the NLI pre-filter over 6,306 to 6,906 prose
  pairs and the Postgres writes, so they bound the model's time per call
  from above.
- **The dollars are token-priced, and the bill is the subscription.** Every
  call is `claude -p` on Oleg's login; the dollar column prices its tokens
  at the harness's stated table for `claude-sonnet-5` ($3 input, $15
  output, $3.75 cache creation, $0.30 cache read per million;
  `connectors/tests/extract_model.py`), stated rather than fetched. Input
  tokens are near 400 for 198 calls because the CLI writes each prompt as
  cache creation; the prompt cost is in the cache column.
- **Services**: B runs one, Postgres with pgvector in Docker; the baseline
  runs none.
- **The baseline pays at query time.** Its ingest is free by design; its 62
  queries are 62 model calls, 1,926 s summed. Their tokens were counted in
  memory but are not written to the results file, so they are not recorded
  here. An estimate, not a measurement: each call carries the whole corpus,
  109,344 tokens by the arm's own `len(text) // 4` rule (Appendix B.3), so
  roughly 6.8 million prompt tokens over the 62 queries.
- **B's `ask` also calls the model at query time**, 13 calls per run, outside
  the ingest figure and likewise not recorded.
- **It does not extrapolate linearly.** The 138 text documents (wiki, docs,
  tickets, pull requests) average 152 words, median 88 (Appendix B.3). At
  that size the fixed per-call overhead (the CLI's own prompt, the system
  prompt and the schema, inside the roughly 3,300 cache tokens a call)
  outweighs the document itself, so the cost here is mostly per call, not
  per word: a per-word rate from this fixture would overstate a corpus of
  longer documents, and a per-document rate would understate it.

## 9. Stack A

Not run. D-013 runs stack A only if B misses a threshold or Oleg asks, and B
did miss one: executed-tier precision is below 0.95 on every reading. Oleg's
decision of 2026-10-20 is not to run it, for two reasons. The measure B
missed is set by the test connector and the tier rule, which D-013 has both
arms share, so A would inherit the miss; the no-model run's 0.842 on
`explain`, with no model call, is the same level as B's. And A's team path
(Neo4j Community, GPLv3 and single-instance on self-managed EC2, or Aura,
a third party receiving the sources) already fails D-013's constraints, and
the rule requires A to fit them as well as to beat B, so A could not take
the pipeline whatever it scored. konyklabs/asbuilt#3 stays open until the
engine ADR merges.

## 10. D-013's working hypothesis, checked

"B on fit and cost, A on time to first answer" (the tiering and
recommendation comment of 2026-09-28 on konyklabs/roadmap#154).

- **B on fit: holds where a store is the point, not on answer quality.**
  Executed-tier precision 0.72 against 0.12 pooled, no hard tier error
  against 17, stale pages found where the baseline found none, `explain`
  and `search` in milliseconds, one service. But `explain` and `search`
  tie the baseline, `ask` loses to it, and the `executed` tier is short of
  0.95.
- **B on cost: holds against the baseline, at this size.** One full ingest
  is $5.61 to $5.77 token-priced and 35 to 38 minutes, then queries cost
  nothing but `ask`'s one call. The baseline pays the whole corpus on every
  query (estimated, not recorded) and takes 31 s at the median for an
  `explain`. Against A, untested.
- **A on time to first answer: untested.** A was not run.

## 11. Deviations from D-013

- **Warm repeats**: 3 per B query, not 20; 0 for the baseline (section 7).
- **The baseline ran once**, not the three runs D-013 asks of every arm, so
  its own run-to-run noise is unmeasured; the bootstrap intervals rest on
  its one run.
- **Stack A was not run** (section 9).
- **No incremental phase.** All four results files are `phase: full`; D-013's
  duplicates, supersession on re-ingest and delta cost are unmeasured.
- **The 2026-10-19 run stopped at the budget cap.** At $40.05 of $50, the 80%
  stop, after 123 calls and before any query (its stop file, Appendix B.1).
  The cause, from the checkpoint comment of 2026-10-20 06:16 UTC on
  konyklabs/roadmap#154: headless `claude -p` calls inherited the machine's
  Claude Code settings (`xhigh` effort, an advisor model consulted
  mid-call, plugins and hooks adding about 17k tokens a prompt). Fixed in
  konyklabs/asbuilt#31; nothing from that run is used.
- **Effort is a variable D-013 did not name.** It is pinned at `medium` for
  every call of every arm and recorded in each results file.
- **The weekly usage-limit message is unverified.** konyklabs/asbuilt#30
  waits for a usage-limit reset by parsing the CLI's message; the session
  form was seen in a real failure, the weekly form ("resets Oct 23, 9am")
  is accepted on an unverified wording (`bench/claude_code.py`). No run
  here waited at all (0 s in every results file), so the path is untested.
- **Calibration style.** D-013 asks for calibration pairs in each arm's
  style; the model-written pairs come from one model run of the test
  connector, not from B's document extractor or the baseline.
- **Spend.** D-013 proposed a $50 cap per arm including debugging. The
  harness enforces it per run (`--budget-dollars 50`), and token-priced, B
  alone has spent more than $50 across runs: $40.05 in the stopped run of
  2026-10-19 and $17.13 in the three runs here, before the $21.53 the
  runner's header records for one 2026-10-06 ingest (measured under the
  machine's inherited settings, not re-measured here). The bill is the
  subscription, so the cap acted as a stop condition, not a spending
  limit.
- **Engineering hours per arm were not tracked.** What git shows: 16
  `feat(spike)` and `fix(spike)` pull requests merged from 2026-09-28 to
  2026-10-20 (#6 to #31, beside the bootstrap #1 and the local pipeline
  #26), 11 of them by 2026-09-30 and the other five on 2026-10-06, 10-19
  and 10-20.
  Per arm, the baseline is one pull request (#13, +3,473/-276 lines) and
  stack B one (#14, +6,998/-21, which also carries the shared pipeline
  layer); the rest is shared harness. Commit times reflect rebases, so
  hours cannot be recovered from them (Appendix B.4).

## Hand audit

The audit is `AUDIT.md`, beside this report, with its commands and its
scripts. It read every `executed` fact the scorer did not credit, in all
three runs and on both `explain` and `search`; checked every credited
`executed` fact against its test's assertions and its run; and classified a
stratified sample of 40 of run 1's unmatched `explain` facts (seed 154).

**The executed tier, scorer against audit** (runs 1, 2, 3):

| reading | scorer | audited |
|---|---|---|
| `explain` | 0.875, 0.857, 0.875 | 0.900, 0.905, 0.900 |
| `search` | 0.353, 0.357, 0.333 | 0.941, 0.929, 1.000 |
| pooled | 0.719, 0.732, 0.727 | 0.912, 0.911, 0.927 |
| distinct `executed` facts | not computed | 25/27 = 0.926 in each run |

- **Nothing uncredited is false.** Each uncredited `executed` fact is a
  planted fact the matcher failed to pair (5 or 6 per run on `explain`; the
  same fact ids recur in every run) or, on `search`, a planted, correctly
  tiered fact the query's expected list leaves out (9, 7 and 9 rows). None
  was lifted without a passing run.
- **Two credited facts claim more than their test asserts**: "Membership
  lapses 3 days after failed renewal." and the 7-day one (F-015, F-016).
  The tests assert the grace period only
  (`system/tests/unit/test_memberships.py`), and no code lapses a
  membership. The cause is the rules extractor writing the statement from
  the test's name (`connectors/tests/extract_rules.py`, `_name_sentence`),
  which breaks D-013's "never past the assertion". The audit's recount with
  those two narrowed is 25/25; that is a recount, not a run.
- **The bar is judged on distinct `executed` facts**, D-013's tier
  accuracy. `search`'s expected lists hold one to three hand-picked facts,
  so `search` and the pooled reading also measure retrieval relevance, and
  the bootstrap's +0.60 mixes that in.
- **Strict reading**: counting wrong the five terse statements that do not
  state their fact on their own ("3rd checkout refused.") gives 0.741 on
  distinct facts and 0.775 to 0.786 on `explain`.

**Unmatched `explain` facts, a sample of 40 from run 1**: 16 matcher misses,
22 true but unplanted, 2 right with a wrong category, 0 false. The
true-but-unplanted share is 0.55 (Wilson 95% interval 0.40 to 0.69) and the
false share 0 of 40 (upper bound 0.09). These are estimates from a sample:
most of the 470 to 528 unmatched facts per run are true statements the
fixture did not plant, so `explain` precision of 0.127 understates B
widely.

**Contradictions, by hand reading** (from the demo script's work): B
surfaces two of the six planted wiki-versus-test contradictions in a form
the scorer credits (X-002, X-003, in every run), returns X-004 with the
right winner uncredited, and misses X-001, X-005 and X-006. The baseline's
`contradictions` answer named all six with the test or code side winning;
the scorer credited none, since it could not match the baseline's entity
names or longer wording. The `contradictions` comparison stays
inconclusive.

**For the scorer and the fixture**, each a change that gets the local lens
round before it lands (`../AGENTS.md`): executed precision computed over
distinct facts; number words ("forty-five" is read as 40 and 5); a
calibration hard negative for "allowed" against "refused", which the
matcher accepts on the overflow-parking pair; an over-claiming statement
credited through its claim; truth F-007's assertion is at steps c5 and c6
of the built repository, not c1 to c6; and facts without a claim are
identified by their statement (`pipeline/store.py`, `base_fact_id`), so
restatements never merge.

**What it means for 0.95.** Audited, B's executed tier is 0.926 on
distinct facts, under the bar, and its two errors come from one connector
defect, not from lifting facts with no passing run. The tests-as-evidence
claim stays unpublished until the scorer, corrected as above, reads at
least 0.95 on a fresh run.

## Appendix A: scorer commands and output

Every command runs from `spike/` on main `ad73e93`. `$W` is the scratch
directory the score JSON was written to (not part of the repository); `$O`
is `.local/overnight-2026-10-20T0217` in Oleg's local workspace. The scorer
makes no model call.

### A.1 The matcher's calibration

```
$ uv run --extra pipeline python bench/score.py --calibrate
calibration: n=118 precision=1.000 recall=1.000 f1=1.000
  tp=64 fp=0 fn=0 tn=54
```

```
$ uv run --extra pipeline python bench/score.py --calibrate tests/fixtures/calibration-model-run.yaml
calibration: n=90 precision=1.000 recall=0.636 f1=0.778
  tp=35 fp=0 fn=20 tn=35
  20 misclassified:
    expect=True predicted=False truth='A check-in at a full station is refused when the overflow_parking flag is off.' candidate="Attempting to check in at a one-capacity station that is already occupied, with the feature flag off, is refused with HTTP 409 and error code 'station_full'."
    expect=True predicted=False truth='A rider can hold at most 2 bikes at once, so a third check-out is refused.' candidate="A rider's first two checkouts succeed with 201, and a third checkout attempt is refused with a 409 checkout_limit_reached error."
    expect=True predicted=False truth='farebox publishes a ride.completed event to the ride.events queue when it closes a ride.' candidate="Closing a normally checked-in ride returns HTTP 200 and publishes exactly one event to the ride.events topic, with payload type ride.completed and payload ride_id matching the ride's id."
    expect=True predicted=False truth='A rider without a membership pays a $1.00 unlock fee for every ride.' candidate='A zero-length trip from an unrecognised rider id is charged exactly the $1.00 floor amount as the casual-ride unlock fee.'
    expect=True predicted=False truth="A member's first 30 minutes of every ride are free." candidate='For a seeded member account, the pricing endpoint returns amount_cents == 0 for trips within the first 30 minutes and amount_cents == 15 once a trip runs slightly past that mark, proving the first 30 minutes are genuinely free rather than just cheap.'
    expect=True predicted=False truth="GET /stations/{id}/status returns the station's available bikes, empty docks and fill ratio." candidate='The station status endpoint returns HTTP 200 with a body reporting available_bikes, empty_docks, and fill_ratio that correctly reflect a four-dock station with three bikes occupying docks.'
    expect=True predicted=False truth='A ride whose bike is not docked within 24 hours of check-out is closed as lost.' candidate='A ride still open one minute past the 24-hour staleness cutoff is swept into the closed set as lost, and none remain in the still-open set.'
    expect=True predicted=False truth='A ride closed as lost is charged a $150.00 lost-bike fee.' candidate='The fee line for a closed stale ride adds exactly $150.00 (15000 cents) on top of the underlying ride charge amount.'
    expect=True predicted=False truth='A member pays $0.15 per minute for every minute after the free minutes.' candidate='For a duration ten units past the configured free-minutes threshold, only the excess duration is billed at MEMBER_RATE (0.15), yielding a total amount of 150 cents.'
    expect=True predicted=False truth='A rider without a membership pays $0.25 per minute from the first minute of the ride.' candidate="This test proves that a ten-minute casual ride, with no free-minute window subtracted first, is charged exactly 350 cents in total, using a CASUAL_RATE of Decimal('0.25')."
    expect=True predicted=False truth='When the ebike_surcharge flag is on, every charged minute of an e-bike ride costs an extra $0.10.' candidate='Toggling the e-bike surcharge flag on adds exactly $0.10 (EBIKE_SURCHARGE) to the price of an otherwise identical e-bike ride, with no surcharge applied at the threshold and $2.50 applied past the threshold.'
    expect=True predicted=False truth='A Tollbooth Pay capture that keeps failing is retried 3 times with backoff before the capture fails.' candidate="The tollbooth client's capture call, when every attempt receives a 503 response, retries exactly MAX_RETRIES times (4 total attempts) and sleeps between attempts for the exact backoff delays [0.5, 1, 2] seconds before finally failing."
    expect=True predicted=False truth='A bike with 3 fault reports within 7 days is locked and gets a maintenance ticket.' candidate='maintenanceSweep locks only the bike that has accumulated 3 fault reports within a 7-day window, opens exactly one maintenance ticket for it, and leaves bikes with just 2 reports or with an older stale report unlocked.'
    expect=True predicted=False truth='A station that is under 20% or over 90% full gets a rebalance order.' candidate='nightlyRebalance creates rebalance orders only for stations whose fill level is below 20% or above 90%, ordering exactly the out-of-bounds stations while leaving in-bounds stations untouched.'
    expect=True predicted=False truth="dispatch counts each ride.completed event toward the demand of the ride's return station." candidate='demandForStation("station-9") returns 2 after ride.completed events are counted toward the return station\'s demand.'
    expect=True predicted=False truth='Rebalancing pauses while the latest Skyglass severity is 3 or more.' candidate="stormPause suppresses rebalance order creation while the latest inserted Skyglass reading's severity is 3 or more, and once a subsequent reading drops severity below 3, isStormPaused returns false and rebalancing resumes, producing exactly one rebalance order from the resumed plans."
    expect=True predicted=False truth='A rider can hold at most 2 bikes at once, so a third check-out is refused.' candidate='3rd checkout refused.'
    expect=True predicted=False truth='A ride whose bike is not docked within 24 hours of check-out is closed as lost.' candidate='Ride open past 24 hours closed as lost.'
    expect=True predicted=False truth='When the ebike_surcharge flag is on, every charged minute of an e-bike ride costs an extra $0.10.' candidate='Ebike surcharge when flag on.'
    expect=True predicted=False truth='The Tollbooth Pay client retries only after a timeout or a 5xx response, never after a 4xx response.' candidate='Capture does not retry a 4xx.'
```

### A.2 Stack B, three runs together

The first report is run 1's own; the table at the end is the scorer's
median, minimum and maximum across the three runs. Without `--headline` and
its two lines, this is the output posted on konyklabs/roadmap#154 at 08:11
UTC (Appendix B.1).

```
$ uv run --extra pipeline python bench/score.py build/results-b_postgres-model-1.json build/results-b_postgres-model-2.json build/results-b_postgres-model-3.json --headline --json $W/b-all.json
prototype: b_postgres
phase: full
ingest:
  seconds=2217.521 input_tokens=398 output_tokens=222005 dollars=5.772 services=['postgres'] documents=258
  model=claude-sonnet-5 embedder=sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4 calls=198 embedding_tokens=16088 cache_tokens=654851

surface        precision   recall      f1        denominators
explain        0.127       0.283       0.176     tp=79/620 vs expected=279 uncited=0 hard_fp=470 unplanted=71
    business-logic       tp=39 expected=108
    history              tp=4 expected=27
    operations           tp=8 expected=44
    technical-implementation tp=28 expected=100
    tier confusion (rows=truth, cols=returned):
      code         code=2 documented=16
      documented   documented=24
      executed     documented=2 executed=35
    tier executed: precision=0.875 (35/40) recall=0.565 (35/62) hard_errors=0
    category accuracy=0.899 (71/79)
    validity accuracy=0.545 (12/22)
    entity resolution: precision=0.973 recall=0.609 unresolved=21
search         0.047       0.211       0.077     tp=8/170 vs expected=38 uncited=0 hard_fp=107 unplanted=55
    business-logic       tp=6 expected=19
    history              tp=0 expected=1
    operations           tp=0 expected=7
    technical-implementation tp=2 expected=11
    tier confusion (rows=truth, cols=returned):
      code         documented=1
      executed     documented=1 executed=6
    tier executed: precision=0.353 (6/17) recall=0.353 (6/17) hard_errors=0
    category accuracy=1.000 (8/8)
    validity accuracy=0.000 (0/1)
    entity resolution: precision=0.917 recall=0.379 unresolved=11
    precision@5=0.047 (4/85) recall@10=0.211 (8/38)
ask            0.122       0.185       0.147     tp=5/41 covered=5/27
    business-logic       tp=3 expected=14
    history              tp=1 expected=5
    operations           tp=0 expected=2
    technical-implementation tp=1 expected=6
contradictions 0.174       0.148       0.160     matched=4/23 vs expected=27 winner=4/4 (winner_accuracy=1.000)
stale          0.143       0.250       0.182     tp=5/35 vs expected=20

surface        p50 (ms)    p95 (ms)    n
explain        2.238       10.715      25
search         9.984       48.332      17
ask            4450.051    6622.352    13
contradictions 8.113       31.882      4
stale          21.460      25.086      3

headline (weighted sum of F1 / recall-where-precision-undefined): 14.5772  |  equal-weights variant: 0.1483
weights: {'explain': 40, 'search': 25, 'ask': 15, 'contradictions': 10, 'stale': 10}

-- across 3 runs: median / min / max --
surface        metric                    median    min       max
explain        precision                 0.127     0.127     0.129
explain        recall                    0.297     0.283     0.315
explain        f1                        0.178     0.176     0.184
explain        executed_tier_precision   0.875     0.857     0.875
search         precision                 0.047     0.041     0.053
search         recall                    0.211     0.184     0.237
search         f1                        0.077     0.068     0.087
search         executed_tier_precision   0.353     0.333     0.357
ask            precision                 0.108     0.103     0.122
ask            recall                    0.148     0.148     0.185
ask            f1                        0.125     0.121     0.147
contradictions precision                 0.174     0.147     0.185
contradictions recall                    0.185     0.148     0.185
contradictions f1                        0.164     0.160     0.185
stale          precision                 0.132     0.125     0.143
stale          recall                    0.250     0.250     0.250
stale          f1                        0.172     0.167     0.182
```

### A.3 Stack B, runs 2 and 3 on their own

```
$ uv run --extra pipeline python bench/score.py build/results-b_postgres-model-2.json --headline --json $W/b-2.json
prototype: b_postgres
phase: full
ingest:
  seconds=2253.191 input_tokens=396 output_tokens=221952 dollars=5.743 services=['postgres'] documents=258
  model=claude-sonnet-5 embedder=sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4 calls=198 embedding_tokens=15304 cache_tokens=643407

surface        precision   recall      f1        denominators
explain        0.129       0.315       0.184     tp=88/680 vs expected=279 uncited=0 hard_fp=528 unplanted=64
    business-logic       tp=43 expected=108
    history              tp=3 expected=27
    operations           tp=7 expected=44
    technical-implementation tp=35 expected=100
    tier confusion (rows=truth, cols=returned):
      code         code=2 documented=23
      documented   documented=26
      executed     documented=1 executed=36
    tier executed: precision=0.857 (36/42) recall=0.581 (36/62) hard_errors=0
    category accuracy=0.841 (74/88)
    validity accuracy=0.522 (12/23)
    entity resolution: precision=0.982 recall=0.590 unresolved=22
search         0.041       0.184       0.068     tp=7/169 vs expected=38 uncited=0 hard_fp=116 unplanted=46
    business-logic       tp=5 expected=19
    history              tp=0 expected=1
    operations           tp=1 expected=7
    technical-implementation tp=1 expected=11
    tier confusion (rows=truth, cols=returned):
      documented   documented=1
      executed     documented=1 executed=5
    tier executed: precision=0.357 (5/14) recall=0.294 (5/17) hard_errors=0
    category accuracy=0.857 (6/7)
    validity accuracy=0.500 (1/2)
    entity resolution: precision=0.846 recall=0.423 unresolved=9
    precision@5=0.047 (4/85) recall@10=0.184 (7/38)
ask            0.108       0.148       0.125     tp=4/37 covered=4/27
    business-logic       tp=3 expected=14
    history              tp=0 expected=5
    operations           tp=0 expected=2
    technical-implementation tp=1 expected=6
contradictions 0.147       0.185       0.164     matched=5/34 vs expected=27 winner=5/5 (winner_accuracy=1.000)
stale          0.132       0.250       0.172     tp=5/38 vs expected=20

surface        p50 (ms)    p95 (ms)    n
explain        2.435       9.268       25
search         10.164      81.762      17
ask            5718.391    7982.455    13
contradictions 8.071       38.538      4
stale          18.872      22.197      3

headline (weighted sum of F1 / recall-where-precision-undefined): 14.2703  |  equal-weights variant: 0.1425
weights: {'explain': 40, 'search': 25, 'ask': 15, 'contradictions': 10, 'stale': 10}
```

```
$ uv run --extra pipeline python bench/score.py build/results-b_postgres-model-3.json --headline --json $W/b-3.json
prototype: b_postgres
phase: full
ingest:
  seconds=2127.203 input_tokens=396 output_tokens=211935 dollars=5.614 services=['postgres'] documents=258
  model=claude-sonnet-5 embedder=sentence-transformers/all-MiniLM-L6-v2@1110a243fdf4 calls=198 embedding_tokens=16153 cache_tokens=651883

surface        precision   recall      f1        denominators
explain        0.127       0.297       0.178     tp=83/652 vs expected=279 uncited=0 hard_fp=499 unplanted=70
    business-logic       tp=39 expected=108
    history              tp=2 expected=27
    operations           tp=7 expected=44
    technical-implementation tp=35 expected=100
    tier confusion (rows=truth, cols=returned):
      code         code=2 documented=21
      documented   documented=24
      executed     documented=1 executed=35
    tier executed: precision=0.875 (35/40) recall=0.565 (35/62) hard_errors=0
    category accuracy=0.880 (73/83)
    validity accuracy=0.500 (12/24)
    entity resolution: precision=0.955 recall=0.594 unresolved=23
search         0.053       0.237       0.087     tp=9/170 vs expected=38 uncited=0 hard_fp=105 unplanted=56
    business-logic       tp=5 expected=19
    history              tp=0 expected=1
    operations           tp=2 expected=7
    technical-implementation tp=2 expected=11
    tier confusion (rows=truth, cols=returned):
      code         documented=2
      documented   documented=1
      executed     documented=1 executed=5
    tier executed: precision=0.333 (5/15) recall=0.294 (5/17) hard_errors=0
    category accuracy=0.889 (8/9)
    validity accuracy=0.333 (1/3)
    entity resolution: precision=0.882 recall=0.484 unresolved=11
    precision@5=0.059 (5/85) recall@10=0.237 (9/38)
ask            0.103       0.148       0.121     tp=4/39 covered=4/27
    business-logic       tp=1 expected=14
    history              tp=2 expected=5
    operations           tp=0 expected=2
    technical-implementation tp=1 expected=6
contradictions 0.185       0.185       0.185     matched=5/27 vs expected=27 winner=5/5 (winner_accuracy=1.000)
stale          0.125       0.250       0.167     tp=5/40 vs expected=20

surface        p50 (ms)    p95 (ms)    n
explain        2.306       10.338      25
search         9.943       63.610      17
ask            5213.013    8184.674    13
contradictions 8.781       31.171      4
stale          20.418      21.389      3

headline (weighted sum of F1 / recall-where-precision-undefined): 14.6323  |  equal-weights variant: 0.1476
weights: {'explain': 40, 'search': 25, 'ask': 15, 'contradictions': 10, 'stale': 10}
```

### A.4 The baseline

```
$ uv run --extra pipeline python bench/score.py build/results-baseline-model-1.json --headline --json $W/baseline.json
prototype: baseline
phase: full
ingest:
  seconds=0.007 input_tokens=0 output_tokens=0 dollars=0.000 services=[] documents=258
  model=claude-sonnet-5 embedder=None calls=0 embedding_tokens=0 cache_tokens=0

surface        precision   recall      f1        denominators
explain        0.136       0.208       0.165     tp=58/425 vs expected=279 uncited=0 hard_fp=297 unplanted=70
    business-logic       tp=18 expected=108
    history              tp=2 expected=27
    operations           tp=12 expected=44
    technical-implementation tp=26 expected=100
    tier confusion (rows=truth, cols=returned):
      code         code=14 documented=9 executed=3
      documented   documented=17
      executed     code=5 documented=5 executed=5
    tier executed: precision=0.114 (5/44) recall=0.081 (5/62) hard_errors=11
    category accuracy=0.534 (31/58)
    validity accuracy=0.000 (0/11)
    entity resolution: precision=0.973 recall=0.416 unresolved=9
search         0.043       0.184       0.069     tp=7/164 vs expected=38 uncited=0 hard_fp=66 unplanted=91
    business-logic       tp=6 expected=19
    history              tp=0 expected=1
    operations           tp=0 expected=7
    technical-implementation tp=1 expected=11
    tier confusion (rows=truth, cols=returned):
      code         code=1 documented=1
      executed     code=2 documented=1 executed=2
    tier executed: precision=0.133 (2/15) recall=0.118 (2/17) hard_errors=6
    category accuracy=1.000 (7/7)
    validity accuracy=0.000 (0/2)
    entity resolution: precision=0.917 recall=0.393 unresolved=6
    precision@5=0.071 (6/85) recall@10=0.184 (7/38)
ask            0.257       0.333       0.290     tp=9/35 covered=9/27
    business-logic       tp=5 expected=14
    history              tp=1 expected=5
    operations           tp=1 expected=2
    technical-implementation tp=2 expected=6
contradictions 0.053       0.037       0.043     matched=1/19 vs expected=27 winner=1/1 (winner_accuracy=1.000)
stale          0.000       0.000       0.000     tp=0/25 vs expected=20

surface        p50 (ms)    p95 (ms)    n
explain        31184.299   68861.109   25
search         18936.077   54116.010   17
ask            7604.814    11649.682   13
contradictions 30679.895   76216.330   4
stale          91482.485   122650.220  3

headline (weighted sum of F1 / recall-where-precision-undefined): 13.1132  |  equal-weights variant: 0.1136
weights: {'explain': 40, 'search': 25, 'ask': 15, 'contradictions': 10, 'stale': 10}
```

### A.5 Stack B against the baseline, one pairing per B run

`--compare-with` prints both arms' reports before the bootstrap; they are
the reports of A.2 to A.4 (checked in B.1) and are left out here.

```
$ uv run --extra pipeline python bench/score.py build/results-b_postgres-model-1.json --compare-with build/results-baseline-model-1.json --json $W/b1-vs-baseline.json
=== paired bootstrap (A - B), over queries ===
surface             diff      ci_low    ci_high   excludes_zero
explain             0.011     -0.056    0.073     False (n=25 queries)
search              0.008     -0.048    0.060     False (n=17 queries)
ask                 -0.143    -0.284    -0.008    True (n=13 queries)
contradictions      0.117     -0.286    0.182     False (n=4 queries)
stale               0.182     0.105     0.231     True (n=3 queries)
executed_precision  0.601     0.428     0.739     True (n=42 queries)
```

```
$ uv run --extra pipeline python bench/score.py build/results-b_postgres-model-2.json --compare-with build/results-baseline-model-1.json --json $W/b2-vs-baseline.json
=== paired bootstrap (A - B), over queries ===
surface             diff      ci_low    ci_high   excludes_zero
explain             0.019     -0.058    0.094     False (n=25 queries)
search              -0.002    -0.052    0.040     False (n=17 queries)
ask                 -0.165    -0.297    -0.055    True (n=13 queries)
contradictions      0.120     -0.286    0.189     False (n=4 queries)
stale               0.172     0.098     0.222     True (n=3 queries)
executed_precision  0.613     0.444     0.732     True (n=42 queries)
```

```
$ uv run --extra pipeline python bench/score.py build/results-b_postgres-model-3.json --compare-with build/results-baseline-model-1.json --json $W/b3-vs-baseline.json
=== paired bootstrap (A - B), over queries ===
surface             diff      ci_low    ci_high   excludes_zero
explain             0.014     -0.056    0.075     False (n=25 queries)
search              0.017     -0.040    0.065     False (n=17 queries)
ask                 -0.169    -0.312    -0.011    True (n=13 queries)
contradictions      0.142     0.000     0.170     False (n=4 queries)
stale               0.167     0.103     0.207     True (n=3 queries)
executed_precision  0.609     0.427     0.743     True (n=42 queries)
```

### A.6 Stack B with no model (the 2026-09-29 results file)

```
$ uv run --extra pipeline python bench/score.py build/results-b_postgres-nomodel.json --headline --json $W/nomodel.json
prototype: b_postgres
phase: full
ingest:
  seconds=53.508 input_tokens=0 output_tokens=0 dollars=0.000 services=['postgres'] documents=120

surface        precision   recall      f1        denominators
explain        0.829       0.122       0.212     tp=34/41 vs expected=279 uncited=0 hard_fp=7 unplanted=0
    business-logic       tp=28 expected=108
    history              tp=0 expected=27
    operations           tp=0 expected=44
    technical-implementation tp=6 expected=100
    tier confusion (rows=truth, cols=returned):
      code         code=2
      executed     executed=32
    tier executed: precision=0.842 (32/38) recall=0.516 (32/62) hard_errors=0
    category accuracy=1.000 (34/34)
    validity accuracy=1.000 (16/16)
    entity resolution: precision=0.985 recall=0.560 unresolved=18
search         0.231       0.316       0.267     tp=12/52 vs expected=38 uncited=0 hard_fp=40 unplanted=0
    business-logic       tp=10 expected=19
    history              tp=0 expected=1
    operations           tp=0 expected=7
    technical-implementation tp=2 expected=11
    tier confusion (rows=truth, cols=returned):
      executed     executed=12
    tier executed: precision=0.261 (12/46) recall=0.706 (12/17) hard_errors=0
    category accuracy=1.000 (12/12)
    validity accuracy=0.750 (3/4)
    entity resolution: precision=0.955 recall=0.457 unresolved=15
    precision@5=0.289 (11/38) recall@10=0.316 (12/38)
ask            0.256       0.407       0.314     tp=11/43 covered=11/27
    business-logic       tp=8 expected=14
    history              tp=0 expected=5
    operations           tp=0 expected=2
    technical-implementation tp=3 expected=6
contradictions 1.000       0.037       0.071     matched=1/1 vs expected=27 winner=1/1 (winner_accuracy=1.000)
stale          n/a         0.000       0.000     tp=0/0 vs expected=20

surface        p50 (ms)    p95 (ms)    n
explain        7.987       9.489       25
search         9.404       135.788     17
ask            12.075      99.352      13
contradictions 5.059       7.973       4
stale          2.906       3.315       3

headline (weighted sum of F1 / recall-where-precision-undefined): 20.5952  |  equal-weights variant: 0.1730
weights: {'explain': 40, 'search': 25, 'ask': 15, 'contradictions': 10, 'stale': 10}
```

```
$ uv run --extra pipeline python bench/score.py build/results-b_postgres-model-1.json --compare-with build/results-b_postgres-nomodel.json --json $W/b1-vs-nomodel.json
=== paired bootstrap (A - B), over queries ===
surface             diff      ci_low    ci_high   excludes_zero
explain             -0.037    -0.076    0.040     False (n=25 queries)
search              -0.190    -0.277    -0.110    True (n=17 queries)
ask                 -0.167    -0.319    -0.021    True (n=13 queries)
contradictions      0.089     0.000     0.095     False (n=4 queries)
stale               0.182     0.105     0.231     True (n=3 queries)
executed_precision  0.195     0.079     0.290     True (n=42 queries)
```

## Appendix B: provenance and the scratch scripts

Neither script is shipped: they read the scorer's JSON and the results
files and decide nothing the scorer decides. Their source is here so that
every number they produced can be reproduced.

### B.1 Provenance

The checkout and the files the report scores; the run times; the code
lines the report cites (the verdict cap, `ask`'s memo, the price table, and
B calling the test connector with its default rules extractor); the stop
file of the 2026-10-19 run; the re-scored output against the overnight
checkpoint (the one difference is the blank line `--headline` adds before
its two lines); and the arm reports A.5 leaves out.

```
$ git rev-parse --short HEAD && git status --short | wc -l
ad73e93
       0

$ for f in b_postgres-model-1 b_postgres-model-2 b_postgres-model-3 baseline-model-1; do cmp build/results-$f.json $O/results-$f.json && echo "$f identical"; done
b_postgres-model-1 identical
b_postgres-model-2 identical
b_postgres-model-3 identical
baseline-model-1 identical

$ python3 -c 'import json,sys
for p in sys.argv[1:]:
    r = json.load(open(p)); q = r["queries"]
    print(p, "effort=%s complete=%s phase=%s queries=%d failed=%d warm_repeats=%s waited_s=%d" % (r.get("effort"), r.get("complete"), r["phase"], len(q), sum("error" in x for x in q), sorted({x["warm_repeats"] for x in q}), sum(x.get("waited_for_reset_s", 0) for x in q)))
' build/results-b_postgres-model-1.json build/results-b_postgres-model-2.json build/results-b_postgres-model-3.json build/results-baseline-model-1.json build/results-b_postgres-nomodel.json
build/results-b_postgres-model-1.json effort=medium complete=True phase=full queries=62 failed=0 warm_repeats=[3] waited_s=0
build/results-b_postgres-model-2.json effort=medium complete=True phase=full queries=62 failed=0 warm_repeats=[3] waited_s=0
build/results-b_postgres-model-3.json effort=medium complete=True phase=full queries=62 failed=0 warm_repeats=[3] waited_s=0
build/results-baseline-model-1.json effort=medium complete=True phase=full queries=62 failed=0 warm_repeats=[0] waited_s=0
build/results-b_postgres-nomodel.json effort=None complete=None phase=full queries=62 failed=0 warm_repeats=[3] waited_s=0

$ ls -l build/results-b_postgres-nomodel.json
-rw-r--r--  1 oleg  staff  287154 Sep 29 06:03 build/results-b_postgres-nomodel.json

$ grep -E 'run-arms .* (start|exit)|main at|extracted 138' $O/log.txt | sed -E 's/, embedder .*//'
[2026-10-20T06:17:01Z] main at ad73e93, clean
[2026-10-20T06:17:07Z] run-arms b 1 start (main ad73e93)
b_postgres: step c6, steps ['c1', 'c2', 'c3', 'c4', 'c5', 'c6'], documents registered 120, pending 138, extracted 138, lift {'facts': 134, 'superseded': 5, 'opened': 1, 'resolved': 1}, claim pairs 21, prose pairs 6906 (cross-encoder/nli-deberta-v3-base@6c749ce3425c)
[2026-10-20T06:55:16Z] run-arms b 1 exit=0 -> build/results-b_postgres-model-1.json
[2026-10-20T06:55:18Z] run-arms b 2 start (main ad73e93)
b_postgres: step c6, steps ['c1', 'c2', 'c3', 'c4', 'c5', 'c6'], documents registered 120, pending 138, extracted 138, lift {'facts': 134, 'superseded': 5, 'opened': 1, 'resolved': 1}, claim pairs 23, prose pairs 6306 (cross-encoder/nli-deberta-v3-base@6c749ce3425c)
[2026-10-20T07:34:14Z] run-arms b 2 exit=0 -> build/results-b_postgres-model-2.json
[2026-10-20T07:34:16Z] run-arms b 3 start (main ad73e93)
b_postgres: step c6, steps ['c1', 'c2', 'c3', 'c4', 'c5', 'c6'], documents registered 120, pending 138, extracted 138, lift {'facts': 134, 'superseded': 5, 'opened': 1, 'resolved': 1}, claim pairs 22, prose pairs 6498 (cross-encoder/nli-deberta-v3-base@6c749ce3425c)
[2026-10-20T08:11:01Z] run-arms b 3 exit=0 -> build/results-b_postgres-model-3.json
[2026-10-20T08:11:06Z] run-arms baseline 1 start (main ad73e93)
[2026-10-20T08:43:12Z] run-arms baseline 1 exit=0 -> build/results-baseline-model-1.json

$ grep -n 'DEFAULT_MAX_VERDICTS =' pipeline/contradict.py; grep -n -A1 'def ask' prototypes/b_postgres/__init__.py | head -3; grep -n 'claude-sonnet-5": {' connectors/tests/extract_model.py
63:DEFAULT_MAX_VERDICTS = 60
480:    def ask(self, question: str) -> Answer:
481-        if question in self._answers:
62:    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_creation": 3.75, "cache_read": 0.30},

$ grep -n 'extractor: str = ' connectors/tests/__main__.py; grep -n -A2 'output = build_step_output(' prototypes/b_postgres/__init__.py
142:    extractor: str = "rules",
303:            output = build_step_output(
304-                root, step_id, history.repo, commits, outcomes, order, timeline=history
305-            )

$ cat build/stop-b_postgres-xhigh-inherited-2026-10-20.json
{
  "arm": "b_postgres",
  "model": "claude-sonnet-5",
  "reason": "$40.0545/$50.00",
  "calls": 123,
  "input_tokens": 3025179,
  "output_tokens": 1273430,
  "cache_creation_tokens": 2957080,
  "cache_read_tokens": 2628255,
  "total_tokens": 9883944,
  "budget_tokens": null,
  "budget_dollars": 50.0,
  "usage_missing_calls": 0
}

# the re-scored three-run output against the overnight checkpoint (headline lines are new with --headline)
$ diff <(sed -n '/^prototype/,$p' $W/b-all.txt | grep -v '^headline\|^weights') <(sed -n '/Stack B, three runs together/,/^## Stack B run 1 against/p' $O/SUMMARY.md | sed -n '/^prototype/,/^```$/p' | grep -v '^```'); echo "diff exit $?"
49d48
< 
diff exit 1

# the arm reports --compare-with prints before its bootstrap are the single-arm reports of A.2 to A.4 and A.6
$ for n in 1 2 3; do diff <(sed -n '/=== arm A/,/=== arm B/p' $W/b$n-vs-baseline.txt | sed '1d;$d' | sed '/^$/N;/^\n$/D') <(grep -v '^headline\|^weights' $W/b-$n.txt | sed '/^$/N;/^\n$/D') >/dev/null && echo "b$n: arm A same"; diff <(sed -n '/=== arm B/,/=== paired/p' $W/b$n-vs-baseline.txt | sed '1d;$d' | sed '/^$/N;/^\n$/D') <(grep -v '^headline\|^weights' $W/baseline.txt | sed '/^$/N;/^\n$/D') >/dev/null && echo "b$n: arm B (baseline) same"; done; diff <(sed -n '/=== arm B/,/=== paired/p' $W/b1-vs-nomodel.txt | sed '1d;$d' | sed '/^$/N;/^\n$/D') <(grep -v '^headline\|^weights' $W/nomodel.txt | sed '/^$/N;/^\n$/D') >/dev/null && echo 'nomodel: arm B same'
b1: arm A same
b1: arm B (baseline) same
b2: arm A same
b2: arm B (baseline) same
b3: arm A same
b3: arm B (baseline) same
nomodel: arm B same
```

### B.2 Derived tables: `report_numbers.py`

The headline under both weightings with the order of the arms, every
per-run count side by side, the pooled executed-tier precision, warm-repeat
latency, and ingest cost per call.

```python
"""Numbers REPORT.md needs that bench/score.py does not print: the headline
under both weightings per run, every per-run measure with min/max, warm-repeat
latency, and ingest cost per call. Reads score JSON written by score.py --json
and the raw results files; computes nothing the scorer already decides."""

import json
import statistics
import sys
from pathlib import Path

score_dir = Path(sys.argv[1])  # holds b-1.json b-2.json b-3.json baseline.json nomodel.json
results_dir = Path(sys.argv[2])  # holds results-*.json

ARMS = [("B run 1", "b-1"), ("B run 2", "b-2"), ("B run 3", "b-3"), ("baseline", "baseline"), ("B no-model (09-29)", "nomodel")]
RESULTS = {"b-1": "results-b_postgres-model-1.json", "b-2": "results-b_postgres-model-2.json",
           "b-3": "results-b_postgres-model-3.json", "baseline": "results-baseline-model-1.json",
           "nomodel": "results-b_postgres-nomodel.json"}
SURFACES = ["explain", "search", "ask", "contradictions", "stale"]
reports = {key: json.loads((score_dir / f"{key}.json").read_text()) for _, key in ARMS}


def f(x, d=3):
    return "n/a" if x is None else f"{x:.{d}f}"


def mmm(values):
    vals = [v for v in values if v is not None]
    return f"{f(statistics.median(vals))} / {f(min(vals))} / {f(max(vals))}"


print("== 1. headline, both weightings (weighted sum / 100, so both are on 0..1) ==")
print(f"{'arm':<20}{'40/25/15/10/10':<16}{'equal weights':<14}")
for label, key in ARMS:
    r = reports[key]
    print(f"{label:<20}{f(r['headline'] / 100, 4):<16}{f(r['headline_equal_weights'], 4):<14}")
b = [reports[k] for k in ("b-1", "b-2", "b-3")]
print(f"{'B median/min/max':<20}{mmm([r['headline'] / 100 for r in b]):<26}{mmm([r['headline_equal_weights'] for r in b])}")
print("per-surface contribution (F1, or recall where precision is undefined):")
for label, key in ARMS:
    s = reports[key]["surfaces"]
    row = []
    for name in SURFACES:
        p, rc, f1 = s[name]["precision"], s[name]["recall"], s[name]["f1"]
        row.append(f"{name}={f(rc if p is None else (f1 or 0.0))}")
    print(f"  {label:<20}" + " ".join(row))
for weighting, field, scale in (("40/25/15/10/10", "headline", 100), ("equal", "headline_equal_weights", 1)):
    ranked = sorted(ARMS, key=lambda a: reports[a[1]][field], reverse=True)
    print(f"order under {weighting}: " + " > ".join(f"{lab} {f(reports[k][field] / scale, 4)}" for lab, k in ranked))

print()
print("== 2. counts per surface, per run ==")
for name in SURFACES:
    print(f"-- {name}")
    for label, key in ARMS:
        s = reports[key]["surfaces"][name]
        if name in ("explain", "search"):
            extra = f"tp={s['tp']} returned={s['returned']} expected={s['expected']} hard_fp={s['hard_false_positives']} unplanted={len(s['unplanted'])} uncited={s['uncited']}"
        elif name == "ask":
            extra = f"correct_sentences={s['correct_sentences']} sentences={s['sentences']} covered={s['covered_facts']}/{s['expected']}"
        elif name == "contradictions":
            extra = f"matched={s['matched']} returned={s['returned']} expected={s['expected']} winner={s['winner_correct']}/{s['winner_checked']}"
        else:
            extra = f"tp={s['tp']} returned={s['returned']} expected={s['expected']}"
        print(f"  {label:<20}P={f(s['precision'])} R={f(s['recall'])} F1={f(s['f1'])}  {extra}")

print()
print("== 3. by category (truth fact's category), tp per run ==")
for name in ("explain", "search", "ask"):
    cats = sorted(reports["b-1"]["surfaces"][name]["by_category"])
    print(f"-- {name}: " + ", ".join(f"{c} expected={reports['b-1']['surfaces'][name]['by_category'][c]['expected']}" for c in cats))
    for label, key in ARMS:
        bc = reports[key]["surfaces"][name]["by_category"]
        print(f"  {label:<20}" + " ".join(f"{c}={bc[c]['tp']}" for c in cats))

print()
print("== 4. tier, category, validity, entity resolution (explain and search) ==")
for name in ("explain", "search"):
    print(f"-- {name}")
    for label, key in ARMS:
        s = reports[key]["surfaces"][name]
        t, c, v, e = s["tier"], s["category_accuracy"], s["validity"], s["entity_resolution"]
        unmatched_exec = t["returned_executed"] - t["tp_executed"]
        print(f"  {label:<20}exec P={f(t['precision'])} ({t['tp_executed']}/{t['returned_executed']}) "
              f"R={f(t['recall'])} ({t['tp_executed']}/{t['expected_executed']}) hard_errors={t['hard_errors']} "
              f"exec-claims-not-credited={unmatched_exec} | cat={f(c['accuracy'])} ({c['correct']}/{c['total']}) "
              f"| validity={f(v['accuracy'])} ({v['correct']}/{v['total']}) "
              f"| ER P={f(e['precision'])} R={f(e['recall'])} unresolved={len(e['unresolved'])}")
        print(f"  {'':<20}confusion {json.dumps(t['confusion'], sort_keys=True)}")
    for metric, get in (("exec P", lambda s: s["tier"]["precision"]), ("exec R", lambda s: s["tier"]["recall"]),
                        ("category", lambda s: s["category_accuracy"]["accuracy"]),
                        ("validity", lambda s: s["validity"]["accuracy"]),
                        ("ER P", lambda s: s["entity_resolution"]["precision"]),
                        ("ER R", lambda s: s["entity_resolution"]["recall"])):
        print(f"  B median/min/max {metric:<9}{mmm([get(r['surfaces'][name]) for r in b])}")

print("-- explain and search pooled (the paired bootstrap's executed_precision pools the same counts)")
for label, key in ARMS:
    ts = [reports[key]["surfaces"][n]["tier"] for n in ("explain", "search")]
    tp = sum(t["tp_executed"] for t in ts)
    ret = sum(t["returned_executed"] for t in ts)
    exp = sum(t["expected_executed"] for t in ts)
    he = sum(t["hard_errors"] for t in ts)
    print(f"  {label:<20}exec P={f(tp / ret if ret else None)} ({tp}/{ret}) R={f(tp / exp)} ({tp}/{exp}) hard_errors={he}")

print()
print("== 5. latency ==")
print("cold (the scorer's table: each query's first call; p50/p95 across the surface's queries), ms")
for name in SURFACES:
    row = [f"{label}: p50={f(reports[key]['latency'][name]['p50_ms'], 1)} p95={f(reports[key]['latency'][name]['p95_ms'], 1)}" for label, key in ARMS]
    print(f"  {name:<15}" + " | ".join(row))
print("warm repeats (per query: p50/p95 over its repeats; here the median of the per-query p50s and the max of the per-query p95s), ms")
for label, key in ARMS:
    q = json.loads((results_dir / RESULTS[key]).read_text())["queries"]
    reps = sorted({x["warm_repeats"] for x in q})
    parts = []
    for name in SURFACES:
        qs = [x for x in q if x["surface"] == name and x["p50_ms"] is not None]
        if not qs:
            parts.append(f"{name}=none")
            continue
        parts.append(f"{name}: p50med={f(statistics.median(x['p50_ms'] for x in qs), 3)} p95max={f(max(x['p95_ms'] for x in qs), 3)} n={len(qs)}")
    print(f"  {label:<20}repeats={reps} " + " | ".join(parts))
    total_cold_s = sum(x["cold_ms"] for x in q) / 1000
    waited = sum(x.get("waited_for_reset_s", 0) for x in q)
    failed = sum(1 for x in q if "error" in x)
    print(f"  {'':<20}queries={len(q)} failed={failed} sum of cold calls={total_cold_s:.0f} s, usage-limit wait={waited:.0f} s")

print()
print("== 6. ingest cost ==")
for label, key in ARMS:
    i = reports[key]["ingest"]
    calls = i.get("calls") or 0
    per_call = (f"per call: {i['seconds'] / calls:.1f} s, {i['output_tokens'] / calls:.0f} output, "
                f"{i['cache_tokens'] / calls:.0f} cache, ${i['dollars'] / calls:.4f}") if calls else "no model calls"
    print(f"  {label:<20}seconds={i['seconds']:.1f} calls={calls} input={i['input_tokens']} output={i['output_tokens']} "
          f"cache={i.get('cache_tokens', 0)} embedding={i.get('embedding_tokens')} dollars={i['dollars']:.3f} "
          f"services={i['services']} documents={i['documents']} | {per_call}")
for field in ("seconds", "output_tokens", "cache_tokens", "dollars"):
    print(f"  B median/min/max {field:<14}{mmm([float(r['ingest'][field]) for r in b])}")
```

```
$ python3 $W/report_numbers.py $W build
== 1. headline, both weightings (weighted sum / 100, so both are on 0..1) ==
arm                 40/25/15/10/10  equal weights 
B run 1             0.1458          0.1483        
B run 2             0.1427          0.1425        
B run 3             0.1463          0.1476        
baseline            0.1311          0.1136        
B no-model (09-29)  0.2060          0.1730        
B median/min/max    0.146 / 0.143 / 0.146     0.148 / 0.143 / 0.148
per-surface contribution (F1, or recall where precision is undefined):
  B run 1             explain=0.176 search=0.077 ask=0.147 contradictions=0.160 stale=0.182
  B run 2             explain=0.184 search=0.068 ask=0.125 contradictions=0.164 stale=0.172
  B run 3             explain=0.178 search=0.087 ask=0.121 contradictions=0.185 stale=0.167
  baseline            explain=0.165 search=0.069 ask=0.290 contradictions=0.043 stale=0.000
  B no-model (09-29)  explain=0.212 search=0.267 ask=0.314 contradictions=0.071 stale=0.000
order under 40/25/15/10/10: B no-model (09-29) 0.2060 > B run 3 0.1463 > B run 1 0.1458 > B run 2 0.1427 > baseline 0.1311
order under equal: B no-model (09-29) 0.1730 > B run 1 0.1483 > B run 3 0.1476 > B run 2 0.1425 > baseline 0.1136

== 2. counts per surface, per run ==
-- explain
  B run 1             P=0.127 R=0.283 F1=0.176  tp=79 returned=620 expected=279 hard_fp=470 unplanted=71 uncited=0
  B run 2             P=0.129 R=0.315 F1=0.184  tp=88 returned=680 expected=279 hard_fp=528 unplanted=64 uncited=0
  B run 3             P=0.127 R=0.297 F1=0.178  tp=83 returned=652 expected=279 hard_fp=499 unplanted=70 uncited=0
  baseline            P=0.136 R=0.208 F1=0.165  tp=58 returned=425 expected=279 hard_fp=297 unplanted=70 uncited=0
  B no-model (09-29)  P=0.829 R=0.122 F1=0.212  tp=34 returned=41 expected=279 hard_fp=7 unplanted=0 uncited=0
-- search
  B run 1             P=0.047 R=0.211 F1=0.077  tp=8 returned=170 expected=38 hard_fp=107 unplanted=55 uncited=0
  B run 2             P=0.041 R=0.184 F1=0.068  tp=7 returned=169 expected=38 hard_fp=116 unplanted=46 uncited=0
  B run 3             P=0.053 R=0.237 F1=0.087  tp=9 returned=170 expected=38 hard_fp=105 unplanted=56 uncited=0
  baseline            P=0.043 R=0.184 F1=0.069  tp=7 returned=164 expected=38 hard_fp=66 unplanted=91 uncited=0
  B no-model (09-29)  P=0.231 R=0.316 F1=0.267  tp=12 returned=52 expected=38 hard_fp=40 unplanted=0 uncited=0
-- ask
  B run 1             P=0.122 R=0.185 F1=0.147  correct_sentences=5 sentences=41 covered=5/27
  B run 2             P=0.108 R=0.148 F1=0.125  correct_sentences=4 sentences=37 covered=4/27
  B run 3             P=0.103 R=0.148 F1=0.121  correct_sentences=4 sentences=39 covered=4/27
  baseline            P=0.257 R=0.333 F1=0.290  correct_sentences=9 sentences=35 covered=9/27
  B no-model (09-29)  P=0.256 R=0.407 F1=0.314  correct_sentences=11 sentences=43 covered=11/27
-- contradictions
  B run 1             P=0.174 R=0.148 F1=0.160  matched=4 returned=23 expected=27 winner=4/4
  B run 2             P=0.147 R=0.185 F1=0.164  matched=5 returned=34 expected=27 winner=5/5
  B run 3             P=0.185 R=0.185 F1=0.185  matched=5 returned=27 expected=27 winner=5/5
  baseline            P=0.053 R=0.037 F1=0.043  matched=1 returned=19 expected=27 winner=1/1
  B no-model (09-29)  P=1.000 R=0.037 F1=0.071  matched=1 returned=1 expected=27 winner=1/1
-- stale
  B run 1             P=0.143 R=0.250 F1=0.182  tp=5 returned=35 expected=20
  B run 2             P=0.132 R=0.250 F1=0.172  tp=5 returned=38 expected=20
  B run 3             P=0.125 R=0.250 F1=0.167  tp=5 returned=40 expected=20
  baseline            P=0.000 R=0.000 F1=0.000  tp=0 returned=25 expected=20
  B no-model (09-29)  P=n/a R=0.000 F1=0.000  tp=0 returned=0 expected=20

== 3. by category (truth fact's category), tp per run ==
-- explain: business-logic expected=108, history expected=27, operations expected=44, technical-implementation expected=100
  B run 1             business-logic=39 history=4 operations=8 technical-implementation=28
  B run 2             business-logic=43 history=3 operations=7 technical-implementation=35
  B run 3             business-logic=39 history=2 operations=7 technical-implementation=35
  baseline            business-logic=18 history=2 operations=12 technical-implementation=26
  B no-model (09-29)  business-logic=28 history=0 operations=0 technical-implementation=6
-- search: business-logic expected=19, history expected=1, operations expected=7, technical-implementation expected=11
  B run 1             business-logic=6 history=0 operations=0 technical-implementation=2
  B run 2             business-logic=5 history=0 operations=1 technical-implementation=1
  B run 3             business-logic=5 history=0 operations=2 technical-implementation=2
  baseline            business-logic=6 history=0 operations=0 technical-implementation=1
  B no-model (09-29)  business-logic=10 history=0 operations=0 technical-implementation=2
-- ask: business-logic expected=14, history expected=5, operations expected=2, technical-implementation expected=6
  B run 1             business-logic=3 history=1 operations=0 technical-implementation=1
  B run 2             business-logic=3 history=0 operations=0 technical-implementation=1
  B run 3             business-logic=1 history=2 operations=0 technical-implementation=1
  baseline            business-logic=5 history=1 operations=1 technical-implementation=2
  B no-model (09-29)  business-logic=8 history=0 operations=0 technical-implementation=3

== 4. tier, category, validity, entity resolution (explain and search) ==
-- explain
  B run 1             exec P=0.875 (35/40) R=0.565 (35/62) hard_errors=0 exec-claims-not-credited=5 | cat=0.899 (71/79) | validity=0.545 (12/22) | ER P=0.973 R=0.609 unresolved=21
                      confusion {"code": {"code": 2, "documented": 16}, "documented": {"documented": 24}, "executed": {"documented": 2, "executed": 35}}
  B run 2             exec P=0.857 (36/42) R=0.581 (36/62) hard_errors=0 exec-claims-not-credited=6 | cat=0.841 (74/88) | validity=0.522 (12/23) | ER P=0.982 R=0.590 unresolved=22
                      confusion {"code": {"code": 2, "documented": 23}, "documented": {"documented": 26}, "executed": {"documented": 1, "executed": 36}}
  B run 3             exec P=0.875 (35/40) R=0.565 (35/62) hard_errors=0 exec-claims-not-credited=5 | cat=0.880 (73/83) | validity=0.500 (12/24) | ER P=0.955 R=0.594 unresolved=23
                      confusion {"code": {"code": 2, "documented": 21}, "documented": {"documented": 24}, "executed": {"documented": 1, "executed": 35}}
  baseline            exec P=0.114 (5/44) R=0.081 (5/62) hard_errors=11 exec-claims-not-credited=39 | cat=0.534 (31/58) | validity=0.000 (0/11) | ER P=0.973 R=0.416 unresolved=9
                      confusion {"code": {"code": 14, "documented": 9, "executed": 3}, "documented": {"documented": 17}, "executed": {"code": 5, "documented": 5, "executed": 5}}
  B no-model (09-29)  exec P=0.842 (32/38) R=0.516 (32/62) hard_errors=0 exec-claims-not-credited=6 | cat=1.000 (34/34) | validity=1.000 (16/16) | ER P=0.985 R=0.560 unresolved=18
                      confusion {"code": {"code": 2}, "executed": {"executed": 32}}
  B median/min/max exec P   0.875 / 0.857 / 0.875
  B median/min/max exec R   0.565 / 0.565 / 0.581
  B median/min/max category 0.880 / 0.841 / 0.899
  B median/min/max validity 0.522 / 0.500 / 0.545
  B median/min/max ER P     0.973 / 0.955 / 0.982
  B median/min/max ER R     0.594 / 0.590 / 0.609
-- search
  B run 1             exec P=0.353 (6/17) R=0.353 (6/17) hard_errors=0 exec-claims-not-credited=11 | cat=1.000 (8/8) | validity=0.000 (0/1) | ER P=0.917 R=0.379 unresolved=11
                      confusion {"code": {"documented": 1}, "executed": {"documented": 1, "executed": 6}}
  B run 2             exec P=0.357 (5/14) R=0.294 (5/17) hard_errors=0 exec-claims-not-credited=9 | cat=0.857 (6/7) | validity=0.500 (1/2) | ER P=0.846 R=0.423 unresolved=9
                      confusion {"documented": {"documented": 1}, "executed": {"documented": 1, "executed": 5}}
  B run 3             exec P=0.333 (5/15) R=0.294 (5/17) hard_errors=0 exec-claims-not-credited=10 | cat=0.889 (8/9) | validity=0.333 (1/3) | ER P=0.882 R=0.484 unresolved=11
                      confusion {"code": {"documented": 2}, "documented": {"documented": 1}, "executed": {"documented": 1, "executed": 5}}
  baseline            exec P=0.133 (2/15) R=0.118 (2/17) hard_errors=6 exec-claims-not-credited=13 | cat=1.000 (7/7) | validity=0.000 (0/2) | ER P=0.917 R=0.393 unresolved=6
                      confusion {"code": {"code": 1, "documented": 1}, "executed": {"code": 2, "documented": 1, "executed": 2}}
  B no-model (09-29)  exec P=0.261 (12/46) R=0.706 (12/17) hard_errors=0 exec-claims-not-credited=34 | cat=1.000 (12/12) | validity=0.750 (3/4) | ER P=0.955 R=0.457 unresolved=15
                      confusion {"executed": {"executed": 12}}
  B median/min/max exec P   0.353 / 0.333 / 0.357
  B median/min/max exec R   0.294 / 0.294 / 0.353
  B median/min/max category 0.889 / 0.857 / 1.000
  B median/min/max validity 0.333 / 0.000 / 0.500
  B median/min/max ER P     0.882 / 0.846 / 0.917
  B median/min/max ER R     0.423 / 0.379 / 0.484
-- explain and search pooled (the paired bootstrap's executed_precision pools the same counts)
  B run 1             exec P=0.719 (41/57) R=0.519 (41/79) hard_errors=0
  B run 2             exec P=0.732 (41/56) R=0.519 (41/79) hard_errors=0
  B run 3             exec P=0.727 (40/55) R=0.506 (40/79) hard_errors=0
  baseline            exec P=0.119 (7/59) R=0.089 (7/79) hard_errors=17
  B no-model (09-29)  exec P=0.524 (44/84) R=0.557 (44/79) hard_errors=0

== 5. latency ==
cold (the scorer's table: each query's first call; p50/p95 across the surface's queries), ms
  explain        B run 1: p50=2.2 p95=10.7 | B run 2: p50=2.4 p95=9.3 | B run 3: p50=2.3 p95=10.3 | baseline: p50=31184.3 p95=68861.1 | B no-model (09-29): p50=8.0 p95=9.5
  search         B run 1: p50=10.0 p95=48.3 | B run 2: p50=10.2 p95=81.8 | B run 3: p50=9.9 p95=63.6 | baseline: p50=18936.1 p95=54116.0 | B no-model (09-29): p50=9.4 p95=135.8
  ask            B run 1: p50=4450.1 p95=6622.4 | B run 2: p50=5718.4 p95=7982.5 | B run 3: p50=5213.0 p95=8184.7 | baseline: p50=7604.8 p95=11649.7 | B no-model (09-29): p50=12.1 p95=99.4
  contradictions B run 1: p50=8.1 p95=31.9 | B run 2: p50=8.1 p95=38.5 | B run 3: p50=8.8 p95=31.2 | baseline: p50=30679.9 p95=76216.3 | B no-model (09-29): p50=5.1 p95=8.0
  stale          B run 1: p50=21.5 p95=25.1 | B run 2: p50=18.9 p95=22.2 | B run 3: p50=20.4 p95=21.4 | baseline: p50=91482.5 p95=122650.2 | B no-model (09-29): p50=2.9 p95=3.3
warm repeats (per query: p50/p95 over its repeats; here the median of the per-query p50s and the max of the per-query p95s), ms
  B run 1             repeats=[3] explain: p50med=2.023 p95max=8.945 n=25 | search: p50med=8.494 p95max=16.643 n=17 | ask: p50med=0.001 p95max=0.005 n=13 | contradictions: p50med=7.098 p95max=32.479 n=4 | stale: p50med=21.284 p95max=172.192 n=3
                      queries=62 failed=0 sum of cold calls=63 s, usage-limit wait=0 s
  B run 2             repeats=[3] explain: p50med=2.137 p95max=9.368 n=25 | search: p50med=8.995 p95max=23.830 n=17 | ask: p50med=0.001 p95max=0.008 n=13 | contradictions: p50med=7.468 p95max=40.275 n=4 | stale: p50med=18.892 p95max=20.744 n=3
                      queries=62 failed=0 sum of cold calls=74 s, usage-limit wait=0 s
  B run 3             repeats=[3] explain: p50med=2.110 p95max=9.173 n=25 | search: p50med=8.786 p95max=14.969 n=17 | ask: p50med=0.001 p95max=0.006 n=13 | contradictions: p50med=6.093 p95max=33.691 n=4 | stale: p50med=20.032 p95max=21.028 n=3
                      queries=62 failed=0 sum of cold calls=69 s, usage-limit wait=0 s
  baseline            repeats=[0] explain=none | search=none | ask=none | contradictions=none | stale=none
                      queries=62 failed=0 sum of cold calls=1926 s, usage-limit wait=0 s
  B no-model (09-29)  repeats=[3] explain: p50med=8.350 p95max=10.425 n=25 | search: p50med=9.558 p95max=14.478 n=17 | ask: p50med=0.000 p95max=0.002 n=13 | contradictions: p50med=5.000 p95max=8.642 n=4 | stale: p50med=2.525 p95max=2.916 n=3
                      queries=62 failed=0 sum of cold calls=1 s, usage-limit wait=0 s

== 6. ingest cost ==
  B run 1             seconds=2217.5 calls=198 input=398 output=222005 cache=654851 embedding=16088 dollars=5.772 services=['postgres'] documents=258 | per call: 11.2 s, 1121 output, 3307 cache, $0.0292
  B run 2             seconds=2253.2 calls=198 input=396 output=221952 cache=643407 embedding=15304 dollars=5.743 services=['postgres'] documents=258 | per call: 11.4 s, 1121 output, 3250 cache, $0.0290
  B run 3             seconds=2127.2 calls=198 input=396 output=211935 cache=651883 embedding=16153 dollars=5.614 services=['postgres'] documents=258 | per call: 10.7 s, 1070 output, 3292 cache, $0.0284
  baseline            seconds=0.0 calls=0 input=0 output=0 cache=0 embedding=0 dollars=0.000 services=[] documents=258 | no model calls
  B no-model (09-29)  seconds=53.5 calls=0 input=0 output=0 cache=0 embedding=1728 dollars=0.000 services=['postgres'] documents=120 | no model calls
  B median/min/max seconds       2217.521 / 2127.203 / 2253.191
  B median/min/max output_tokens 221952.000 / 211935.000 / 222005.000
  B median/min/max cache_tokens  651883.000 / 643407.000 / 654851.000
  B median/min/max dollars       5.743 / 5.614 / 5.772
```

### B.3 Corpus size and document length: `corpus_size.py`

The baseline arm's own estimate over the ingest root its run assembled
(`build/ingest/`, written at the baseline's start, 08:11 UTC), and the
words per source document.

```python
"""The baseline arm's own corpus estimate (len(text) // 4, its fallback test)
over the assembled c6 ingest root, and the words per source document, for the
ingest-cost caveat. Imports the arm's functions; changes nothing."""

import sys
from pathlib import Path

spike = Path(sys.argv[1])
root = Path(sys.argv[2])
sys.path.insert(0, str(spike))
from prototypes.baseline import (  # noqa: E402
    DEFAULT_MAX_CORPUS_TOKENS,
    _build_documents,
    _estimate_tokens,
)

docs = _build_documents(root)
corpus = "\n\n".join(f"=== {doc_id} ===\n{text}" for doc_id, text in docs)
print(f"documents={len(docs)} corpus_estimate_tokens={_estimate_tokens(corpus)} "
      f"fallback_threshold={DEFAULT_MAX_CORPUS_TOKENS} full_path={_estimate_tokens(corpus) <= DEFAULT_MAX_CORPUS_TOKENS}")
by_kind: dict[str, list[int]] = {}
for doc_id, text in docs:
    by_kind.setdefault(doc_id.split("/", 1)[0], []).append(len(text.split()))
for kind, words in sorted(by_kind.items()):
    words.sort()
    print(f"  {kind:<8} n={len(words):<4} words median={words[len(words) // 2]} min={words[0]} max={words[-1]}")
text_docs = [w for k in ("wiki", "doc", "ticket", "pull") for w in by_kind.get(k, [])]
text_docs.sort()
print(f"  text documents (wiki+doc+ticket+pull) n={len(text_docs)} words median={text_docs[len(text_docs) // 2]} mean={sum(text_docs) / len(text_docs):.0f}")
```

```
$ ls -ld build/ingest && cat build/ingest/step.json
drwxr-xr-x Oct 20 04:11 build/ingest
{"step": "c6"}

$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python $W/corpus_size.py "$PWD" build/ingest
documents=258 corpus_estimate_tokens=109344 fallback_threshold=150000 full_path=True
  code     n=106  words median=79 min=0 max=2718
  doc      n=10   words median=391 min=346 max=444
  pull     n=8    words median=128 min=62 max=233
  run      n=14   words median=297 min=90 max=1335
  ticket   n=80   words median=74 min=47 max=174
  wiki     n=40   words median=237 min=201 max=334
  text documents (wiki+doc+ticket+pull) n=138 words median=88 mean=152
```

### B.4 What git shows of the effort

```
$ gh pr list --repo konyklabs/asbuilt --state merged --limit 50 --json number,mergedAt,additions,deletions,title --jq 'sort_by(.number) | .[] | "#\(.number)  merged \(.mergedAt[0:16])Z  +\(.additions)/-\(.deletions)  \(.title[0:72])"'
#1  merged 2026-09-28T10:52Z  +507/-0  docs(asbuilt): bootstrap the project overview and the org CI callers (ko
#6  merged 2026-09-28T17:19Z  +25340/-63  feat(spike): the benchmark harness and the invented system Gearwell (#2)
#10  merged 2026-09-28T21:26Z  +7680/-1279  feat(spike): harden the harness before any benchmark arm runs (#7)
#11  merged 2026-09-29T01:31Z  +5657/-25  feat(spike): the test connector, engine-independent, with bag-of-facts s
#12  merged 2026-09-29T09:23Z  +878/-34  feat(spike): claude-code provider for the model extractor, on the subscr
#13  merged 2026-09-29T09:28Z  +3473/-276  feat(spike): the no-store baseline arm, the MCP adapter, and transcripts
#14  merged 2026-09-29T10:00Z  +6998/-21  feat(spike): stack B, our own fact model on Postgres + pgvector, with th
#16  merged 2026-09-29T18:54Z  +489/-27  feat(spike): record model usage, keep paid-for facts on a stop, and esti
#19  merged 2026-09-30T01:58Z  +197/-10  feat(spike): ask the model extractor for the rule a test proves, not its
#20  merged 2026-09-30T01:58Z  +1877/-43  feat(spike): hold fuller statements to fair matching rules, calibrated o
#22  merged 2026-09-30T10:15Z  +483/-39  feat(spike): quote what a failed claude-code call said and retry once wh
#24  merged 2026-09-30T12:31Z  +63/-8  fix(spike): a structured-output call gets four turns, not one (#23)
#26  merged 2026-10-06T21:52Z  +218/-4  chore(asbuilt): add the local pipeline and the rapid mode for the spike 
#27  merged 2026-10-06T21:59Z  +102/-1  fix(spike): write the stack-B claim value as anyOf and refuse what Ajv s
#28  merged 2026-10-06T23:21Z  +68/-1  fix(spike): an arm run refuses the fallback embedder and skipped NLI unl
#29  merged 2026-10-06T23:57Z  +232/-24  fix(spike): a failed query is recorded and the arm goes on, results flus
#30  merged 2026-10-19T20:50Z  +679/-16  fix(spike): wait for a usage-limit reset instead of retrying into it, an
#31  merged 2026-10-20T06:16Z  +101/-1  fix(spike): load no settings files and name the effort on every claude -
```
