# DEVICE_MODELS: a real sky130 liberty STA `SYN_TOOL`

`src/DEVICE_MODELS.py` is a second timing-estimation backend alongside
`src/PYRTL.py`: real sky130 NLDM liberty delay tables and a rise/fall-aware
static timing analyzer, wired in as a full `SYN_TOOL` (it places pipeline cuts
*and* scores them, the same as every other backend — not a checker bolted onto
PyRTL).

It exists because PyRTL's built-in cost model (`gate_delay_funcs` in its
`analysis.py`) is a flat per-gate-type, per-width lookup with **no fanout or
load term at all** — confirmed against the current PyRTL source (checked
against both the locally installed 0.11.3 and the latest 1.0.3 release; this
has not changed). Real sky130 synthesis shows a hard, load-dependent cliff:
driving past a cell's characterized `max_capacitance` costs several times the
in-range delay, and that cliff is exactly the shape a per-gate flat model can
never reproduce. See [`SYN_DESIGN.md`](SYN_DESIGN.md) for the pipelining
sweep this feeds into, and [`AUTOFSM_DESIGN.md`](AUTOFSM_DESIGN.md) for the
sibling feature whose delay budget comes from the same `SYN_TOOL` interface.

---

## 1. Selecting the tool

Two independent ways in, matching or overriding each other:

```python
from pypeline import PART
PART("sky130_fd_sc_hvl")          # or #pragma PART "sky130..." in C
```

```
pipelinec design.py --syn_tool sky130     # overrides PART, either direction
pipelinec design.py --syn_tool pyrtl      # forces PyRTL even with a sky130 PART
```

**No part and no flag stays PyRTL — completely unchanged.** Every existing
part-less design keeps today's behavior; nothing about this feature is
default-on. `SYN.PART_SET_TOOL` (`src/SYN.py`) gained one `elif` branch, and
`--syn_tool` just pre-sets `SYN.SYN_TOOL` before that function's own
`if SYN_TOOL is None:` guard ever runs.

## 2. How it works

One file, three sections, in dependency order:

**(a) Liberty data.** `LOAD_LIBERTY(library, corner)` reads a condensed JSON
pack (`src/liberty_data/sky130_fd_sc_hvl__tt_025C_3v30.json`, ~2MB, generated
offline from the real `.lib` by a scratchpad script — not shipped, not a
runtime dependency of this section). **All 57 cells in the corner are
included**, not just the ones any one design happens to use, so arbitrary user
code resolves against it. Per cell: input pin capacitances, `max_capacitance`,
and NLDM tables (`cell_rise`/`cell_fall`/`rise_transition`/`fall_transition`,
plus `setup_rising`/`hold_rising` constraint tables) keyed by
`(out_pin, related_pin)` or `(in_pin, related_pin, timing_type)`.
`_bilinear()` looks up a 2D `(input_transition, output_load)` table with
linear **extrapolation** past either axis's bound — not clamping, because a
real out-of-range load is real and clamping would silently underpredict
exactly the cells that decide the cliff.

**(b) The STA engine.** `run_sta(json_path, top, ...)` builds the netlist
graph from a liberty-mapped yosys JSON, Kahn's-algorithm topological orders
the combinational cells, and propagates arrival times. Sequential-cell
classification comes from the liberty pack's own `is_sequential` flag (any
cell with an `ff` or `latch` group) rather than a hardcoded name list, so
every DFF/latch/scan variant in the corner is handled uniformly. Three things
this does that a naive port of "walk the graph, take the worse of rise/fall
at each hop" does not:

1. **Rise and fall propagate separately**, using each arc's `timing_sense`
   (`positive_unate`: rise←rise; `negative_unate`: rise←fall; `non_unate`:
   conservative, either) to pick which input polarity feeds which output
   polarity. Taking the worst of both at every hop double-counts on inverting
   chains — real signal transitions alternate fast/slow edges, and real
   silicon never charges the worst edge twice in a row.
2. **Register clk→Q is a real modeled arc** (idealized clock: arrival 0, a
   fixed transition), not an assumed-zero seed — `dfxtp_1`'s own clk→Q is
   0.68ns at light load and 2.6ns at fanout 64 in this library.
3. **Setup is checked at data endpoints**, not just combinational arrival:
   period = clk→Q + combinational + `setup_rising` at the capturing register.

No net/interconnect delay is modeled — real sky130 flows report zero net
delay in their timing reports, so this matches the ground truth exactly rather
than adding an unvalidated wire-load guess.

Sections (a) and (b) depend on nothing but the stdlib — no `SYN`/`VHDL`
import anywhere in them — so both can be driven standalone, with zero
PipelineC integration, directly against an externally-supplied netlist. That
property is what let the engine be validated (Results, below) before any
compiler wiring existed at all.

**(c) The `SYN_TOOL` surface.** `IS_INSTALLED`, `SYN_AND_REPORT_TIMING[_MULTIMAIN]`,
`ParsedTimingReport`/`PathReport` — modelled directly on `src/PYRTL.py`, the
smallest existing example of the contract `SYN.py` requires. Imports
`SYN`/`VHDL`/`OPEN_TOOLS` *inside* its functions rather than at module top,
specifically so (a)/(b) keep the standalone property above.

The production synth recipe, once per whole-design confirmation or per
isolated leaf entity:

```
ghdl --std=08 <files> -e <top>;
synth -top <top> -noabc;                 # leave all structural mapping to the
                                         #   single liberty ABC pass below
flatten; opt -full;                      # expose and simplify cross-entity logic
dfflibmap -liberty <lib>;
abc -liberty <lib> -fast;                # see "the -fast finding" below
flatten;
write_json <out>.json
```

This is recipe `early_flatten_noabc`, selected 2026-08-20 by reproducing
latchup.app's own post-early-flatten netlists — see "Matching latchup's
early-flatten flow" below.

`run_sta` then runs directly in-process — no second Python subprocess, unlike
PyRTL's flow which shells out to run its own generated script.

