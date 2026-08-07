# Autopipelining and the Throughput Sweep

How PipelineC turns combinational logic into pipelines to meet an fmax goal,
and how the *planned throughput sweep* replaced the old "middle out" sweep.

## 0. Who does what

| file | role |
|---|---|
| `src/SYN.py` | The infrastructure that already existed and remains: timing params (`TimingParams`, slices, IO regs), the pipeline map (`GET_PIPELINE_MAP`), recursive slicing (`SLICE_DOWN_HIERARCHY_...`), per-function path delay collection (`ADD_PATH_DELAY_TO_LOOKUP`), the coarse sweep engine (`DO_COARSE_THROUGHPUT_SWEEP`, kept for `--coarse` and mini-sweeps), entity writing, and the `DO_THROUGHPUT_SWEEP` entry point. |
| `src/SWEEP.py` | New. The *brains* of autopipelining: cut domains, slice landscapes, floor prediction, cut planning, and the synthesis-feedback refinement loop (`DO_PLANNED_THROUGHPUT_SWEEP`). Replaces the old middle-out sweep that lived in SYN.py. |

Vocabulary used throughout (each defined in detail later):

| term | one-liner |
|---|---|
| **slice** | a fraction 0.0–1.0 of one module's delay where a register row is inserted (`TimingParams._slices`); the only way registers physically exist, ultimately always in raw HDL *leaves* |
| **cut** | a planned register row across a whole *cut domain*'s delay axis; one cut becomes one-or-more leaf slices |
| **cut domain** | the largest subtree registers may be added to (a comb MAIN, or each AUTOPIPELINE-tagged region) |
| **landscape** | the flattened delay axis of one domain: where every nanosecond of logic lives and whether a cut may land there |
| **segment** | one leaf-most piece of that axis (sliceable / atomic / locked) |
| **floor** | the fmax that no amount of added registers can beat (longest un-cuttable stretch) |
| **plan** | per-MAIN sweep state: domains, landscapes, cuts, learned scale factors, locks |
| **measurement frontier** | the topmost fully-combinational funcs — the only hierarchical modules ever synthesized per-module; their measured through-delays calibrate the estimates of everything above (and thus how many cuts the first plan gets) |
| **lock** | a mini-sweep result frozen onto all instances of a func (`params_are_fixed`); planning treats it as a pre-pipelined black box |
| **trim** | post-met iterations that retry with fewer cuts to prove the stage count is minimal |

## 1. Old vs new, in one table

| | old middle-out sweep | new planned sweep |
|---|---|---|
| where do registers go? | evenly spaced "best guess" slices over the whole delay, count grown by a multiplier when timing failed | cuts placed by a static delay model (the *landscape*) that knows where delay lives and where cuts are legal |
| how many stages? | however many the growing multiplier reached when timing first passed | fewest-stages first: budgets calibrated by the *measurement frontier* (topmost fully-comb funcs, measured) start at the theoretical minimum (usually just missing timing) and stages are added only from synthesis feedback; met-with-slack results get trimmed (`--pipeline_min_effort`) |
| how many syn runs? | every hierarchy level synthesized up front, including MAINs + a full-design run per guess + per-module coarse sweeps when guesses plateaued (wireguard: ~16 full runs) | leaf functions + the measurement frontier (topmost fully-comb funcs) + topmost untagged stateful modules (everything else estimated — never MAINs, never anything with state inside) + one full-design run per iteration, max 12 (+ trim/probe runs) |
| unmet timing at the end | exit 0, results written, sim runs — silent | results written for debugging, then `ERROR: TIMING NOT MET` block + **non-zero exit**; sim/bitstream skipped |
| reaction to failing timing | grow `best_guess_sweep_mult`, or step `hier_sweep_mult` down the hierarchy and coarse-sweep smaller modules (4 interacting multipliers) | escalation ladder: densify the attributed hotspot func → measure estimated delays for real when fmax stagnates → only then mini-sweep + lock the hotspot (measured, minimality-probed); global rescale when attribution is impossible |
| unreachable goals | plateaued for many runs, then gave up | fmax *floor* predicted and blamed before any syn run; sweep stops at the floor |
| slices vs latency | conflated in logs ("0 clks 53 slices") | reported separately: `cuts=N main_latency=M pipeline_stages=D` |
| pipeline depth | only the top module's own latency (0 for a stream) | a `Pipeline depth summary` at *Writing Results* totals every register stage built, including inside decoupled sub-pipelines |
| state | `SweepState` + 4 multipliers, pickled `.sweep` resume files | `MainSweepPlan` per main; no resume (syn log caching already makes re-runs cheap); history written to `sweep_history.json` |

