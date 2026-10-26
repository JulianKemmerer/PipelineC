# GOWIN complexity review

Gowin tool/part selection, HTML timing reports and final-build handling. [SYN design](../../SYN_DESIGN.md) documents the part-version suffix and adapter contract.

Source: [GOWIN.py](../../../src/GOWIN.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 615 | 511 | 9 | 0 | 15 |

Highest-scoring functions: `SYN_AND_REPORT_TIMING_NEW` (464–607, CCN 15); `__init__` (31–66, CCN 9); `__init__` (70–97, CCN 8).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Repairing HTML as XML** — `ParsedHTMLTimingReport.__init__` (31–66), `PathHTMLReport.__init__` (70–97). String substitutions repair malformed tags/entities, then fixed child indexes locate tables and columns. A tool update adding a wrapper/table column can break parsing or misread timing.
2. **Part interpretation** — `PART_TO_DEVICE_VERSIONS` (406–428), package/grade tables and grade substring matching. Overlapping package prefixes or additional version syntax can select the wrong family row.
3. **Artifact names and final builds** — `SYN_AND_REPORT_TIMING_NEW` (464–607). Top naming, synthesis report paths and final bitstream bypasses must remain consistent. Several name/file-list computations are repeated; unused-looking latency/hash arguments are inherited from the common API.

## Duplication and simplification

Keep package/version data declarative and validate a parsed part record. Parse timing by semantic table labels with a tolerant HTML parser if the format continues to require repairs; avoid replacing this with another growing list of substitutions. Inspect available tool-native structured reports before adding a dependency.

The common synthesis runner can own manifest/reuse and final-artifact requirements. The backend should supply part configuration, project text and report parsing. Explicit worst-per-group selection is safer than taking the first group occurrence by convention.

## Validation

No Gowin run or parser failure was reproduced. Use captured malformed HTML, added table rows, multiple paths and package-prefix overlaps. Confirm final build input top names match emitted files and cached characterization never suppresses bitstream production.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

