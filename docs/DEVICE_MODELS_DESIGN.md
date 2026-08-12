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

The synth recipe, once per whole-design confirmation or per isolated leaf
entity:

```
ghdl --std=08 <files> -e <top>;
synth -top <top>;                        # no -flatten: real sky130 flows don't either
dfflibmap -liberty <lib>;
abc -liberty <lib> -fast;                # see "the -fast finding" below
flatten;                                 # purely structural, AFTER abc --
write_json <out>.json                    #   connects the STA graph without
                                          #   changing which gates abc chose
```

`run_sta` then runs directly in-process — no second Python subprocess, unlike
PyRTL's flow which shells out to run its own generated script.

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

### Cache-key versioning

`SYN.GET_PATH_DELAY_CACHE_DIR` appends library + corner + `DEVICE_MODELS.MODEL_VERSION`
for this tool, the same way PyRTL appends `_<TECH>nm_<FF>ff`. Bump
`MODEL_VERSION` on any change to `run_sta`'s algorithm or `ABC_EXTRA_ARGS` that
could change a previously-cached leaf delay's value — otherwise a model
change could silently replay a stale pre-change number.

## 3. Results

Measured against real sky130 synthesis of a radix-2 divider (`latchup.app`'s
own sky130 fmax scoring, 1→128 pipeline stages, entity hashes verified
bit-identical to theirs) and a held-out different design/language reference
(`TARGET_33cycles_140mhz`).

**Engine alone, fed real (not self-synthesized) netlists** — isolates the STA
physics from any synthesis-recipe question:

| | MAE across 9 real netlists | held-out `TARGET_33` |
|---|---|---|
| STA engine (sections a+b) | **4.66%** | **−0.4%** (was +35.4% under the prior fitted-linear model) |

**End to end, real shipped recipe, our own hash-verified builds** — the
harder test, since it includes our own local synthesis, not a given netlist:

| N (stages) | real (ns) | predicted (ns) | err% |
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
| Our synth recipe vs. a real sky130 netlist's own FF count | sequential mapping fidelity (exact, 4029/4029) |
| Per-stage bit-distribution readback (`*_registers.log`), all hash-verified builds | no zero-bit or degenerate pipeline splits silently wasting a stage |
| Whole-design STA, our own synthesis, all 7 stage counts | the end-to-end shape bar: monotone, saturating, real 32→64 knee reproduced |
| Real `pipelinec --syn_tool sky130` build, normal throughput sweep (not `--no_sweep`) | the full integration: per-leaf isolated synthesis, multimain confirmation, sweep convergence, all through the real CLI |
| `run_all` regression suite | PyRTL/default behavior is unaffected — every shared `SYN.py` function this feature touches (`PART_SET_TOOL`, `TOOL_DOES_PNR`, cache-dir keying, mux cache-key logic) still does exactly what it did before for every other tool |

## 5. Limitations and future work

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
- **Setup/hold constraint table axis convention is standard but unverified in
  isolation** — the shape and total-period results validate it in aggregate,
  but no test isolates the setup term the way the cliff cells isolate the
  load-extrapolation term.
