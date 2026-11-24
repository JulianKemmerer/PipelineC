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
2. **Identity and evidence reuse** — synthesis input manifests, stored measurements, delay/area/components caches and tool/recipe identity. File names, source bodies, constraints and target options jointly determine validity. A cache hit must carry enough provenance to decide whether it can drive placement or only provide a starting hint. A result kept for reuse needs the reads it rests on: `RECORDED_READS` scopes record each delay/components/area file read (replacing a process-wide record of every read), and memos replay the reads behind a value. A memo that does not keep its reads hides them from a later scope; `STORED_MEASUREMENT`'s per-parse memo and `Logic.measured_area` are not recorded, which AUTO_FSM's search cache covers by digesting the measured areas of a search's closure instead.
3. **Clock constraints** — `WRITE_CLK_CONSTRAINTS_FILE` (635–760). Tool-specific clock grouping and MCP rules are emitted in one routine. The Quartus branch writes successive asynchronous clock-group commands without a newline or semicolon.
4. **Timing-path normalization/attribution** — `TIMING_REPORT_PATHS`, `DISTINCT_PATHS`, register-bank normalization and MAIN path helpers. Flattened/renamed physical names must map conservatively to logical instances; missing evidence is not a passing observation. Two name schemes meet here and differ: an instance is labeled with the name its caller calls it by (`WIRE_TO_VHDL_NAME` of the local name), while a function is named module-qualified. On WireGuard's Poly1305 body (tree `9fbd5d9f`), `feedback_mul_add_mod_…` labels an instance of `poly1305_math_residue_mul_add_mod_inferred`, an imported alias, and an AUTO_PIPELINE call is labeled with the wrapped function's bare name. `_VHDL_INSTANCE_TRIE`, `PATH_CELLS_BY_MAIN` and `INSTANCE_LABEL_POSITION` map names through the emitted labels; the sweep's function attribution still mostly matches function names as substrings (see the [SWEEP review](SWEEP_COMPLEXITY_REVIEW.md#ranked-hotspots)).
5. **Module-global target configuration** — `SYN_TOOL`, part resolution, output paths and build settings. The driver and optimizer can both select the tool. Import order and parse-time initialization make standalone API usage harder than the CLI.
6. **Final file lists** — `WRITE_FINAL_FILES` and `GET_VHDL_FILES_TCL_TEXT_AND_TOP`. The listed files are computed in `GET_VHDL_FILES_TCL_TEXT_AND_TOP`, and each backend's Tcl generator calls it again, so `read_vhdl.tcl` and `pipelinec_top.qip` are made by filtering that generated Tcl text (`startswith("read_vhdl")`, `{` rewritten to `[subst {`). `--module_prefix` therefore needs a second remap of the paths inside the Tcl text (`MAP_LISTED_PATHS`) besides the one that writes `vhdl_files.txt`. Suspected: a future change to which files the final artifact lists needs both sites again. Passing the list to the Tcl generators, or having them return the lines `WRITE_FINAL_FILES` wants, would leave one.
   Writing the final files repeats work in builds with zero added clocks (`--comb`, `--no_synth`, the no-tool fallback). `WRITE_FINAL_FILES` passes every instance to `AUTO_PIPELINE.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES`, which skips only the files in `_NON_ZERO_CLK_FILES_WRITTEN`: those it wrote itself. `AUTO_PIPELINE.WRITE_ALL_ZERO_CLK_VHDL` doesn't add its files to that set, so the final pass renders every zero-clock entity a second time. On WireGuard's `chacha20poly1305_encrypt_decrypt_shared` (`--no_synth`, Vivado 2019.2 found, tree based on `57185ab7`), that re-render took 18.6 s of `WRITE_FINAL_FILES`' 34.3 s under cProfile, for 411 entity files. Vivado's `read_vhdl.tcl` text took 7.1 s, 1.9 s of it in `vivado -version`. Without profiling, the whole build took 81–92 s, against 61 s for the same build without the final-file step (77 s with no tool found). Suggested: record the zero-clock writer's files in the same set. Its module comment already argues that within one process an entity name fixes the rendered content. Check that every file `vhdl_files.txt` lists keeps its bytes.

## Duplication and simplification

**Confirmed generated-output defect:** with three clocks and the Quartus branch, an in-memory call emitted three `set_clock_groups` statements joined as `...]set_clock_groups...` on one line. The [experiment](REVIEW_EXPERIMENTS.md#quartus-clock-command-separators) exercises the real writer with mocked file IO; Quartus itself was not run. This affects Pypeline multi-clock builds selecting Quartus, subject to frontend/backend support for that design.

Create a shared synthesis runner around `BuildRequest -> ArtifactManifest -> RunResult -> TimingReport`. Backends should provide script generation and parsing hooks while shared code owns directories, invocation, reuse, completeness and provenance. This removes repeated scaffolding without forcing unrelated log grammars into one parser.

Use typed measurement states and a common report validator. Represent clock constraints as records before rendering tool syntax. Move configuration to a build session and manage the worker pool with guaranteed cleanup. Preserve existing explicit measurement frontiers and conservative attribution rules.

## Validation

Re-run the separator probe and parse generated constraints as Tcl with stubbed commands. Fixture-test absent, malformed and reordered reports. Compare same-input warm reuse and intentional invalidation after type, constraint, tool or recipe changes. Check worker failure cleanup and measurement results independent of completion order. This review did not run a full synthesis sweep.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

