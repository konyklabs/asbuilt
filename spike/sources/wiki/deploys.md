---
id: wiki/deploys
title: Deploying Gearwell
version: 5
lastmodified: '2026-05-06T10:10:00-04:00'
author: lev.anand
space: GW
---

# Deploying Gearwell

Our deploy calendar and what to do when a deploy goes wrong. Read the windows section before you schedule anything for late in the week.

## Windows

Deploys are fine any time Monday through Thursday. Friday is more restricted — anything has to land before 12:00, and nothing goes out after that. The idea is simple: if something breaks, you want people around to fix it, not a fresh incident starting right as everyone logs off for the weekend.

## Rollback

If a deploy turns out to be bad, the fix is to redeploy the previous release rather than trying to patch forward under pressure. That's a direct consequence of how migrations work here — they only ever move forward, so there's no matching "undo" migration to run, and rolling the release back is the only clean path.

## Before you deploy

Check the current on-call rotation and make sure someone's actually watching before a deploy goes out, especially anywhere near the edge of a window. A deploy with nobody watching it is how a small issue turns into a multi-hour one.

## Related pages

On-call handbook has the rotation you should check before deploying. Database backups covers the other kind of recovery, for when a deploy problem also touches data.
