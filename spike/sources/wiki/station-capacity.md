---
id: wiki/station-capacity
title: Station capacity and overflow parking
version: 3
lastmodified: '2026-03-01T16:20:00-05:00'
author: priya.lund
space: GW
---

# Station capacity and overflow parking

What happens when a rider rolls up to a station with every dock full — the default behavior, and the flag that changes it for busy locations.

## Full Station

By default, if the overflow_parking flag is off for a station, a check-in there gets refused the moment every dock is full. The rider has to find somewhere else to leave the bike; dockyard won't let them squeeze it in.

## Overflow

Flip overflow_parking on for a station and that changes — a bike can be checked in even with every regular dock already taken. We use this at a handful of high-traffic spots where turning riders away causes more complaints than a slightly overcrowded station does.

## Error

When a check-in gets refused for this reason, the app gets back an HTTP 409 with the error code station_full — that's the exact signal the rider app looks for to show the "station full, try nearby" message instead of a generic failure.

## When to turn overflow on for a station

Ping me if a station is getting repeated full-station complaints — I'd rather look at the numbers before flipping the flag than have someone guess at it. It's a per-station setting, not global.

## Related pages

Dockyard API has the endpoint behind this. Check-out rules covers the equivalent limits on the way out.
