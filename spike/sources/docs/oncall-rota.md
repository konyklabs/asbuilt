---
id: doc/oncall-rota
title: 'On-call rota'
headRevisionId: '9Kd1Mr57'
modifiedTime: '2026-09-01T09:30:00-04:00'
owner: lev.anand
mimeType: application/vnd.google-apps.document
---

# On-call rota

The actual rotation and escalation reference, maintained separately from the wiki's general on-call handbook since this one changes more often and shouldn't need a wiki edit every time someone swaps a shift.

## Rotation

The rotation turns over on a weekly basis, with the outgoing and incoming engineers handing off on Monday at 10:00. Swaps between engineers are fine as long as both people update the calendar invite — don't just swap informally and leave the rota looking wrong for whoever checks it next.

## Escalation

If the nightly rebalance job fails outright, the page goes straight to whoever's on the ops on-call rotation — no warning tier first, no waiting for a pattern. That's the one alert on this rota's list that skips straight to a page rather than a softer notification.

## Rotation order

| Team | Typical cadence |
|---|---|
| Ops | Weekly |
| Fares | Weekly |
| Fleet | Weekly |

Order rotates between the three teams; check the shared calendar for who's actually up next rather than assuming it follows this table in a fixed sequence.

## Swapping a shift

Post in the on-call channel before swapping, not after — someone else may already be planning around the original assignment. Once both people confirm, update the calendar invite yourself; don't wait for whoever runs the rota to do it for you.

## Getting added to the rotation

New engineers don't go straight onto the rotation the moment they join — talk to your manager about when you're ready, and make sure you've shadowed at least one full shift before you're the one holding the pager solo. There's no fixed tenure requirement; it's a judgment call based on how comfortable you are with the runbooks by then.

## If the rota looks wrong

If you spot a gap, a double-booking, or an assignment that doesn't match the calendar, flag it in the on-call channel rather than quietly fixing it yourself — someone may have a reason for the current arrangement that isn't obvious from the doc alone.

## Related pages

On-call handbook has the general expectations for being on-call. Dispatch alerts and Farebox alerts cover the specific triggers behind pages you might get from this rotation.
