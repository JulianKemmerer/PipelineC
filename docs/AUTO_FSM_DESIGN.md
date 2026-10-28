# AUTO_FSM: pure functions as resource-shared state machines

`AUTO_FSM(func)` implements a pure combinational function as a finite state
machine that shares operations across several clock cycles. Where
[`AUTO_PIPELINE`](AUTO_PIPELINE_DESIGN.md) cuts one full copy of the hardware with N serial
register slices (N clocks of latency and N+1 combinational regions, II=1),
AUTO_FSM can keep one adder and use it twelve times. Its default area search
also considers [`AUTO_COMB_AREA_OPT`](AUTO_COMB_OPT_DESIGN.md)'s combinational
rewrites, comparing whole scheduled designs rather than assuming maximum
sharing always minimizes area.

Both are tool-driven: you write the function, state a clock goal, and the build
figures out the rest — how many stages, or how many states.

- Implementation: [`src/AUTO_FSM.py`](../src/AUTO_FSM.py) (including the driver loop,
  `DO_SCHEDULE_PASSES`), the tag class in [`src/pypeline.py`](../src/pypeline.py), the
  elaborator hook in [`src/PY_TO_LOGIC.py`](../src/PY_TO_LOGIC.py), invoked from
  [`src/pipelinec`](../src/pipelinec).
- Pypeline (Python) frontend only. The C frontend's `__clk()`-based FSM support
  ([`src/C_TO_FSM.py`](../src/C_TO_FSM.py)) is a different feature solving a
  different problem — there the *user* writes the states.

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section rather
> than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## Table of Contents

