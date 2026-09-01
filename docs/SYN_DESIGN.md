# Autopipelining and the Throughput Sweep

How PypelineC turns combinational logic into pipelines to meet an fmax goal.

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section rather
> than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## 0. Who does what

| file | role |
|---|---|
| `src/SYN.py` | Shared infrastructure: timing params (`TimingParams`, slices, IO regs), the pipeline map (`GET_PIPELINE_MAP`), recursive slicing (`SLICE_DOWN_HIERARCHY_...`), per-function path delay collection (`ADD_PATH_DELAY_TO_LOOKUP`), the coarse sweep engine (`DO_COARSE_THROUGHPUT_SWEEP`, used by `--coarse` and mini-sweeps), entity writing, and the `DO_THROUGHPUT_SWEEP` entry point. |
| `src/SWEEP.py` | The planner: cut subtrees, slice landscapes, floor prediction, cut planning, and the synthesis-feedback refinement loop (`DO_PLANNED_THROUGHPUT_SWEEP`). |
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

## 1. How pipelines physically form

Registers physically exist in two forms:

1. **Leaf slices** — a raw HDL leaf (no submodules, e.g. `BIN_OP_PLUS`) with
   `TimingParams._slices = [0.5]` becomes a 2-stage adder, carry chain broken
   at 50% of its delay (a slice value is a fraction 0.0–1.0 of that module's
   *own* delay, but what that fraction turns into differs by leaf kind). Leaf
   latency = `len(_slices)`:

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
     equal-width conversion looks like it throws away information, but it
     doesn't: once a boundary is registered, each stage computes its own
     chunk from scratch off a registered 1-bit carry-in, so that stage's
     delay depends only on its own chunk width, not on where along the
     leaf's *unregistered* delay axis the cut nominally sits. Since real
     per-width delay is monotonic (and concave — sky130 measured
     `D(10)=2.607ns`, `D(34)=3.851ns` for a 34-bit `MINUS`, nowhere near
     linear), minimizing the worst stage's delay for a given stage count
     means equal-width chunks, full stop — an uneven, delay-fraction-derived
     boundary measurably misses real sky130 timing goals that the plain
     equal-width split meets, even when it looks better for one isolated
     leaf in isolation. Locally optimal per-leaf boundaries do not reliably
     predict whole-design QoR after real lowering (fanout and
     max-capacitance effects dominate there instead), so exact per-leaf
     boundaries remain available as an internal placement mechanism
     (`exact_bit_boundaries`) rather than the default allocation policy.
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
     top of that, after a real measurement fails.

   A single mux select bus registered *on top of* an already-registered,
   wider parallel sibling can materialize a real register while adding
   **zero pipeline depth**: `SWEEP.GET_PIPELINE_MAP` schedules a shared
   downstream consumer by the *max* of its inputs' readiness, so a short
   branch's register is free once a slower sibling already bounds that max —
   a mismatch between requested cuts and actually-built slices is the tell.
   `SWEEP.DROP_NON_DEEPENING_PLACEMENTS` drops any `INSTANCE_INPUT`/
   `INSTANCE_OUTPUT` placement, or a complete synchronized boundary-register
   group, whose removal leaves the subtree's
   real post-lowering `GET_TOTAL_LATENCY` exactly where it started — ground
   truth after real lowering, not a landscape estimate, since only the real
   synchronous schedule can see this. The comparison also folds in each
   AUTOPIPELINE-tagged descendant region's own latency: such a region
   reports 0 latency to its immediate container by convention (so
   balanced-latency reporting doesn't double-count an already-decoupled
   region), so a monolithic-only comparison would misread every one of that
   region's real registers as adding no depth and drop them all.
   `DROP_NON_DEEPENING_PLACEMENTS` mirrors `SUMMARIZE_SUBTREE_PIPELINE`'s own
   `monolithic + sum(regions)` formula exactly to avoid this.
   Group members are tested and removed atomically: testing one parallel bank
   at a time would make every member appear redundant and leave an arbitrary
   incomplete frontier behind.
   - `SPLIT_KIND_1LL` ("one logic level" — AND/OR/XOR/NOT/NEGATE/MULT):
     these generators (`stage_for_1ll`) always place the *whole* operation in
     exactly one stage no matter the latency — only the register *boundary*
     moves. Latency 1 puts the op in stage 0 or 1 depending on which side of
     0.5 the slice falls; latency 2 puts registers on both sides with the op
     untouched in the middle. A 3rd slice is provably wasted (a bare register
     around logic that never shrinks), so `RAW_VHDL.LEAF_MAX_SPLIT_SLICES`
     caps these at 2 — enforced primarily in the landscape (§3: only a
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

The planned sweep preserves a concrete `PipelinePlacement` through selection
and lowering rather than immediately projecting a fractional cut through
every descendant. `instance_input`/`instance_output` set one entity boundary
flag; `bit_internal` adds a local slice only to a genuinely bit-splittable
raw leaf. An older recursive fraction mechanism remains for the coarse
sweep and compatibility paths:

```
        MAIN  cut at 30% of 100ns
          |
         foo  -> cut lands at 25% of foo's 40ns
          |
       adder  -> cut lands at 50% of adder's 5ns   <- real register here
```

**Cuts != latency.** The two are related but distinct numbers, always
reported separately. Latency can exceed the cut count (children of one cut
sliced at misaligned positions, IO regs, `make_stream_pipeline`-style
factories with internal `autopipeline()` calls). A mini-swept WireGuard
`block_step` accepts one internal half-way slice, with its external banks
then chosen over direct parent-dataflow edges: a ten-instance serial chain
needs the ten internal slices plus nine shared boundaries, not both banks on
every instance — three clocks per instance is only the final fallback when
compact boundary policies miss timing. An **autopipeline-tagged call site
reports latency 0 to its container** (so FSMs keep their cycle accounting) —
a stateful MAIN prints `main_latency=0` while a deep pipeline runs inside
it. That is expected, not a bug.

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
sit in series, as in a stream pipeline — a topology-aware lock records its
shared boundary cover and reports the realized total (a WireGuard-shaped
design's `block_step` repeated ten times reports its true shared-boundary
total, not a naive per-instance sum). The `Pipeline depth summary` at
*Writing Results* prints this figure as "N slice(s) total (N+1 pipeline
stages)" (computed at *Writing Results* on the final, actually-emitted
table, so it reflects any extra depth the AUTOPIPELINE pin-and-confirm
re-elaboration (§6) added).

