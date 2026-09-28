---
id: wiki/alerts-dispatch
title: Dispatch alerts
version: 2
lastmodified: '2026-04-29T16:05:00-04:00'
author: ren.okafor
space: GW
---

# Dispatch alerts

The two alerts ops actually gets paged or pinged for. Different severities, different response expected.

## Weather

A weather-poll failure on its own doesn't trigger anything — Skyglass has the odd bad response and the job just tries again next cycle. It's four failures back to back that raises a warning for the team. That's a nudge to go look, not a page — check dispatch's connection to Skyglass before it turns into something worse.

## Job Failures

A failed nightly rebalance is treated more seriously — that one pages the ops on-call engineer directly, no warning tier in between. Missing a night of rebalancing has real next-morning consequences, so this doesn't wait for a pattern to form before someone gets woken up.

## Why these two are different

A stalled weather poll degrades gracefully — storm pause just stops trusting old readings rather than doing something dangerous. A missed rebalance has no equivalent fallback, which is why it gets the louder alert.

## Related pages

Runbook: weather poll and Runbook: nightly rebalance both have the response steps for whichever one paged you. On-call handbook has the actual rotation and escalation path.