## 2. How pipelines physically form (unchanged)

This part works like it always did. Registers only physically exist as:

1. **Leaf slices** — a raw HDL leaf (no submodules, e.g. `BIN_OP_PLUS`) with
   `TimingParams._slices = [0.5]` becomes a 2-stage adder, carry chain broken
   at 50% of its delay (a slice value is always a fraction 0.0–1.0 of that
   module's *own* delay). Leaf latency = `len(_slices)`:

   ```
   4 ns ADD, _slices = [0.5]:
   in --[ low 2 ns of carry chain ]--REG--[ high 2 ns ]-- out   (1 clk latency)
   ```
2. **IO regs** — `_has_input_regs/_has_output_regs` add boundary registers.

Everything else is *emergent*: a hierarchical module's latency is rebuilt
bottom-up from its children by `GET_PIPELINE_MAP`, and the VHDL writer
registers wires crossing stage boundaries (`REG_STAGEn_<wire>`). A cut
"through" a hierarchy is really the old recursive mechanism translating a
fraction of the parent's delay into fractions of child delays until it
reaches leaves:

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
factories with internal `autopipeline()` calls: wireguard's block_step
accepted "1 slice" became 4 real stages). And an **autopipeline-tagged call
site reports latency 0 to its container** (so FSMs keep their cycle
accounting) — a stateful MAIN prints `main_latency=0` while a deep pipeline
runs inside it. That is expected, not a bug.

**A module's latency is not its slice count.** A module's total latency is
its own leaf slices *plus* the summed latencies of its submodule instances,
so an entity named `foo_25CLK` can legitimately carry only 8 slices of its
own (the other 17 stages live in submodules). `latency == slice count` holds
*only* for a pure-comb, fully-sliceable region (nothing below it to add
depth) — which is exactly the region `CHECK_CUTS_VS_LATENCY` marks `strict`.

**Reporting how deep the design got pipelined.** Because a stream MAIN reads
`main_latency=0` and the deepest single instance (one block_step) is far
shallower than the whole pipeline, neither alone answers "how many stages did
autopipelining build?". So the metric reported as `pipeline_stages=` per
iteration and in the `Pipeline depth summary` at *Writing Results* is the
**total register stages in a main's cut domains**:

```
total = (register stages sliced directly into the cut-domain roots)
      + (latency of every decoupled autopipeline region instance in them)
```

The two parts never overlap: a domain root's own latency already zeroes its
decoupled children (they report 0 to it), and the second term adds exactly
those back. This equals the input-to-output depth when the regions sit in
series, as in a stream pipeline (wireguard chacha: 0 monolithic + block_step
3 clks x 10 = 30 stages — not the "3" a single-instance view would show).
The summary is computed at *Writing Results* on the final, actually-emitted
table, so it reflects any extra depth the AUTOPIPELINE pin-and-confirm
re-elaboration (§6.5) added.

Entity naming is also unchanged: each distinct (IO regs + leaf slices)
combination hashes to its own VHDL entity `funcname_<latency>CLK_<hash>`.

## 3. Delay model: leaf-only synthesis with estimates

Old: `ADD_PATH_DELAY_TO_LOOKUP` synthesized **every** function individually —
adder, foo, bar, and MAIN each got a syn run — because composing delays from
children was thought too inaccurate.

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
synthesized per-module — a domain root like wireguard's `encrypt_dataflow`
(Reg/Feedback in its FIFOs/interlocks) is estimated, not measured. The
calibration that used to come from measuring domain roots comes instead
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

**Estimates are never allowed to be why a sweep fails**:
- `MEASURE_DELAYS(funcs)` really synthesizes given functions and replaces
  their estimates (invalidating stale pipeline-map caches);
