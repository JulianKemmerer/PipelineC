# CXXRTL complexity review

GHDL/Yosys CXXRTL simulation adapter. Small and template-oriented, but its clock and lifecycle behavior matters when selected for a Python design. See [SIM design](../SIM_DESIGN.md).

Source: [CXXRTL.py](../../src/CXXRTL.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 133 | 64 | 1 | 0 | 9 |

Highest-scoring functions: `DO_SIM` (14–133, CCN 9).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Monolithic `DO_SIM`** (14–133). It derives names, writes a C++ harness, discovers tools, compiles and executes in one routine.
2. **Clock assumptions** — zero clocks indexes an empty list; multiple clocks only warn, while the default harness still toggles one `top.clk`. Correct multi-clock simulation is not implemented by this template.
3. **Run limits and output names** — the default C++ loop hardcodes ten cycles and ignores the function's latency argument. Symbol escaping differs from Verilator's names and must remain backend-specific.
4. **Command/tool consistency** — the configured Yosys binary is used for conversion but `yosys-config` comes from PATH. Header paths can therefore come from another installation.

## Duplication and simplification

Share conversion/build manifest and process execution with other adapters. Keep a small CXXRTL name renderer and harness generator. Expose capabilities and reject unsupported default clock configurations before compilation. A common run request would eliminate the hardcoded run-count policy.

The inherited clone detector found substantial similarity with VERILATOR.DO_SIM, primarily orchestration rather than interchangeable generated C++ semantics.

## Validation

No CXXRTL build was run. Test zero/one/multiple clocks, explicit run count, underscore escaping and paired yosys/yosys-config selection. Generated harness smoke tests should check unsupported configurations fail clearly.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

