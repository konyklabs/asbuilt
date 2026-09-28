# Executed-fact audit

For asbuilt#7 (D-013: a passing test proves exactly what it asserted). Each of the
28 facts that were `executed` in the first cut of the truth, with the test its
carrier names, read at every step it runs (`system/` plus the `history/` overlays).

- **a**: the assertion proves the statement as written.
- **b**: the statement claims more than the assertion; it is narrowed to what is
  asserted, keeping its id. The narrowed statement is in `facts.yaml`.
- **c**: the statement is right but unproven at a boundary; the assertion below is
  added to the same test (same node id), at the steps given, in wave 2.

Counts: a 15, b 2, c 11. `truth/validate.py` checks that
this table covers every executed or demoted fact and that each (b) row's statement
matches `facts.yaml`.

| Fact | Test | Verdict | Asserts now | Narrowed statement, or assertion to add | Steps |
|---|---|---|---|---|---|
| F-001 | `tests/e2e/test_pricing.py::test_member_first_thirty_minutes_free` | c | a member's 20-minute ride costs 0 cents | add: a member ride of exactly 30 minutes costs 0 cents and a 31-minute member ride costs 15 cents | c1 (history/c1 overlay) |
| F-002 | `tests/e2e/test_pricing.py::test_member_first_fortyfive_minutes_free` | c | a member's 40-minute ride costs 0 cents | add: a member ride of exactly 45 minutes costs 0 cents and a 46-minute member ride costs 15 cents | c2, c3 (history/c3 overlay) |
| F-003 | `tests/e2e/test_pricing.py::test_member_first_thirty_minutes_free` | c | a member's 20-minute ride costs 0 cents | add: a member ride of exactly 30 minutes costs 0 cents and a 31-minute member ride costs 15 cents | c4, c5, c6 (final file) |
| F-004 | `tests/e2e/test_pricing.py::test_casual_ride_charges_one_dollar_unlock_fee` | a | a casual zero-minute ride costs 100 cents, which is the unlock fee alone | - | - |
| F-005 | `tests/unit/test_pricing.py::test_member_rate_after_free_minutes` | a | MEMBER_RATE is 0.15 and a member ride 10 minutes past the free minutes costs 150 cents | - | - |
| F-006 | `tests/unit/test_pricing.py::test_casual_rate_from_first_minute` | a | CASUAL_RATE is 0.25 and a 10-minute casual ride costs 350 cents (100 unlock plus 10 x 25) | - | - |
| F-007 | `tests/unit/test_pricing.py::test_ebike_surcharge_when_flag_on` | c | on a 10-minute casual e-bike ride the flag adds 100 cents; members are not exercised | add: with the flag on, a member e-bike ride of MEMBER_FREE_MINUTES minutes costs 0 cents and one of MEMBER_FREE_MINUTES + 10 minutes costs 250 cents (10 x (15 + 10)) | c1-c6 |
| F-008 | `tests/unit/test_pricing.py::test_single_ride_cap_25` | a | SINGLE_RIDE_CAP is 25.00 and a 1000-minute casual ride costs exactly 2500 cents | - | - |
| F-009 | `tests/unit/test_pricing.py::test_single_ride_cap_30` | a | SINGLE_RIDE_CAP is 30.00 and a 1000-minute casual ride costs exactly 3000 cents | - | - |
| F-010 | `tests/unit/test_lost_bikes.py::test_ride_open_past_24_hours_closed_as_lost` | c | a ride open 24 hours and 1 minute is closed as lost | add: a ride open 23 hours and 59 minutes is not closed (close_lost_rides returns an empty list) | c1-c6 |
| F-011 | `tests/unit/test_lost_bikes.py::test_lost_bike_fee_100` | a | the lost ride's invoice line exceeds its ride charge by exactly 10000 cents | none; the planted failure at c5 demotes this fact to code (truth/planted-runs.yaml, X-021) | c1-c4 pass, c5 fails |
| F-012 | `tests/unit/test_lost_bikes.py::test_lost_bike_fee_150` | a | the lost ride's invoice line exceeds its ride charge by exactly 15000 cents | none; the planted failure at c5 means the $150.00 test first runs and passes at c6 | c6 |
| F-013 | `tests/e2e/test_refunds.py::test_refund_after_14_days_rejected` | c | a request 15 days after the ride ended gets 422 refund_window_expired | add: a request exactly 14 days after the ride ended gets 201 with status requested, and one 14 days and 1 minute after gets 422 refund_window_expired | c1-c6 (history/c5 overlay and final file) |
| F-014 | `tests/e2e/test_refunds.py::test_refund_under_five_dollars_auto_approved_when_flag_on` | c | with the flag on, a 499-cent refund is approved | add: with the flag on, a 500-cent refund stays requested; with the flag off, a 499-cent refund stays requested | c6 |
| F-015 | `tests/unit/test_memberships.py::test_membership_lapses_3_days_after_failed_renewal` | b | GRACE_DAYS is 3, the membership moves to grace and grace_ends_at is the failure plus 3 days; no code moves a membership from grace to lapsed, so an assertion cannot prove 'lapses' | A failed renewal gives a membership a grace period that ends 3 days after the failure. | c1, c2 |
| F-016 | `tests/unit/test_memberships.py::test_membership_lapses_7_days_after_failed_renewal` | b | GRACE_DAYS is 7, the membership moves to grace and grace_ends_at is the failure plus 7 days; no code moves a membership from grace to lapsed | A failed renewal gives a membership a grace period that ends 7 days after the failure. | c3-c6 |
| F-017 | `tests/e2e/test_checkin.py::test_checkin_at_full_station_refused` | a | a check-in at a full station with the flag off gets 409 station_full | - | - |
| F-018 | `tests/e2e/test_checkin.py::test_checkin_at_full_station_allowed_with_overflow_parking` | a | a check-in at a full station with the flag on gets 200 | - | - |
| F-019 | `tests/e2e/test_checkout.py::test_third_checkout_refused` | a | the first two check-outs get 201 and the third gets 409 checkout_limit_reached | - | - |
| F-020 | `maintenanceSweep > locks a bike with 3 fault reports in 7 days and opens a ticket` | c | a bike with 3 reports inside the window is locked and close-lost is called; no ticket is checked and neither boundary is tested | add: a ticket of kind maintenance exists for bike-1 after the sweep (needs listTickets() exported from dispatch/src/db/maintenanceTickets.ts, now in PLAN); a bike with 2 reports inside the window is not locked; a bike with 3 reports, one of them 7 days and 1 minute old, is not locked | c1-c6 |
| F-021 | `nightlyRebalance > orders a rebalance for a station under 20% or over 90% full` | c | stations at 0.1 and 0.95 get orders and one at 0.5 does not | add: stations at exactly 0.2 and exactly 0.9 get no order (the expected station ids and the order count stay unchanged) | c1-c6 (history/c5 overlay of nightlyRebalance.ts and final) |
| F-022 | `stormPause > pauses rebalancing while the latest Skyglass severity is 3 or more` | c | a fresh severity-3 reading pauses and a fresh severity-2 reading does not; only one reading exists at a time | add: with a fresh severity-4 reading followed by a newer fresh severity-1 reading, isStormPaused is false and one plan is returned (proves 'latest') | c6 |
| F-023 | `tests/unit/test_tollbooth_client.py::test_capture_retries_three_times_then_fails` | c | a capture that keeps getting 503 makes MAX_RETRIES + 1 calls with BACKOFF_SECONDS sleeps and raises TollboothPaymentFailed; neither constant is pinned, and no code marks a payment row failed | add: calls == 4 and sleeps == [0.5, 1, 2]; the statement's tail is also narrowed to 'before the capture fails' (applied) | c1-c6 |
| F-049 | `tests/unit/test_flags.py::test_dynamic_pricing_off_by_default` | a | FLAGS['dynamic_pricing'] is False | - | - |
| F-050 | `tests/e2e/test_close_ride.py::test_close_ride_publishes_ride_completed` | a | a check-in publishes ride.completed on ride.events with the ride's id | none; flaky at c6 by plan (truth/planted-runs.yaml) | c1-c5 conclusive, c6 flaky |
| F-051 | `tests/e2e/test_checkin.py::test_checkin_full_station_returns_409` | a | the 409 body is exactly {error: station_full} | - | - |
| F-052 | `tests/e2e/test_station_status.py::test_station_status_reports_fill_ratio` | a | the status body is exactly station_id, available_bikes 3, empty_docks 1, fill_ratio 0.75 | - | - |
| F-053 | `rideEvents > counts ride.completed toward the return station's demand` | a | two ride.completed events for station-9 give it a demand of 2 | - | - |