**Slices vs. pipeline stages — `stages = slices + 1`.** A slice
count is not the same number as "how many pipeline stages". 0 slices (comb
logic) is 1 stage; 1 slice splits it into 2 stages; N slices in series
give N+1 stages. So the `pipeline_stages=` field printed per sweep iteration
and written to `sweep_history.json` is always **realized deepest slices + 1**,
not the requested `cuts` count. The requested cut count and realized slice
count are often equal for one pure-comb subtree (so `pipeline_stages` is then
`cuts + 1`), but those two counts can differ after boundary lowering or with
decoupled regions — a print like `cuts=0 main_latency=0 pipeline_stages=20`
can look like no registers were added at all when in fact locked slices
distributed across decoupled regions account for all 20 stages.

Entity naming is also unchanged: each distinct (IO regs + leaf slices)
combination hashes to its own VHDL entity `funcname_<latency>CLK_<hash>`.

## 2. Delay model: leaf-only synthesis with estimates

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

## 3. Concepts: cut subtrees, landscapes, and cut planning

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

Instead of discovering boundaries by trial synthesis, the cut subtrees are
computed once from the sliceability rules below.

The descend rule (used both by the recursive slicer and the landscape):
descend into a child iff

```
call site is AUTOPIPELINE tagged (or contains a tag deeper)     # override
OR (parent is sliceable AND child is sliceable)                 # plain comb
```

The child-side check matters: a sliceable parent does not by itself license
descending into a stateful child. Without it, a cut could be planned against
a stateful child where it produces no register and silently vanishes; the
descend rule prevents that class of bug by construction — such a cut now
stops and the child boundary becomes the stage boundary instead.
Sliceability itself (`CAN_HAVE_ADDED_LATENCY`): no fixed-latency/vhdl-text/
clock-crossing/state-regs/memory/blackbox/feedback.

### Landscape, segments, and typed candidates

*Where inside a subtree may cuts land, and what does each stretch of delay
cost?* `BUILD_SLICE_LANDSCAPE` flattens a subtree onto its delay axis into
leaf-most **segments**:

- `sliceable` — `SPLIT_KIND_BITS` raw HDL leaf; cuts anywhere inside produce
  a register (§1: the leaf's own generator decides *how*, via an equal-width
  split, not the landscape), **capped** to at most `width - 1` legal units
  (`RAW_VHDL.GET_LEAF_BIT_WIDTH`, the effective operand width passed to the
  generator's `GET_BITS_PER_STAGE_DICT`; binary arithmetic uses its widest
  input rather than counting a widened carry output as another bit) — an
  N-bit leaf can hold at most N-1 interior registers (N
  stages); offering more legal positions than that would let `PLAN_CUTS`
  request cuts `GET_BITS_PER_STAGE_DICT` could only honor with **interior
  zero-bit stages** (bare registers around no logic — a 4-bit op spread over
  15 units would otherwise accept 14 cuts,
  `[0,1,0,0,0,1,0,0,0,1,0,0,0,1,0]` bits per stage). Backstopped by a hard
  error in `GET_BITS_PER_STAGE_DICT` itself if an interior zero-bit stage
  ever slips through anyway (a leading or trailing zero-bit stage is fine —
  an IO-boundary register with no logic on the outer side).
