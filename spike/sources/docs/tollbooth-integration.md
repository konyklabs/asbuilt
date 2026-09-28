---
id: doc/tollbooth-integration
title: 'Tollbooth Pay integration notes'
headRevisionId: '6Gv5Ur22'
modifiedTime: '2025-12-10T14:30:00-05:00'
owner: kasia.brandt
mimeType: application/vnd.google-apps.document
---

# Tollbooth Pay integration notes

Deeper technical notes on the Tollbooth Pay integration than what fits on the wiki page — this is the doc to check before touching the payment client code itself.

## Retries

A failed call gets retried up to 3 times before the payment is finally marked failed — it's not an infinite retry loop, and it's not a single attempt either. Each retry waits a bit longer than the one before it rather than firing back-to-back immediately: the client waits 0.5 seconds before the first retry, 1 second before the second, and 2 seconds before the third, each gap roughly doubling the one before it so the three attempts spread out without stalling the caller for too long overall.

## Timeouts

Right now each outbound call to Tollbooth Pay is configured to wait 10 seconds before giving up. That's the client-side timeout, separate from whatever timeout Tollbooth Pay itself applies on their end.

## Idempotency

Every capture call includes the ride's own id as the idempotency key sent to Tollbooth Pay. That choice means a retried capture after a dropped response never results in a double charge — Tollbooth Pay recognizes the repeated key and returns the original result instead of processing it again.

## Settlement

Captured funds don't land in our account instantly — Tollbooth Pay settles two business days after the capture, so any reconciliation against our own records needs to account for that lag rather than expecting same-day totals to match.

## Webhooks

Tollbooth Pay pushes a webhook to farebox every time a membership renewal charge fails. That webhook is the only trigger for moving a membership into grace — there's no separate polling job on our side checking renewal status.

## A note on the timeout number

The client-side timeout above is what's currently configured; if you're debugging a slow capture, check the client config directly rather than trusting this doc blindly; configuration like this tends to get tuned occasionally without every doc getting a matching update the same day.

## Related pages

Tollbooth Pay integration has the same retry, timeout and idempotency behavior in wiki form, aimed at a broader audience. Refunds auto-approval covers money moving in the other direction.
