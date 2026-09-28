---
id: doc/q3-ops-review
title: 'Q3 operations review'
headRevisionId: '0Ya2Wr03'
modifiedTime: '2026-09-15T11:30:00-04:00'
owner: tobin.achebe
mimeType: application/vnd.google-apps.document
---

# Q3 operations review

Notes from the quarterly ops review, covering alerting and the incidents worth calling out from the last few months. Shared with fares and fleet leads as well as ops, since a couple of the items touch all three teams.

**Attendees:** Tobin Achebe, Ren Okafor, Mara Voss, Priya Lund

## Paging

We spent some time on the fares paging threshold this quarter: a payment failure rate above 5% sustained over a 10-minute window pages the fares on-call engineer. The group agreed that threshold is still catching real issues without over-paging on noise, so no change proposed here.

## Incidents

The incident worth a proper mention this quarter was the weather-poll outage on 2026-08-12, which left the poll down for 6 hours after a Skyglass API key rotation went out without a matching update to dispatch's configuration. The group walked through the detection gap discussed in that incident's own write-up rather than repeating it here in full.

## Other discussion

General sentiment was that alerting across the three services is in reasonable shape, though a couple of people flagged that on-call handoff notes have been inconsistent quarter to quarter — worth a lighter-weight template so nothing important gets dropped between rotations.

Mara also raised that fares has been getting occasional questions from finance about how payment failures reconcile against captured totals; nothing urgent, but worth a short doc pass at some point so it stops being a recurring one-off conversation.

## Next quarter

The plan for next quarter's review is to bring a short written summary in advance instead of reconstructing the quarter from memory in the room — that should make the incidents section especially easier to keep tight and consistent between reviews.

## Action items

- Ren: draft a lighter handoff-notes template for the on-call rotation.
- Priya: follow up with fleet on whether any dockyard-side alerting gaps came up this quarter.
- Tobin: schedule a follow-up check-in on the weather-poll incident's action items before next quarter's review.

## Related pages

Incident: weather poll outage, 2026-08-12 has the full write-up. Farebox alerts and Dispatch alerts cover the paging rules discussed here in more day-to-day detail.
