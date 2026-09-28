---
id: wiki/runbook-nightly-rebalance
title: 'Runbook: nightly rebalance'
version: 5
lastmodified: '2026-05-20T08:50:00-04:00'
author: ren.okafor
space: GW
---

# Runbook: nightly rebalance

On-call runbook for the nightly rebalance job. If you got paged about this job, start here, not in the code.

## Schedule

The job kicks off at 02:00. If you're checking whether it ran, that's the time to look for in the dispatch logs.

## Weather

Nothing about the weather changes whether this job runs — it fires on schedule regardless of what's happening outside, rain or shine. Don't build any assumption into a downstream script that this job might sit out a rough night; it won't.

## Rerun

If the job fails — check dispatch's error logs for the stack trace first — re-run it by hand, and get it done before 06:00. Past that point vans are already rolling and a late rebalance plan just creates conflicting instructions for drivers already on the road.

## Escalation

Can't get it to rerun cleanly? Page the ops on-call rotation rather than sitting on it — a missed rebalance means stations stay lopsided for a full day, which compounds fast on a busy commute morning.

## Related pages

Dispatch scheduled jobs has the full list of what runs and when. Rebalancing has the logic behind what the job actually decides to move.
