---
id: wiki/glossary
title: Glossary
version: 8
lastmodified: '2026-08-20T09:50:00-04:00'
author: dana.whitlock
space: GW
---

# Glossary

Terms that show up across tickets, docs and conversations without ever quite being defined anywhere. Add to this rather than re-explaining the same word in a new ticket every time.

## Dock

A dock is the smallest unit of station capacity — one single bike slot. A station's total capacity is just the count of docks it has; when people say a station is "full," they mean every dock at it currently has a bike in it.

## Grace Period

The window a membership sits in after a renewal fails, before it actually lapses. Right now that's 7 days — long enough for a rider to notice and fix a card issue without immediately losing member pricing over it.

## Rebalance Order

The instruction dispatch generates telling a van to move bikes into or out of a specific station. An order always aims for the same target: enough bikes moved to bring that station to 50% full, no more, no less.

## Fault Report

What gets created when a rider flags a bike as having a problem. Mechanically it's just a maintenance_tickets row with its kind set to fault_report — the same table that holds actual maintenance tickets, just a different kind value distinguishing a rider complaint from a ticket a mechanic opened directly.

## Related pages

Membership lifecycle has the full grace-period state machine. Rebalancing explains when a rebalance order actually gets triggered in the first place.