- the refinement loop calls it automatically when it runs out of ideas while
  estimates are still in play (streamsoc: `Falling back to full hierarchy
  synthesis: replacing 21 estimated delays with measured results...` — after
  which sample_power's plan shrank from 25 cuts to 14 and still met timing);
- `--full_hier_syn` forces the old synthesize-everything behavior up front.

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

### Cut domain

*Where is adding registers even allowed to start?* A **cut domain** is a
maximal subtree that can accept added latency: the MAIN itself if it is pure
comb, otherwise each region reached through AUTOPIPELINE-tagged call sites
underneath stateful containers. One plan per MAIN, one or more domains per
plan.

In the running example `my_main` is itself sliceable comb (the state lives
*inside* `acc`, which the descend rule below refuses to enter), so the whole
main is one cut domain with root `my_main` — the left shape below. The right
shape is what real stream designs (wireguard) look like: the MAIN is an FSM,
so registers may only be added inside explicitly tagged regions:

```
 MAIN (pure comb)                    MAIN (FSM: Reg/Feedback -> not sliceable)
   = the whole MAIN is                 |
     one cut domain                    +-- prep_fsm (stateful, no tag)   X no domain
                                       |
                                       +-- wrapper (stateful)
                                             |
                                             +-- autopipeline(chacha_loop(...))   <- TAG
                                                   |
                                                   chacha_loop = cut domain root
```

This replaces the old question "which module should the middle-out sweep
coarse-sweep next?" — instead of discovering boundaries by trial synthesis,
the domains are computed once from the sliceability rules.

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

### Landscape and segments

*Where inside a domain may cuts land, and what does each stretch of delay
cost?* `BUILD_SLICE_LANDSCAPE` flattens a domain onto its delay axis into
leaf-most **segments**:

- `sliceable` — raw HDL leaf; cuts anywhere inside produce a register,
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

`finalize()` rasterizes the segments into three per-unit arrays. `legal[u]`
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

`PLAN_CUTS` walks left to right filling a per-stage budget of
`target_period / global_scale` weighted units — 10 ns here — and drops a
cut on the **last legal unit** whenever the budget fills (an atomic run
longer than the whole budget just gets its own stage):

```
walk:  units 0..9 accumulate 10.0 -> budget full at unit 9, legal -> CUT@9
       units 10..19 accumulate 10.0 -> unit 19 legal          -> CUT@19
       units 20..24 = final stage (4 ns, no cut needed)

cuts = [9, 19]   ->  3 stages of ~10ns / ~10ns / ~4ns
```

Cuts then convert to the same fractional slices the old code used —
`fraction = (unit + 0.5) / total_units` — and `SLICE_DOWN_HIERARCHY`
translates each fraction into leaf slices (Section 2). After applying:

```
cut@9  -> 9.5/25 = 0.38 of my_main -> 9.5ns is inside mul_add[1] (0..10)
          -> 3.5ns into ADD (6..10)  -> ADD._slices  = [0.875]
cut@19 -> 19.5/25 = 0.78 of my_main -> 4.5ns into mul_add[2] (15..25)
          -> 4.5ns into MULT (0..6)  -> MULT._slices = [0.75]

TimingParamsLookupTable (only non-empty entries shown):
  my_main/mul_add[1]/ADD   ._slices = [0.875]   # leaf register row 1
  my_main/mul_add[2]/MULT  ._slices = [0.75]    # leaf register row 2
  -> my_main rebuilt latency = 2 clks = 3 pipeline stages
```

Parallel branches overlap on the axis; a unit is legal if *any* sliceable
leaf covers it. The old equivalent of all of the above was
`GET_BEST_GUESS_IDEAL_SLICES(n)` = n evenly spaced fractions, blind to what
they'd hit (a cut at 0.5 here would have landed inside `acc` and been
silently lost — the "Finding #1" bug class the invariant now guards).

After applying cuts, `CHECK_CUTS_VS_LATENCY` compares the planned cut count
against the leaf slices that actually materialized in the domain subtree.
Its strictness follows the landscape:

