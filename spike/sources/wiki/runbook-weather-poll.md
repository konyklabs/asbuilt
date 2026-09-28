---
id: wiki/runbook-weather-poll
title: 'Runbook: weather poll'
version: 2
lastmodified: '2026-09-10T09:05:00-04:00'
author: ren.okafor
space: GW
---

# Runbook: weather poll

Runbook for the job that keeps our storm data fresh. Short page — this job either works or it doesn't, there isn't much middle ground.

## Stale Readings

If the newest Skyglass reading on file is older than 60 minutes, the storm pause logic stops trusting it and won't pause rebalancing on the strength of a reading that old. So a dead weather poll doesn't just mean stale data sitting around — it quietly turns off storm protection for rebalancing too, which is the scarier failure mode here.

## Alert

Four failed polls in a row — not four total, four consecutive — trips a warning alert to the ops team. One or two bad polls in isolation is normal noise from a flaky upstream call and won't page anyone; it's the unbroken streak of four that means something's actually wrong.

## What to check first

Confirm dispatch can still reach Skyglass at all before assuming the job itself is broken — a bad API key or a network change on our side looks identical to Skyglass being down from where this job sits.

## Related pages

Storm pause explains what the readings this job collects are used for. Incident: weather poll outage, 2026-08-12 is a real example of this job going dark and what caused it.
