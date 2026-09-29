"""The extraction pipeline every benchmark arm shares (D-013, konyklabs/asbuilt#4).

Written once, against the write-side ``StoreInterface`` in ``store.py``:

- ``store.py``: the interface, the fact identity rule, the merge and episode
  rules, and ``MemoryStore`` (a pure-Python implementation for unit tests).
- ``embed.py``: the embedder every arm uses, named and pinned, with a
  deterministic fallback.
- ``resolve.py``: names to entity rows.
- ``history.py``: the built git repository as the test connector's timeline.
- ``sources.py``: every source document with its version and lastmodified.
- ``lift.py``: the test connector's tiers, candidates and supersessions,
  applied to a store.
- ``contradict.py``: contradiction candidates by claim join and, for prose,
  an NLI pre-filter then a model verdict.
- ``stale.py``: which documented facts are stale.

An arm supplies only its own store and its own document extraction.
"""
