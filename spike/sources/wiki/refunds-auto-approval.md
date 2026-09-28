---
id: wiki/refunds-auto-approval
title: Refund auto-approval
version: 1
lastmodified: '2026-09-02T10:30:00-04:00'
author: kasia.brandt
space: GW
---

# Refund auto-approval

New this quarter: small refunds no longer have to sit in the fares review queue. This page explains the rule and where it lives in the flag table, since I keep getting asked whether it's on by default.

## Rule

With refund_auto_approve switched on, any refund under $5.00 skips the manual review step entirely and gets approved the moment it's requested. Anything at or above that amount still goes through a fares agent exactly as before — this only shortens the path for the small stuff that used to clog the queue for no good reason.

## Flag

That flag lives alongside three others in the feature_flags table: dynamic_pricing, ebike_surcharge, overflow_parking, and refund_auto_approve itself. All four are read the same way by whichever service checks them, so there's nothing special about this one mechanically — it's just the newest row.

## Why this exists

Most sub-five-dollar refund requests were being approved anyway, just slowly, and the review step was mostly adding a delay rather than catching anything. This just removes the wait for the cases that were never really in question.

## Related pages

Feature flags has the mechanics of how flags are read and cached. Refunds process covers the manual path this flag shortcuts.
