# JS Test Runner Report Shapes — Jest, Mocha, Playwright Test

Fetched 2026-09-28. Vitest 5 already covered elsewhere (assertionResults[] with ancestorTitles/title/status/duration).

## Jest

| Item | Value | Label | Source | Fetch date |
|---|---|---|---|---|
| Machine-readable report | `--json` + `--outputFile=<path>` CLI flags | verified | https://jestjs.io/docs/cli | 2026-09-28 |
| Reporter config | `reporters` array in config; built-ins: `default`, `github-actions`, `summary` — no built-in JUnit | verified | https://jestjs.io/docs/configuration#reporters-arraymodulename--modulename-options | 2026-09-28 |
| Title fields | per-test: `title` (leaf), `ancestorTitles[]` (describe chain), `fullName` (joined) | verified | https://jestjs.io/docs/configuration#testresultsprocessor-string ; https://github.com/jestjs/jest/blob/main/packages/jest-types/src/TestResult.ts | 2026-09-28 |
| Status values | 7-value union: `passed,failed,skipped,pending,todo,disabled,focused`; default jest-circus runner emits only `passed,failed,pending,todo` in practice | verified (union, primary source) / sourced (in-practice subset, third-party blog) | https://github.com/jestjs/jest/blob/main/packages/jest-types/src/TestResult.ts ; https://currents.dev/posts/test-status-translation-guide | 2026-09-28 |
| Duration | `duration` (ms, nullable) per assertion result | verified | https://github.com/jestjs/jest/blob/main/packages/jest-types/src/TestResult.ts | 2026-09-28 |
| Retries | single result per test; retry info folded into `retryMessages[]`/`retryReasons[]` on that one result, not separate attempts | verified | https://github.com/jestjs/jest/blob/main/packages/jest-types/src/TestResult.ts | 2026-09-28 |
| Run metadata (git/env) | no such field in the documented/typed schema | sourced (absence) | same two sources above | 2026-09-28 |
| JUnit | no built-in JUnit reporter; community `jest-junit` is the standard add-on (out of scope here — not Jest's own docs) | sourced | https://jestjs.io/docs/configuration#reporters-arraymodulename--modulename-options | 2026-09-28 |

## Mocha

| Item | Value | Label | Source | Fetch date |
|---|---|---|---|---|
| Machine-readable report | `--reporter json` (`-R json`) + `--reporter-option output=<path>` (alias `-O`/`--reporter-options`) | verified | https://mochajs.org/reporters/json/ ; https://mochajs.org/running/cli/ | 2026-09-28 |
| Report shape | top-level `{stats, tests[], pending[], failures[], passes[]}`; per test `{title, fullTitle, file, duration, currentRetry, speed, err}` | verified | https://raw.githubusercontent.com/mochajs/mocha/master/lib/reporters/json.js | 2026-09-28 |
| Title fields | `title` = leaf name, `fullTitle` = describe+it path (`Runnable.fullTitle()`) | verified (fields) / sourced (join semantics — well-known Mocha API behavior, not directly quoted from a docs page) | same as above | 2026-09-28 |
| Status values | no `status` string field; state = which bucket array a test lands in — effectively 3 states: passed/failed/pending | sourced | https://currents.dev/posts/test-status-translation-guide (corroborated by the json.js bucket structure) | 2026-09-28 |
| Retries | single object per test; `currentRetry` is a count, no per-attempt array | verified | https://raw.githubusercontent.com/mochajs/mocha/master/lib/reporters/json.js | 2026-09-28 |
| Run metadata (git/env) | none native in `stats` or per-test object | sourced (absence) | same source | 2026-09-28 |
| JUnit | ships built-in `xunit` reporter, docs call it "XUnit-compatible XML"; `--reporter-option output=<path>.xml` | verified | https://mochajs.org/reporters/xunit/ | 2026-09-28 |
| JUnit naming | `<testcase classname="test.parent.fullTitle()" name="test.title" file=... time=...>` — classname carries the describe path, name is the leaf; standard classname+name reconstruction works, but the leaf `name` alone repeats across suites | verified | https://raw.githubusercontent.com/mochajs/mocha/master/lib/reporters/xunit.js | 2026-09-28 |

## Playwright Test

| Item | Value | Label | Source | Fetch date |
|---|---|---|---|---|
| Machine-readable report | `--reporter=json`; output via `PLAYWRIGHT_JSON_OUTPUT_NAME`/`_DIR`/`_FILE` env vars or `outputFile` in reporter config | verified | https://playwright.dev/docs/test-reporters | 2026-09-28 |
| Report shape | `JSONReport{config,suites[],errors,stats}` → `JSONReportSuite{title,file,specs[],suites?}` → `JSONReportSpec{title,tests[]}` → `JSONReportTest{status:'skipped'\|'expected'\|'unexpected'\|'flaky', results[]}` | verified | https://cdn.jsdelivr.net/npm/playwright@1.56.1/types/testReporter.d.ts | 2026-09-28 |
| Title fields | no flat titlePath field in the JSON; path is reconstructed by walking nested `suites[].title` down to `specs[].title` | verified | same as above | 2026-09-28 |
| Attempt status values | `TestStatus = 'passed'\|'failed'\|'timedOut'\|'skipped'\|'interrupted'`, one per `JSONReportTestResult` | verified | same as above | 2026-09-28 |
| Duration | `duration` (ms) on `stats` and on each `JSONReportTestResult` | verified | same as above | 2026-09-28 |
| Retries | separate attempts: `JSONReportTest.results[]` holds one entry per attempt, each with its own `retry` index and its own `status`/`duration` | verified | same as above | 2026-09-28 |
| Run metadata (git/env) | `config` carries resolved project config (incl. an optional user-defined `metadata` field) but no automatic git-commit field; `stats` is counts/timing only | verified (absence) | same as above | 2026-09-28 |
| JUnit | ships built-in `junit` reporter; `--reporter=junit`, `PLAYWRIGHT_JUNIT_OUTPUT_NAME` etc. | verified | https://playwright.dev/docs/test-reporters | 2026-09-28 |
| JUnit naming | `<testcase name="test.titlePath().slice(3).join(' › ')" classname=suiteName>` — `name` already contains the full describe/it path joined by " › " | verified | https://raw.githubusercontent.com/microsoft/playwright/main/packages/playwright/src/reporters/junit.ts | 2026-09-28 |

## Summary — what a generic reader needs per runner

- **Jest**: read `testResults[].testResults[]`; use `ancestorTitles`+`title` (or `fullName`) for the path, `status`∈{passed,failed,pending,todo,…}, `duration`; retries live in `retryMessages`/`retryReasons` on the one result, not extra rows.
- **Mocha**: read `tests[]` (or the `passes`/`failures`/`pending` buckets) from the JSON reporter; `fullTitle` gives the path directly, no `status` field — infer from bucket; `currentRetry` is a count only, one row per test.
- **Playwright**: walk `suites[]` → `specs[]` for the path, then iterate `tests[].results[]` — each array entry is one real attempt with its own `status`/`duration`/`retry`, so retries are multiple rows by design.
- **JUnit path**: Mocha's `xunit` and Playwright's `junit` are both built-in and directly usable; Jest ships none and needs a third-party reporter (`jest-junit`, not covered here since it isn't Jest's own docs).
- **Native run metadata**: none of the three natively stamp git commit or CI environment into the report; that has to come from a custom reporter, a sidecar file, or (Playwright only) the optional user-defined `metadata` field in project config.