The recipe above reaches yosys as a `.ys` script file
(`artifact_paths["synthesis_yosys_script"]`, `<stem>_syn.ys`) passed via
`yosys -s <path>`, not inlined into a `yosys -p '<commands>'` shell argument
— a large design's `ghdl --std=08 <files> -e <top>` command can otherwise
exceed Linux's `MAX_ARG_STRLEN` (131072 bytes per single argv/envp string;
see `pypeline_sim_DESIGN.md`'s cocotb section for the full mechanism).
Cache/artifact identity is unaffected: `recipe_commands_sha256` hashes
`_get_synthesis_recipe_commands()`'s return value directly, never the `.sh`
or `.ys` file text, and `_vhdl_input_record` hashes the VHDL files' own
bytes, not how their paths reach yosys.

Every run writes both the traditional text log and a sibling
`*_timing.json`. The structured report records `worst_period_ns`, `fmax_mhz`,
launch clock-to-Q, combinational and setup components, launch/capture
endpoints, critical-path arcs and loads, cell/unmapped counts,
`max_capacitance` violations, library/corner, synthesis recipe, model version,
and the full model/cache identity. A purely combinational isolated leaf has
zero clock-to-Q and setup by construction; a registered full design normally
has all three components.

The historical no-early-flatten flow remains the `current` **control recipe**.
The opt-in synthesis-recipe matrix also has fixed internal variants for
`synth -flatten`, flattening with `-noabc` before the single liberty ABC pass,
and the former production `early_flatten_opt` sequence. Each variant has a
distinct artifact and cache identity. There is no public arbitrary-flags
interface.

The closed recipe IDs are `current`, `synth_flatten`, `synth_flatten_noabc`,
`early_flatten_opt`, and the production `early_flatten_noabc`, selected only
by the opt-in benchmark's internal `PIPELINEC_INTERNAL_SKY130_RECIPE`
environment variable. The production identity has no recipe suffix. Every
non-production mapped netlist, script, log, leaf-delay cache, and
minimum-period cache carries a versioned `__recipe_<id>_v1` suffix, including
the historical `current` control.

**The empty-suffix rule makes a `MODEL_VERSION` bump mandatory on every
promotion.** Because the default recipe is exactly the one whose cache
identity has no suffix, promoting a different recipe without bumping the
version would leave the identity string unchanged and silently replay the
*previous* recipe's leaf delays out of the same directory. Promotions so far:
2 → 3 with `early_flatten_opt`, 3 → 4 with `early_flatten_noabc`.

**Per-leaf isolation (an architectural limit, not a bug).** Like every
existing `SYN_TOOL`, a leaf-entity `SYN_AND_REPORT_TIMING` call synthesizes
*only* that one leaf in complete isolation, so its measured delay can never
see fanout from a sibling instance elsewhere in the design. Only the
whole-design multimain path ever sees more than one leaf's logic at once.
Real cross-instance net sharing can only be captured by that whole-design
path — see Limitations.

### The `-fast` finding

The plain `abc -liberty <lib>` invocation (no extra flags) uses yosys's
*modern* default liberty script, ending in `&nf {D}` — a network-flow
area-recovery mapper. `{D}` is only replaced when `-D <ps>` is explicitly
passed. Sweeping `-D` from 500 to 32000 picoseconds (a 64x range) against
this design produced **byte-identical output every time** — under the default
script, `-D` has no effect at all. Comparing our mapping of a real sky130
netlist against its own real post-synthesis netlist showed why: ours chose
`sky130_fd_sc_hvl__mux2_1` for ~1000 instances where the real one has
essentially zero, using an AOI-gate decomposition instead — a genuine
mapping-*choice* divergence, not a modeling error (confirmed separately: the
STA engine, fed the real netlist directly, was already accurate to a few
percent).

`abc -liberty <lib> -fast` switches to the *classic* `map {D}` technology
mapper instead. With no other change, this closed nearly all of the gap:
cell-histogram distance to the real netlist dropped by ~8x, `mux2_1` usage
went to exactly zero, and predicted-period error at one measured point went
from +33.6% to −1.6%. Adding a `-D` target back on top of `-fast` made it
*worse* — the fix is the bare flag, not a tuned target. `ABC_EXTRA_ARGS` in
`DEVICE_MODELS.py` is the single switch if this ever needs revisiting.

**Re-validated 2026-08-20, with one cited fact now obsolete.** `-fast` is
still right (it is part of the recipe that reproduces latchup's current
netlists exactly), but "`mux2_1` usage goes to exactly zero" was a property
of *their pre-flatten flow*, not of the flag. Their post-early-flatten
netlists contain 838 `mux2_1` at 33 stages and 745 at 65 — and `-fast` under
the current recipe reproduces those counts exactly too. Mux inference is a
property of the network abc is handed; do not treat "zero `mux2_1`" as the
signature to match.

### Mux path-delay cache key

`SYN.GET_CACHED_LOGIC_FILE_KEY` special-cases mux delay: historically every
mux width/type collapsed to one shared cache key `"mux"`, because PyRTL's own
measurement is provably width-blind (1.640ns at every width 1..64, measured
with the cache deleted). A real per-cell model doesn't share that property —
a 32-bit mux's select really does drive 32 sinks inside its own entity, so it
measures slower than a 2-bit one even in complete per-leaf isolation.

`SYN.MUX_DELAY_KEY_BY_WIDTH` (tri-state: `None`/`True`/`False`) resolves
automatically per tool when unset — collapsed for every tool that predates
this feature (PyRTL included, unchanged), width-keyed only for
`DEVICE_MODELS`. `--mux_delay_by_width` / `--no_mux_delay_by_width` force
either, for any tool, for direct A/B measurement.

In width-keyed mode the key describes physical packed width, not the source
type name: every N-bit integer, signed value, float, enum, array, struct, or
nested aggregate MUX reads and writes `MUX_uintN_t.delay` and its
`MUX_uintN_t.timing.json` sidecar. Built-in MUXes remain cacheable when their
ports carry a user-defined type; unrelated user functions retain the normal
non-cacheable policy. If several cold typed MUX entities resolve to the same
key during one compiler run, only one representative synthesis is launched
and its timing report is propagated to the equivalent logic objects. Collapsed
mode continues to use the single `mux` key exactly as before.

