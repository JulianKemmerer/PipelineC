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

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section rather
> than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

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
property is what let the engine be validated (§3) before any compiler wiring
existed at all.

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

This is recipe `early_flatten_noabc` — chosen because it reproduces
latchup.app's own post-early-flatten netlists; see §3.

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

The no-early-flatten flow remains available as the `current` **control
recipe**. The opt-in synthesis-recipe matrix also has fixed internal variants
for `synth -flatten`, flattening with `-noabc` before the single liberty ABC
pass, and the `early_flatten_opt` sequence (production under `MODEL_VERSION`
3, before it was superseded — see History). Each variant has a distinct
artifact and cache identity. There is no public arbitrary-flags interface.

The closed recipe IDs are `current`, `synth_flatten`, `synth_flatten_noabc`,
`early_flatten_opt`, and the production `early_flatten_noabc`, selected only
by the opt-in benchmark's internal `PIPELINEC_INTERNAL_SKY130_RECIPE`
environment variable. The production identity has no recipe suffix. Every
non-production mapped netlist, script, log, leaf-delay cache, and
minimum-period cache carries a versioned `__recipe_<id>_v1` suffix, including
the `current` control.

**The empty-suffix rule makes a `MODEL_VERSION` bump mandatory on every
promotion.** Because the default recipe is exactly the one whose cache
identity has no suffix, promoting a different recipe without bumping the
version would leave the identity string unchanged and silently replay the
*previous* recipe's leaf delays out of the same directory. The current
production model is `MODEL_VERSION` 4, recipe `early_flatten_noabc` — see
History for why it replaced the recipe before it.

**Per-leaf isolation (an architectural limit, not a bug).** Like every
existing `SYN_TOOL`, a leaf-entity `SYN_AND_REPORT_TIMING` call synthesizes
*only* that one leaf in complete isolation, so its measured delay can never
see fanout from a sibling instance elsewhere in the design. Only the
whole-design multimain path ever sees more than one leaf's logic at once.
Real cross-instance net sharing can only be captured by that whole-design
path — see §5.

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

`-fast` remains part of the production recipe (it reproduces latchup's
current netlists exactly), but "`mux2_1` usage goes to exactly zero" is not a
property of the flag — it was a property of latchup's pre-flatten flow
specifically. Their post-early-flatten netlists contain 838 `mux2_1` at 33
stages and 745 at 65, and `-fast` under the current recipe reproduces those
counts exactly too. Mux inference is a property of the network abc is
handed, not of `-fast` in isolation; treat cell-histogram match against a
real target netlist as the signature to match, not any one cell count.

### Mux path-delay cache key

`SYN.GET_CACHED_LOGIC_FILE_KEY` special-cases mux delay. Collapsed mode
(every mux width/type sharing one cache key, `"mux"`) is right for PyRTL,
whose own measurement is provably width-blind (1.640ns at every width 1..64,
measured with the cache deleted); a real per-cell model doesn't share that
property — a 32-bit mux's select really does drive 32 sinks inside its own
entity, so it measures slower than a 2-bit one even in complete per-leaf
isolation.

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

## 3. Results

Measured against real sky130 synthesis of a radix-2 divider — `latchup.app`'s
own sky130 fmax scoring, with entity hashes verified bit-identical to theirs
on 4 fresh scored builds (rebuilt locally under `--no_sweep --no_hier_syn`,
same top-entity hash as latchup's own netlists: `solution_16clk_48e99f0c`,
`solution_32clk_42c98b59`, `solution_33clk_f2083cc2`,
`solution_64clk_17c0b934`) — and a held-out different design/language
reference (`TARGET_33cycles_140mhz`). Full record:
[`latchup_early_flatten_match_matrix.json`](../src/tests/pypeline_tests/qor/latchup_early_flatten_match_matrix.json).

**STA engine accuracy, fed real (not self-synthesized) netlists** — isolates
the physics from any synthesis-recipe question. Across a broader,
recipe-independent corpus of 9 real sky130 netlists, MAE is 4.66% with the
held-out design at −0.4%; the same engine also reproduces the real,
non-linear sky130 delay-vs-register-count curve (e.g. only a 3.8% predicted
fmax gain from 32→64 pipeline registers on the divider, where every other
stage-count doubling gains 40%+ — a shape a naive linear model cannot
produce). On latchup's 4 post-early-flatten netlists specifically, MAE is
4.82% (worst 6.35%), and on a shared 33-stage critical path 10 of its 11 arcs
agree with latchup's own reported delays to within 8 ps, including a
35-fanout `nand2_1` arc at 1.990 ns against their 1.989 ns. The entire
residual concentrates in one arc, the final `mux2_1` `S→X` (0.904 ns here vs.
their 1.132 ns, at a 2.592 ns input slew well inside that cell's
characterized range) — see §5 for why this is read as an unrecoverable
convention difference rather than a modeling gap.

