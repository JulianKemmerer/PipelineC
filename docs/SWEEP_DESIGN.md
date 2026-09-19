# Throughput sweeps

How PypelineC uses the synthesis API to iterate toward a timing goal: the
planned sweep, the coarse sweep, and the seeded confirm-or-sweep. This is the
machinery every temporal AUTO feature shares; each feature's own feedback
into the loop is documented with that feature.

- Implementation: [`src/SWEEP.py`](../src/SWEEP.py).
- The synthesis runs, reports and delay model it drives:
  [`SYN_DESIGN.md`](SYN_DESIGN.md).
- What a pipeline *is* (slices, IO registers, the pipeline map, VHDL
  lowering) and the AUTO_PIPELINE build loop:
  [`AUTO_PIPELINE_DESIGN.md`](AUTO_PIPELINE_DESIGN.md).

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section rather
> than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## 1. Who does what

| file | role in a sweep |
|---|---|
| `src/SWEEP.py` | The common machinery: cut subtrees, slice landscapes, floor prediction, cut planning and typed placement, applying placements to `TimingParams`, hotspot attribution and mini-sweeps, plan accounting, `sweep_history.json`, and the drivers — `DO_THROUGHPUT_SWEEP` (entry point), `DO_PLANNED_THROUGHPUT_SWEEP` (the refinement loop), `DO_COARSE_THROUGHPUT_SWEEP` (`--coarse` and mini-sweeps), `DO_SEEDED_CONFIRM_OR_SWEEP` (the pin-and-confirm confirmation run). |
| `src/SYN.py` | The synthesis API the sweep calls: delay collection, single-instance and whole-design synthesis, parsed timing reports ([`SYN_DESIGN.md`](SYN_DESIGN.md)). |
| `src/AUTO_PIPELINE.py` | The pipeline representation the sweep edits, and AUTO_PIPELINE-specific feedback: constrained regions are planned and enforced on every iteration ([`AUTO_PIPELINE_DESIGN.md`](AUTO_PIPELINE_DESIGN.md#6-constrained-auto_pipeline-regions-latency--start_latency--max_latency)). |
| `src/AUTO_MULTI_CYCLE.py` | AUTO_MULTI_CYCLE feedback: failing multi-cycle paths raise their cycle count ([`AUTO_MULTI_CYCLE_DESIGN.md`](AUTO_MULTI_CYCLE_DESIGN.md#3-sweep-feedback)). |
| `src/AUTO_FSM.py` | Wraps the whole sweep in its own schedule-and-confirm loop ([`AUTO_FSM_DESIGN.md`](AUTO_FSM_DESIGN.md#34-the-driver-loop)). |
| `src/PYRTL.py`, `src/DEVICE_MODELS.py` | The `SYN_TOOL` backends the delay model and fast sweeps are built on — see [`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md) for the real sky130 liberty STA backend (`PART("sky130...")` / `--syn_tool device_models`) and why it exists (PyRTL's own cost model has no fanout/load term at all). |

Vocabulary used throughout (each defined in detail later; the measurement
frontier and estimated delays are part of the delay model in
[`SYN_DESIGN.md`](SYN_DESIGN.md#5-delay-model-leaf-only-synthesis-with-estimates)):

| term | one-liner |
|---|---|
| **slice** | one serial register boundary inserted by pipelining; it is represented either by a raw-leaf-local fraction in `TimingParams._slices` or by an operation instance's input/output-register flag |
| **cut** | a requested stage boundary on a whole *cut subtree*'s delay axis; typed planning resolves it to one or more concrete physical placements |
| **cut subtree** | the largest subtree registers may be added to (a comb MAIN, or each AUTO_PIPELINE-tagged region) |
| **landscape** | the flattened delay axis of one cut subtree: where every nanosecond of logic lives and whether a cut may land there |
| **segment** | one leaf-most piece of that axis (sliceable / atomic / locked) |
| **placement** | one typed physical register location: an operation-instance input/output boundary or a genuine bit-internal leaf cut; `fixed` placements are retained by controlled internal experiments |
| **floor** | the fmax that no amount of added registers can beat (longest un-cuttable stretch) |
| **plan** | per-MAIN sweep state: cut subtrees, landscapes, cuts, learned scale factors, locks |
| **measurement frontier** | the topmost fully-combinational funcs — the only hierarchical modules ever synthesized per-module; their measured through-delays calibrate the estimates of everything above (and thus how many cuts the first plan gets) |
| **lock** | a mini-sweep result whose internal slices are frozen onto all instances of a func (`params_are_fixed`); optional input/output banks are selected from parent dataflow rather than assumed per instance |
| **trim** | post-met iterations that retry with fewer cuts to prove the stage count is minimal |

## 2. Concepts: cut subtrees, landscapes, and cut planning

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
comb, otherwise each region reached through AUTO_PIPELINE-tagged call sites
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
                                             +-- AUTO_PIPELINE(chacha_loop)(...)   <- TAG
                                                   |
                                                   chacha_loop = cut subtree root
```

Instead of discovering boundaries by trial synthesis, the cut subtrees are
computed once from the sliceability rules below.

The descend rule (used both by the recursive slicer and the landscape):
descend into a child iff

```
call site is AUTO_PIPELINE tagged (or contains a tag deeper)     # override
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
  a register ([`AUTO_PIPELINE_DESIGN.md` §2](AUTO_PIPELINE_DESIGN.md#2-how-pipelines-physically-form): the leaf's own generator decides *how*, via an equal-width
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
  the `SPLIT_KIND_MUX_BITS` bullet in [`AUTO_PIPELINE_DESIGN.md` §2](AUTO_PIPELINE_DESIGN.md#2-how-pipelines-physically-form)); only the terminal, still-
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
boundaries — assuming each leaf gets exactly one cut, the only count known
at formation time — all move to one common physical unit after
materialization. A coherent ancestor output remains preferable when it covers
the complete frontier with one bank. Every accepted group carries one
deterministic group identity, member list, physical unit, and aggregate
registered-bit cost: it is one logical cut even though lowering writes
several physical banks. Final realization checks and non-deepening cleanup
validate or remove these groups atomically.

The stamped physical unit is only that one-cut estimate, though: a leaf that
goes on to collect a second bit request (its own group's sibling frontier)
moves ALL of that leaf's requests together to a different, but still common,
equal-width boundary once `MATERIALIZE_BIT_PLACEMENT_REQUESTS` sees the real
per-leaf count — the group's *planned* unit is provisional diagnostic
metadata, not an invariant to hold the realized placements to.
`SUMMARIZE_PLACEMENT_GROUPS` therefore verifies every planned member realized
and that all realized members share one physical unit, records the realized
unit and whether it moved from the plan in `placement_trace.json`, and raises
only on a genuine loss (a missing member) or a genuine split (realized
members on different units) — not on a moved-but-coherent frontier.

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

`DO_THROUGHPUT_SWEEP` auto-selects `--coarse` for a single MAIN with no target
MHz only if `FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL` holds for it,
the same predicate `ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES`
sanity-checks. A stateful main (Reg/Feedback, no AUTO_PIPELINE below) cannot take
added latency. It used to be forced into coarse slicing anyway and crash with
`Trying to slice into <main> for no reason`. That hit every single stateful goal-less
MAIN, whether or not it held a `@pipeline_latency` child. Such a design now falls through to
the planned sweep, which skips goal-less mains, has no plan, and characterizes the
design as written with one synthesis run and zero added latency. Explicit `--coarse`
on such a main raises the same "No main functions are elligible for pipelining"
error the multi-main selection already did.

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
synchronized frontier's planned and realized members, registered-bit total,
and atomic realization verdict. `planned_axis_unit` is the provisional
one-cut estimate the group was formed with; `realized_axis_unit` is the
actual common physical unit (`None` if the group did not realize to one
unit), and `moved_from_planned` says whether the two differ — a coherent
frontier is free to move as a whole (see above) and is not an error. A
`locked_instances` entry separately records every
coarse mini-sweep lock, including its fixed internal slices, selected input/
output banks, boundary strategy, rebuilt latency, and realization check.
`mini_sweep_boundary_diagnostics` records the alias-only direct edges, the
minimum-cost input/output cover, and any edge ineligible because a no-I/O
pragma applied. The trace, generated VHDL, mapped JSON, and STA report
together are the evidence for a placement claim; requested cut counts alone
are not.

`PIPELINEC_INTERNAL_SKIP_PIPELINE_MAP_PNG=1` is an internal switch that
suppresses only diagnostic pipeline-map PNG rendering. Large fine-grained QoR
probes use it, and the pypeline test runner sets it for every test (see
[pypeline_TESTS.md](pypeline_TESTS.md#choosing-a-synthesis-tool)). The text map, placement trace, HDL, and default behavior

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

**A plateau stops the sweep even when the prediction is wrong.** The band
protects results that beat a wrong prediction, but on its own it lets a
sweep that is simply *stuck* above a pessimistic soft floor run to the
iteration cap. Under sky130, `sweep_floor_detect_design.py` at 100 MHz
predicts a ~37 MHz soft floor, then sits at exactly 51.42 MHz while cuts grow
25 → 64 and `global_scale` inflates: 12 iterations, `iteration_limit`.
`SWEEP.AT_PLATEAU` never consults the prediction. It stops with
`stopped_reason = "plateau"` when all of these hold:

- the last `PLATEAU_STREAK` (3) unmet results are flat within noise (max−min
  under 1% of the target, the same rule as `same_mhz_count`);
- the cut count grew from the first of those results to the current one;
- the current plan used measured delays (the soft-floor gate: fallback done,
  no estimates in play, or `prim` mode) and is a fresh plan, not a
  placement refinement. A refinement is a same-depth probe carried over
  from the previous plan. Under PyRTL, stopping on the post-fallback
  refinement's 15.11 MHz would have missed the next denser plan's
  15.82 MHz.

The window may span the measured-delay fallback, because a synthesized fmax
is real whichever model planned it. Structural experiments restart it
(`plan.plateau_window_start`): an AUTO_MULTI_CYCLE count change or a
locked-hotspot boundary strategy. Floor stops are checked first, and the
unpipelinable/locked-hotspot stops fire sooner (one repeat), so the plateau
catches only what nothing more specific explains. When a soft floor below the
goal exists, the warning and the `TIMING NOT MET` reason name it as the
likely limit. In the example, iterations 4–6 (50.60 / 51.42 / 51.42 MHz,
cuts 11 → 43) stop the sweep after 6 syn runs.

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

The history dumps to `<out_dir>/<top>/sweep_history.json` (`schema_version`
2). Each goal main has its iteration records **and a `final` record for the
design as built**. Read `final` for "what did this build achieve". The
iteration log alone can't answer that: an assumed-met final iteration, a
restored best/met snapshot and a [pin-and-confirm](AUTO_PIPELINE_DESIGN.md#5-latency-pin-and-confirm-loop-pypeline-designs-only) confirmation run are all not "the last
iteration".

```json
{"schema_version": 2, "build_complete": true,
 "mains": {"my_main": {
   "goal_mhz": 100.0,
   "iterations": [
     {"iter": 1, "main": "my_main", "goal_mhz": 100.0, "achieved_mhz": 87.0,
      "met": false, "cuts": 2, "main_latency": 2, "pipeline_stages": 3,
      "predicted_stage_ns": 10.0, "bottleneck": "mul_add",
      "action": "densify(mul_add x1.75)", "run": 1, "index": 0},
     {"iter": 2, "main": "my_main", "goal_mhz": 100.0, "achieved_mhz": null,
      "met": true, "cuts": 4, "pipeline_stages": 5,
      "action": "met(no failing path reported)", "run": 1, "index": 1}],
   "final": {"met": true, "achieved_mhz": null, "mhz_is_lower_bound": true,
     "lower_bound_mhz": 100.0, "met_basis": "no_failing_path_reported",
     "source": "planned_sweep", "run": 1, "iter": 2, "iteration_index": 1,
     "failure_reason": null, "auto_pipelined": true, "slices_built": 4,
     "pipeline_stages": 5, "stopped_reason": null, "cuts": 4,
     "locked_instances": 0}}}}
```

- **Iterations.** Records accumulate across every deciding run in the build:
  - planned sweeps, including a [pin-and-confirm](AUTO_PIPELINE_DESIGN.md#5-latency-pin-and-confirm-loop-pypeline-designs-only) fallback sweep
  - confirmation runs (`action: "confirm"`)

  Each record is tagged with its `run` number and its `index` in the list.
  Planless goal mains get `action: "as_written"` records.
- **A main no path report named.** When every report passed but none named
  this main (the report for its clock group showed another main's worst
  path), its record has `achieved_mhz: null`. Before schema 2 no record was
  written at all, so such a sweep's history ended one iteration early.
- **`final.source`** is `planned_sweep`, `confirmation_run`, `as_written`,
  `coarse_sweep` or `no_sweep`. `run`, `iter` and `iteration_index` name the
  record whose table was kept: a restored snapshot names its own iteration.
  `standalone_mhz` is the planless as-written check's number.
- **`final.met`** agrees with the build's exit code by construction: a main in
  `sweep_timing_failures` is `met: false`, and that tuple supplies
  `achieved_mhz` and `failure_reason`. `met: null` means unverified
  (`--no_sweep`, or no goal).
- **`mhz_is_lower_bound`.** A met main with no measured MHz has
  `achieved_mhz: null` and `mhz_is_lower_bound: true`: the goal is a lower
  bound on its fmax, never the fmax itself.
- **Depth fields** (`auto_pipelined`, `slices_built`, `pipeline_stages`) are
  read off the final table through the same `MAIN_PIPELINE_DEPTH` as the
  printed `Pipeline depth summary`.
- **When it's written.** Each deciding run writes the file provisionally
  (`build_complete: false`), so a build that dies later still leaves data.
  The driver rewrites it at *Writing Results* (`build_complete: true`) before
  the TIMING NOT MET exit, so failing builds get it too. A `--comb`
  characterization build records nothing and writes no file.

## 3. The refinement loop

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
   fmax flat 3x (1% of target) while cuts grew, delays measured?
          |-- yes --> stop(plateau), warn (blame soft floor if any), keep best
          |
   attribute critical path to a function (approximate)
          |
   hotspot found:   func_delay_scale[hotspot] *= target/achieved  -> replan
   same hotspot 2x: isolated mini-sweep of that func, lock result
                    (the isolated probe measures that helper itself)
   hotspot locked:  try the opposite compact boundary side, then bounded
                    one-sided/both-sided fallback policies before rescaling
   hotspot cannot be auto-pipelined (state regs, vhdl text, ...):
                    rescale once (boundary registers may cut its IO paths),
                    then if fmax stagnates stop and tell the user PLAINLY:
                    "critical path is in function F, which cannot be
                    auto-pipelined (reason) - restructure F or lower the goal"
   no attribution:  global_scale *= target/achieved               -> replan
                    (a replan whose x1.1 nudges cannot change the cut count
                    -- saturated landscape -- drops those nudges again)
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
   candidates for the deepest one that auto-pipelining *can* help, so one
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
see [`AUTO_PIPELINE_DESIGN.md` §2](AUTO_PIPELINE_DESIGN.md#2-how-pipelines-physically-form)), broken down by decoupled region — computed on the final emitted
table so it includes any depth the [pin-and-confirm](AUTO_PIPELINE_DESIGN.md#5-latency-pin-and-confirm-loop-pypeline-designs-only) re-elaboration added:

```
[sweep] Pipeline depth summary:
[sweep]   chacha20_pipeline_shared: 19 slice(s) total (20 pipeline stages)
[sweep]     chacha20_block_step: 1 internal slice x 10 + 9 shared output
[sweep]       boundaries = 19 slices
[sweep]     (decoupled regions above sum to the end-to-end pipeline depth
             when in series, as in a stream pipeline)
[sweep]   some_planless_main: not auto-pipelined (nothing sliceable; meets its
             goal as written if at all)
```

**When auto-pipelining cannot help at all**, the tool also says so
explicitly during the sweep:

- a MAIN with a timing goal but nothing cuttable (no sliceable logic, no
  AUTO_PIPELINE regions) is noted at planning time (a plain message, not a
  warning — this is a normal design shape): *"contains nothing auto-pipelining
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
- a flat fmax while cuts keep growing stops with `plateau`, naming the soft
  floor (if any) as the likely limit, even when that floor's prediction is
  far off;
- generic stops (`iteration_limit`, `no_legal_adjustment`) repeat the last
  unpipelinable culprit if one was seen;
- the presynth wave still prints `Design likely limited to ~X MHz due to
  function: F` when a measured unpipelinable module is slower than a main's
  goal (soft number — its standalone critical path includes IO paths that
  boundary registers may cut in context).

## 4. Feature-specific feedback in the loop

The loop above is shared. Three features add their own steps, each owned by the
feature's module:

- **Constrained AUTO_PIPELINE regions.** Every iteration, right after
  `APPLY_LOCKS`, `AUTO_PIPELINE.ENFORCE_AUTO_PIPELINE_REGIONS` plans and locks each
  constrained call site to its register count; `AUTO_PIPELINE.REGION_FOR_HOTSPOT` /
  `AUTO_PIPELINE_REGION_FEEDBACK` turn a hotspot inside a region into a region
  count change, and `STOP_AT_AUTO_PIPELINE_LATENCY_LIMIT` stops at a cap.
  `PLAN_TOTAL_CUTS` / `PLAN_TRIMMABLE_CUTS` / `PLAN_FINGERPRINT_PLACEMENTS` (here)
  count region cuts along with the main's own.
- **AUTO_MULTI_CYCLE counts.** A failing path matched to an AUTO_MULTI_CYCLE group
  raises that group's count before any pipelining feedback for the main.
- **The `.latency` pin-and-confirm loop.** After pass 1,
  `AUTO_PIPELINE.DO_AUTO_PIPELINE_LATENCY_PASSES` re-elaborates with the harvested
  latencies and calls `DO_SEEDED_CONFIRM_OR_SWEEP`: one confirmation synthesis of
  the seeded table, falling back to a full planned sweep only if it fails.
  `RECORD_CONFIRMATION_RESULTS` records it in `sweep_history.json`.

## 5. Command line

| flag | meaning |
|---|---|
| (default) | planned sweep per MAIN with a target MHz |
| `--comb` | no pipelining; one syn run reporting comb fmax per clock |
| `--coarse` | single-instance coarse sweep only (evenly-spaced global fractions, `GET_BEST_GUESS_IDEAL_SLICES`; latency grown from timing reports); auto-selected for a single main with no target MHz **that can take added latency** (`FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL`). A single stateful/unsliceable goal-less main is not coarse swept: the planned sweep characterizes it as written with one synthesis run and zero added latency. Explicit `--coarse` on such a main is a clear "No main functions are elligible for pipelining" error |
| `--start N` / `--stop N` / `--sweep` | coarse sweep controls (start latency, stop latency, +1 stepping) |
| `--pipeline_min_effort N` | extra full-design syn iterations allowed to reduce stages after timing is met (default 2; 0 = accept the first met result, fastest but possibly over-pipelined); no effect with `--no_sweep` |
| `--no_sweep` | write the sweep's first planned guess as final VHDL and stop -- zero sweep synthesis iterations, timing NOT verified. Works with both the default planned sweep and `--coarse`. |

## 6. Tests

Fast tests in `src/tests/pypeline_tests/inst/`; see
[`pypeline_TESTS.md`](pypeline_TESTS.md) for categories. Feature-specific
end-to-end tests are listed with their features
([AUTO_PIPELINE](AUTO_PIPELINE_DESIGN.md#7-tests),
[AUTO_MULTI_CYCLE](AUTO_MULTI_CYCLE_DESIGN.md#6-tests),
[AUTO_FSM](AUTO_FSM_DESIGN.md#5-tests)).

They run under
`--syn_tool device_models` (DEVICE_MODELS, seconds per synth run; see
[pypeline_TESTS.md](pypeline_TESTS.md#choosing-a-synthesis-tool)) unless marked.
The plain design files are registered in `synth_tests.py`, and the `*_test.py`
wrappers that assert on build output in `build_report_tests.py`:

| test | proves |
|---|---|
| `sweep_comb_test.py` | pure comb MAIN: planner places cuts, meets timing |
| `sweep_two_mains_test.py` | two MAINs: per-main plans, no-attribution fallback |
| `sweep_fsm_auto_pipeline_test.py` | Reg-FSM main + AUTO_PIPELINE region (via `_auto_pipeline_with_io_regs`): cut subtree is the tagged child, FSM latency stays 0 |
| `sweep_stateful_boundary_test.py` | comb→stateful→comb: cuts stop at the stateful boundary |
| `sweep_floor_detect_test.py` (build_report_device_models, sky130, 100 MHz; its unregistered `--syn_tool pyrtl` mode uses 50 MHz) | unreachable goal: floor predicted & blamed up front, sweep stops within 6 syn runs with `plateau` (sky130, prediction off) / `empirical_floor` (PyRTL, prediction matches) in `sweep_history.json`, results written, then `TIMING NOT MET` + non-zero exit |
| `sweep_unpipelinable_test.py` | stateful MAIN with a goal but nothing cuttable: told plainly that auto-pipelining cannot help (planning time + standalone as-written check FAIL + failing report), one full syn run, `TIMING NOT MET` + non-zero exit, and `sweep_history.json` `final` agrees (not met, same MHz, a failure reason) |
| `sweep_planless_test.py` | stateful MAIN with a met goal but nothing cuttable: one standalone as-written check synthesis prints PASS, its critical path is NOT stored as the func delay, one full syn run, exit 0, `sweep_history.json` `final` is a met `as_written` record with `standalone_mhz` |
| `sweep_float32_test.py` (registered once per backend, **every** `--syn_tool`) | the sweep still runs end to end on each synthesis tool: one part-neutral float32 adder MAIN, each tool supplying its own `DEFAULT_PART` and clock goal. See [pypeline_TESTS.md](pypeline_TESTS.md#per-syn_tool-sweep-coverage) |

Every build that synthesizes the top level writes a `sweep_history.json`
iteration record, **including `--comb`** (`action: "comb"`, 0 cuts): that is
the unpipelined measurement every sweep starts from, and the reference point
`sweep_float32_tool_compare.py` plots each tool's curve against. A `--comb`
build never pursued the goal, so its `final` record is
`met: null` / `met_basis: "unverified"`, like `--no_sweep`.

In-process: `sweep_history_record_unit_test.py`
(registered in `unit_tests.py`) pins the `sweep_history.json` `final`
semantics: an assumed-met main is a goal lower bound, a timing failure
overrides the outcome, a confirmation run supersedes the sweep, a restored
snapshot keeps its iteration, and unverified builds get `met: null`.
`sweep_plateau_unit_test.py` (also `unit_tests.py`) pins `AT_PLATEAU`: the
sky130 trace stops at iteration 6 and not 5; still-improving,
no-cut-growth, short, met, or incomplete windows never stop.

## 7. Limitations and future work

1. **The coarse path crashes on narrow leaves.** `--coarse --sweep` can
   raise `GET_BITS_PER_STAGE_DICT: interior zero-bit stage ... for a 2-bit
   op` on a design with many narrow (1-3 bit) leaves at a high cut count —
   reproducible independent of which design triggers it. The leaf-bit-width
   cap that prevents this exists only in the planned sweep
   (`BUILD_SLICE_LANDSCAPE`, §2), not `--coarse`, which consults only
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
   bit requests must materialize their equal-width boundaries — predicted
   assuming one cut per leaf, at formation time — in one common physical
   unit. The planner refuses to *form* the group when peers do not overlap
   under that one-cut prediction, or a coherent ancestor output already cuts
   the frontier more cheaply. This avoids inventing latency, but can miss a
   true graph cut whose raster intervals do not expose that geometry. A group
   that *did* form can still see its realized unit move once
   `MATERIALIZE_BIT_PLACEMENT_REQUESTS` learns a leaf's real request count
   (e.g. a sibling group on the same leaf); `SUMMARIZE_PLACEMENT_GROUPS`
   accepts that move as long as the whole group still lands on one common
   unit, and only raises when realized members genuinely split across
   different units or a member is lost.
5. **Frontier discovery is local to one landscape unit.** It synchronizes
   the operation-output and bit-internal candidates already represented at
   that unit; it does not construct a complete dependency DAG or schedule a
   multi-unit rank globally. More complex fork/join geometries can therefore
   still require graph scheduling if local typed placement cannot express the
   useful physical boundary.
6. **Whether raw HDL leaves should support genuinely uneven bit-split
   boundaries** (rather than always equal-width, [`AUTO_PIPELINE_DESIGN.md` §2](AUTO_PIPELINE_DESIGN.md#2-how-pipelines-physically-form)) is open. Measured
   evidence so far favors equal-width — real per-width delay is monotonic
   and concave, so minimizing the worst stage at a given stage count means
   equal-width chunks — but the constraint itself has not been revisited
   since.

## History

Why things are the way they are. Entries are keyed by **topic, not date** —
when something changes, revise the entry that owns that topic rather than
adding a new one. Keep a fact here only if it still changes a decision
today: an alternative someone would otherwise retry, a measurement that is
still a live regression reference, or the reason a default is what it is.
Numbers carry the conditions they were measured under, not the date they
were taken.

### Why the planned sweep replaced the middle-out sweep

The original auto-pipelining sweep grew pipeline depth via four interacting
multiplier knobs (`best_guess_sweep_mult`, `hier_sweep_mult`, and two more)
against evenly-spaced "best guess" register placements, synthesizing every
hierarchy level up front (a full wireguard build cost roughly 16 full
synthesis runs) and silently exiting 0 on unmet timing. The planned sweep
(`src/SWEEP.py`) instead builds a static delay model of where delay actually
lives (the *landscape*) and where cuts are legal, starts from a
measurement-frontier-calibrated fewest-stages guess, and adds stages only
from synthesis feedback — typically far fewer syn runs, and a hard non-zero
exit on unmet timing rather than a silent pass. See §1's vocabulary table
for the terms this introduced.

### Mux select-fanout cliff

A single mux select bus registered on top of an already-registered, wider
parallel sibling can materialize a real register while adding zero pipeline
depth, since `GET_PIPELINE_MAP` schedules a shared downstream consumer by
the max of its inputs' readiness — a short branch's register is free once a
slower sibling already bounds that max ([`AUTO_PIPELINE_DESIGN.md` §2](AUTO_PIPELINE_DESIGN.md#2-how-pipelines-physically-form)). Found on `soft_shift_rot`
(sky130, real liberty STA): a 7-cut plan with this placement measured
105.95 MHz with 4 max-capacitance violations, where dropping the
non-deepening placement alone reached 252.13 MHz at 6 cuts with none, and
additionally chunking the remaining wide selected banks by default reached
377.41 MHz — beating even the escalation ladder's own best result on that
design (317.36 MHz at 8 cuts), with fewer register banks.
`DROP_NON_DEEPENING_PLACEMENTS` ([`AUTO_PIPELINE_DESIGN.md` §2](AUTO_PIPELINE_DESIGN.md#2-how-pipelines-physically-form)) is the fix, and defaulting wide
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
actually emit (§2) *and* realized-plan judging to rank by
budget-met-then-fewest-cuts rather than raw worst stage (§2, `_PLAN_RANK`);
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
