# QUARTUS complexity review

Quartus adapter and LPM_MULT primitive rendering, called after Python elaboration through SYN. See [the backend contract](../SYN_DESIGN.md#3-the-backend-contract).

Source: [QUARTUS.py](../../src/QUARTUS.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 528 | 362 | 10 | 0 | 13 |

Highest-scoring functions: `__init__` (165–253, CCN 13); `SYN_AND_REPORT_TIMING_NEW` (289–455, CCN 8); `PART_TO_FAMILY` (29–42, CCN 6).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Path parsing/selection** — `PathReport.__init__` (165–253), `ParsedTimingReport.__init__` (148–161). Fixed token offsets derive period, slack and endpoints. Multiple reports for one group overwrite the earlier entry rather than explicitly selecting the worst, making correctness depend on report ordering.
2. **Shared run scaffolding** — `SYN_AND_REPORT_TIMING_NEW` (289–455). Directory, entity/hash, constraints, manifest, reuse and script logic largely repeats other backends.
3. **Primitive latency** — `GET_PRIMITIVE_MODULE_TEXT` (51–127). LPM_MULT parameterization must agree with compiler latency and signedness; hardware-specific rules belong here.
4. **Constraint dependency** — this backend consumes the shared SYN clock writer. The three-clock separator defect is confirmed in [SYN's review](SYN_COMPLEXITY_REVIEW.md#duplication-and-simplification), not in this parser.

## Duplication and simplification

Extract generic run preparation/reuse into SYN and use a shared validated report record. Keep Quartus grammar and primitive rendering local. Select the worst path explicitly after parsing rather than assuming output order. Build asynchronous clock constraints from a list of commands with one serialization boundary.

## Validation

The malformed shared SDC output was reproduced without Quartus. No real Quartus regression was run. Test reordered multiple paths, missing clock/slack fields, escaped endpoint names, and signed/unsigned LPM_MULT latency before replacing its adapter.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

