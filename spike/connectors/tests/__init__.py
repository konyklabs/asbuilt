"""The test connector (asbuilt#8): pytest end-to-end/unit tests and Vitest
tests as a knowledge source (D-013's "Tests as a source", the killer
feature). Static half: `collect.py` (AST skeletons, no test process run)
and two extractors over a skeleton — `extract_rules.py` (deterministic
templates) and `extract_model.py` (structured output through
`bench/llm.py`). Dynamic half: `evidence.py` (outcomes per test id per
commit, from pytest-json-report/reportlog/JUnit XML/Vitest JSON) and
`lift.py` (D-013's provenance-tier rule, combining a skeleton with its
evidence). `__main__.py` is the CLI that ties them together into
`build/connector/tests-<step>.json`."""