This canonicalization changed neither `DEVICE_MODELS.py`, model V4, timing
coefficients, the liberty data, nor the cache-directory identity: an N-bit
typed MUX is the same isolated MUX bank already represented by the existing
integer key, rather than a new timing model.

### Cache-key versioning

`SYN.GET_PATH_DELAY_CACHE_DIR` appends library + corner + `DEVICE_MODELS.MODEL_VERSION`
for this tool, the same way PyRTL appends `_<TECH>nm_<FF>ff`. Bump
`MODEL_VERSION` on any change to `run_sta`'s algorithm or `ABC_EXTRA_ARGS` that
could change a previously-cached leaf delay's value — otherwise a model
change could silently replay a stale pre-change number.

`GET_MODEL_CACHE_IDENTITY()` is the machine-readable source of truth used by
both timing JSON and benchmark manifests. Fixed non-production recipes extend
that identity with their recipe suffix. Promoting a different recipe requires
a `MODEL_VERSION` bump; merely running an isolated alternate recipe does not
invalidate the unchanged production cache.

### Frozen recipe screen (2026-08-14)

The primary recipe matrix has been run on byte-identical VHDL for the
unchanged gate Divider's isolated `step_gates` entity. The durable evidence is
[`synthesis_recipe_step_gates_matrix.json`](../src/tests/pypeline_tests/qor/synthesis_recipe_step_gates_matrix.json),
including source/VHDL/tool/liberty hashes, exact commands, timing components,
mapped-artifact hashes, and relative deltas:

| recipe | period | fmax | cells | versus `current` |
|---|---:|---:|---:|---|
| `current` | 5.817 ns | 171.90 MHz | 754 | control |
| `synth_flatten` | 4.909 ns | 203.71 MHz | 414 | 15.6% less period, 45.1% fewer cells |
| `synth_flatten_noabc` | 4.948 ns | 202.10 MHz | 425 | 14.9% less period, 43.6% fewer cells |
| `early_flatten_opt` | 4.849 ns | 206.25 MHz | 427 | 16.7% less period, 43.4% fewer cells |

This first screen established that early flattening was materially beneficial
for the isolated step under the pinned tools. It did not by itself justify a
production change; the full-design screen below made that decision.

### Pre-step compare/select cone and clean-baseline floor (2026-08-14)

Two further durable artifacts isolate a different effect and keep their
provenance deliberately separate:

- [`divider_gate_clean_baseline_critical_paths.json`](../src/tests/pypeline_tests/qor/divider_gate_clean_baseline_critical_paths.json)
  is the unchanged gate fixture run by clean commit `c81ca31f`, with the
  `current` recipe and no superseded handoff patch. At 28, 50, 63, 67, and 70
  slices, the winning path starts at the divisor input and traverses the
  pre-step `right != 0` reduction and 32-bit `left_eff` select before entering
  the first radix step. At 67 slices it is 7.010 ns (142.647 MHz); 70 slices
  adds 1,135 mapped cells but changes timing by exactly zero. The shared
  pre-step prefix is about 5.67 ns, dominated by a 4.325 ns fanout-64 NAND3
  arc that violates `max_capacitance`. A hierarchy-delay fallback finally
  gives the mux two near-edge slices at 73, jumping to 224.314 MHz; trim then
  restores a different 66-slice / 67-stage result at 184.348 MHz. The exact
  final 66-slice VHDL passes 141 ordered vectors at 66-cycle latency. That is
  the clean baseline, and it still fails the 48-slice acceptance limit.
- [`synthesis_recipe_pre_divzero_matrix.json`](../src/tests/pypeline_tests/qor/synthesis_recipe_pre_divzero_matrix.json)
  holds the source-generated compare and mux VHDL byte-identical under a
  small frozen wrapper
  ([`synthesis_recipe_pre_divzero_wrapper.vhd`](../src/tests/pypeline_tests/qor/synthesis_recipe_pre_divzero_wrapper.vhd)).
  The leaf VHDL came from clean `c81ca31f`; the synthetic wrapper was mapped
  with this session's diagnostic backend. `current` measures 5.541 ns, 130
  cells, and three capacitance violations. Each early-flatten variant measures
  2.630 ns, 94 cells, and zero violations.

The controlled cone matrix is strong evidence that hierarchy visible to ABC
creates the pre-step fanout cliff, and that early flattening can remove it. It
remains mechanism evidence rather than an acceptance result; the clean
baseline, forced control, and automatic production results retain separate
provenance.

### Full frozen recipe selection and production result (2026-08-15)

The full recipe matrix held the 16 ordered VHDL files byte-identical at the
generic hand-equivalent 32-slice placement (divide-zero select plus the first
31 repeated-step outputs). Every row passed the same 141-vector exact-VHDL
test. The durable summary is
[`synthesis_recipe_forced32_matrix.json`](../src/tests/pypeline_tests/qor/synthesis_recipe_forced32_matrix.json).

| recipe | period | fmax | cells | DFFs | cap violations | map time |
|---|---:|---:|---:|---:|---:|---:|
| historical `current` | 6.703 ns | 149.19 MHz | 27,330 | 3,072 | 3 | 226 s |
| `synth_flatten` | 5.918 ns | 168.98 MHz | 16,359 | 3,072 | 0 | 1,692 s |
| `synth_flatten_noabc` | 5.919 ns | 168.95 MHz | 16,285 | 3,072 | 0 | 1,769 s |
| **`early_flatten_opt`** | **5.667 ns** | **176.47 MHz** | 16,594 | 3,072 | 0 | 242 s |

> **Superseded as the production selection** by "Matching latchup's
> early-flatten flow" below. This matrix stands as the record of the V3
> decision, but its selection policy — maximise *our own* fmax at equal
> latency — turned out to be the wrong objective for a model whose job is to
> predict what latchup will report. `early_flatten_opt` remains available as
> a named recipe.

