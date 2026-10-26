# SYN complexity review

Tool selection, measurement collection, constraints, cache/manifests and report normalization shared by Pypeline builds. [SYN design](../../SYN_DESIGN.md) defines the backend contract and several distinct cache layers.

Source: [SYN.py](../../../src/SYN.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 3,967 | 2,733 | 123 | 14 | 60 |

Highest-scoring functions: `ADD_PATH_DELAY_TO_LOOKUP` (3189–3512, CCN 60); `WRITE_NAME_INDEX_LOG` (3701–3838, CCN 30); `LOGIC_IS_ZERO_DELAY` (1796–1876, CCN 28).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Measurement orchestration** — `ADD_PATH_DELAY_TO_LOOKUP` (3189–3512). Full/rooted scope, measured frontiers, modeled/estimated/cached values, mux sharing, area sidecars, thread jobs and follow-up estimates all share one flow. Unknown, estimated zero and proven wiring are materially different states. If a worker raises before the final close/join, pool cleanup is not protected by a context manager.
2. **Identity and evidence reuse** — synthesis input manifests, stored measurements, delay/area/components caches and tool/recipe identity. File names, source bodies, constraints and target options jointly determine validity. A cache hit must carry enough provenance to decide whether it can drive placement or only provide a starting hint.
3. **Clock constraints** — `WRITE_CLK_CONSTRAINTS_FILE` (635–760). Tool-specific clock grouping and MCP rules are emitted in one routine. The Quartus branch writes successive asynchronous clock-group commands without a newline or semicolon.
4. **Timing-path normalization/attribution** — `TIMING_REPORT_PATHS`, `DISTINCT_PATHS`, register-bank normalization and MAIN path helpers. Flattened/renamed physical names must map conservatively to logical instances; missing evidence is not a passing observation.
5. **Module-global target configuration** — `SYN_TOOL`, part resolution, output paths and build settings. The driver and optimizer can both select the tool. Import order and parse-time initialization make standalone API usage harder than the CLI.

## Duplication and simplification

**Confirmed generated-output defect:** with three clocks and the Quartus branch, an in-memory call emitted three `set_clock_groups` statements joined as `...]set_clock_groups...` on one line. The [experiment](REVIEW_EXPERIMENTS.md#quartus-clock-command-separators) exercises the real writer with mocked file IO; Quartus itself was not run. This affects Pypeline multi-clock builds selecting Quartus, subject to frontend/backend support for that design.

Create a shared synthesis runner around `BuildRequest -> ArtifactManifest -> RunResult -> TimingReport`. Backends should provide script generation and parsing hooks while shared code owns directories, invocation, reuse, completeness and provenance. This removes repeated scaffolding without forcing unrelated log grammars into one parser.

Use typed measurement states and a common report validator. Represent clock constraints as records before rendering tool syntax. Move configuration to a build session and manage the worker pool with guaranteed cleanup. Preserve existing explicit measurement frontiers and conservative attribution rules.

## Validation

Re-run the separator probe and parse generated constraints as Tcl with stubbed commands. Fixture-test absent, malformed and reordered reports. Compare same-input warm reuse and intentional invalidation after type, constraint, tool or recipe changes. Check worker failure cleanup and measurement results independent of completion order. This review did not run a full synthesis sweep.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

