# asbuilt demo: stack B through the MCP adapter

For konyklabs/asbuilt#5. Gearwell is an invented bike-share back office (the
fixture under `spike/system/` and `spike/sources/`); nothing here describes a
real system.

Every "the tool returns" block below is quoted from the 2026-10-20 overnight
run (asbuilt `main` at ad73e93, effort `medium`), never written for this
script. Paths are abbreviated:

- `OVN` = `~/dev/konyklabs/.local/overnight-2026-10-20T0217`
- `OVN/b_postgres-model-N.md` is the transcript of stack B run N. These are
  byte-identical to `spike/build/transcripts/b_postgres-model-N.md` (checked
  with `cmp`, all three).
- `OVN/results-b_postgres-model-N.json` holds the same answers with their
  structured citations.

Two things to know before quoting any of it on stage:

1. **The transcripts came from `bench/run.py`, not from an MCP session.** It
   calls the same `Prototype` methods the MCP tools call. The MCP text block
   renders a fact the same way, `- [tier] statement (document#location, ...)`
   (`spike/asbuilt_mcp.py:164`, `spike/bench/run.py:398`). A contradiction is
   laid out differently: `- (refutes, winner=a|b)` then `a:` and `b:` lines
   (`spike/asbuilt_mcp.py:258`), where the transcript shows `A:`/`B:` and
   the winner's statement. Nothing in the overnight evidence came through the
   adapter, and I found no record of a stack B run through it.
2. **A live run is a fourth model ingest, so its output will not match these
   quotes word for word.** The three overnight runs returned 22, 31 and 25
   contradiction pairs. The pairs named below came back in all three runs,
   and the `ask` answer in prompt 6 changed between runs.

## Setup

The Postgres volume from the overnight run is gone. **A live demo needs one
fresh ingest of about 37 minutes** (2127 to 2253 s in the three runs) on the
Claude Code subscription: 198 `claude -p` calls. The harness's own token-priced
estimate is $5.61 to $5.77. That is list price, not a bill, because the
subscription pays.

The MCP server ingests on its **first tool call**. It does not ingest at
startup, and every new server process starts again from an empty store
(`ensure_ingested` calls `ingest(..., incremental=False)`, which runs
`store.reset()`). So: one Claude Code session, warmed up about 40 minutes
before the demo and kept open. Reconnecting the server with `/mcp`,
restarting `claude` or using `--resume` throws the ingest away.

Each command is one line.

```
# 0. The spike venv must have both extras (prints ok if so; the MCP path does NOT refuse the fallback embedder the way bench/run.py does)
cd ~/dev/konyklabs/asbuilt/spike && .venv/bin/python -c "import fastmcp, psycopg, sentence_transformers; print('ok')"
# only if that failed: both extras in one command (a sync without them removes them)
cd ~/dev/konyklabs/asbuilt/spike && uv sync --extra pipeline --extra serve

# 1. Empty Postgres 17 + pgvector on 127.0.0.1:55432 (down -v, then up --wait)
~/dev/konyklabs/asbuilt/spike/prototypes/b_postgres/reset.sh

# 2. A neutral directory for the demo session, so the model cannot just read spike/truth/ (the answer key)
mkdir -p ~/asbuilt-demo && cd ~/asbuilt-demo

# 3. Register the server (local scope = this directory), server cwd = spike/ as in the overnight runs, timeout above the ingest
claude mcp add-json asbuilt '{"type":"stdio","command":"/bin/sh","args":["-c","cd ~/dev/konyklabs/asbuilt/spike && exec .venv/bin/python asbuilt_mcp.py"],"env":{"ASBUILT_ARM":"b_postgres","ASBUILT_FIXTURE":".","ASBUILT_EFFORT":"medium","ASBUILT_BUDGET_DOLLARS":"10","ASBUILT_WAIT_FOR_RESET":"0"},"timeout":5400000}'

# 4. Check it connects (this starts the server but does not ingest, because ingest waits for the first tool call)
claude mcp get asbuilt

# 5. Start the session
cd ~/asbuilt-demo && claude
```

