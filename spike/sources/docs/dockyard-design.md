---
id: doc/dockyard-design
title: 'Dockyard design'
headRevisionId: '7Hc2Xr31'
modifiedTime: '2025-11-03T14:00:00-05:00'
owner: priya.lund
mimeType: application/vnd.google-apps.document
---

# Dockyard design

Original design doc for dockyard, written before the service existed. Kept here mostly as a historical reference for the reasoning behind the shape of the service — check the wiki for anything that needs to reflect what actually shipped.

## Goals

Give the fleet team a single service responsible for the physical side of the bike-share system: where a bike is, whether a station can accept another one, and what a rider is allowed to do with the bikes checked out to them. Everything here is about state and rules, not about money — pricing was always meant to live somewhere else.

## Non-goals

This service was never meant to know anything about pricing, billing, or membership status. It also isn't meant to own scheduling or rebalancing logic — those belong to a separate service that reasons about the fleet as a whole rather than one station or one ride at a time.

## Capacity

A station has a fixed number of docks. Once every dock is occupied, a check-in attempt is refused outright as long as overflow_parking is off for that station — dockyard won't let a bike squeeze in past that hard limit unless the flag says otherwise.

## Checkout

A rider account is limited to 2 bikes checked out at once. A third check-out attempt while two are already outstanding gets refused rather than silently allowed — the intent is to stop one account from tying up an unreasonable share of the fleet at once.

## Rides Table

The table that tracks an open or closed ride stores where the bike ends up in a column named end_station — that's the field to query if you need to know the destination of a completed ride.

## Events

When a bike gets checked in, dockyard is the one that publishes the ride.completed event, since it's the service that actually observes the bike arriving at a dock.

## Design

Every write dockyard makes goes through its own database user, scoped only to the tables listed above — no other service reaches in directly. All state changes that matter to another service (a ride ending, a bike coming off the road) go out as an event rather than a shared table read, which keeps the boundary clean even as the schema evolves.

## Open questions at the time of writing

Whether overflow_parking should be a per-station setting or a global one was still being debated when this was written — check the current wiki page rather than assuming either answer from this doc.
