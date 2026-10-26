# DEVICE_MODELS complexity review

Liberty-backed synthesis/STA and area modeling, used for fast Python HDL exploration. [DEVICE_MODELS design](../DEVICE_MODELS_DESIGN.md) states the model's limitations and its distinction from routed timing.

Source: [DEVICE_MODELS.py](../../src/DEVICE_MODELS.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 1,963 | 1,411 | 52 | 4 | 65 |

Highest-scoring functions: `run_sta` (505–807, CCN 65); `__init__` (1356–1452, CCN 24); `SYN_AND_REPORT_TIMING_NEW` (1795–1963, CCN 22).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Static timing propagation** — `run_sta` (505–807, CCN 65). Netlist connectivity, topological order, rise/fall arrivals, timing sense, load/slew interpolation, launch clock-to-Q and capture setup all interact. At a register endpoint it picks the larger arrival first, then adds setup for that arrival's transition. The smaller arrival can have a larger slew-dependent setup and therefore the worse total period. Missing arcs, unmapped cells and incomplete topological coverage also must not become reassuring low delay.
2. **Liberty lookup/model assumptions** — cell models, `_bilinear`, sequential classification and graph builders. Extrapolation beyond characterized tables can create extreme or nonphysical values. Registers and latches both being sequential does not by itself implement latch transparency or time borrowing. These are model boundaries to document/test, not newly proven compiler bugs.
3. **Run and cache recipe** — `_run_synth_and_sta` (1559–1764), `SYN_AND_REPORT_TIMING_NEW` (1795–1963). Yosys mapping, library/corner/recipe identity, netlist retention, timing, area and shared log storage must refer to the same artifact.
4. **Self-generated text parsed back into objects** — `PathReport.__init__` (1356–1452). Dozens of optional fields are serialized as human-readable lines and recovered by token matching. Changing a label can silently remove provenance or a model component.

## Duplication and simplification

**Confirmed algorithmic counterexample:** mocked sequential cells gave a rise arrival of 10 ns with 1 ns setup, and a fall arrival of 9 ns with 10 ns setup. The real `run_sta` returned 11 ns; maximizing arrival plus setup over both states gives 19 ns. The [probe](REVIEW_EXPERIMENTS.md#sta-endpoint-polarity) isolates endpoint selection; these are synthetic cells, not a demonstrated error magnitude in the shipped sky130 library. Compare complete endpoint costs before choosing the winner. More generally, propagating only one arrival/slew pair per polarity is an approximation when competing paths have different slews.

The synthesis wrapper duplicates other backends and belongs in the common runner. `run_sta` already returns a structured dictionary and the backend writes a JSON sidecar; extend that existing boundary into the report adapter so timing/area/provenance need not be recovered from self-generated prose. Keep backward text reading only for the cache versions that need it.

Separate Liberty loading, graph construction, propagation and report assembly with explicit coverage results. Consider OpenSTA as an optional accuracy/reference backend before extending this file into a general timing engine. Its documented Liberty/Verilog/SDC capabilities overlap with the custom engine, but deployment cost and runtime on many small characterization jobs need measurement. See the [tool assessment](REVIEW_COMPLEXITY.md#other-tools-and-libraries).

## Validation

Use hand-calculated positive/negative/non-unate chains, reconvergent paths, fanout changes, missing arcs, sequential endpoints and combinational cycles. Assert path components sum to the reported period and coverage failures remain visible. Compare model predictions and runtime with a standard STA engine on the same mapped netlists; no such accuracy comparison was performed in this review.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

