# PYRTL complexity review

A fast estimated-timing backend using a generated PyRTL analysis script after GHDL/Yosys lowering. [SYN design](../../SYN_DESIGN.md) and [DEVICE_MODELS design](../../DEVICE_MODELS_DESIGN.md) explain its place among timing models.

Source: [PYRTL.py](../../../src/PYRTL.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 335 | 184 | 8 | 0 | 12 |

Highest-scoring functions: `SYN_AND_REPORT_TIMING_NEW` (121–325, CCN 12); `_RAISE_IF_NO_TIMING_PATHS` (328–335, CCN 5); `IS_INSTALLED` (48–57, CCN 3).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Cross-process lowering/analysis** — `SYN_AND_REPORT_TIMING_NEW` (121–325). VHDL becomes a Yosys BLIF, then a generated Python script imports PyRTL and parses its timing output. Failure and identity cross several tool boundaries.
2. **Private API and model assumptions** — generated `pyrtl.passes._remove_unlistened_nets`, technology scale and FF overhead. Changes in a dependency's private API can break the adapter. This estimated model must not be treated as routed device timing.
3. **No-path and cached-error handling** — `_RAISE_IF_NO_TIMING_PATHS` (328–335), manifest construction and log parsing. The explicit no-timing-path marker is a useful safeguard. The manifest names `sys.executable`, but the script invokes `python3`; different environments could make those different interpreters.

## Duplication and simplification

Share HDL-to-Yosys artifacts and common runner logic with OPEN_TOOLS/DEVICE_MODELS. Make the analysis script a stable helper receiving explicit inputs rather than embedding it in every run. Invoke the interpreter actually recorded in the recipe. Prefer a public PyRTL operation if available, or isolate/version-test the private API use.

Whether this backend should eventually be optional or retired is a product/benchmark decision, not something a complexity score proves. Preserve it if its speed provides a distinct useful tier.

## Validation

No PyRTL run was performed. Verify no-path errors on fresh and reused logs, interpreter/dependency identity, stage failure propagation and changes in model parameters. Compare ranking quality and runtime with DEVICE_MODELS on the same designs before removing either backend.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