Why each setting is there:

- **`"timeout": 5400000` (90 minutes).** I read this in the installed CLI
  (2.1.304) binary and its error text. I have not tested it against a live
  ingest. A stdio MCP tool call that sends no progress is aborted after an
  idle limit, and the constant for stdio is 1,800,000 ms (30 minutes), which
  is shorter than the ingest. The error text says: *"set a per-server
  "timeout" (ms) to allow longer silent runs for just this server; otherwise
  set CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT (ms) globally (0 disables)"*. The
  per-server value also becomes that server's hard per-call limit.
- **`ASBUILT_BUDGET_DOLLARS=10`.** Through MCP, nothing else sets a budget
  (`bench/run.py --budget-dollars` is not in this path). `CountingClient`
  stops at 80%, which is $8 against the $5.6 to $5.8 estimate.
- **`ASBUILT_WAIT_FOR_RESET=0`.** If the subscription hits its usage limit
  mid-ingest, the default is to sleep until the reset. Inside a tool call
  that means a timeout. This makes it fail fast instead. Start the warm-up
  with usage headroom.
- **`ASBUILT_EFFORT=medium`** is the default, written out to match the
  overnight runs. Each extraction call already passes `--setting-sources ""`.

The `claude mcp add --help` syntax, for reference (CLI 2.1.304):

```
Usage: claude mcp add [options] <name> <commandOrUrl> [args...]
  # Add stdio server with environment variables:
  claude mcp add my-server -e API_KEY=xxx -- npx my-mcp-server
  -e, --env <env...>           Set environment variables (e.g. -e KEY=value)
  -s, --scope <scope>          Configuration scope (local, user, or project) (default: "local")
```

`add` has no timeout option. The equivalent with it, which then needs the
idle limit raised at launch instead (same caveat: read from the binary, not
tested):

```
claude mcp add asbuilt -e ASBUILT_ARM=b_postgres -e ASBUILT_FIXTURE=. -e ASBUILT_EFFORT=medium -e ASBUILT_BUDGET_DOLLARS=10 -e ASBUILT_WAIT_FOR_RESET=0 -- /bin/sh -c "cd ~/dev/konyklabs/asbuilt/spike && exec .venv/bin/python asbuilt_mcp.py"
CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=5400000 claude
```

(The README's plugin route, `claude --plugin-dir plugin`, runs
`uv run --extra serve` from the plugin and sets no timeout. That is fine for
the null and baseline arms, but not for this demo.)

**Warm-up (about 37 minutes before the demo; not part of the show).** Type:

> Call the asbuilt explain tool for "farebox" with limit 3 and paste the tool's text output verbatim.

To watch progress from another terminal, count documents. The count starts
at 120 (code files and test runs) and ends at 258, when every wiki page,
document, ticket and pull request has been extracted:

```
docker exec asbuilt-b-postgres-postgres-1 psql -U asbuilt -d asbuilt -tAc "select count(*) from asbuilt.document"
```

The ingest runs `claude -p` as a subprocess of the MCP server, and its
stderr goes to Claude Code's MCP log for `asbuilt` (I have not checked where
2.1.304 writes it; `/mcp` in the session shows the server's state). If the count stays at 120 for more than a couple of
minutes, read that log before waiting the 37 minutes. A `claude` binary or
login the server cannot see fails inside that first tool call.

The first three lines in run 1 (`OVN/b_postgres-model-1.md`,
`q-explain-01`), with the citations cut here for width:

