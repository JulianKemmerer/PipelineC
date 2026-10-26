# SIM complexity review

Simulator selection, build-phase dispatch, file inventories and support checks. [SIM design](../../SIM_DESIGN.md) covers each adapter; separate reviews cover their implementations.

Source: [SIM.py](../../../src/SIM.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 364 | 262 | 11 | 2 | 21 |

Highest-scoring functions: `_DO_OPTIONAL_SIM` (110–207, CCN 21); `CHECK_PIPELINED_NATIVE_SIM_SUPPORTED` (297–364, CCN 17); `SET_SIM_TOOL` (20–36, CCN 8).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Build-phase policy** — `NATIVE_SIM_SKIPS_BUILD`, `SIM_AT_COMB_STAGE`, `DO_COMB_STAGE_SIM`, `_DO_OPTIONAL_SIM` (110–207). Source extension, comb/no-synth modes, tool fallback and latency maps determine whether simulation sees source semantics or the final built circuit. This policy is also reflected in the driver and debug CLI.
2. **Native support boundary** — `CHECK_PIPELINED_NATIVE_SIM_SUPPORTED` (297–364). It walks effects and rejects global-wire uses the native delayed-result model cannot represent. The runtime has a corresponding check. Missing a case produces plausible but cycle-wrong results.
3. **Simulation file inventory** — `GET_SIM_FILES` (210–233). It recursively collects VHDL with a narrow legacy filename filter. MODELSIM and EDAPLAY call it, so stale sweep candidates and same-named entities can enter their inputs. Other backends consume the final manifest.
4. **Global selection** — `SIM_TOOL` and `SET_SIM_TOOL`. Selection persists at module scope; the default C case does not unconditionally restore the default after an earlier Python selection. Same-process usage needs a defined reset boundary.

## Duplication and simplification

Give every simulator one `SimulationRequest` containing a final artifact manifest, clock description, run limit and optional user testbench. Replace recursive VHDL discovery with the exact build file list. Share support/capability checks between dispatch and runtime, keeping unsupported cases explicit.

Have backends return a `SimulationResult`; the CLI should own process exit. This removes different return/exit conventions and makes adapters easier to test. Centralize build-mode normalization so the driver, simulator and comparison tool do not maintain independent versions.

## Validation

The recursive collection behavior was verified by reading its callers; no stale-file simulation was run. Test a manifest containing one final entity while older candidates remain on disk, native fallback after unavailable synthesis, unsupported global timing, and sequential simulator selections in one process.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

