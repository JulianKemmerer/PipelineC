# VIVADO complexity review

Vivado synthesis/report adapter. [SYN's backend contract](../../SYN_DESIGN.md#3-the-backend-contract) describes the base report and optional path/coverage data used by the Python compiler.

Source: [VIVADO.py](../../../src/VIVADO.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 1,215 | 821 | 17 | 4 | 34 |

Highest-scoring functions: `__init__` (338–496, CCN 34); `__init__` (72–227, CCN 23); `PARSE_UTILIZATION` (248–304, CCN 19).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Human-readable path parsing** — `PathReport.__init__` (338–496, CCN 34). Fixed headings, previous-line state, wrapped delay types, pin/cell names and requirement/slack conversion are intertwined. A format change can lose attribution or produce an incomplete object. Validate requirement and source period before division.
2. **Whole report parsing** — `ParsedTimingReport.__init__` (72–227). Timing loops, merged-register expansion and worst path groups are recovered from synthesis prose. Register renaming is not merely diagnostic: downstream blame depends on it.
3. **Optional structured evidence** — `PARSE_EXTRA_PATHS` (1150–1215), utilization and RAM parsing. Optional query failure, truncation and parsed counts must remain distinct from complete coverage. Tab-separated rows are already a better boundary than the base prose parser.
4. **Script generation/reuse** — synthesis helpers and final-top behavior. Requested reports, constraints, recipe identity and retained checkpoints must describe the same artifact; a characterization log cannot substitute for a final implementation.

## Duplication and simplification

Use the common synthesis runner proposed in the SYN review. Extend machine-readable Tcl output for the base timing record where practical; keep vendor prose as diagnostics. Parse into one normalized report type and require finite positive periods, valid delay fields and explicit coverage. Preserve raw and normalized endpoint names so lossy normalization is visible.

Do not merge optional evidence with base worst-per-clock reports in a way that weakens conservative behavior. Existing coverage/error distinctions are worth retaining.

## Validation

No new Vivado failure was reproduced. Fixture-test different whitespace/wrapping, missing requirements, MCP paths, merged bit ranges, optional query failure/truncation and utilization-column changes. Compare both sweep decisions and path attribution when changing emitted hierarchy names.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

