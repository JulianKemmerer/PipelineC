# Autopipelining and the Throughput Sweep

How PypelineC turns combinational logic into pipelines to meet an fmax goal,
and how the *planned throughput sweep* replaced the old "middle out" sweep.

## 0. Who does what

| file | role |
|---|---|
| `src/SYN.py` | The infrastructure that already existed and remains: timing params (`TimingParams`, slices, IO regs), the pipeline map (`GET_PIPELINE_MAP`), recursive slicing (`SLICE_DOWN_HIERARCHY_...`), per-function path delay collection (`ADD_PATH_DELAY_TO_LOOKUP`), the coarse sweep engine (`DO_COARSE_THROUGHPUT_SWEEP`, kept for `--coarse` and mini-sweeps), entity writing, and the `DO_THROUGHPUT_SWEEP` entry point. |
| `src/SWEEP.py` | New. The *brains* of autopipelining: cut subtrees, slice landscapes, floor prediction, cut planning, and the synthesis-feedback refinement loop (`DO_PLANNED_THROUGHPUT_SWEEP`). Replaces the old middle-out sweep that lived in SYN.py. |
| `src/PYRTL.py`, `src/DEVICE_MODELS.py` | The `SYN_TOOL` backends this document's delay model and sweep are built on top of — see [`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md) for the real sky130 liberty STA backend (`PART("sky130...")` / `--syn_tool sky130`) and why it exists (PyRTL's own cost model has no fanout/load term at all). |

Vocabulary used throughout (each defined in detail later):

| term | one-liner |
|---|---|
| **slice** | one serial register boundary inserted by pipelining; it is represented either by a raw-leaf-local fraction in `TimingParams._slices` or by an operation instance's input/output-register flag |
| **cut** | a requested stage boundary on a whole *cut subtree*'s delay axis; typed planning resolves it to one or more concrete physical placements |
| **cut subtree** | the largest subtree registers may be added to (a comb MAIN, or each AUTOPIPELINE-tagged region) |
| **landscape** | the flattened delay axis of one cut subtree: where every nanosecond of logic lives and whether a cut may land there |
| **segment** | one leaf-most piece of that axis (sliceable / atomic / locked) |
| **placement** | one typed physical register location: an operation-instance input/output boundary or a genuine bit-internal leaf cut; `fixed` placements are retained by controlled internal experiments |
| **floor** | the fmax that no amount of added registers can beat (longest un-cuttable stretch) |
| **plan** | per-MAIN sweep state: cut subtrees, landscapes, cuts, learned scale factors, locks |
| **measurement frontier** | the topmost fully-combinational funcs — the only hierarchical modules ever synthesized per-module; their measured through-delays calibrate the estimates of everything above (and thus how many cuts the first plan gets) |
| **lock** | a mini-sweep result whose internal slices are frozen onto all instances of a func (`params_are_fixed`); optional input/output banks are selected from parent dataflow rather than assumed per instance |
| **trim** | post-met iterations that retry with fewer cuts to prove the stage count is minimal |

## 1. Old vs new, in one table

| | old middle-out sweep | new planned sweep |
|---|---|---|
| where do registers go? | evenly spaced "best guess" slices over the whole delay, count grown by a multiplier when timing failed | cuts placed by a static delay model (the *landscape*) that knows where delay lives and where cuts are legal |
| how many stages? | however many the growing multiplier reached when timing first passed | fewest-stages first: budgets calibrated by the *measurement frontier* (topmost fully-comb funcs, measured) start at the theoretical minimum (usually just missing timing) and stages are added only from synthesis feedback; met-with-slack results get trimmed (`--pipeline_min_effort`) |
| how many syn runs? | every hierarchy level synthesized up front, including MAINs + a full-design run per guess + per-module coarse sweeps when guesses plateaued (wireguard: ~16 full runs) | leaf functions + the measurement frontier (topmost fully-comb funcs) + topmost untagged stateful modules (everything else estimated — never MAINs, never anything with state inside) + one full-design run per iteration, max 12 (+ trim/probe runs) |
| unmet timing at the end | exit 0, results written, sim runs — silent | results written for debugging, then `ERROR: TIMING NOT MET` block + **non-zero exit**; sim/bitstream skipped |
| reaction to failing timing | grow `best_guess_sweep_mult`, or step `hier_sweep_mult` down the hierarchy and coarse-sweep smaller modules (4 interacting multipliers) | escalation ladder: densify the attributed hotspot once → after a second attribution, measure and mini-sweep that helper in isolation, then lock its proven-minimal nonzero split; measure remaining estimates if feedback still stagnates; global rescale when attribution is impossible |
| unreachable goals | plateaued for many runs, then gave up | fmax *floor* predicted and blamed before any syn run; sweep stops at the floor |
| slices vs latency | conflated in logs ("0 clks 53 slices") | reported separately: `cuts=N main_latency=M pipeline_stages=D` |
| pipeline depth | only the top module's own latency (0 for a stream) | a `Pipeline depth summary` at *Writing Results* totals every slice built, including inside decoupled sub-pipelines |
| state | `SweepState` + 4 multipliers, pickled `.sweep` resume files | `MainSweepPlan` per main; no resume (syn log caching already makes re-runs cheap); history written to `sweep_history.json` |

## 2. How pipelines physically form

Registers physically exist in two forms:

1. **Leaf slices** — a raw HDL leaf (no submodules, e.g. `BIN_OP_PLUS`) with
   `TimingParams._slices = [0.5]` becomes a 2-stage adder, carry chain broken
   at 50% of its delay (a slice value is a fraction 0.0–1.0 of that module's
   *own* delay, but see below — what that fraction turns into differs by leaf
   kind). Leaf latency = `len(_slices)`:

   ```
   4 ns ADD, _slices = [0.5]:
   in --[ low 2 ns of carry chain ]--REG--[ high 2 ns ]-- out   (1 clk latency)
   ```

   `RAW_VHDL.GET_LEAF_SPLIT_KIND` puts every raw HDL leaf into one of four
   kinds, which each generator's own code (not the sweep/landscape layer)
   decides how to honor:
   - `SPLIT_KIND_BITS` (PLUS/MINUS/EQ/NEQ/GT/GTE/LT/LTE/accum): the operand
     bit range is what gets split. `RAW_VHDL.GET_BITS_PER_STAGE_DICT` divides
     the width as **evenly as possible across the requested chunk COUNT**
     (`len(_slices) + 1` stages). Compatibility/coarse fractional requests
     therefore set the count rather than arbitrary bit boundaries. Typed
     bit placements normally carry the canonical equal-width boundary,
     ordinal, and count all the way through lowering, so the trace describes
     the exact emitted split. Typed `exact` placements may instead carry a
     strictly increasing integer boundary group; that group is validated,
     hashed, and emitted without changing the compatibility path. The normal
     equal-width conversion looks like it throws away
     information, but it doesn't: once a boundary is registered, each stage
     computes its own chunk from scratch off a registered 1-bit carry-in, so
     that stage's delay depends only on its own chunk width, not on where
     along the leaf's *unregistered* delay axis the cut nominally sits. Since
     real per-width delay is monotonic (and concave — sky130 measured
     `D(10)=2.607ns`, `D(34)=3.851ns` for a 34-bit `MINUS`, nowhere near
     linear), minimizing the worst stage's delay for a given stage count
     means equal-width chunks, full stop — an earlier version of this fix
     instead inverted a delay-fraction curve to place *uneven* boundaries,
     which measurably missed real sky130 timing goals that the plain
     equal-width split (and even the original linear-fraction model) met.

     **Current-model exact-boundary result (2026-08-21).** All subtract
     boundaries 1..33 were mapped in isolation under unchanged model V4.
     Bit 24 was best in isolation (345.96 MHz versus 314.96 MHz at the equal
     bit-17 split), but the full 49-stage Divider became much worse at
     144.43 MHz; bits 28 and 33 reached only 152.06 and 162.99 MHz. The bit-24
     full path contained a 64-fanout NOR and a 3.92 ns max-capacitance
     violation. Local leaf optimality therefore did not predict flattened
     whole-design QoR, and exact subtract boundaries were retained as an
     internal mechanism rather than made the ordinary allocation policy.
   - `SPLIT_KIND_MUX_BITS` (every built-in MUX): the initial landscape deliberately
     exposes only the normal operation-output boundary. A typed physical
     placement may split the packed output bits, however, making each stage's
     select drive only that chunk. Aggregate data uses the generated
     `c_structs_pkg` SLV conversion functions around the stage-local selection.
     A selected bank at least `SWEEP.DEFAULT_MUX_CHUNK_MIN_WIDTH` (32) bits
     wide is chunked this way by default when the plan is built
     (`SWEEP.CHUNK_SELECTED_MUX_OUTPUT_BANKS`) — same latency contribution,
     same cut count, half the select fanout, so `--no_sweep` gets it too.
     The bounded same-depth-neighbor refinement below (`BUILD_CHUNKED_MUX_
     REFINEMENT`) only adds the terminal, deliberately unregistered MUX on
     top of that, after a real measurement fails — see the dated result.

**Mux select-fanout cliff result (2026-08-25).** A single mux select bus
registered *on top of* an already-registered, wider parallel sibling can
materialize (a real register was set) while adding zero pipeline depth —
`SWEEP.GET_PIPELINE_MAP` schedules a shared downstream consumer by the
*max* of its inputs' readiness, so a short branch's register is free once a
slower sibling already bounds that max. Found for real on `soft_shift_rot`
(sky130, real liberty STA, `--no_hier_syn --no_sweep`): planning
`MUX_uint5_t_if_eff_amt`'s output on top of an already-selected
`MUX_uint64_t_if_w` cost nothing in depth but cost everything in fanout —
`cuts=7, 6 slice(s) built` (the mismatch itself was the tell), 4
design-wide max-capacitance violations, 8.50 ns combinational delay,
105.95 MHz measured versus 252.13 MHz for the otherwise-identical 6-cut
plan that omitted it. `SWEEP.DROP_NON_DEEPENING_PLACEMENTS` now drops any
`INSTANCE_INPUT`/`INSTANCE_OUTPUT` placement whose removal, alone, leaves
the subtree's real post-lowering `GET_TOTAL_LATENCY` exactly where it
started — ground truth after real lowering, not a landscape estimate,
since only the real synchronous schedule can see this. Measured effect,
same target, same `--no_hier_syn --no_sweep` flags:

| fix applied | cuts | measured fmax | max-cap violations |
|---|---|---|---|
| none (today's `master`) | 7 (6 slices) | 105.95 MHz | 4 |
| drop the non-deepening cut alone | 6 | 252.13 MHz | 0 |
| + chunk the remaining wide banks by default | 6 | **377.41 MHz** | 0 |

The combined result (377.41 MHz) beats even the measured escalation's own
best result on this design (317.36 MHz at 8 cuts) — with two fewer
register banks. `--no_hier_syn`'s own floor estimate for this design
(~192.3 MHz, summed isolated per-leaf delays) is separately known to run
~2.5x high on a mux chain versus hierarchical synthesis (~483 MHz) — a
pre-existing, unrelated limitation of that flag, not fixed here.

**AUTOPIPELINE-region blind spot, found by the regression suite.** The
initial `DROP_NON_DEEPENING_PLACEMENTS` compared a candidate's effect
against `TimingParamsLookupTable[subtree_root].GET_TOTAL_LATENCY(...)`
alone. `autopipeline_latency_test` (`stream_pipeline_test_top` /
`div_inv`'s AUTOPIPELINE'd `soft_div_radix` core) failed against it: that
subtree's own landscape reaches into a nested AUTOPIPELINE-tagged
descendant (`BUILD_SLICE_LANDSCAPE`'s `SUB_HAS_AUTOPIPELINE_IN_HIER` check
already permits descending through one), and `SYN.GET_SUBMODULE_LATENCY`
deliberately reports such a region's own depth as 0 to its container — the
same convention `SUMMARIZE_SUBTREE_PIPELINE`'s own docstring documents, so
balanced-latency reporting doesn't double-count an already-decoupled
region. A monolithic-only comparison therefore misread every one of that
region's real registers as "added no depth" and deleted all 3 (then 6) of
them, collapsing the plan to `cuts=0` and burning all 12 sweep iterations
without ever placing a single register (17.16 MHz vs. 50 MHz goal,
`TIMING NOT MET`). Fixed by adding each such region's own
`GET_TOTAL_LATENCY` back into the comparison, mirroring `SUMMARIZE_
SUBTREE_PIPELINE`'s own `monolithic + sum(regions)` formula exactly.
Re-verified: `autopipeline_latency_test` passes (5-stage pinned
confirmation, 266.72 MHz vs. 50 MHz goal), and the mux select-fanout cliff
result above is unaffected (that design has no AUTOPIPELINE regions, so
the region-sum contributes nothing extra there).
   - `SPLIT_KIND_1LL` ("one logic level" — AND/OR/XOR/NOT/NEGATE/MULT):
     these generators (`stage_for_1ll`) always place the *whole* operation in
     exactly one stage no matter the latency — only the register *boundary*
     moves. Latency 1 puts the op in stage 0 or 1 depending on which side of
     0.5 the slice falls; latency 2 puts registers on both sides with the op
     untouched in the middle. A 3rd slice is provably wasted (a bare register
     around logic that never shrinks), so `RAW_VHDL.LEAF_MAX_SPLIT_SLICES`
     caps these at 2 — enforced primarily in the landscape (§4: only a
     `SPLIT_KIND_1LL` segment's own two boundary units are ever legal cut
     positions) and backstopped by a hard error in
     `SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES` if anything else ever
     requests a 3rd.
   - `SPLIT_KIND_NONE` (bit-manip/cast/const-shift/const-ref): no
     stage-dependent behavior at all; in practice unreachable since
     `LOGIC_IS_ZERO_DELAY` already excludes these from ever getting cuts.
2. **IO regs** — `_has_input_regs/_has_output_regs` add boundary registers.
   Typed `instance_input` and `instance_output` placements lower directly to
   the selected child boundary. They do not manufacture fractional cuts in
   every primitive below that child.

Everything else is *emergent*: a hierarchical module's latency is rebuilt
bottom-up from its children by `GET_PIPELINE_MAP`, and the VHDL writer
registers wires crossing stage boundaries (`REG_STAGEn_<wire>`).

The planned sweep now preserves a concrete `PipelinePlacement` through
selection and lowering rather than immediately projecting a fractional cut
through every descendant. `instance_input`/`instance_output` set one entity
boundary flag; `bit_internal` adds a local slice only to a genuinely
bit-splittable raw leaf. The older recursive fraction mechanism remains for
the coarse sweep and compatibility paths:

```
        MAIN  cut at 30% of 100ns
          |
         foo  -> cut lands at 25% of foo's 40ns
          |
       adder  -> cut lands at 50% of adder's 5ns   <- real register here
```

**Cuts != latency.** The two are related but distinct numbers, now always
reported separately. Latency can exceed the cut count (children of one cut
sliced at misaligned positions, IO regs, `make_stream_pipeline`-style
factories with internal `autopipeline()` calls). A mini-swept WireGuard
`block_step` accepts one internal half-way slice. Its external banks are then
chosen over direct parent-dataflow edges: a ten-instance serial chain needs
the ten internal slices plus nine shared boundaries, not both banks on every
instance. The historical compatibility shape was 3 clocks per instance; it
is now only the final fallback when compact boundary policies miss timing.
An **autopipeline-tagged call
site reports latency 0 to its container** (so FSMs keep their cycle
accounting) — a stateful MAIN prints `main_latency=0` while a deep pipeline
runs inside it. That is expected, not a bug.

**A module's latency is not its slice count.** A module's total latency is
its own leaf slices *plus* the summed latencies of its submodule instances,
so an entity named `foo_25CLK` can legitimately carry only 8 slices of its
own (the other 17 register delays live in submodules). `latency == slice count` holds
*only* for a pure-comb, fully-sliceable region (nothing below it to add
depth) — which is exactly the region `CHECK_CUTS_VS_LATENCY` marks `strict`.

**Reporting how deep the design got pipelined.** Because a stream MAIN reads
`main_latency=0` and the deepest single instance (one block_step) is far
shallower than the whole pipeline, neither alone answers "how many stages did
autopipelining build?". So `GET_SUBTREE_PIPELINE_STAGES`/`SUMMARIZE_SUBTREE_
PIPELINE` compute the **total slices in a main's cut subtrees**:

```
total = (slices inserted directly into the cut-subtree roots)
      + (latency of every decoupled autopipeline region instance in them)
```

The two parts never overlap: a subtree root's own latency already zeroes its
decoupled children (they report 0 to it), and the second term adds exactly
those back. This equals the input-to-output register count when the regions
sit in series, as in a stream pipeline. The historical WireGuard
compatibility result was 0 monolithic + `block_step` 3 clocks x 10 = 30
slices — not the "3" a single-instance view would show. A topology-aware
lock instead records its shared boundary cover and reports the realized total.
The `Pipeline depth summary` at *Writing Results* prints
this figure as "N slice(s) total (N+1 pipeline stages)" (computed at *Writing Results*
on the final, actually-emitted table, so it reflects any extra depth the
AUTOPIPELINE pin-and-confirm re-elaboration (§6.5) added).

**Slices vs. pipeline stages — `stages = slices + 1`.** A slice
count is not the same number as "how many pipeline stages". 0 slices (comb
logic) is 1 stage; 1 slice splits it into 2 stages; N slices in series
give N+1 stages. So the `pipeline_stages=` field printed per sweep iteration
and written to `sweep_history.json` is always **realized deepest slices + 1**,
not the requested `cuts` count. The requested cut count and realized slice
count are often equal for one pure-comb subtree (so `pipeline_stages` is then
`cuts + 1`), but those two counts can differ after boundary lowering or with
decoupled regions.
Conflating these values can make a print like `cuts=0
main_latency=0 pipeline_stages=20` look like no registers were added at all.
The compact WireGuard result has no remaining *global* cuts, but does have 19
realized locked slices (ten internal helper slices and nine shared
boundaries), i.e. **20** pipeline stages end-to-end.

Entity naming is also unchanged: each distinct (IO regs + leaf slices)
combination hashes to its own VHDL entity `funcname_<latency>CLK_<hash>`.

## 3. Delay model: leaf-only synthesis with estimates

Old: `ADD_PATH_DELAY_TO_LOOKUP` synthesized **every** function individually —
adder, foo, bar, and MAIN each got a syn run — because composing delays from
children was thought too inaccurate. This mode still exists as
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

New (default `HIER_SYN_MODE == "leaf"`): only functions whose delay
*genuinely requires* synthesis get a run:

- raw HDL leaves (adders, muxes, raw VHDL text modules, ...), heavily
  disk-cached across builds;
- hierarchical *comb* functions with no sliceable path to raw leaves;
- the **measurement frontier**: topmost *fully-combinational* funcs (see
  below).

**MAINs are no longer force-synthesized** (they were in the old flow, to
seed coarse sweep guesses). A fully-comb main IS the measurement frontier
and gets measured there; a main with state anywhere below is always
estimated — its whole-design zero-clk critical path (which includes the
regions about to be pipelined, and internal reg-involved paths) feeds no
planning decision, wastes a near-whole-design syn run, and used to print
as a bogus `Design likely limited to X MHz` report. `--coarse` measures its
main lazily when needed (estimate used if the main has state below).

**Modules with Reg/Feedback state in their subtree** (recursive —
`FUNC_SUBTREE_HAS_STATE`): a per-module synthesis run of such a module
reports its *internal critical path* (often register-to-register, possibly
deep inside a nested FSM) — a different quantity than the *input-to-output
through-delay* that dataflow slicing geometry needs. Only a fully
combinational subtree guarantees measured == through-delay. So stateful
modules split by whether slicing descends through them
(`FUNC_SUBTREE_HAS_AUTOPIPELINE`):

- **on the estimate chain** (an AUTOPIPELINE tag somewhere below — e.g. a
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
(Reg/Feedback in its FIFOs/interlocks) is estimated, not measured. The
calibration that used to come from measuring subtree roots comes instead
from the **measurement frontier** (`FUNC_IS_TOPMOST_COMB`): the topmost
fully-combinational funcs — the largest subtrees with no Reg/Feedback
anywhere inside, where measured == input→output through-delay *by
construction* — each get one real synthesis run in the presynth wave.
Estimates above the frontier are built from those measured totals (plus
measured atomic spans), so first plans stay at the fewest-stages guess;
interior comb funcs below the frontier stay estimated, and the landscape
rescales their relative geometry into the measured frontier total.

Hierarchical functions on the pipelining path are **estimated** instead:
`delay = zero-clk pipeline map total` (the critical topological path through
already-known child delays), marked `logic.delay_is_estimated`, never
written to the disk cache. Estimates over-estimate badly — they can't see
cross-boundary synthesis optimizations (wireguard: leaf-sum 1128 ns vs
~150 ns synthesized, mostly collapsed carry chains).

That inflation is why the **measurement frontier** exists (previous
paragraph): the topmost fully-comb funcs are measured so the estimated
totals above them are realistic. The landscape keeps estimated geometry
(*where* delay lives, relatively) while measured frontier totals calibrate
*how many* cuts — the first plan is the fewest-stages guess
(`~real_delay / target_period`), which typically just misses timing, and
stages are added from synthesis feedback. Under-pipelining and iterating up
is the default; over-pipelining to meet timing fast is what makes people
distrust HLS tools.

**Estimates are never allowed to be why a sweep fails** (in the default
`"leaf"` and `"full"` modes):
- `MEASURE_DELAYS(funcs)` really synthesizes given functions and replaces
  their estimates (invalidating stale pipeline-map caches);
- the refinement loop calls it automatically when it runs out of ideas while
  estimates are still in play (streamsoc: `Falling back to full hierarchy
  synthesis: replacing 21 estimated delays with measured results...` — after
  which sample_power's plan shrank from 25 cuts to 14 and still met timing);
- `--full_hier_syn` forces the old synthesize-everything behavior up front.

`--no_hier_syn` (`HIER_SYN_MODE == "prim"`) deliberately gives this guarantee
up: the fallback is gated on `HIER_SYN_MODE == "leaf"` exactly, so it never
fires in `"prim"` mode, and `MEASURE_DELAYS` itself refuses to (re-)synthesize
any func with submodules there. A `--no_hier_syn` sweep that stalls on
estimate-driven cut placement stops at its best result instead of measuring
for real -- the tradeoff for never paying for a hierarchical syn run.

## 4. New concepts (SWEEP.py)

### A running example

Every concept below is illustrated with this little design (PipelineC-style
pseudo code; delays are made-up round numbers, 1 unit = 1 ns here — real
landscapes use tenths of ns, `DELAY_UNIT_MULT`):

```c
uint8_t mul_add(uint8_t x) { return x * 3 + 1; }   // comb: MULT then ADD

uint8_t acc(uint8_t x) {                            // stateful: Reg inside
    static uint8_t total;                           //  -> cannot be sliced
    total += x;
    return total;
}

#pragma MAIN_MHZ my_main 100.0                      // goal: 10 ns period
uint8_t my_main(uint8_t x) {
    uint8_t a = mul_add(x);                         // 10 ns of comb
    uint8_t s = acc(a);                             //  5 ns atomic span
    return mul_add(s);                              // 10 ns of comb again
}
```

Instance tree with per-func delays after the presynth wave (leaves measured
via synthesis + disk cache, hierarchical funcs estimated, `acc` measured
whole as a topmost stateful span):

```
my_main                    estimated 25 ns   (state below via acc -> NEVER
 |                                            synthesized; estimate built
 |                                            from measured parts)
 |- mul_add    [inst 1]    MEASURED  10 ns   (topmost fully-comb func = the
 |    |                                       measurement frontier: one real
 |    |                                       syn run, through-delay by
 |    |                                       construction)
 |    |- MULT              measured   6 ns   (raw HDL leaf, geometry only)
 |    '- ADD               measured   4 ns   (raw HDL leaf, geometry only)
 |- acc                    measured   5 ns   (stateful, no tags: atomic span,
 |                                            interior never synthesized)
 '- mul_add    [inst 2]    MEASURED  10 ns   (same func, same one syn run)
```

`my_main`'s 25 ns estimate is the sum of measured frontier totals and the
measured atomic span, so the cut budget below is calibrated to reality
without ever synthesizing a module that has state inside it (on real
designs the frontier measurement is what deflates the wildly-inflated
leaf-sum estimates — wireguard's chacha comb subtree estimates ~1090 ns
but measures ~150 ns).

### Cut subtree

*Where is adding registers even allowed to start?* A **cut subtree** is a
maximal subtree that can accept added latency: the MAIN itself if it is pure
comb, otherwise each region reached through AUTOPIPELINE-tagged call sites
underneath stateful containers. One plan per MAIN, one or more cut subtrees
per plan.

In the running example `my_main` is itself sliceable comb (the state lives
*inside* `acc`, which the descend rule below refuses to enter), so the whole
main is one cut subtree with root `my_main` — the left shape below. The right
shape is what real stream designs (wireguard) look like: the MAIN is an FSM,
so registers may only be added inside explicitly tagged regions:

```
 MAIN (pure comb)                    MAIN (FSM: Reg/Feedback -> not sliceable)
   = the whole MAIN is                 |
     one cut subtree                   +-- prep_fsm (stateful, no tag)   X no subtree
                                       |
                                       +-- wrapper (stateful)
                                             |
                                             +-- autopipeline(chacha_loop(...))   <- TAG
                                                   |
                                                   chacha_loop = cut subtree root
```

This replaces the old question "which module should the middle-out sweep
coarse-sweep next?" — instead of discovering boundaries by trial synthesis,
the cut subtrees are computed once from the sliceability rules.

The descend rule (used both by the old recursive slicer and the landscape,
now fixed): descend into a child iff

```
call site is AUTOPIPELINE tagged (or contains a tag deeper)     # override
OR (parent is sliceable AND child is sliceable)                 # plain comb
```

The child-side check is new — previously a sliceable parent descended into
stateful children where cuts produced no registers and silently vanished
("Finding #1"). Now such a cut stops and the child boundary becomes the
stage boundary. Sliceability itself (`CAN_HAVE_ADDED_LATENCY`) is unchanged:
no fixed-latency/vhdl-text/clock-crossing/state-regs/memory/blackbox/feedback.

### Landscape, segments, and typed candidates

*Where inside a subtree may cuts land, and what does each stretch of delay
cost?* `BUILD_SLICE_LANDSCAPE` flattens a subtree onto its delay axis into
leaf-most **segments**:

- `sliceable` — `SPLIT_KIND_BITS` raw HDL leaf; cuts anywhere inside produce
  a register (§2: the leaf's own generator decides *how*, via an equal-width
  split, not the landscape), **capped** to at most `width - 1` legal units
  (`RAW_VHDL.GET_LEAF_BIT_WIDTH`, the same "widest input/output wire" every
  such leaf's own codegen already uses as `GET_BITS_PER_STAGE_DICT`'s
  `num_bits`) — an N-bit leaf can hold at most N-1 interior registers (N
  stages); offering more legal positions than that let `PLAN_CUTS` request
  cuts `GET_BITS_PER_STAGE_DICT` could only honor with **interior zero-bit
  stages** (bare registers around no logic — found for real: a 4-bit op
  spread over 15 units accepted 14 cuts, `[0,1,0,0,0,1,0,0,0,1,0,0,0,1,0]`
  bits per stage). Backstopped by a hard error in `GET_BITS_PER_STAGE_DICT`
  itself if an interior zero-bit stage ever slips through anyway (a leading
  or trailing zero-bit stage is fine — an IO-boundary register with no
  logic on the outer side).
- `sliceable_1ll` — `SPLIT_KIND_1LL` and the initial-planner view of
  `SPLIT_KIND_MUX_BITS`; the operation-output boundary is legal and the
  interior blames like `atomic`. Ordinary planning therefore cannot waste a
  2nd/3rd cut inside one 1LL operation. A genuine `SPLIT_KIND_1LL` span's
  own reason is `1ll_atomic` and stays a hard floor; a `SPLIT_KIND_MUX_BITS`
  span's reason is `mux_packed_bank` and is a *soft* floor (in
  `SOFT_FLOOR_REASONS`) — it is only the unchunked estimate, and a selected
  wide bank is chunked into the genuinely bit-split lowering by default now
  (see the `SPLIT_KIND_MUX_BITS` bullet above and the dated result below);
  only the terminal, still-unregistered MUX split remains behind the
  bounded physical-neighbor refinement, reached after whole-design timing
  says the schedule is poor.
- `atomic` — unsliceable span (reason recorded: `state_regs`,
  `feedback_vars`, `vhdl_module_text`, `inside_X_container`, ...),
- `locked` — `params_are_fixed` (a mini-sweep result); already pipelined
  internally, forbids new cuts, costs no stage budget.

For the running example the landscape's `segments` list is (fields
abbreviated — each `Segment` also carries `ancestor_funcs`, the set of
func names on its path, used for attribution):

```python
SliceLandscape(root="my_main", total_units=25, units_to_ns=1.0).segments = [
 Segment(inst="mul_add[1]/MULT", kind=SLICEABLE, start= 0, end= 6),
 Segment(inst="mul_add[1]/ADD",  kind=SLICEABLE, start= 6, end=10),
 Segment(inst="acc",             kind=ATOMIC,    start=10, end=15,
         reason="state_regs", hard=False),
 Segment(inst="mul_add[2]/MULT", kind=SLICEABLE, start=15, end=21),
 Segment(inst="mul_add[2]/ADD",  kind=SLICEABLE, start=21, end=25),
]
```

`finalize()` builds deterministic operation-output candidates plus provisional
bit-planning sites, deduplicates boundaries seen through more than one
hierarchy level, and rasterizes the segments into three per-unit arrays. Every
legal unit has either a concrete output candidate or a bit site that can be
materialized after the selected count for that leaf is known. `legal[u]`
answers "may a cut land on unit u?", `weight[u]` is that unit's cost toward
a stage budget (multiplied by the learned `func_delay_scale` during
densification), `blame[u]` points at the atomic segment covering an illegal
unit:

```
unit:    0    5    10   15   20   24
         |    |    |    |    |    |
axis:    MMMMMMAAAA sssss MMMMMMAAAA     M/A = mul_add MULT/ADD leaves
                    ^acc (atomic)        s   = acc, state_regs
legal:   1111111111 00000 1111111111
weight:  1111111111 11111 1111111111     (all 1.0 until densified)
blame:   .......... aaaaa ..........     (a -> the acc Segment)
```

`PLAN_CUTS` fills a per-stage budget of `target_period / global_scale`
weighted units — 10 ns here — in **three passes**, none of which has a
tolerance knob:

1. **Fewest cuts that fit.** Walk left to right and cut at the *furthest*
   legal unit whose stage still fits the budget; overshoot only when **no**
   legal unit fits (a genuine atomic run — that stage sets the floor). This
   is the classic exchange-argument greedy and is optimal for the cut
   *count*: starting a stage later can never make the remainder easier.
2. **Tighten for free.** Binary-search the smallest budget `W` that still
   needs only that many cuts, and emit pass 1's plan at `W`. Count is
   monotone non-increasing in `W`, so the predicate is monotone.
3. **Prefer real boundaries.** Among units that fit the tightened budget,
   prefer one carrying an `INSTANCE_OUTPUT` candidate over a provisional
   bit site — guarded by the cut count, so it can never trade registers for
   tidiness.

```
walk:  units 0..9 accumulate 10.0 -> unit 9 is the furthest legal that fits -> CUT@9
       units 10..19 accumulate 10.0 -> unit 19 likewise                     -> CUT@19
       units 20..24 = final stage (4 ns, no cut needed)

cuts = [9, 19]   ->  3 stages of ~10ns / ~10ns / ~4ns
```

Pass 3 is load-bearing, not polish. Pass 1 minimizes the cut *count* but not
the worst stage *at* that count: on the radix-2 divider at a 7.4 ns goal the
furthest fitting position sits ~0.23 ns **past** each iteration boundary — a
legal bit site 2 bits into a 34-bit subtractor — so passes 1–2 alone keep the
same 32 cuts while placing them as ragged mid-operation register banks
instead of on the clean MUX boundary.

This replaced a walk that cut when the budget filled and then, via a
`PLAN_CUTS_BOUNDARY_SNAP_FRAC = 0.85` tolerance, allowed itself to accumulate
up to 0.85 of an **extra** budget to reach a `_RUN_BOUNDARY_UNITS` position.
That tolerance existed for a real reason (without any snap, a low cut count
merged an iteration's tail, the 1LL MUX between iterations, and the next
iteration's head into one ~11 ns stage) — but being a fraction of the budget
it scaled with the budget, and once the budget fell *below* one repeated unit
it did the opposite of its job: a 4.7 ns budget snapped forward to the
7.119 ns iteration boundary, a 51% overrun, and reported 33 cuts where 64
were needed. Every goal from 167 to 250 MHz produced the identical 33-cut
plan. The rule above cannot do that — a stage never exceeds the budget when a
legal position inside it would have fit — so the ~11 ns merge is forbidden
outright rather than by tolerance.

`PLAN_CUTS` still chooses delay-axis units, preserving the existing budget,
floor, and feedback machinery. `PLAN_PIPELINE_PLACEMENTS` then
chooses an output candidate or provisional bit site at each unit. All selected
sites for one bit-splittable leaf are normally materialized together as
ordinals `1..K` of the exact `K+1` equal-width chunks emitted by `RAW_VHDL`;
typed exact groups retain explicitly requested integer boundaries instead. The
reported physical axes and local fractions are recomputed from those bit
boundaries rather than pretending the raster requests are hardware. Its
deterministic ranking prefers a coherent hierarchy/output boundary, then
shallower hierarchy and larger covered span, then local registered-bit cost
and a bit-internal site. The current bit cost is local rather than graph-wide,
so it is a late tie-break, not a claim to know the complete alignment-register
cost.

A plan is then judged on where its registers **actually land**, not where they
were requested. `MATERIALIZE_BIT_PLACEMENT_REQUESTS` emits equal-width bit
boundaries chosen from how many requests hit a leaf, so a lone request
anywhere in a 34-bit operation becomes a split at bit 17 — the real divider
asked for cuts at 3.9%, 11.8% and 51.3% of its subtractors and got the
midpoint for all three. The stage structure the planner costed then does not
exist, and the extra registers can buy nothing: at a 190 MHz goal that
produced 48 cuts whose realized worst stage was 7.00 ns, identical to the
32-cut boundary-only plan, for 16 more register banks. So `PLAN_PIPELINE_PLACEMENTS` lowers several candidate plans and keeps the
best, ranked by `_PLAN_RANK`:

- the plan as first planned on the raster;
- **re-planned against the equal-width boundaries its own per-leaf cut counts
  imply** (`_LANDSCAPE_WITH_EQUAL_WIDTH_BIT_SITES`), iterated to a fixed
  point — the per-leaf count is almost always 1 or 2, so it settles at once.
  This is what stops a plan being relocated out from under the budget that
  chose it;
- the two *uniform* split families ("split every wide leaf once", "twice"),
  probed directly. A restriction derived from one plan only explores that
  plan's own family, which otherwise leaves the answer dependent on where the
  first raster plan happened to land — two nearby goals could pick different
  families and the **looser** goal end up with more registers;
- the plan using only real operation boundaries, whose positions cannot move;
- the incumbent re-planned at the worst stage it actually achieved, which
  drops registers that shorten nothing when the caller's budget is
  unreachable (the goal sits below the design's floor).

`_PLAN_RANK` is **meet the budget first, then fewest cuts**, with worst stage
deciding only when nothing meets it. Ranking on worst stage first is a bug
that silently destroys every intermediate pipeline depth: a 47-cut plan at
5.19 ns that comfortably meets a 190 MHz goal loses to a 63-cut plan at
3.85 ns — 33% more registers to beat a target already met — which collapses
the whole 32..64 range onto 64.

Bit splitting therefore survives whenever it genuinely pays and is dropped
when it only looked like it would on the raster.

Note this makes the planner *honest about* the generator's equal-width
contract rather than changing it. Whether that constraint itself should stay
is an open question — see the "Open question (2026-08-21)" note under
`SPLIT_KIND_BITS` in §2.

`APPLY_PIPELINE_PLACEMENTS` lowers the selected types directly. After the
pipeline map is rebuilt, `CHECK_PIPELINE_PLACEMENTS_REALIZED` verifies every
selected candidate materialized; a missing placement is a hard compiler error.
The resulting `N` serial register slices delimit `N + 1` combinational stages.

Parallel branches overlap on the axis, and that overlap decides legality: a
candidate is a real stage boundary only if **nothing uncuttable straddles its
position**. Segments are not a serial chain — the divider's `UNARY_OP_NOT`
reads `BIN_OP_MINUS`'s output and feeds `q_out`, so it runs *alongside* the
MUX that feeds `remainder`, not after it. Registering the NOT's output
therefore lands strictly inside the parallel MUX's atomic span: the NOT branch
gets a register while the MUX path crosses the same depth uncut, so no
pipeline stage is created. Left legal that silently inflates the cut count
without deepening the pipeline — the real divider planned 48 cuts and built
32 slices, 16 of them wasted on NOT outputs. `finalize()` therefore drops any
candidate straddled by an `atomic`/`sliceable_1ll` segment, comparing exact
positions (not units) and exempting a blocker's own end boundary, with one
raster unit of slack at the near edge: a candidate's nominal position is its
unit + 0.5 while the boundary it stands for is the segment's exact `.end`, so
an operation output whose true edge is where the next segment *begins* can
round to a hair inside it. Without that slack half the `BIN_OP_MINUS` outputs
disappeared and the planner had nothing to use between whole iterations.

`--coarse` (and the hotspot mini-sweep, which is a
`--coarse` run in isolation) uses `GET_BEST_GUESS_IDEAL_SLICES(n)` = n
evenly spaced global fractions with no idea what they'd hit (a cut at 0.5
here would have landed inside `acc` and been silently lost — the "Finding
#1" bug class the invariant above guards against). A landscape-aware,
exact-cut-count replacement for this (`SEARCH_EXACT_CUT_COUNT`/
`GET_EVEN_SLICES_OVER_LANDSCAPE`) was built and measured against real
sky130 synthesis: on the divider design it consistently placed cuts *worse*
than the blind fractions it was meant to improve on (~16% lower fmax at an
equal, fixed cut count, holding every other change constant) with no
counter-example found where it did better — reverted rather than shipped.
See the project's autopipelining-fmax investigation handoff notes if
revisiting this.

Compatibility/coarse paths still use `CHECK_CUTS_VS_LATENCY` to compare a
fractional cut count
against the leaf slices that actually materialized in the subtree.
Its strictness follows the landscape:

- **Zero leaf slices** while cuts were planned: always a hard error
  (the Finding #1 class — every register vanished).
- **Fully sliceable subtree** (every delay unit legal — pure comb, a
  register can go anywhere): fewer leaf slices than cuts is a hard error —
  nothing in the subtree may absorb a cut, so a shortfall means slicing
  descent itself is broken. *More* slices than cuts is normal even here:
  a cut is a stage-boundary line across the dataflow, and where it crosses
  parallel branches each branch materializes its own leaf register.
- **Subtree with unsliceable spans** (atomic/locked segments): cuts
  legitimately shift/merge around those spans on the way down, so a
  shortfall is expected — a one-line `[sweep] note:` only, no warning.

### Flat functions, fixed placements, and traces

Candidates are collected from combinational operation instances recursively,
not just user helper-function boundaries. A user may write one flat sequence
of operations and still expose the same legal physical locations as an
equivalent hierarchy. Source hierarchy is retained as metadata and a
coherence tie-break; it is not a requirement that the user predict one
clock's worth of logic per helper.

`PIPELINEC_INTERNAL_PLACEMENT_FILE` is an intentionally internal experiment
hook, not a command-line or source interface. Schema version 1 accepts generic
selectors (`candidate_id`, kind, function, ancestor, instance path/regex,
main/subtree, hierarchy depth, coherent-boundary flag, axis bounds, `all`, and
`limit`) plus exact candidate IDs and strictly increasing
`exact_bit_boundaries` groups for a named raw leaf. `replace` emits
only the fixed schedule; `seed` retains fixed positions while the ordinary
planner fills long remaining intervals. Unmatched or ambiguous selectors fail
loudly. This exists for controlled physical-placement A/B tests and must not
become a Divider-name rule or public slice-cap option.

Every planned run writes `<out>/top/placement_trace.json`. Trace schema 5 keeps
concrete output `candidates` separate from nonphysical bit `planning_sites`.
Per-iteration and final selections contain only physical placements; a bit
selection records its emitted width, boundary, split ordinal/count,
bits-per-stage, boundary mode/group, requested raster coordinate, actual
axis/local coordinate, and realization status. The trace also records
per-iteration physical fingerprints and whether the one bounded generic
chunked-MUX refinement was attempted (`same_depth_refinement.chunked_mux_attempted`),
plus instance/function metadata,
estimated registered bits, internal forced mode, boundary-register type, and
local stage assignment. A `locked_instances` entry separately records every
coarse mini-sweep lock, including its fixed internal slices, selected input/
output banks, boundary strategy, rebuilt latency, and realization check.
`mini_sweep_boundary_diagnostics` records the alias-only direct edges, the
minimum-cost input/output cover, and any edge ineligible because a no-I/O
pragma applied. The trace,
generated VHDL, mapped JSON, and STA report
together are the evidence for a placement claim; requested cut counts alone
are not.

The clean gate-Divider baseline demonstrates why this distinction matters.
The preserved
[`divider_gate_clean_baseline_critical_paths.json`](../src/tests/pypeline_tests/qor/divider_gate_clean_baseline_critical_paths.json)
comes from unchanged commit `c81ca31f`, the historical `current` synthesis
recipe, and no
handoff patch. Its 28/50/63/67/70-slice winning paths all contain the pre-step
divide-by-zero compare/select cone before the first repeated radix step. By 67
slices that invariant prefix is about 5.67 ns; adding three more old-planner
slices changes the 7.010 ns period by exactly zero. A fallback placement at 73
slices jumps to 224.31 MHz after finally isolating that mux, then trimming
finds a different 66-slice/67-stage placement at 184.35 MHz. Its exact final
VHDL passes 141 ordered vectors at 66-cycle latency, but it remains well over
the 48-slice limit. This is evidence for a missing legal operation boundary
and a mapping/fanout effect, not evidence that the repeated step itself needs
still more cuts. The frozen compare/select
recipe matrix is documented in
[`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md#pre-step-compareselect-cone-and-clean-baseline-floor-2026-08-14).
Typed-placement results retain their own modified-tree hashes and must not be
described as part of that clean baseline.

### Divider acceptance result (2026-08-16)

The generic typed planner and the production sky130 recipe now meet the
Divider target without a Divider-name rule, exact-cut search, public slice
cap, or required stage-sized helper function. The durable record is
[`divider_qor_acceptance.json`](../src/tests/pypeline_tests/qor/divider_qor_acceptance.json).

| unchanged fixture | compiler/recipe | slices | combinational stages | fmax | cells | DFFs | verdict |
|---|---|---:|---:|---:|---:|---:|---|
| gate | clean `c81ca31f` / historical control | 66 | 67 | 184.35 MHz | 34,585 | 10,327 | fails 48-slice limit |
| gate | typed planner / `early_flatten_opt` V3 | **31** | **32** | **160.43 MHz** | 16,514 | 3,007 | **pass** |
| arithmetic | clean `c81ca31f` / historical control | 64 | 65 | 149.16 MHz | 22,563 | 8,749 | fails fewer-than-64 limit |
| arithmetic | typed planner / `early_flatten_opt` V3 | **32** | **33** | **180.05 MHz** | 13,779 | 3,072 | **pass** |

These fmax figures are under the V3 production recipe `early_flatten_opt`.
The production recipe is now `early_flatten_noabc` (model V4), chosen because
it reproduces latchup's real netlists rather than because it maximises our own
fmax — under it the same arithmetic design maps to 13,873 cells at 169.6 MHz.
See docs/DEVICE_MODELS_DESIGN.md, "Matching latchup's early-flatten flow".

The current automatic gate trace contains the first 31 coherent `step_gates`
outputs.  With `early_flatten_opt`, that is enough to remove the former
pre-loop divide-zero fanout floor without an explicit divide-zero placement.
This is one slice fewer than the 32-slice physical control and comfortably
inside the 48-slice allowance. Its exact final VHDL
passes 141 vectors with continuous traffic, bubbles, divide-by-zero, edge
cases, ordering, valid timing, `input_ready == 1`, and flush at 31-cycle
latency; its immutable mapped netlist has zero unmapped cells and zero
capacitance violations.

The arithmetic fixture has no stage-sized helper at all. Its successful trace
selects the pre-loop divide-zero output followed by the first 31 flat loop
remainder-select operations. That 64-to-32-slice improvement is the direct
regression proof that operation-boundary scheduling applies to ordinary flat
dataflow, not merely to the gate fixture's convenient helper hierarchy.

The first automatic gate plan met timing, so full dependency-DAG scheduling,
custom ABC scripts, sequential retiming, flatter stage-oriented VHDL, and
source reshaping were not deepened. Those remain escalation paths if a future
design exposes a typed-landscape limitation; hierarchy remains metadata and a
tie-break, never the unit of scheduling.

### Budget-to-latency continuity result (2026-08-21)

The three-pass `PLAN_CUTS`, the parallel-branch legality rule, and
realized-plan judging were accepted together against the `--no_sweep
--no_hier_syn` radix-2 divider (`early_flatten` shape, sky130 model V4,
`early_flatten_noabc`). The acceptance rule was stated per **latency**, not
per MHz target: a deeper pipeline at a given goal is fine, a slower pipeline
at a given stage count is not.

Measured on the first planned guess (`iter=1` is the same
`PLAN_PIPELINE_PLACEMENTS` call `--no_sweep` writes, taken before any
`global_scale` adjustment, so the sweep's own synthesis measures the
`--no_sweep` artifact):

| slices / stages | before | after | |
|---:|---:|---:|---|
| 16 / 17 | 67.40 MHz | **68.09 MHz** | +1.0% |
| 32 / 33 | 169.57 MHz | **169.57 MHz** | equal; placement-identical (32 MUX outputs, same units) |
| 33 / 34 | 169.57 MHz | not produced | the 33rd cut measured zero gain — pure waste |
| 48 / 49 | not produced | 164.69 MHz | new intermediate level, see below |
| 64 / 65 | 164.69 MHz | **221.94 MHz** | +34.8% |
| 65 / 66 | not produced | 221.94 MHz | |

The accepted gate is **the 33-stage solution must maintain or improve**; it is
equal, and no other measured latency regressed. Goal-to-slice mapping,
before → after: 69→16/16, 100→32/32, 135.5→32/32, 167→33/**48**,
190→33/**48**, 200→33/**64**, 214→33/**65**, 284→64/65. The 33-slice plateau
spanning 167–250 MHz is gone.

The reachable levels are structural, not arbitrary. One loop iteration is
`BIN_OP_MINUS` 3.851 ns + `MUX_uint32_t` 3.268 ns = 7.119 ns, so "one cut per
iteration" (32) and "two" (64) fall out for free. A real level sits between
them — cut at a MINUS's output, the *next* MINUS's midpoint, then that MUX's
output: 3 cuts per 2 iterations, **48**, predicted ~5.1 ns. Reaching it needs
both halves of the plan/lower contract working (see "Landscape, segments, and
typed candidates"): the bit site must be planned *at* the equal-width
boundary lowering will emit, and plans must be ranked by `_PLAN_RANK` (meet
the goal, then fewest cuts) rather than by raw worst stage.

Do not confuse an intermediate level with a **phase variant**. The old
planner emitted 33–48-slice plans whose realized worst stage was 7.00 ns —
identical to the 32-slice plan's — registers spent for no speed. Those are
what realized-plan judging discards. A genuine level is a different stage
structure: 48 slices at ~5.1 ns is ~72% of the coarse level, where a phase
variant sits within a raster unit of it.

The 48-slice first guess exposed the remaining defect rather than becoming a
returned result: it mapped to 164.69 MHz, below the 32-slice plan's 169.57
MHz. The follow-up investigation held `DEVICE_MODELS.py`, model V4, the
liberty data, timing coefficients, and `early_flatten_noabc` byte-identical.
Its controlled results were:

| 49-stage structural A/B | full-Divider fmax | result |
|---|---:|---|
| equal-width subtract split, output-boundary MUX | 164.69 MHz | control; plateau |
| best isolated subtract boundary (bit 24) | 144.43 MHz | rejected; full-design fanout/max-capacitance dominated |
| exact subtract bit 28 | 152.06 MHz | rejected |
| exact subtract bit 33 | 162.99 MHz | rejected |
| explicit ripple-borrow stage-local subtract | 99.16 MHz | rejected |
| chunk selected integer MUXes, tail unchanged | 170.15 MHz | only +0.3% over 33 stages |
| chunk selected integer MUXes plus terminal MUX | **194.22 MHz at 50 stages** | accepted |

The promoted response is generic. After a full-design timing miss, before a
denser landscape plan is synthesized, the sweep constructs at most one
physical neighbor: each selected built-in MUX output bank becomes one exact
midpoint packed-bit boundary, and the last candidate MUX is included to
remove a formerly unsplit tail. Selected output banks retain one clock of
local latency; the terminal split costs one additional slice. Physical
fingerprints prevent duplicate synthesis. If the neighbor fails, the already
computed stage-specific/global feedback resumes normal densification; no
Divider name, iteration count, target frequency, or public slice cap appears
in the rule.

At the 180 MHz goal the normal sweep now measures the 48-slice/49-stage
control at 164.69 MHz, then returns **49 slices / 50 stages at 194.22 MHz**.
The immutable final VHDL passes all 141 ordered vectors at 49-cycle latency,
including bubbles and divide-by-zero, and maps with complete topology and
zero unmapped cells. The 32-slice/33-stage endpoint remains 169.57 MHz and
the 64-slice/65-stage endpoint remains 221.94 MHz because neither renders a
bit-chunked MUX. Thus the accepted returned sequence is approximately
169.57 → 194.22 → 221.94 MHz at 33 → 50 → 65 stages, with meaningful gains
on both depth increases instead of a flat intermediate plateau.

The generic lowering was subsequently checked with the Divider's 32-bit
loop-carried values wrapped in a one-field user struct. The normal 180 MHz
sweep, starting from an empty temporary path-delay cache, took the same route:
the 48-slice control missed, then the packed-MUX neighbor returned 49 slices /
50 stages at **194.2227 MHz**. The immutable VHDL passed the same 141-vector
test at 49-cycle latency. Trace schema 5 recorded 17 wrapper-MUX midpoint
placements (including the terminal refinement), and cache output contained
only canonical `MUX_uint32_t.delay` and `MUX_uint32_t.timing.json` files.
There is no wrapper-type cache filename or Divider-specific production rule.

### Floor

*What fmax can this subtree never exceed?* The longest run of illegal units
is the predicted minimum stage delay — reported with a blamed instance
**before any synthesis run**. Old behavior: this was discovered empirically
by watching 5+ full syn runs plateau at the same MHz.

In the running example the longest illegal run is `acc`'s 5 units → floor =
1000/5 = 200 MHz, comfortably above the 100 MHz goal, so the report is just
informational:

```
[sweep] main=my_main subtree=my_main comb delay ~25.0 ns, target 10.0 ns
        (100.0 MHz), predicted fmax floor (soft) ~200.0 MHz
        due to acc (state_regs, 5.0 ns unsliceable)
```

If `acc` instead held 20 ns of division, the floor (50 MHz) would sit below
the goal and the sweep says so up front:

```
[sweep] WARNING: predicted soft floor 50.0 MHz is below the 100.0 MHz goal - ...
```

Floors come in two strengths:

- **hard** — pure comb spans no register can ever land in (raw VHDL text
  leaves, comb trapped *inside* a stateful container between its
  registers). A true ceiling: the sweep gives up on reaching it.
- **soft** (`state_regs`, `feedback_vars`, `fixed_latency`) — a stateful
  module's span is its estimated through-delay, which mixes paths that
  boundary registers CAN cut with internal ones they can't, so it is a
  rough hint, not a ceiling (wireguard's `append_auth_tag` once carried a
  31.4 ns measured span yet the design met 12.5 ns). The sweep only stops
  at a soft floor *empirically* (achieved fmax stuck there for consecutive
  iterations).

**"At the floor" is a symmetric band, not a one-sided threshold.**
`SWEEP.AT_PREDICTED_FLOOR(curr_mhz, floor, target_mhz)` requires curr_mhz
within `[FLOOR_TOLERANCE*floor, floor/FLOOR_TOLERANCE]` — both a lower bound
*and* an upper bound. An earlier version checked only the lower bound
(`curr_mhz >= FLOOR_TOLERANCE*floor`), which is satisfied by any fmax above
the floor however far above: seen for real, a sweep stopped at 124.18 MHz
citing a ~71.6 MHz predicted floor (73% above it, nowhere near stagnating)
and reported `TIMING NOT MET` despite comfortably beating its own 147 MHz
goal. A curr_mhz far above the floor means the *prediction* was wrong, not
that a ceiling was reached, so it must not count as "at the floor".

**Restoring the best-seen result must re-check whether it actually met
its goal.** When the sweep stops without the final iteration meeting
timing, it restores whichever earlier iteration had the best worst-case
achieved/target ratio (`best_tpl`/`best_score`) and writes that out instead.
`SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS(best_score)` (`best_score >= 1.0`) then
re-derives `met_timing` for that restored snapshot — without it, a build
could restore a snapshot that measured 244.72 MHz against a 147.00 MHz
target and still exit `TIMING NOT MET`, because `met_timing` was last
written by a later, worse iteration (e.g. one a floor-stop landed on
afterward) and never re-checked against the snapshot actually written out.

### Plan

`MainSweepPlan` (one per MAIN with a target MHz) replaces the old
`SweepState`/`InstSweepState` multiplier bookkeeping. For the running
example, mid-sweep after one failed iteration that was attributed to
`mul_add`, the plan would look like:

```python
MainSweepPlan(
  main_inst        = "my_main",
  target_mhz       = 100.0,
  subtrees         = ["my_main"],            # cut subtree roots
  landscapes       = {"my_main": <SliceLandscape above>},
  cuts             = {"my_main": [9, 19]},   # planned cut units per subtree
  # learned calibration (successors of the old global multipliers,
  # but per-func where attribution allows):
  func_delay_scale = {"mul_add": 1.75},      # densify: mul_add units now
                                             #  cost 1.75x stage budget
  global_scale     = 1.0,                    # no-attribution fallback knob
  locked           = {},                     # inst -> fixed interior slices
                                             #  + independently chosen I/O banks
  met_timing       = False,
  last_failing_total_cuts = 2,               # for post-met trim bisection
  unpipelinable_blame     = None,
  history          = [ {...one dict per iteration...} ],
)
```

The history dumps to `<out_dir>/<top>/sweep_history.json`, one record per
(iteration, main):

```json
{"iter": 1, "main": "my_main", "goal_mhz": 100.0, "achieved_mhz": 87.0,
 "cuts": 2, "main_latency": 2, "pipeline_stages": 3,
 "predicted_stage_ns": 10.0, "bottleneck": "mul_add",
 "action": "densify(mul_add x1.75)"}
```

## 5. The refinement loop

```
                 +--------------------------------------------+
                 | plan cuts per subtree (landscape + budget)  |
                 | apply locks, slice, write VHDL              |
                 +--------------------+-----------------------+
                                      |
                        one full-design synthesis run
                                      |
                     per clock group timing report
                                      |
        met? -- yes --> minimality proven and --pipeline_min_effort spent?
          |               not proven: retry with fewer cuts (trim) - bisect
          |                    between the last known FAILING cut count and
          |                    the met count (or probe ~12% below a count
          |                    that never had a failing data point). NOTE:
          |                    reported slack is NOT the signal - tools stop
          |                    optimizing at slack ~0, so met designs report
          |                    near-zero slack no matter how over-registered.
          |                    If the retry fails timing, restore the
          |                    fewest-stage met result and finish.
          |               otherwise: done (Met timing...)
          |
          no
          |
   unused chunked-MUX physical neighbor available?
          |           (wide selected output banks are already chunked by
          |           default when the plan is built -- see
          |           CHUNK_SELECTED_MUX_OUTPUT_BANKS above the top of this
          |           diagram; this step only adds the still-unregistered
          |           terminal MUX and any narrower selected bank the
          |           default pass skipped)
          |-- yes --> try it once before any denser schedule
          |-- no/failed --> continue with ordinary feedback below
          |
   at hard floor? / soft floor + stagnant? --> stop, warn, keep best (exit 0)
          |
   attribute critical path to a function (approximate)
          |
   hotspot found:   func_delay_scale[hotspot] *= target/achieved  -> replan
   same hotspot 2x: isolated mini-sweep of that func, lock result
                    (the isolated probe measures that helper itself)
   hotspot locked:  try the opposite compact boundary side, then bounded
                    one-sided/both-sided fallback policies before rescaling
   hotspot cannot be autopipelined (state regs, vhdl text, ...):
                    rescale once (boundary registers may cut its IO paths),
                    then if fmax stagnates stop and tell the user PLAINLY:
                    "critical path is in function F, which cannot be
                    autopipelined (reason) - restructure F or lower the goal"
   no attribution:  global_scale *= target/achieved               -> replan
          |
   fmax stagnant (within 1% of target, twice) or out of ideas,
   estimates in play -> MEASURE_DELAYS all of them (once), keep going
          |
   iteration cap (12) -> stop with warning, keep best result
```

**Escalation ladder for a stuck hotspot** — ordered to prefer a measured,
compact repeated-helper solution before global densification skips past it:

1. before synthesizing the denser plan, try one fingerprint-deduplicated
   chunked-MUX neighbor when the current schedule contains such
   operation-output boundaries; if it fails, retain the feedback calculated
   for the ordinary next step;
2. densify cuts in the attributed func (`func_delay_scale`) — replan;
3. still attributed to the same helper on the next full-design result →
   isolated **mini-sweep**: measure
   the hotspot's own delay first if it is fully comb (the coarse initial
   guess divides delay by target period — an inflated estimate would
   over-pipeline the lock from the start; a hotspot with state below keeps
   its estimate, the loop self-corrects), coarse-sweep upward from that
   guess, then **bisect downward** (`MINISWEEP_TRIM_PROBES` single-latency
   runs) between the last failing and first passing latency before locking
   — the lock lands on the proven-minimal latency, never the first passing
   overshoot. A zero-cut isolated pass is deliberately not locked: adding
   IO registers alone would add latency without splitting the hot path.
4. fmax stuck while cuts grow and the targeted probe did not help → **measure**
   the remaining estimated delays for real and replan with true geometry.

A same-fmax comparison uses a *relative* tolerance (1% of target):
62.92 → 62.99 MHz is the same result, not progress.

The old loop's outer structure ("reset to zero clocks, slice, synthesize,
adjust") survives, but the *adjust* step changed from multiplier growth +
hierarchy step-down to the table above. The old per-module coarse sweep
survives in two places: the `--coarse` CLI path, and as the **mini-sweep**
run on an attributed hotspot (streamsoc: fft attributed 3x → `Isolated
coarse sweep of hotspot: fft_2pt_pipeline_no_handshake` → met 129 MHz in
isolation with 2 cuts → locked interior plus a parent-dataflow boundary
policy).

**Attribution is approximate by design.** Post-synthesis names below the
top-level MAIN are mangled differently by every tool, and keep/dont_touch
attributes bloat designs — so exact hierarchical matching is never
attempted. Instead:

1. MAINs resolve via entity-name prefixes (unchanged
   `GET_MAIN_INSTS_FROM_PATH_REPORT` — MAIN entities survive unmangled);
2. function-name *fragments* from the subtree's landscape (`SWEEP.
   RANK_PATH_FUNC_CANDIDATES`) are substring-matched against the report's
   register/netlist names (generated `REG_STAGEn_<wire>` FF names survive
   synthesis well) and ranked **by depth, not by name length**: a candidate
   whose name is a substring of *every available* endpoint name is a true
   common ancestor of the two registers (both endpoint names share their
   textual prefix down to their lowest common ancestor), so the deepest
   (rightmost) such match wins, longer name breaking ties — this finds the
   LCA without ever needing exact hierarchical matching. Only when no
   candidate matches any endpoint name at all does it fall back to summing
   matched-substring length across every endpoint/resource string (the
   original scoring, kept as a last resort for tools that report resources
   but no usable register endpoint names). The subtree root and the main's
   own names are **excluded** — the flattened netlist prefixes every
   register with the top entity name, so the root would match everything
   and always win, a meaningless attribution;

   *Why length alone was wrong:* every ancestor func's name is itself a
   substring of a descendant register's fully-qualified name (each
   hierarchy level just prepends its own instance name), so a pure
   matched-length score carries no depth signal — it always favors
   whichever candidate name is longest. Seen for real on wireguard-fpga's
   decrypt path: a 58-character auto-generated interface-func wrapper name
   (`if8040c842_decrypt_dataflow_core_..._inst18`) scored 14112 and beat
   the 29-character `chacha20_chacha20_block_step` at 7056, even though
   Vivado's own timing report showed the critical path running entirely
   between two registers *inside* the latter, many levels deeper than the
   wrapper. `SWEEP.RESOLVE_PIPELINABLE_HOTSPOT` additionally guards a
   related case: the correctly-attributed deepest common ancestor can
   itself be unsliceable (state/feedback at its own level, e.g. a
   `feedback_vars` submodule threaded through an interface-func wrapper)
   while wrapping other, unrelated sliceable logic — before declaring the
   path unpipelinable it scans the remaining ranked candidates for the
   deepest one that autopipelining *can* help, so one stuck ancestor never
   masks a densifiable one on the same path;
3. entity-local `REG_STAGEn` stage numbers are logged only — stage indices
   are local to the entity the FF lives in, never global;
4. low confidence → no attribution → global rescale. PYRTL (the no-PART
   software timing model) reports a single fmax with no names at all and
   always takes this path — still floor-bounded and convergent.
5. mains never implicated in any *failing* report count as met once every
   reported path meets its goal (per clock group reports only show the
   group-worst path, which can live in a different main — same semantics as
   the old sweep).

Every iteration logs one line per main — a real one from WireGuard showing
targeted densification of the correctly-attributed interior hotspot:

```
[sweep] iter=1 main=chacha20_pipeline_shared_chacha20_pipeline_shared goal=80.00MHz
        got=47.91MHz (20.87ns) cuts=12 main_latency=0 pipeline_stages=13
        predicted_stage=12.25ns bottleneck=chacha20_chacha20_block_step
        action=densify(chacha20_chacha20_block_step x1.75)
```

(An early version of this sweep once "met timing in one iteration" on this
design — with 88 stages, because the cut budget was computed against a 7.5×
inflated estimated delay axis. Meeting timing fast by drowning the design
in registers is the failure mode that makes people distrust HLS tools; a
few more iterations converging from below is always the better trade.)

One from streamsoc (compare: the old sweep would have re-sliced the *whole*
design more finely):

```
[sweep] iter=1 main=fft_2pt_pipeline_no_handshake goal=110.00MHz got=98.86MHz
        (10.11ns) cuts=3 main_latency=4 pipeline_stages=5 predicted_stage=9.10ns
        bottleneck=fft_2pt_pipeline_no_handshake action=densify(fft_... x1.17)
```

### Attribution depth-ranking result (2026-08-24)

`./build.py --dec --sim --native` (wireguard-fpga, 80 MHz goal) used to fail
after 2 iterations: iter=1 attributed the critical path to
`if8040c842_decrypt_dataflow_core_..._inst18` — an auto-generated
interface-func wrapper, unsliceable because a `Feedback[uint1_t]` inside
`strip_auth_tag` makes it report `feedback_vars` — and iter=2 stopped there
(`action=stop(unpipelinable if8040c842_...)`), despite Vivado's own timing
report showing the actual worst path running entirely between two
registers inside `chacha20_chacha20_block_step`, many levels deeper and
fully sliceable. Replaying the real timing report through the old scorer
confirmed why: all four matched candidates matched every endpoint name and
every one of 250 netlist resources, so the summed-length score just picked
the longest name (14112 for the 58-char wrapper vs 7056 for the 29-char
`chacha20_chacha20_block_step`) — no depth signal at all.

With `RANK_PATH_FUNC_CANDIDATES` (rank by deepest shared substring match,
not name length) and `RESOLVE_PIPELINABLE_HOTSPOT` (skip past an
unsliceable match to a deeper sliceable one on the same path), the same
build now attributes correctly from iteration 1 and meets timing:

```
[sweep] iter=1 ... got=31.34MHz (31.91ns) cuts=7 ... bottleneck=chacha20_chacha20_block_step
        action=densify(chacha20_chacha20_block_step x2.68)
[sweep] iter=2 ... got=63.13MHz (15.84ns) cuts=35 ... action=minisweep(chacha20_chacha20_block_step)
[sweep]   Locked chacha20_chacha20_block_step at cuts=1 (0 input + 9 output boundary bank(s)) on 10 instance(s)
[sweep] iter=3 ... got=95.91MHz (10.43ns) cuts=1 ... action=met
PASS decrypt_dataflow_decrypt_dataflow: 95.91 MHz vs 80.00 MHz goal (confirmation run)
```

3 iterations, 21 pipeline stages, met with margin (95.91 vs 80.00 MHz) —
where the unfixed build never got past 31.34 MHz. `./build.py --enc
--sim --native` (no `feedback_vars` submodule in its call graph, so never
exercised this bug) was not re-run as part of this fix; it already passed
at iter=1 before and after, and the change only touches how a hotspot is
*chosen* when multiple candidates match a path, not the sweep's
convergence mechanics.

**Unmet timing fails the build.** The best pipeline found (largest
worst-case achieved/target ratio across iterations) is still written out —
those results are useful for debugging — but then the build prints an
unmissable per-main error block and exits non-zero; simulation and
bitstream generation are skipped:

```
================== TIMING NOT MET ================================
ERROR: TIMING NOT MET: encrypt_dataflow achieved 73.01 MHz vs 80.00 MHz
       goal (unpipelinable_hotspot: poly1305_mac_instance, feedback_vars)
Results were written for debugging; skipping simulation/bitstream.
```

(A silent version of exactly this — sweep stops unmet, results written,
cocotb sim runs and passes, exit 0 — is how a failing wireguard build once
went unnoticed.)

**Pipeline depth summary.** Right after the *Writing Results* banner, one
block reports how deeply each main ended up pipelined (total slices and stages,
see §2), broken down by decoupled region — computed on the final emitted
table so it includes any depth the §6.5 re-elaboration added:

```
[sweep] Pipeline depth summary:
[sweep]   chacha20_pipeline_shared: 19 slice(s) total (20 pipeline stages)
[sweep]     chacha20_block_step: 1 internal slice x 10 + 9 shared output
[sweep]       boundaries = 19 slices
[sweep]     (decoupled regions above sum to the end-to-end pipeline depth
             when in series, as in a stream pipeline)
[sweep]   some_planless_main: not autopipelined (nothing sliceable; meets its
             goal as written if at all)
```

**When autopipelining cannot help at all**, the tool also says so
explicitly during the sweep:

- a MAIN with a timing goal but nothing cuttable (no sliceable logic, no
  AUTOPIPELINE regions) is noted at planning time (a plain message, not a
  warning — this is a normal design shape): *"contains nothing autopipelining
  can help - the goal is met only if the design meets timing as written
  (checked below)"* — and then gets ONE standalone whole-module synthesis so
  the user immediately sees whether "as written" holds:
  `[sweep] F synthesized as written (standalone check): X MHz vs Y MHz goal
  - PASS/FAIL`. The reported number is informational only — it is NEVER
  stored as the func's delay (a stateful module's report is an internal
  critical path, not the input-to-output through-delay estimates use — the
  measurement frontier rule has no exceptions), and pass/fail for the build
  still comes from the in-context full-design reports (a passing clock
  group means every path in it met, including this main's). If its
  in-context timing report fails, the warning repeats with path endpoints
  and feeds the `TIMING NOT MET` failure exit above;
- a failing path attributed to an unpipelinable func stops the sweep with
  the culprit named and the reason (`unpipelinable_hotspot`);
- generic stops (`iteration_limit`, `no_legal_adjustment`) repeat the last
  unpipelinable culprit if one was seen;
- the presynth wave still prints `Design likely limited to ~X MHz due to
  function: F` when a measured unpipelinable module is slower than a main's
  goal (soft number — its standalone critical path includes IO paths that
  boundary registers may cut in context).

## 6. Command line

| flag | meaning |
|---|---|
| (default) | planned sweep per MAIN with a target MHz |
| `--comb` | no pipelining; one syn run reporting comb fmax per clock |
| `--coarse` | single-instance coarse sweep only (evenly-spaced global fractions, `GET_BEST_GUESS_IDEAL_SLICES`; latency grown from timing reports); auto-selected for a single main with no target MHz |
| `--start N` / `--stop N` / `--sweep` | coarse sweep controls (start latency, stop latency, +1 stepping) |
| `--full_hier_syn` | synthesize every hierarchy level for path delays (no estimates) |
| `--no_hier_syn` | opposite of `--full_hier_syn`: never synthesize any hierarchical module (incl. MAINs, stateful atomic spans) -- only true primitive leaves are synthesized, everything else estimated. Gives up the automatic estimate-was-inaccurate fallback to real synthesis. |
| `--pipeline_min_effort N` | extra full-design syn iterations allowed to reduce stages after timing is met (default 2; 0 = accept the first met result, fastest but possibly over-pipelined); no effect with `--no_sweep` |
| `--no_sweep` | write the sweep's first planned guess as final VHDL and stop -- zero sweep synthesis iterations, timing NOT verified. Works with both the default planned sweep and `--coarse`. |

### Build output: `name_index.log`

Alongside `module_instances.log` (top-N-by-delay-usage functions and their instance
paths) and `integer_module_instances.log`, every build also writes
`SYN_OUTPUT_DIRECTORY/name_index.log` (`SYN.WRITE_NAME_INDEX_LOG`), so a generated name
seen anywhere else in the build's own output — a VHDL entity name, a
`module_instances.log` hierarchy path, a `[sweep]`/stdout message — can be traced back to
source without cross-referencing a second log or re-deriving a formatting decision. Four
sections:

- **ENTITIES**: every instantiated function's true source location
  (`Logic.ast_meta.src_file:line[:col]`), its full uncollapsed canonical name when the
  displayed name was actually collapsed to fit the VHDL identifier length cap (see
  [PY_TO_LOGIC_DESIGN.md](PY_TO_LOGIC_DESIGN.md)'s "Canonical function name format"), and
  its instance count.
- **TYPES**: the same full-name decode for every collapsed `@struct`/`@enum` canonical
  type name.
- **GENERATED SOURCES**: every synthetic pypeline-generated Python source (a to_bytes/
  from_bytes cast helper, an AUTOFSM-opened FSM, an interface function's generated wiring
  module) actually written to `SYN_OUTPUT_DIRECTORY/pypeline_generated_source/` by
  `pypeline.dump_generated_sources` — so a `_py_lNN` location suffix pointing at generated
  code (not user source) resolves to a real file instead of a name nobody can open.
- **PIPELINE VARIANTS**: decodes each `hash_ext` (the trailing hash on names like
  `decrypt_dataflow_decrypt_dataflow_0CLK_6f395802` or `top_2abf080f.vhd` — an md5 of the
  timing-params configuration, see `TimingParams.BUILD_HASH_EXT` /
  `MultiMainTimingParams.GET_HASH_EXT`) back to the function it belongs to and its stage
  count. The hash itself is never renamed (it keys real cache/output files and content-hash
  cache replay across AUTOPIPELINE passes) — only decoded.

Best-effort throughout: every field is sourced from a `parser_state` side-table that is
simply empty (not an error) for a plain C-frontend design, so `name_index.log` is still
written, just with less content than a Pypeline design produces.

### Also produced: source locations on stdout/`[sweep]` messages

`SYN.FUNC_SRC_LOC_STR(parser_state, func_name)` appends `" [file.py:line]"` (from the same
`Logic.ast_meta` `name_index.log` reads, empty string when there is none) to every stdout
line that names a function without a location: `"Synthesizing function:"`,
`"Design likely limited to ~N MHz due to function:"`, and every `[sweep]` WARNING/NOTE
line in `SWEEP.py` that names a hotspot or a MAIN. Reading a failing build's own console
output no longer requires separately grepping `module_instances.log`/`pipeline_map.log`
just to find which line of which file a printed name refers to.

## 6.5 AUTOPIPELINE `.latency` pin-and-confirm loop (Pypeline designs only)

Pypeline's `AUTOPIPELINE(func)` tag exposes the sweep's discovered stage count back to
the design's Python as `.latency` (e.g. `make_stream_pipeline` sizes its output FIFO
from it). The stage count only exists *after* the sweep, so `SYN.DO_SWEEP_AND_AUTOPIPELINE`
wraps the parse+sweep sequence in an outer loop — a **pin-and-confirm** loop, not a
repeat-the-sweep one:

1. **Pass 1 (bootstrap, identical to a normal build):** `PARSE_FILE` with an empty
   latency cache (`.latency` reads 0 everywhere) → path delays → full throughput
   sweep → `SYN.HARVEST_AUTOPIPELINE_LATENCIES` walks the finished
   TimingParamsLookupTable and groups each AUTOPIPELINE-tagged instance's
   `GET_TOTAL_LATENCY` by the tag's canonical key (a pure in-memory walk; no
   synthesis, no file I/O). The harvest invalidates every entry's memoized
   latency/hash first (same rationale as `WRITE_FINAL_FILES`): the planner
   mutates submodule `_slices` after container totals were first memoized,
   and a stale memo here would feed `.latency` (and the native simulator's
   delay lines) a number contradicting the entities actually written.
2. **Early exits (the zero-added-cost invariant):** if there are no AUTOPIPELINE call
   sites, or the design's Python never *read* any `.latency`
   (`pypeline.AUTOPIPELINE_LATENCY_WAS_READ()`, a read-tracked property flag), the
   loop ends here — the cache couldn't have influenced the elaborated design, so
   pass 1's result is final. Cost is exactly the classic single parse + single
   sweep. `.c` designs never enter the loop at all (`AUTOPIPELINE` is
   Pypeline-only syntax).
3. **Pass 2 (pin + confirm):** install the harvested latencies
   (`pypeline.SET_AUTOPIPELINE_LATENCY_CACHE`), re-run `PARSE_FILE` (re-executes the
   whole design import graph; `.latency` reads now resolve), rewrite the zero-clk
   VHDL, re-run path delays (mostly disk-cached), then
   `SYN.SEED_TIMING_PARAMS_FROM_PREVIOUS` carries pass 1's sweep solution (slices +
   IO-reg flags) into the fresh zero-clk table. Matching is **two-tier**: exact
   instance path first, else func (entity) name — the func-name tier is load-bearing
   because entity names encode closure values, so a `.latency`-derived parameter
   change (e.g. FIFO depth) renames its factory entity and every instance path
   underneath, exactly where the AUTOPIPELINE'd core lives (the core's own name is
   stable — its closure captures only the user's func). Seeding ends by
   invalidating EVERY entry's cached hash/latency strings — cached hash
   chains embed child func names, and any cache carried across the
   re-elaboration boundary may reference since-renamed entities (the class
   of bug behind the shared-wireguard GHDL "unit not found" failure). Then
   `SYN.DO_SEEDED_CONFIRM_OR_SWEEP` runs **one** full-design synthesis. The loop
   stops only when the post-confirmation harvest **equals** the values this pass's
   Python consumed — meeting timing alone is not sufficient: realizing the seeded
   fractional slices hierarchically (e.g. into pipelined built-in div/mult entities
   with their own stage granularity) can change an instance's total latency even on
   a passing confirmation, and exiting then would build VHDL whose actual depth
   contradicts every `.latency`-derived constant baked into it (and desync the
   native simulator's latency emulation). When the totals change, the loop simply
   re-elaborates with the fresh numbers (an extra pass, typically converging
   immediately since the per-instance slices are already in place); on exit the
   `.latency` values the design consumed provably equal the stage counts built. The
   confirmation is guaranteed to be a REAL synthesis, not a cached-log
   replay: timing hashes (`RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES`)
   record each child's func name alongside its subtree, so a design whose
   descendants renamed (resized FIFO) hashes differently from pass 1 even
   with identical slices — both the multimain top log name and every entity
   filename are content-aware, which also keeps the skip-if-exists entity
   write sound ("same filename ⇒ same rendered content"). The module's own
   name is deliberately not in its tuple (it's already in every filename),
   so leaf tuples — and therefore previously cached leaf synthesis logs —
   are unaffected. The confirmation's verdict feeds the driver's
   TIMING-NOT-MET exit gate via `sweep_timing_failures` (empty on met; a
   failed confirmation falls back to the full sweep, whose own result then
   governs). `SYN.WRITE_FINAL_FILES` additionally invalidates the entire
   final table before writing (final files computed 100% against current
   state) and runs `CHECK_VHDL_FILES_CONSISTENCY`: every `entity work.X`
   referenced inside a listed file must be defined by a listed file, turning
   any stale/mixed entity references into an immediate build error instead
   of a downstream GHDL/Vivado analysis failure.
4. **Fallback (rare):** if the confirmation fails timing, it falls back to a full
   planned sweep (which replans from a fresh zero-clk table each iteration, so the
   seeds can't corrupt it), harvests again, and loops back to step 3 with the new
   numbers. Bounded by `SYN.AUTOPIPELINE_MAX_LATENCY_PASSES` (3 total passes); at
   the cap the build fails loudly, advising an explicit `depth=N` pin at the
   unstable call site.

Hard errors (instead of silently-wrong hardware):
- **Divergent `.latency`:** the same AUTOPIPELINE-tagged function instantiated at
  multiple sites with *different* discovered stage counts — legal per-instance in
  the framework, unrepresentable as the single `.latency` int the design's Python
  read. Fix: give each call site its own factory-produced closure, or pin `depth=N`.
- **Call-site set changed between passes:** an AUTOPIPELINE-tagged instance on pass
  2 whose func didn't exist in pass 1 (detected as unseedable) — i.e. Python control
  flow, or closure-captured values encoded in a tagged function's identity, depended
  on `.latency`'s own value. Only sizing *outside* AUTOPIPELINE'd functions may
  depend on it.
- **No settling within the pass cap:** a `.latency`-derived change keeps perturbing
  timing enough to change the discovered stage counts themselves.

Repeated-`PARSE_FILE` support (sys.modules eviction of the design import graph,
per-parse compiler-cache cleanup via `DEL_ALL_CACHES`) lives in `PY_TO_LOGIC.py` —
see `PY_TO_LOGIC_DESIGN.md`'s AUTOPIPELINE section.

The converged harvest has one more consumer: a non-`--comb` `--sim` run hands it
(plus the final per-MAIN latencies) to the native simulator at the end of the build,
which re-imports the design with the cache installed and emulates every latency —
see `pypeline_sim_DESIGN.md` §"Pipelined native sim".

## 6.6 AUTOFSM schedule-and-confirm loop (Pypeline designs only)

`AUTOFSM(func)` is the resource-minimizing dual of AUTOPIPELINE: instead of
cutting one copy of a function's hardware into pipeline stages, it keeps ONE
copy of each distinct operation and runs the function over several cycles. Full
design in [`AUTOFSM_DESIGN.md`](AUTOFSM_DESIGN.md); what matters here is how it
sits around everything above.

**Loop nesting.** `SYN.DO_SWEEP_AND_AUTOPIPELINE` is the whole of §5 + §6.5 factored
into one function; `src/pipelinec` calls it via `SYN.DO_PIPELINED_BUILD`, which is
the dispatch point. When a design contains AUTOFSM call sites,
`AUTOFSM.DO_SCHEDULE_PASSES` wraps it instead:

```
bootstrap parse (AUTOFSM call sites are combinational passthroughs)
for each schedule pass:
    ADD_PATH_DELAY_TO_LOOKUP          <- measure the operations, do NOT sweep
    schedule + bind each AUTOFSM
    install schedules, re-PARSE_FILE  <- call sites become the generated FSMs
    SYN.DO_SWEEP_AND_AUTOPIPELINE     <- §5 sweep + §6.5 AUTOPIPELINE loop
    timing met, or nothing/only-floors blamed?  -> done
    otherwise shrink the blamed FSMs' per-state budget and go again
```

The bootstrap design is deliberately **not** swept: it holds the raw
combinational blob nobody intends to build, so sweeping it would fail timing
pointlessly. It exists only to be measured.

**The CLI driver stays thin.** `src/pipelinec` holds only argparse, argument
validation/combination, propagating flags into module-level settings
(`SYN.HIER_SYN_MODE`, `SIM.SET_SIM_TOOL`, ...), and a top-level sequence of
named calls (parse → comb path → `SYN.DO_PIPELINED_BUILD` → write results →
`SWEEP.PRINT_TIMING_FAILURES` → optional bitstream → optional sim). It defines
no functions and no loops; every loop above lives in the module whose feature
it drives.

**Why a generated FSM needs no sweep support.** It holds non-volatile `Reg`
state, so `CAN_HAVE_ADDED_LATENCY` is already False: the sweep treats it as an
unsliceable atomic block whose measured delay is a soft floor (§4's
`state_regs` reason), and `CALC_TOTAL_LATENCY` reports 0 added latency to its
container. Everything it needs was already there.

**Two delay-model changes** (`SYN.py`), both about *which* functions get delays:

- **`FUNC_SUBTREE_HAS_AUTOFSM`**, consulted alongside
  `FUNC_SUBTREE_HAS_AUTOPIPELINE` in `FUNC_PATH_DELAY_IS_ESTIMABLE`. A stateful
  MAIN with no AUTOPIPELINE anywhere is an atomic span, so *nothing inside it*
  is measured — which would leave the AUTOFSM scheduler seeing zero delays and
  putting the entire function in one state. Only ever true on the bootstrap
  pass; once scheduled, the tag sits on the calling function and the FSM entity
  below it is correctly an atomic span (its one whole-module synthesis measures
  the register-to-register path, i.e. its worst state — exactly the number
  timing attribution needs).
- **`parser_state.func_force_estimated`**, a new escape hatch checked at the top
  of `FUNC_PATH_DELAY_IS_ESTIMABLE`. The bootstrap passthrough looks exactly
  like a measurement frontier (§3) and would otherwise get one whole-blob
  synthesis of precisely the parallel logic the user asked *not* to build — for
  a float64 polynomial, that does not finish in reasonable time. Nothing
  consumes that number: the scheduler works from the individual operations
  underneath, measured and disk-cached as usual.
- **`_AUTOFSM_MUX_ENTITIES`**, folded into `ADD_PATH_DELAY_TO_LOOKUP`'s
  `funcs_to_synth` list. A generated FSM holds state, so it is an atomic span:
  one whole-module synthesis for its register-to-register path, and nothing
  inside it measured. That is right for its fmax number and wrong for its
  operand multiplexers, whose real delay is the single most load-bearing input
  to AUTOFSM's decision about how finely to share — the thing it otherwise has
  to guess at with a flat constant. Those few entities are therefore named
  explicitly and collected for measurement in their own right. They are small —
  one 3-to-8-way multiplexer per shared unit input port — so this is a handful
  of quick runs, not a meaningful build cost.

  They live under `include/pypeline/operators/` intending
  `_IS_PYPELINE_OPERATOR_LIBRARY_CODE` to classify them as non-user code and so
  make each shape cacheable in `path_delay_cache`. That predicate does not
  currently fire, for these or for the soft-operator library it was written for:
  it calls `inspect.getsourcefile` on the callable in
  `pypeline_entity_callables`, which is deliberately the `@hw_func` **wrapper**
  (see `_elaborate_live_func`), and a wrapper's source file is `pypeline.py`.
  An `inspect.unwrap` at that lookup would fix it. Nothing is wrong with the
  delays meanwhile — they are measured every build instead of once.

**Scheduling inside the pass loop.** Each pass now runs AUTOFSM's minimum-area
search rather than a single greedy schedule
([`AUTOFSM_DESIGN.md`](AUTOFSM_DESIGN.md) §3.7). It is pure computation over
already-measured delays — no synthesis, no tool output — and it is bounded by
move and DAG-size caps rather than a wall clock, because the schedule has to
stay a pure function of the source. `--autofsm_no_area_sweep` restores the
greedy schedule. The search is forbidden from returning a schedule whose worst
state is longer than the greedy one's, so it can never spend the timing margin
this loop exists to defend; when a `max_latency=` cap cannot be met the driver
exits nonzero rather than building something slower than the source asked for.
`MAX_SCHEDULE_PASSES` is 6 rather than 4, since a pass may now also be spent
absorbing a freshly measured multiplexer delay.

**Timing attribution.** `AUTOFSM.BLAMED_AUTOFSM_KEYS` reads
`sweep_timing_failures`. When the sweep attributed a blamed function, a
generated FSM entity is exactly the unsliceable atomic block it names. With no
attribution (PYRTL reports no path detail) it falls back to blaming every
AUTOFSM under the failing MAIN — over-blaming costs one extra pass,
under-blaming would silently give up.

**Convergence** is easier than §6.5's. A schedule is a pure function of (the
function's Logic graphs, its operations' delays, the budget scale) and is
independent of the surrounding design, so nothing can oscillate: only an
explicit tightening changes the answer, and tightening is monotonic and capped
(`MAX_SCHEDULE_PASSES`). The loop also stops early when every blamed region is
`at_floor` — one indivisible operation too slow for the clock, which no number
of extra states can fix.

## 7. Test matrix

Fast tests (no `PART()` → PYRTL software timing model, seconds per synth
run) in `src/tests/pypeline_tests/inst/`, registered in `synth_tests.py`:

| test | proves |
|---|---|
| `sweep_comb_test.py` | pure comb MAIN: planner places cuts, meets timing |
| `sweep_two_mains_test.py` | two MAINs: per-main plans, no-attribution fallback |
| `sweep_fsm_autopipeline_test.py` | Reg-FSM main + AUTOPIPELINE region (via `_autopipeline_with_io_regs`): cut subtree is the tagged child, FSM latency stays 0 |
| `sweep_stateful_boundary_test.py` | comb→stateful→comb: cuts stop at the stateful boundary (Finding #1 regression) |
| `sweep_floor_detect_test.py` | unreachable goal: floor predicted & blamed up front, sweep stops after a few syn runs, results written, then `TIMING NOT MET` + non-zero exit |
| `sweep_unpipelinable_test.py` | stateful MAIN with a goal but nothing cuttable: told plainly that autopipelining cannot help (planning time + standalone as-written check FAIL + failing report), one full syn run, `TIMING NOT MET` + non-zero exit |
| `sweep_planless_test.py` | stateful MAIN with a met goal but nothing cuttable: one standalone as-written check synthesis prints PASS, its critical path is NOT stored as the func delay, one full syn run, exit 0 |
| `autopipeline_latency_test.py` | end-to-end factory design (`make_stream_pipeline`, no MAX_IN_FLIGHT) through the full sweep **plus** the §6.5 pin-and-confirm loop: pass 2 runs, harvested `.latency` > 0, seeded confirmation syn passes with no fallback sweep, loop settles within the pass cap (extra realization passes allowed) |

| `autofsm_latency_test.py` | §6.6 end-to-end: schedule pass runs, several same-kind operations fold onto fewer shared units, latency == states + 1, and exactly ONE instance of each shared unit appears in the generated VHDL |
| `autofsm_resources_compare_test.py` | §6.6 area: same design built `--comb` (no sharing) and scheduled, compared by yosys cell count — guards the reason the feature exists |
| `autofsm_timing_iter_test.py` | §6.6 iteration: a deliberately over-packed first schedule misses the clock, the FSM is blamed, its budget is tightened, and a later build passes — with no source change |

Unit/in-process coverage (registered in `elab_tests.py`):
`autopipeline_harvest_test.py` (harvest grouping + divergence, seed two-tier matching
+ call-site-change detection, `CANONICAL_CALLABLE_KEY` determinism, latency
cache/read-flag), `autofsm_unit_test.py` (scheduler binding/dependency/register
invariants, budget→states, floors, byte-identical generated source across
re-elaborations) and `double_parse_file_test.py` (repeated `PARSE_FILE`
equivalence, including an AUTOFSM design).

Real-toolchain validation: the wireguard-fpga ChaCha20-Poly1305 shared build
(`wireguard-fpga/3.build/pypeline_build/build.py --shared --sim --syn_tb`,
Vivado plus cocotb/GHDL) and the multi-clock streamsoc example
(`examples/stream_soc/cpu/hardware/top.c`).

## 8. Operator QoR: raw VHDL vs. soft-operator-library implementations

`src/tests/pypeline_tests/op_qor_bench.py` measures pipelined (sliced) fmax
for candidate implementations of `PLUS`/`MINUS`/`INFERRED_MULT`/`GT`/`GTE`/
`LT`/`LTE`/`EQ`/`NEQ`, across a width matrix including wireguard-fpga's actual
instantiated widths (mixed `uint32×uint3`, `uint32×uint4`, `uint16×uint1`,
`uint8×uint1`, plus `uint8/16/32/64` same-width pairs). It exists because the
soft-operator-library default flip (NEGATE, compares, DIV, MOD, variable shift
moved off SW_LIB/cpp onto ordinary Pypeline HDL) was never QoR-validated, and
wireguard-fpga was then seen missing timing with pipeline depth no longer
helping (40→52 stages barely moved fmax).

**That regression is resolved -- see "Outcome" below.** The cause was the
comparator implementation, and it hurt twice over: the old flavor was both
slower in silicon *and* badly over-modeled, so the sweep planner densified
the wrong function while also paying real delay.

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
  "Known blind spot").
- **`--tool vivado`**: `PART("xc7a200tffg1156-2")` (wireguard-fpga's actual
  part), real OOC synthesis, minutes per case. Ground truth.

`--ops` / `--widths` / `--impls` narrow the matrix; results land in
`op_qor_results_<tool>.csv`, one row per `(op, impl, widths, n_cuts)`,
resumable by `(tool, op, impl, l_type, r_type)`. `--impls` (added 2026-08) is
the one to reach for when following up a PyRTL finding with a scoped Vivado
head-to-head, e.g. `--tool vivado --impls soft_cmp_sub_swapped,soft_cmp_prefix`
-- without it, a full `--tool vivado` run re-measures every impl in
`CMP_IMPLS`/`PLUS_MINUS_IMPLS`/etc., which is minutes-per-case across the
whole matrix.

Four harness properties that are easy to get wrong, and were:

- **`--stop` is exclusive.** `SYN.py` stops once `coarse_latency >=
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
  canonical `BIN_OP_GT_*`/`BIN_OP_GTE_*` name a soft build would use -- see
  "Cache hygiene" below.

### Comparator results (Vivado, xc7a200tffg1156-2)

Best sliced fmax (`n_cuts ≥ 1`), winner first:

| op | widths | ranking (MHz) |
|---|---|---|
| `GT` | `uint16×uint1` | **soft_fixed 696** · soft_bitwise 572 · raw_revived 560 · soft_default 521 |
| `GT` | `uint32×uint32` | **soft_fixed 530** · raw_revived 521 · soft_bitwise 440 · soft_default 419 |
| `GT` | `uint32×uint3` | **soft_fixed 585** · raw_revived 527 · soft_bitwise 524 · soft_default 419 |
| `LTE` | `uint16×uint1` | **raw_revived 687** · soft_bitwise 561 · soft_fixed 530 · soft_default 521 |
| `LTE` | `uint32×uint32` | **soft_fixed 530** · raw_revived 521 · soft_bitwise 424 · soft_default 419 |
| `LTE` | `uint32×uint3` | **raw_revived 579** · soft_fixed 530 · soft_bitwise 510 · soft_default 419 |

`soft_fixed` (the operand-swapped flavor) wins 4 of 6; `raw_revived_sliced`
(the otherwise-dead RAW_VHDL hand-pipelined comparator,
`RAW_VHDL.py:3050-3665`) wins the other 2 and is genuinely competitive --
but it *degrades when first sliced* (`GT uint32×uint32`: 449 MHz comb → 367
MHz at 1 cut, recovering only by 7 cuts), which is the wrong shape for a
deeply pipelined design. **`soft_default` finishes last in all six cases.**

### Why the old comparator was over-modeled

Every cached delay is a full out-of-context register-to-register measurement:
clk→Q + routing + logic + setup. A *single* bitwise op measures the same
**1.019 ns** regardless of width (`BIN_OP_AND_uint1_t_uint1_t` ==
`BIN_OP_AND_uint32_t_uint32_t` == 1.019 ns) -- that is one logic level plus a
fixed floor. `ESTIMATE_HIER_PATH_DELAYS` derives a hierarchical func's delay by
walking the topological path and adding each submodule's **full** cached delay,
so a chain of K leaves accumulates roughly (K−1) copies of a floor that exists
only once in real silicon.

That penalty applies only to implementations that decompose to gate level:

| impl | est_op_ns | measured @0 cut | est/meas |
|---|---|---|---|
| `soft_fixed` (swapped) | 2.40 | 2.34 | **1.03×** |
| `soft_default` (un-swapped) | 7.60 | 4.37 | **1.74×** |
| `soft_bitwise` | 115.60 | 4.34 | **26.6×** (35× avg across widths) |
| `raw_revived_sliced` | *(none)* | 2.23 | measured leaf, never estimated |

(`GT uint32×uint32`.) `make_soft_cmp_sub` computes one fixed `diff = a - b`
and derives all four ops from it, which forces an extra `is_zero` term for
`GT`/`LTE` -- `1 if diff == 0 else 0` becomes `BIN_OP_EQ` + `MUX_uint1_t`, and
`(1-neg) & (1-is_zero)` adds a 1-bit `MINUS` and an `AND`. Three gate-level
ops, each charged a full 1.019 ns, is most of the 74% inflation.
`make_soft_cmp_sub_swapped` instead reorders operands per op
(`a>b ≡ neg(b-a)`, `a>=b ≡ !neg(a-b)`, `a<b ≡ neg(a-b)`, `a<=b ≡ !neg(b-a)`),
so every op is one subtract plus one sign-bit read -- matching the structure
the old SW_LIB C generator used (`GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE`). Its
generated entity contains exactly one submodule (`BIN_OP_MINUS_int33_t_int33_t`
for a 32-bit compare) and models at 1.03×.

`soft_bitwise` is the extreme case: fine in hardware (440 MHz sliced) but
modeled 27-47× too slow, because it is 32 serial 1-bit levels. It is not
registered by default; anything opting into it would be wildly over-pipelined.

**No estimator scaling constant was added.** The default models at 1.03×; the
fix belonged in the implementation, not in a correction factor. A constant
would have papered over `soft_default` while leaving `soft_bitwise` off by 35×.

### Outcome

**Shipped:** `soft.py:register_soft_cmp` registers
`make_soft_cmp_sub_swapped` for all four ops (previously `make_soft_cmp_sub`).
`make_soft_cmp_sub` is unchanged and kept for QoR comparison. Compares stay
soft by default -- `raw_revived_sliced` was measured head-to-head and does not
justify reverting `C_BUILT_IN_FUNC_IS_RAW_HDL`. No change to `EQ`/`NEQ`/
`MINUS`, which remain correctly raw-HDL by default.

Historical WireGuard baseline before mini-sweep boundary coalescing, shared
encrypt+decrypt syn_tb build on
`xc7a200tffg1156-2`, with that one change:

```
chacha20_pipeline_shared: met timing, 30 slice(s) built (31 pipeline stages), iterations=6
PASS decrypt_dataflow_shared: 91.17 MHz vs 80.00 MHz goal (confirmation run)
```

**80 MHz met at 30 slices / 31 stages**, against a failing baseline of
62.3 MHz at 40 slices / 41 stages. The plateau itself was never the bug -- the sweep's escalation ladder
(densify → measured fallback → minisweep → lock) is designed to climb out of
one, and does, in 6 iterations. What broke it was feeding that ladder a
comparator that was simultaneously slower and 74% over-modeled.

That 30-slice result used the old per-instance input-plus-output lock policy;
it is retained as a regression baseline, not as the target for the
topology-aware boundary policy described above.

**Current topology-aware result (fresh generated output, 2026-08-23):** the
same shared `build.py --shared --sim --syn_tb` flow selected one internal
half-way `block_step` slice on all ten instances, then found nine direct
producer-to-consumer edges and selected only the first nine producer output
banks. No input bank was selected and the final block has no output bank.
The schema-5 trace therefore realizes **10 + 9 = 19 slices / 20 stages**,
rather than the old 30/31 shape. The pinned Vivado confirmation met 80 MHz at
**84.45 MHz** (0.658 ns MET slack; 11.796 ns data path), and the cocotb/GHDL
shared encrypt+decrypt test exited zero with no test failures. This is a
physical integration result, not a Divider-specific rule.

### Cache hygiene

`path_delay_cache/.../BIN_OP_{GT,GTE,LT,LTE}_*.delay` entries have mixed
provenance: some predate the operator overhaul (measuring the SW_LIB
C-generated comparator), some were written by this harness under
`FORCE_RAW_INT_CMP_FOR_QOR_BENCH` (measuring the RAW_VHDL one) -- two
different implementations under one canonical entity name. They are inert
today, because with compares soft by default no build ever generates a
`BIN_OP_GT_*` entity to look up. They are worth deleting anyway: if compares
were ever flipped back to raw, the SW_LIB-era values would silently supply
numbers for an implementation that no longer exists.

### Known blind spot: primitive-aware operators (pyrtl only)

PyRTL's estimate is a generic gate-delay model with no awareness of
FPGA-specific fast-path primitives. This was expected to matter for
`INFERRED_MULT` (DSP inference) and does -- soft multiplier variants are only
compared against each other under `--tool pyrtl`, and `INFERRED_MULT` stays on
the inferred path regardless, because wireguard-fpga specifically needs its
multiplies inferred.

**The same blind spot applies to `PLUS`.** The pyrtl sweep shows
`soft_carry_select` beating `raw_default` by a wide margin (`uint32 + uint32`
at 6 cuts: 219 MHz vs 119 MHz), but Xilinx's CARRY4 gives the raw adder a
dedicated fast-carry chain a generic gate model cannot represent. `PLUS` was
deliberately left on its raw default rather than flipped from that data. It is
also not implicated in the wireguard regression: chacha20's quarter round uses
only `+`, `^`, `|` and *constant* rotates, none of which the operator overhaul
touched (constant shift amounts resolve to `CONST_SL/SR_<n>_<type>` built-ins
before any registry lookup -- only variable shifts reach the operator
registry). Re-measure `PLUS` under `--tool vivado` before drawing any
conclusion from the pyrtl numbers.

### Naming cleanup (2026-08): `soft_<op>_<algorithm>`, not `soft_<algorithm>_<op>`

Every soft-operator factory and its generated hardware entity name now leads
with the op family, algorithm second -- e.g. the default comparator's
generated entity is `soft_cmp_sub_swapped_...`, not the old
`soft_sub_cmp_swapped_...`. The old order read as an overloaded
*subtraction* operator rather than a subtract-based *comparator* (`sub`
there has always meant "built via subtract," never "substituted"). Renamed
throughout: `make_soft_cmp_sub`/`_sub_swapped`/`_bitwise` (soft_cmp.py),
`make_soft_add_ripple`/`_carry_select` and `make_soft_sub` (soft_add.py),
`make_soft_mult_shift_add`/`_karatsuba` and `make_soft_add_tree_shifted`
(soft_mult.py), `make_soft_div_radix[4]`/`make_soft_mod_radix[4]` and their
`_signed` counterparts (soft_div.py), `make_soft_shift_barrel_sl/sr` and
`make_soft_rot_barrel_l/r` (soft_shift.py). Pure rename, no behavior change --
verified via the full `synth` test category (58/58 passing, including real
Vivado builds) and the native-sim golden tests. `path_delay_cache/` is
unaffected: it is keyed on entity name, but every cached file (2530 across
all tool subdirectories) is a built-in leaf (`BIN_OP_*`/`UNARY_OP_*`/`MUX_*`/
`CONST_*`/`BIT_*`) -- no soft-op composite entity, old or new name, has ever
had its own cache entry, because a soft op's *leaves* are what get cached,
and those leaf names don't change when the soft op around them is renamed.

### fmax follow-up (2026-08): a parallel-prefix comparator beats the default under PyRTL

Revisited whether a better-autopipelining comparator exists, since the
comparator sits on the soft divider's critical path (a 32-bit radix-4 divide
instantiates ~48 of them).

**The recorded PyRTL sweep looked corrupted but wasn't.** GT/uint32/
`soft_cmp_sub_swapped` in `op_qor_results_pyrtl.csv` goes
10.88ns@0cuts → **18.11ns@1cut** → 15.51 → 12.50 → 12.64 → 10.72 → 10.72
(identical at 5 and 6 cuts) -- the signature of "the harness re-measured the
same design twice." Verified directly (re-running single cases through
`pipelinec`, diffing generated VHDL) that it is real, distinct data at every
cut count (`-- Pipeline Slices: [...]` differs every time, the tool's own log
says `Same or worse timing result...` at 1 cut). The 0→1cut dip: the coarse
sweep places cuts at naive even clock-count fractions
(`GET_BEST_GUESS_IDEAL_SLICES`), not by where delay concentrates, and at 1
cut that lands a register mid-way through the single 33-bit `BIN_OP_MINUS`'s
carry chain, splitting it unevenly under PyRTL's flat per-op delay model. The
5==6-cut plateau is the opposite effect: once cuts have isolated the true
bottleneck segment, further cuts land in already-zero-delay regions and stop
changing the number (a real slicing floor). Lesson: judge a comparator by its
whole curve, never a single `n_cuts` point, and don't assume non-monotonic
data is a harness bug without checking the generated VHDL first.

**Three new candidates were built, sim-verified (directed edges + signed
sign-boundary crossings + mismatched operand widths), and elaboration-gated:**

- `make_soft_cmp_borrow` -- explicit LSB-to-MSB borrow-propagate chain
  instead of the HDL `-` operator, reading the sign as the top difference bit
  rather than a final borrow-out (those are NOT the same bit -- a
  two's-complement sign bit is `x_msb^y_msb^borrow-in`, not the borrow that
  ripples past it; conflating them broke only the signed sim_call sweep).
  **Measured 7-8x WORSE than the default** (uint32 GT @0cuts: 79.86ns vs.
  10.61-10.88ns). Not because the sum-bits hypothesis was right (a
  subtractor's critical path is its carry chain regardless of whether sum
  bits are also produced) but because hand-unrolling 31 bits into individual
  bitwise `@hw_func` leaf operations forfeits the flat/lumped delay PyRTL
  gives the native `-` operator and prices 31 serial gate levels
  individually instead -- the exact same "primitive-aware operators (pyrtl
  only)" blind spot documented above for `PLUS`/CARRY4, now confirmed to
  apply to comparators too. Not evidence of worse real hardware; a `--tool
  vivado` re-measurement (which infers fast-carry primitives from bitwise
  ripple patterns) would be needed to actually rank it.
- `make_soft_cmp_prefix` -- log2(n)-deep parallel-prefix magnitude compare,
  combining per-bit `(gt,lt)` codes with an associative leader-select
  operator, one `@hw_func` per tree level (same per-level-entity idiom that
  measurably helped `make_soft_mult_shift_add`'s estimation accuracy, section
  above). **Measured BETTER than the default at every PyRTL cut count**,
  confirmed across all 24 measurable (op, width-pair) combinations in the
  full sweep (GT/GTE/LT/LTE × uint16/32/64, plus mismatched uint32×uint3/4;
  the two narrowest pairs have no `n_cuts>=1` default data to compare against
  since the default's design is too small to slice at all there) -- 24/24
  wins, 0 losses, 0 ties. Representative point, uint32 GT: 13.66/7.79/6.83/
  6.75/4.84/4.24/4.16 ns at cuts 0-6 vs. the default's
  10.88/18.11/15.51/12.50/12.64/10.72/10.72 -- roughly 2-2.5x better once
  pipelined. The per-level entity boundary is doing real work here: unlike
  the borrow chain, PyRTL prices each level's small 2-bit combine as its own
  submodule rather than unrolling one giant flat per-bit scan.
- `make_soft_cmp_chunked` -- c-bit chunks compared in parallel (each chunk's
  *internal* compare a small serial bitwise scan), reduced across chunks via
  the same tree `make_soft_cmp_prefix` uses. uint32 GT, chunk_bits=8:
  29.48/16.83/12.01/9.20/8.31 ns at cuts 0-4 -- beats the default at
  n_cuts>=2, loses at 0-1, loses to the prefix tree throughout (each chunk
  still pays the serial-scan PyRTL penalty internally, just amortized over
  fewer/wider chunks).

**Vivado result (xc7a200tffg1156-2, all 32 (op, width) combinations
measured): confirms the PyRTL direction, but not unconditionally.**
`soft_cmp_prefix` wins 28/32 combinations at `n_cuts>=1` against the then
default `soft_cmp_sub_swapped`. The win is decisive and *widens* with
operand width across all four ops -- uint32 and uint64, GT/GTE/LT/LTE all
favor `soft_cmp_prefix`, e.g. uint64 GTE up to 40% faster at deep cuts. But
at the two narrowest widths (uint8, uint16) **GTE and LTE specifically
lose** to `soft_cmp_sub_swapped`, consistently at every cut count, not
noise (uint16 GTE: `soft_cmp_sub_swapped` 1.83-1.97ns vs. `soft_cmp_prefix`
2.15-2.79ns at every measured cut). GT/LT still win even at those narrow
widths -- only the non-strict ops regress. The mechanism:
`soft_cmp_sub_swapped`'s GTE/LTE cost is identical to its GT/LT cost (same
one-subtract-one-sign-bit structure, just operand-swapped), and Vivado
already optimizes that single small subtract extremely well at 8-16 bits
(~1.7-2ns) -- `soft_cmp_prefix`'s fixed per-level tree overhead (extra
`MUX_uint2_t` entities per level) doesn't pay for itself until the base
comparator is wide enough to actually be the bottleneck.

**Outcome: promoted as the unconditional library default.**
`soft.py:register_soft_cmp` now registers `make_soft_cmp_prefix` for all
four ops (previously `make_soft_cmp_sub_swapped`) -- a net win across the
full measured matrix (28/32), accepted with eyes open on the narrow-width
GTE/LTE tradeoff: those 4 losing combinations are real, not noise, and
notably invisible to the PyRTL-only sweep (PyRTL's 24/24 never flagged
them; every one of its measured combinations favored `soft_cmp_prefix`,
including the narrow-width GTE/LTE cases where Vivado disagrees -- see
"Known blind spot" above; PyRTL's flat delay model doesn't distinguish "a
tiny subtract Vivado optimizes very well" from "a larger one it doesn't,"
so it missed the exact crossover Vivado exposed). Since
`register_soft_cmp` is called automatically by
`register_sw_lib_replacements` (`PY_TO_LOGIC.PARSE_FILE`), this changes the
comparator every Pypeline build gets by default. `make_soft_cmp_sub_swapped`
remains available via `register_soft_cmp_sub_swapped` for a design known to
be narrow-width-GTE/LTE-heavy, where it is still the Vivado-confirmed
better choice. `AUTOFSM.py`'s `_SOFT_FACTORY_FOR_OP` was deliberately left
on `make_soft_cmp_sub_swapped` -- that map selects for even decomposition
as FSM resource-sharing candidates, a different criterion its own comment
calls out as "deliberately not" about speed, which this investigation never
measured. See `soft_cmp.py`'s module docstring and both registration
functions' docstrings in `soft.py` for the up-to-date numbers.

Elaborator constraints newly hit while building these (beyond the existing
divider-work list -- `break` unsupported, no tuple loop variables, no
tuple-unpacking of closure constants, closure values limited to
C-types/ints/bools/None/callables/lists-tuples thereof): a call target must
be a bare name, not a subscript (`leaf_fns[j](...)` where `leaf_fns` is a
Python list of distinct per-index closures fails with `AttributeError:
'Subscript' object has no attribute 'id'` -- give each differently-shaped
callable its own bare-name local instead of indexing into a list of them);
and a slice used as a call argument must be assigned to a typed local first
(`f(ae[hi:lo], ...)` fails the same way -- write `x: t = ae[hi:lo]` then
`f(x, ...)`).

## 9. Soft barrel shifter: mux count is the only lever

`include/pypeline/operators/soft_shift.py`'s variable-amount barrel shifter
(`make_soft_shift_barrel_sl`/`make_soft_shift_barrel_sr`) is a chain of stages, each a
`if amount[i]: result = shifted` conditional assignment beside a *constant*
shift (`result << (1<<i)`). This investigation started from the hypothesis
that mirrors the multiplier investigation above: does the barrel have the
same uniform-width-stage mispricing the flat multiplier had, where genuinely
cheaper early levels get priced the same as the expensive final one?

**The hypothesis does not hold, for a structural reason specific to muxes.**
The constant shift beside each stage is pure rewiring (`CONST_SL/SR_<n>_<type>`
built-ins, zero delay, PY_TO_LOGIC.py:4293-4311) -- so a barrel shifter is
*exactly* a chain of raw-HDL `MUX_<type>` leaf entities and nothing else
(PY_TO_LOGIC.py:3573-3592). Under the PyRTL tool used by this investigation,
**every mux in a design shares one cached delay, regardless of width or
type**: `GET_CACHED_LOGIC_FILE_KEY` uses the collapsed literal key `"mux"`,
and the measured `path_delay_cache/pyrtl_20nm_0ff/syn/mux.delay` value is
1.640 ns for every width. (`DEVICE_MODELS` instead canonicalizes by packed
width; see `DEVICE_MODELS_DESIGN.md`.) An unsplit MUX is one logic level and
the initial landscape treats it atomically; the later bounded packed-bit
refinement is feedback-only and was not active in these PyRTL barrel results.
So initial stage pricing *is* uniform -- but for a chain of genuinely
identical muxes that is correct, not a mispricing: there is no analogue of the multiplier's
narrower-early-level structure to expose, and splitting a stage into a
narrower "active" sub-mux plus a wide passthrough (as a narrow analogy to
the multiplier's per-level-width fix would suggest) prices *worse* --
two 1.640 ns muxes instead of one -- no matter how cheap it is in real
silicon.

**Consequence: the only lever that matters is how many serial muxes the
barrel has.** It sets comb delay, the slicing floor (one mux, 1.640 ns/2.66
ns on Vivado -- see table below), and the cut count needed to reach that
floor, all simultaneously.

**The shipped shape had one dead stage.** `amount_bits =
max(1, n_bits.bit_length())` gives 6 stages for `uint32_t`, though shift/
rotate amounts 0..31 need only 5 -- the 6th stage (shift-by-32) can only ever
produce zero. Fixed to `amount_bits = max(1, (n_bits - 1).bit_length())`.
This mirrors what the C flow's SW_LIB generator already does correctly
(`shift_bit_width = min(max_shift.bit_length(), right_unsigned_width)` with
`max_shift = left_width - 1`, `SW_LIB.py:7081-7083`) -- the Pypeline soft
library had regressed behind its own C-flow sibling.

### Structural variants tried, PyRTL `uint32_t`, `--coarse --sweep --start 0 --stop 9`

| variant | shape | comb ns | floor ns | cuts to floor |
|---|---|---|---|---|
| baseline (was shipped) | 6 stages (dead 6th stage) | 7.84 | 1.64 | 5 |
| **minimal stages (now shipped)** | 5 stages, no dead stage | **6.94** | **1.64** | **4** |
| masked/AND-OR select | 5 stages, `(shifted&mask)\|(result&~mask)` instead of a mux | 6.94 (tie) | 1.91 (worse) | never reaches 1.64 |
| one-hot decode + OR-reduce | all n shifted versions in parallel, one-hot select | 24.54 | 3.42 | far worse throughout |
| reversed stage order | minimal stages, largest-shift-first | 6.94 (tie) | 1.64 | 4 (tie) |
| one `@hw_func` per stage | minimal stages, composed chain instead of inline loop | 6.94 (tie) | 1.64 | 4 (tie) |
| `VAR_REF_RD` array-index select | `opts[k]=v<<k` for all k, `result=opts[amount]` | 6.94 (tie) | 1.64 | 4 (tie) |

Minimal-stage-count wins outright at every cut count and is never worse than
any other shape measured. Reversed order, per-stage composition, and
array-index select all tie it exactly -- confirming, directly from measured
data, that stage *count* is what governs delay; composition style,
ordering, and codegen shape do not. Two results are worth flagging on their
own:

- **The masked/AND-OR variant ties on comb but is measurably worse once
  sliced** (1.91 ns vs 1.64 ns -- never reaches the true floor within 8
  cuts measured). Its estimated delay (`est_op_ns` = 6.3) *under-predicts*
  its own measured comb delay (6.94), the mirror image of the multiplier's
  over-prediction problem -- and an under-prediction is worse for cut
  placement, since `BUILD_SLICE_LANDSCAPE`'s even-fraction coarse slicer
  places cuts assuming the estimate is trustworthy. This is a caution
  against judging a soft-op redesign by comb delay (or by a delay-model
  estimate) alone; §8's "the decision metric is pipelined per-stage delay
  at n_cuts >= 1, not comb delay at n_cuts = 0" rule applies here too, and
  this round is direct evidence for it, not just the comparator round's.
- **One-hot decode is decisively the worst shape**, because "free rewiring"
  for the n parallel shifted versions does not make the *selection* free:
  a one-hot decode is n equality comparators, and the OR-reduce is a wide
  tree -- both real logic, unlike a barrel's single-bit mux select per
  stage.

### Confirmed on real Vivado hardware (`xc7a200tffg1156-2`)

The minimal-stage-count result was not left as a PyRTL-only estimate --
re-run head-to-head against the shipped baseline shape, `--coarse --sweep`,
`uint32_t`:

| cuts | baseline (6 stages) ns | minimal (5 stages) ns |
|---|---|---|
| 0 (comb) | 2.660 | 2.640 |
| 1 | 1.930 | 1.930 |
| 2 | 1.460 | 1.460 |
| 3 | 1.460 | 1.460 |
| 4 | 1.460 | **1.300 (floor)** |
| 5 | **1.300 (floor)** | 1.300 |
| 6 | 1.300 | 1.300 |

Same shape as PyRTL: minimal-stage-count reaches the true floor at 4 cuts
instead of 5, and is never worse at any cut count. **The comb-delay gap is
much smaller on real Vivado than PyRTL predicted** (0.8% vs PyRTL's 12.9%)
-- real synthesis evidently optimizes away much of the dead stage's
unreachable logic during its own passes, where PyRTL's flatten-only flow
does not. This is exactly why the decision metric is the full sweep, not
comb delay on either backend alone: the *cut-count-to-floor* signal held
up identically on both tools even though the comb-delay magnitude did not.

### Bidirectional shift/rotate: one funnel barrel instead of four

Pypeline had no variable-amount rotate at all before this round (`rotl`/
`rotr` are constant-only -- `PY_TO_LOGIC.py:4778-4798`'s `_require_const`).
Three new factories in `soft_shift.py`:

- `make_soft_rot_barrel_l` / `make_soft_rot_barrel_r` -- the same minimal-stage
  barrel, using the constant `rotl`/`rotr` built-in (also free rewiring, VHDL
  `rol`/`ror`) as each stage's operation instead of a shift. Rotation is mod
  `n_bits`, so this needs no oversize guard and no dead stage at all.
- `make_soft_shift_rot` -- a unified 4-mode primitive (`direction` x
  `rotate`), answering the motivating C idiom
  (`(n<<d)|(n>>(N-d))` for rotate, composed from up to four separate barrel
  calls plus a subtract plus an OR) with **one** left-shift-only funnel
  barrel: `hi = rotate ? v : 0`; fold `v`/`hi` into a `2n`-bit word (`concat`,
  free rewiring, with the concat order and effective shift amount chosen by
  `direction`); barrel-shift that word left; slice out the correct half.
  The identity (right-shift-by-d == left-funnel-shift-by-(n-d), taking the
  same upper half) was verified both by direct calculation and by the
  correctness gate below.

Measured PyRTL, `uint32_t`, funnel vs. a faithful Pypeline transcription of
the pasted four-barrel C idiom (both built from the shipped minimal-stage
barrels):

| cuts | four-barrel composition ns | funnel (`make_soft_shift_rot`) ns |
|---|---|---|
| 0 (comb) | 11.910 | 10.860 |
| 1 | 8.950 | 8.260 |
| 2 | 6.300 | 6.290 |
| 3 | 4.660 | 4.290 |
| 4 | 4.290 | 4.290 |
| 5 | 3.650 | **2.960 (floor)** |
| 6 | **2.960 (floor)** | 2.960 |

The funnel is equal-or-better at every cut count and reaches the floor one
cut sooner, at roughly half the total mux-entity count (one barrel instead
of up to two run in parallel plus a merge), matching the area argument made
before landing.

### Correctness

Every shipped factory (`make_soft_shift_barrel_sl/sr`, the new rotl/rotr, and
`make_soft_shift_rot`) is exhaustively swept in
`src/tests/pypeline_tests/inst/soft_ops_test.py` over tiny widths
(1, 2, 3 bits, where the amount-width formula is most likely to be off by
one) plus `uint8_t`, both directions, and (for `make_soft_shift_rot`) all
four `direction`/`rotate` combinations. A signed sweep of
`make_soft_shift_barrel_sr` against Python's arithmetic `>>` was also checked and
found already correct: each stage's *constant* shift lowers through VHDL's
`numeric_std.shift_right`, which is arithmetic (sign-extending) for a signed
operand type by construction (`RAW_VHDL.py:4251-4310`) -- so no separate
signed barrel implementation was needed, unlike the signed-multiply defect
found in the mult round.

## 10. Karatsuba base-case threshold: no split beats every split, below 16 bits

Two multiplier shapes exist in `soft_mult.py`: `make_soft_mult_shift_add` (the
default, `INFERRED_MULT` registered for `any_uint_t x any_uint_t` by
`register_soft_mult`) and `make_soft_mult_karatsuba(l_t, r_t, threshold)`, a
recursive Karatsuba split that falls back to shift-and-add once an operand
narrows to `threshold` bits. That threshold had never been measured -- it was
`8` from when the factory was written, and every prior comparison (this doc's
mult-recursion work, `op_qor_bench.py`'s matrix) ran at that one fixed value.

That matters because `threshold=8` is not even the shallowest possible
Karatsuba shape at 16 bits: `uint16 x uint16` at `T=8` still recurses once
more (its 9-bit middle term splits again), where `T=9..15` stops immediately.
The prior verdict on this doc's multiplier round -- "Karatsuba loses to
shift-and-add at every cut count" -- was measured against a shape carrying a
gratuitous extra recursion level, never the cheapest one available.

### Only a handful of thresholds build distinct hardware

`threshold` only changes shape at specific values; every integer between two
of those values builds byte-identical hardware (confirmed via
`CANONICAL_CALLABLE_KEY`, which two different thresholds map to the *same*
hash whenever they produce the same recursion tree). At `uint16`, for
example: `T=6` and `T=7` are identical; `T=9..15` are identical; `T>=16` all
degenerate to `make_soft_mult_shift_add` directly (Karatsuba never actually
fires). Sweeping every integer would re-measure the same design up to 15x
over; `op_qor_bench.py`'s `karatsuba_threshold_reps(n_bits)` enumerates one
representative per distinct class instead.

`threshold < 3` does not terminate: a 3-bit operand splits into `half=1` /
`hi=2` with `mid = max(1,2)+1 = 3`, so the middle sub-multiply is the same
width as its parent and recurses forever (confirmed: `RecursionError` at
`threshold=2`). Fixed with an explicit guard in `make_soft_mult_karatsuba`.

### Sweep, PyRTL `--coarse --sweep`, uint8 and uint16 (in scope this round; 32/64-bit widths not yet measured)

Best sliced fmax (`n_cuts >= 1`), and the est/measured ratio at `n_cuts=0`
(§8's over-prediction mechanism -- a hierarchical soft implementation sums
every leaf's full measured delay with no cross-module optimization credit,
so deeper hierarchies over-predict worse):

| width | threshold | best fmax (cuts>=1) | comb ns | est/measured @ 0 cuts |
|---|---|---|---|---|
| 8 | T=3 | 32.75 MHz (1 cut) | 43.46 | 3.27x |
| 8 | T=4 | 34.20 MHz (1 cut) | 39.37 | 2.68x |
| 8 | T=5 | 35.94 MHz (1 cut) | 35.74 | 2.14x |
| 8 | **T=8 (=no split)** | **61.41 MHz (1 cut)** | 23.31 | 1.21x |
| 16 | T=3 | 27.66 MHz (3 cuts) | 70.80 | 2.99x |
| 16 | T=4 / T=5 | 28.45 MHz (3 cuts) | 67.33 | 2.61x |
| 16 | T=6 / old default T=8 | 38.33 MHz (3 cuts) | 62.71 | 2.28x |
| 16 | T=9 | 39.77 MHz (3 cuts) | 54.95 | 1.95x |
| 16 | **T=16 (=no split)** | **77.73 MHz (3 cuts)** | 38.73 | 1.22x |

**The result is simpler than the mult-recursion round's per-level-width fix:
there is no interior optimum.** Comb delay falls monotonically as `threshold`
rises (confirming the structural model directly), but sliced fmax rises
monotonically right along with it, all the way to the trivial `T=n_bits`
case -- Karatsuba's recombination cost (`a_lo+a_hi`, `b_lo+b_hi`, a 3-way
`z1_full - z0 - z2` subtract, and a 3-way shifted sum, all at or near full
`out_t` width) is a fixed-ish overhead per split that a 16-bit-or-smaller
design's actual multiply work never earns back. Splitting is pure loss in
this range, at every cut count measured, not just at `n_cuts=0`.

Sanity control confirmed the harness itself: `soft_karatsuba_t{n_bits}` rows
are bit-identical (same measured ns at every cut count) to the corresponding
`soft_shift_add` rows -- as they must be, since `T>=n_bits` makes
`make_soft_mult_karatsuba` return `make_soft_mult_shift_add` directly.

### Outcome

**Shipped:** `make_soft_mult_karatsuba`'s default `threshold` raised from `8`
to `16`. `register_soft_mult_karatsuba` gained a `threshold=None` parameter
(forwarded via `functools.partial` when set, so the emitted entity stays
readably named rather than falling into `_callable_canonical_name`'s opaque
lambda-hash fallback) so a caller can still reach any measured or unmeasured
threshold explicitly.

Deliberately conservative: 16 is the ceiling of what was actually measured
this round, not an estimate of some wider optimum. Raising the default only
removes recursion this data directly shows is harmful at widths <= 16 bits;
it cannot, by construction, make an untested 32- or 64-bit design recurse
*less* than it otherwise would have (a 32-bit multiply's first split still
produces two 16-bit halves, exactly where this round's data ends). Whether a
real (non-degenerate) optimum threshold exists above 16 bits -- the original
hypothesis motivating Karatsuba's presence in this library at all -- is still
open and was explicitly out of scope this round.

### Correctness

`test_soft_karatsuba_mult` covers the `threshold<3` guard (must raise);
`test_soft_mult_karatsuba_threshold_override` covers
`register_soft_mult_karatsuba(threshold=...)` end-to-end through native sim,
both the override and default paths. Every threshold class from `T=3` to
`T=n_bits` was also swept for pure correctness (native sim, `uint8`/`uint12`/
`uint16`, corners plus random pairs): 0 mismatches at every threshold --
Karatsuba's correctness does not depend on where the recursion bottoms out,
only its QoR does.