- **Zero leaf slices** while cuts were planned: always a hard error
  (the Finding #1 class — every register vanished).
- **Fully sliceable domain** (every delay unit legal — pure comb, a
  register can go anywhere): fewer leaf slices than cuts is a hard error —
  nothing in the domain may absorb a cut, so a shortfall means slicing
  descent itself is broken. *More* slices than cuts is normal even here:
  a cut is a stage-boundary line across the dataflow, and where it crosses
  parallel branches each branch materializes its own leaf register.
- **Domain with unsliceable spans** (atomic/locked segments): cuts
  legitimately shift/merge around those spans on the way down, so a
  shortfall is expected — a one-line `[sweep] note:` only, no warning.

### Floor

*What fmax can this domain never exceed?* The longest run of illegal units
is the predicted minimum stage delay — reported with a blamed instance
**before any synthesis run**. Old behavior: this was discovered empirically
by watching 5+ full syn runs plateau at the same MHz.

In the running example the longest illegal run is `acc`'s 5 units → floor =
1000/5 = 200 MHz, comfortably above the 100 MHz goal, so the report is just
informational:

```
[sweep] main=my_main domain=my_main comb delay ~25.0 ns, target 10.0 ns
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

### Plan

`MainSweepPlan` (one per MAIN with a target MHz) replaces the old
`SweepState`/`InstSweepState` multiplier bookkeeping. For the running
example, mid-sweep after one failed iteration that was attributed to
`mul_add`, the plan would look like:

```python
MainSweepPlan(
  main_inst        = "my_main",
  target_mhz       = 100.0,
  domains          = ["my_main"],            # cut domain roots
  landscapes       = {"my_main": <SliceLandscape above>},
  cuts             = {"my_main": [9, 19]},   # planned cut units per domain
  # learned calibration (successors of the old global multipliers,
  # but per-func where attribution allows):
  func_delay_scale = {"mul_add": 1.75},      # densify: mul_add units now
                                             #  cost 1.75x stage budget
  global_scale     = 1.0,                    # no-attribution fallback knob
  locked           = {},                     # inst -> (slices, io_regs) from
                                             #  mini-sweeps, none here
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
 "cuts": 2, "main_latency": 2, "pipeline_stages": 2,
 "predicted_stage_ns": 10.0, "bottleneck": "mul_add",
 "action": "densify(mul_add x1.75)"}
```

## 5. The refinement loop

```
                 +--------------------------------------------+
                 | plan cuts per domain (landscape + budget)   |
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
   at hard floor? / soft floor + stagnant? --> stop, warn, keep best (exit 0)
          |
   attribute critical path to a function (approximate)
          |
   hotspot found:   func_delay_scale[hotspot] *= target/achieved  -> replan
   hotspot 3x:      isolated mini-sweep of that func, lock result
                    (only after estimates are measured - see ladder below)
   hotspot locked:  global rescale once, then stop if stagnant
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

**Escalation ladder for a stuck hotspot** — ordered so that fixing the
*delay model* always comes before adding registers by force:

1. densify cuts in the attributed func (`func_delay_scale`) — replan;
2. fmax stuck at the same value while cuts grow means cuts are not landing
   on the real critical path → **measure** all estimated delays for real
   and replan with true geometry (mini-sweeps are gated off until this has
   happened);
3. still attributed to the same func 3× → isolated **mini-sweep**: measure
   the hotspot's own delay first if it is fully comb (the coarse initial
   guess divides delay by target period — an inflated estimate would
   over-pipeline the lock from the start; a hotspot with state below keeps
   its estimate, the loop self-corrects), coarse-sweep upward from that
   guess, then **bisect downward** (`MINISWEEP_TRIM_PROBES` single-latency
   runs) between the last failing and first passing latency before locking
   — the lock lands on the proven-minimal latency, never the first passing
   overshoot.

A same-fmax comparison uses a *relative* tolerance (1% of target):
62.92 → 62.99 MHz is the same result, not progress.

The old loop's outer structure ("reset to zero clocks, slice, synthesize,
adjust") survives, but the *adjust* step changed from multiplier growth +
hierarchy step-down to the table above. The old per-module coarse sweep
survives in two places: the `--coarse` CLI path, and as the **mini-sweep**
run on an attributed hotspot (streamsoc: fft attributed 3x → `Isolated
coarse sweep of hotspot: fft_2pt_pipeline_no_handshake` → met 129 MHz in
isolation with 2 cuts → locked with IO regs).

**Attribution is approximate by design.** Post-synthesis names below the
top-level MAIN are mangled differently by every tool, and keep/dont_touch
attributes bloat designs — so exact hierarchical matching is never
attempted. Instead:

1. MAINs resolve via entity-name prefixes (unchanged
   `GET_MAIN_INSTS_FROM_PATH_REPORT` — MAIN entities survive unmangled);
2. function-name *fragments* from the domain's landscape are
   substring-scored against the report's register/netlist names (generated
   `REG_STAGEn_<wire>` FF names survive synthesis well); highest score wins.
   The domain root and the main's own names are **excluded** — the flattened
   netlist prefixes every register with the top entity name, so the root
   would match everything and always win, a meaningless attribution;
