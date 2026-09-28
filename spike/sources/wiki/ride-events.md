---
id: wiki/ride-events
title: The ride.events queue
version: 3
lastmodified: '2026-03-12T10:45:00-04:00'
author: kasia.brandt
space: GW
---

# The ride.events queue

How farebox and dispatch talk to each other without either one calling the other's API directly. If you're wiring up a new consumer, read the payload section before you write a line of code.

## Producers

farebox is the only thing that writes to this queue. Two events come out of it: a ride.completed message goes out the moment a ride is closed, and a ride.refunded message goes out separately whenever a refund actually gets paid — those are two different triggers, not the same event with a different status field.

## Consumers

dispatch is the one big reader here. It watches this queue under the consumer group dispatch-demand, and for every ride.completed event it sees, it credits that ride's return station with one more unit of demand — that's the raw signal that eventually feeds into deciding which stations need a rebalance.

## Payload

A ride.completed message carries six fields: ride_id, rider_id, bike_id, return_station_id, ended_at, and amount_cents. That's deliberately the minimum a consumer needs — if you find yourself needing something else off the ride, you're probably better off calling farebox's API than trying to get it added to this payload.

## Retention

Messages sit in the queue for 7 days before they age out. That's plenty for normal processing, but it does mean a consumer that's been down for over a week loses data rather than catching up on everything it missed — worth knowing if you're building something that reads from here.

## Related pages

Farebox API has the endpoint that triggers the ride.completed event. Rebalancing covers what dispatch actually does with the demand these events feed.