```
- [executed] Refund under $5.00 auto approved when flag on. (code/tests/e2e/test_refunds.py#test_refund_under_five_dollars_auto_approved_when_flag_on, run/pytest-c6#tests/e2e/test_refunds.py::test_refund_under_five_dollars_auto_approved_when_flag_on)
- [executed] Single ride cap $30.00. (code/tests/unit/test_pricing.py#test_single_ride_cap_30, run/pytest-c5#..., ..., wiki/casual-pricing##cap, ticket/GW-162#description, pull/14#body)
- [executed] Lost bike fee $150.00. (code/farebox/pricing.py#LOST_BIKE_FEE, code/tests/unit/test_lost_bikes.py#test_lost_bike_fee_150, run/pytest-c6#tests/unit/test_lost_bikes.py::test_lost_bike_fee_150, ticket/GW-163#description, pull/14#body)
```

Every prompt below asks for verbatim output, so that the session's own model
does not paraphrase the tool. `##cap` is not a typo: the renderer puts `#`
in front of a wiki location that already starts with `#`.

## The script

### 1. The wiki says one thing, the test says another

> Use the asbuilt contradictions tool with no entity and limit 100. Paste the pair about the membership grace period verbatim.

Run 1 (`OVN/b_postgres-model-1.md`, `q-contradictions-01`, pair 10 of 22):

```
- A: - [documented] A member gets a 3-day grace period to fix their payment method before their membership lapses. (wiki/membership-faq##grace, ticket/GW-136#description)
  B: - [executed] Membership lapses 7 days after failed renewal. (code/tests/unit/test_memberships.py#test_membership_lapses_7_days_after_failed_renewal, run/pytest-c3#tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal, code/tests/unit/test_memberships.py#test_membership_lapses_7_days_after_failed_renewal, run/pytest-c4#tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal, code/tests/unit/test_memberships.py#test_membership_lapses_7_days_after_failed_renewal, run/pytest-c5#tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal, code/tests/unit/test_memberships.py#test_membership_lapses_7_days_after_failed_renewal, run/pytest-c6#tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal, wiki/glossary##grace-period, wiki/membership-lifecycle##grace, ticket/GW-136#comment-2, pull/11#body)
  label=refutes, winner='Membership lapses 7 days after failed renewal.'
```

Say: the FAQ page says 3 days, and a test that passed at every step from c3
to c6 says 7. The winner is chosen by tier, so the passing test wins. This is
planted contradiction X-002, credited by the scorer in all three runs.

`limit 100` matters. The tool returns 20 pairs per page by default, and the
next pair came back in position 22, 30 and 22 of the three runs.

### 2. The second one it found

> From the same output, paste the pair about the single-ride cap verbatim.

Run 1 (`OVN/b_postgres-model-1.md`, `q-contradictions-01`, pair 22 of 22):

```
- A: - [executed] Single ride cap $30.00. (code/tests/unit/test_pricing.py#test_single_ride_cap_30, run/pytest-c5#tests/unit/test_pricing.py::test_single_ride_cap_30, code/tests/unit/test_pricing.py#test_single_ride_cap_30, run/pytest-c6#tests/unit/test_pricing.py::test_single_ride_cap_30, wiki/casual-pricing##cap, ticket/GW-162#description, pull/14#body)
  B: - [documented] A single ride is capped at $25.00 regardless of how long the bike stays out or how many extras land on top of the per-minute rate. (wiki/fares-overview##cap, doc/fares-price-sheet##caps-and-fees, doc/fares-price-sheet##rate-table, pull/14#comment-2)
  label=refutes, winner='Single ride cap $30.00.'
```

This is planted contradiction X-003, credited in all three runs. Those two are
**all** of the six planted wiki-versus-test contradictions that the scorer
credits to B. See "What B did not surface" below before going further.

### 3. Tier ranking: what the store believes about one rule

> Use the asbuilt explain tool on "lost-bike-fee" with limit 50. Paste the first two lines and any line that mentions $100 verbatim.

Run 1 (`OVN/b_postgres-model-1.md`, `q-explain-06`, lines 1, 2 and 16 of 22,
p50 2.0 ms):

