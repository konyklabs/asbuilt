---
id: wiki/skyglass
title: Skyglass weather integration
version: 3
lastmodified: '2026-09-04T12:15:00-04:00'
author: ren.okafor
space: GW
---

# Skyglass weather integration

How dispatch pulls weather data from Skyglass, our storm-severity provider. Short page, since the whole integration is really just one call.

## Endpoint

dispatch hits GET /v2/severity, passing along the station's latitude and longitude so the reading is specific to that location rather than some regional average. The call gives up after 3 seconds if Skyglass hasn't responded — tight enough that a slow Skyglass doesn't back up the weather-poll job behind it.

## Scale

Severity comes back as a single number from 0 to 5 — 0 means clear, and 5 is their top tier, a severe storm warning. Everything else sits somewhere in between; there's no separate category system to learn, just where a reading falls on that one scale.

## If the API key needs rotating

Coordinate with whoever's rotating it — dispatch's config has to update in the same window or the poll job starts failing silently until someone notices. See the 2026-08-12 incident write-up for what that looks like when it goes wrong.

## Related pages

Storm pause is the rule that consumes these readings. Runbook: weather poll covers the job that calls this endpoint on a timer.