**Recipe/mapping fidelity, our own synthesis of the identical frozen VHDL**,
scored against latchup's reported period and mapped cell histogram: period
MAE is 5.42% (worst 6.52%), and 3 of the 4 hash-identical designs match
latchup's own cell histogram exactly across all 19 cell types — 13,873/13,873
cells at 33 stages, zero difference in any type. The 65-stage design is the
one that doesn't reproduce (+1.4% cells, +5.04% period); see §5 for the
likely cause (a yosys version gap between this repo's toolchain and
latchup's).

**The gate-level Divider variant is recipe-insensitive**: already a flat
netlist of single-gate entities, so ABC's own structural mapping choice
barely matters (`early_flatten_opt` 207.74 MHz / 20,053 cells vs.
`early_flatten_noabc` 207.84 MHz / 19,960 cells, identical DFF and `mux2_1`
counts).

**The carry-save multiplier improvement did not tune this model.** With
`MODEL_VERSION = 4`, `early_flatten_noabc`, the liberty data, and all timing
coefficients held byte-identical, the latchup-style
`--no_sweep --no_hier_syn` candidate remains 700.640825 MHz at 31 stages for
a 700 MHz request and reaches 909.794952 MHz at 60 stages for a 701 MHz
request (the 720/905 MHz probes produce a 61-stage candidate at the same
measured fmax). That 29.852% gain is attributable to planner/RAW-VHDL
structure, not a different STA calibration; the full mechanism and evidence
are recorded in [`SYN_DESIGN.md`](SYN_DESIGN.md)'s History section.

The combined gate and arithmetic acceptance record — the actual divider build
this model's own recipe and STA feed into — is tracked from
[`pypeline_TESTS.md`](pypeline_TESTS.md#related); the pipeline-depth-scheduling
decisions this results section motivated are in
[`SYN_DESIGN.md`](SYN_DESIGN.md)'s History section.

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
| Carry-save multiplier, latchup-style first candidate at 31 and 60/61 stages | planner/RAW-VHDL structure raises fmax 700.640825→909.794952 MHz while model V4, recipe, liberty, and coefficients remain unchanged |
| `run_all` regression suite | PyRTL/default behavior is unaffected — every shared `SYN.py` function this feature touches (`PART_SET_TOOL`, `TOOL_DOES_PNR`, cache-dir keying, mux cache-key logic) still does exactly what it did before for every other tool |

## 5. Limitations and future work

- **Component-aware register overhead is gated on complete evidence.** Full
  registered paths report measured clk-to-Q, combinational, and setup fields
  in both text and JSON. When every active landscape segment has those fields,
  the planner normalizes relative weights to the measured combinational root,
  subtracts one root launch-plus-setup cost from each proposed stage's period,
  and adds that cost back once in the predicted stage delay. Incomplete
  sidecar coverage falls back to the legacy full register-to-register weights
  for the entire landscape rather than mixing cost conventions. This is not
  the rejected fixed planner-wide subtraction: the old
  `GET_REGISTER_OVERHEAD_NS()` hook used one `dfxtp_1` clk-to-Q plus setup
  constant regardless of path evidence. It was tried and reverted because a
  Divider sweep spiraled past 270 slices instead of converging in 4-6
  iterations. The remaining limitation is coverage: a newly measured backend
  without complete component sidecars retains legacy over-prediction until
  those fields are available.
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
  (32) bits wide is chunked unconditionally once selected. A narrower
  selected bank, or the still-unregistered terminal MUX, still only gets
  chunked after a whole-design miss (one bounded midpoint-chunk neighbor);
  isolated-leaf ranking did not predict full-design fanout QoR for those,
  hence the bound.
- **Mux select-fanout cliff.** A register on a short parallel branch can be
  free in pipeline depth but ruinous in fanout, and planning did not always
  catch it — the fix (`SWEEP.DROP_NON_DEEPENING_PLACEMENTS`) and the
  measured cliff it closes live in [`SYN_DESIGN.md`](SYN_DESIGN.md)'s
  History section, since the fix itself is in the planner, not this model.
- **`--no_hier_syn` sums isolated per-leaf delays, which runs high on a mux
  chain specifically.** On `soft_shift_rot`, `--no_hier_syn` reports 38.2 ns
  comb delay (`MUX_uint64_t` 5.363 ns/leaf) where hierarchical synthesis
  measures 15.2 ns (2.1 ns/leaf) — a ~2.5x floor-estimate inflation
  (192.3 MHz predicted vs. 483 MHz real), because cross-instance fanout
  sharing between the mux's own select and its neighbors is invisible to
  per-leaf isolated measurement (see the fanout-sharing bullet below). Not
  fixed here: `--no_hier_syn` is a deliberate flag choice, and the
  mismatched floor is just a misleading number, not a build failure.
- **`--no_sweep`'s own pipelining guess has drifted from a past calibration
  point.** Two of the four latchup-matched designs (§3) no longer reproduce
  latchup's slice count under the current planner: designs latchup built at
  33 and 64 slices now come out at 65 and 97 slices under
  `--no_sweep --no_hier_syn`, rebuilt from the identical `solution.py`
  sources at commit `9fb4be5`. This drift is in the planner's own
  pipelining guess, unrelated to this file's delay/area model — recorded
  rather than silently worked around
  (`latchup_area_match_matrix.json`'s `planner_drift_note`); only the two
  designs that still reproduce latchup's slice count carry a scored area
  comparison, since comparing area at a different slice count than latchup
  measured would be apples to oranges.
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
  matching real sky130 results well on a different design, re-run the same
  methodology (§2, "The -fast finding") before assuming the physics model
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
- **Setup/hold constraint conventions are not fully isolated.** Our setup
  term and final high-slew cell-arc delay are both consistently smaller than
  latchup's implied numbers (§3) — read as differences in how their tool
  derives transition/setup conventions that cannot be recovered from their
  published artifacts, not fitted away with a fudge factor. Together these
  account for essentially all of the remaining ~5% engine error.

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
delay engine's own ~5% residual (§3) and for the same reason — a real
mapped netlist, summed exactly.

**Estimated area** (`SYN.ESTIMATE_DESIGN_AREA`: cached per-leaf areas summed
across the instance hierarchy, plus FF count × one flip-flop's real cell
area — no synthesis) overshoots real measured area, and by how much depends
heavily on structural sharing an isolated per-leaf sum cannot see: on two
in-repo designs rebuilt under the current (v2) model, overshoot is 4.65% on
a design with no wide shared muxes, versus 342% on one that has them — the
same cross-instance-sharing limitation the delay estimate already has
(`--no_hier_syn` sums per-leaf delays ~2.5x high on a mux chain, §5). The
sequential (FF-count) term overshoots worse than the combinational term
specifically because `GET_REGISTERS_ESTIMATE_TEXT_AND_FFS` counts every
declared pipeline-register bit before any of yosys's own FF-level
optimization (constant/dead-bit elimination, retiming) — apparently a large
majority of them, on designs with heavy structural repetition. Per-FF area
is exact by construction on both sides (both reduce to
`GET_SEQUENTIAL_CELL_AREA`'s 48.84 µm² — see the matrix's own
`math.isclose` check), so the sequential term's entire error is in the FF
*count*, not the per-FF cost.

**The cheap estimate is not a usable absolute area predictor on a design
with this much structural repetition** — the radix-2 divider unrolls the
same four operators (`BIN_OP_MINUS_uint34_t`, `MUX_uint32_t`, `BIN_OP_NEQ`,
`UNARY_OP_NOT`) once per bit — and should be read as a same-design,
same-direction relative signal only. This is
`SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS`'s whole-design estimate
specifically, not AUTOFSM's own register allocator (`ALLOCATE_REGISTERS`,
`docs/AUTOFSM_DESIGN.md` §3.2c) — a different and narrower count, tracking
genuinely live cross-state values rather than every declared bit. Whether
AUTOFSM's allocator has a comparable gap is checked directly (not assumed
either way) in `inst/autofsm_real_area_compare_test.py`, now that AUTOFSM
consumes this model (see the note at the end of this section). See History
for why the model landed on these v2 numbers rather than the much larger
ones an early version reported.

### Leaf area cache — `area_cache/`, mirrors `path_delay_cache/`

Per-leaf area is measured and cached exactly like delay, in a **separately
versioned** tree so the two invalidate independently:

```
area_cache/device_models_<library>_<corner>_a<AREA_MODEL_VERSION><recipe_suffix>/syn/<leaf_key>.area
```

`AREA_MODEL_VERSION` (currently 2; see History for why it was bumped from 1)
is deliberately not `MODEL_VERSION`: leaf area depends only on which cells
the synthesis recipe maps to, not on `run_sta()`'s own STA algorithm, so a
future STA-only `MODEL_VERSION` bump must not discard an otherwise-valid
committed `area_cache`, and vice versa. `SYN.GET_AREA_CACHE_DIR` mirrors
`GET_PATH_DELAY_CACHE_DIR` exactly (same `PYPELINEC_AREA_CACHE_DIR` env
override pattern, same recipe suffix, `None` for every `SYN_TOOL` but
`DEVICE_MODELS`). Cache files hold the value *and its unit* as text
(`"255886.4 um2"`), not a bare number — deliberately, since a future
non-sky130 profile would use a different unit and a silent mismatch would be
far worse than a cache miss; `SYN.GET_CACHED_LEAF_AREA` rejects a stored
unit that disagrees with the active model's own unit rather than mixing it
in.

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

The `area_cache/` tree ships pre-populated (18 leaf keys at the current
`AREA_MODEL_VERSION` — every leaf a sky130 `build_report`/`synth` test in
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

## History

Why things are the way they are. Entries are keyed by **topic, not date** —
when something changes, revise the entry that owns that topic rather than
adding a new one. Keep a fact here only if it still changes a decision
today: an alternative someone would otherwise retry, a measurement that is
still a live regression reference, or the reason a default is what it is.
Numbers carry the conditions they were measured under, not the date they
were taken.

### Delay-recipe selection: early flattening, and matching latchup exactly

ABC seeing pre-flatten hierarchy creates a fanout cliff at a pre-loop
compare/select cone (measured directly: a 4.325 ns fanout-64 NAND3 arc
violating `max_capacitance`, on the unchanged gate-Divider fixture at clean
commit `c81ca31f`) — both an isolated-step screen
([`synthesis_recipe_step_gates_matrix.json`](../src/tests/pypeline_tests/qor/synthesis_recipe_step_gates_matrix.json))
and a controlled cone matrix
([`synthesis_recipe_pre_divzero_matrix.json`](../src/tests/pypeline_tests/qor/synthesis_recipe_pre_divzero_matrix.json),
reproducing just the pre-step divisor-nonzero compare/select via
[`synthesis_recipe_pre_divzero_wrapper.vhd`](../src/tests/pypeline_tests/qor/synthesis_recipe_pre_divzero_wrapper.vhd))
confirmed early flattening (before the single liberty ABC pass, §2) removes
it, at a cost of no functional difference on 141 ordered test vectors.
`early_flatten_opt` was promoted first (`MODEL_VERSION` 3), selected by
maximizing this repo's *own* fmax at equal latency (39.3% smaller than the
un-flattened control, at roughly the control's own runtime).

That selection policy turned out to be the wrong objective: this model's job
is to predict what latchup will report, not to maximize our own fmax.
Re-scored directly against latchup's own reported netlists and cell
histograms, `early_flatten_opt` was only the 4th-best of 5 recipes by that
metric (11.12% period MAE, 0/4 designs matching latchup's cell histogram
exactly). The runner-up, `synth_flatten_noabc`, is the cautionary case for
scoring on mean error alone: 12.61% MAE looks close to the eventual winner,
and it reproduces latchup's cell histogram exactly on 3 of 4 designs — the
same three the winner matches — but its 4th design misses by **34.72%**,
nearly 3x its own mean. `early_flatten_noabc` (skip ABC's own structural
mapping entirely, leaving all of it to the single liberty pass) is both
closer on average and far more even — 5.42% MAE, worst case 6.52%, 3 of 4
hash-identical designs matching every one of 19 cell types exactly.
Promoted to `MODEL_VERSION` 4; the whole shipped leaf cache was
regenerated, and 23 of its 35 entries changed value versus V3.

The remaining ~5% gap under V4 concentrates almost entirely in two
identified, unrecoverable conventions rather than distributed error: our
final `mux2_1` `S→X` arc measures smaller than latchup's on one shared
critical path (0.904 ns vs. 1.132 ns, both in-range — reproducing their
number would need a ~3.85 ns input transition on that arc even though the
preceding cell's *delay* already agrees with theirs to 1 ps), and our setup
term is consistently ~1.5x smaller (0.141 ns vs. their implied 0.201 ns at
33 stages). Both read as transition-propagation/setup conventions in
latchup's own tool that cannot be read off their published artifacts, and
neither was fitted away with a fudge factor.

### Area model V1 → V2

V1 cached `total_cell_area` for each leaf, which includes the `dont_touch`
input/output registers every isolated leaf is synthesized with
(`VHDL.WRITE_LOGIC_TOP`, purely to give the leaf a register-to-register path
for STA) — on one measured narrow leaf
(`BIN_OP_AND_uint16_t_uint16_t`), those harness registers were 91% of the
cached value, 11.7x the leaf's real combinational area, and the whole-design
*estimate* built on top of such leaves separately double-counted (summing
sequential cells into a term it called "combinational", then adding its own
FF term on top). V2 caches `combinational_cell_area` instead — the same
`MEASURE_NETLIST_AREA` call, already split by each cell's own
`is_sequential` flag, so no new measurement was needed — and fixes the
double-count at the same time. Found while wiring the leaf-area cache into
AUTOFSM's area-search ranking. The two designs originally measured at
270-410% overshoot under V1 were never rebuilt under V2 (their source is
latchup's own `solution.py`, not committed to this repo), so no corrected
number exists for those specific points; current V2 accuracy is
characterized instead by two in-repo designs (§6, "Two numbers, two very
different accuracies").