- `sliceable_1ll` — `SPLIT_KIND_1LL` and the initial-planner view of
  `SPLIT_KIND_MUX_BITS`; the operation-output boundary is legal and the
  interior blames like `atomic`. Ordinary planning therefore cannot waste a
  2nd/3rd cut inside one 1LL operation. A genuine `SPLIT_KIND_1LL` span's
  own reason is `1ll_atomic` and stays a hard floor; a `SPLIT_KIND_MUX_BITS`
  span's reason is `mux_packed_bank` and is a *soft* floor (in
  `SOFT_FLOOR_REASONS`) — it is only the unchunked estimate, and a selected
  wide bank is chunked into the genuinely bit-split lowering by default (see
  the `SPLIT_KIND_MUX_BITS` bullet in §1); only the terminal, still-
  unregistered MUX split remains behind the bounded physical-neighbor
  refinement, reached after whole-design timing says the schedule is poor.
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

When every active segment has a structured timing sidecar, `weight[u]` uses
the measured combinational component rather than repeating clk-to-Q and setup
for every leaf in a hierarchical path. The root measurement supplies the
normalized combinational frontier total, and one root launch-plus-setup cost
is reserved for each proposed stage: `budget_units_for_period()` subtracts it
from the target period and `PREDICTED_STAGE_NS()` adds it back once. If any
active segment lacks component evidence, the whole landscape falls back to
the legacy full register-to-register weights; partial evidence is never mixed
into an apparently precise stage budget.

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

A cut is never placed later than the budget allows: unlike a tolerance-based
snap to a preferred boundary, this algorithm cannot accumulate slack across
stages, so it cannot merge an iteration's tail, an inter-iteration MUX, and
the next iteration's head into one oversized stage the way a fixed-fraction
tolerance can at low cut counts.

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
32-cut boundary-only plan, for 16 more register banks. So
`PLAN_PIPELINE_PLACEMENTS` lowers several candidate plans and keeps the
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

A selected delay-axis unit can require several synchronized physical
register banks to cut a parallel or reconvergent frontier.
`_PARALLEL_OUTPUT_FRONTIER` groups raw-operation outputs whose real intervals
strictly overlap and end in that unit. `_PARALLEL_BIT_FRONTIER` groups genuine
bit requests that strictly cross the same point, provided their equal-width
one-cut boundaries all move to one common physical unit after materialization.
A coherent ancestor output remains preferable when it covers the complete
frontier with one bank. Every accepted group carries one deterministic group
identity, member list, physical unit, and aggregate registered-bit cost: it is
one logical cut even though lowering writes several physical banks. Final
realization checks and non-deepening cleanup validate or remove these groups
atomically.

Bit splitting therefore survives whenever it genuinely pays and is dropped
when it only looked like it would on the raster.

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
would disappear, leaving the planner nothing to use between whole iterations.

`--coarse` (and the hotspot mini-sweep, which is a `--coarse` run in
isolation) uses `GET_BEST_GUESS_IDEAL_SLICES(n)` = n evenly spaced global
fractions with no landscape awareness — a cut at a blind fraction can land
inside an atomic span and be silently lost, exactly the failure class the
sliceability/descend-rule invariants above guard against for the planned
sweep. A landscape-aware, exact-cut-count replacement for `--coarse`
(`SEARCH_EXACT_CUT_COUNT`/`GET_EVEN_SLICES_OVER_LANDSCAPE`) was measured
against real sky130 synthesis on the divider design and consistently placed
cuts worse than the blind fractions it was meant to improve on (~16% lower
fmax at an equal, fixed cut count, holding every other change constant, with
no counter-example found) — not shipped.

Compatibility/coarse paths still use `CHECK_CUTS_VS_LATENCY` to compare a
fractional cut count against the leaf slices that actually materialized in
the subtree. Its strictness follows the landscape:

- **Zero leaf slices** while cuts were planned: always a hard error — every
  register vanishing is always a hard error.
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

