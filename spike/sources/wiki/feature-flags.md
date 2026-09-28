---
id: wiki/feature-flags
title: Feature flags
version: 4
lastmodified: '2026-03-18T12:00:00-04:00'
author: lev.anand
space: GW
---

# Feature flags

How flags work mechanically across the three services. Not a list of what each flag does — see the flag's own page for that — just how the table is read and what happens when it's empty.

## Defaults

If a flag has no row in feature_flags at all, every service treats that as off rather than erroring or falling back to some other default. This matters when a new flag ships: until someone actually inserts the row, the code behind it is inert, which is the safest failure mode for something that changes pricing or access.

## Flags

Right now the table holds three flags: dynamic_pricing, ebike_surcharge, and overflow_parking. Each one gates a specific behavior in a specific service, and none of them affect each other — flipping one doesn't change how the others are read or evaluated.

## Adding a new flag

Insert the row, deploy the service that reads it, then flip it on when you're ready — in that order. Don't flip a flag on before the code that checks it has shipped, since older code just won't be looking for the row yet.

## Related pages

Refunds auto-approval and Dynamic pricing both document specific flags and their behavior. Gearwell platform overview has the bigger picture of how the three services are organized.