3. entity-local `REG_STAGEn` stage numbers are logged only — stage indices
   are local to the entity the FF lives in, never global;
4. low confidence → no attribution → global rescale. PYRTL (the no-PART
   software timing model) reports a single fmax with no names at all and
   always takes this path — still floor-bounded and convergent.
5. mains never implicated in any *failing* report count as met once every
   reported path meets its goal (per clock group reports only show the
   group-worst path, which can live in a different main — same semantics as
   the old sweep).

Every iteration logs one line per main — a real one from wireguard showing
targeted densification of the correctly-attributed interior hotspot:

```
[sweep] iter=1 main=encrypt_dataflow_encrypt_dataflow goal=80.00MHz
        got=47.91MHz (20.87ns) cuts=12 main_latency=0 pipeline_stages=12
        predicted_stage=12.51ns bottleneck=chacha20_chacha20_block_step
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
        (10.11ns) cuts=3 main_latency=4 pipeline_stages=4 predicted_stage=9.10ns
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

(A silent version of exactly this — sweep stops unmet, results written,
cocotb sim runs and passes, exit 0 — is how a failing wireguard build once
went unnoticed.)

**Pipeline depth summary.** Right after the *Writing Results* banner, one
block reports how deeply each main ended up pipelined (total register stages,
see §2), broken down by decoupled region — computed on the final emitted
table so it includes any depth the §6.5 re-elaboration added:

```
[sweep] Pipeline depth summary:
[sweep]   chacha20_pipeline_shared: 30 pipeline register stage(s) total
[sweep]     chacha20_block_step: 3 clk(s) deep x 10 instance(s) = 30 stage(s)
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
| `--coarse` | single-instance coarse sweep only (even slices, latency grown from timing reports); auto-selected for a single main with no target MHz |
| `--start N` / `--stop N` / `--sweep` | coarse sweep controls (start latency, stop latency, +1 stepping) |
| `--full_hier_syn` | synthesize every hierarchy level for path delays (no estimates) |
| `--pipeline_min_effort N` | extra full-design syn iterations allowed to reduce stages after timing is met (default 2; 0 = accept the first met result, fastest but possibly over-pipelined) |

## 6.5 AUTOPIPELINE `.latency` pin-and-confirm loop (Pypeline designs only)

Pypeline's `AUTOPIPELINE(func)` tag exposes the sweep's discovered stage count back to
the design's Python as `.latency` (e.g. `make_stream_pipeline` sizes its output FIFO
from it). The stage count only exists *after* the sweep, so the `pipelinec` driver
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

**Loop nesting.** `run_sweep_and_autopipeline` in `src/pipelinec` is the whole
of §5 + §6.5 factored into one function. When a design contains AUTOFSM call
sites, `run_autofsm_schedule_passes` wraps it:

```
bootstrap parse (AUTOFSM call sites are combinational passthroughs)
for each schedule pass:
    ADD_PATH_DELAY_TO_LOOKUP          <- measure the operations, do NOT sweep
    schedule + bind each AUTOFSM
    install schedules, re-PARSE_FILE  <- call sites become the generated FSMs
    run_sweep_and_autopipeline        <- §5 sweep + §6.5 AUTOPIPELINE loop
    timing met, or nothing/only-floors blamed?  -> done
    otherwise shrink the blamed FSMs' per-state budget and go again
```

The bootstrap design is deliberately **not** swept: it holds the raw
combinational blob nobody intends to build, so sweeping it would fail timing
pointlessly. It exists only to be measured.

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
| `sweep_fsm_autopipeline_test.py` | Reg-FSM main + AUTOPIPELINE region (via `_autopipeline_with_io_regs`): cut domain is the tagged child, FSM latency stays 0 |
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

Real-toolchain validation: the wireguard-fpga ChaCha20-Poly1305 build
(`wireguard-fpga/3.build/pypeline_build/build_syn_tb_pipe*.sh`, Vivado) and the
multi-clock streamsoc example (`examples/stream_soc/cpu/hardware/top.c`).

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

`--ops` / `--widths` narrow the matrix; results land in
`op_qor_results_<tool>.csv`, one row per `(op, impl, widths, n_cuts)`,
resumable by `(tool, op, impl, l_type, r_type)`.

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