Every planned run writes `<out>/top/placement_trace.json`. Trace schema 6 keeps
concrete output `candidates` separate from nonphysical bit `planning_sites`.
Per-iteration and final selections contain only physical placements; a bit
selection records its emitted width, boundary, split ordinal/count,
bits-per-stage, boundary mode/group, requested raster coordinate, actual
axis/local coordinate, and realization status. The trace also records
per-iteration physical fingerprints and whether the one bounded generic
chunked-MUX refinement was attempted (`same_depth_refinement.chunked_mux_attempted`),
plus instance/function metadata,
estimated registered bits, internal forced mode, boundary-register type, and
local stage assignment. Schema 6 adds `placement_groups`, summarizing each
synchronized frontier's planned and realized members, physical unit,
registered-bit total, and atomic realization verdict. A `locked_instances`
entry separately records every
coarse mini-sweep lock, including its fixed internal slices, selected input/
output banks, boundary strategy, rebuilt latency, and realization check.
`mini_sweep_boundary_diagnostics` records the alias-only direct edges, the
minimum-cost input/output cover, and any edge ineligible because a no-I/O
pragma applied. The trace, generated VHDL, mapped JSON, and STA report
together are the evidence for a placement claim; requested cut counts alone
are not.

`PIPELINEC_INTERNAL_SKIP_PIPELINE_MAP_PNG=1` is an internal benchmark switch
that suppresses only diagnostic pipeline-map PNG rendering for very large
fine-grained probes. The text map, placement trace, HDL, and default behavior

