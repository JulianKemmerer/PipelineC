# DIAMOND complexity review

Lattice Diamond adapter supporting LSE and Synplify timing formats. Its public interface is documented in [SYN design](../SYN_DESIGN.md#3-the-backend-contract).

Source: [DIAMOND.py](../../src/DIAMOND.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 478 | 311 | 12 | 1 | 20 |

Highest-scoring functions: `init_synplify` (279–372, CCN 20); `SYN_AND_REPORT_TIMING_NEW` (65–192, CCN 11); `init_lse` (375–466, CCN 10).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Two timing grammars** — `PathReport.init_synplify` (279–372), `init_lse` (375–466). Source/capture clocks, resource paths and fixed token positions differ. Global `DIAMOND_TOOL` determines which schema a PathReport expects.
2. **Path aggregation** — `ParsedTimingReport.init_lse`/`init_synplify`. Both select the worst per clock, but duplicate the reduction and error behavior; zero-path handling differs by grammar.
3. **Run preparation** — `SYN_AND_REPORT_TIMING_NEW` (65–192), output naming, constraints and scripts. Most of this is shared backend work.

## Duplication and simplification

Keep two small parsers returning one common report type; share validation and worst-per-clock reduction. Pass the selected grammar explicitly to parsing instead of consulting mutable module state. `NODE_TO_ELEM` duplicates OPEN_TOOLS's escaped-dot handling and can become a named path-normalization helper. ECP5 primitive delegation to OPEN_TOOLS is already useful reuse.

## Validation

No new defect was reproduced. Fixtures should cover both tool modes, escaped record fields, mixed clocks, zero/missing paths and multiple report orderings. Common runner extraction must retain the different command recipes and cache identities.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