At equal latency, `early_flatten_opt` has the largest fmax margin, is 39.3%
smaller than the control, and maps in roughly the control's runtime. It was
the production recipe at `MODEL_VERSION = 3`. `synth_flatten_noabc` saves 74
cells versus `synth_flatten` but is a timing tie, takes longer, and loses to
the production recipe by 7.52 MHz. No-`-fast`, `-D`, custom ABC scripts,
buffering/upsize, and register retiming were not promoted; the earlier
no-`-fast`/`-D` evidence was worse or inert, and the higher-return primary
matrix already met the acceptance target without sequential retiming risk.

The first generic automatic planner result produced 33 slices / 34
combinational stages: the divide-zero select, 31 coherent repeated-step
outputs, and one legal operation output inside the last step. A later
minimal-stage regression run with the same production recipe trimmed that to
31 coherent repeated-step output boundaries. Early flattening removes the
former pre-step fanout floor, so no dedicated divide-zero boundary is needed.
An immutable remap of the current 16-file result is **160.43 MHz**, 16,514
cells, 3,007 DFFs, zero unmapped cells, zero capacitance violations, and
complete timing topology. Exact GHDL/cocotb simulation passed 141 ordered
vectors at 31-cycle latency. The combined gate and arithmetic acceptance record is
[`divider_qor_acceptance.json`](../src/tests/pypeline_tests/qor/divider_qor_acceptance.json).

## 3. Results

Measured against real sky130 synthesis of a radix-2 divider — `latchup.app`'s
own sky130 fmax scoring, with entity hashes verified bit-identical to theirs —
and a held-out different design/language reference (`TARGET_33cycles_140mhz`).
The first subsection is the current calibration; the two after it are the
historical record it was built on.

### Matching latchup's early-flatten flow (2026-08-20)

latchup.app adopted an early synthesis flatten, invalidating the flow this
model had been calibrated against. Four fresh scored builds of the
*arithmetic* radix-2 divider were used as ground truth. Every one was rebuilt
locally with the same `--no_sweep --no_hier_syn` invocation and produced the
**same top entity hash** latchup's netlists carry
(`solution_16clk_48e99f0c`, `solution_32clk_42c98b59`, `solution_33clk_f2083cc2`,
`solution_64clk_17c0b934`), so the VHDL under test is identical to theirs and
every comparison below is apples-to-apples. Full record:
[`latchup_early_flatten_match_matrix.json`](../src/tests/pypeline_tests/qor/latchup_early_flatten_match_matrix.json).

**(a) STA engine alone, fed latchup's OWN mapped netlists** — isolates the
physics from any recipe question, the same methodology as the historical
9-netlist table below:

| netlists | MAE | worst |
|---|---|---|
| 4 post-early-flatten | **4.82%** | 6.35% |
| 3 pre-flatten (control) | 5.83% | 6.81% |

The engine is unaffected by their flatten change. On the 33- and 34-stage
designs it independently picks *the same critical path endpoints* latchup
reports, and an arc-by-arc diff of the 33-stage path shows 10 of its 11 arcs
agreeing to **within 8 ps** — including a 35-fanout `nand2_1` arc at 1.990 ns
against their 1.989 ns. The entire residual is one arc: the final
`mux2_1` `S→X`, where we compute 0.904 ns against their 1.132 ns at a 2.592 ns
input slew. This is *not* out-of-range extrapolation (that cell's slew axis
runs to 3.75 ns); reproducing their number would need a ~3.85 ns input
transition, i.e. their tool derives a larger transition out of the preceding
cell than we do while agreeing on its delay to 1 ps. Their implied setup is
also consistently ~1.5x ours. Both are conventions we cannot read off their
artifacts, so they are recorded here rather than fitted away.

**(b) Recipe selection, our own synthesis on the identical frozen VHDL**,
scored against latchup's reported period and mapped cell histogram:

| recipe | period MAE | worst | designs reproducing their histogram exactly |
|---|---|---|---|
| `current` | 24.52% | 39.32% | 0/4 |
| `synth_flatten` | 13.09% | 29.18% | 0/4 |
| `synth_flatten_noabc` | 12.61% | 34.72% | 3/4 |
| `early_flatten_opt` (was production) | 11.12% | 21.29% | 0/4 |
| **`early_flatten_noabc`** | **5.42%** | **6.52%** | **3/4** |

"Exactly" is literal: at 33 stages `early_flatten_noabc` maps to 13,873 cells
against their 13,873, matching all 19 cell types with zero difference in every
one. Its remaining error is (a)'s engine residual, not a mapping difference.
The 65-stage design is the one it does not reproduce (+1.4% cells, 7.0%
histogram distance, +5.04% period) — the likely cause is that latchup runs
**yosys 0.55** while this repo's oss-cad-suite is **0.48+51**, a difference no
repo change can close. `synth_flatten_noabc` is the cautionary result: exact on
the same three designs, then +34.72% on the fourth. Promotion bumped
`MODEL_VERSION` 3 → 4 and the whole shipped leaf cache was regenerated; 23 of
its 35 entries changed value, so no V3 number could have been carried over.

**The gate-level Divider variant is recipe-insensitive**, checked directly on
one frozen build: `early_flatten_opt` 207.74 MHz / 20,053 cells vs
`early_flatten_noabc` 207.84 MHz / 19,960 cells, identical DFF and `mux2_1`
counts. Expected — that design is already a flat netlist of single-gate
entities, so `synth`'s internal ABC pass has nothing structural left to do and
`-noabc` is a no-op for it. The promotion therefore does not move the gate
acceptance point in `divider_qor_acceptance.json`, which was taken under V3.

**Two divergences from latchup's flow that remain, both recorded not fixed:**
their yosys version as above, and their frontend path — they go VHDL → ghdl →
`write_verilog` (`rtl/PipelineC_inner.v`) → `read_verilog` → synth behind a
hand-written `rtl/Solution.v` wrapper, where PipelineC reads the VHDL directly
through the ghdl-yosys plugin.

