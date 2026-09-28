---
id: wiki/database-backups
title: Database backups
version: 2
lastmodified: '2026-02-05T17:00:00-05:00'
author: lev.anand
space: GW
---

# Database backups

Where our safety net comes from, for anyone who needs to know without digging through the infrastructure config.

## Schedule

A snapshot of the shared database gets taken every night at 01:00. It's fully automated — nobody has to kick it off, and nobody gets notified unless it fails.

## Retention

We hold onto 14 days of these snapshots before older ones roll off. That's enough to recover from most "someone ran a bad migration" scenarios, but it's not a long-term archive — if you need something from further back than that, snapshots aren't going to have it.

## Restoring from one

This isn't self-service — if you think you need a restore, page whoever's on platform on-call rather than trying to do it yourself. Restoring the wrong snapshot, or restoring over live data by mistake, is a much worse day than whatever prompted the request in the first place.

## Related pages

Data retention policy is the formal write-up of retention across the whole platform, not just backups. Deploying Gearwell covers rollback, which is a different recovery path from restoring a snapshot.
