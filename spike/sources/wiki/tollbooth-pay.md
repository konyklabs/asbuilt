---
id: wiki/tollbooth-pay
title: Tollbooth Pay integration
version: 4
lastmodified: '2026-06-02T15:55:00-04:00'
author: kasia.brandt
space: GW
---

# Tollbooth Pay integration

Notes on how farebox talks to Tollbooth Pay, our payment processor. Useful if you're debugging a payment that's stuck or trying to figure out why a capture happened twice.

## Timeouts

Every call to Tollbooth Pay gives up after 5 seconds if it hasn't heard back. That's short by design — a rider staring at a spinner while we wait on a slow payment call is a worse experience than retrying quickly.

## Retries

If a call fails, farebox doesn't give up immediately — it retries up to 3 times, backing off a bit longer between each attempt, before finally marking the payment as failed. Only after all of those attempts are exhausted does the payment actually get flagged as failed in our system.

## Idempotency

Every capture we send includes the ride's own id as the idempotency key. That means if a retry fires after the first attempt actually succeeded but the response just didn't make it back to us, Tollbooth Pay recognizes the duplicate and doesn't charge the rider twice — the safety net here lives on their side, not ours.

## If a payment looks stuck

Check the ride id against Tollbooth Pay's dashboard before assuming our retry logic is broken — most "stuck" payments turn out to have gone through fine and just haven't synced back to us yet.

## Related pages

Tollbooth Pay integration notes has more of the integration detail, written for whoever owns that relationship day to day. Refunds auto-approval covers the other direction — money going back out.