- [1. If you have not done this before](#1-if-you-have-not-done-this-before)
- [2. User API](#2-user-api)
  - [2.1 Stream wrapper: `make_stream_auto_fsm`](#21-stream-wrapper-make_stream_auto_fsm)
- [3. How it works](#3-how-it-works)
  - [3.1 Building the DAG](#31-building-the-dag)
  - [3.2 Scheduling and binding](#32-scheduling-and-binding)
  - [3.2b Operand multiplexers](#32b-operand-multiplexers)
  - [3.2c Register allocation](#32c-register-allocation)
  - [3.3 Code generation](#33-code-generation)
  - [3.4 The driver loop](#34-the-driver-loop)
  - [3.5 Delay measurement](#35-delay-measurement)
  - [3.6 Simulation](#36-simulation)
  - [3.7 The minimum-area search](#37-the-minimum-area-search)
  - [3.8 Consuming real sky130 area](#38-consuming-real-sky130-area)
  - [3.9 What the clock goal does to allocation](#39-what-the-clock-goal-does-to-allocation)
- [4. Results](#4-results)
  - [Poly1305 kernels on Artix-7](#poly1305-kernels-on-artix-7)
- [5. Tests](#5-tests)
- [6. Limitations and future work](#6-limitations-and-future-work)
- [History](#history)
  - [Constant-aware cleanup and compact operand plans](#constant-aware-cleanup-and-compact-operand-plans)
  - [Pipelined units and pinned regions](#pipelined-units-and-pinned-regions)
  - [Hardware-only entity names](#hardware-only-entity-names)
  - [Schedules a build produced are applied or the build stops](#schedules-a-build-produced-are-applied-or-the-build-stops)
  - [Measurements before scheduling decisions](#measurements-before-scheduling-decisions)
  - [Measured unit stages](#measured-unit-stages)
  - [Control timing and local repair](#control-timing-and-local-repair)
  - [Tighten loop termination](#tighten-loop-termination)
  - [Forced descent into one-bit gates](#forced-descent-into-one-bit-gates)
  - [Operand multiplexer costing](#operand-multiplexer-costing)
  - [Control-path encoding: constant tables, comparators, and one-hot](#control-path-encoding-constant-tables-comparators-and-one-hot)

---

---

## 1. If you have not done this before

Two pieces of standard high-level-synthesis vocabulary carry most of the design.

**Scheduling** — assigning each operation to a time step (here, an FSM state).
Two constraints: an operation cannot run before its inputs exist, and whatever
chain of operations runs combinationally inside one state must fit in one clock
period.

**Binding** — deciding which physical hardware runs each operation. Two
multiplies scheduled in *different* states can share one multiplier. That
sharing is the entire point of the feature. The price is a multiplexer on each
of the shared unit's inputs, selecting operands by state.

The unit of sharing here is the **entity**: two operations share hardware if and
only if the compiler gave them the same entity name (`BIN_OP_PLUS_int16_t_int16_t`,
a particular float multiplier, a particular `@hw_func`). This has a consequence
worth internalizing early:

> **One operation per unit per state.** A chain of same-entity operations can
> never be packed into one state — you cannot use one adder twice in a cycle.
> A chain of *different* entities can.

**Why loops and straight-line code are the same problem.** By the time AUTO_FSM
runs, Python `for` loops have been unrolled and `if`s have become multiplexers.
What is left is a pure dataflow graph. So "the user wrote a loop" and "the user
wrote twelve similar lines" produce identical graphs, and AUTO_FSM folds both.

**Other vocabulary used below**

| term | meaning |
|---|---|
| entity / `Logic` | one function definition; `parser_state.FuncLogicLookupTable` maps entity name → `Logic`. Every *call site* is a separate hardware instance (`Logic.submodule_instances`) — the compiler shares nothing by default. |
| delay unit (du) | tenths of a nanosecond. `Logic.delay` is an int in these units (`SYN.DELAY_UNIT_MULT == 10.0`), so a 4.2 ns adder has delay 42. |
| node | one operation in the DAG, identified by its local instance name (operation name + source coordinates). |
| glue | a zero-delay operation: struct field reads, constant shifts, rewiring. Free, so never scheduled and never shared — just re-rendered wherever its value is used. |
| functional unit (FU) | one shared hardware instance, identified by entity. |

Background reading, in order: [`docs/SYN_DESIGN.md`](SYN_DESIGN.md) for the
delay model, [`docs/SWEEP_DESIGN.md`](SWEEP_DESIGN.md) for the sweep, [`docs/PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md)
for how Python becomes a `Logic` graph, and
[Automatic (HLS-like) Implementation](pypeline_guide.md#automatic-hls-like-implementation) for
AUTO_PIPELINE, whose machinery AUTO_FSM mirrors.

---

## 2. User API

```python
from pypeline import AUTO_FSM, MAIN, Reg, hw_func, int16_t

@hw_func
def next_state(s: state_t) -> state_t:
    ...                                  # pure: no Reg, no Feedback, no globals

UPDATE = AUTO_FSM(next_state)             # construct once, at module/factory level

@MAIN(40.0)
def top() -> state_t:
    state: Reg[state_t]
    req: UPDATE.in_stream_t              # auto-generated {data, valid} struct
    req.data = state
    req.valid = start_pulse
    resp = UPDATE(req)                   # resp: {data, valid}
    if resp.valid:
        state = resp.data
    return state

UPDATE.latency                           # fixed in->out cycle count; 0 until known
```

**Contract**

- `func` must be `@hw_func`-decorated, **pure** (no `Reg`/`Feedback`/global wires
  anywhere in its call subtree; `BUILD_SCHEDULE` checks the whole subtree with
  `AUTO.FIND_EFFECTS` and names the offending callee, so an impure callee cannot hide
  inside a shared unit), take exactly **one** annotated argument, and
  have an annotated return type. Bundle multiple inputs into an `@struct` — the
  same single-argument rule `make_stream_auto_pipeline` and `make_stream_multi_cycle`
  follow.
- The argument is a `{data, valid}` struct. Use `MY_FSM.in_stream_t`, or any
  structurally identical type — `make_stream_t(in_t)` from
  `include/pypeline/stream/stream.py` works, and is duck-type compatible.
  (`src/pypeline.py` cannot import the `include/pypeline` library, which is why
  it grows its own twin of that struct.)
- An input is accepted **only while the FSM is idle**. A `valid` pulse asserted
  while it is busy is IGNORED — there is no backpressure signal in this version.
  Space requests at least `.latency` cycles apart; `.latency` is available to
  the surrounding Python precisely so it can do that. `make_stream_auto_fsm`
  (§2.1) does this bookkeeping automatically, with real valid/ready
  backpressure instead of manual spacing.
- The result appears with a one-cycle `valid` pulse **exactly `.latency` cycles**
  after the accepted input cycle. `.data` holds the last result between pulses.
  Initiation interval == `.latency`.
- Construct `AUTO_FSM(...)` **eagerly, once**, and capture it by closure into the
  `@hw_func` that calls it. Constructing it inline inside a function body still
  works, but then nothing outside can read `.latency`. (Same rule, same reason,
  as AUTO_PIPELINE.)

**When `.latency` reads 0**, the call site is a zero-latency combinational
passthrough (`o.data = func(s.data); o.valid = s.valid`):

- plain native Pypeline sim (`pypeline_sim.py` run directly),
- `--comb` / `--no_synth` / `--yosys_json` builds,
- the bootstrap elaboration pass of a real build.

This mirrors AUTO_PIPELINE exactly, and it is why a well-written AUTO_FSM
testbench reacts to `resp.valid` rather than counting cycles: the same source is
then correct at latency 0 and at latency 17.

**`max_latency=N`** caps the FSM's in→out latency at N cycles (execution states
plus the registered-output cycle). It is a **hard constraint**: if no schedule
meeting the clock goal fits inside N cycles the build fails, with a message
naming the FSM and the latency found by scheduling. The search considers more
unit copies, concrete pipelined units and alternate sharing granularity (§3.2).
The dependency chain and each implementation's launch/completion delays bound
the attainable latency; failure means the considered implementations do not fit.
Note that "no cap" and "generous
cap" are not the same thing: the area search spends latency to buy area (§3.7),
and the cap bounds how much of it the search may spend.

```python
UPDATE = AUTO_FSM(next_state, max_latency=8)   # never more than 8 cycles
```

`register_output=False` is the area-oriented boundary form: the result and its
one-cycle valid pulse are driven directly in the final execution state, so
`.latency == n_states` and no result register bank is built. The default is
`True` because a raw call site's `.data` then holds the previous result between
pulses. Most designs should not set this directly; `make_stream_auto_fsm` uses it
when its own backpressure holding register is already the output boundary.
The unregistered raw boundary needs an idle accept cycle after its final state,
so its initiation interval is `.latency + 1`.

### 2.1 Stream wrapper: `make_stream_auto_fsm`

`include/pypeline/stream/stream_auto_fsm.py`'s `make_stream_auto_fsm(func,
max_latency=None)` is pure library code (no compiler changes) built the same
way `make_stream_auto_pipeline`/`make_stream_multi_cycle` are: it constructs an
`AUTO_FSM(func, max_latency=max_latency, register_output=False)` internally and
wraps its final-state result in
a real valid/ready `@interface` stream port, so callers no longer hand-roll
the `busy`-register spacing the raw contract above requires.

```python
blob_fsm = make_stream_auto_fsm(blob)
@MAIN(25.0)
def top(stream_in: blob_fsm.in_stream_t, stream_out: blob_fsm.out_fb_t) -> blob_fsm.return_t:
    return blob_fsm(stream_in, stream_out)
```

**Shape: exactly one registered output.** A holding register latches the FSM's
one-cycle final-state pulse; a `busy` register tracks whether the FSM itself is
occupied. Raw AUTO_FSM's optional output bank is disabled here: building it and
then immediately copying it into the wrapper's holding register would spend
two full-width banks on a boundary that needs one.
`stream_in_if.ready` is asserted only when both are free, and the output side
is computed *first* in the body (the same same-cycle out→in trick
`make_stream_multi_cycle` uses), so the slot a result just vacated is visible to
the accept decision in the same cycle — back-to-back requests with an always-
ready consumer still pack tightly, one every `latency` cycles, no bubble.

Two alternative shapes were considered and rejected:
- **Bypass/skid output** (combinational presentation when the slot is free,
  registering only on a downstream stall) matches the raw AUTO_FSM latency
  exactly, but adds a combinational path from the FSM's own output registers
  to the wrapper's port — the registered-output shape has none.
- **Cycle-counter** (mirroring `make_stream_multi_cycle`'s `cycles_since_launch`)
  hits `latency` cycles of II with zero bubble, but its body would have to read
  `.latency` directly — see the next paragraph for why that's a real hazard
  here, not just a style preference.

**Latency = `fsm.latency + 1`; II = `fsm.latency + 1`.** The one extra cycle
over the raw FSM is the holding register. Crucially, **the generated hardware
never reads `.latency`** — unlike the raw call site's manual spacing, the
wrapper's RTL shape is identical whether `fsm.latency` is 0 (bootstrap pass /
`--comb` / native sim) or a real scheduled value. This matters because
AUTO_FSM naming identity carries the wrapped function, `max_latency` and
`register_output`, but excludes the changing schedule/`.latency` state — a wrapper whose body varied with
`.latency` could hash two genuinely different circuits to the same entity name
and reuse stale measured delays. Avoiding `.latency` in the body sidesteps it
by construction.

See `src/tests/pypeline_tests/inst/stream_auto_fsm_test.py` for the native-sim
handshake/backpressure tests and `self_check_stream_auto_fsm_test.py` for the
full self-checking design, also run through real GHDL (§5).

---

## 3. How it works

```
 design.py
    │
    │  ── bootstrap pass ──────────────────────────────────────────────
    │  PY_TO_LOGIC._elab_call sees the tag, finds no schedule installed,
    │  and instantiates a COMBINATIONAL PASSTHROUGH around func.
    │  Purpose: put func -- and every operation inside it -- into the
    │  design so SYN.ADD_PATH_DELAY_TO_LOOKUP measures their delays.
    ▼
 SYN.ADD_PATH_DELAY_TO_LOOKUP        per-operation delays (measured, disk-cached)
    ▼
 AUTO_FSM.HARVEST_AUTO_FSM_SCHEDULES   build DAG -> schedule -> bind
    ▼
 pypeline.SET_AUTO_FSM_SCHEDULE_CACHE     canonical_key -> schedule dict
    ▼
 PY_TO_LOGIC.PARSE_FILE (re-execute the design)
    │  now _elab_call finds a schedule and instantiates the GENERATED FSM,
    │  and .latency reads a real value
    ▼
 sweep + AUTO_PIPELINE convergence  (the normal flow, unchanged)
    ▼
 timing met?  ──no, and an AUTO_FSM is to blame──►  shrink its per-state
    │                                              budget, reschedule, repeat
   yes
    ▼
 final VHDL
```

### 3.1 Building the DAG

`BUILD_DAG` walks the elaborated `Logic` graph of the tagged function. Each
submodule instance becomes a node; operand references are traced back through
the wire graph (`_trace_operand`) to whatever produces them: another node, the
function's input, or a constant.

Before scheduling, typed constant cleanup removes constant-only work and
built-in identities, preserves narrowing and signed assignments, and performs
pruning and typed common-expression elimination. A range proof folds a
comparison whose operand intervals decide it (`AUTO._comparison_result`). An
operand with no known interval, such as a function input, holds some value of
the first type its cast chain applies, so `uint1 > 1` folds to 0 by widths alone.
The proof covers built-in comparisons and calls to the implementation a
comparison was dispatched to, such as the default soft comparator: elaboration
records those in `parser_state.pypeline_compare_impl_ops`, and the call keeps
the operator's meaning. Bootstrap preparation registers
constant-operand primitive wrappers for independent characterization; their
measured delay includes the constant. A comparison the range proof decides gets
no wrapper: it would synthesize to flip-flops only, and a backend reports no
timing path for that ([#288](https://github.com/JulianKemmerer/PipelineC/issues/288)).
`AUTO.delay_implementation_seeds` likewise offers no soft-comparator
alternative for one. Unsigned constant multiplication uses the
existing shift/add implementation factory. Scoped user implementations remain
intact. `DESCRIBE_SCHEDULE` reports the cleanup counts, the dependency floor
(`_chain_floor`: states with one unit per operation and no operand muxes at the
schedule's budget), how many bound unit kinds carry measured rather than
estimated delays, and the chosen width merges and fused pairs.

`AUTO_FSM.py` balances equality-controlled selection chains only after
a BDD proves distinct constant comparisons on the same unsigned index are
exclusive. It retains a default row for out-of-range indexes. The search also
considers compatible unsigned width adapters, recurring closed arithmetic pairs
and full unsharing of an entity. Original cast chains and scoped operator
implementations remain part of every legality proof. A width-adapter move binds
a unit into its next wider compatible unit only (`_local_merge_choices`); a
later merge moves everything already bound to the narrower unit, so longer
chains are reached one step at a time.

Three classifications:

- **delay 0 → glue.** Never scheduled, never shared, re-rendered inline at each
  use. Duplicating free wiring costs nothing. "Unmeasured" never means 0:
  `_schedule_delays` takes this pass's measurement or the carried snapshot, and
  resolves anything in neither through `_resolve_delay_du` (path delay cache,
  submodule sum, width heuristic). A 0-op schedule built from logic whose own
  delay resolves above 0 is refused with `AutoFsmInternalError` (see History,
  "Tighten loop termination").
- **delay fits a state → atomic unit.** Shareable: two nodes of this entity in
  different states bind to one FU.
- **delay exceeds a state's budget → descend**, inlining the operation's body
  into this DAG so something too slow for one state can be split across several.
  "Exceeds" means the operation plus a flat operand-mux allowance
  (`MUX_PENALTY_DU`, 1 ns) does not fit. The fold count is not known yet, so a
  heavily shared unit's real mux can still push a state over budget; the area
  search resolves that by giving the unit more copies (§3.7).

There is a fourth reason to descend that has nothing to do with delay: the area
search may pass an `opened` set of entities it wants taken apart because doing
so is estimated to make the design smaller (§3.7). Both paths go through the
same code; the budget test and the `opened` set are simply OR-ed.

Descent enters an entity if it has a recorded live Python callable — i.e. it
came from Python source that can be regenerated — or if it is a built-in
operator for which the operator library supplied an equivalent that does
(§3.7). The two reasons to descend open a built-in operator into different
equivalents. A **forced** descent (too slow for a state) prefers the
width-halving one: two half-width built-in adds, or two half-width inferred
products and one add, which descend again only if still too slow. A
**chosen** descent (the `opened` set) uses the bit-level soft-operator one.
Descent is **best-effort**: a body that cannot be regenerated falls back
to keeping the operation atomic (reported as a floor) rather than failing the
build. When that operation is slower than one state, `DESCRIBE_SCHEDULE`
appends a `descent blocked:` line naming each such entity and why: it has no
Python source or soft-operator equivalent to open, or an operation inside it
cannot be regenerated, named by instance with its source coordinates
(`UnregenerableOpError`). An operation kept whole as a pipelined unit (§3.2)
is not listed: its stages fit the budget, and its `pipeline` line reports
it. Variable-index reads are regenerated at their original
types, including compound elements and multiple dimensions. Their measured
selection delay participates in scheduling.

**Descent depth is capped** at `_MAX_DESCEND_DEPTH = 8` levels, for the same
best-effort reason: past that many nested calls, the recursive walk gives up
and the entity that would have been descended into stays atomic instead,
reported as a floor. This matters for a deeply-nested soft-operator body —
`register_soft_mult()`'s default carry-save multiplier is a 30-level
deferred-carry chain at `uint16 x uint16`, shedding only a few delay units per
level, so an 8-level cap strands a still-slow atomic node well before the
chain bottoms out (this is exactly what made `qor/multiplier/auto_fsm.py`
narrow its operands to `uint8` — see that file's own comment). The build log
names it: when a descent stopped purely because of this cap, `DESCRIBE_SCHEDULE`
appends a `descend cap: gave up after 8 levels for N entity/ies (...)` line
next to `AT FLOOR`, distinguishing "this genuinely cannot be split further"
from "the cap gave up before reaching a state that fits."

Also skipped while walking: submodule instances whose names contain
`CLOCK_ENABLE`. Those are clock-gating plumbing the backend adds to a `Logic`
when it gates submodules inside an `if`, and they only appear on passes where
that backend step has already run over these objects — which the driver's later
reschedules see, because they reuse a parser state a full build has been
through. They are not data operations, and tracing their operands looks for
drivers a pure function does not have.

`_trace_operand` also records the **cast chain**: every intermediate wire type
between producer and consumer. Assigning a wire narrows to the destination's
width, so a value that passed through a narrower variable in the original code
must pass through the same narrowing in the FSM, or the FSM would compute
something the pure function does not.

### 3.2 Scheduling and binding

`SCHEDULE_DAG` is a list scheduler. Per state, it walks the ready operations in
longest-remaining-chain order and places one if:

1. **some copy of its unit is free this state** — one operation per unit per
   state is exactly what makes a unit shareable rather than duplicated;
2. **the chain still fits the budget** —
   `chain_start + delay + mux_delay ≤ budget_du`, where
   `budget_du = period_ns × 10 × budget_scale` and `mux_delay` is the real,
   measured delay of that unit's operand multiplexer at its actual fold count,
   not a flat estimate (§3.2b);
3. **the units' emission order stays acyclic** — generated source declares units
   in a fixed order. Only combinational producer edges constrain that order;
   a registered producer is read through a `Feedback[T]` local declared before
   the physical calls.

**Pipelined units.** `AUTO_FSM` characterizes existing pure callable
boundaries and primitive arithmetic using AUTO_PIPELINE's count-targeted
landscape and concrete lowering. Depths are planned in order from one, at most
through the first non-improving predicted worst stage or the last legal
placement, and only as far as a caller needs: the shallowest depth whose stage
fits, one level past a chosen depth, or one exact depth. The cache resumes
where an earlier request stopped. This adds no synthesis. Each plain-data
implementation records latency L, initiation interval II, input/output/internal
stage delays, estimated register bits, characterization context and the exact
placement recipe and digest. The search compares these against combinational
and decomposed units by rescheduling the whole function. Its PIPELINE moves are
local steps, as UNSHARE adds one copy at a time: each selection form's
shallowest feasible depth, one level either side of a chosen depth, and back to
combinational.
Recipes retain the root and descendants with concrete register choices;
omitted descendants mean no added registers. Restoration fixes the entire
hierarchy, including those implicit zero placements. Characterization reuses
the existing register estimator's entity/placement cache across depths.

Launch and completion are separate events: launch in state s reserves the unit
until s+II, while the result becomes available in s+L. Dependent work waits for
completion; independent launches may overlap. Register allocation starts a
result's live range at completion and reads its operands at launch. The final
state and hard latency cap include all outstanding results and any output cycle.
Pipelines advance on bubbles; only scheduled completions write work registers.

An optional implementation places operand selection inside the same concrete
AUTO_PIPELINE region as the unit. Its signature carries a selector and typed
arrays of operand alternatives, with a row count recorded in the implementation.
The scheduler includes selection in that region's stage delays and enforces its
row capacity. The area model prices its actual muxes and pipeline storage.
Codegen emits one physical call per FU, with the selected placement pinned;
surrounding sweeps cannot move or grow it. A different realized digest or
latency raises `AutoFsmInternalError`.

**Measured stages.** The landscape predicts stages from the cut positions it
plans, and the realized registers of a nested parallel hierarchy can sit
elsewhere. After each build, a path that ends inside a pinned unit measures
that placement: an isolated stage (both ends inside the unit) or its launch
(from a register of the FSM proper, through operand selection into the first
stage). A path from another unit's output also holds that unit and the
chained logic, so it measures neither. Endpoints are matched through the FSM
instance's elaborated name, as attribution matches them (§3.4). The measured
worst stage replaces the prediction for that placement digest wherever a depth
is judged: forced pipelining, the search's PIPELINE moves and the selected
implementation. A depth predicted to fit but measured over budget is therefore
not chosen again. Before any whole-design build, the driver also synthesizes
each chosen placement without a measurement on its own
(`_measure_unit_placements`: the recipe applied to an isolated copy of the
unit, operand selection included, through the backend's ordinary per-instance
run and synthesis store). A call site whose chosen placement measures over its
budget is rescheduled at once (`_confirm_unit_placements`). The deeper depths
of that recipe are measured first, in parallel up to `-j`
(`_measure_deeper_placements`): every depth `_unit_profiles` predicts can still
improve, below the latency cap. One reschedule then sees them all. Measuring
one depth per round costs a full area search per depth. On WireGuard's Poly1305
epilogue at 80 MHz, `residue_mul_mod` at L=5, 6, 7 and 8 all kept the same
17.9 ns path from the input register through a 34×34 leaf, and the four rounds
took about two hours. One line per recipe reports the measured depth curve and
says when every depth kept the same worst path. Each round
measures a placement the search will not choose again, or ends; a miss the
search cannot avoid is left to the build and its timing loop. The isolated run
does not include the state register's decode in front of the selection, which
the in-context measurement above still catches.

Ready operations are tracked incrementally, through a priority heap fed by a
per-node count of unplaced predecessors. Rescanning every unplaced operation
after every placement is quadratic per state — invisible when a DAG held a few
dozen operations, and fatal now the area search routinely scores candidates
holding thousands.

The ordering check (rule 3) runs for every placement attempt, millions of times
in one area search on the WireGuard Poly1305 kernels. The unit-edge graph is
acyclic before each check, so any cycle the new edges close runs through one of
their targets. `_edges_stay_acyclic` therefore searches only from those targets,
over the existing edges plus the new ones, without copying the graph.

If nothing at all fits an empty state, the cheapest ready operation is forced in
alone and the schedule is flagged **`at_floor`**: one indivisible operation that
no number of extra states can speed up. The driver stops tightening when it sees
this, instead of looping to its pass cap.

**Copies.** Binding is normally one unit per entity, but `SCHEDULE_DAG` accepts
a per-entity copy count, and `schedule["fus"]` maps unit id → entity as an
explicit indirection rather than assuming the two are the same string. Two
things use it: a `max_latency` cap that sharing alone cannot meet, and the area
search's unshare move (§3.7).

A cap first gets the copies it directly forces (`_replication_for_latency`):
an entity used F times with R copies needs at least ⌈F/R⌉ states, so a cap of
S states forces R ≥ ⌈F/S⌉. When the schedule still runs past the cap,
`_replicate_to_cap` searches one knob, a limit k on operations per unit:

- **What k does.** Every entity gets ⌈F/k⌉ copies, and k is bisected for the
  most sharing whose schedule meets the cap.
- **Why one uniform knob.** What keeps a capped schedule long is usually many
  kinds of operation queueing at once, and each unit's operand mux shrinks
  with its fold count.
- **Why not one unit at a time.** Giving units one at a time to the most-loaded
  entity, at most eight times, never reached 64 or 32 cycles on the WireGuard
  Poly1305 epilogue. The uniform search meets both: 64 states with 77 units,
  and 29 states with 326 units, at 80 MHz.
- **When it gives up.** k = 1 is one unit per operation, where only the
  dependency chain sets the state count. A cap that k = 1 misses cannot be
  met, and that schedule's latency is what the failure message reports.

A capped anchor's copies seed the area search, so its candidates start from a
binding that already meets the cap.

Constants: `DEFAULT_BUDGET_SCALE = 0.9` (the delay model does not account for
everything the FSM's own control adds, so leave headroom),
`BUDGET_TIGHTEN_FACTOR = 0.75` (the tightening step only when a failure
reported no achieved MHz, §3.4), `MAX_SCHEDULE_PASSES = 6`. `MUX_PENALTY_DU = 10`
is the descent test's flat operand-mux allowance (§3.1) and the seed for a mux
shape nothing has ever measured. Override the starting budget with
`--auto_fsm_budget_scale`. It applies to every call site the build schedules,
including one a re-elaboration creates during the build (§3.4).

Determinism is load-bearing: node ids come from source coordinates, ties break
on node id, and the schedule is a pure function of (Logic graphs, delays,
budget_scale, the search's grain and binding choices). Independence from the
surrounding design is what makes the driver's loop converge trivially — only an
explicit tightening can change the answer, so there is no fixed-point search.
Which functions get scheduled can still change, when the design sizes one from
a value it reads such as an AUTO_PIPELINE `.latency`; §3.4 covers those call
sites.
The area search is bounded by move and DAG-size caps, never by a wall clock,
for the same reason.

### 3.2b Operand multiplexers

Sharing a unit means selecting its operands per state, and that multiplexer is
the entire cost side of the sharing trade. It is modelled as a **real
entity**, not a flat per-operation constant — a flat estimate is wrong in
both directions at once, over-charging a unit with two users and badly
under-charging one with twenty, exactly the range the area search explores
(see History for the measured error this replaced) — in
`include/pypeline/operators/auto_fsm_mux.py`:

```python
@hw_func
def auto_fsm_operand_mux(sel: uint3_t, choices: int16_t[6]) -> int16_t:
    return choices[sel]
```

Three things follow from that shape.

**Rows are distinct values, not operation count.** Binding N operations to one
unit does not imply N different values on every input port. `_operand_mux_plan`
canonicalizes the expression each use actually sees after register allocation,
including input fields, reused registers, same-state FU outputs, constants and
inline glue trees. Equal values share one row; a port with one distinct value
bypasses the mux; ports with the same state-to-row map share one narrow selector.
The area estimator and code generator consume the same plan, so the ranking
cannot claim a coalescing that the RTL fails to build. This matters especially
under `--no_hier_syn --no_sweep`: it removes leaves and mux inputs before
synthesis rather than relying on cross-instance optimization to discover them.

**Muxes factor through common zero-delay structure.** Distinct complete values
can still differ in only a small leaf. `_operand_factor_plan` recursively moves
the state-selected choice through unscheduled glue, implementing identities
such as

```
mux(sel, concat(common, a), concat(common, b))
    -> concat(common, mux(sel, a, b))
```

Scheduled computation is always a leaf, so the transform cannot move or
duplicate real work across states. It is especially useful for elaborated
loops: accumulators, serializers, CRCs and iterative arithmetic often retain
most of a word while selecting one new bit. On the 32-bit divider it replaced
wide 32-row operand choices with two rolling-register bit reads — one of the
largest single combinational-area reductions available to the search on that
design (§4). Again this is structural before synthesis, so it still helps
when hierarchical optimization and sweeping are disabled.

**It is an array read, not an if/elif chain.** A variable array index elaborates
to the balanced binary `VAR_REF_RD` selection tree — log2(N) deep. A naive
nested if/elif form would instead elaborate to a *priority* chain, N−1 deep.

**One canonical entity per (element type, fold count).** The factory is
memoized, so the entity name is a pure function of (type, n), stable across the
driver's repeated re-elaborations, and — because the callable identity is stable
too — reverse-lookupable in `pypeline_entity_callables` to find the delay that
was measured for it.

**It gets measured.** A generated FSM holds state, so its placement geometry
is estimated from its children. Its operand muxes are independent scheduler
consumers, so
`AUTO_FSM._REGISTER_MUX_ENTITIES` and `AUTO_FSM.AUTO_FSM_MUX_ENTITIES` name these few
entities and scoped characterization collects them for measurement in their
own right. They are small — one 3-to-8-way mux per shared unit input port — so
this is a handful of quick synthesis runs, not a meaningful build cost.
**The entity AUTO_FSM measures is the entity AUTO_FSM instantiates.**

The module lives under `include/pypeline/operators/` with the other shipped
operator code. Each measurement is an ordinary synthesis run, reused whenever
its inputs are identical: from the output directory, or across output
directories with `--syn_cache`
([`SYN_DESIGN.md`](SYN_DESIGN.md#shared-synthesis-store---syn_cache-dir)). The
delays stay out of the name-keyed `cache/delay`, which would not notice an
edited library.

Real numbers matter here: on the PYRTL flow a 6-way `int16_t` mux measures
4.29 ns against a flat-constant estimate's 1.0 ns — a 4× error in the one
term that decides how much sharing is worth doing.

Generated code, per unit input port:

```
u0_sel: uint2_t = 0            # narrow fold-index decode: still an if/elif
if st == 4:
    u0_sel = 1
elif st == 6:
    u0_sel = 2
u0_c0: int16_t[3]              # the wide data path: one array per port
u0_c0[0] = <state 1's operand>
u0_c0[1] = <state 4's operand>
u0_c0[2] = <state 6's operand>
u0_a0: int16_t = _af_mux0(u0_sel, u0_c0)
```

A port with a single user gets no multiplexer at all. A port type that cannot be
arrayed falls back to the inline if/elif form.

**The choices array is `make_array_t(t, n)`, never `t[n]`.** For an array-valued
port, `t[n]` appends an *inner* dimension (arrays follow C order by design: in
`T[A][B]`, `A` is outer),
so a 5-way mux over `uint2_t[4]` used to declare `uint2_t[4][5]` choices and
return a `uint2_t[5]`. Elaboration does not compare array lengths
([#359](https://github.com/JulianKemmerer/PipelineC/issues/359)), so only
VHDL analysis caught it: WireGuard's capped Poly1305 epilogue, the first
schedule to share an array-taking operation, failed in Vivado. The same rule
applies to the FSM's own choice arrays (operand factoring, register-write and
rolling-output muxes). `self_check_auto_fsm_array_mux_test.py` covers both.

Operand equivalence preserves shared glue as a DAG: `_value_equiv_key` memoizes
each node/state traversal, and `_GlueValueKey` caches hashes and compares
structure iteratively. Operand-factor plans memoize each typed choice group;
area traversal and emission visit each shared plan once. Generated glue is
materialized once per node/state, so typed CSE preserves a DAG through code
generation rather than expanding reconvergent arithmetic back into a tree.
Repeated children are not expanded again while hashing
or comparing keys. Hash collisions still trigger exact structural comparison;
the optimization changes analysis cost, not which values may share a mux row.

### 3.2c Register allocation

With everything folded onto a few units, **registers are routinely a larger part
of the design than the units they feed** — on the donut example the model puts
several times more area in registers than in the shared arithmetic.

`ALLOCATE_REGISTERS` runs the classic left-edge allocation over live ranges, so
values that are never live at the same time share a register. A value's range
starts the state *after* the one that computes it, because writeback happens at
the end of a state and reads see the snapshot committed at the last clock edge —
that off-by-one is what lets a value written in state 5 reuse the register
another value was last read from in state 5.

Values of the same c type from the same functional unit always remain the first
choice: this is free because the register's data input is unchanged and only
its write-enable states grow. Values from different units may now share too,
but only when the active area model says one register bank costs more than one
additional mux input. Under sky130 this compares the real 48.84 µm²/bit FF
against the real/cached 2:1 mux-bank cost; the abstract FPGA-oriented model
usually retains same-FU-only binding. A measured/modelled writeback-mux delay is
then added to every producer path, and cross-unit reuse is disabled for the
entire type if any such path would exceed the state budget. The allocator also
prefers a free register already sourced by the current FU, avoiding needless
mux inputs introduced by greedy register numbering.

`ALLOCATE_REGISTERS` is used by both the code generator (which declares the
registers) and the area model (which prices them), so the model cannot drift
from what gets built.

Two conservative recurrence recoveries sit alongside the interval allocator:

- `_OUTPUT_SHIFT_PACKS` recognizes a final, unrolled
  `concat(old[W-2:0], produced_bit)` chain and emits one W-bit rolling register
  instead of W separately-enabled result-bit lifetimes. This can reduce control
  and muxing even when the synthesized FF count is unchanged.
- For a full-width, consecutive consume/produce recurrence, it proves that a
  same-width source is read only at the two descending bit positions that a
  left-shifting register exposes. The source and output then share one rolling
  vector, while the produced bits share one one-bit lifetime register. Any
  whole-vector read, unexpected bit position, skipped state, compound/signed
  mismatch, or combinational recurrence that still contains older source bits
  rejects the transform. The model explicitly charges the W-bit source/shift
  write-data mux.

Transaction input storage is likewise lifetime-aware for top-level scalar
struct fields and array elements (accepted as `s.data.f` or `s.data[i]`, rendered
by the same path renderer as other references). A field used after the first
state receives its own input
register; unused fields receive none. A uniquely matched first-state-only field
that feeds a recovered rolling source preloads that work register on accept,
instead of occupying a separate input bank for the entire transaction. Whole
input uses, nested or compound fields, and ambiguous matches retain the original
`Reg[in_t]` path. This is the common handwritten-FSM pattern “load early input
straight into work storage,” expressed as a graph/lifetime proof rather than an
algorithm-specific rewrite.

### 3.3 Code generation

The FSM is emitted as **ordinary Pypeline Python source**, exec'd into a
synthetic module (`_exec_generated`, mirroring `pypeline._exec_generated_func`)
and elaborated by the normal path. There is no new backend IR and no VHDL
generator change — which is most of why the feature is as small as it is. It
also means the generated FSM holds real `Reg` state, so SYN and SWEEP already do
the right thing with it: unsliceable, zero added latency, measured as one atomic
block whose delay becomes an fmax floor.

Operations are re-emitted as the Python construct that produced them
(`DECODE_OP`): operators as operator syntax with operand locals declared at the
original port types (which reproduces the identical entity, hence identical
hardware and identical cached delay), and everything else as a **direct call to
the live callable**. Never as operator syntax for non-builtins — the float
library registers operators in a scope, and re-emitted syntax outside that scope
would mis-dispatch. An operation that cannot be decoded raises rather than being
guessed at.

Worked example — `((a+b)+c)+d`, three adds folded onto one adder over three
states (this is real generated output, with injected type names left as-is):

```python
@hw_func
def auto_fsm_chain_428aec93(s: _af_t0) -> _af_t1:
    st_r: Reg[_af_t4]           # 0 = idle, 1..3 = execution states
    in_r: Reg[_af_t2]           # input latch
    v0_r: Reg[_af_t6]           # both non-overlapping sums share this register
    out_data_r: Reg[_af_t3]
    out_valid_r: Reg[_af_t5]
    # Snapshot committed state before any write below (pypeline assignment is sequential)
    st: _af_t4 = st_r
    in_v: _af_t2 = in_r
    v0: _af_t6 = v0_r
    o: _af_t1
    o.data = out_data_r         # registered outputs: data holds, valid pulses
    o.valid = out_valid_r
    out_valid_r = 0
    # Accept a new input only while idle (II == latency)
    if (st == 0) & s.valid:
        in_r = s.data
        st_r = 1
    # BIN_OP_PLUS_int16_t_int16_t: 3 operation(s) sharing one unit
    u0_sel0_lut: _af_t9 = [0, 0, 1, 1]  # state -> distinct port-0 value
    u0_sel0: _af_t8 = u0_sel0_lut[st]
    u0_c0: _af_t10                      # one array per unit input port
    u0_c0[0] = in_v.a
    u0_c0[1] = v0
    u0_a0: _af_t3 = _af_mux11(u0_sel0, u0_c0)
    u0_sel1_lut: _af_t9 = [0, 0, 1, 2]  # a different mapping needs a selector
    u0_sel1: _af_t8 = u0_sel1_lut[st]
    u0_c1: _af_t12
    u0_c1[0] = in_v.b
    u0_c1[1] = in_v.c
    u0_c1[2] = in_v.d
    u0_a1: _af_t3 = _af_mux11(u0_sel1, u0_c1)
    u0_o: _af_t6 = (u0_a0 + u0_a1)      # THE one hardware adder
    # Writebacks: constant write-enable LUT per register, no state compares
    v0_wel: _af_t13 = [0, 1, 1, 0]
    v0_we: _af_t5 = v0_wel[st]
    if v0_we:
        v0_r = u0_o
    ow_lut: _af_t13 = [0, 0, 0, 1]      # last-state pulse
    ow: _af_t5 = ow_lut[st]
    if ow:
        out_data_r = u0_o
    out_valid_r = ow
    return o
```

#### The control path

Everything above that reads `st` is **control**, and how it is built is selected
by `--auto_fsm_ctl` (`auto` by default; `v3`, `v2` and `onehot` are explicit
choices). The shape shown is `v3`.

**`--auto_fsm_ctl v2`** decodes state with comparators: `u0_sel = 0; if st ==
2: u0_sel = 1; elif st == 3: ...` per shared unit, and `if st == 1: ... elif
st == 2: ...` for the writebacks and next state. That is one equality
comparator per fold per unit plus one per state, each followed by a priority
chain — O(states x units) comparators, all of them in the path from the state
register to the operand multiplexers.

**`--auto_fsm_ctl v3`** (what `auto` normally selects) replaces every one of
them with a **constant lookup table indexed by the state**. A constant local
array read at a variable index elaborates to a
balanced selection tree whose leaves are literals, which synthesis
constant-folds to roughly one gate per table output bit. Three kinds appear:

| table | what it drives | width |
|---|---|---|
| `u{n}_sel{p}_lut` | one distinct state→operand-row map (shared by ports with the same map) | `ceil(log2(distinct values))` bits |
| `v{n}_wel` | one register's write enable | 1 bit |
| `ns_lut`, `ow_lut` | next state, output-write pulse | state width, 1 bit |

Exactly **one comparator survives per FSM**: `st == 0` in the accept.

Three details that are load-bearing:

- **`if <one-bit value>:` is a clock enable, not a comparator.** PY_TO_LOGIC
  only inserts a `!= 0` comparison when the condition is wider than one bit
  (`BOOL_C_TYPE` is `uint1_t`), so a write-enable table feeding `if v0_we:`
  costs the table and nothing else.
- **`st_r = ns_lut[st]` is written BEFORE the accept block**, so the accept's
  `st_r = 1` overrides it. Pypeline assignment is sequential; reversing these
  two would silently drop every accepted input.
- **The select table is off the data path.** `st` is a register output
  available at the start of the cycle, so `st -> table -> mux.sel` resolves in
  parallel with `operands -> mux.data`. The scheduler charges `max(data arrival, select arrival) + mux delay`. The select arrival comes from measured decode-shape proxies initially and attributed state-register paths on later passes.

Two shapes were considered and **rejected**: using the state bits *directly* as
a mux select (with data inputs padded out to one row per state) grows the
operand mux from `folds` rows to `states + 1` rows, which on any real data
width costs far more than the decode it saves — sine's 7-fold float64 unit would
buy 8 extra 64-bit mux rows to avoid about 3 gates. And the compiler has no
ROM primitive of its own. The library's `make_ram` ROM is an opaque raw-VHDL
block that generated schedules cannot fold constants into, so a constant array
at a variable index is the closest thing, and it is exactly what is used here.

`onehot` goes further: the state register becomes one bit per state (plus idle),
so every control signal is a constant-index bit read. Write enables become
`v0_we = st1h[1:1] | st1h[3:3]`, the next state is a bit shift, and the accept
is a bit read — **zero** comparators. It pays for this with one flip-flop per
state instead of `log2(states)`, and with a binary encoder per shared unit,
since the operand mux is a measured balanced tree that needs a binary select.
Measured results are in §4. `auto` independently performs the area search for
v3 and onehot, rejects either encoding if it violates the timing budget or
`max_latency`, and selects the smaller estimate. Each encoding uses its measured selector timing in packing and binding. `HARVEST_AUTO_FSM_SCHEDULES` keeps a build memo per call site, keyed by the encoding, corrected timing model and implementation choices. Searches rank and walk independently.
The resolved encoding is
stored in the schedule and printed with both candidate costs. `v2` remains an
explicit regression/A-B mode rather than an automatic candidate.

Points that are easy to get wrong, and are deliberate here:

- **Snapshot every register first.** Pypeline assignment is sequential, so a
  later write to `st_r` would otherwise be visible to an earlier-written read.
  Reading everything into locals up front makes the body a clean "read committed
  state → compute → write next state". (This is the ordering hazard
  `make_stream_multi_cycle` handles by hand; here it is solved once, structurally.)
- **A shared unit's output local is only valid in the state that unit is
  running.** Any value read in a *later* state must come from a register — which
  is exactly what `_cross_state_nodes` allocates, and what an assertion in
  `_render_ref` enforces rather than trusting.
- **Typed locals are emitted before any `if`, never inside one.** A local first
  declared in one branch would have no type on the other paths. Operand
  expressions, narrowing casts, struct assembly and the final result are all
  rendered above the multiplexer/writeback chains for this reason.
- **Struct assembly** (`return my_struct_t(a=..., b=...)`) elaborates to a
  multi-port reference operation, not a single driver. It is rendered as a typed
  local plus one assignment per field, shortest-path-first so a whole-value base
  lands before field overwrites.
- **The logical function key hashes emitted hardware** (`auto_fsm_<func>_<hash8>`),
  including typed operations, binding, state assignments and pinned placement
  digests. Model-only budget or evidence changes keep the entity when the source
  is identical. Changed hardware receives a new synthesis identity.
- Given the same schedule, generated source is **byte-identical** across
  re-elaborations. Entity-name stability across the driver's repeated passes
  depends on it, and `auto_fsm_unit_test.py` asserts it.

Generated source is written to `<out_dir>/auto_fsm_generated/` on every build, so
a problem inside it can be read as source instead of inferred from VHDL. VHDL
presentation retains the user's wrapped function and source location with an
`auto_fsm_` prefix. Bootstrap passthroughs additionally include `comb` so they remain
distinguishable from scheduled FSMs. The registry disambiguates different logical
schedule keys when they share a readable base. `name_index.log` links the emitted
entity, logical schedule key, original user source and generated source; see
[Generated VHDL names](PY_TO_LOGIC_DESIGN.md#generated-vhdl-names).

### 3.4 The driver loop

`src/pipelinec` calls `AUTO_PIPELINE.DO_PIPELINED_BUILD`, which dispatches to
`AUTO_FSM.DO_SCHEDULE_PASSES` when the design contains AUTO_FSM call sites. That
loop wraps `AUTO_PIPELINE.DO_SWEEP_AND_AUTO_PIPELINE` (the
[throughput sweep](SWEEP_DESIGN.md) plus the AUTO_PIPELINE
[pin-and-confirm loop](AUTO_PIPELINE_DESIGN.md#5-latency-pin-and-confirm-loop-pypeline-designs-only)):

```
bootstrap parse (AUTO_FSM call sites are combinational passthroughs)
for each schedule pass:
    SYN.ADD_PATH_DELAY_TO_LOOKUP                  <- measure the operations, do NOT sweep
    schedule + bind each AUTO_FSM                 <- the minimum-area search (§3.7); after
                                                     a tightening, only the blamed ones
    synthesize each new pinned unit placement     <- reschedule a call site whose
                                                     placement misses its budget, after
                                                     measuring that recipe's deeper depths
    install schedules, REPARSE                    <- call sites become the generated FSMs;
                                                     one new to the build is scheduled first
    AUTO_PIPELINE.DO_SWEEP_AND_AUTO_PIPELINE      <- sweep + AUTO_PIPELINE loop (its
                                                     re-parses also go through REPARSE)
    follow the call sites the design now builds
    timing met, or nothing/only-floors blamed?  -> done
    last tightening gained no fmax?             -> done (path is not in the states)
    otherwise shrink the blamed FSMs' per-state budget by the measured miss and go again
```

The bootstrap design is deliberately **not** swept: it contains the raw
combinational blob nobody intends to build, so sweeping it would just fail
timing pointlessly. It exists only to be measured.

**Call sites new to the build.** A call site's key is its function's identity,
closure values included. A design that sizes an AUTO_FSM's function from a value
it reads during elaboration gets a different function, and so a different call
site, when that value changes. WireGuard's Poly1305 kernels have
`capacity = body AUTO_PIPELINE depth + 2`: the bootstrap parse reads depth 0, the
sweep builds depth 1, and AUTO_PIPELINE's pin-and-confirm pass 2 re-executes the
design with depth 1 installed. Every re-parse inside the build goes through
`REPARSE`: the driver's own, the pin-and-confirm passes and the RAM plan
re-parses. A call site with no installed schedule is new. It elaborated as a
passthrough, so its operations are measured as on the bootstrap pass. It is
then scheduled by the steps a pass uses (measurement, control calibration, the
area search, pinned placements, the `max_latency=` exit) and installed beside
the existing schedules, and the design is executed again. The loop then
carries on where it was, so pin-and-confirm still runs one seeded confirmation
synthesis rather than a fresh sweep. Each round installs every new key, and a
construction can depend only on values read before it (AUTO_PIPELINE latencies
are fixed for the re-parse, an earlier AUTO_FSM's latency once its schedule is
installed), so the rounds end without a bound of their own. A call site whose
installed schedule was refused is not new: that is still an internal error
(`CHECK_SCHEDULES_APPLIED`).

After the sweep the driver takes the installed schedules of the call sites the
design now builds, so blame, local repair and tightening follow them
(`_BLAMED_MISS_RATIOS` blames only keys the driver holds). A pass whose call
sites changed is not a tightening of the same FSMs, so the stall rule does not
judge it.

Before the first full search, `AUTO_FSM._measure_schedule_inputs` replaces the
derived estimates that decide the forced-descent grain with measurements (§3.5).
Then `AUTO_FSM._calibrate_controls` measures small decode proxies keyed only by
encoding, state-register width and select width. Both use the ordinary synthesis
store; wiring-only proxies need no run. The FSM keeps its
inline v3 tables, onehot encoders or v2 comparisons. Exact table contents never
create characterization entities. Proxies estimate decode depth; they cannot
measure the fanout and routing of the real FSM. Later attributed paths starting
at the state register replace the proxy with in-context per-unit select arrival.

After synthesis, the driver reads the observation matching the retained
implementation signature. Generated source lines and register writer maps
attribute paths to selection, units, same-state chains and writeback. Ordered
Vivado arcs refine the attribution; endpoint-only backends retain possible writer
chains. Unmatched evidence is stored and reported once per pass.
An arc's source coordinate is read only after the FSM instance's own label,
because that label carries the call site in the caller (`..._py_l79_.../`). Only
cell arcs place a boundary: Vivado may name a net after a neighbouring module.
A boundary sequence that runs against the units' emission order is a merged
cell named after another unit, so it never selects the edge to separate.

Each attributed miss can produce complete schedules with corrected entity/select
delays, registered selection, a separated same-state edge, the next pipeline
depth, or a local extra unit. Feasible candidates compete by the existing area
objective. Local repair corrects model error, so it applies only where the
model said the schedule fits: a schedule whose modelled worst state already
exceeds the clock period was predicted to miss, and global tightening handles
its budget. A repaired build that does not raise fmax falls back to global
tightening rather than stopping; the stall rule judges tightening steps.
The existing pass, stall, floor and hardware-equality stop rules bound the loop;
no extra repair limit is introduced. Unblamed FSMs keep their schedules during
repair. Exact isolated unit-stage paths update carried pipeline timing evidence.

**Why a generated FSM needs no sweep support.** It holds non-volatile `Reg`
state, so `CAN_HAVE_ADDED_LATENCY` is already False: the sweep treats it as an
unsliceable atomic block whose delay, its schedule's worst state (§3.5), is a
soft floor (the `state_regs` reason in [`SWEEP_DESIGN.md`](SWEEP_DESIGN.md#floor)), and
`CALC_TOTAL_LATENCY` reports 0 added latency to its container.

**Scheduling inside the pass loop.** Each pass runs the minimum-area search
(§3.7) rather than a single greedy schedule. It is pure computation over
already-measured delays — no synthesis, no tool output — and it is bounded by
move and DAG-size caps rather than a wall clock, because the schedule has to
stay a pure function of the source. `--auto_fsm_no_area_sweep` restores the
greedy schedule. The search is forbidden from returning a schedule whose worst
state is longer than the greedy one's, so it can never spend the timing margin
this loop exists to defend; when a `max_latency=` cap cannot be met the driver
exits nonzero rather than building something slower than the source asked for.
`MAX_SCHEDULE_PASSES` is 6, since a pass may also be spent absorbing a freshly
measured multiplexer delay.

On a timing failure, `BLAMED_AUTO_FSM_KEYS` decides which regions are implicated.
The sweep names the failing MAIN and, when it could attribute one, the function
to blame — and a generated FSM entity is exactly the kind of unsliceable atomic
block it reports. With no attribution available (notably PYRTL, whose software
timing model reports no path detail) it falls back to blaming every AUTO_FSM under
the failing MAIN: over-blaming costs one extra pass, under-blaming would silently
give up.

Tightening then shrinks the budget **until the schedule actually changes** — one
step does not always move an operation across a state boundary, and rebuilding a
byte-identical design to discover that would waste a synthesis run. Each step
(`TIGHTENED_BUDGET_SCALE`) multiplies the budget scale by the measured miss,
achieved over goal MHz of the worst failure blaming that FSM
(`_BLAMED_MISS_RATIOS`). It also always goes at least just below the
schedule's current worst state, so that state has to repack. A 72.65-of-80 MHz
build therefore steps from 11.2 to 10.2 ns rather than to 8.4 ns, and a
79.99-of-80 MHz near miss still moves its worst state. Without an achieved
number the step is `BUDGET_TIGHTEN_FACTOR`. A fixed 0.75 step once took the
WireGuard Poly1305 epilogue from 11.2 to 8.4 ns, below its 32–34-bit
multiplies and 260-bit adds, and forced descent into all of them at once.
On `auto_fsm_timing_iter_test` (120 MHz, sky130), the measured step met timing
on the third schedule pass with 2 states (122.8 MHz). The fixed step needed a
fourth pass and 3 states (128.6 MHz).
Each tightening trial reschedules only the blamed FSMs, whose budgets moved;
the others keep their schedule, so "changed" means a blamed FSM changed. Each
trial is a full area search, so an unblamed FSM rescheduled there would cost
as much as a blamed one. The next pass reschedules the blamed FSMs, and only
them (`reschedule_keys`). An FSM nothing blamed keeps its installed schedule:
its MAIN met timing or its paths pointed elsewhere, so a new schedule could
only change hardware that is not the problem. On WireGuard, a full
reschedule after one MAIN missed rebuilt the passing decrypt epilogue
(37 to 44 states) and repeated its pinned-unit rounds.
The loop stops when:

- timing is met;
- nothing is blamed;
- every blamed region is `at_floor`;
- **a tightened build did not raise any failing MAIN's fmax** by more than
  `TIGHTEN_MIN_FMAX_GAIN` (1%). The schedule changed and the critical path did
  not, so it runs somewhere the state count cannot reach: the FSM's own
  control, or elsewhere in the MAIN. `TIGHTENING_STALLED` makes this decision.
  It never stops on missing data, and the stop prints the old and new state
  counts and fmax;
- further shrinking changes nothing. `SCHEDULES_EQUAL` compares the hardware
  (`_SCHEDULE_NON_HARDWARE_KEYS` excludes model diagnostics), so this stop can actually fire;
- or at the pass cap.

A stop that leaves timing unmet still fails the build through the normal
timing exit.

**Convergence** is easier than the AUTO_PIPELINE loop's. A schedule is a pure
function of (the function's Logic graphs, its operations' delays, the budget
scale) and is independent of the surrounding design, so nothing can oscillate:
only an explicit tightening changes the answer, and tightening is monotonic and
capped (`MAX_SCHEDULE_PASSES`). The set of call sites can change with an
AUTO_PIPELINE latency the design reads. Such changes happen inside the
AUTO_PIPELINE loop and are bounded by its pass limit.

### 3.5 Delay measurement

AUTO_FSM is an independent delay consumer in
`SYN.COLLECT_PATH_DELAY_REQUIREMENTS`
([SYN_DESIGN.md](SYN_DESIGN.md#5-scoped-synthesis-and-delay-estimates)).
A stateful caller does not require a pipeline landscape for its scheduler to
receive operation delays.

- **Operation roots:** on the bootstrap pass, each `sub_inst_to_auto_fsm_key`
  call (the combinational passthrough) contributes its dependency subtree. The
  scheduler composes measured primitive delays and estimates of the
  hierarchical operations above them.
- **Scheduled FSMs:** once the call points at a generated stateful FSM, that
  FSM is one atomic span whose delay is its installed schedule's worst state,
  or a longer measured stage of a pinned unit (`SCHEDULED_FSM_DELAY_DU`, as an
  estimate). A whole-module synthesis of it reports an input-to-output figure
  rather than a state's delay, and costs minutes per FSM; only an FSM with no
  installed schedule gets one. Nothing inside it is collected. Rescheduling therefore keeps the operation delays carried from the
  bootstrap pass (`_schedule_delays`). Measuring the units inside a scheduled
  FSM replaced those carried delays with whichever units the current schedule
  happened to instantiate. A tightening trial and the rebuilt schedule then
  disagreed (`auto_fsm_timing_iter_test` oscillated 1→2→1 states), and a copied
  warm directory rescheduled differently (`warm_copy_no_resynth_test`).
- **`AUTO_FSM_MUX_ENTITIES`:** registered operand muxes remain explicit
  calibration consumers, independently of the surrounding stateful hierarchy.
  Their reports inform schedule sharing and area search. Identical tool inputs
  reuse output-directory or synthesis-store reports.
- **`parser_state.func_force_estimated`:** the bootstrap passthrough resembles
  a combinational frontier but must stay estimated. Synthesizing the giant
  parallel body would measure hardware the scheduler was asked to share.
  Its operation dependencies still receive calibration.
- **Decisions rest on measurements (`_measure_schedule_inputs`).** A primitive
  width estimated from measured widths (`SYN.PrimitiveDelayModel`,
  [SYN_DESIGN.md](SYN_DESIGN.md#shared-operator-cache-cache)) is the one estimate
  that can stand. It is measured only when its delay plus the flat mux
  allowance lies within its error bound of the state budget
  (`_estimate_could_decide`), the only case where a measurement could change
  whether it fits a state. A helper
  inside the passthrough is eligible but not a frontier, so its delay is
  derived from its submodules: standalone leaves, each with its own registers
  and routing, summed along the deepest chain. Before each pass's search and
  each tightening attempt, the driver builds the plain forced-descent DAG. It
  measures every entity that the DAG opens or keeps atomic over budget while
  carrying only an estimate, then, once no descent changes, every operation
  the cleaned graph binds, including units cleanup creates (balanced
  selections, constant-multiply factories). Descents are measured outermost first: a
  helper measured whole needs none of its children measured. An entity with a
  measured part already over budget is
  not measured: the whole cannot be faster, and synthesizing a kernel's whole
  parallel body is what the passthrough rule above avoids (the first version
  of this rule queued the entire Poly1305 epilogue kernel for one standalone
  run). Schedules carry `measured_entities`, covering generated units outside
  the function's subtree as well, so a later pass that no longer instantiates
  a helper still knows its carried delay is a measurement.
- **Uninstantiated entities (`_measure_entities`).** The delay scope only
  walks instances under a MAIN. Decode proxies, constant wrappers and helpers
  inside a scheduled FSM have none there, so each gets an isolated root
  instance: the backend's ordinary per-function run, with output-directory and
  `--syn_cache` reuse. The design's own instance tables are untouched. A
  stored report from such a run is the same input identity an ordinary build
  computes, so a later build of either kind reuses it. `PARSE_FILE` trims every
  registered measurement root (`AUTO_FSM_MEASURE_ENTITIES`) with the MAIN
  trees, so the measured entity text is the text a scheduled FSM later
  instantiates under the same name.

`FUNC_SUBTREE_HAS_AUTO_FSM` remains available to identify scheduling hierarchy;
`DEL_AUTO_FSM_SUBTREE_CACHE` resets its cache through `SYN.DEL_ALL_CACHES`.

### 3.6 Simulation

`AUTO_FSM._sim_fsm` in `src/pypeline.py` models the generated FSM's registers
for transaction timing — the state count, input latch and output behavior. The
native datapath evaluates the original pure function. Generated arithmetic,
adapters and pipeline placement therefore require native-versus-GHDL checks. It follows the established commit discipline
(`_sim_delay_line`, `_call_sim_model`): the returned value depends only on state
committed at the last clock edge, so repeated evaluation during convergence
cannot churn, and the next state is buffered so only the final pass lands.

Schedules reach the simulator the same way AUTO_PIPELINE latencies do:
`SIM.DO_OPTIONAL_SIM` → `pypeline_sim.run_sim(auto_fsm_schedules=...)` →
`SET_AUTO_FSM_SCHEDULE_CACHE` **before** the design import, because the tag
captures its schedule at construction and any `.latency`-derived Python sizing
must match what was built.

### 3.7 The minimum-area search

`SWEEP_MIN_AREA_SCHEDULE` runs on every AUTO_FSM build unless
`--auto_fsm_no_area_sweep` is given.

#### What it searches over

Within each combinational graph, two scheduling/binding moves:

| move | what it changes | what it buys | what it costs |
|---|---|---|---|
| **open** an entity | one operation becomes its constituent operations | fewer distinct units; different entities may converge on the same smaller pieces and share them | more operations → more states, registers, multiplexers |
| **unshare** an entity | one more physical copy of a unit | narrower multiplexers; fewer states, so fewer registers | one more unit |

The anchor schedule (§3, "the plain share-everything schedule") does neither
of these deliberately: it opens an operation only when it is too slow to fit
a state — a correctness last resort, not a search — and shares everything
unconditionally, which for anything cheaper than its own multiplexer (a
one-bit OR, say) is a straight loss. The search exists to move off that
anchor when it pays.

#### Descending past the operator level

Descent bottoms out at built-in operators by default — a
`BIN_OP_PLUS_uint32_t_uint32_t` has no Python source, so there is nothing to
re-express — but the soft-operator library (`include/pypeline/operators/`)
supplies an equivalent that does — `make_soft_add_ripple`,
`make_soft_mult_shift_add`, `make_soft_cmp_sub_swapped`, … — whose own leaves
are inferred bitwise operations. Descent can therefore continue all the way
down to gates.

**Forced descent halves instead of going straight to gates.** For an unsigned
add, subtract or inferred multiply that is too slow for one state, `_open_target`
first uses the width-halving equivalent from `_SPLIT_FACTORY_FOR_OP`:

| Built-in | Width-halving equivalent | Body |
| --- | --- | --- |
| `PLUS` | `make_soft_add_split` | low-half add, then high-half add taking its carry |
| `MINUS` | `make_soft_sub_split` | the same on `a + ~b`, with carry-in 1 into the low half |
| `INFERRED_MULT` | `make_soft_mult_split` | wider operand split in half: two pinned inferred products, one add of the upper bits |

A carry enters an inferred adder through one extra low bit
(`(x<<1 | 1) + (y<<1 | c)`), so each half is one `+` and its carry chain stays
a carry chain. Each half is itself a built-in, so a half that is still too slow
is split again; one that fits stays a word-level unit. The bit-level flavor made
a 260-bit add into ~1300 one-bit operations. In the WireGuard Poly1305
epilogue, the first budget tightening (11.2 to 8.4 ns) pushed its 260-bit
adds and 32–34-bit multiplies past the budget, and that became a
31,494-fold one-bit AND on one shared unit, which needed at least that many
states. On the same modular multiply at 8.4 ns, halving gives 66 scheduled
operations in 22 states where bit-level descent gave 7,795 in 3,253. A signed
operator, or an add too narrow to shrink when split (the carry-in bit makes a
4-bit add's high half 4 bits again), keeps the soft-operator equivalent.

Split equivalents are prepared by `PREPARE_SPLIT_EQUIVALENTS` breadth-first,
from the function's own operators down through each halving, up to
`_MAX_SPLIT_EQUIVALENTS` shapes. Breadth-first means the cap can only cut the
narrowest halvings, never an operator the function itself uses. The area
search's chosen opens still use the bit-level flavors, whose sharing behavior
the measurements below were taken on.

Candidates are prepared (`PREPARE_SOFT_EQUIVALENTS`) while the AUTO_FSM call
site elaborates, where a live elaborator, the design's module globals and the
tagged function are all in hand at once. That happens on every pass
(`_PREPARE_CANDIDATES`): the bootstrap pass's search chooses among them, and
each scheduled re-parse must record a live callable for every unit the carried
schedule binds — an opened soft multiplier's adder tree, say — or code
generation cannot call it. They land in
`FuncLogicLookupTable` **uninstantiated** — candidates, not hardware. Nothing is
built unless the search picks it. Two supporting details that are easy to get
wrong:

- Built-in operator `Logic` objects are created lazily while walking the
  *instance* tree from the MAINs, so a candidate's bitwise leaves have no
  `Logic` at all until `_RESOLVE_BUILTIN_SUBMODULES` materializes them. Without
  that they look like zero delay and zero area, and decomposition looks **free**.
- Their delays come from `cache/delay` via `_resolve_delay_du`: a candidate
  is never instantiated so never measured, but its leaves are the universal
  bitwise operators every design uses, so real measurements are normally already
  on disk.

`PY_TO_LOGIC` grew two side tables for this, both populated as a side effect of
ordinary elaboration:

- **`pypeline_builtin_op_info`** — entity → (op name, operand c types), so
  AUTO_FSM can ask the library for the right factory without parsing entity
  names.
- **`pypeline_bit_manip_info`** — entity → which builtin produced it, so
  `bit_assign`, bit reads/slices and `concat` can be re-emitted as source. A
  soft adder's body is mostly those; without this, descending into one would
  fail to regenerate and silently fall back to atomic.

**A type living only inside a descended body reconstructs correctly** (a soft
multiplier's local partial-products array, say, or a struct-typed descended
local). `_TypeResolver.resolve` rebuilds an array type `BASE[d1][d2]...`
compositionally from a reconstructible `BASE` — an array is always
reconstructible if its element type is — and `_Codegen` seeds from the
AUTO_FSM'd function's whole elaborated subtree, not just what survived into
the schedule, so a type used only inside a fully-descended entity is still
resolvable. See `qor/multiplier/auto_fsm.py`, the design that exercises this,
and the `[type resolver: array reconstruction]` section of
`auto_fsm_unit_test.py`.

#### The search itself

**Combinational graph choices are included by default.** AUTO_FSM call-site
elaboration (`_PREPARE_CANDIDATES`, on every pass) calls `AUTO_COMB_OPT.prepare` to create exact alternatives through the shared
`AUTO` search ([`AUTO_DESIGN.md`](AUTO_DESIGN.md)): CSE, exclusive sharing, factoring, constant arithmetic, bit-width
reduction and decomposition. No explicit `AUTO_COMB_AREA_OPT` tag is required.
The delay objective of the same preparation path also exposes AUTO_COMB_DELAY_OPT's
speculation, balancing, carry-save and operator alternatives by default.
Up to two delay-ranked finalists join the existing area-oriented candidates;
they are still judged by complete FSM area and must satisfy timing/latency.
No extra synthesis jobs are launched to select these combinational candidates.
`SWEEP_MIN_AREA_SCHEDULE` runs the existing graph-local search
(`_SWEEP_MIN_AREA_SCHEDULE`) on the original and eligible alternatives. Each
choice is scheduled and bound independently, then priced with the same full
register/mux/control area model. Timing and latency caps remain hard constraints;
the original graph's result remains an incumbent. A lower-combinational-area
graph may lose because it needs more state or wider selection logic.

Candidate graphs and their scores are pinned during a build's repeated parses,
but generated callables are rematerialized in each parser state. Soft
equivalents are prepared separately rather than left to `prepare`, which returns
before seeding them when it retains the original graph (a scoped operator
implementation in the call tree). A selected
schedule records its actual source entity and rewrite moves. The additional
candidate count is bounded and very large expanded graphs are skipped before
scheduling; see [the shared search limits](AUTO_COMB_OPT_DESIGN.md#6-fsm-integration).
Explicit forced schedules and `--auto_fsm_no_area_sweep` bypass these choices.
`AUTO_FSM(AUTO_COMB_AREA_OPT(f))` is valid too, but starts from AUTO_COMB_AREA_OPT's explicitly selected graph;
passing the original function gives the broader joint search.

`AUTO_FSM(AUTO_COMB_DELAY_OPT(f))` likewise starts from the explicitly selected zero-cycle graph.
The shared timing snapshot and implementation limits are described in
[`AUTO_COMB_OPT_DESIGN.md`](AUTO_COMB_OPT_DESIGN.md).

Input-storage and output-pack reachability analyses treat reconvergent glue
as a DAG. Shared visited sets avoid exponential path expansion, with per-state
visitation where state affects field use. Operand-equivalence keys share a memo
within one immutable FU-plan computation, never across mutable schedules.
The diamond-graph unit regression bounds accesses deterministically. Large-fold
messages are latency/search-size advisories, not correctness/timing failures.

```
anchor = the plain share-everything schedule      # candidate zero and incumbent
if the anchor has more than MAX_SWEEP_DAG_NODES operations: return it
repeat up to MAX_SWEEP_MOVES times:
    for each openable entity:   reschedule the WHOLE function with it opened
    for each shared entity:     reschedule the WHOLE function with one more unit
    take the candidate closest to the clock budget, then the cheapest,
        even if it is worse than the incumbent
    if it is closer to the budget than the best-so-far, or equally close and
       beats it by > SWEEP_MIN_IMPROVEMENT and clears the anchor-relative
       OPEN shape-confidence guard:
        it becomes the best
    else after MAX_SWEEP_UPHILL consecutive non-improvements: stop
return the best
```

Every feasible candidate also records its state count and estimated area. The
cheapest area at each state count, kept where no schedule with fewer states is
cheaper (`_pareto_frontier`), is the schedule's `area_frontier`, a diagnostic
key outside the hardware identity. `DESCRIBE_SCHEDULE` prints it as
`area vs states`. A single-flight stream FSM's latency is its throughput, and
area-minimal schedules tend to fill a `max_latency=` cap, so this lets a caller
pick a cap from the trade the search already saw, without synthesis. It holds
only what the area walk visited. There is no latency-weighted objective: the
cap is the latency control.

**An oversized anchor keeps coarsening available.** Expansion and unsharing
stop at `MAX_SWEEP_DAG_NODES`, while a pipelined helper can replace an opened
body by one atomic node. Those candidates remain eligible, subject to the same
per-trial graph-size check. The report identifies the skipped expansion work.

Within one call site's searches, bindings with the same typed graph reuse a
compressed cleaned-graph cache (`_AreaSearchMemo`). Its key includes delays,
state budget, opened and preserved boundaries, adapters and fused groups. The
graph before adapters and fused groups is kept too, so MERGE and FUSE moves
rebind it without repeating descent and cleanup. Each candidate receives an
independent decoded graph. The same memo keeps `SCHEDULE_DAG` plans, keyed by
the graph, the encoding's select delay, the unit implementations and the unit
counts. A `max_latency` cap's bisection (`_replicate_to_cap`) schedules each
candidate at several counts, and its one-unit-per-operation trial is the same
plan for every binding of a graph, so UNSHARE and depth moves mostly reuse
plans. A reused plan also records the operand-mux snapshot entries its
scheduling priced, so the schedule is byte-identical to scheduling again. The
memo is shared by both encodings under `auto`: graphs do not depend on the
encoding, and plans only reuse under an equal select delay. Register
allocation and costing still run for every distinct binding.
This cache does not persist between parses and adds no search cutoff; the
selected result does (see [below](#search-results-persist-across-builds)).

Each step's moves are collected first, then built, then judged in move order.
The builds are independent, so with `-j` above one they run in forked worker
processes (`_map_forked`); cache entries a worker adds are merged back, and
the trace, the visited set and the choice are the parent's. PIPELINE moves
characterize each unit's depths the same way, one unit per worker. A
characterization resumes from its cached state, which advances as a new object
rather than in place, so a worker's progress merges back like a new entry. The
result is the same at any `-j`. A platform that cannot fork builds serially.
What a worker materializes in its own parser state (a unit function and its
types) does not come back. Later steps create it again when they need it:
pinned-unit measurement creates its units before it writes the type package,
which a reused result needs too.

#### Search results persist across builds

`HARVEST_AUTO_FSM_SCHEDULES` keeps each call site's selected schedule in the
output directory (`auto_fsm_searches/<digest>.pkl.z`) and, with `--syn_cache`,
in the store (`auto_fsm/v1/<tool>/<part>/<digest>.pkl.z`). A later harvest
with the same digest reuses it instead of searching, prints that it did, and
copies a store hit into its own output directory. The digest covers what the
search reads:
- the call site's key and source identity, the budget scale, the encoding
  request, the area-sweep and force flags, and the whole carried schedule;
- the design's source hashes and a hash of the compiler's and the Pypeline
  library's own sources (`_compiler_source_hash`), so any code change searches
  again;
- `_search_parser_inputs`: every delay an entity carries and its estimated
  flag, the control-path proxies, the clock goals, the target, the delay,
  area and placement settings, and under DEVICE_MODELS the leaf area cache.

An entity without a delay is left out of the digest. A search materializes
such entities as it goes (a candidate's built-in leaves, unit functions), so
leaving them in would make the next harvest's digest depend on whether the
previous one searched or reused. What those entities resolve to on disk is
checked instead. `SYN.GET_CACHED_PATH_DELAY` records every cache/delay file the
process reads (`SYN.CACHED_PATH_DELAY_READS`, merged back from forked
workers), a stored result keeps that record, and a result is reused only while
every recorded file still reads the same, a missing file included. An
unreadable, foreign or stale entry is a miss, never a failure. A reuse
refreshes the stored file's time, and `--syn_cache_prune` removes results no
build has used for that long.
Area contributions use compensated summation so equal modeled costs do not
acquire a different rank merely from their accumulation order. The terms,
weights, confidence margins and existing deterministic tie-break stay the same.

Four deliberate properties:

**Local proposal, global evaluation.** Each move names one entity, but every
candidate is scored by rescheduling the whole function. Opening or unsharing A
changes how B and C pack into states, how many values cross state boundaries and
how wide everyone's multiplexers get; scoring A on its own numbers would miss
all of it.

**Bounded uphill walking.** Opening one operation usually costs area by itself —
one shared unit becomes its unshared guts. The payoff comes when a *second*
operation is opened and the two turn out to be built from the same pieces, which
then share. A search that stopped at the first non-improving move could never
reach that, because the win is only visible from the far side of the move that
pays for it.

**The anchor guarantee.** The share-everything schedule is the incumbent, and
the result is the best point ever seen. It therefore cannot regress according
to its own model. A model can still mis-rank physical hardware — particularly
where limited synthesis shares logic the per-leaf sum cannot see — so the
whole-design A/B tests in §5 remain the ground truth and bound that risk.

OPEN moves get an additional, anchor-relative confidence guard for exactly
that known blind spot. The base required win is `SWEEP_MIN_IMPROVEMENT` (25%),
then it rises by eight percentage points per doubling of scheduled operations
or state count relative to the written-grain anchor (capped at 95%). UNSHARE
does not pay this margin: it keeps the same DAG, so its extra units and narrower
mux/register banks are already the quantities the measured model prices. This
is not a latency preference — a large, slow schedule is still eligible — but a
requirement that a comparison spanning radically different hierarchy/control
shapes show enough margin to survive the documented per-leaf modelling error.

**The search may spend slack, but not miss the declared goal.** Area is the
objective, so a candidate is not rejected merely because its modelled worst
state is longer than the anchor's incidental critical state. It is rejected if
that state runs further past the scaled clock budget than the anchor's does,
or if it violates `max_latency`. For an anchor that fits, that means any
over-budget candidate is rejected. An anchor can itself be over budget: an
operation passes the descent test with a flat 1 ns mux allowance (§3.1), and
then sharing it many ways puts a wider mux in front of it. The search then
ranks candidates by how far past the budget they run before their area, and
any candidate closer to fitting becomes the best. A candidate no further over
than the anchor is kept, so the search can reach a binding that needs two
units widened together. Widening one of them alone leaves the other over
budget, and is only a step on the way.
This lets a low-frequency design trade unused timing margin and latency for
fewer cells. The normal real-synthesis confirmation loop remains the authority:
if model optimism causes a miss, the driver tightens the budget and reschedules
until the built FSM meets the goal. Consequently a larger-area schedule is
accepted only when it is required to satisfy timing or the hard latency cap;
otherwise the lowest-area feasible point wins.

#### Why area is estimated and timing is measured

**Only timing is parseable from every synthesis backend.** Vivado, Quartus,
PYRTL and the rest all report a critical path, and the driver already closes a
loop around it. There is no equally portable utilization number, so there is no
version of this search that can depend on one. Area is therefore a
tool-independent internal model — the `AREA_*` constants at the top of
`src/AUTO_FSM.py` — that only ever *ranks* candidates against each other. yosys
cell counts appear only inside the test suite, to calibrate the model and to
prove before/after numbers; never inside the search.

The model has five terms, which are exactly the things sharing trades between:

- **units** — one copy of each bound entity, however many operations use it. The
  term sharing shrinks, and the reason AUTO_FSM exists.
- **glue** — every unscheduled (zero-delay) operation, counted once per use,
  because glue is re-rendered wherever needed rather than shared. Free when it
  really is wiring, emphatically not otherwise. Counting it is what stops
  decomposition from looking free.
- **multiplexers** — one per unit input port, sized by its count of distinct
  operand values after register allocation (not blindly by fold count), plus
  writeback muxes for profitable cross-FU register reuse. The term sharing
  grows, and the reason sharing more finely eventually stops paying.
- **registers** — cross-state values after allocation, plus the output and state
  registers (the output term is absent for `register_output=False`).
- **state decode**.

The constants are normalised so one bit of an adder is 1.0, with ratios taken
from real yosys cell counts (a 16-bit add ≈ 100 cells ≈ 6.25 cells/bit; a
flip-flop, a 2-input gate and a 2:1 mux bit ≈ 1 cell each ≈ 0.16). **The single
most important ratio is arithmetic against multiplexer-and-register**, because
that is the entire sharing trade: a model that priced a 16-bit adder the same
as a 16-bit register would decide that unsharing cheap adders is a win, a
mistake real synthesis measures as 4.5% worse. An adder bit is about six of
the things sharing costs, not one.
`auto_fsm_area_sweep_compare_test.py` is where that correspondence is held to
account.

**Under `--syn_tool device_models`, this changes for three of the five terms.** The
portability argument above is about *timing*, not area specifically — it is
why the abstract model has to exist for every tool, not why it has to be the
only source when a better one is available. Real per-leaf µm² exists for
sky130 (§3.8), so under `SYN.SYN_TOOL is DEVICE_MODELS` the units, registers
and operand-multiplexer terms use real cached measurements wherever one
exists, falling back to the abstract model (scaled into µm²) only where one
does not; the glue and state-decode terms stay abstract regardless, because
neither has a synthesizable entity of its own to measure in isolation. Every
other tool is completely unaffected — same five abstract terms, same
`AREA_*` constants, same numbers as before §3.8 existed.

#### Where the stopping point comes from

Nothing in the code says "stop when the multiplexer delay exceeds the unit
delay". That behaviour falls out of the cost model. Walk the granularity axis far
enough and a 16-bit adder becomes 150-odd gates sharing three one-bit units
across 150-odd states — three tiny units, and multiplexers and registers costing
an order of magnitude more than the adder did. The estimate turns back up and
the search stops.

### 3.8 Consuming real sky130 area

`DEVICE_MODELS`/`SYN.py` measure and cache real per-leaf µm² the same way
they already measure and cache per-leaf delay (full story:
`docs/DEVICE_MODELS_DESIGN.md`'s area section). The search above uses it:
under `SYN.SYN_TOOL is DEVICE_MODELS`, `ESTIMATE_SCHEDULE_AREA`'s unit,
register and operand-multiplexer terms are real cached µm² wherever a
measurement exists, falling back leaf-by-leaf to the abstract §3.7 model
(scaled into µm²) only where one does not. **Ground truth throughout is real
sky130 synthesis, never the abstract model** — a cache hit always wins
regardless of how far it sits from `_leaf_area`'s guess, and a mis-ranking
from a stale or absent measurement is what needs fixing, not the other way
round. `--auto_fsm_abstract_area` forces the old abstract-only ranking, for
A/B comparison against real data.

**Gating.** Every function below only returns real numbers when
`SYN.SYN_TOOL is DEVICE_MODELS` (i.e. `PART("sky130...")` or
`--syn_tool device_models`); for every other tool the cache is empty by
construction (`SYN.GET_AREA_CACHE_DIR` returns `None`) and every AUTO_FSM
build outside sky130 is unaffected — same schedules, same numbers, as
before this section existed.

**The API, mirroring delay's own shape:**

| delay (`_resolve_delay_du`) | area (`AUTO._leaf_area_um2` et al.) |
|---|---|
| `SYN.GET_CACHED_PATH_DELAY(logic, parser_state)` — per-leaf disk cache read | `SYN.GET_CACHED_LEAF_AREA(logic, parser_state)` → `(value_um2, "um2")` or `None` |
| — (no by-key form needed; delay is always looked up via a `Logic`) | `SYN.GET_CACHED_LEAF_AREA_BY_KEY(key, parser_state)` — same read, keyed directly (`"MUX_uint{width}_t"`) for operand multiplexers, priced from `(ctype, fold count)` during scheduling before any mux entity exists |
| `_heuristic_leaf_delay_du` | `_leaf_area` (§3.7), scaled by `UM2_PER_ABSTRACT_AREA_UNIT` into µm² |
| — | `DEVICE_MODELS.GET_SEQUENTIAL_CELL_AREA()` → `(48.84, "um2")` — a closed-form liberty lookup, not a per-shape measurement, so `_ff_area_um2` needs no cache at all |

`AUTO._area_unit_scale(parser_state)` is the single switch: `1.0`
(abstract units, unchanged behavior) for every non-`DEVICE_MODELS` tool or
when `FORCE_ABSTRACT_AREA` is set, `UM2_PER_ABSTRACT_AREA_UNIT` otherwise —
every other area function multiplies its abstract fallback by this, so
`est_area` is directly comparable to a build's own `Measured area: ...` line
under sky130 without further conversion. `AUTO._leaf_area_um2`,
`_ff_area_um2` and `_mux_bank_area_um2` each implement the cache-hit →
scaled-fallback tier for one kind of term; `ESTIMATE_ENTITY_AREA`'s own hierarchy
walk stays AUTO_FSM's, deliberately **not** delegated to
`SYN.GET_ESTIMATED_COMBINATIONAL_AREA` — that function returns `0.0` for an
uncached leaf and reports it as missing, which would read as free wiring and
never get shared (the same failure mode v1's zero-delay bug had). A schedule
carries how much of its `est_area` was measured vs estimated in its
`DESCRIBE_SCHEDULE` build-log line (`area model: sky130 um2 (N measured, M
estimated)`), alongside a new `register bits: N` line (`_register_bit_count`)
recording AUTO_FSM's live-range registers plus compacted transaction input,
state and optional output storage independent of area — useful on its own for
comparing against a real build's sequential cell count (see the register-count
finding below).

**The leaf area cache underneath this excludes the STA harness's own registers**
from each leaf's cached value — see [`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md)'s
History section ("Area model V1 → V2") for why that distinction matters; nothing below
depends on the details, only on the corrected values being what's cached.

**What real measurement corrected, once the harness was out of the way.**
Fitting real cached µm² against width across the `BIN_OP_PLUS`/`MINUS`
entries in `cache/area` gives `UM2_PER_ABSTRACT_AREA_UNIT ≈ 98.93` µm² per
adder bit. Both operators cost `AREA_PER_BIT_ADD` per `_leaf_area`, so one
joint fit covers both. The fit uses only entries whose operands are both at
least 8 bits wide: an incrementer such as `uint16 + uint1` costs about half a
real 16-bit adder, and `area_model_test.py` would otherwise drift as the test
suite caches more of them. `AREA_PER_BIT_MUX` scaled by it is 1.15x the real cached
`MUX_uintN_t` leaves — 29.304 µm²/bit, exact (not just close) across every
measured width 1/8/32/34/64 — a real, independent confirmation of the ratio
`auto_fsm_min_area_verify_test.py` set by a completely different method
(yosys cell counts on one design). `AREA_PER_BIT_BITWISE` splits real cost
roughly down the middle rather than tracking it: scaled it is 1.16x the real
cached `BIN_OP_AND` leaves (13.6752 µm²/bit, exact across widths 1/16/32; a
bare `and2_1` liberty cell matches it exactly) and 0.74x the real cached
`BIN_OP_XOR`/`BIN_OP_OR` leaves (both 21.4896 µm²/bit, matching a raw
`xor2_1` liberty cell exactly) — one abstract constant pricing two real
costs 57% apart, overshooting one and undershooting the other by
construction, not by fitting error. The one term that is not approximate
but *wrong* is the flip-flop:
`AREA_PER_BIT_FF` (0.20, an FPGA number — "paired with its LUT, nearly
free") is 2.5x too cheap against a real sky130 `dfxtp_1` (0.49 abstract
units). `_ff_area_um2` uses the real cell area directly under sky130, no
fitting involved.

**Two structural gaps real measurement does not fix** — cross-instance
combinational sharing, and the whole-design FF-count estimator's own
overshoot — are described in Limitations, below, since neither is specific
to this search's ranking: both are as true of `SYN.ESTIMATE_DESIGN_AREA`'s
build-log estimate as of the terms feeding `ESTIMATE_SCHEDULE_AREA` here. The
anchor guarantees that the selected estimate is no worse than the plain
schedule's estimate; it cannot guarantee physical area when the model
mis-ranks an edge case. A systematic overshoot that hits every candidate
similarly does not change which one ranks smallest, while whole-design
synthesis tests bound the remaining risk.
`inst/auto_fsm_real_area_compare_test.py` is where this is checked against
real synthesis rather than assumed: real-µm²-ranked vs abstract-ranked vs
the plain anchor, all three built and measured, not just estimated.

### 3.9 What the clock goal does to allocation

Two different mechanisms decompose an operation into smaller ones, and they pull
in opposite directions with respect to the clock goal. Confusing them is the
usual source of "why is my design not getting smaller when I ask for less
speed?"

**A HIGH clock goal forces decomposition, and does not unshare.** `BUILD_DAG`
descends into any operation whose own delay plus its operand multiplexer exceeds
one state's budget (`too_slow_for_a_state`). That is a correctness move, not an
optimization: an operation that cannot fit one state makes the clock goal
unreachable at any latency. The pieces it descends into are still SHARED, one
unit per entity — a tight clock never hands anything extra copies. Only a
`max_latency=` cap that sharing cannot meet, or the search's own UNSHARE move,
adds unit copies.

**A LOW clock goal is what lets the search decompose by choice.** With a budget
big enough that the whole operation fits one state, keeping it atomic is the
anchor, and opening it becomes something `SWEEP_MIN_AREA_SCHEDULE` decides on
area grounds — the "split until multiplexers and registers cost more than the
units saved" behaviour an area-first build wants. A loose clock also provides
slack the area search may spend, up to the scaled clock budget; real synthesis
and the tighten/reschedule loop still enforce the declared FMAX. It changes
both what the anchor is and which slower-but-feasible area points can be
considered.

`auto_fsm_min_area_verify_test.py` is where this is measured rather than
asserted: it builds the alternatives the search passed over
(`--auto_fsm_open` / `--auto_fsm_unshare`) and checks the search's answer against
their real yosys cell counts.

#### What that measurement found, and why decomposition usually loses

The latest run of that test includes distinct-operand mux coalescing and the
new register/control allocation. The numbers remain the clearest statement of
the trade. Three uint8 divides at a 1 MHz goal, whole design, `$scopeinfo`
excluded:

| schedule | cells | shape |
|---|---|---|
| share the divider whole | **966** | 5 ops → 2 units, 3 states |
| open the divider up | 1493 | 254 ops → 9 units, 60 states |
| two dividers, unopened | 1636 | 3 units, 2 states |
| three dividers, unopened | 2373 | 4 units, 2 states |

Opening one unit into N pieces spreads work over many states and buys operand
selection plus state/write control for the shared pieces. Distinct-operand
coalescing reduced the old opened result (1700 cells) to 1493, but it remains
54.6% larger than keeping the composite divider whole. The first calibration
error was `AREA_PER_BIT_MUX`: it priced a 2:1 multiplexer bit at about one yosys
cell, where measurement across four multiplexer shapes puts it at 2.07-2.14.
That constant is set from those measurements and remains the term that decides
ordinary sharing.

Recalibrating leaf constants does not close the hierarchy gap. With coalesced
muxes the raw per-leaf model rates the 254-op point at 384 versus a 950 anchor
(59.6% smaller), while whole-design yosys says it is 54.6% larger. Flattened
synthesis already shares/optimizes repeated arithmetic inside the atomic
divider; opening exposes that arithmetic to AUTO_FSM's per-leaf sharing but also
materializes a far larger FSM control/data-selection shape. A constant cannot
correct one side without corrupting the directly measured leaf prices. The
adaptive OPEN confidence guard therefore requires 70.3% at this 50.8x shape
growth (25% base plus 8 points per doubling), declines the move, and returns
the real 966-cell minimum. The asymmetry is intentional: declining a real win
costs an opportunity, while accepting a false one ships a regression.

#### Why a search that usually declines to move is still worth running

The codegen this search sits on top of — measured array multiplexers, real
register allocation (§3.2b, §3.2c) — is where the shipped area win actually
comes from (§4); the search itself declines on most designs, and that is the
right answer, not a sign it doesn't work. Share-everything binding is close
to optimal whenever every shared unit is an expensive multiply or a wide
add, because the multiplexer and control cost of opening one rarely beats
what sharing the whole unit already saves. The search's job is to prove
that cheaply and per-design instead of assuming it — and to actually move
for the designs where it's false: cheap operations sitting behind wide
multiplexers, or several composite units built from the same smaller shared
pieces. Without this search, that case would need to be assumed correct by
inspection instead of checked.

#### Why donut and sine decline every move

Neither shipped example takes a single move at any clock goal, and both declines
are correct rather than a search failure:

* `auto_fsm_donut_update` is int16 add/subtract/compare. Opening a 16-bit adder
  yields ~16 one-bit operations, each wanting its own operand multiplexers and
  cross-state registers, to save one adder. Its state count also has a floor no
  clock can lower: the most-shared unit carries 8 operations, and one unit runs
  at most one operation per state.
* `float_sine_auto_fsm` is float64. Floating-point operands have no soft
  equivalent and float built-ins have no Python source to descend into, so its
  expensive units are not openable candidates at all. Its state count *does*
  fall with a looser budget (14 → 10 at 1 MHz), but that is the greedy scheduler
  packing more per state, not the search choosing differently.

A design where opening pays needs a unit far more expensive than the
multiplexers and control sharing its pieces costs, with a modelled margin large
enough for the resulting shape change. A divider is the strongest in-repo
candidate — its soft equivalent is a chain of compare-and-subtract steps — and
`auto_fsm_div_share_test.py` deliberately confirms that even this particular
small divider is still cheaper left whole.

#### Which built-in operators can be opened at all

`_SOFT_FACTORY_FOR_OP` maps a built-in operator to the soft-operator equivalent
a chosen open uses, and the one a forced descent falls back to when there is no
width-halving equivalent (`_SPLIT_FACTORY_FOR_OP`, unsigned PLUS, MINUS and
INFERRED_MULT only). Signedness is part of that choice, and getting it wrong does not
produce a slower design, it produces a WRONG one — `_open_target`'s return-type
and arity checks cannot tell the difference, since the widths match and only the
answers differ.

| operator | unsigned | signed |
|---|---|---|
| PLUS / MINUS | ripple adder / subtract-via-add (forced: width-halving split) | ripple adder / subtract-via-add |
| MULT | shift-and-add (forced INFERRED_MULT: width-halving split) | **not openable** — no signed soft multiplier exists |
| DIV / MOD | radix restoring | signed radix (magnitudes, sign applied after) |
| comparisons, EQ / NEQ | subtract-based | same |
| shifts | **not openable** (see below) | |
| floating point | **not openable** — no soft equivalent | |

Both soft multipliers sum `a << i` over the set bits of `b` treating `b` as
unsigned; for a signed `b` the top bit carries weight `-2**(n-1)` and its partial
product would have to be subtracted. `make_soft_mult_shift_add(int16_t, int16_t)`
builds without complaint and computes `-3 * 4` as `1048564`, so a signed
multiply is refused rather than opened.

Shifts are absent even though `operators/soft_shift.py` ships barrel shifters:
the built-in takes its amount at the operand's own width while the barrel takes
exactly `log2(width)` amount bits, so the two disagree for any amount at or
above the operand width. Wiring them up needs an adapter that saturates the
amount first.

---

## 4. Results

Measured on this repo with the PYRTL/yosys flow (`src/tests/pypeline_tests/inst/`
and `examples/pypeline/`):

| design | operations | shared units | states | latency |
|---|---|---|---|---|
| `auto_fsm_resources_test.py` — 6 multiplies + 5 adds | 11 | **2** | 6 | 7 |
| `auto_fsm_donut_update.py` — donut per-frame rotation | 28 | **9** | 8 | 9 |
| `float_sine_auto_fsm.py` — float64 degree-5 Horner | 19 | **4** | 14 | 15 |

Area, same design built both ways (yosys cell count, whole-design top):

```
combinational (--comb, no sharing):    12117 cells
resource-shared FSM              :      3392 cells      3.57x smaller
```

Under `--syn_tool device_models`, the real-area search (§3.7, §3.8) currently reaches
24,095.7 µm² total (14,278.9 combinational + 9,816.8 sequential, 201 real FF
cells) on a divider design, at 70.40 MHz — **10.62× smaller** than the lowest
committed AUTO_PIPELINE/latchup.app reference for the same design (255,886.4
µm², asserted by `auto_fsm_real_area_compare_test.py`; the estimator is only
the ranking signal). The structural changes that contributed most:
deduplicating the output register bank (`make_stream_auto_fsm` owning the only
one, rather than a separate raw-AUTO_FSM bank copied into it), factoring
operand multiplexers through common zero-delay structure (§3.2b), and fusing
a consumed source with its produced output into one rolling register (§3.2c)
— the last of these alone removes 31 flip-flops by turning two W-bit banks
into one W+1-bit one. These transformations are recurrence- and
lifetime-based, not divider-specific: the unit-test fixture exercises the
same pattern with an XOR/subtract accumulator, and deliberately verifies that
an uncaptured combinational recurrence is rejected because it still needs
older source bits. See History for the control-path encoding decision this
design also settled (constant tables vs. comparators vs. one-hot).

Timing iteration, starting from a deliberately over-packed schedule
(`--auto_fsm_budget_scale 1.5`): first build 30.46 MHz vs a 40 MHz goal (FAIL) →
budget tightened → 44.23 MHz (PASS), with no source change.

Latency capping: `AUTO_FSM(add_chain, max_latency=4)` on five dependent adds that
would otherwise share one adder over 5 states (latency 6) builds 3 adders over 2
states (latency 3) instead. `max_latency=2` on the same design fails the build
with *"the shortest schedule … needs 2 states (latency 3) … raise max_latency to
at least 3"*.

### Poly1305 kernels on Artix-7

WireGuard's shared Poly1305 prologue and epilogue, ten lanes each, are built
as stream FSMs from `src/tests/pypeline_tests/qor/poly1305/` at 80 MHz on
`xc7a200tffg1156-2`. Timing is Vivado 2019.2 post-synthesis, without placement.
[`qor/poly1305_auto_fsm_vivado_200t.json`](../src/tests/pypeline_tests/qor/poly1305_auto_fsm_vivado_200t.json)
records every build, its measurement inputs and its reproduction command.

| kernel | `max_latency` | operations | units | states | register bits | MHz | LUT | FF | DSP | builds |
|---|---|---|---|---|---|---|---|---|---|---|
| epilogue | 32 | 374 | 98 | 32 | 16,241 | 86.08 | 10,210 | 19,155 | 48 | 1 |
| epilogue | 48, 64 | 374 | 70 | 45 | 10,782 | 86.30 | 7,283 | 15,300 | 24 | 1 |
| prologue | 48 | 368 | 80 | 48 | 9,313 | 86.78 | 9,323 | 12,912 | 84 | 2 |
| prologue | 64 | 368 | 39 | 62 | 6,395 | 85.74 | 5,460 | 10,241 | 37 | 1 |

The cap-32 epilogue row was built with the final compiler: its pinned Karatsuba
placement measured 11.00 ns on its own, within the 11.2 ns budget. The other
rows come from earlier snapshots of this work, before the search's merge moves
became next-wider steps; the QoR record names each row's compiler.

At caps 48 and 64 the epilogue's area optimum is the same 45-state schedule;
the two builds generate identical source. The cap-48 prologue missed by 0.66
ns on its first build, from the state register through a shared 130-bit adder;
attribution matched the path and one local repair (a second adder) met timing.

The prologue at cap 32 fits only with its whole modular multiply as a pinned
five-stage unit. Its first two builds missed (49.5 and 54.5 MHz): the
placements were predicted at 10.9 and 7.0 ns per stage and measured at 20.2 and
18.3 ns (§3.2, "Measured stages"). Chosen placements are now synthesized on
their own before a build relies on them; this cap was not rebuilt with that.

The prologue's limiting chain is its power tree: for ten lanes, four dependent
modular multiplications (r → r² → r³ → r⁵ → r¹⁰), each a 130-bit product
followed by `uint260_mod_prime`'s reduction. Their measured operation delays
sum to 351.8 ns over 72 operations, so with the multiply split into
combinational pieces the dependency floor is 40 states at 11.2 ns.

The baseline compiler, scheduling from the same measurements, also fits the
epilogue into 32 states, as 878 operations on 277 units, but misses timing at
53.58 MHz (26,671 LUT, 26,952 FF, 88 DSP); its next pass tightens to 7.5 ns
states and grows to 1,055 operations on 349 units. WireGuard's accepted cap-64
build with the baseline compiler needed three epilogue passes (1,214
operations on 117 units, then 1,671 on 188, then 21,332 on 9,478 with 54,346
register bits) to reach 81.04 MHz, and the whole run took 14 h 51 m. With empty
synthesis stores the baseline meets none of these caps: derived estimates split
the comparator into one-bit gates (33,427 epilogue operations) or report the
cap infeasible.

Full-capacity GHDL runs check the generated datapaths against independent
Python Poly1305 vectors, cycle by cycle against native simulation: the
epilogue at cap 32 (the hardware build's schedule; 646 cycles match) and the
prologue at cap 48 (its first-pass schedule, 912 cycles match; that self-check
top keeps only the first power as a hardware output, so it meets timing on its
first build).

---

## 5. Tests

| test | category | what it proves |
|---|---|---|
| `auto_fsm_attribution_test.py` | unit | ordered Vivado carry/routing arcs, endpoint-only paths, retained unmatched evidence, parallel late select arrival, edge separation, width-keyed decode proxies, measured pinned-unit stages (isolated and launch) and rescheduling placements measured over budget before a build |
| `auto_fsm_cache_test.py` | unit | stale source/target/version refusal (recorded, and an internal error inside a build), malformed cache misses, applied forced schedules, provenance completeness, serial unit characterization and stable hardware identities; `REPARSE` schedules a call site new to the build and still refuses a rejected schedule; a call site created during a pass is scheduled from `--auto_fsm_budget_scale`, blamed and tightened (stubbed driver) |
| `auto_fsm_transforms_test.py` | unit | exclusive selection proofs, typed width-adapter legality and next-wider merge steps, closed-pair fusion refusal and trimmed measurement roots |
| `auto_fsm_prefix_tree_test.py` | unit | a derived hierarchy estimate is measured (outermost first, never when a measured part already exceeds the budget) before it decides forced descent, and the carried measurement is reused on a later pass; array input elements render as indexes; a MAIN with no registers of its own drives its scheduled FSM's clock enable; a helper kept whole as a pipelined unit is not a blocked descent |
| `auto_fsm_var_index_read_test.py` | elab_introspect | direct and nested variable-index source regeneration (regression for #377) |
| `self_check_auto_fsm_constants_test.py` | native_vs_vhdl_sim | typed folding, constant arithmetic, signed extension and overflow in generated hardware |
| `self_check_auto_fsm_pipelined_unit_test.py` | native_vs_vhdl_sim | pinned pipelines, launch/completion timing, ignored busy requests and stalled outputs |
| `self_check_auto_fsm_select_share_test.py` | native_vs_vhdl_sim | indexed scalar/struct/array reads, defaults, width sharing and generated fused arithmetic |
| `self_check_auto_fsm_poly1305_test.py` | native_vs_vhdl_sim | unchanged Poly1305 prologue/epilogue arithmetic, transaction stalls and host expected values |
| `auto_fsm_test.py` | native_sim, (synth via wrapper) | the pure function's semantics, and the passthrough behaviour when unscheduled |
| `auto_fsm_unit_test.py` | unit | scheduler/codegen internals: binding, one-op-per-unit-per-state, dependency order, distinct-operand mux coalescing and common-glue factoring, same- and cross-FU register reuse, recovered rolling output and consume/produce storage, field-lifetime input compaction, optional output bank, automatic control encoding, budget → states, floors, determinism, schedule is carryable data, a scheduled re-parse prepares the soft equivalents its schedule binds, the `descent blocked:` report, tighten-loop termination (`SCHEDULES_EQUAL` ignores budget bookkeeping, the `TIGHTENING_STALLED` truth table), the tightening step (`TIGHTENED_BUDGET_SCALE` follows the measured miss and always passes the worst state; `_BLAMED_MISS_RATIOS`), forced descent splitting wide adds and inferred multiplies into narrower inferred ones while a chosen open stays bit-level, the area search reaching a jointly feasible binding from an over-budget anchor and skipping candidates when the anchor is past the DAG cap, unmeasured delays resolved rather than zeroed, the zero-op guard (and measured-0 operations still legal), soft-operator equivalents, soft adder sign extension, `_TypeResolver` array reconstruction, real-sky130-area tiering (cold cache falls back to scaled abstract not zero, a cache hit wins over any abstract guess, `--auto_fsm_abstract_area`, real flip-flop area) |
| `area_model_test.py` (`src/tests/pypeline_tests/inst/`) | unit | not AUTO_FSM-specific (SYN/DEVICE_MODELS leaf-area-cache coverage), but two tests here directly guard AUTO_FSM.py's own constant: the committed `cache/area` excludes STA-harness registers, and `AUTO.UM2_PER_ABSTRACT_AREA_UNIT` refits to what is actually committed |
| `self_check_auto_fsm_test.py` | native_sim, vhdl_sim, synth ×2 | the FSM computes what the function did — in native sim, in GHDL, at latency 0 and at real latency |
| `stream_auto_fsm_test.py` | native_sim | `make_stream_auto_fsm`'s handshake protocol: ready deasserts while busy, latency/II == `fsm.latency + 1`, and — the property raw AUTO_FSM cannot provide — a stalled consumer never loses a result and sees stable data while it's held |
| `self_check_auto_fsm_split_test.py` | native_vs_vhdl_sim | forced descent's width-halving equivalents in real hardware: a 32-bit add and subtract and a 16x16 inferred multiply, forced open by a small `--auto_fsm_budget_scale`, compute the same values in native sim and GHDL |
| `self_check_auto_fsm_array_mux_test.py` | native_vs_vhdl_sim ×2 | array-valued operand muxes: direct 5- and 7-way `uint2_t[4]` muxes (plus scalar and struct ones) over every selector and lane, and a scheduled FSM whose one shared unit takes and returns `uint2_t[4]` (7- and 5-way array ports, array registers), in native sim and GHDL |
| `self_check_stream_auto_fsm_test.py` | native_sim, vhdl_sim, synth ×2 | same shape as `self_check_auto_fsm_test.py`, one layer up: the wrapper's handshake + the real scheduled FSM underneath it compute and sequence what the function did, with real backpressure toggled from the testbench, in native sim, in GHDL, at latency 1 and at real latency |
| `qor/multiplier/auto_fsm.py`, `qor/divider/auto_fsm.py`, `qor/sqrt/auto_fsm.py` | synth | AUTO_PIPELINE→`make_stream_auto_fsm` conversions of the QoR designs, real `PART("sky130")`/pyrtl builds with `ready` genuinely wired (never a constant 1); the multiplier is what exposed and pins the `_TypeResolver` array-reconstruction fix below |
| `auto_fsm_latency_test.py` | synth | end-to-end schedule; the generated VHDL instantiates exactly as many copies of each shared unit as the schedule claims |
| `auto_fsm_resources_compare_test.py` | synth | the FSM is actually smaller than the logic it replaces |
| `auto_fsm_area_sweep_compare_test.py` | synth | the area search does not make designs bigger, and its cost model agrees with yosys about which of two schedules is smaller — the calibration guard |
| `auto_fsm_min_area_verify_test.py` | synth | the search actually MOVES on a design built to reward moving, the move is smaller in real yosys cells, and no alternative point of the search space (built via `--auto_fsm_open` / `--auto_fsm_unshare`) is smaller still |
| `auto_fsm_real_area_compare_test.py` | build_report | same question under `--syn_tool device_models`, judged by real `Measured area:` rather than yosys cells: real-µm²-ranked vs `--auto_fsm_abstract_area` vs `--auto_fsm_no_area_sweep`, all three built; pins the 25k µm² v7 structural ceiling and beats the lowest committed AUTO_PIPELINE/latchup.app divider area; plus AUTO_FSM's own allocated-storage bit count against the build's real sequential cell count (the register-fidelity question §3.8 raises explicitly) |
| `auto_fsm_max_latency_test.py` | synth | a meetable `max_latency` is met by unsharing; an unmeetable one fails the build naming the latency actually needed |
| `auto_fsm_timing_iter_test.py` | build_report (sky130) | a critical path inside an FSM is found and fixed by rescheduling (`auto_fsm_timing_iter_design.py`: narrow inputs, so the states, not the input-capture fanout, set the critical path); checks each pass's full-design timing and authenticated mapped end-register attribution |
| `auto_fsm_latency_sized_test.py` | build_report (sky130) | an AUTO_FSM sized from an AUTO_PIPELINE depth (`auto_fsm_latency_sized_design.py`: lanes = divider depth + 2): the call site pin-and-confirm pass 2 creates is scheduled before its single seeded confirmation synthesis, and the build exits 0 |
| `auto_fsm_tighten_stall_test.py` | build_report (sky130) | the other half: when rescheduling cannot move the critical path (sky130, 110 MHz, a path the state count cannot change), the driver stops after the first tightened build with no fmax gain in its full-design timing records, prints why, never produces a 0-op schedule, and exits nonzero within a timeout |
| `auto_fsm_ctl_compare_test.py` | synth | the constant-table control path is not bigger than the comparator chains it replaced, and the donut FSM still meets the clock goal that v2 misses |
| `double_parse_file_test.py` | elab | re-parsing an AUTO_FSM design is reproducible |

`self_check_auto_fsm_test.py` is worth copying as a template: it reacts to
`resp.valid` rather than counting cycles, so one source file is correct at every
latency, which is what lets it be reused unchanged across four registrations.
`self_check_stream_auto_fsm_test.py` follows the same template one layer up —
it reacts to `stream_out_if.stream.valid & ready_now` (the real "consumed this
cycle" condition) instead, so it is equally correct at latency 1 (`--comb`)
and at `fsm.latency + 1` (scheduled).

---

## 6. Limitations and future work

Priorities are discussed in [#347](https://github.com/JulianKemmerer/PipelineC/discussions/347).

**Current limitations**

- One argument (bundle into a struct); one computation in flight; the raw
  call site has no backpressure — `valid` while busy is ignored. Wrap with
  `make_stream_auto_fsm` (§2.1) for a real valid/ready port instead.
- The function must be pure: no `Reg`, `Feedback` or global wires anywhere in
  its subtree. Variable-index scalar and compound array reads retain their original types.
- An operation bigger than a state that cannot be decomposed *and* has no
  soft-operator equivalent sets a floor. That is honest — a float64 multiplier
  is not divisible by scheduling — but it means the clock goal must be reachable
  by the slowest single operation.
- Pinned unit stages are predicted from AUTO_PIPELINE's landscape, whose cut
  positions a nested parallel hierarchy may not realize. A pipelined Poly1305
  modular multiply was predicted at 10.9 ns per stage and measured 20.2 ns
  (§3.2, "Measured stages"). A recipe whose chosen depth is mispredicted costs
  one synthesis per remaining depth, and one reschedule, before a build uses it.
  When every depth keeps the same worst path, the report says so: no depth of
  that recipe can fix it, and the search moves to another recipe.
- Control overhead grows with the number of folded operations, because the
  operand multiplexers do. At tens of operations this is a clear win; at
  thousands the multiplexers would dominate (see "loop-preserving FSMs" below).
- The area model is still a model for every tool except sky130, and even under
  sky130 it is a per-leaf sum, not a whole-design synthesis: it ranks
  candidates in abstract units calibrated against yosys cell counts (§3.7),
  which is not the same thing as LUTs on the part you are targeting — on an
  FPGA, flip-flops come paired with the LUTs in front of them and are far
  cheaper than a cell count suggests. Under `--syn_tool device_models` (§3.8) the
  unit, register and multiplexer terms use real cached µm² instead, which
  fixes the FPGA-calibrated flip-flop term's biggest error (2.5x too cheap)
  but does not fix two gaps a per-leaf sum cannot see by construction: (1)
  **cross-instance combinational sharing** on wide operand-multiplexer
  trees — confirmed still present as a 256% whole-design overshoot on
  `qor/divider/auto_fsm.py`. `qor/multiplier/auto_fsm.py` used to be the
  contrasting low-overshoot case (4.65%, per
  `qor/latchup_area_match_matrix.json`'s `in_repo_evidence`) precisely
  *because* it shared its multiplier to one atomic unit with no wide muxes at
  all — that stopped being true once its operands were narrowed to `uint8`
  to fix a search-time hang (see that file's own comment and §6's AUTO_FSM
  search-cost entry below): AUTO_FSM now opens the multiplier up into a real
  36-fold-shared `chunk_add_w_2` unit with a genuine operand mux, and a local
  build now measures 242.45% overshoot (83385.5 estimated vs 24349.7 um2
  measured) — close to the divider's number, for the same reason. This is
  not a matrix re-run (no latchup.app PnR comparison behind it, just this
  repo's own `Measured area:` build-log line) but it is consistent with the
  gap being design-shape-dependent, not a constant to calibrate away; and (2)
  **`SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS`'s own FF-count overshoot**
  (5.7-5.9x; per-FF area is exact, so the error is entirely in the *count*,
  before any yosys-level FF optimization) — a different and much cruder count
  than AUTO_FSM's own `ALLOCATE_REGISTERS` (§3.2c), which tracks genuinely
  live cross-state values rather than every declared bit, checked directly
  (not assumed) in `inst/auto_fsm_real_area_compare_test.py`. Neither gap is
  specific to the search's ranking: both are as true of
  `SYN.ESTIMATE_DESIGN_AREA`'s whole-design build-log estimate as of the
  terms feeding `ESTIMATE_SCHEDULE_AREA`. The anchor bounds model-space
  regressions; the real whole-design A/B tests guard the physical result.
- **The search's own cost is superlinear in folds-per-shared-unit, and has no
  wall-clock bound by design** (§3.7 — a schedule must stay a pure function of
  the source, so the only caps are size-based: `MAX_SWEEP_DAG_NODES`,
  `MAX_SWEEP_MOVES`, `_MAX_DESCEND_DEPTH`). `SCHEDULE_DAG`'s placement search,
  `ALLOCATE_REGISTERS`, and the operand-mux plan all scale with the busiest
  unit's fold count, so a schedule where one entity folds a few hundred
  operations onto one unit can run for a very long time on a SINGLE
  `BUILD_SCHEDULE` call — before the min-area search even starts multiplying
  that cost by candidates. This is exactly what happened when
  `register_soft_mult()`'s default switched to a 30-level carry-save
  multiplier: `qor/multiplier/auto_fsm.py` (then `uint16 x uint16`) folded 247
  adds onto one unit — past `_MAX_DESCEND_DEPTH`, which stopped it from
  descending the other 24 levels — and did not finish scheduling in any
  reasonable time, with nothing printed after the pass banner (no synthesis
  was involved; `ADD_PATH_DELAY_TO_LOOKUP` had already finished). Fixed by
  narrowing the test to `uint8`, which fits under the cap with the shipping
  default (see that file's own comment). Two things now make the NEXT such
  case visible instead of silent: `BUILD_SCHEDULE` prints a one-time
  `AUTO_FSM <key>: '<entity>' folds N operations onto one shared unit (>
  SWEEP_LARGE_SCHEDULE_FOLDS) ...` notice *before* calling `SCHEDULE_DAG`, so
  it fires even under `--auto_fsm_no_area_sweep`'s single anchor build; and
  `DESCRIBE_SCHEDULE` reports when `_MAX_DESCEND_DEPTH` (not a genuine floor)
  is why an entity stayed atomic (§3.1). The notice names only knobs that
  actually shrink the FIRST schedule built — `max_latency=`, a lower clock
  goal, a shallower/narrower operator source — deliberately NOT
  `--auto_fsm_unshare`/`--auto_fsm_open`: confirmed by testing that both route
  through `FORCE_SCHEDULE`, which resolves its pattern against an
  already-scheduled anchor (`_resolve_entity_pattern` reads `schedule["fus"]`)
  and so unconditionally pays for one full, uncapped `BUILD_SCHEDULE` before
  applying anything forced — no help at all when that anchor alone is what
  does not finish. This is itself an open gap: entity names are already known
  from the cheap, unscheduled DAG (`BUILD_DAG` + `_resolve_inlined`, no
  `SCHEDULE_DAG` involved), so `FORCE_SCHEDULE` resolving patterns against
  that instead of a fully scheduled anchor would make both force flags a
  genuine escape hatch even when the anchor itself is the bottleneck — not
  done here, since it touches a function two other tests
  (`auto_fsm_min_area_verify_test.py`, `auto_fsm_div_share_test.py`) depend on.
  Both the notice and the descend-cap report are advisory —
  neither raises, and there is still no hard cap — because a legitimate
  large design should still build, just no longer in silence.
- **A capped search reschedules thousands of candidates, and every timing
  miss pays it again.** On the Poly1305 epilogue fixture
  (`qor/poly1305/auto_fsm.py`, `CAPACITY=5`, `max_latency=64`, 80 MHz,
  harvested Vivado xc7a200tffg1156-2 delays, no synthesis during the search),
  one `auto` harvest builds 2,179 schedules per encoding and took 92 minutes
  of wall time serially on a loaded four-core machine. PIPELINE moves, with
  their depth characterization, were 44% of a profiled v3 search. (Before
  PIPELINE, MERGE and FUSE moves, WireGuard's epilogue at 11.2 ns per state
  built 626 per encoding.) The encodings' measured
  select delays differ there (1.4 ns for v3, 2.4 ns for onehot), so the onehot
  search reuses no v3 schedule, only cleaned graphs. On the first three steps
  of the v3 search on that fixture, the plan memo and the inner-loop changes
  took the search from 1,839 s to 1,257 s serially, and forked builds to
  617 s at `-j 3`, with byte-identical schedules and trace. In a serial
  search, the largest parts are each candidate's `SCHEDULE_DAG` runs,
  including the cap's bisection, and graph cleanup. A later build with the
  same inputs reuses the result instead
  ([search results persist across builds](#search-results-persist-across-builds)),
  but a changed input, such as a tightened budget, searches again. Two cuts
  were measured and rejected.
  - Skipping OPEN moves when the anchor is at the cap would have lost the
    epilogue's result (64 → 56 states, −31% estimated area from two OPENs).
  - A schedule-free lower bound (units plus glue) is about half an estimate
    and pruned none of the prologue's first-move candidates.

**Future work**

- **Register capacity sharing.** Functional units can serve compatible unsigned narrow operations through width adapters (§3.7). Ordinary value registers still require the same type; sharing one wider register among different narrow lifetimes remains future work.
- **Larger recurrent groups.** Recurring closed multiply→add/subtract and arithmetic→MUX pairs are candidates for whole-unit binding (§3.7). Longer groups and groups with externally used intermediates remain separate operations.
- **Per-node grain**, rather than per-entity. Opening an operation today opens
  every use of it, because every use must stay bound to one unit for sharing to
  mean anything.
- **Soft-operator flavor search.** One fixed flavor per operator today (ripple
  adder, shift-add multiplier, subtract comparator); the library ships several,
  and which one decomposes best is a second search axis.
- **Globally optimal register/mux binding.** Cross-unit sharing now makes each
  local merge only when FF area beats the incremental writeback mux and its
  delay fits the state budget. The allocator is still a deterministic greedy
  left-edge pass, not a global weighted matching across all free intervals;
  such a solver could sometimes choose a different set of merges with fewer
  total mux inputs.
- **A ROM/SRAM primitive.** Constant tables are built today as a constant local array
  read at a variable index, which elaborates to a full selection tree and only
  becomes cheap once synthesis folds the constants. It works (the whole v3
  control path depends on it) but the internal delay model prices the unfolded
  tree — a 5-entry table estimates at 4.8 ns where the module it sits in
  measures 1.9 ns. Harmless inside an AUTO_FSM, whose delay is one measured
  whole-module number, but a real ROM/table primitive with its own cost model
  would make the idiom usable in ordinary designs. (A design can instantiate an
  explicit ROM today with the library's `make_ram`; this item is about the
  compiler's own treatment of constant arrays.) Likewise, a sufficiently
  large register file or lookup table could eventually map to SRAM, but no
  latchup-compatible inferred SRAM primitive exists in this flow yet; treating
  an ordinary array as one today only produces combinational logic.
- **A latent bit-slice bug in deeply-opened schedules** ([#366](https://github.com/JulianKemmerer/PipelineC/issues/366)). Rescheduling the donut
  design under a tightened budget produces a 412-operation, 131-state plan whose
  generated source fails to elaborate: *"Bit index [14:14] out of range for
  uint9_t"*. This is unrelated to which control-path encoding is chosen — the
  constant-table default (§3.3, "The control path") only avoids triggering it
  by meeting timing, and therefore never opening the schedule this far, on
  the first pass — but it is reachable from any design the search opens far
  enough.
- **Multiple concurrent AUTO_FSM threads sharing units.** Two FSMs that both need
  a float multiplier could share one, with arbitration. The binding step already
  keys on entity, so the scheduler generalizes; what is missing is the arbiter
  and a cross-FSM resource model.
- **Loop-preserving FSMs.** AUTO_FSM schedules the *unrolled* graph, so control
  grows with the folded-operation count. The fix is real loop back-edges:
  schedule the body once, add an index register, and index operands from arrays.
  A user-facing sequential/`__clk()`-style layer for Pypeline would be the
  natural emission target for that — but note the dependency direction: such a
  layer does **not** help AUTO_FSM as it stands, because per-state code regions
  would create one instance per call site and defeat the single-call-site
  sharing trick. AUTO_FSM's emission helpers are reusable substrate for building
  it later, not the other way round.

## History

Why things are the way they are. Entries are keyed by **topic, not date** —
when something changes, revise the entry that owns that topic rather than
adding a new one. Keep a fact here only if it still changes a decision
today: an alternative someone would otherwise retry, a measurement that is
still a live regression reference, or the reason a default is what it is.

### Constant-aware cleanup and compact operand plans

Typed cleanup runs on the FSM DAG even when scoped implementations prevent
whole-function combinational rewriting. Constant wrappers preserve original
operator dispatch and are measured independently. Shared operand-factor nodes
remain shared in both planning and source emission; reconvergent graphs no
longer expand into an exponential expression tree.
Binding candidates also reuse the same cleaned graph within one area search;
repeating typed cleanup for each unit-count choice otherwise dominates large
kernel probes. Cached candidates retain independent mutable graph data.

### Pipelined units and pinned regions

AUTO_FSM compares complete schedules using combinational, decomposed and
pipelined units. Placement uses AUTO_PIPELINE's measured-primitive landscape;
its concrete digest belongs to the hardware identity. Launch and completion are
separate scheduling events, and surrounding sweeps cannot move an FSM-owned
recipe. Measured corrections try feasible word-level pipelines before forced
fine-grained descent, including with area search disabled.
Sparse placement recipes omit unsliced descendants while restoring and fixing
their zero placements. Register-estimator results for unchanged child placements
are reused across characterization depths.
PIPELINE moves are local steps and depths are characterized lazily. The first
form proposed every feasible depth of every candidate unit at every search step:
on the Poly1305 prologue at cap 64 (harvested Artix-7 delays, 11.2 ns states)
that was about 445 of the roughly 670 candidates per step, 3,343 candidates and
2,863 CPU seconds in all, with the initial characterization of every depth alone
taking about 600 CPU seconds. Width-adapter moves became local steps for the
same reason: proposing every compatible narrow-to-wide pair gave the integer
square root (`qor/sqrt`, sixteen subtract widths) about 110 merges per step,
1,068 of its first 1,428 candidates. Its build took over 25 minutes against
155 seconds before, and `qor_sqrt_auto_fsm_test` timed out.

### Hardware-only entity names

Budgets and model diagnostics formerly renamed byte-identical hardware. Entity
hashes now exclude those fields while retaining operations, types, bindings,
states and placements. Stale source, target or recipe data remains a cache miss.
The `forced` report flag of `--auto_fsm_open`/`--auto_fsm_unshare` schedules,
set after naming, was first left in the hash: re-elaboration refused every
forced schedule as stale, which `auto_fsm_min_area_verify_test` exposed once
refused schedules stopped the build (above).

### Schedules a build produced are applied or the build stops

`BUILD_AUTO_FSM_FUNC` treats an unusable installed schedule as a cache miss and
elaborates the combinational passthrough. Inside a build every installed
schedule comes from the build's own passes, so the driver (and AUTO_PIPELINE's
re-parses) now raise `AutoFsmInternalError` with the refusal reason
(`CHECK_SCHEDULES_APPLIED`). The first Poly1305 epilogue build at cap 64 showed
why: a pinned pipelined unit was re-characterized during elaboration, before
logic trimming, so its context digest never matched the one taken after
parsing. The refusal was silent, the passthrough was synthesized (11.4 MHz,
87.7 ns through the whole kernel), and the build carried on. Pinned recipes are
now verified where they are applied, by region enforcement's digest and latency
checks, not re-characterized at elaboration.

A call site with no installed schedule was first treated the same way, which
is wrong for a call site new to the build. WireGuard's cold 40 MHz shared build
scheduled the capacity-2 Poly1305 kernels, the sweep settled the body at 1
clock, and pin-and-confirm pass 2 re-elaborated capacity-3 functions: an
`AutoFsmInternalError` after 1:46:44 and three whole-design syntheses.
`REPARSE` now schedules such call sites before the check (§3.4). Three more
changes keep the new FSMs first-class:
- The driver re-reads its schedules after the sweep. `_BLAMED_MISS_RATIOS`
  ignores keys the driver does not hold, so a new FSM that missed timing would
  have ended the loop with "no AUTO_FSM region is implicated".
- `--auto_fsm_budget_scale` applies to every call site, not only to those of the
  bootstrap parse.
- Pinned units of a newly scheduled FSM are neither harvested as `.latency`
  values nor required to have a previous-pass counterpart in pin-and-confirm
  seeding
  ([`AUTO_PIPELINE_DESIGN.md`](AUTO_PIPELINE_DESIGN.md#5-latency-pin-and-confirm-loop-pypeline-designs-only)).
  Otherwise the new FSM's units would read as changed latencies (another pass)
  or as a changed set of call sites (an exit).

### Measurements before scheduling decisions

On Artix-7 the Poly1305 comparator's nine-leaf prefix helper derives 10.8 to
12.8 ns from standalone leaves (with that build's cached leaf delays) against a
2.3 ns synthesis measurement. On a fresh output directory forced descent split
it and everything above it into one-bit gates: the epilogue grew to 33,427
operations and 62 states, and its cap-64 build ran 12 hours without finishing.
WireGuard's accepted cap-64 run avoided this only because its output directory
held logs for those helpers from earlier builds. Warm synthesis stores could
not reproduce that: the fixture's identities differ from WireGuard's.
Measuring each estimated helper that a descent decision rests on fixes the cause.
The same isolated-root measurement made the decode proxies real: before it,
`ADD_PATH_DELAY_TO_LOOKUP(root_func_names=...)` silently skipped them because
nothing instantiated them, and every first pass charged a zero select delay.
Constant wrappers likewise went unmeasured until a scheduled FSM instantiated
them. Once measured they were synthesized twice: the root was written
untrimmed, and the scheduled FSM's trimmed instance had different text under
the same entity name (13 extra runs on the epilogue's first cap-64 build).

### Measured unit stages

The Poly1305 prologue at cap 32 kept its whole modular multiply as a pinned
five-stage unit, predicted at 10.9 ns per stage. Vivado measured 20.2 ns from
the state register, through the unit's operand selection and two cascaded
DSP48E1 with 39 CARRY4, to the first stage register: the realized registers
left the Karatsuba middle product uncut until its subtract. The recorder of
measured stages matched endpoints with the schedule's entity name, which the
netlist never contains (it names the elaborated instance), and it required
both ends inside the unit. No stage was recorded, the search judged depths by
prediction only, and the next pass rebuilt the same placement. Measurements
now follow the elaborated instance, include a unit's launch path, and replace
the prediction wherever a depth is judged. The cause of the misprediction is
the landscape's scaling: inside a hierarchy measured as a whole (the 130-bit
Karatsuba at 25.9 ns), children are placed by their standalone delays (38.8 ns
along its longest chain) scaled to the whole, so a 16.7 ns half-multiply sits
at 11.1 ns, while the register realized at its output still follows all of
it. AUTO_PIPELINE's own sweep corrects such predictions by measuring; pinned
regions skip that. WireGuard's shared build at cap 64 then missed timing the
same way (52.57 MHz, a four-stage modular multiply), and each in-context
correction cost a whole-design pass. Chosen placements are therefore measured
on their own before the first build that uses them.

### Control timing and local repair

The data and select paths are parallel, so the scheduler charges
`max(data, select) + mux`. A small width-keyed proxy supplies the first estimate;
state-register paths supply in-context corrections. Selectors remain inline:
per-table characterization would add runs without capturing real fanout.
Attributed misses compare local complete reschedules before global tightening.
Repair applies only where the model predicted a fit. In the first form a
stalled repair stopped the loop: on sky130, `auto_fsm_timing_iter_test`'s
deliberately loose 2.5 budget pipelined one adder per pass (76, 94.9, then
72.9 MHz) and stopped without ever tightening. A stalled repair now falls back
to tightening, and the stall stop applies to tightening steps.

### Tighten loop termination

Found under `--syn_tool device_models` with `auto_fsm_tighten_test.py` at 110 and
150 MHz (`--auto_fsm_budget_scale 1.5`). There, the tighten loop ran for
20–30+ minutes without ending. Three independent defects combined:

- **Tightening that could not help.**
  - The design measured 102.25 MHz at 2, 3 and 6 states.
  - Its critical path is state flop → one `nand2` driving 143 loads
    (7.99 ns, a max-capacitance violation) → `mux2` → register. That nand2 is
    the FSM's input-capture enable, which feeds all 142 input-register bits.
    It is in the FSM, but not in any state, so no schedule moves it.
  - Blame falls back to every FSM under the MAIN, so the loop kept shrinking
    the budget until adds decomposed into hundreds of 1-bit ANDs.
  - Fix: stop when a tightened build gains no fmax (`TIGHTEN_MIN_FMAX_GAIN`).
  - Splitting under a tightened budget was deliberately kept. The stall stop
    ends this case before the budget reaches it.
- **A "0 ops -> 0 shared unit(s), 1 states" schedule, and the hang.**
  - `BUILD_SCHEDULE` defaulted unmeasured delays to 0. `_resolve_delay_du`
    trusts a known 0, so its fallbacks never ran.
  - This hit a combinational candidate's soft-operator gates (1269 nodes),
    which are never instantiated and so never measured. The candidate became
    all glue, scored as a free 1-state FSM, and won the area search.
  - It only competed once the anchor had itself decomposed: the candidate size
    filter scales with the anchor's node count.
  - Codegen then rendered that glue inline recursively. A gate-level carry
    chain, where each carry feeds two consumers, becomes one exponentially
    large expression.
  - Fix: `_schedule_delays` resolves unmeasured delays, and the same candidate
    now prices at 888 ops / 390 states. `_check_nonempty_schedule` is the
    tripwire. Codegen's inline glue rendering is still unmemoized, and is safe
    only because genuine glue is plain wiring.
- **`SCHEDULES_EQUAL` compared `budget_scale`.** Every tightened trial
  therefore looked changed, so "shrinking no longer changes the schedule" was
  dead code. It now compares hardware only.

### Forced descent into one-bit gates

Found in the WireGuard shared Poly1305 build (80 MHz, `hybrid_square`). The
first confirmation measured the epilogue FSM at 72.65 MHz. The driver tightened
its budget by the fixed 0.75 step, from 11.2 to 8.4 ns, and the next schedule
printed `'BIN_OP_AND_uint1_t_uint1_t' folds 31494 operations onto one shared
unit` before running out of memory. Three defects combined:

- **Forced descent went straight to gates.** At 8.4 ns the 260-bit adds and
  subtracts and the 32–34-bit inferred multiplies no longer fit a state, and
  the only equivalents they could open into were the bit-level ripple adder
  and shift-and-add multiplier.
  - The 31,494-fold AND was the share-everything anchor. It was built and
    scheduled before any area scoring, so it was never chosen as an area win.
  - The model priced it correctly as terrible. On one modular multiply at
    8.4 ns, the anchor was estimated at 397,856 against 8,320 at 11.2 ns.
  - Its muxes were not a literal 3,135:1 per port. In that modular multiply,
    operand factoring turned each port of the shared AND into one 1-bit mux
    of 351–523 inputs, behind 260 4- to 7-way muxes over 260-bit registers.
    Those wide register muxes are most of the estimate.
  - Fix: forced descent prefers the width-halving equivalents (§3.7), which
    keep every operation a word-level inferred one.
- **The search could not run on that anchor at all.** The anchor had no DAG
  cap, and each candidate rebuilt the same oversized DAG only to be refused by
  `MAX_SWEEP_DAG_NODES`. Fix: an anchor already past the cap is returned
  without building candidates (§3.7).
- **The fixed tightening step overshot.** It took the budget past whole operator
  widths at once. Fix: the step follows the measured miss (§3.4).

The WireGuard probes that confirmed these also showed an over-budget anchor
that one-at-a-time UNSHARE could not repair. Each of two shared units needed a
second copy, and either copy alone was rejected for still missing the budget.
The search now ranks candidates by how far past the budget they run before
their area (§3.7).

### Operand multiplexer costing

Sharing's entire cost side — the multiplexer selecting a shared unit's
operands per state (§3.2b) — used to be priced as a flat `MUX_PENALTY_DU = 10`
(1.0 ns) constant per scheduled operation. That was wrong in both directions
at once: over-charging a unit with two users, badly under-charging one with
twenty — exactly the range the area search explores. Measured directly, a
6-way `int16_t` mux costs 4.29 ns, a 4× error against the flat estimate, in
the one term that decides how much sharing is worth doing. Replaced with a
real, measured entity (`auto_fsm_operand_mux`, §3.2b), which also made
distinct-value coalescing and common-glue factoring possible — optimizations
a flat-cost model gave no reason to build, since it couldn't see the savings.

### Control-path encoding: constant tables, comparators, and one-hot

`--auto_fsm_ctl v2` (comparator chains) costs one equality comparator per fold
per unit plus one per state, each followed by a priority chain — O(states x
units) comparators in the path from the state register to every operand
multiplexer. `--auto_fsm_ctl v3` (constant lookup tables, what `auto`
normally selects) replaces nearly all of them with a table read, leaving
exactly one comparator per FSM. The area saving alone is real but modest
(roughly 0.5-2.4% smaller across three measured designs). The timing result
is the one that matters: on a donut-rotation design close to its clock goal,
the comparator-chain path misses by 0.07 MHz, which forces the driver to
tighten the budget and reschedule — the resulting deeply-opened schedule (412
operations over 131 states) hits the latent bit-slice bug tracked in
Limitations, and the build fails outright. The constant-table path meets the
same goal on the first pass without ever opening the schedule that far, and
is also the first schedule where that FSM is smaller than the combinational
logic it replaces.

`onehot` was expected to lose (one flip-flop per state instead of
`log2(states)`) and did not: its extra flip-flops are cheaper than expected
and its decode is cheaper still, since a write enable becomes an OR of
already-decoded hot bits rather than a fresh boolean function of the state
bits. It won on all three designs measured, on both area and fmax. Its
flip-flop cost grows linearly in state count where binary encoding grows
logarithmically, and nothing in the three measured designs (6, 8, 14 states)
says where the crossover is — which is why `auto` prices both encodings for
the actual schedule rather than trusting either result as universal.

Separately: pricing the constant-table path's own lower control cost in the
area model changed zero scheduling decisions on the three measured designs.
The saving is real but small next to the unit and multiplexer terms that
actually drive the search's choices — the model terms are correct and in
place, the lever simply has less leverage than expected.
