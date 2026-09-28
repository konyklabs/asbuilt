# Empty on purpose: pyproject.toml's `pythonpath = ["."]` is what puts the
# repo root on sys.path so `tests/test_pricing.py` can `import farebox`; this
# file just marks the root for pytest's own rootdir discovery.
