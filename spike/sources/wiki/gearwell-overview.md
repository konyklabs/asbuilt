---
id: wiki/gearwell-overview
title: Gearwell platform overview
version: 7
lastmodified: '2026-01-20T09:40:00-05:00'
author: lev.anand
space: GW
---

# Gearwell platform overview

Gearwell is the back office behind the bike-share fleet: check-out and check-in, pricing and billing, and the scheduled jobs that keep bikes where riders actually need them. Three services split the work, one per team. If you're new here, this page is the map — everything else links off it.

## Services

The three services used to sit in separate repositories, one per team, which made any change that crossed a service boundary a coordination exercise across three separate reviews. They were folded into a single repository on 2026-01-12, and a pricing tweak that also needs a dispatch event can now ship as one change instead of three. dockyard (fleet) and farebox (fares) are both Python; dispatch (ops) is TypeScript, a holdover from before the monorepo move rather than a deliberate split.

## Data

The services share one database cluster but not write access to it. Each service connects with a database user of its own, and that user's grants are scoped to the tables it owns — farebox has no way to write to a dispatch table, and dispatch has none to a farebox one. Anything one service needs from another comes through an API call or a queued event, never a row it reached across and wrote itself. This is enforced at the database level, not just by convention, so a bug in one service can't silently corrupt another's data.

## Where to look next

Data model has the full table list and who owns each one. Feature flags explains how the three services read flags without hitting the database on every request. Dispatch scheduled jobs covers what runs on a timer and how the jobs avoid stepping on each other.

## Last reviewed

Reviewed at v7. Ping Lev if a service boundary described here looks out of date — this page tends to lag the codebase by a release or two.
