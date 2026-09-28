---
id: wiki/alerts-farebox
title: Farebox alerts
version: 3
lastmodified: '2026-07-08T14:40:00-04:00'
author: mara.voss
space: GW
---

# Farebox alerts

Just the one alert on the fares side right now, but it's the one that actually wakes someone up, so it gets its own page instead of being buried in a bigger runbook.

## Payment Failures

If the payment failure rate climbs above 5% over a rolling 10-minute window, whoever's on the fares on-call rotation gets paged. That threshold is set high enough that a couple of unlucky declined cards in a row won't trigger it — it's meant to catch something systemic, like Tollbooth Pay itself having a bad day, not normal background noise.

## What it usually means

Nine times out of ten this is Tollbooth Pay having an issue on their end, not something broken in our own code — check their status page before assuming it's us. If it is us, the Tollbooth Pay client's retry and timeout behavior is the first place to look.

## If you're the one paged

Don't panic-revert a recent deploy before checking whether the failure rate is actually elevated or just noisy — pull up the dashboard first. A false alarm here is annoying but a bad revert under pressure is worse.

## Related pages

Tollbooth Pay integration has the retry and timeout details behind most payment failures. Dispatch alerts covers the equivalent page-worthy alerts on the ops side.
