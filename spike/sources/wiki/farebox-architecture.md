---
id: wiki/farebox-architecture
title: Farebox architecture
version: 4
lastmodified: '2026-03-20T14:15:00-04:00'
author: mara.voss
space: GW
---

# Farebox architecture

I'm not an engineer, but I get asked "how does farebox actually connect to the other two services" often enough that I put together this summary with help from the team. Read Farebox API if you want the endpoint-level detail instead.

## Close Ride

dockyard is the one that knows the moment a ride physically ends, so it's the one that calls us — specifically hitting our internal close endpoint for that ride's id — and farebox takes it from there, working out the price and marking the ride closed on our side.

## Flags Cache

Both farebox and dockyard keep a local copy of the flags table rather than hitting the database on every request, and that copy is refreshed every 60 seconds. So if you flip a flag and it doesn't seem to take effect instantly everywhere, that's expected — give it up to a minute.

## Weather Readings

farebox doesn't own any weather data itself. When it needs the current severity for surge pricing, it reads straight out of the weather_readings table that dispatch owns and keeps updated — farebox is just borrowing a row, not maintaining its own copy of the weather.

## Related pages

Farebox API has the endpoint reference this page summarizes. Dynamic pricing covers what actually happens with that severity reading once farebox has it.
