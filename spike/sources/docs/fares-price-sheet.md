---
id: doc/fares-price-sheet
title: 'Fares price sheet'
headRevisionId: '1Qm4Vr12'
modifiedTime: '2026-03-05T10:30:00-05:00'
owner: mara.voss
mimeType: application/vnd.google-apps.document
---

# Fares price sheet

The canonical numbers for every fare-related charge in one place, meant for anyone outside fares who needs the current rates without digging through a wiki page per rule — support leads, the finance contact who reconciles Tollbooth Pay payouts, anyone building a pricing calculator for the marketing site.

## Member Rates

Members are billed $0.15 for each minute once their free window has run out. That's the only per-minute number that applies to a member account; nothing else stacks onto the base rate unless a separate rule (e-bike, surge) says otherwise.

## Casual Rates

A rider without a membership pays two things on every ride: a flat $2.00 to unlock the bike, and then $0.25 for every minute starting immediately, with no free window at all. The unlock charge is billed the instant the ride starts, before any minutes have accrued.

## Ebike

Riding an e-bike adds $0.10 to every billed minute whenever the ebike_surcharge flag is switched on for that ride. It layers on top of whichever base per-minute rate already applies, member or casual.

## Caps And Fees

Two ceiling numbers matter here. First, no single ride bills for more than $25.00 total, however long it runs. Second, a bike that never gets docked within 24 hours of check-out triggers a $100.00 lost-bike fee, charged on top of the capped ride total rather than instead of it.

## Rate table

| Charge | Amount |
|---|---|
| Member per-minute | $0.15 |
| Casual unlock | $2.00 |
| Casual per-minute | $0.25 |
| E-bike surcharge (per minute, flag on) | $0.10 |
| Single-ride cap | $25.00 |
| Lost-bike fee | $100.00 |

## Notes for finance

These are gross rider-facing numbers before any processor fee Tollbooth Pay takes off the top — reconcile against captured amounts, not against this sheet directly. Flag me if a payout doesn't tie back cleanly; it's usually a timing issue rather than a rate mismatch.
