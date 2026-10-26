# OPEN_TOOLS complexity review

GHDL/Yosys/nextpnr and device-specific open-tool flows, plus ECP5 primitive rendering. [SYN design](../SYN_DESIGN.md) is its architectural reference.

Source: [OPEN_TOOLS.py](../../src/OPEN_TOOLS.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 1,831 | 1,365 | 27 | 4 | 39 |

Highest-scoring functions: `GET_PRIMITIVE_MODULE_TEXT` (1068–1831, CCN 39); `SYN_AND_REPORT_TIMING_NEW` (666–950, CCN 31); `__init__` (440–555, CCN 27).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Run construction** — `SYN_AND_REPORT_TIMING_NEW` (666–950). XC7 final builds, JSON-only output, seeds, manifests, GHDL plugin handling and nextpnr flags interact. Reusing a timing log is insufficient when the requested result is a netlist or bitstream; the explicit bypasses already present are necessary.
2. **Timing parser** — report constructors around 440–598. Tool-specific prose supplies clock groups and path resources. Device families and synthesis-only versus routed flows do not expose identical evidence.
3. **Primitive templates** — `GET_PRIMITIVE_MODULE_TEXT` (1068–1831). A 764-line generator repeats per-pin component declarations and maps while assigning input/pipeline/output and extra register stages. Latency accounting must match the available physical primitive registers.
4. **Tool/part discovery** — `PART_TO_CMD_LINE_OPTS`, executable/plugin detection and family flags. Hidden global selection and fallback paths can make a locally installed tool behave differently from the declared recipe.

## Duplication and simplification

The inherited clone scan found many overlapping repeated statement windows in the primitive generator. Replace per-bit declarations/maps with width/pin descriptors and loops, preserving named exceptional pins and register policy. Do not count those overlapping windows as separate savings.

Factor the common HDL-to-Yosys preparation used by this file, PYRTL, DEVICE_MODELS and CXXRTL into an artifact-producing operation. The shared runner should retain tool-specific switches and final-output requirements. An estimated 250–500 physical lines may disappear from the primitive renderer after helpers; this is unimplemented.

## Validation

No new open-tool failure was reproduced. Check ECP5 supported widths and register counts, final XC7 versus characterization names, seed-sensitive reuse, JSON artifacts on a warm cache, and long file lists. Verify emitted port coverage and realized latency, then use representative real tool builds for any template refactor.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

