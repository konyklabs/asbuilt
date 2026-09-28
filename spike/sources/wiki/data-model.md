---
id: wiki/data-model
title: Data model
version: 6
lastmodified: '2026-02-18T09:30:00-05:00'
author: lev.anand
space: GW
---

# Data model

Notes on the schema that don't belong in any one service's own docs — the bits that span ownership boundaries or just need explaining once instead of three times.

## Rides

The rides table is owned by dockyard, and the column that holds where a ride ended up is called return_station_id — not "end station" or anything similar, despite what you might see it called informally in a conversation. If you're writing a query against this table, that's the column name to reach for.

## Money

farebox never stores a dollar amount as a decimal. Every money column — on payments, on invoice lines, wherever a charge shows up — is named amount_cents and holds an integer number of cents. It's a small thing but it avoids an entire category of rounding bug that decimal currency columns are prone to.

## Access

Each service connects to the database with its own user, and that user can only write to the tables it owns. dockyard can't touch a farebox row directly, dispatch can't touch a dockyard row directly — any cross-service read goes through an API or a queue instead.

## Related pages

Gearwell platform overview has the bigger picture on why the services are split this way. Farebox architecture has more on how farebox specifically reads data it doesn't own, like weather readings.