**Planner follow-up, with this model frozen:** the arithmetic continuity work
did not edit `DEVICE_MODELS.py`, its coefficients, the liberty pack, recipe,
or model V4. It confirmed that the former 49-stage first guess maps to only
164.69 MHz between 169.57 MHz at 33 stages and 221.94 MHz at 65 stages.
Whole-design critical paths, not changes to this STA, led to the generic
chunked-MUX refinement now documented in
[`SYN_DESIGN.md`](SYN_DESIGN.md#budget-to-latency-continuity-result-2026-08-21):
a normal 180 MHz sweep returns 50 stages at 194.22 MHz and passes the exact
final-VHDL functional test. This is also direct evidence for the limitation
below: the isolated subtract boundary with the best modeled fmax became one
of the worst full-Divider schedules once flattened fanout was present.

The follow-up one-field-struct Divider check began with an empty cache and
reproduced the same 49-slice/50-stage, 194.2227 MHz result. Its typed 32-bit
MUX measurement populated `MUX_uint32_t.delay` plus the canonical timing
sidecar and no struct-named entry, while all 141 functional vectors passed.
That test validates cache/type canonicalization without changing the frozen
model.

### Historical calibration corpus (pre-early-flatten)

These tables were taken against latchup's *older* flow, on designs
historically labeled 1→128 cycles.

The `N` values in this historical calibration table are the source design's
cycle labels. They are retained as evidence metadata and must not be confused
with current compiler reporting, where `N` inserted slices means `N + 1`
combinational stages.

**Engine alone, fed real (not self-synthesized) netlists** — isolates the STA
physics from any synthesis-recipe question:

| | MAE across 9 real netlists | held-out `TARGET_33` |
|---|---|---|
| STA engine (sections a+b) | **4.66%** | **−0.4%** (was +35.4% under the prior fitted-linear model) |

**Historical calibrated `current` control, our own hash-verified builds** —
retained because it validates the original `-fast` calibration across the
external corpus. The production full-Divider result is reported above:

| historical source label N (cycles) | real (ns) | predicted (ns) | err% |
|---|---|---|---|
| 1 | 253.000 | 236.608 | −6.5% |
| 4 | 68.670 | 64.742 | −5.7% |
| 8 | 34.130 | 32.286 | −5.4% |
| 16 | 18.680 | 17.902 | −4.2% |
| 32 | 10.980 | 10.719 | −2.4% |
| 64 | 10.500 | 10.314 | −1.8% |
| 128 | 7.774 | 8.105 | +4.3% |

MAE 4.3%. The real sky130 curve is not smooth — 32→64 buys only 4% despite
doubling the registers, while every other doubling buys 40%+ — and this is
the shape that decides whether local rankings agree with real synthesis.
Predicted 32→64 gain: **3.8%**. Before the `-fast` fix (default abc script,
otherwise identical): MAE 37.5%, predicted 32→64 gain 35.7% — monotone, but
completely flat, no knee at all.

Real synthesis mapping was cross-checked independently of period: sequential
mapping (`dfflibmap`) matches exactly (4029/4029 flip-flops, one hash-verified
build), before the `-fast` fix was even found.

## 4. Verification

| check | what it proves |
|---|---|
| STA engine vs. 9 real `timing.log`s, netlists supplied (not self-synthesized) | the NLDM physics — unateness, clk→Q, setup, `max_capacitance` extrapolation — reproduce real numbers, isolated from any synthesis-recipe question |
| STA engine vs. 4 post-early-flatten + 3 pre-flatten `timing.log`s, netlists supplied | the physics is recipe-independent: MAE 4.82% after their flow change vs. 5.83% before it, and the same critical-path endpoints they report |
| Arc-by-arc diff of one shared critical path (33 stages) | agreement is per-cell-arc, not just in total: 10 of 11 arcs within 8 ps, so the residual is one identified convention difference, not distributed error |
| Our synth recipe vs. latchup's own mapped cell histogram, 4 hash-identical designs | mapping fidelity, not just number fidelity: exact on all 19 cell types on 3 of 4 designs (13,873/13,873 at 33 stages) |
| Our synth recipe vs. a real sky130 netlist's own FF count | sequential mapping fidelity (exact, 4029/4029) |
| Replay of all 4 shipped cache-source builds after a `MODEL_VERSION` bump | the regenerated leaf cache is complete: 100% cache hits, zero re-synthesis, exactly one sky130 cache directory |
| Per-stage bit-distribution readback (`*_registers.log`), all hash-verified builds | no zero-bit or degenerate pipeline splits silently wasting a stage |
| Whole-design STA, our own synthesis, all 7 stage counts | the end-to-end shape bar: monotone, saturating, real 32→64 knee reproduced |
| Real `pipelinec --syn_tool sky130` build, normal throughput sweep (not `--no_sweep`) | the full integration: per-leaf isolated synthesis, multimain confirmation, sweep convergence, all through the real CLI |
| `run_all` regression suite | PyRTL/default behavior is unaffected — every shared `SYN.py` function this feature touches (`PART_SET_TOOL`, `TOOL_DOES_PNR`, cache-dir keying, mux cache-key logic) still does exactly what it did before for every other tool |

## 5. Limitations and future work

- **Register overhead is modeled by STA but is not subtracted as one fixed
  planner-wide constant.** Full registered paths include measured clk->Q,
  combinational, and setup components in both text and JSON reports. The
  planner's initial global slice-count budget still uses the measured
  frontier total without a separate fixed overhead subtraction. A
  `GET_REGISTER_OVERHEAD_NS()` hook
  (subtracting `dfxtp_1`'s own clk->Q + `setup_rising` from the per-stage
  budget) was built and tried, but reverted: on the divider design it
  produced a sweep that no longer converged (a real planned-sweep run
  spiraled past 270+ slices without settling, where the unmodified
  planner reaches its answer in 4-6 iterations) — the tighter budget it
  imposes appears to interact badly with the sweep's own densify/trim
  heuristics rather than being a pure, harmless correction. Worth
  retrying if the interaction is ever root-caused, but not as a silent
  default.
- **A "bits"-kind raw HDL leaf's own delay is real and concave in width**
  (measured here: `D(10)=2.607ns`, `D(34)=3.851ns` for `BIN_OP_MINUS`, far
  from linear) but `RAW_VHDL.GET_BITS_PER_STAGE_DICT` does not try to fit or
  invert that curve to place *uneven* bit boundaries — an implementation
  that did was tried and found, by testing against real synthesis here, to
  measurably miss timing goals a plain **equal-width** split met (once a
  stage boundary is registered, that stage's own delay depends on its own
  chunk width, not on cumulative position along the leaf's *unregistered*
  delay axis — a cumulative-curve inversion models the wrong quantity). The
  concave shape above is still worth knowing as context for why splitting
  helps at all and why gains taper off with more stages; it just isn't
  something the bit-allocation decision needs to fit a curve to.
- **Packed-MUX bit chunking is now a default at plan-build time for wide
  banks, but the initial landscape stays atomic.** A 1-bit MUX select versus
  a 32-bit one carries different measured delay here (`MUX_uint1_t` 0.983 ns
  versus `MUX_uint32_t` 3.268 ns), and the raw generator can split the
  packed output bank for scalars and aggregates. The landscape's own
  fewest-stage geometry is preserved (chunking never changes cut count or
  latency), but a selected bank at least `SWEEP.DEFAULT_MUX_CHUNK_MIN_WIDTH`
  (32) bits wide is chunked unconditionally once selected — see the mux
  select-fanout cliff result below, where this alone was worth 105.95 ->
  292.48 MHz at an unchanged cut count. A narrower selected bank, or the
  still-unregistered terminal MUX, still only gets chunked after a
  whole-design miss (one bounded midpoint-chunk neighbor); isolated-leaf
  ranking did not predict full-design fanout QoR for those, hence the bound.
- **Mux select-fanout cliff (2026-08-25): a register on a short parallel
  branch can be free in depth but ruinous in fanout, and `--no_sweep`
  planned it anyway.** `SWEEP.GET_PIPELINE_MAP` schedules a shared
  downstream consumer by the *max* of its inputs' readiness, so a register
  on a branch shorter than an already-registered sibling adds zero pipeline
  depth — real hardware that materializes for nothing. Found on
  `soft_shift_rot`'s parallel `MUX_uint5_t_if_eff_amt` (select) /
  `MUX_uint64_t_if_w` (data) muxes under `--no_hier_syn --no_sweep`: the
  planned 7th cut reported `cuts=7, 6 slice(s) built` (the mismatch was the
  tell) and cost 4 design-wide max-capacitance violations for zero extra
  depth — 105.95 MHz measured versus 252.13 MHz for the otherwise-identical
  6-cut plan that omitted it. `SWEEP.DROP_NON_DEEPENING_PLACEMENTS` now
  drops any placement whose removal, alone, leaves the subtree's real
  post-lowering latency exactly where it started; this is the "never
  actually benefits from the whole-design physics during planning"
  limitation above turned fatal, not a new failure mode. See
  `docs/SYN_DESIGN.md`'s own dated result for the full measurement table.
- **`--no_hier_syn` sums isolated per-leaf delays, which runs high on a mux
  chain specifically.** On `soft_shift_rot`, `--no_hier_syn` reports 38.2 ns
  comb delay (`MUX_uint64_t` 5.363 ns/leaf) where hierarchical synthesis
  measures 15.2 ns (2.1 ns/leaf) — a ~2.5x floor-estimate inflation
  (192.3 MHz predicted vs. 483 MHz real), because cross-instance fanout
  sharing between the mux's own select and its neighbors is invisible to
  per-leaf isolated measurement (see the fanout-sharing bullet below). Not
  fixed here: `--no_hier_syn` is a deliberate flag choice, and the
  mismatched floor is just a misleading number, not a build failure.
- **No net/interconnect delay.** Matches the sky130 flows measured against
  (all report zero net delay), but is therefore a pre-PnR estimate, not a
  post-route number — say so plainly wherever this tool's output is surfaced.
- **Cross-instance fanout sharing is invisible to per-leaf isolated
  measurement**, by construction — the same limitation every existing
  `SYN_TOOL`'s leaf-delay collection has. The whole-design multimain path does
  see it (that's where the real cliff shows up), but the pipelining *planner*
  itself budgets from summed leaf delays, the same as it does for PyRTL — so
  a design planned under `--no_sweep` (no multimain confirmation at all, e.g.
  the exact mode `latchup.app` itself runs pipelining in) never actually
  benefits from the whole-design physics during planning, only during a real
  sweep's confirmation step.
- **One library/corner shipped** (`sky130_fd_sc_hvl`, `tt_025C_3v30`) — the
  only one any current ground truth can validate. The loader already takes
  `(library, corner)` as a parameter; adding another is a data-generation
  exercise, not a code change.
- **`-fast` was found empirically on one yosys version (0.48+51) against one
  design family.** It is not derived from first principles, and a different
  yosys/abc version could plausibly need a different flag. If this stops
  matching real sky130 results well on a different design, re-run the flag
  sweep documented in the project history before assuming the physics model
  itself regressed.
- **We are a yosys minor version behind the thing we model.** latchup runs
  yosys 0.55; this repo's oss-cad-suite is 0.48+51. On three of four
  hash-identical designs that costs nothing (exact cell-histogram match); on
  the fourth (65 stages) it is the leading explanation for a +1.4% cell /
  +5.04% period divergence. Not fixable by a repo change. Re-check the recipe
  matrix whenever the local toolchain is upgraded, because the selection was
  made on this pairing.
- **latchup's frontend has a Verilog round trip we do not.** They go VHDL →
  ghdl → `write_verilog` → `read_verilog` → synth behind a hand-written
  wrapper; PipelineC reads VHDL straight through the ghdl-yosys plugin. Not
  currently believed to matter (the histograms match), but it is a real
  structural difference between the two flows.
- **Setup/hold constraint table axis convention is standard but still not
  isolated.** The 2026-08-20 arc-by-arc comparison narrowed it usefully:
  against latchup, our setup term is consistently ~1.5x smaller (0.141 ns vs
  their implied 0.201 ns at 33 stages), and separately our final high-slew
  cell arc is smaller (0.904 ns vs 1.132 ns for a `mux2_1` `S→X` at 2.592 ns
  input slew — in range, not extrapolated). Reproducing their number requires
  a ~3.85 ns input transition, i.e. they derive a larger *transition* out of
  the preceding cell while agreeing with us on its *delay* to 1 ps. Both look
  like transition-propagation/setup conventions we cannot read off their
  artifacts, and neither was fitted away with a fudge factor. Together they
  are essentially the whole remaining ~5% engine error.

## 6. Area model

Added alongside the delay model above, sky130 only, following the same
measured-leaves/estimated-hierarchy shape as delay. See
`src/tests/pypeline_tests/qor/latchup_area_match_matrix.json` for the full
record this section summarizes.

### The measurement is definitional

latchup.app's own reported area is exactly `Σ liberty area:` over every cell
in its mapped netlist — regex-summed directly against their own `synth.v`
cell histograms (no PipelineC build on either side), 0.0001% MAE across all
four ground-truth designs. `DEVICE_MODELS.MEASURE_NETLIST_AREA` computes
precisely this over a mapped `write_json` netlist, splitting sequential
(`is_sequential` liberty cells, e.g. `dfxtp_1`) from combinational. It runs
as a free byproduct of `_run_synth_and_sta`'s existing mapped netlist — no
separate synthesis pass, no STA graph walk, since area does not propagate
through paths the way delay does.

`DEVICE_MODELS.LOAD_CELL_AREAS` parses the vendored raw `.lib`'s
unconditional per-cell `area:` attribute directly (57/57 cells), rather than
extending the condensed JSON pack: three committed QoR evidence matrices pin
that pack's sha256 as provenance, and area needs no NLDM table lookup, so
there was nothing to gain by disturbing it.

### Two numbers, two very different accuracies

**Measured area** (a real mapped netlist exists — mode 2's whole-design
confirmation synthesis, or mode 1's forced per-leaf remeasure, both below)
is highly accurate: **2.87% MAE** against latchup's real reported area, on
the two divider designs (16 and 32 slices) whose slice count this repo's
current `--no_sweep` planner still reproduces exactly from latchup's own
`solution.py` at latchup's own target MHz. This is in the same range as the
delay engine's own ~5% residual (§3 above) and for the same reason — a real
mapped netlist, summed exactly.

**Estimated area** (`SYN.ESTIMATE_DESIGN_AREA`: cached per-leaf areas summed
across the instance hierarchy, plus FF count × one flip-flop's real cell
area — no synthesis) overshoots real measured area by **270-410%** on every
design measured under `AREA_MODEL_VERSION` 1. Part of that number is now
understood to have been a measurement bug, not purely the
cross-instance-sharing limitation described below: an isolated leaf is wrapped in
`dont_touch` input/output registers (`VHDL.WRITE_LOGIC_TOP`) purely to give
it a register-to-register path for STA, and v1 cached `total_cell_area`,
which includes them. For a narrow leaf they dominate —
`BIN_OP_AND_uint16_t_uint16_t`'s v1-cached value was 91% harness flip-flop,
11.7x its real combinational area — and the fixed 464724.3 µm² combinational
estimate the matrix records for this divider (all four static leaf
entities, every design) is a v1 sum across exactly that kind of leaf. Fixed
in `AREA_MODEL_VERSION` 2 (below): `combinational_cell_area` is cached
instead of `total_cell_area`, which also fixes a matching double-count this
whole-design estimate itself had (summing sequential cells into a term it
calls "combinational", then adding its own FF term on top). The two 270-410%
matrix designs were not rebuilt under v2 — their source is latchup's own
`solution.py`, not committed to this repo — so a corrected number for those
specific four points is not available; `qor/latchup_area_match_matrix.json`'s
`area_model_version_2_correction` key has the full account, including two
in-repo builds that confirm the fix's real size (4.65% overshoot post-fix on
a design with no wide shared muxes, vs 342% still on one that has them) and
that the two limitations named below are unaffected by it. Both terms
overshoot, and the sequential one is worse:

| | combinational | sequential (FF count) |
|---|---|---|
| overshoot vs. measured | 2.7-3.6x | 5.7-5.9x |
| why | isolated per-leaf sum sees no cross-instance sharing — the SAME limitation already documented for isolated delay estimation on this exact design family (`--no_hier_syn` sums per-leaf delays ~2.5x high on a mux chain, §5 below) | `GET_REGISTERS_ESTIMATE_TEXT_AND_FFS` counts every declared pipeline-register bit before any of yosys's own FF-level optimization (constant/dead-bit elimination, retiming) — apparently a large majority of them, on this design |

Per-FF area is exact by construction on both sides (both reduce to
`GET_SEQUENTIAL_CELL_AREA`'s 48.84 µm² — see the matrix's own
`math.isclose` check), so the sequential term's entire error is in the FF
*count*, not the per-FF cost. **The cheap estimate is not a usable absolute
area predictor on a design with this much structural repetition** — the
radix-2 divider unrolls the same four operators (`BIN_OP_MINUS_uint34_t`,
`MUX_uint32_t`, `BIN_OP_NEQ`, `UNARY_OP_NOT`) once per bit — and should be
read as a same-design, same-direction relative signal only. This is
`SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS`'s whole-design estimate
specifically, not AUTOFSM's own register allocator (`ALLOCATE_REGISTERS`,
`docs/AUTOFSM_DESIGN.md` §3.2c) — a different and narrower count, tracking
genuinely live cross-state values rather than every declared bit. Whether
AUTOFSM's allocator has a comparable gap is checked directly (not assumed
either way) in `inst/autofsm_real_area_compare_test.py`, now that AUTOFSM
consumes this model (see the note at the end of this section).