```
- [executed] Lost bike fee $150.00. (code/farebox/pricing.py#LOST_BIKE_FEE, code/tests/unit/test_lost_bikes.py#test_lost_bike_fee_150, run/pytest-c6#tests/unit/test_lost_bikes.py::test_lost_bike_fee_150, ticket/GW-163#description, pull/14#body)
- [code] Lost bike fee $100.00. (code/tests/unit/test_lost_bikes.py#test_lost_bike_fee_100, run/pytest-c1#tests/unit/test_lost_bikes.py::test_lost_bike_fee_100, code/tests/unit/test_lost_bikes.py#test_lost_bike_fee_100, run/pytest-c2#tests/unit/test_lost_bikes.py::test_lost_bike_fee_100, code/tests/unit/test_lost_bikes.py#test_lost_bike_fee_100, run/pytest-c3#tests/unit/test_lost_bikes.py::test_lost_bike_fee_100, code/tests/unit/test_lost_bikes.py#test_lost_bike_fee_100, run/pytest-c4#tests/unit/test_lost_bikes.py::test_lost_bike_fee_100, code/tests/unit/test_lost_bikes.py#test_lost_bike_fee_100, run/pytest-c5-rerun#tests/unit/test_lost_bikes.py::test_lost_bike_fee_100)
- [documented] Missing the 24-hour docking window currently costs the rider $100.00. (wiki/lost-and-stolen-bikes##lost-fee, doc/fares-price-sheet##caps-and-fees, doc/fares-price-sheet##rate-table)
```

