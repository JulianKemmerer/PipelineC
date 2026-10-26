# MODELSIM complexity review

Interactive ModelSim project setup, not a complete automated Pypeline testbench. [SIM design](../SIM_DESIGN.md) is its reference.

Source: [MODELSIM.py](../../src/MODELSIM.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 124 | 89 | 1 | 0 | 5 |

Highest-scoring functions: `DO_OPTIONAL_DEBUG` (28–124, CCN 5).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Project setup and process exit** — `DO_OPTIONAL_DEBUG` (28–124) writes project/INI files, invokes vsim and unconditionally exits with -1 afterward. Successful interactive setup and simulation failure are not distinct outcomes.
2. **Input selection** — it calls `SIM.GET_SIM_FILES(latency=0)` even when a different latency was passed. That helper recursively finds VHDL rather than using the final artifact list, risking stale/duplicate entities.
3. **Tool-specific dependency setup** — Vivado float packages and installation fallbacks are embedded in the adapter. Generated Tcl and shell paths use different quoting mechanisms.

## Duplication and simplification

Consume the final manifest and return a project/setup result. Let the CLI decide whether interactive completion is success. Keep simulator library setup data local, but share workspace/process handling. Do not build another simulator abstraction just to wrap 124 lines; the value comes from joining the other adapters' existing contract.

## Validation

No ModelSim session was launched. Test emitted project inputs against a directory containing obsolete candidates, honor the selected final timing plan, and distinguish setup failure from a successfully closed GUI.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

