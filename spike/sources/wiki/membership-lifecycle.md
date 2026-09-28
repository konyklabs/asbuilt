---
id: wiki/membership-lifecycle
title: Membership lifecycle
version: 6
lastmodified: '2026-04-10T13:45:00-04:00'
author: kasia.brandt
space: GW
---

# Membership lifecycle

The state machine behind a membership, from the fares side. This is the page to check when a support ticket asks "why is this rider being charged the wrong rate" — nine times out of ten the answer is here.

## Statuses

A membership is always in exactly one of three states: active, grace, or lapsed. There's no "paused" or "suspended" — if a rider wants to stop riding for a while, they just don't ride, and the membership sits in active until either they cancel it or a renewal fails.

## Renewal Failures

Tollbooth Pay tells us about a failed renewal through a webhook, and that's the only way a membership moves out of active — there's no polling job that checks card status on its own. The webhook handler flips the row to grace and stamps a grace_ends_at timestamp on it, which is what everything downstream keys off.

## Pricing

Status drives pricing directly: grace still gets charged the member rate, lapsed gets charged the casual rate. That surprises people, but it's deliberate — a card that failed once shouldn't instantly turn someone into a casual rider mid-cycle, they get a window to fix it first without losing member pricing.

## Grace

That window is 7 days from the failed renewal before the membership actually lapses. If the card gets fixed and a renewal goes through inside that window, the membership goes straight back to active; if not, it lapses automatically once the window closes.

## Related pages

Refunds auto-approval and Tollbooth Pay integration cover the payment side of this. Support playbook has the script for what to tell a rider whose card just failed.