(`GT uint32×uint32`.) `make_soft_sub_cmp` computes one fixed `diff = a - b`
and derives all four ops from it, which forces an extra `is_zero` term for
`GT`/`LTE` -- `1 if diff == 0 else 0` becomes `BIN_OP_EQ` + `MUX_uint1_t`, and
`(1-neg) & (1-is_zero)` adds a 1-bit `MINUS` and an `AND`. Three gate-level
ops, each charged a full 1.019 ns, is most of the 74% inflation.
`make_soft_sub_cmp_swapped` instead reorders operands per op
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
`make_soft_sub_cmp_swapped` for all four ops (previously `make_soft_sub_cmp`).
`make_soft_sub_cmp` is unchanged and kept for QoR comparison. Compares stay
soft by default -- `raw_revived_sliced` was measured head-to-head and does not
justify reverting `C_BUILT_IN_FUNC_IS_RAW_HDL`. No change to `EQ`/`NEQ`/
`MINUS`, which remain correctly raw-HDL by default.

wireguard-fpga's shared encrypt+decrypt syn_tb build, on
`xc7a200tffg1156-2`, with that one change:

```
chacha20_pipeline_shared: met timing, 30 pipeline register stage(s) built, iterations=6
PASS decrypt_dataflow_shared: 91.17 MHz vs 80.00 MHz goal (confirmation run)
```

**80 MHz met at 30 stages**, against a failing baseline of 62.3 MHz at 40
stages. The plateau itself was never the bug -- the sweep's escalation ladder
(densify → measured fallback → minisweep → lock) is designed to climb out of
one, and does, in 6 iterations. What broke it was feeding that ladder a
comparator that was simultaneously slower and 74% over-modeled.

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

## 9. Soft barrel shifter: mux count is the only lever

`include/pypeline/operators/soft_shift.py`'s variable-amount barrel shifter
(`make_soft_barrel_sl`/`make_soft_barrel_sr`) is a chain of stages, each a
`if amount[i]: result = shifted` conditional assignment beside a *constant*
shift (`result << (1<<i)`). This investigation started from the hypothesis
that mirrors the multiplier investigation above: does the barrel have the
same uniform-width-stage mispricing the flat multiplier had, where genuinely
cheaper early levels get priced the same as the expensive final one?

**The hypothesis does not hold, for a structural reason specific to muxes.**
The constant shift beside each stage is pure rewiring (`CONST_SL/SR_<n>_<type>`
built-ins, zero delay, PY_TO_LOGIC.py:4293-4311) -- so a barrel shifter is
*exactly* a chain of raw-HDL `MUX_<type>` leaf entities and nothing else
(PY_TO_LOGIC.py:3573-3592). And **every mux in a design shares one cached
delay, regardless of width or type**:
`GET_CACHED_LOGIC_FILE_KEY` (SYN.py:3930-3932) collapses the cache key to the
literal string `"mux"` ("Mux is same delay no matter type"); measured value
`path_delay_cache/pyrtl_20nm_0ff/syn/mux.delay` = 1.640 ns for every mux in
the repo. A `MUX` entity is also exactly one logic level
(RAW_VHDL.py:3703-3730, "Which stage gets the 1 LL?"). So stage pricing
*is* uniform -- but for a chain of genuinely identical muxes that is
correct, not a mispricing: there is no analogue of the multiplier's
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

- `make_soft_barrel_rotl` / `make_soft_barrel_rotr` -- the same minimal-stage
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

Every shipped factory (`make_soft_barrel_sl/sr`, the new rotl/rotr, and
`make_soft_shift_rot`) is exhaustively swept in
`src/tests/pypeline_tests/inst/soft_ops_test.py` over tiny widths
(1, 2, 3 bits, where the amount-width formula is most likely to be off by
one) plus `uint8_t`, both directions, and (for `make_soft_shift_rot`) all
four `direction`/`rotate` combinations. A signed sweep of
`make_soft_barrel_sr` against Python's arithmetic `>>` was also checked and
found already correct: each stage's *constant* shift lowers through VHDL's
`numeric_std.shift_right`, which is arithmetic (sign-extending) for a signed
operand type by construction (`RAW_VHDL.py:4251-4310`) -- so no separate
signed barrel implementation was needed, unlike the signed-multiply defect
found in the mult round.
