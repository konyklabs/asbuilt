---
id: wiki/farebox-api
title: Farebox API
version: 4
lastmodified: '2026-09-08T13:35:00-04:00'
author: kasia.brandt
space: GW
---

# Farebox API

The two farebox endpoints other services actually call, plus the rider-facing refund endpoint's error shape. Internal endpoints live under /internal — that prefix is how you can tell them apart from rider-facing ones at a glance.

## Close Ride

dockyard hits POST /internal/rides/{id}/close the moment a bike gets docked, and that single call is what prices the ride and closes it out on our side. dockyard never computes a fare itself — it just tells us a ride ended and waits for farebox to say what it costs.

## Refunds

POST /refunds is rider-facing. If someone tries to request a refund on a ride that ended more than 14 days ago, it comes back HTTP 422 with refund_window_expired rather than a generic validation error, so the client can show something specific instead of "something went wrong."

## A note on internal endpoints

Nothing under /internal has rider-token auth on it — it's service-to-service only, gated at the network layer. Don't ever wire the rider app up to one of these directly, even for a quick fix.

## Related pages

Ride events covers what farebox publishes once a ride is closed. Refunds process has the policy this endpoint enforces.
