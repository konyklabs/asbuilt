---
id: wiki/incident-2026-08-12-weather-poll
title: 'Incident: weather poll outage, 2026-08-12'
version: 1
lastmodified: '2026-08-14T11:00:00-04:00'
author: ren.okafor
space: GW
---

# Incident: weather poll outage, 2026-08-12

Write-up for the weather-poll outage on 2026-08-12, while it's still fresh. Filing this here rather than just in the incident channel so it's findable later.

## Summary

The weather poll was down for 6 hours on 2026-08-12. Root cause was a Skyglass API key rotation that went out without a matching update to dispatch's own configuration — the old key simply stopped working the moment the rotation completed on Skyglass's side, and every poll call started failing from that point until someone caught it and pushed the new key through to dispatch.

## What we're changing

Any future key rotation on an integration like this needs a checklist item to update the consuming service's config in the same window, not as a follow-up task. We got lucky that this only affected rebalancing decisions rather than pricing.

## Detection gap

Nobody noticed for longer than they should have — the consecutive-failure alert did eventually fire, but by then the outage had already been running a while. Worth revisiting whether that alert should trigger sooner.

## Related pages

Runbook: weather poll has the response steps for this exact failure mode. Skyglass weather integration has the endpoint and config details involved here.
