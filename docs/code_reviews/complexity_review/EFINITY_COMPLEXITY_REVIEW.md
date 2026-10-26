# EFINITY complexity review

Efinix project generation and timing adapter; relevant to Python designs targeting this tool. See [SYN design](../SYN_DESIGN.md#3-the-backend-contract).

Source: [EFINITY.py](../../src/EFINITY.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 439 | 330 | 7 | 0 | 14 |

Highest-scoring functions: `__init__` (53–109, CCN 14); `__init__` (113–170, CCN 10); `SYN_AND_REPORT_TIMING_NEW` (205–439, CCN 8).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Joining clock summaries to paths** — `ParsedTimingReport.__init__` (53–109). Target and achieved frequencies are parsed in separate sections and joined by clock name before division. Missing rows or a renamed clock produces None/key failures; repeated paths overwrite endpoint provenance for a group.
2. **Path grammar** — `PathReport.__init__` (113–170). Section flags and exact token counts derive resources and endpoints. Unsupported lines can be silently omitted.
3. **Project/script emission** — `SYN_AND_REPORT_TIMING_NEW` (205–439). A large XML template, tool setup, map/PNR commands and log reuse share one routine. Multi-step shell success depends on each stage being checked, not only the final command.

## Duplication and simplification

Use common run preparation and validated report records. Parse clock summaries and paths independently, then perform an explicit checked join. Represent project options as data and render XML with escaping rather than embedding arbitrary paths in strings. Retain target-specific options; reduce repeated scaffolding, not documented device behavior.

## Validation

No new tool failure was reproduced. Test absent frequency rows, zero frequencies, repeated paths, malformed section headers and XML-special characters in paths. A script-level test should establish that map failure cannot be hidden by a later command or stale artifact.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

