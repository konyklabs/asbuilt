---
id: wiki/dispatch-jobs
title: Dispatch scheduled jobs
version: 3
lastmodified: '2026-09-05T14:25:00-04:00'
author: ren.okafor
space: GW
---

# Dispatch scheduled jobs

The three timers dispatch runs on its own, with no human triggering them. Each has its own runbook linked below; this page is just the index and the locking model they all share.

## Schedules

Nightly rebalance fires once a day at 03:00 America/New_York. Maintenance sweep runs every hour, right on the hour. Weather poll is the most frequent of the three, firing every 15 minutes around the clock. None of these windows overlap in a way that matters — they're independent timers, not a pipeline.

## Locking

Every one of these jobs takes out a database lock named after itself before doing any work, and releases it when it finishes. That's what stops two overlapping runs of the same job from double-processing — if a run is slow and the next scheduled trigger fires before it's done, the second one just finds the lock held and skips its turn rather than piling on.

## Where to look when something's wrong

Each job has its own runbook page with more detail than fits here — Runbook: nightly rebalance, Runbook: maintenance sweep, Runbook: weather poll. Start there before digging into dispatch's source directly.

## Related pages

Dispatch alerts covers what pages the on-call rotation when one of these jobs fails outright rather than just running slow.
