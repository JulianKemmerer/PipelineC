# COCOTB complexity review

Generated cocotb testbenches, makefiles and result interpretation for HDL simulation. [SIM design](../SIM_DESIGN.md) documents this adapter and the single-clock generated template.

Source: [COCOTB.py](../../src/COCOTB.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 353 | 133 | 3 | 1 | 19 |

Highest-scoring functions: `DO_SIM` (60–296, CCN 19); `CHECK_COCOTB_RESULTS` (299–353, CCN 7); `GET_MAKEFILE_TEXT` (15–57, CCN 1).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Testbench generation** — `DO_SIM` (60–296). Clock startup/settling, finite versus run-all loops, debug helpers, sim_finish behavior, makefile selection and subprocess verdicts are coupled. A one-cycle labeling change can invalidate native/HDL comparisons.
2. **Zero input setter** — the emitted debug-input helper branches on `if val_input:`. Zero is a valid hardware value but chooses the getter branch. A probe evaluated the actual source template and confirmed a signal initially 7 stayed 7 after `drive(dut, 0)`.
3. **Result interpretation** — `CHECK_COCOTB_RESULTS` (299–353). It reads `results.xml`, otherwise falls back to a particular console substring. It checks failure elements but does not require a nonempty testcase collection. A custom makefile or stale result file needs an explicit freshness/result-path contract.
4. **Control-flow outcome** — the backend calls `sys.exit(0)` after success, preventing a normal caller from treating it as a reusable API.

## Duplication and simplification

Separate a testbench description, text rendering, execution and result validation. The setter needs an explicit absent-value sentinel (at minimum `is not None`) so every integer value can be written. Share clock/run-limit policy through a SimulationRequest; retain backend-specific scheduling semantics.

Use the configured structured results path, ensure it belongs to this invocation and validate that tests actually ran. Return a SimulationResult to the CLI. The actual cocotb API compatibility should be tested against supported versions before altering signal-assignment syntax.

## Validation

The zero-value helper bug was reproduced without cocotb/GHDL; see [experiments](REVIEW_EXPERIMENTS.md#backend-adapter-probes). Test helper writes of 0/nonzero, initial clock edges, sim_finish versus assertion/crash, empty/stale XML and custom result locations. No complete simulator run was performed here.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