### `--no_sweep` planner drift, found while calibrating (not an area bug)

The 2026-08-20 delay-recipe-selection entry above (§3) recorded all four
designs reproducing latchup's exact top-entity hash under
`--no_sweep --no_hier_syn`. Rebuilt one week later against the identical
`solution.py` sources (2026-08-27, commit `9fb4be5`), only the 16- and
32-slice designs still reproduce latchup's slice count; the two designs
latchup built at 33 and 64 slices now come out at 65 and 97 slices under the
current planner. This is drift in `--no_sweep`'s own pipelining guess since
2026-08-20 (see the recent "autopipeline sweep improvements" commits),
unrelated to the area model — recorded in the matrix's
`planner_drift_note` rather than silently worked around, and why only two of
the four designs carry a `measured_vs_latchup_error_pct` (the other two are
no longer the same design point latchup measured, so comparing their area to
`area.log` would be apples to oranges — their real measured area is still
recorded, just not scored against latchup's number).

### Leaf area cache — `area_cache/`, mirrors `path_delay_cache/`

Per-leaf area is measured and cached exactly like delay, in a **separately
versioned** tree so the two invalidate independently:

```
area_cache/device_models_<library>_<corner>_a<AREA_MODEL_VERSION><recipe_suffix>/syn/<leaf_key>.area
```

`AREA_MODEL_VERSION` (currently 2) is deliberately not `MODEL_VERSION`: leaf
area depends only on which cells the synthesis recipe maps to, not on
`run_sta()`'s own STA algorithm, so a future STA-only `MODEL_VERSION` bump
must not discard an otherwise-valid committed `area_cache`, and vice versa.
`SYN.GET_AREA_CACHE_DIR` mirrors `GET_PATH_DELAY_CACHE_DIR` exactly (same
`PYPELINEC_AREA_CACHE_DIR` env override pattern, same recipe suffix, `None`
for every `SYN_TOOL` but `DEVICE_MODELS`). Cache files hold the value *and
its unit* as text (`"255886.4 um2"`), not a bare number — deliberately,
since a future non-sky130 profile would use a different unit and a silent
mismatch would be far worse than a cache miss; `SYN.GET_CACHED_LEAF_AREA`
rejects a stored unit that disagrees with the active model's own unit rather
than mixing it in.

**1 → 2:** v1 cached `total_cell_area`, which includes the `dont_touch`
STA-harness registers every isolated leaf is synthesized with
(`VHDL.WRITE_LOGIC_TOP`) — 91% of a narrow leaf's v1-cached value, on the
`BIN_OP_AND_uint16_t_uint16_t` example above. v2 caches
`combinational_cell_area` instead (same `MEASURE_NETLIST_AREA` call, already
split by each cell's own `is_sequential` flag — no new measurement). Found
and fixed while wiring this cache into AUTOFSM's area-search ranking (see
the note at the end of this section); the bump means every v1 `.area` file
is superseded, not reinterpreted, since the two numbers differ by however
many harness bits that leaf's own ports carried.

**Two operating modes**, both real and both exercised by
`area_estimate_build_report_test`:

1. **latchup.app's own usage** (`--no_hier_syn --no_sweep`): every leaf
   either hits a warm `area_cache` entry, or — when its `.delay` is cached
   but its `.area` is missing — `ADD_PATH_DELAY_TO_LOOKUP` forces one real
   synthesis to fill both, mirroring the existing clause that does the same
   for a missing combinational-planner-weights sidecar. The hierarchy above
   the leaves is always the cheap estimate; no whole-design synthesis
   happens under `--no_sweep`.
2. **Normal use** (a real confirmation or throughput-sweep synthesis runs):
   the exact measured area comes free from that run's own mapped netlist,
   reported alongside the estimate with their delta.

Both print at the same call sites `WRITE_REGISTERS_ESTIMATE_FILE` already
uses, and write a `<top><hash>_area.json` sidecar next to
`<top><hash>_registers.log`:

```
Estimated area: 83788.0 um2 (comb 53311.8 + regs 30476.2, 624 FFs) [estimate, pre-PnR]
Measured area: 6812.2 um2 (estimate +61.40%)
```

The `area_cache/` tree ships pre-populated (18 leaf keys as of
`AREA_MODEL_VERSION` 2 — every leaf a sky130 `build_report`/`synth` test in
this repo's own registered suite happens to touch while running, not a
deliberately curated set; see `git log` for the generating builds), and
`nix/package.nix` copies it out of the read-only store into
`.pypelinec_area_cache/` + exports `PYPELINEC_AREA_CACHE_DIR`, mirroring
`path_delay_cache`'s existing treatment exactly.

**Consumed by AUTOFSM's minimum-area search.** Under `--syn_tool sky130`,
`AUTOFSM.py`'s ranking (`docs/AUTOFSM_DESIGN.md` §3.8) uses real cached
leaf/register/multiplexer µm² from this cache wherever a measurement exists,
falling back to its own abstract per-bit model (scaled into µm² by a
constant refit from this cache, `AUTOFSM.UM2_PER_ABSTRACT_AREA_UNIT`) only
where one does not — `--autofsm_abstract_area` forces the old abstract-only
ranking for comparison. Every non-sky130 tool is unaffected: the abstract
model is still the only signal there, unchanged. Real measurement confirmed
most of the abstract model's combinational ratios to within ~30% (AND/XOR/
mux bits) and found one large, genuine error (the flip-flop term, 2.5x too
cheap, calibrated for an FPGA where a flip-flop pairs with its LUT) — but it
does not fix the two limitations two paragraphs above (cross-instance
sharing, the FF-count estimator's own overshoot), since neither is a per-leaf
measurement problem. See `docs/AUTOFSM_DESIGN.md` §3.8 for the full account
and `inst/autofsm_real_area_compare_test.py` for the real-synthesis check.
