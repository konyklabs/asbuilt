---
id: wiki/checkout-rules
title: Check-out rules
version: 2
lastmodified: '2025-12-15T14:00:00-05:00'
author: sami.haddad
space: GW
---

# Check-out rules

The gate dockyard applies before it lets a bike leave a station. Two rules, both enforced server-side, neither one skippable from the app.

## Locked Bikes

A bike sitting in status locked simply cannot be checked out — the request fails before anything else about the rider is even considered. Locked usually means a mechanic pulled it for a maintenance issue, so this isn't a bug when it happens, it's the system doing exactly what it's supposed to.

## Limit

A rider can have up to 3 bikes checked out to their account at once. Try to take a fourth and dockyard turns it down, regardless of how many docks are open at the station in front of them.

## If a rider says the app is wrong

Check the account's open rides first — sometimes a rider genuinely forgot they still have a bike out from days ago, and that's eating into their limit without them realizing it. If the account is clean and they're still blocked, that's a dockyard bug, not a rule working as intended.

## Related pages

Dockyard API has the actual endpoint and error codes behind this. Station capacity covers the check-in side of the equation.
