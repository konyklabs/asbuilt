---
id: wiki/dockyard-api
title: Dockyard API
version: 5
lastmodified: '2026-02-02T11:10:00-05:00'
author: sami.haddad
space: GW
---

# Dockyard API

Endpoint reference for the three calls that get hit most from other services and from support tooling. Not a full API reference — just the ones people actually ask me about.

## Checkin

POST /rides/{id}/checkin is what closes out a ride at the dock. If the target station is full, it comes back with HTTP 409 and the error code station_full instead of silently failing or queuing the request — that's the signal to show the rider a "station full" message rather than a generic error screen.

## Station Status

GET /stations/{id}/status is the read side — it returns how many bikes are sitting at a station right now, how many empty docks are left, and a fill ratio you can use directly for a progress-bar style display without doing the math client-side.

## Checkout

POST /rides/checkout is the other direction. If the rider already has 2 bikes checked out to their account, a third attempt comes back HTTP 409 with checkout_limit_reached rather than succeeding — the limit is enforced here, not just documented somewhere.

## Auth

All three of these sit behind the same rider-token auth as the rest of the API — nothing special here, just flagging it since people sometimes assume internal-sounding endpoints skip auth. They don't.

## Related pages

Station capacity has the full context for the checkin behavior. Check-out rules covers the checkout limit from the rider-facing side.
