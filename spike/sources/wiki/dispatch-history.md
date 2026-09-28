---
id: wiki/dispatch-history
title: Dispatch service history
version: 1
lastmodified: '2026-01-15T16:00:00-05:00'
author: tobin.achebe
space: GW
---

# Dispatch service history

A bit of background for anyone confused about why dispatch looks different from the other two services under the hood. Short page, but it answers a question I get a lot from new engineers.

## Rewrite

dispatch wasn't always TypeScript — it started life in Python like dockyard and farebox, and got rewritten in a 2025 rewrite that swapped the language entirely while keeping the same job. If you're reading old design notes or an old ticket that references Python types for dispatch, that's why — they predate the rewrite.

## Why it happened

The scheduling and job-locking logic dispatch runs benefited from a different set of libraries than what the Python ecosystem offered at the time, and the team decided a clean rewrite was less risky than trying to bolt those patterns on. It wasn't a reaction to any incident, just a considered call by the ops team.

## What survived the rewrite

The job names, the schedules, and the database schema dispatch owns all carried over unchanged — this was a language rewrite, not a redesign. Anything documented about what the jobs do is still accurate regardless of which version of the service you're looking at.

## Related pages

Gearwell platform overview has the current language and ownership for all three services. Dispatch scheduled jobs covers what the service actually runs today.
