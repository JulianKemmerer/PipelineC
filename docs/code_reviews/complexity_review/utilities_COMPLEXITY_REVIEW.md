# utilities complexity review

Small dependency-light helpers shared by compiler modules. This file has no dedicated design document and does not need a broad architectural rewrite.

Source: [utilities.py](../../../src/utilities.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 150 | 98 | 10 | 0 | 9 |

Highest-scoring functions: `GET_VERSION_STR` (71–102, CCN 9); `_GIT` (51–65, CCN 3); `GET_TOOL_PATH` (15–19, CCN 2).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Process execution** — `GET_SHELL_CMD_OUTPUT` (109 onward). A shell string, captured stdout/stderr and one generic exception serve every tool. There is no explicit timeout/cancellation/result schema, and successful stderr is discarded. Generated shell scripts can mask an earlier failing command if the last command succeeds.
2. **Identity helpers** — `GET_VERSION_STR` (71–102), repository/path caches. Process-wide memoization is reasonable for a CLI banner but should not be mistaken for a build-content fingerprint. The version string intentionally ignores untracked files.
3. **Nondeterministic set conversion** — `FIND_REGEX_MATCHES` returns a list made from a set. If a caller emits or hashes that order, results can vary across Python hash seeds; this is a conditional risk, not a demonstrated output change.

## Duplication and simplification

Keep these helpers dependency-free. Add a small subprocess runner accepting argv, cwd and explicit timeout, returning exit status plus both streams; keep shell execution as an explicit choice for real scripts. The synthesis/simulation runner should own policy and logging.

Preserve deterministic discovery order or sort matches where ordering has no semantic meaning. Do not adopt a large utility framework to replace straightforward path and integer-width helpers.

## Validation

No new helper defect was reproduced. Check failed subprocesses preserve useful diagnostics, spaced paths survive argv execution, cancellation cleans up children, and deterministic match order is defined. Existing utility tests are the appropriate starting point.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

