---
id: wiki/runbook-maintenance-sweep
title: 'Runbook: maintenance sweep'
version: 2
lastmodified: '2026-03-25T11:40:00-04:00'
author: tobin.achebe
space: GW
---

# Runbook: maintenance sweep

What the hourly maintenance sweep actually does, for anyone in fleet or ops who needs to explain a locked bike to a confused mechanic.

## Threshold

A bike gets pulled from service automatically once it picks up 3 fault reports inside a 7-day window. When that happens the sweep locks the bike so it can't be checked out again and opens a maintenance ticket in the same pass — nobody has to notice the pattern and act on it manually.

## Lost Rides

On every single run, the sweep also asks farebox to close out any rides that have gone stale, hitting farebox's internal close-lost endpoint. That's a separate concern from fault reports — it's cleanup for rides that never got closed properly, not a maintenance signal on the bike itself.

## Returning Bikes

Getting a bike back into service after it's been locked is two steps, in order: a mechanic closes out the maintenance ticket first, then goes into dockyard and unlocks the bike itself. Skipping the ticket step and just unlocking the bike from the admin panel leaves a stale open ticket sitting around, which throws off the fault-report count if the bike gets flagged again later.

## Related pages

Dispatch scheduled jobs has the schedule this sweep runs on alongside the other two jobs. Glossary defines what counts as a fault report in the first place.
