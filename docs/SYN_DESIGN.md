# Synthesis API

How the PypelineC compiler talks to synthesis tools: which tool a build uses,
what runs it can launch, what it expects back, and what it keeps between
builds. Everything that *uses* those runs to reach a goal — the throughput
sweep, the AUTO_PIPELINE / AUTO_MULTI_CYCLE / AUTO_FSM loops — is documented
elsewhere and only calls into this layer.

- Implementation: [`src/SYN.py`](../src/SYN.py), plus one backend module per
  tool (table in §2).
- Iterating these runs toward a timing goal:
  [`SWEEP_DESIGN.md`](SWEEP_DESIGN.md).
- The real sky130 liberty STA backend:
  [`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md).

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section rather
> than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## 1. Who does what

| file | role |
|---|---|
| `src/SYN.py` | The synthesis API: tool selection, the run kinds of §4, report handling, delay/area caches, constraint and final output files, pre-synthesis area/register estimates. |
| backend modules (§2) | Run one tool and parse its output into the report objects of §3. |
| `src/SWEEP.py` | Throughput sweeps: plan registers, run synthesis, react to reports ([`SWEEP_DESIGN.md`](SWEEP_DESIGN.md)). |
| `src/AUTO_PIPELINE.py` | Pipeline representation (`TimingParams`), pipelined VHDL, and the AUTO_PIPELINE build loop ([`AUTO_PIPELINE_DESIGN.md`](AUTO_PIPELINE_DESIGN.md)). |
| `src/AUTO_MULTI_CYCLE.py` | Multi-cycle path constraints and AUTO_MULTI_CYCLE counts ([`AUTO_MULTI_CYCLE_DESIGN.md`](AUTO_MULTI_CYCLE_DESIGN.md)). |
| `src/AUTO_FSM.py`, `src/AUTO_COMB_OPT.py`, `src/AUTO.py` | The other AUTO features and their shared machinery ([`AUTO_FSM_DESIGN.md`](AUTO_FSM_DESIGN.md), [`AUTO_COMB_OPT_DESIGN.md`](AUTO_COMB_OPT_DESIGN.md), [`AUTO_DESIGN.md`](AUTO_DESIGN.md)). |

`SYN.py` imports every backend at module level and never imports `SWEEP`.
Where one of its functions needs the pipeline representation
(`AUTO_PIPELINE`) or multi-cycle constraints (`AUTO_MULTI_CYCLE`), it imports
that module inside the function, so importing `SYN` stays cycle-free.

## 2. Choosing a tool

`PART_SET_TOOL(part)` sets the module-level `SYN_TOOL` to a backend module from
the design's `PART(...)` string, the first time it is called:

| part prefix | `SYN_TOOL` | runs |
|---|---|---|
| none | `PYRTL` | PyRTL's software gate-delay model (no FPGA part) |
| `xc` | `VIVADO` | Vivado synthesis, optionally place-and-route (`VIVADO.DO_PNR`) |
| `ep`, `10c`, `5c` | `QUARTUS` | Quartus |
| `lfe5u` (ECP5) / `ice` | `OPEN_TOOLS` (yosys + nextpnr); ice40 uses `DIAMOND` when installed | |
| `T8` / `Ti` | `EFINITY` | Efinity |
| `GW` | `GOWIN` | Gowin |
| `CCGM` | `CC_TOOLS` | CologneChip toolchain |
| `sky130` | `DEVICE_MODELS` | yosys + ghdl mapping to a sky130 liberty library, then the compiler's own STA ([`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md)) |

`pipelinec --syn_tool pyrtl|sky130` presets `SYN_TOOL` before the design is
parsed, overriding the part. `--yosys_json` (`OPEN_TOOLS.YOSYS_JSON_ONLY`) turns
synthesis into netlist export only. `TOOL_DOES_PNR()` says whether a tool's
timing is post-place-and-route (Vivado/Gowin with PnR enabled, Quartus,
open tools, Efinity, CologneChip) or a synthesis estimate (Diamond, PyRTL,
DEVICE_MODELS); the answer is part of the delay-cache directory (§6).

`SYN_TOOL` and the other build options (`SYN_OUTPUT_DIRECTORY`,
`TOP_LEVEL_MODULE`, `HIER_SYN_MODE`, `MUX_DELAY_KEY_BY_WIDTH`, ...) are module
globals set by `src/pipelinec`. Other modules always read them as `SYN.NAME`,
never through a copied name, so a later assignment is seen everywhere.

## 3. The backend contract

A backend module provides:

- `SYN_AND_REPORT_TIMING(inst_name, Logic, parser_state, TimingParamsLookupTable, total_latency=None, hash_ext=None, use_existing_log_file=True, is_final_top=False)`
  — synthesize one instance (or, with `is_final_top`, build the final design);
- `SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params)` —
  synthesize the whole multi-MAIN top;
- (most backends) `SYN_AND_REPORT_TIMING_NEW`, the shared implementation of
  both;
- optionally `FUNC_IS_PRIMITIVE` / `GET_PRIMITIVE_MODULE_TEXT`, for tools with
  vendor primitives that `VHDL.py` instantiates directly.

Each returns a `ParsedTimingReport`: `orig_text` (the tool log) and
`path_reports`, a dict from path group (clock) to that group's worst
`PathReport`. The compiler reads these `PathReport` fields:

| field | meaning |
|---|---|
| `path_delay_ns` | the worst path's delay; per cycle for a multi-cycle path |
| `path_group`, `source_ns_per_clock` | the clock group and its launch-edge period |
| `start_reg_name`, `end_reg_name`, `netlist_resources` | endpoint and resource names, for attribution (approximate, see [`SWEEP_DESIGN.md`](SWEEP_DESIGN.md#3-the-refinement-loop)) |
| `launch_clock_to_q_ns`, `combinational_delay_ns`, `setup_ns` (optional) | a decomposition of `path_delay_ns`; DEVICE_MODELS provides it, and it becomes the timing-components sidecar of §6 |
| area fields (optional) | measured cell area (`total_cell_area`, `area_unit`, ...) — DEVICE_MODELS only |

To write their project files and constraints, backends call back into a small
part of `SYN.py`: `SYN_OUTPUT_DIRECTORY`, `TOP_LEVEL_MODULE`,
`GET_OUTPUT_DIRECTORY`, `GET_VHDL_FILES_TCL_TEXT_AND_TOP` (the file list, in
the tool's syntax), `GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH` and
`WRITE_CLK_CONSTRAINTS_FILE` (§7). A single-instance run wraps its table in an
`AUTO_PIPELINE.MultiMainTimingParams`, imported inside the function.

## 4. Kinds of synthesis runs

| run | entry point | used by |
|---|---|---|
| per-function delay measurement | `ADD_PATH_DELAY_TO_LOOKUP` (the pre-synthesis wave), `MEASURE_DELAYS` (re-measure named functions), `ESTIMATE_HIER_PATH_DELAYS` (no synthesis: pipeline-map estimates) | every build; the sweep's measured-delay fallback; `AUTO.TimingModel` reads the results |
| one instance at a given latency | `RUN_INST_SYN_AND_UPDATE_CACHE` | the coarse sweep and hotspot mini-sweeps |
| the whole multi-MAIN design | `SYN_TOOL.SYN_AND_REPORT_TIMING_MULTIMAIN` | each planned-sweep iteration, the pin-and-confirm confirmation, `--comb` characterization |
| the final bitstream | `GENERATE_FINAL_BITSTREAM` | `--pins` builds |

`SET_MEASURED_DELAY_FROM_REPORT` turns a per-function report into
`Logic.delay` (integer tenths of a nanosecond, `DELAY_UNIT_MULT`), records its
timing components, and writes the disk cache for non-user code
(`LOGIC_PATH_DELAY_IS_CACHEABLE`). `GET_MAIN_INSTS_FROM_PATH_REPORT` maps a
whole-design report back to MAIN instances by entity-name prefix.


## 5. Delay model: leaf-only synthesis with estimates

`ADD_PATH_DELAY_TO_LOOKUP` can synthesize **every** function individually —
adder, foo, bar, and MAIN each get a syn run — because composing delays from
children can be too inaccurate for some designs. This mode is
`--full_hier_syn` (`HIER_SYN_MODE == "full"`).

There is also a third, opposite mode: `--no_hier_syn`
(`HIER_SYN_MODE == "prim"`) synthesizes **only** true primitive leaves (funcs
with no submodules) and estimates every hierarchical module above them,
including MAINs and stateful atomic spans that `"leaf"` mode would otherwise
give one whole-module synthesis run. It also disables `MEASURE_DELAYS` for
any hierarchical func, so the automatic "estimate proved inaccurate, measure
for real" fallback described below never fires -- a `--no_hier_syn` sweep
that stalls stops at its best result instead. Meant for fast iteration on
designs where even the measurement frontier's syn runs (e.g. a slow
combinational MAIN) are too expensive; pairs well with `--no_sweep`.

Note the one place `"prim"` can do *more* work than `"leaf"`: because every
hierarchical module is now estimated, `_FUNC_NEEDS_SUBMODULE_DELAYS` must
descend into stateful spans that `"leaf"` mode covered with a single
whole-module run, collecting every `BIN_OP` leaf underneath them. Those leaves
are small and disk-cacheable, but on a *cold* `path_delay_cache` a state-heavy
design can trade one big synthesis run for many small ones.

**Area rides the same leaf-synthesis path, sky130 only.** Every leaf syn run
under `DEVICE_MODELS` measures real µm² for free from the same mapped
netlist it already STAs, cached to `area_cache/` alongside
`path_delay_cache/` (own `PYPELINEC_AREA_CACHE_DIR`, own version, so an
STA-only cache bump can't invalidate it and vice versa). A `--no_hier_syn`
build therefore leaves every touched leaf area-cached as a side effect, even
though `--no_hier_syn` disables the delay estimate-vs-measure fallback.
`SYN.WRITE_AREA_ESTIMATE_FILE` prints one `Estimated area: ...` line (cheap,
hierarchy-summed from that cache) next to the existing `Estimated register
usage: ...` line, and any real whole-design confirmation/sweep synthesis
additionally prints the exact `Measured area: ...` from its own mapped
netlist. See `docs/DEVICE_MODELS_DESIGN.md`'s area section for the full
model, its accuracy, and its known limits.

Default (`HIER_SYN_MODE == "leaf"`): only functions whose delay *genuinely
requires* synthesis get a run:

- raw HDL leaves (adders, muxes, raw VHDL text modules, ...), heavily
  disk-cached across builds;
- hierarchical *comb* functions with no sliceable path to raw leaves;
- the **measurement frontier**: topmost *fully-combinational* funcs (see
  below).

**MAINs are not force-synthesized.** A fully-comb main IS the measurement
frontier and gets measured there; a main with state anywhere below is always
estimated — its whole-design zero-clk critical path (which includes the
regions about to be pipelined, and internal reg-involved paths) feeds no
planning decision, and would waste a near-whole-design syn run on a number
that isn't the right quantity anyway (an internal critical path, not the
input-to-output through-delay dataflow slicing geometry needs).
`--coarse` measures its main lazily when needed (estimate used if the main
has state below).

**Modules with Reg/Feedback state in their subtree** (recursive —
`FUNC_SUBTREE_HAS_STATE`): a per-module synthesis run of such a module
reports its *internal critical path* (often register-to-register, possibly
deep inside a nested FSM) — a different quantity than the *input-to-output
through-delay* that dataflow slicing geometry needs. Only a fully
combinational subtree guarantees measured == through-delay. So stateful
modules split by whether slicing descends through them
(`FUNC_SUBTREE_HAS_AUTO_PIPELINE`):

- **on the estimate chain** (an AUTO_PIPELINE tag somewhere below — e.g. a
  dataflow core containing tagged stream pipelines): **estimated** from
  submodule delays, never synthesized per-module — tagging `logic.delay`
  with an inner critical path would poison the parent landscape.
  `MEASURE_DELAYS` also refuses to touch them.
- **not on the chain** (plain FSMs, glue, FIFO wrappers): they are atomic
  spans — slicing never enters, only their span *width* matters. They get
  **one whole-module synthesis at this topmost point and nothing inside
  them is ever synthesized or estimated** (their interior delays feed no
  decision — synthesizing every `BIN_OP` inside an FSM would be pure
  waste).

The design-level fmax cap stateful modules impose is real, but it shows up
empirically in full-design timing reports (and stops the sweep via the
empirical floor), not in the geometry model.

**There are no exceptions**: nothing with state in its subtree is ever
synthesized per-module — a subtree root like wireguard's `encrypt_dataflow`
(Reg/Feedback in its FIFOs/interlocks) is estimated, not measured.
Calibration comes instead from the **measurement frontier**
(`FUNC_IS_TOPMOST_COMB`): the topmost fully-combinational funcs — the
largest subtrees with no Reg/Feedback anywhere inside, where measured ==
input→output through-delay *by construction* — each get one real synthesis
run in the presynth wave. Estimates above the frontier are built from those
measured totals (plus measured atomic spans), so first plans stay at the
fewest-stages guess; interior comb funcs below the frontier stay estimated,
and the landscape rescales their relative geometry into the measured
frontier total.

Hierarchical functions on the pipelining path are **estimated** instead:
`delay = zero-clk pipeline map total` (the critical topological path through
already-known child delays), marked `logic.delay_is_estimated`, never
written to the disk cache. Estimates over-estimate badly — they can't see
cross-boundary synthesis optimizations (wireguard: leaf-sum 1128 ns vs
~150 ns synthesized, mostly collapsed carry chains).

That inflation is why the **measurement frontier** exists: the topmost
fully-comb funcs are measured so the estimated totals above them are
realistic. The landscape keeps estimated geometry (*where* delay lives,
relatively) while measured frontier totals calibrate *how many* cuts — the
first plan is the fewest-stages guess (`~real_delay / target_period`), which
typically just misses timing, and stages are added from synthesis feedback.
Under-pipelining and iterating up is the default; over-pipelining to meet
timing fast is what makes people distrust HLS tools.

**Estimates are never allowed to be why a sweep fails** (in the default
`"leaf"` and `"full"` modes):
- `MEASURE_DELAYS(funcs)` really synthesizes given functions and replaces
  their estimates (invalidating stale pipeline-map caches);
- the refinement loop calls it automatically when it runs out of ideas while
  estimates are still in play (streamsoc: `Falling back to full hierarchy
  synthesis: replacing 21 estimated delays with measured results...` — after
  which sample_power's plan shrank from 25 cuts to 14 and still met timing);
- `--full_hier_syn` forces the synthesize-everything behavior up front.

`--no_hier_syn` (`HIER_SYN_MODE == "prim"`) deliberately gives this guarantee
up: the fallback is gated on `HIER_SYN_MODE == "leaf"` exactly, so it never
fires in `"prim"` mode, and `MEASURE_DELAYS` itself refuses to (re-)synthesize
any func with submodules there. A `--no_hier_syn` sweep that stalls on
estimate-driven cut placement stops at its best result instead of measuring
for real -- the tradeoff for never paying for a hierarchical syn run.


Two more hooks decide *which* functions get delays, for AUTO_FSM's scheduler
(`AUTO_FSM.FUNC_SUBTREE_HAS_AUTO_FSM`, `AUTO_FSM._AUTO_FSM_MUX_ENTITIES`, and
`parser_state.func_force_estimated`); see
[`AUTO_FSM_DESIGN.md`](AUTO_FSM_DESIGN.md#35-delay-measurement).

## 6. Caches

Measurements outlive a build in two committed directories next to `src/`:

- **`path_delay_cache/`** (`PYPELINEC_PATH_DELAY_CACHE_DIR` overrides it). The
  directory is keyed by tool, the tool's model identity (PyRTL tech node and
  flip-flop overhead; DEVICE_MODELS library, corner, `MODEL_VERSION` and
  synthesis recipe), the planner-weight suffix
  (`GET_PLANNER_DELAY_CACHE_SUFFIX`), the part (except for DEVICE_MODELS, whose
  part only selects the tool), and `pnr` / `syn` (`TOOL_DOES_PNR`). Each entry is
  `<key>.delay` (total ns) with an optional `<key>.timing.json` sidecar (schema 1:
  `launch_clock_to_q_ns`, `combinational_delay_ns`, `setup_ns`, `path_delay_ns`).
  `GET_CACHED_LOGIC_FILE_KEY` makes the key: the function name plus input types,
  capped at 235 bytes; a built-in MUX is keyed by packed width
  (`GET_MUX_CACHE_KEY`), or collapsed to one entry where the tool does not
  distinguish widths (`MUX_DELAY_KEY_BY_WIDTH` overrides that).
- **`area_cache/`** (`PYPELINEC_AREA_CACHE_DIR`), DEVICE_MODELS only, keyed by
  `AREA_MODEL_VERSION` rather than `MODEL_VERSION` so an STA-only change keeps it.

Only non-user code is disk-cached (`IS_USER_CODE`), plus built-in MUXes of any
type. `USE_COMBINATIONAL_PLANNER_WEIGHTS` selects whether the planner weighs
the combinational component or the full register-to-register delay
(`GET_PLANNER_DELAY`); it is part of the cache directory so the two never mix.

## 7. Constraints and output files

- **Clock constraints.** `GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH` picks the file
  type per tool (`.xdc`, `.sdc`, `.ldc`, or a nextpnr `.py`) and the MHz per
  clock; `WRITE_CLK_CONSTRAINTS_FILE` writes clocks (a clock with no goal gets
  `INF_MHZ` so a report can still be produced), then asks
  `AUTO_MULTI_CYCLE.GET_MCP_PATH_CONSTRAINTS` for multi-cycle paths
  ([`AUTO_MULTI_CYCLE_DESIGN.md`](AUTO_MULTI_CYCLE_DESIGN.md#2-constraints)).
- **Final files.** `WRITE_FINAL_FILES` writes the VHDL of the final
  `TimingParams` table (dumping AUTO_COMB_OPT's generated sources first),
  invalidates every cached hash/latency in that table so the files are computed
  against current state, and runs `CHECK_VHDL_FILES_CONSISTENCY`: every
  `entity work.X` referenced inside a listed file must be defined by a listed
  file.
- **Estimates.** `WRITE_REGISTERS_ESTIMATE_FILE` and `WRITE_AREA_ESTIMATE_FILE`
  print `Estimated register usage: ...` / `Estimated area: ...` before
  synthesis; `PRINT_MEASURED_AREA_IF_AVAILABLE` prints `Measured area: ...` after
  a whole-design run that reports area.
- **Reports.** `WRITE_MODULE_INSTANCES_REPORT_BY_DELAY_USAGE` and the
  name index below.

**A synthesized netlist with no timing paths is always an error.** A design that
synthesizes away to nothing, typically because it drives no top-level output, has no
Fmax. PYRTL's generated script checks for a zero-length critical path before
`max_freq` (which would divide by zero with `FF_OVERHEAD = 0`). It prints
`PYRTL.NO_TIMING_PATHS_MARKER`, and `SYN_AND_REPORT_TIMING_NEW` raises a readable
error on both fresh and reused logs. DEVICE_MODELS raises the same error for a
zero worst period. Logic that truly has no timing path should be marked `@wires`,
which `LOGIC_IS_ZERO_DELAY` never times. `PYRTL.PathReport` matches only lines
*starting* with `Fmax (MHz):`, so a traceback quoting the script's `print` line can
no longer parse as a number.

### Build output: `name_index.log`

Every successful build, including `--no_synth`, writes
`SYN_OUTPUT_DIRECTORY/name_index.log` through `SYN.WRITE_NAME_INDEX_LOG`. Use it to
trace an entity, record, helper, instance or wire back to Python without reverse
engineering a truncated identifier. It contains:

- **ENTITIES**: logical function key, emitted VHDL base, definition location, instance
  count, and the full logical canonical name when that key was shortened.
- **TYPES**: full logical struct/enum names for shortened internal type keys.
- **SOURCE DESCRIPTIONS**: source symbol, module/qualname, full source path and line,
  parameters and nested type/callable descriptions, and structural identity. Shared
  types retain all contributing origins. Generated helpers identify the originating
  factory or user function as well as their generated implementation.
- **INSTANCES AND WIRES**: each instance's hierarchy/scope, its logical and emitted
  names, submodule call-site locations and raw/emitted wire names with logical types.
  Duplicate-instance collapsing retains every contributing call-site origin.
- **GENERATED SOURCES**: synthetic Python files dumped into
  `pypeline_generated_source/` (interface wiring, casts/bytes helpers and other
  generated functions). These make generated `_py_lNN` coordinates navigable.
- **PIPELINE VARIANTS**: the timing hashes and stage counts associated with functions.
  A timing hash is distinct from a naming digest: it identifies register placement
  and referenced child timing shapes, including alternatives with equal latency.
- **EMITTED IDENTIFIERS**: final composed VHDL identifiers mapped to their logical
  spelling and expanded presentation. This also indexes emitted timing variants.

For example, look up `kept_data_bus_t_from_kept_data_bus_n_4_data_t_uint8_t`
to find the `make_kept_data_bus_t` declaration and `data_t=uint8_t, n=4` description.
For a long `_h...` name, the full description and nested origins explain the omitted
parameters. Instance/wire entries identify the particular call site separately from
the shared function definition.

The emission registry is shared by entity references, VHDL filenames, output
directories and generated constraint paths. Internal logical keys still drive backend
type lookup, function reuse and timing caches; they are not parsed from the rendered
name. See [Generated VHDL names](PY_TO_LOGIC_DESIGN.md#generated-vhdl-names).
Plain C builds have no Pypeline registry and retain their existing naming behavior;
the index uses whatever source and timing information is available.

### Also produced: source locations on stdout/`[sweep]` messages

`SYN.FUNC_SRC_LOC_STR(parser_state, func_name)` appends `" [file.py:line]"` (from the same
`Logic.ast_meta` `name_index.log` reads, empty string when there is none) to every stdout
line that names a function without a location: `"Synthesizing function:"`,
`"Design likely limited to ~N MHz due to function:"`, and every `[sweep]` WARNING/NOTE
line in `SWEEP.py` that names a hotspot or a MAIN. Reading a failing build's own console
output no longer requires separately grepping `module_instances.log`/`pipeline_map.log`
just to find which line of which file a printed name refers to.

## 8. Command line

| flag | meaning |
|---|---|
| `--syn_tool pyrtl\|sky130` | use that backend regardless of `PART(...)` |
| `--comb` | no pipelining; one synthesis run reporting combinational fmax per clock |
| `--no_synth` | like `--comb`, without synthesis: just write the combinational HDL |
| `--full_hier_syn` | synthesize every hierarchy level for path delays (no estimates) |
| `--no_hier_syn` | opposite of `--full_hier_syn`: never synthesize any hierarchical module (incl. MAINs, stateful atomic spans) -- only true primitive leaves are synthesized, everything else estimated. Gives up the automatic estimate-was-inaccurate fallback to real synthesis. |
| `--mux_delay_by_width` / `--no_mux_delay_by_width` | force width-keyed or collapsed MUX delay-cache entries |
| `--verilog`, `--yosys_json`, `--xo_axis`, `--pins FILE` | final-output variants: Verilog top, netlist export only, Vivado AXIS XO, bitstream with pin constraints |

Sweep flags (`--coarse`, `--no_sweep`, `--pipeline_min_effort`, ...) are in
[`SWEEP_DESIGN.md`](SWEEP_DESIGN.md#5-command-line).

## 9. Operator QoR benchmark

`src/tests/pypeline_tests/op_qor_bench.py` measures pipelined (sliced) fmax
for candidate implementations of `PLUS`/`MINUS`/`INFERRED_MULT`/`GT`/`GTE`/
`LT`/`LTE`/`EQ`/`NEQ`, across a width matrix including wireguard-fpga's actual
instantiated widths (mixed `uint32×uint3`, `uint32×uint4`, `uint16×uint1`,
`uint8×uint1`, plus `uint8/16/32/64` same-width pairs). It validates each
soft-operator implementation choice against sliced (not just combinational)
fmax, since a combinational win can vanish or reverse once a design is
actually pipelined.

**The decision metric is pipelined per-stage delay at n_cuts ≥ 1, not comb
delay at n_cuts = 0.** An implementation that wins combinationally can lose
once sliced -- synthesis collapses a comb blob in ways that vanish the moment
registers are inserted (a 1-cut result *worse* than 0-cut is normal and
expected), and a 30-40 stage pipeline never sees the n_cuts=0 number.
Area/utilization is recorded (Vivado runs only) as a free diagnostic, never as
a tiebreaker.

### Harness

One `pipelinec <design>.py --coarse --sweep --start 0 --stop N` invocation per
`(op, impl, widths)` combination sweeps every cut count inside a single process
(`--sweep` forces the dumb +1-clock-per-step path instead of the
delay-report-based incremental guess `--coarse` normally uses), parsing every
printed `Current: ... latency=N clks cuts=N slices` line rather than spawning
one subprocess per cut count. `bench_main` never gets an explicit MHz goal, so
the sweep never "meets timing" early and always walks the full requested range
(or stops on its own once an operator can no longer be sliced -- itself a real
data point: that cut count is the operator's floor). Two tools:

- **`--tool pyrtl`** (default): no `PART()` call, so `PART_SET_TOOL(None)`
  falls back to PyRTL's software gate-delay estimate -- seconds per case
  instead of minutes. Used for broad matrix sweeps. `INFERRED_MULT`
  raw-vs-soft is skipped under this tool (no DSP-inference model; see
  Limitations, below).
- **`--tool vivado`**: `PART("xc7a200tffg1156-2")` (wireguard-fpga's actual
  part), real OOC synthesis, minutes per case. Ground truth.

`--ops` / `--widths` / `--impls` narrow the matrix; results land in
`op_qor_results_<tool>.csv`, one row per `(op, impl, widths, n_cuts)`,
resumable by `(tool, op, impl, l_type, r_type)`. `--impls` is the flag to
reach for when following up a PyRTL finding with a scoped Vivado head-to-head,
e.g. `--tool vivado --impls soft_cmp_sub_swapped,soft_cmp_prefix` -- without
it, a full `--tool vivado` run re-measures every impl in
`CMP_IMPLS`/`PLUS_MINUS_IMPLS`/etc., which is minutes-per-case across the
whole matrix.

Five harness properties that are easy to get wrong:

- **`--stop` is exclusive.** The coarse sweep (`SWEEP.py`) stops once `coarse_latency >=
  stop_at_latency`, so `--stop N` measures cut counts `0..N-1`. The harness
  passes `stop + 1` so the intended top cut count -- the most decision-relevant
  point -- is actually measured.
- **Result width must be full precision.** The generated design takes its
  return type from `arith_result_type(op, l_t, r_t)`, not from `l_t`.
  Declaring `l_t` truncates, and synthesis then prunes the discarded high
  bits: `uint32 * uint32 -> uint64` declared as `uint32` throws away half the
  product (and changes the DSP-inference decision entirely), while `PLUS`
  silently loses its carry-out bit.
- **`MINUS` has no distinct soft implementation.** `make_soft_sub` computes
  `a + ~b + 1` using whatever `PLUS` is registered -- inferred by default --
  so it is the *same netlist* as `raw_default` (confirmed: identical measured
  delay). Only `raw_default` is a real measurement for `MINUS`; there is
  nothing to compare against until a genuinely different subtractor exists.
- **The harness shares the repo's `path_delay_cache/`.** Entries it adds are
  real measurements of real entities, so this is harmless for anything
  reachable by default. The exception is `raw_revived_sliced`, whose
  `FORCE_RAW_INT_CMP_FOR_QOR_BENCH` path emits a raw comparator under the same
  canonical `BIN_OP_GT_*`/`BIN_OP_GTE_*` name a soft build would use -- a
  build that runs the benchmark and then a normal build against the same
  cache directory can pick up a comparator shape it never asked for. This is
  already latent, not just hypothetical: the cache's `BIN_OP_{GT,GTE,LT,LTE}_*`
  entries have mixed provenance today, some measuring the SW_LIB C-generated
  comparator and some the `FORCE_RAW_INT_CMP_FOR_QOR_BENCH` RAW_VHDL one, both
  filed under the same canonical entity name. Harmless only because compares
  are soft by default today; flipping any of `GT`/`GTE`/`LT`/`LTE` back to
  raw would silently pull numbers from an implementation that no longer
  matches what gets built.
- **Only a handful of Karatsuba thresholds build structurally distinct
  hardware.** `op_qor_bench.py`'s `karatsuba_threshold_reps` groups the
  threshold sweep by `CANONICAL_CALLABLE_KEY` before measuring, since most
  threshold values collapse onto the same entity (at uint16: `T=6`≡`T=7`,
  `T=9..15` all identical, `T>=16` degenerates to no-split/shift-add) --
  sweeping every integer threshold would just re-measure the same few shapes
  repeatedly. Separately, `make_soft_mult_karatsuba` itself rejects
  `threshold < 3`: a 3-bit operand's middle sub-multiply recurses at the
  same width as its parent, so anything below 3 never terminates (confirmed
  by measurement: `RecursionError`).

Current soft-operator defaults (comparator, barrel shifter, Karatsuba
threshold, carry-save multiplier) and the QoR reasoning behind each are in
[`pypeline_DESIGN.md`'s Soft Operator Library section](pypeline_DESIGN.md#soft-operator-library-includepypelineoperators);
the investigations that established them are recorded in this file's History
section, below.

## 10. Limitations and future work

1. **Watch for "rewire-only" entities when building a deep, many-node
   soft-operator tree.** A `@hw_func`-tagged entity whose synthesized result
   is pure wiring (a bit-slice, a concat-of-slices, or a reduction level
   with zero arithmetic ops) makes PyRTL's `max_freq` divide by a zero
   critical-path delay and crash the first time it is independently
   timing-estimated. `@wires` is the fix, but must be applied truthfully and
   propagated through the *entire* reachable computation — tagging
   something `@wires` that calls real arithmetic would silently hide that
   delay from every future estimate. Preferring fewer, coarser-grained
   entities (one `@hw_func` per structural level rather than per bit-slice/
   concat node) reduces how many entities are even candidates for this.
2. **Caching for AUTO_FSM's operand-mux measurement entities doesn't fire**
   ([`AUTO_FSM_DESIGN.md`](AUTO_FSM_DESIGN.md#35-delay-measurement)). `_IS_PYPELINE_OPERATOR_LIBRARY_CODE` is meant to classify
   `include/pypeline/operators/` entities as non-user code so their delays
   are cacheable in `path_delay_cache`, but it calls `inspect.getsourcefile`
   on the `@hw_func` wrapper callable rather than the wrapped function, so
   it always resolves to `pypeline.py` and never fires. An `inspect.unwrap`
   at that lookup would fix it. Nothing is incorrect meanwhile — the
   affected delays are just measured every build instead of once.
3. **`INFERRED_MULT` raw-vs-soft comparison is skipped under the PyRTL tool**
   in the operator QoR benchmark (§9) — PyRTL has no DSP-inference cost
   model, so multiplier coverage there is sky130/Vivado-only.
4. **`PLUS` has the same PyRTL blind spot as `INFERRED_MULT`, with a bigger
   real-hardware caveat.** PyRTL's own sweep shows `soft_carry_select`
   beating `raw_default` by a wide margin (uint32 `+` uint32 at 6 cuts: 219
   vs. 119 MHz) — flipping the default on that data alone would be a
   one-line change, and is deliberately not done: Xilinx's `CARRY4`
   primitive gives the raw adder a dedicated fast-carry chain that a
   generic gate-delay model cannot represent, so the PyRTL numbers are not
   trustworthy here without a `--tool vivado` re-measurement, which hasn't
   been done. Not implicated by the wireguard regression either way:
   chacha20's quarter round uses only `+`, `^`, `|`, and constant-amount
   rotates, and a constant shift/rotate amount resolves to a
   `CONST_SL`/`SR_<n>_<type>` built-in before it ever reaches the operator
   registry, so only variable-amount shifts in that design reach a
   soft/raw choice at all.

## History

Why things are the way they are. Entries are keyed by **topic, not date** —
when something changes, revise the entry that owns that topic rather than
adding a new one. Keep a fact here only if it still changes a decision
today: an alternative someone would otherwise retry, a measurement that is
still a live regression reference, or the reason a default is what it is.
Numbers carry the conditions they were measured under, not the date they
were taken. The planner's own history (the planned sweep, the mux
select-fanout cliff, divider acceptance) is in
[`SWEEP_DESIGN.md`](SWEEP_DESIGN.md#history).

### Comparator implementation selection

`GT`/`GTE`/`LT`/`LTE` default to `make_soft_cmp_prefix` — a log2(n)-deep
parallel-prefix magnitude compare (per-bit (gt,lt) codes combined by an
associative leader-select tree, one `@hw_func` per level) — not the older
operand-swapped subtract (`make_soft_cmp_sub_swapped`, still available via
`register_soft_cmp_sub_swapped`) or a bitwise-decomposed one. Every cached
leaf delay is a full out-of-context register-to-register measurement
(clk→Q + routing + logic + setup) that is the same regardless of operand
width — one logic level plus a fixed floor — so a hierarchical
implementation that decomposes into many small leaves is estimated far
worse than it measures (a fully bitwise-decomposed comparator's estimate
ran 26-47x its measured delay). The prefix tree sidesteps that: pricing
each tree level as its own entity, rather than unrolling one flat serial
scan, is what let it clear PyRTL's sweep (24/24 (op,width) combinations,
every `n_cuts>=1`) beating the previous default outright — the same
per-level-entity structure that the rejected borrow-chain candidate below
lacks, which is why PyRTL over-prices it so badly.

Vivado (`xc7a200tffg1156-2`, all 32 (op,width) combinations) confirmed the
prefix tree wins 28/32 at `n_cuts>=1`, margin widening with operand width
across all four ops (up to 40% faster than the swapped-subtract shape at
deep cuts for uint64 `GTE`) — enough to promote it as the unconditional
default. The 4 losses are `GTE`/`LTE` specifically at the two narrowest
widths (uint8, uint16): swapped-subtract's `GTE`/`LTE` costs the same as
its `GT`/`LT` (one subtract, operand order swapped per op), and real
synthesis already optimizes that single small subtract very well at 8-16
bits, so the tree's fixed per-level overhead doesn't pay off until the
comparator is wide enough to be the actual bottleneck — PyRTL's own sweep
missed all four losses entirely, the sharpest concrete instance of its
serial-vs-tree blind spot anywhere in this doc. `register_soft_cmp_sub_swapped`
therefore stays the right pick, via `scope=`, for a design known to be
narrow-width-`GTE`/`LTE`-heavy; `AUTO._SOFT_FACTORY_FOR_OP` also stays
pinned to it deliberately (unrelated to this speed tradeoff — the pin
selects for even decomposition as a sharing candidate, not fmax, and
prefix's decomposition properties there haven't been evaluated).

Two other candidates were measured and rejected. `make_soft_cmp_borrow`
(explicit LSB-to-(width-2) bitwise borrow-propagate loop, same
operand-swap identity as swapped-subtract) measured 7-8x worse under PyRTL
(uint32 `GT` @0cuts: 79.86ns vs. swapped-subtract's 10.61-10.88ns) for a
tool-artifact reason, not a real one: hand-unrolling 31 bits into
individual bitwise leaves forfeits the lumped delay PyRTL gives the native
`-` operator and prices 31 serial gate levels individually — not evidence
about real hardware, and re-ranking it honestly needs a Vivado
remeasurement that hasn't been done. `make_soft_cmp_chunked` (parallel
`chunk_bits`-wide chunks, each an internal serial scan, reduced through the
same prefix tree) beats swapped-subtract at `n_cuts>=2` but loses to the
full prefix tree at every cut count measured, since each chunk still pays
the serial-scan penalty internally — kept as a distinct point on the
granularity spectrum between the two, not a leading candidate. Only a
hand-pipelined raw-VHDL comparator (`raw_revived_sliced`, otherwise dead
code, `RAW_VHDL.py`) is occasionally faster than the prefix tree, but
degrades badly on first slicing, the wrong shape for a deeply pipelined
design. Decision metric throughout ([§9](#9-operator-qor-benchmark)):
pipelined per-stage delay at `n_cuts >= 1`, never comb delay at
`n_cuts = 0` — synthesis collapses a comb blob in ways that vanish the
moment registers are inserted, so a combinational win can invert once
sliced.

### Barrel shifter shape

`make_soft_shift_barrel_sl/sr` is a chain of `MUX` leaf entities, one per
bit of the shift amount; comb delay, the slicing floor, and the cuts needed
to reach it are all set purely by *how many* stages the chain has, not by
composition style, stage ordering, or codegen shape (all measured equal).
The shipped shape carried one dead stage (`amount_bits` sized from
`n_bits.bit_length()` instead of `(n_bits-1).bit_length()`, so a 32-bit
shifter had an unreachable shift-by-32 stage) — fixed to the minimal stage
count, which reaches the true floor one cut sooner on both PyRTL and real
Vivado synthesis. A masked/AND-OR select (no mux) ties on combinational
delay but is measurably worse once sliced, and a one-hot decode is
decisively worse (the "free" parallel shifted versions still need real
comparator+OR-tree logic to select among them) — both rejected. Rotate
(`rotl`/`rotr`, previously constant-amount only) and a unified 4-mode
shift/rotate primitive (`make_soft_shift_rot`) are now built from the same
minimal-stage barrel via a single left-only funnel shift, rather than
composing up to four separate barrels — equal-or-better at every cut count,
roughly half the mux-entity count of the naive four-barrel composition.

### Karatsuba base-case threshold

`make_soft_mult_karatsuba`'s recursion floor (`threshold`) is 16, not 8.
Below 16 bits, splitting is pure loss at every cut count: comb delay falls
monotonically as `threshold` rises, but so does sliced fmax, all the way to
the trivial no-split case — Karatsuba's recombination cost (two adds, a
3-way subtract, a 3-way shifted sum, all at or near full output width) is
fixed-ish overhead that a 16-bit-or-smaller multiply's actual work never
earns back. 16 is deliberately the ceiling of what was measured, not an
estimate of some wider optimum; a real (non-degenerate) optimum above 16
bits — the original motivation for Karatsuba's presence in this library —
remains open. `register_soft_mult_karatsuba(threshold=...)` still reaches
any threshold explicitly.

### Carry-save multiplier: default, and why it replaced shift-and-add

`register_soft_mult()` registers `make_soft_mult_carry_save` (`max_width=2`),
not `make_soft_mult_shift_add` (still available via
`register_soft_mult_shift_add()`). The carry-save reduction is a direct
algorithm port of a real, externally-authored sky130-targeted design (a
CoHDL-generated `uint16 x uint16` multiplier, 684 MHz at 33 cycles): every
add is capped at a fixed small width, and its carry-out is folded into the
next stage's input rather than resolved in place — cheap on an ASIC with no
dedicated carry chain, where `make_soft_mult_shift_add`'s balanced tree of a
few full-width carry-propagate adds is the wrong (FPGA-carry-chain-shaped)
tradeoff. Auto-pipelined via the *planned* sweep (not `--coarse`, which has
an unrelated pre-existing crash on this design's many narrow leaves —
[`SWEEP_DESIGN.md` Limitations](SWEEP_DESIGN.md#7-limitations-and-future-work), item 1) with a real `@MAIN(700)` target and the latchup-style
`--no_sweep --no_hier_syn` flags, the first emitted candidate reaches
700.64 MHz at 30 cycles (31 stages), beating the reference's
own 684 MHz/33 cycles.

| requested `CLK_RATE_MHZ` | added-clock latency | comb stages | measured fmax |
|---:|---:|---:|---:|
| 700 | 30 | 31 | 700.640825 MHz |
| 701 | 59 | 60 | 909.794952 MHz |
| 720 | 60 | 61 | 909.794952 MHz |
| 905 | 60 | 61 | 909.794952 MHz |

The 700 MHz point preserves the established 31-stage baseline. The first
deeper family is selected by a 701 MHz request and improves measured fmax by
29.852% while remaining below 64 stages. Its frozen mapped netlist has 7,164
cells, 4,605 sequential cells, and zero unmapped cells.

The old plateau had two independent causes. A two-input-bit `PLUS` was capped
from its widened three-bit output and its nominal one-bit-per-stage lowering
still left a complete full-adder path in stage 1. At the same time, one
logical delay-axis cut selected one arbitrary member of a parallel narrow-op
rank instead of registering the complete frontier.

The fixes are generic: binary split width comes from the operands, the
two-stage two-bit unsigned add uses registered carry-prefix state, and typed
placement can synchronize parallel output or bit frontiers. Selection remains
based on measured timing components and requested stage budget; neither the
elaborated multiplier architecture nor an operator-overload choice depends on
the requested clock, target device, or a hard-coded multiplier boundary.

The 909.794952 MHz critical path is 1.099148767 ns: 0.6644067045 ns launch
clk-to-Q, one 0.2936405239 ns `and2_1` arc, and 0.1411015387 ns setup. The
exact 720 MHz candidate's final VHDL also passed the 51-product GHDL test with
bubbles, ordering, and exact 60-clock latency.

Two real bugs surfaced while porting, both worth remembering as traps for a
similar port: (1) a bare pure-wire entity (a bit-slice passthrough, or a
reduction level with zero `add` ops) crashes PyRTL's `max_freq` with a
divide-by-zero the first time it's independently timing-estimated — fixed
with `@wires`, which must be applied truthfully and threaded through the
*entire* reachable computation (a combine node is only pure wires if both
children are), since a false `@wires` tag would silently hide a real
child's delay from every future estimate; (2) multiplying by a 1-bit
operand makes every partial product disjoint, so the pairing scan that only
shrinks the summand count on an `add` hung indefinitely — fixed by merging
contiguous non-overlapping (`pass`) elements for bookkeeping only, with a
hard iteration cap as a backstop.

The first construction pass emitted one `@hw_func`/`@wires` entity per
bit-slice and per 2-input concat node — 2,489 `.vhd` files for one
`uint16 x uint16` instance, ~78% of them pure-wire entities synthesizing to
nothing. Rebuilding around one `@hw_func` per reduction level (each owning
its own reduction loop *and* its tail call to the next level, matching the
precedent `soft_div_radix` already set for a loop body whose per-iteration
closure data varies) cut that to 41 files with no change to either public
factory signature. General lesson: prefer one entity per structural level
over one entity per primitive operation when building a deep, repetitive
soft-operator tree — fewer entities also means fewer places a `@wires` tag
needs to be correct.