Say: results are ranked executed, then code, then documented. The $100 test
passed from c1 to c4 and failed at c5, so it dropped from executed to code.
The wiki page still says $100 and sits at the bottom. The same three tiers in
the same order came back in runs 2 and 3. (The `run/pytest-c5-rerun`
citation on the code line is not supposed to be there: the truth schema says
reruns are never cited. Don't point at it.)

### 4. What a citation is

> Show the structured citations (document, location, version) for the $150 fact from that result.

Whether Claude Code passes the tool's `structuredContent` to the model, or
only its text block, is not verified. The text block has no versions. If the
session can't show them, show this from the results file instead: run 1,
`OVN/results-b_postgres-model-1.json`, `q-explain-06`, result 0:

```json
"tier": "executed",
"citations": [
  {"document": "code/farebox/pricing.py", "location": "LOST_BIKE_FEE", "version": "710c96573b202d8448f73542ab69ff1685fb160f"},
  {"document": "code/tests/unit/test_lost_bikes.py", "location": "test_lost_bike_fee_150", "version": "1ab33e0eca9b2ec15c77ebe84b3bba04f1d1d87e"},
  {"document": "run/pytest-c6", "location": "tests/unit/test_lost_bikes.py::test_lost_bike_fee_150", "version": null},
  {"document": "ticket/GW-163", "location": "description", "version": "2026-07-22T14:10:00-04:00"},
  {"document": "pull/14", "location": "body", "version": "2026-07-22T14:00:00-04:00"}
],
"claim": {"entity": "lost bike fee", "attribute": "lost_bike_fee", "value": 150, "unit": "usd"},
"valid_from": "2026-07-22T00:00:00+00:00",
"valid_to": null
```

Say: a code citation's version is the commit that last changed the file, a
ticket's or pull request's is its timestamp, and a test run's is the run id
itself. The wiki line from prompt 3 carries
`{"document": "wiki/lost-and-stolen-bikes", "location": "#lost-fee", "version": "2"}`,
meaning page revision 2. The old $100 fact carries
`"valid_to": "2026-07-22T18:00:00+00:00"` (same file, result 1).

### 5. Which pages have gone stale

> Use the asbuilt stale tool with since 2026-03-01T00:00:00-05:00. Paste the lines about the single-ride cap and the grace period verbatim, and tell me how many lines came back in total.

Run 1 (`OVN/b_postgres-model-1.md`, `q-stale-01`, 2 of 16 lines, p50 22.6 ms):

```
- [documented] A single ride is capped at $25.00 regardless of how long the bike stays out or how many extras land on top of the per-minute rate. (wiki/fares-overview##cap, doc/fares-price-sheet##caps-and-fees, doc/fares-price-sheet##rate-table, pull/14#comment-2)
- [documented] A member gets a 3-day grace period to fix their payment method before their membership lapses. (wiki/membership-faq##grace, ticket/GW-136#description)
```

Say: these are pages the code has moved past. The scorer credited three
planted stale pages from these two lines (S-003, S-004, S-005), the same in
all three runs. Be plain about the rest: 16 lines came back for 10 planted
pages, and most of them are not stale. One example from the same output:
`- [documented] The annual membership plan costs $120.00 once a year. (wiki/membership-faq##plans, ticket/GW-110#description)`.
Stale F1 is 0.17 to 0.18. That is low, but the baseline scored 0.000.

### 6. A free-form question, and why it is the weak surface

> Use the asbuilt ask tool: "How long can a membership go unpaid after a failed renewal before it lapses?" Paste the answer verbatim.

Run 1 (`OVN/b_postgres-model-1.md`, `q-ask-02`) got it right:

```
- A membership sits in a grace period after a failed renewal, and lapses automatically once that grace window closes. (wiki/glossary##grace-period, wiki/membership-lifecycle##grace)
- Currently the grace window is 7 days. (run/pytest-c6#tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal, run/pytest-c5#tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal, run/pytest-c4#tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal)
- This 7-day window replaced a previous 3-day window, giving a second retry attempt more room to land before the account falls over. (pull/11#body, run/pytest-c2#tests/unit/test_memberships.py::test_membership_lapses_3_days_after_failed_renewal, run/pytest-c1#tests/unit/test_memberships.py::test_membership_lapses_3_days_after_failed_renewal)
```

Run 3 (`OVN/b_postgres-model-3.md`, `q-ask-02`) got it wrong, by majority vote:

```
- So, based on the majority and the explicit grace-period description, the supported answer is 3 days, though one fact contradicts this with 7 days. (run/pytest-c2#tests/unit/test_memberships.py::test_membership_lapses_3_days_after_failed_renewal, run/pytest-c1#tests/unit/test_memberships.py::test_membership_lapses_3_days_after_failed_renewal, code/tests/unit/test_memberships.py#test_membership_lapses_3_days_after_failed_renewal)
```

Say: `ask` has a model write sentences over the top facts, and that model can
ignore the tier the store assigned. A live run can come out either way. This
is the surface where the baseline beats B (ask F1 0.290 against 0.147). Show
both answers, whichever one the live session produces.

### 7. Where B picked the wrong winner

> From the contradictions output in step 1, paste the pairs about how many bikes a rider can hold and about the rebalance trigger verbatim.

Run 1 (`OVN/b_postgres-model-1.md`, `q-contradictions-01`, pairs 18 and 8):

```
- A: - [documented] A rider can have up to 3 bikes checked out to their account at once. (wiki/checkout-rules##limit)
  B: - [documented] If the rider already has 2 bikes checked out to their account, a third checkout attempt returns HTTP 409 with checkout_limit_reached rather than succeeding. (wiki/dockyard-api##checkout, doc/dockyard-design##checkout, ticket/GW-116#comment-2)
  label=refutes, winner='A rider can have up to 3 bikes checked out to their account at once.'
- A: - [documented] A station is flagged for a rebalance order once it drops under 25% full. (wiki/rebalancing-overview##trigger)
  B: - [documented] A station qualifies for a rebalance order once it falls under 20% full. (doc/dispatch-design##rebalance)
  label=refutes, winner='A station is flagged for a rebalance order once it drops under 25% full.'
```

Say: both are planted wiki-versus-test contradictions (X-005, X-006). The
test (`test_third_checkout_refused`, the dispatch Vitest) holds the true
values, 2 bikes and 20%. B paired the wiki with another *document* instead of
the test, so tier never decided it, and B named the wiki as the winner,
which is wrong. The same thing happened in all three runs. For the checkout
limit, `ask` led with "up to 3 bikes" in all three runs (`q-ask-10`).

### 8. Asking by name, and getting nothing

> Use the asbuilt explain tool on "member-free-minutes", then the contradictions tool with entity "member-free-minutes". Paste both outputs verbatim.

All three runs (`OVN/b_postgres-model-{1,2,3}.md`, `q-explain-04` and
`q-contradictions-02`):

```
(no facts)
```
```
(no contradictions)
```

Say: the facts exist. `explain("farebox")` in run 1 lists
`- [executed] Member 1st 30 minutes free. (code/tests/e2e/test_pricing.py#test_member_first_thirty_minutes_free, run/pytest-c4#..., ...)`.
The test's fact is filed under `farebox` and `pricing`, and the documents'
45- and 30-minute statements under the per-minute rate (`MEMBER_RATE`). Nothing is filed under
the rule's own name, so asking for it by name finds nothing, and the test and
the wiki never meet. That is why X-001 is missed. `explain("membership-grace")` is also empty in all
three runs.

## What B did not surface

There are six planted wiki-versus-test contradictions (X-001 to X-006 in
`spike/truth/contradictions.yaml`). In each of the three runs:

| | planted | scorer credits B | what B returned (all three runs) |
|---|---|---|---|
| X-001 | wiki: 45 free minutes / test: 30 | no, no, no | The 45-minute wiki against the 30-minute promotion page, ticket and PR, with no test on either side. Winner right (30). Both filed under `MEMBER_RATE`, so the scorer cannot match them. |
| X-002 | wiki: 3-day grace / test: 7 days | yes, yes, yes | prompt 1 |
| X-003 | wiki: $25 cap / test: $30 | yes, yes, yes | prompt 2 |
| X-004 | wiki: $100 lost-bike fee / test: $150 | no, no, no | The wiki's $100 against the executed $150 (pair 5 in run 1), winner $150. **Hand-read only.** The scorer rejects the wording of the wiki side. This is owed to the hand audit, not claimed. |
| X-005 | wiki: 3 bikes / test: 2 | no, no, no | The wiki against other documents. **Wrong winner** (the wiki). |
| X-006 | wiki: under 25% / test: under 20% | no, no, no | The wiki against the design doc. **Wrong winner** (the wiki). |

Scored: 2 of 6, the same two in every run. Do not say B finds contradictions
the baseline misses. In the one baseline run (`OVN/baseline-model-1.md`,
`q-contradictions-01`), read by hand, the baseline returned all six of these
pairs with the test or code side as the winner. The scorer credited none of
them, because it could not resolve the baseline's entity names (for example
`rule:checkout-limit`) or match its longer statements. The contradictions
comparison is inconclusive (bootstrap difference +0.117, CI -0.286 to 0.182,
n=4 queries). The scorer's undercounting on both arms is a question for the
hand audit.

## Numbers to say out loud

All from `OVN/SUMMARY.md`. These compare B run 1 against baseline run 1,
paired bootstrap over queries (A - B):

- Executed-tier precision: B 0.875 (35/40), baseline 0.114 (5/44);
  difference +0.601, CI 0.428 to 0.739. Across B's three runs: 0.857 to 0.875.
- Stale: +0.182, CI 0.105 to 0.231 (baseline F1 0.000).
- Explain +0.011 and search +0.008. Both CIs span zero: ties.
- Ask: -0.143, CI -0.284 to -0.008. B loses.
- Latency p50: explain 2.2 ms against 31.2 s, stale 21 ms against 91.5 s,
  ask 4.5 s against 7.6 s.

## What this does not show yet

- Code extraction is not built. B's code and executed tiers come only from
  test names and test runs. It never reads a constant like `CHECKOUT_LIMIT`.
- Executed-tier precision is 0.857 to 0.875 across three runs. That is under
  the 0.95 bar D-013 sets before "a passing test is the evidence" can be
  claimed.
- This is one invented fixture of 258 documents, small enough to fit a
  context window (about 430 KB under `build/ingest`), and one baseline run.
  The hand audit of what the scorer did not credit is still owed.
