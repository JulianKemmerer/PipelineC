# EDAPLAY complexity review

Copies generated VHDL for manual EDA Playground use. This is a small export utility with no complex algorithm; [SIM design](../../SIM_DESIGN.md) supplies context.

Source: [EDAPLAY.py](../../../src/EDAPLAY.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 25 | 16 | 1 | 0 | 3 |

Highest-scoring functions: `SETUP_EDAPLAY` (12–25, CCN 3).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **File inventory** — `SETUP_EDAPLAY` (12–25) uses recursive `SIM.GET_SIM_FILES`, so intermediate files may be exported.
2. **Flattening names** — every source file is copied by basename into one directory. Different source paths with the same basename overwrite each other.
3. **Repeated export** — the directory is reused without an inventory of old outputs. Files no longer in the design can remain in the upload set.

## Duplication and simplification

Use the exact artifact manifest, reject basename collisions or generate a deliberate renamed package, and write into a fresh export directory. Share this with generic artifact packaging only if there is another real consumer. No large rewrite or external framework is justified.

## Validation

No export failure was reproduced. A small file-inventory check with duplicate basenames and a second smaller export is sufficient; no hardware synthesis is needed to verify this change.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

