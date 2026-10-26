# VERILATOR complexity review

Verilator harness/build adapter after generated VHDL is converted to Verilog. Read [SIM design](../SIM_DESIGN.md) for its role and user-provided main.cpp support.

Source: [VERILATOR.py](../../src/VERILATOR.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 203 | 125 | 2 | 1 | 17 |

Highest-scoring functions: `DO_SIM` (28–203, CCN 17); `GET_VERILATOR_BIN_PATH` (19–25, CCN 3).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Harness and symbol generation** — `DO_SIM` (28–203). Clock aliases, debug macros, latency constants, generated C++ and build commands share one routine. Escaping must match converted Verilog identifiers.
2. **Unsupported clock/run policy** — when a default clock is unknown or multiple clocks exist, the loop is commented out and the generated program returns success. This can look like a completed simulation while no cycles ran. User-provided main.cpp is a valid escape hatch.
3. **Run-all value** — the loop bound is emitted from `args.run`; the CLI's nonnumeric run-all mode needs an explicit supported/unsupported contract, rather than C++ text generated from an arbitrary value.
4. **Process and build configuration** — hardcoded make parallelism, shell paths and `sys.exit` repeat adapter policy.

## Duplication and simplification

Share conversion artifacts, process execution and run requests with CXXRTL/COCOTB while keeping engine-specific symbol/harness emission. Validate default harness capability before generation and return an explicit setup-only/unsupported result when no clock can be driven. Do not report success solely because an empty harness exits zero.

## Validation

The empty-loop branch was inspected, not executed with Verilator. Check generated harnesses for zero/one/multiple clocks, debug ports and run-all, and test custom main.cpp separately. Verify native/HDL comparisons use a harness that actually advances clocks.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

