---
id: wiki/dynamic-pricing
title: Dynamic pricing
version: 2
lastmodified: '2026-04-15T13:00:00-04:00'
author: kasia.brandt
space: GW
---

# Dynamic pricing

Surge pricing, Gearwell-style — built and behind a flag, not yet something riders see in production. This page is mostly for whoever eventually turns it on.

## Status

The dynamic_pricing flag ships off by default. Nobody sees a surged rate right now unless the flag gets explicitly flipped on for a rollout.

## Surge

When the flag is on and the latest severity reading is 2 or higher, every per-minute rate gets multiplied by 1.25 for the duration of that reading. It's a straight multiplier on top of whatever the rider's normal per-minute rate already is — member or casual, the surge applies the same way to both.

## Weather Source

The severity number that drives this comes from the weather_readings table, which dispatch owns and populates from Skyglass. farebox just reads the latest row from it — it doesn't call Skyglass directly or keep its own copy of severity anywhere.

## Rolling this out

Whoever flips this on should coordinate with support first — a rider seeing a higher-than-usual per-minute rate with zero warning is exactly the kind of thing that generates confused tickets.

## Related pages

Storm pause is a different rule that also reads from weather_readings, for rebalancing rather than pricing. Feature flags has the general mechanics of how this flag gets read and cached.
