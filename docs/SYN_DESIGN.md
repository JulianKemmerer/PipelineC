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
| slices vs latency | conflated in logs ("0 clks 53 slices") | reported separately: `cuts=N main_latency=M deepest_pipeline=D` |
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
accounting) — a stateful MAIN prints `main_latency=0` while a deep
`deepest_pipeline` runs inside it. That is expected, not a bug.

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
 "cuts": 2, "main_latency": 2, "deepest_pipeline": 2,
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
        got=47.91MHz (20.87ns) cuts=12 main_latency=0 deepest_pipeline=12
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
        (10.11ns) cuts=3 main_latency=4 deepest_pipeline=4 predicted_stage=9.10ns
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

**When autopipelining cannot help at all**, the tool also says so
explicitly during the sweep:

- a MAIN with a timing goal but nothing cuttable (no sliceable logic, no
  AUTOPIPELINE regions) warns at planning time: *"contains nothing
  autopipelining can help - the goal is met only if the design meets timing
  as written"* — and again with path endpoints if its timing report fails
  (which also feeds the `TIMING NOT MET` failure exit above);
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
   synthesis, no file I/O).
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
   `SYN.DO_SEEDED_CONFIRM_OR_SWEEP` runs **one** full-design synthesis: timing met
   (the expected case — only FIFO/counter widths changed) means done, and the
   `.latency` values the design consumed provably equal the stage counts built —
   pinning makes cross-pass latency drift impossible by construction. The
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
| `sweep_unpipelinable_test.py` | stateful MAIN with a goal but nothing cuttable: told plainly that autopipelining cannot help (planning time + failing report), one syn run, `TIMING NOT MET` + non-zero exit |
| `autopipeline_latency_test.py` | end-to-end factory design (`make_stream_pipeline`, no MAX_IN_FLIGHT) through the full sweep **plus** the §6.5 pin-and-confirm loop: pass 2 runs, harvested `.latency` > 0, one seeded confirmation syn passes with no fallback sweep and no pass 3, latency matches `sweep_history.json` |

Unit/in-process coverage (registered in `elab_tests.py`):
`autopipeline_harvest_test.py` (harvest grouping + divergence, seed two-tier matching
+ call-site-change detection, `CANONICAL_CALLABLE_KEY` determinism, latency
cache/read-flag) and `double_parse_file_test.py` (repeated `PARSE_FILE` equivalence).

Real-toolchain validation: the wireguard-fpga ChaCha20-Poly1305 build
(`wireguard-fpga/3.build/pypeline_build/build_syn_tb_pipe*.sh`, Vivado) and the
multi-clock streamsoc example (`examples/stream_soc/cpu/hardware/top.c`).
