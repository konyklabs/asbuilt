---
id: doc/dispatch-design
title: 'Dispatch design'
headRevisionId: '3Tz9Kr18'
modifiedTime: '2025-12-01T11:00:00-05:00'
owner: tobin.achebe
mimeType: application/vnd.google-apps.document
---

# Dispatch design

The original design doc for dispatch, written before any of it was built. Useful for the reasoning behind the service boundaries; treat the actual schedules and thresholds here as a starting point rather than gospel, since some of this predates what actually shipped.

## Goals

One service that looks at the whole fleet at once and decides what needs to move — which stations are too empty or too full, which bikes need pulling for maintenance, and what the weather is doing to either of those decisions. Nothing here is rider-facing; dispatch talks to dockyard and farebox, never directly to the rider app.

## Non-goals

Dispatch was never meant to own pricing or membership logic, and it wasn't meant to talk to riders directly either — anything a rider sees goes through dockyard or farebox, dispatch just feeds decisions into those systems. It also isn't meant to be the source of truth for where a bike physically is; dockyard owns that.

## Rebalance

A station qualifies for a rebalance order once it falls under 20% full or climbs over 90% full — those are the two trigger conditions, empty and overfull, both flagged the same way. When an order does go out, the target is the same regardless of which side triggered it: move enough bikes to bring the station to 50% full.

## Jobs

Two of the scheduled jobs are sketched out here with rough intervals: the maintenance sweep was planned to run every 30 minutes, and the weather poll was planned to run every 5 minutes. Those were the working assumptions at design time, before load testing settled on the actual production intervals.

## Design

Each job runs independently on its own timer and takes a lock scoped to itself before doing any work, so overlapping runs of the same job can't step on each other. Jobs don't call each other directly — anything one job needs from another's output goes through the shared database, read-only across the boundary.

## Open questions at the time of writing

Whether the rebalance trigger thresholds should be symmetric (same distance from the target in both directions) was still under discussion — don't assume the numbers above reflect the final call without checking current behavior.
