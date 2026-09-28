---
id: doc/data-retention-policy
title: 'Data retention policy'
headRevisionId: '5Wb7Nr06'
modifiedTime: '2026-06-15T15:00:00-04:00'
owner: lev.anand
mimeType: application/vnd.google-apps.document
---

# Data retention policy

Platform-wide policy on how long different categories of data are kept, and who's responsible for enforcing each category. This is the policy doc; day-to-day mechanics for any one category live on that category's own wiki page.

## Purpose

Riders and internal teams both benefit from a clear, written answer to "how long do you keep this," rather than an ad-hoc answer depending on who's asked. This document exists so that answer is consistent and doesn't quietly drift service by service.

## Scope

This policy covers backups of the shared database, along with any other data category that gets its own row here as it's added. It doesn't cover data a rider explicitly deletes through their account settings — that's handled by a separate, faster deletion path outside the scope of this policy.

## Backups

Snapshots of the shared database are retained for 30 days before they're purged. That window is meant to cover the realistic range of "when might someone notice something needs restoring," from an immediate bad deploy to a slower-burn data issue that takes a few weeks to surface.

## Exceptions

Any deviation from a retention window listed here needs sign-off from platform, not just from whichever team wants the exception. Document the reason and the new window in this doc directly rather than letting an exception live only in someone's memory or a chat thread.

## Review cadence

This policy gets revisited whenever a new data category is added to the platform, and otherwise on a regular cycle even if nothing obviously needs to change — retention windows have a way of becoming outdated quietly if nobody's looking at them.

## Ownership

Platform owns this document and is the team to approach with any proposed change, but every team is expected to know the retention window for data they generate. Don't assume ignorance of this policy is a valid excuse if a category you own turns out to be handled inconsistently with what's written here.

## Requesting a new category be added

If your team introduces a new kind of durable data that isn't already covered by an existing category here, open a request with platform rather than assuming a sensible default applies automatically. Until a category is written down in this document, treat its retention as undefined rather than guessing at what seems reasonable.

## Related pages

Database backups has the operational side of the backup schedule this policy governs. Deploying Gearwell covers a different kind of recovery — rolling back a bad release rather than restoring from a snapshot.