The preserved
[`divider_gate_clean_baseline_critical_paths.json`](../src/tests/pypeline_tests/qor/divider_gate_clean_baseline_critical_paths.json)
records a clean, unmodified-planner baseline for the gate-Divider design
(commit `c81ca31f`, no handoff patch): its winning paths at 66-73 slices all
contain the same pre-loop divide-by-zero compare/select cone, and additional
slices beyond the point where that cone is isolated buy zero fmax. This is
evidence for a missing legal operation boundary and a mapping/fanout effect,
not evidence that the repeated step itself needs more cuts — see
[`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md) for the frozen
compare/select recipe matrix this motivated. Typed-placement results retain
their own modified-tree hashes and are not part of this baseline.

The generic typed planner and the production sky130 recipe meet the Divider
design's QoR target without a Divider-name rule, exact-cut search, public
slice cap, or required stage-sized helper function; see this file's History
section for how the acceptance result was reached and
[`pypeline_TESTS.md`](pypeline_TESTS.md#related) for the durable acceptance
record.

### Floor

*What fmax can this subtree never exceed?* The longest run of illegal units
is the predicted minimum stage delay — reported with a blamed instance
**before any synthesis run**.

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
*and* an upper bound. A curr_mhz far above the floor means the *prediction*
was wrong, not that a ceiling was reached, so it must not count as "at the
floor" — checking only the lower bound would let a sweep stop and report
`TIMING NOT MET` while sitting 73% above its own predicted floor and
comfortably beating its actual goal.

**Restoring the best-seen result must re-check whether it actually met
its goal.** When the sweep stops without the final iteration meeting
timing, it restores whichever earlier iteration had the best worst-case
achieved/target ratio (`best_tpl`/`best_score`) and writes that out instead.
`SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS(best_score)` (`best_score >= 1.0`) then
re-derives `met_timing` for that restored snapshot — without it, a build
could restore a snapshot that measured well above its target and still exit
`TIMING NOT MET`, because `met_timing` was last written by a later, worse
iteration (e.g. one a floor-stop landed on afterward) and never re-checked
against the snapshot actually written out.

### Plan

`MainSweepPlan` (one per MAIN with a target MHz) holds the sweep's
per-main state. For the running example, mid-sweep after one failed
iteration that was attributed to `mul_add`, the plan would look like:

```python
MainSweepPlan(
  main_inst        = "my_main",
  target_mhz       = 100.0,
  subtrees         = ["my_main"],            # cut subtree roots
  landscapes       = {"my_main": <SliceLandscape above>},
  cuts             = {"my_main": [9, 19]},   # planned cut units per subtree
  # learned calibration, per-func where attribution allows:
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

## 4. The refinement loop

```
                 +--------------------------------------------+
                 | plan cuts per subtree (landscape + budget)  |
                 | apply locks, slice, write VHDL               |
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

**Judging a change to this loop is stated per latency, not per MHz target:**
a deeper pipeline at a given goal is an acceptable outcome; a slower
pipeline at a given stage count is not. Comparing two planner behaviors (or
two commits) means holding stage count fixed and comparing fmax, or holding
the MHz goal fixed and asking whether the reachable depth changed — never
comparing MHz-goal outcomes reached at two different stage counts as if
they were the same axis.

The loop resets to zero clocks, slices, synthesizes, and adjusts;
adjustment follows the escalation ladder above. The per-module coarse sweep
is also used in two other places: the `--coarse` CLI path, and as the
**mini-sweep** run on an attributed hotspot (streamsoc: fft attributed 3x →
`Isolated coarse sweep of hotspot: fft_2pt_pipeline_no_handshake` → met
129 MHz in isolation with 2 cuts → locked interior plus a parent-dataflow
boundary policy).

**Attribution is approximate by design.** Post-synthesis names below the
top-level MAIN are mangled differently by every tool, and keep/dont_touch
attributes bloat designs — so exact hierarchical matching is never
attempted. Instead:

1. MAINs resolve via entity-name prefixes (
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

   *Why length alone is wrong:* every ancestor func's name is itself a
   substring of a descendant register's fully-qualified name (each
   hierarchy level just prepends its own instance name), so a pure
   matched-length score carries no depth signal — it always favors
   whichever candidate name is longest. On wireguard-fpga's decrypt path a
   58-character auto-generated interface-func wrapper name
   (`if8040c842_decrypt_dataflow_core_..._inst18`) scores 14112 under
   length-alone and would beat the 29-character `chacha20_chacha20_
   block_step` at 7056, even though the actual timing report shows the
   critical path running entirely between two registers *inside* the
   latter, many levels deeper than the wrapper — depth-ranked matching
   attributes this correctly. `SWEEP.RESOLVE_PIPELINABLE_HOTSPOT`
   additionally guards a related case: the correctly-attributed deepest
   common ancestor can itself be unsliceable (state/feedback at its own
   level, e.g. a `feedback_vars` submodule threaded through an
   interface-func wrapper) while wrapping other, unrelated sliceable logic
   — before declaring the path unpipelinable it scans the remaining ranked
   candidates for the deepest one that autopipelining *can* help, so one
   stuck ancestor never masks a densifiable one on the same path;
3. entity-local `REG_STAGEn` stage numbers are logged only — stage indices
   are local to the entity the FF lives in, never global;
4. low confidence → no attribution → global rescale. PYRTL (the no-PART
   software timing model) reports a single fmax with no names at all and
   always takes this path — still floor-bounded and convergent.
5. mains never implicated in any *failing* report count as met once every
   reported path meets its goal (per clock group reports only show the
   group-worst path, which can live in a different main — same semantics as
   the coarse sweep).

Every iteration logs one line per main — a real one from WireGuard showing
targeted densification of the correctly-attributed interior hotspot:

```
[sweep] iter=1 main=chacha20_pipeline_shared_chacha20_pipeline_shared goal=80.00MHz
        got=47.91MHz (20.87ns) cuts=12 main_latency=0 pipeline_stages=13
        predicted_stage=12.25ns bottleneck=chacha20_chacha20_block_step
        action=densify(chacha20_chacha20_block_step x1.75)
```

Meeting timing in very few iterations is not automatically a good sign: a
cut budget computed against a badly-inflated estimated delay axis can "meet
timing in one iteration" by drowning the design in far more registers than
necessary. Meeting timing fast by over-pipelining is the failure mode that
makes people distrust HLS tools; a few more iterations converging from below
is always the better trade.

One from streamsoc (compare: a per-module coarse re-slice of the whole
design would cost far more synthesis runs to reach the same result):

```
[sweep] iter=1 main=fft_2pt_pipeline_no_handshake goal=110.00MHz got=98.86MHz
        (10.11ns) cuts=3 main_latency=4 pipeline_stages=5 predicted_stage=9.10ns
        bottleneck=fft_2pt_pipeline_no_handshake action=densify(fft_... x1.17)
```

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

Silently continuing past unmet timing — writing results, running sim,
exiting 0 — would let a real timing failure go unnoticed, since simulation
only checks logical correctness, not fmax.

**Pipeline depth summary.** Right after the *Writing Results* banner, one
block reports how deeply each main ended up pipelined (total slices and stages,
see §1), broken down by decoupled region — computed on the final emitted
table so it includes any depth the §6 re-elaboration added:

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

## 5. Command line

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

## 6. AUTOPIPELINE `.latency` pin-and-confirm loop (Pypeline designs only)

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
   of bug behind a "unit not found" GHDL failure on a shared-across-instances
   design). Then `SYN.DO_SEEDED_CONFIRM_OR_SWEEP` runs **one** full-design
   synthesis. The loop stops only when the post-confirmation harvest
   **equals** the values this pass's Python consumed — meeting timing alone
   is not sufficient: realizing the seeded fractional slices hierarchically
   (e.g. into pipelined built-in div/mult entities with their own stage
   granularity) can change an instance's total latency even on a passing
   confirmation, and exiting then would build VHDL whose actual depth
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

## 7. AUTOFSM schedule-and-confirm loop (Pypeline designs only)

`AUTOFSM(func)` is the resource-minimizing dual of AUTOPIPELINE: instead of
cutting one copy of a function's hardware into pipeline stages, it keeps ONE
copy of each distinct operation and runs the function over several cycles. Full
design in [`AUTOFSM_DESIGN.md`](AUTOFSM_DESIGN.md); what matters here is how it
sits around everything above.

**Loop nesting.** `SYN.DO_SWEEP_AND_AUTOPIPELINE` is the whole of §4 + §6 factored
into one function; `src/pipelinec` calls it via `SYN.DO_PIPELINED_BUILD`, which is
the dispatch point. When a design contains AUTOFSM call sites,
`AUTOFSM.DO_SCHEDULE_PASSES` wraps it instead:

```
bootstrap parse (AUTOFSM call sites are combinational passthroughs)
for each schedule pass:
    ADD_PATH_DELAY_TO_LOOKUP          <- measure the operations, do NOT sweep
    schedule + bind each AUTOFSM
    install schedules, re-PARSE_FILE  <- call sites become the generated FSMs
    SYN.DO_SWEEP_AND_AUTOPIPELINE     <- §4 sweep + §6 AUTOPIPELINE loop
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
unsliceable atomic block whose measured delay is a soft floor (§3's
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
- **`parser_state.func_force_estimated`**, an escape hatch checked at the top
  of `FUNC_PATH_DELAY_IS_ESTIMABLE`. The bootstrap passthrough looks exactly
  like a measurement frontier (§2) and would otherwise get one whole-blob
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
  of quick runs, not a meaningful build cost. They live under
  `include/pypeline/operators/`, intending `_IS_PYPELINE_OPERATOR_LIBRARY_CODE`
  to classify them as non-user code and so make each shape cacheable in
  `path_delay_cache` (a caching gap here is tracked in Limitations and future
  work, below).

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

**Convergence** is easier than §6's. A schedule is a pure function of (the
function's Logic graphs, its operations' delays, the budget scale) and is
independent of the surrounding design, so nothing can oscillate: only an
explicit tightening changes the answer, and tightening is monotonic and capped
(`MAX_SCHEDULE_PASSES`). The loop also stops early when every blamed region is
`at_floor` — one indivisible operation too slow for the clock, which no number
of extra states can fix.

## 8. Test matrix

Fast tests (no `PART()` → PYRTL software timing model, seconds per synth
run) in `src/tests/pypeline_tests/inst/`, registered in `synth_tests.py`:

| test | proves |
|---|---|
| `sweep_comb_test.py` | pure comb MAIN: planner places cuts, meets timing |
| `sweep_two_mains_test.py` | two MAINs: per-main plans, no-attribution fallback |
| `sweep_fsm_autopipeline_test.py` | Reg-FSM main + AUTOPIPELINE region (via `_autopipeline_with_io_regs`): cut subtree is the tagged child, FSM latency stays 0 |
| `sweep_stateful_boundary_test.py` | comb→stateful→comb: cuts stop at the stateful boundary |
| `sweep_floor_detect_test.py` | unreachable goal: floor predicted & blamed up front, sweep stops after a few syn runs, results written, then `TIMING NOT MET` + non-zero exit |
| `sweep_unpipelinable_test.py` | stateful MAIN with a goal but nothing cuttable: told plainly that autopipelining cannot help (planning time + standalone as-written check FAIL + failing report), one full syn run, `TIMING NOT MET` + non-zero exit |
| `sweep_planless_test.py` | stateful MAIN with a met goal but nothing cuttable: one standalone as-written check synthesis prints PASS, its critical path is NOT stored as the func delay, one full syn run, exit 0 |
| `autopipeline_latency_test.py` | end-to-end factory design (`make_stream_pipeline`, no MAX_IN_FLIGHT) through the full sweep **plus** the §6 pin-and-confirm loop: pass 2 runs, harvested `.latency` > 0, seeded confirmation syn passes with no fallback sweep, loop settles within the pass cap (extra realization passes allowed) |
| `autofsm_latency_test.py` | §7 end-to-end: schedule pass runs, several same-kind operations fold onto fewer shared units, latency == states + 1, and exactly ONE instance of each shared unit appears in the generated VHDL |
| `autofsm_resources_compare_test.py` | §7 area: same design built `--comb` (no sharing) and scheduled, compared by yosys cell count — guards the reason the feature exists |
| `autofsm_timing_iter_test.py` | §7 iteration: a deliberately over-packed first schedule misses the clock, the FSM is blamed, its budget is tightened, and a later build passes — with no source change |

Unit/in-process coverage (registered in `elab_tests.py`):
`autopipeline_harvest_test.py` (harvest grouping + divergence, seed two-tier matching
+ call-site-change detection, `CANONICAL_CALLABLE_KEY` determinism, latency
cache/read-flag), `autofsm_unit_test.py` (scheduler binding/dependency/register
invariants, budget→states, floors, byte-identical generated source across
re-elaborations) and `double_parse_file_test.py` (repeated `PARSE_FILE`
equivalence, including an AUTOFSM design).

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

1. **The coarse path crashes on narrow leaves.** `--coarse --sweep` can
   raise `GET_BITS_PER_STAGE_DICT: interior zero-bit stage ... for a 2-bit
   op` on a design with many narrow (1-3 bit) leaves at a high cut count —
   reproducible independent of which design triggers it. The leaf-bit-width
   cap that prevents this exists only in the planned sweep
   (`SWEEP.BUILD_SLICE_LANDSCAPE`, §3), not `--coarse`, which consults only
   `LEAF_MAX_SPLIT_SLICES` (`None`/uncapped for `SPLIT_KIND_BITS`). Suggested
   fix: port the cap into the coarse path, or make `LEAF_MAX_SPLIT_SLICES`
   return `width-1` for `SPLIT_KIND_BITS`.
2. **The 0.1 ns delay raster (`DELAY_UNIT_MULT = 10.0`) is coarse for narrow
   leaves.** Every sub-0.1 ns leaf collapses to the same weight, so e.g. a
   3-bit add and a 1-bit XOR are indistinguishable to `PLAN_CUTS`. Not a live
   risk for sky130 at ordinary widths (measured leaf delays sit comfortably
   above the raster floor), but the strongest argument that a soft
   operator's own internal chunk width should be tuned per target rather
   than assumed fixed. Suggested fix: raise `DELAY_UNIT_MULT` and round
   rather than truncate.
3. **Component-aware stage budgeting requires complete timing sidecars.**
   When every active segment has clk-to-Q, combinational, and setup fields,
   the planner packs combinational work and reserves launch/setup exactly
   once per proposed stage. If even one active segment lacks those fields,
   the landscape deliberately falls back to legacy full register-to-register
   weights instead of mixing incompatible costs. This preserves correctness
   and reproducibility, but newly measured or non-sky130 designs can retain
   depth-proportional over-prediction until their sidecars are complete.
4. **Parallel-frontier grouping is deliberately conservative.** Output and
   bit frontiers require strict interval overlap (an antichain), and grouped
   bit requests must materialize their equal-width boundaries in one common
   physical unit. The planner refuses the group when peers do not overlap,
   move to different units, or a coherent ancestor output already cuts the
   frontier more cheaply. This avoids inventing latency, but can miss a true
   graph cut whose raster intervals do not expose that geometry.
5. **Frontier discovery is local to one landscape unit.** It synchronizes
   the operation-output and bit-internal candidates already represented at
   that unit; it does not construct a complete dependency DAG or schedule a
   multi-unit rank globally. More complex fork/join geometries can therefore
   still require graph scheduling if local typed placement cannot express the
   useful physical boundary.
6. **Watch for "rewire-only" entities when building a deep, many-node
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
7. **`AUTOPIPELINE(func, depth=N)` is documented but silently a no-op.** The
   value is stored on `AutopipelineCall` elaboration and never read by
   anything downstream. `--coarse --start N --stop N+1` against a design
   with no `@MAIN` MHz goal is the actual "best fmax at a fixed latency"
   mechanism today.
8. **Caching for AUTOFSM's operand-mux measurement entities doesn't fire**
   (§7). `_IS_PYPELINE_OPERATOR_LIBRARY_CODE` is meant to classify
   `include/pypeline/operators/` entities as non-user code so their delays
   are cacheable in `path_delay_cache`, but it calls `inspect.getsourcefile`
   on the `@hw_func` wrapper callable rather than the wrapped function, so
   it always resolves to `pypeline.py` and never fires. An `inspect.unwrap`
   at that lookup would fix it. Nothing is incorrect meanwhile — the
   affected delays are just measured every build instead of once.
9. **Whether raw HDL leaves should support genuinely uneven bit-split
   boundaries** (rather than always equal-width, §1) is open. Measured
   evidence so far favors equal-width — real per-width delay is monotonic
   and concave, so minimizing the worst stage at a given stage count means
   equal-width chunks — but the constraint itself has not been revisited
   since.
10. **`INFERRED_MULT` raw-vs-soft comparison is skipped under the PyRTL tool**
    in the operator QoR benchmark (§9) — PyRTL has no DSP-inference cost
    model, so multiplier coverage there is sky130/Vivado-only.
11. **`PLUS` has the same PyRTL blind spot as `INFERRED_MULT`, with a bigger
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
were taken.

### Why the planned sweep replaced the middle-out sweep

The original autopipelining sweep grew pipeline depth via four interacting
multiplier knobs (`best_guess_sweep_mult`, `hier_sweep_mult`, and two more)
against evenly-spaced "best guess" register placements, synthesizing every
hierarchy level up front (a full wireguard build cost roughly 16 full
synthesis runs) and silently exiting 0 on unmet timing. The planned sweep
(`src/SWEEP.py`) instead builds a static delay model of where delay actually
lives (the *landscape*) and where cuts are legal, starts from a
measurement-frontier-calibrated fewest-stages guess, and adds stages only
from synthesis feedback — typically far fewer syn runs, and a hard non-zero
exit on unmet timing rather than a silent pass. See §0's vocabulary table
for the terms this introduced.

### Mux select-fanout cliff

A single mux select bus registered on top of an already-registered, wider
parallel sibling can materialize a real register while adding zero pipeline
depth, since `GET_PIPELINE_MAP` schedules a shared downstream consumer by
the max of its inputs' readiness — a short branch's register is free once a
slower sibling already bounds that max (§1). Found on `soft_shift_rot`
(sky130, real liberty STA): a 7-cut plan with this placement measured
105.95 MHz with 4 max-capacitance violations, where dropping the
non-deepening placement alone reached 252.13 MHz at 6 cuts with none, and
additionally chunking the remaining wide selected banks by default reached
377.41 MHz — beating even the escalation ladder's own best result on that
design (317.36 MHz at 8 cuts), with fewer register banks.
`DROP_NON_DEEPENING_PLACEMENTS` (§1) is the fix, and defaulting wide
selected-mux banks to chunked lowering is now unconditional, not gated
behind hitting this cliff first.

### Divider acceptance and the 48-slice intermediate level

The generic typed planner meets the divider design's QoR target without any
divider-specific naming rule, exact-cut search, public slice cap, or
required stage-sized helper function; the durable acceptance record is
[`divider_qor_acceptance.json`](../src/tests/pypeline_tests/qor/divider_qor_acceptance.json),
tracked from [`pypeline_TESTS.md`](pypeline_TESTS.md#related). The reachable
pipeline depths are structural: one register per loop iteration gives 32
slices, two gives 64, and a real intermediate level exists at 48 (cut at one
subtract's output, the next subtract's midpoint, then that MUX's output —
three cuts per two iterations) — but reaching it needs the bit-boundary
lowering to land exactly on the equal-width split the leaf generator will
actually emit (§3) *and* realized-plan judging to rank by
budget-met-then-fewest-cuts rather than raw worst stage (§3, `_PLAN_RANK`);
getting either wrong collapses the plan back onto 32 or 64. The packed-MUX
physical-neighbor refinement (chunk selected integer MUXes, including the
terminal one) is what the sweep tries automatically after a full-design
miss, before densifying further — this is what lets 48 slices reach its
full potential fmax rather than plateauing well below the 64-slice level;
[`divider_continuity_bench.py`](pypeline_TESTS.md#related)
confirms the terminal MUX is the entire effect (chunking every *other*
selected bank first buys +0.3%; adding the terminal one reaches 194.22 MHz
at 50 stages).

A **phase variant** realizes the same worst stage as a coarser accepted
plan — registers spent without moving fmax, landing within one delay-raster
unit of it — where a **real level** is a genuinely different stage
structure at a measurably different fmax (the 48→50-slice step above is a
real level; a same-worst-stage restructuring at 49 slices would be a phase
variant of one of its neighbors). This is exactly what realized-plan
judging exists to reject: ranking by budget-met-then-fewest-cuts rather
than raw worst stage (above, `_PLAN_RANK`) means a phase variant loses to
the plan it duplicates on cut count, not fmax. The negative A/B evidence
behind the 48-slice/49-stage control is the concrete reason to trust that
control rather than retry its neighbors: an isolated per-leaf model ranks
an exact-bit subtract boundary as the *best* modeled fmax of the group, but
built into the full divider it is one of the *worst* full schedules
(144.43 MHz vs. the equal-width control's 164.69 MHz) — full-design fanout
and max-capacitance dominate in a way no isolated leaf measurement sees
(neighboring exact boundaries also lose: 152.06, 162.99; an explicit
stage-local ripple-borrow subtract is far worse still, 99.16). Isolated
leaf delay is a planning heuristic, not a QoR prediction — this is the
concrete instance to point to when that distinction needs defending.

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
narrow-width-`GTE`/`LTE`-heavy; `AUTOFSM._SOFT_FACTORY_FOR_OP` also stays
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
tradeoff. Autopipelined via the *planned* sweep (not `--coarse`, which has
an unrelated pre-existing crash on this design's many narrow leaves —
Limitations item 1) with a real `@MAIN(700)` target and the latchup-style
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
