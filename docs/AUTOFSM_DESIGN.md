# AUTOFSM: pure functions as resource-shared state machines

`AUTOFSM(func)` implements a pure combinational function as a finite state
machine that holds **one copy of each distinct operation** and runs the function
over several clock cycles. It is the resource-minimizing dual of
[`AUTOPIPELINE`](SYN_DESIGN.md): where AUTOPIPELINE cuts one full copy of the
hardware with N serial register slices (N clocks of latency and N+1
combinational pipeline regions, initiation interval 1, maximum throughput,
maximum area), AUTOFSM keeps one adder and uses it twelve times (initiation
interval N, minimum area).

Both are tool-driven: you write the function, state a clock goal, and the build
figures out the rest — how many stages, or how many states.

- Implementation: [`src/AUTOFSM.py`](../src/AUTOFSM.py) (including the driver loop,
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

**Why loops and straight-line code are the same problem.** By the time AUTOFSM
runs, Python `for` loops have been unrolled and `if`s have become multiplexers.
What is left is a pure dataflow graph. So "the user wrote a loop" and "the user
wrote twelve similar lines" produce identical graphs, and AUTOFSM folds both.

**Other vocabulary used below**

| term | meaning |
|---|---|
| entity / `Logic` | one function definition; `parser_state.FuncLogicLookupTable` maps entity name → `Logic`. Every *call site* is a separate hardware instance (`Logic.submodule_instances`) — the compiler shares nothing by default. |
| delay unit (du) | tenths of a nanosecond. `Logic.delay` is an int in these units (`SYN.DELAY_UNIT_MULT == 10.0`), so a 4.2 ns adder has delay 42. |
| node | one operation in the DAG, identified by its local instance name (operation name + source coordinates). |
| glue | a zero-delay operation: struct field reads, constant shifts, rewiring. Free, so never scheduled and never shared — just re-rendered wherever its value is used. |
| functional unit (FU) | one shared hardware instance, identified by entity. |

Background reading, in order: [`docs/SYN_DESIGN.md`](SYN_DESIGN.md) for the
delay model and the sweep, [`docs/PY_TO_LOGIC_DESIGN.md`](PY_TO_LOGIC_DESIGN.md)
for how Python becomes a `Logic` graph, and
[`docs/pypeline_guide.md`'s Tool-Chosen Implementation section](pypeline_guide.md#tool-chosen-implementation-autopipeline-and-autofsm) for
AUTOPIPELINE, whose machinery AUTOFSM mirrors.

---

## 2. User API

```python
from pypeline import AUTOFSM, MAIN, Reg, hw_func, int16_t

@hw_func
def next_state(s: state_t) -> state_t:
    ...                                  # pure: no Reg, no Feedback, no globals

UPDATE = AUTOFSM(next_state)             # construct once, at module/factory level

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
  anywhere in its call subtree), take exactly **one** annotated argument, and
  have an annotated return type. Bundle multiple inputs into an `@struct` — the
  same single-argument rule `make_stream_pipeline` and `make_valid_ready_mcp`
  follow.
- The argument is a `{data, valid}` struct. Use `MY_FSM.in_stream_t`, or any
  structurally identical type — `make_stream_t(in_t)` from
  `include/pypeline/stream/stream.py` works, and is duck-type compatible.
  (`src/pypeline.py` cannot import the `include/pypeline` library, which is why
  it grows its own twin of that struct.)
- An input is accepted **only while the FSM is idle**. A `valid` pulse asserted
  while it is busy is IGNORED — there is no backpressure signal in this version.
  Space requests at least `.latency` cycles apart; `.latency` is available to
  the surrounding Python precisely so it can do that. `make_stream_autofsm`
  (§2.1) does this bookkeeping automatically, with real valid/ready
  backpressure instead of manual spacing.
- The result appears with a one-cycle `valid` pulse **exactly `.latency` cycles**
  after the accepted input cycle. `.data` holds the last result between pulses.
  Initiation interval == `.latency`.
- Construct `AUTOFSM(...)` **eagerly, once**, and capture it by closure into the
  `@hw_func` that calls it. Constructing it inline inside a function body still
  works, but then nothing outside can read `.latency`. (Same rule, same reason,
  as AUTOPIPELINE.)

**When `.latency` reads 0**, the call site is a zero-latency combinational
passthrough (`o.data = func(s.data); o.valid = s.valid`):

- plain native Pypeline sim (`pypeline_sim.py` run directly),
- `--comb` / `--no_synth` / `--yosys_json` builds,
- the bootstrap elaboration pass of a real build.

This mirrors AUTOPIPELINE exactly, and it is why a well-written AUTOFSM
testbench reacts to `resp.valid` rather than counting cycles: the same source is
then correct at latency 0 and at latency 17.

**`max_latency=N`** caps the FSM's in→out latency at N cycles (execution states
plus the registered-output cycle). It is a **hard constraint**: if no schedule
meeting the clock goal fits inside N cycles the build fails, with a message
naming the FSM and the latency it actually needs. The tool meets a cap the only
way a cap can be met — by giving back sharing and building a second (third, …)
copy of whatever unit is forcing the states. Note that "no cap" and "generous
cap" are not the same thing: the area search spends latency to buy area (§3.7),
and the cap bounds how much of it the search may spend.

```python
UPDATE = AUTOFSM(next_state, max_latency=8)   # never more than 8 cycles
```

`register_output=False` is the area-oriented boundary form: the result and its
one-cycle valid pulse are driven directly in the final execution state, so
`.latency == n_states` and no result register bank is built. The default is
`True` because a raw call site's `.data` then holds the previous result between
pulses. Most designs should not set this directly; `make_stream_autofsm` uses it
when its own backpressure holding register is already the output boundary.

### 2.1 Stream wrapper: `make_stream_autofsm`

`include/pypeline/stream/stream_autofsm.py`'s `make_stream_autofsm(func,
max_latency=None)` is pure library code (no compiler changes) built the same
way `make_stream_pipeline`/`make_valid_ready_mcp` are: it constructs an
`AUTOFSM(func, max_latency=max_latency, register_output=False)` internally and
wraps its final-state result in
a real valid/ready `@interface` stream port, so callers no longer hand-roll
the `busy`-register spacing the raw contract above requires.

```python
blob_fsm, blob_fsm_t = make_stream_autofsm(blob)
@MAIN(25.0)
def top(stream_in: blob_fsm.in_stream_t, stream_out: blob_fsm.out_fb_t) -> blob_fsm_t:
    return blob_fsm(stream_in, stream_out)
```

**Shape: exactly one registered output.** A holding register latches the FSM's
one-cycle final-state pulse; a `busy` register tracks whether the FSM itself is
occupied. Raw AUTOFSM's optional output bank is disabled here: building it and
then immediately copying it into the wrapper's holding register would spend
two full-width banks on a boundary that needs one.
`stream_in_if.ready` is asserted only when both are free, and the output side
is computed *first* in the body (the same same-cycle out→in trick
`make_valid_ready_mcp` uses), so the slot a result just vacated is visible to
the accept decision in the same cycle — back-to-back requests with an always-
ready consumer still pack tightly, one every `latency` cycles, no bubble.

Two alternative shapes were considered and rejected:
- **Bypass/skid output** (combinational presentation when the slot is free,
  registering only on a downstream stall) matches the raw AUTOFSM latency
  exactly, but adds a combinational path from the FSM's own output registers
  to the wrapper's port — the registered-output shape has none.
- **Cycle-counter** (mirroring `make_valid_ready_mcp`'s `cycles_since_launch`)
  hits `latency` cycles of II with zero bubble, but its body would have to read
  `.latency` directly — see the next paragraph for why that's a real hazard
  here, not just a style preference.

**Latency = `fsm.latency + 1`; II = `fsm.latency + 1`.** The one extra cycle
over the raw FSM is the holding register. Crucially, **the generated hardware
never reads `.latency`** — unlike the raw call site's manual spacing, the
wrapper's RTL shape is identical whether `fsm.latency` is 0 (bootstrap pass /
`--comb` / native sim) or a real scheduled value. This matters because
`AUTOFSM.__repr__` (§3, canonical-name hashing) carries the canonical key and
`max_latency` but *not* `.latency` itself — a wrapper whose body varied with
`.latency` could hash two genuinely different circuits to the same entity name
and reuse stale measured delays. Avoiding `.latency` in the body sidesteps it
by construction.

See `src/tests/pypeline_tests/inst/stream_autofsm_test.py` for the native-sim
handshake/backpressure tests and `self_check_stream_autofsm_test.py` for the
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
 AUTOFSM.HARVEST_AUTOFSM_SCHEDULES   build DAG -> schedule -> bind
    ▼
 pypeline.SET_AUTOFSM_SCHEDULE_CACHE     canonical_key -> schedule dict
    ▼
 PY_TO_LOGIC.PARSE_FILE (re-execute the design)
    │  now _elab_call finds a schedule and instantiates the GENERATED FSM,
    │  and .latency reads a real value
    ▼
 sweep + AUTOPIPELINE convergence  (the normal flow, unchanged)
    ▼
 timing met?  ──no, and an AUTOFSM is to blame──►  shrink its per-state
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

Three classifications:

- **delay 0 → glue.** Never scheduled, never shared, re-rendered inline at each
  use. Duplicating free wiring costs nothing.
- **delay fits a state → atomic unit.** Shareable: two nodes of this entity in
  different states bind to one FU.
- **delay exceeds a state's budget → descend**, inlining the operation's body
  into this DAG so something too slow for one state can be split across several.

There is a fourth reason to descend that has nothing to do with delay: the area
search may pass an `opened` set of entities it wants taken apart because doing
so is estimated to make the design smaller (§3.7). Both paths go through the
same code; the budget test and the `opened` set are simply OR-ed.

Descent enters an entity if it has a recorded live Python callable — i.e. it
came from Python source that can be regenerated — or if it is a built-in
operator for which the soft-operator library supplied an equivalent that does
(§3.7). Descent is **best-effort**: a body that cannot be regenerated falls back
to keeping the operation atomic (reported as a floor) rather than failing the
build.

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
   in a fixed order, so if unit A feeds unit B in one state, B can never feed A
   in another.

Ready operations are tracked incrementally, through a priority heap fed by a
per-node count of unplaced predecessors. Rescanning every unplaced operation
after every placement is quadratic per state — invisible when a DAG held a few
dozen operations, and fatal now the area search routinely scores candidates
holding thousands.

If nothing at all fits an empty state, the cheapest ready operation is forced in
alone and the schedule is flagged **`at_floor`**: one indivisible operation that
no number of extra states can speed up. The driver stops tightening when it sees
this, instead of looping to its pass cap.

**Copies.** Binding is normally one unit per entity, but `SCHEDULE_DAG` accepts
a per-entity copy count, and `schedule["fus"]` maps unit id → entity as an
explicit indirection rather than assuming the two are the same string. Two
things use it: a `max_latency` cap that sharing alone cannot meet (an entity
used F times with R copies needs at least ⌈F/R⌉ states, so a cap of S states
forces R ≥ ⌈F/S⌉ — computed directly, not searched for), and the area search's
unshare move (§3.7).

Constants: `DEFAULT_BUDGET_SCALE = 0.9` (the delay model does not account for
everything the FSM's own control adds, so leave headroom),
`BUDGET_TIGHTEN_FACTOR = 0.75`, `MAX_SCHEDULE_PASSES = 6`. `MUX_PENALTY_DU = 10`
survives only as the seed for a mux shape nothing has ever measured. Override
the starting budget with `--autofsm_budget_scale`.

Determinism is load-bearing: node ids come from source coordinates, ties break
on node id, and the schedule is a pure function of (Logic graphs, delays,
budget_scale, the search's grain and binding choices). Independence from the
surrounding design is what makes the driver's loop converge trivially — only an
explicit tightening can change the answer, so there is no fixed-point search.
The area search is bounded by move and DAG-size caps, never by a wall clock,
for the same reason.

### 3.2b Operand multiplexers

Sharing a unit means selecting its operands per state, and that multiplexer is
the entire cost side of the sharing trade. It is modelled as a **real
entity**, not a flat per-operation constant — a flat estimate is wrong in
both directions at once, over-charging a unit with two users and badly
under-charging one with twenty, exactly the range the area search explores
(see History for the measured error this replaced) — in
`include/pypeline/operators/autofsm_mux.py`:

```python
@hw_func
def autofsm_operand_mux(sel: uint3_t, choices: int16_t[6]) -> int16_t:
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

**It gets measured.** A generated FSM holds state, so SYN treats it as one
atomic span and never looks inside it (`FUNC_PATH_DELAY_IS_ESTIMABLE`). That is
right for the FSM's own fmax number and wrong for its multiplexers, so
`AUTOFSM._REGISTER_MUX_ENTITIES` and `SYN._AUTOFSM_MUX_ENTITIES` name these few
entities and `ADD_PATH_DELAY_TO_LOOKUP` collects them for measurement in their
own right. They are small — one 3-to-8-way mux per shared unit input port — so
this is a handful of quick synthesis runs, not a meaningful build cost.
**The entity AUTOFSM measures is the entity AUTOFSM instantiates.**

The module lives under `include/pypeline/operators/` so that
`SYN._IS_PYPELINE_OPERATOR_LIBRARY_CODE` classifies it as shipped library code
rather than user code, which is what makes a measured delay eligible for
`path_delay_cache` — though this classification does not currently fire for
these entities (or for the soft-operator library the same predicate was
written for), so both are re-measured each build rather than read from disk;
see [`SYN_DESIGN.md`](SYN_DESIGN.md)'s Limitations section for why and the
fix. The delays are correct either way — this only affects build time.

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
struct fields. A field used after the first state receives its own input
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
def autofsm_chain_428aec93(s: _af_t0) -> _af_t1:
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
by `--autofsm_ctl` (`auto` by default; `v3`, `v2` and `onehot` are explicit
choices). The shape shown is `v3`.

**`--autofsm_ctl v2`** decodes state with comparators: `u0_sel = 0; if st ==
2: u0_sel = 1; elif st == 3: ...` per shared unit, and `if st == 1: ... elif
st == 2: ...` for the writebacks and next state. That is one equality
comparator per fold per unit plus one per state, each followed by a priority
chain — O(states x units) comparators, all of them in the path from the state
register to the operand multiplexers.

**`--autofsm_ctl v3`** (what `auto` normally selects) replaces every one of
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
  parallel with `operands -> mux.data`. This is why `CTL_LUT_DU` is 0: charging
  it in series would model a sum where the truth is a max.

Two shapes were considered and **rejected**: using the state bits *directly* as
a mux select (with data inputs padded out to one row per state) grows the
operand mux from `folds` rows to `states + 1` rows, which on any real data
width costs far more than the decode it saves — sine's 7-fold float64 unit would
buy 8 extra 64-bit mux rows to avoid about 3 gates. And a real ROM primitive
does not exist in the compiler; a constant array at a variable index is the
closest thing, which is exactly what is used here.

`onehot` goes further: the state register becomes one bit per state (plus idle),
so every control signal is a constant-index bit read. Write enables become
`v0_we = st1h[1:1] | st1h[3:3]`, the next state is a bit shift, and the accept
is a bit read — **zero** comparators. It pays for this with one flip-flop per
state instead of `log2(states)`, and with a binary encoder per shared unit,
since the operand mux is a measured balanced tree that needs a binary select.
Measured results are in §4. `auto` independently performs the area search for
v3 and onehot, rejects either encoding if it violates the timing budget or
`max_latency`, and selects the smaller estimate. The resolved encoding is
stored in the schedule and printed with both candidate costs. `v2` remains an
explicit regression/A-B mode rather than an automatic candidate.

Points that are easy to get wrong, and are deliberate here:

- **Snapshot every register first.** Pypeline assignment is sequential, so a
  later write to `st_r` would otherwise be visible to an earlier-written read.
  Reading everything into locals up front makes the body a clean "read committed
  state → compute → write next state". (This is the ordering hazard
  `make_valid_ready_mcp` handles by hand; here it is solved once, structurally.)
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
- **The entity name hashes the schedule** (`autofsm_<func>_<hash8>`), so
  rescheduling produces a *different* entity. That makes stale cross-pass reuse
  structurally impossible: nothing can seed pipelining onto, or reuse a cached
  delay for, an entity whose contents changed underneath it.
- Given the same schedule, generated source is **byte-identical** across
  re-elaborations. Entity-name stability across the driver's repeated passes
  depends on it, and `autofsm_unit_test.py` asserts it.

Generated source is written to `<out_dir>/autofsm_generated/` on every build, so
a problem inside it can be read as source instead of inferred from VHDL.

### 3.4 The driver loop

`AUTOFSM.DO_SCHEDULE_PASSES`, called from [`src/pipelinec`](../src/pipelinec) via
`SYN.DO_PIPELINED_BUILD`, wraps `SYN.DO_SWEEP_AND_AUTOPIPELINE` (the sweep +
AUTOPIPELINE convergence flow). Each pass: measure → schedule → install →
re-execute the design → full sweep + AUTOPIPELINE convergence → check timing.

The bootstrap design is deliberately **not** swept: it contains the raw
combinational blob nobody intends to build, so sweeping it would just fail
timing pointlessly. It exists only to be measured.

On a timing failure, `BLAMED_AUTOFSM_KEYS` decides which regions are implicated.
The sweep names the failing MAIN and, when it could attribute one, the function
to blame — and a generated FSM entity is exactly the kind of unsliceable atomic
block it reports. With no attribution available (notably PYRTL, whose software
timing model reports no path detail) it falls back to blaming every AUTOFSM under
the failing MAIN: over-blaming costs one extra pass, under-blaming would silently
give up.

Tightening then shrinks the budget **until the schedule actually changes** — one
step of the factor does not always move an operation across a state boundary, and
rebuilding a byte-identical design to discover that would waste a synthesis run.
The loop stops when timing is met, when nothing is blamed, when every blamed
region is `at_floor`, when further shrinking changes nothing, or at the pass cap.

### 3.5 Delay measurement

Two changes were needed in `SYN.py`, both small and both about *which* functions
get delays:

- **`FUNC_SUBTREE_HAS_AUTOFSM`** — a stateful container holding an AUTOFSM call
  site must have its subtree delays resolved. Without this, a stateful MAIN with
  no AUTOPIPELINE anywhere is an atomic span and *nothing inside it* is ever
  measured, so the scheduler would see zero delays everywhere and put the whole
  function in one state. (Only ever true on the bootstrap pass: once scheduled,
  the tag lives on the calling function while the FSM entity below it is
  correctly treated as an atomic span, whose one whole-module synthesis measures
  its register-to-register path — i.e. its worst state.)
- **`parser_state.func_force_estimated`** — the bootstrap passthrough looks
  exactly like a measurement frontier (fully combinational, inside a stateful
  caller) and would get one whole-blob synthesis of precisely the giant parallel
  logic the user asked *not* to build. For a float64 polynomial that does not
  finish in reasonable time. Nothing needs that number; the scheduler works from
  the individual operations underneath, which are measured and cached as usual.

### 3.6 Simulation

`AUTOFSM._sim_fsm` in `src/pypeline.py` models the generated FSM's registers
directly — same state register, same input latch, same output registers — so
native sim and hardware are cycle-accurate against each other by construction
rather than by a separate argument. It follows the established commit discipline
(`_sim_delay_line`, `_call_sim_model`): the returned value depends only on state
committed at the last clock edge, so repeated evaluation during convergence
cannot churn, and the next state is buffered so only the final pass lands.

Schedules reach the simulator the same way AUTOPIPELINE latencies do:
`SIM.DO_OPTIONAL_SIM` → `pypeline_sim.run_sim(autofsm_schedules=...)` →
`SET_AUTOFSM_SCHEDULE_CACHE` **before** the design import, because the tag
captures its schedule at construction and any `.latency`-derived Python sizing
must match what was built.

### 3.7 The minimum-area search

`SWEEP_MIN_AREA_SCHEDULE` runs on every AUTOFSM build unless
`--autofsm_no_area_sweep` is given.

#### What it searches over

Two axes:

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

Candidates are prepared during the bootstrap elaboration
(`PREPARE_SOFT_EQUIVALENTS`), the one moment a live elaborator, the design's
module globals and the tagged function are all in hand at once. They land in
`FuncLogicLookupTable` **uninstantiated** — candidates, not hardware. Nothing is
built unless the search picks it. Two supporting details that are easy to get
wrong:

- Built-in operator `Logic` objects are created lazily while walking the
  *instance* tree from the MAINs, so a candidate's bitwise leaves have no
  `Logic` at all until `_RESOLVE_BUILTIN_SUBMODULES` materializes them. Without
  that they look like zero delay and zero area, and decomposition looks **free**.
- Their delays come from `path_delay_cache` via `_resolve_delay_du`: a candidate
  is never instantiated so never measured, but its leaves are the universal
  bitwise operators every design uses, so real measurements are normally already
  on disk.

`PY_TO_LOGIC` grew two side tables for this, both populated as a side effect of
ordinary elaboration:

- **`pypeline_builtin_op_info`** — entity → (op name, operand c types), so
  AUTOFSM can ask the library for the right factory without parsing entity
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
AUTOFSM'd function's whole elaborated subtree, not just what survived into
the schedule, so a type used only inside a fully-descended entity is still
resolvable. See `qor/multiplier/autofsm.py`, the design that exercises this,
and the `[type resolver: array reconstruction]` section of
`autofsm_unit_test.py`.

#### The search itself

```
anchor = the plain share-everything schedule      # candidate zero and incumbent
repeat up to MAX_SWEEP_MOVES times:
    for each openable entity:   reschedule the WHOLE function with it opened
    for each shared entity:     reschedule the WHOLE function with one more unit
    take the cheapest feasible result, even if it is worse than the incumbent
    if it beats the best-so-far by > SWEEP_MIN_IMPROVEMENT
       and clears the anchor-relative OPEN shape-confidence guard:
        it becomes the best
    else after MAX_SWEEP_UPHILL consecutive non-improvements: stop
return the best
```

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
that state exceeds the scaled clock budget, or if it violates `max_latency`.
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
`src/AUTOFSM.py` — that only ever *ranks* candidates against each other. yosys
cell counts appear only inside the test suite, to calibrate the model and to
prove before/after numbers; never inside the search.

The model has five terms, which are exactly the things sharing trades between:

- **units** — one copy of each bound entity, however many operations use it. The
  term sharing shrinks, and the reason AUTOFSM exists.
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
`autofsm_area_sweep_compare_test.py` is where that correspondence is held to
account.

**Under `--syn_tool sky130`, this changes for three of the five terms.** The
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
round. `--autofsm_abstract_area` forces the old abstract-only ranking, for
A/B comparison against real data.

**Gating.** Every function below only returns real numbers when
`SYN.SYN_TOOL is DEVICE_MODELS` (i.e. `PART("sky130...")` or
`--syn_tool sky130`); for every other tool the cache is empty by
construction (`SYN.GET_AREA_CACHE_DIR` returns `None`) and every AUTOFSM
build outside sky130 is unaffected — same schedules, same numbers, as
before this section existed.

**The API, mirroring delay's own shape:**

| delay (`_resolve_delay_du`) | area (`AUTOFSM._leaf_area_um2` et al.) |
|---|---|
| `SYN.GET_CACHED_PATH_DELAY(logic, parser_state)` — per-leaf disk cache read | `SYN.GET_CACHED_LEAF_AREA(logic, parser_state)` → `(value_um2, "um2")` or `None` |
| — (no by-key form needed; delay is always looked up via a `Logic`) | `SYN.GET_CACHED_LEAF_AREA_BY_KEY(key, parser_state)` — same read, keyed directly (`"MUX_uint{width}_t"`) for operand multiplexers, priced from `(ctype, fold count)` during scheduling before any mux entity exists |
| `_heuristic_leaf_delay_du` | `_leaf_area` (§3.7), scaled by `UM2_PER_ABSTRACT_AREA_UNIT` into µm² |
| — | `DEVICE_MODELS.GET_SEQUENTIAL_CELL_AREA()` → `(48.84, "um2")` — a closed-form liberty lookup, not a per-shape measurement, so `_ff_area_um2` needs no cache at all |

`AUTOFSM._area_unit_scale(parser_state)` is the single switch: `1.0`
(abstract units, unchanged behavior) for every non-`DEVICE_MODELS` tool or
when `FORCE_ABSTRACT_AREA` is set, `UM2_PER_ABSTRACT_AREA_UNIT` otherwise —
every other area function multiplies its abstract fallback by this, so
`est_area` is directly comparable to a build's own `Measured area: ...` line
under sky130 without further conversion. `AUTOFSM._leaf_area_um2`,
`_ff_area_um2` and `_mux_bank_area_um2` each implement the cache-hit →
scaled-fallback tier for one kind of term; `ESTIMATE_ENTITY_AREA`'s own hierarchy
walk stays AUTOFSM's, deliberately **not** delegated to
`SYN.GET_ESTIMATED_COMBINATIONAL_AREA` — that function returns `0.0` for an
uncached leaf and reports it as missing, which would read as free wiring and
never get shared (the same failure mode v1's zero-delay bug had). A schedule
carries how much of its `est_area` was measured vs estimated in its
`DESCRIBE_SCHEDULE` build-log line (`area model: sky130 um2 (N measured, M
estimated)`), alongside a new `register bits: N` line (`_register_bit_count`)
recording AUTOFSM's live-range registers plus compacted transaction input,
state and optional output storage independent of area — useful on its own for
comparing against a real build's sequential cell count (see the register-count
finding below).

**The leaf area cache underneath this excludes the STA harness's own registers**
from each leaf's cached value — see [`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md)'s
History section ("Area model V1 → V2") for why that distinction matters; nothing below
depends on the details, only on the corrected values being what's cached.

**What real measurement corrected, once the harness was out of the way.**
Fitting real cached µm² against width across every `BIN_OP_PLUS`/`MINUS`
entry in `area_cache/` (both cost `AREA_PER_BIT_ADD` per `_leaf_area`, so one
joint fit covers both) gives `UM2_PER_ABSTRACT_AREA_UNIT ≈ 98.93` µm² per
adder bit. `AREA_PER_BIT_MUX` scaled by it is 1.15x the real cached
`MUX_uintN_t` leaves — 29.304 µm²/bit, exact (not just close) across every
measured width 1/8/32/34/64 — a real, independent confirmation of the ratio
`autofsm_min_area_verify_test.py` set by a completely different method
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
`inst/autofsm_real_area_compare_test.py` is where this is checked against
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

`autofsm_min_area_verify_test.py` is where this is measured rather than
asserted: it builds the alternatives the search passed over
(`--autofsm_open` / `--autofsm_unshare`) and checks the search's answer against
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
divider; opening exposes that arithmetic to AUTOFSM's per-leaf sharing but also
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

* `autofsm_donut_update` is int16 add/subtract/compare. Opening a 16-bit adder
  yields ~16 one-bit operations, each wanting its own operand multiplexers and
  cross-state registers, to save one adder. Its state count also has a floor no
  clock can lower: the most-shared unit carries 8 operations, and one unit runs
  at most one operation per state.
* `float_sine_autofsm` is float64. Floating-point operands have no soft
  equivalent and float built-ins have no Python source to descend into, so its
  expensive units are not openable candidates at all. Its state count *does*
  fall with a looser budget (14 → 10 at 1 MHz), but that is the greedy scheduler
  packing more per state, not the search choosing differently.

A design where opening pays needs a unit far more expensive than the
multiplexers and control sharing its pieces costs, with a modelled margin large
enough for the resulting shape change. A divider is the strongest in-repo
candidate — its soft equivalent is a chain of compare-and-subtract steps — and
`autofsm_div_share_test.py` deliberately confirms that even this particular
small divider is still cheaper left whole.

#### Which built-in operators can be opened at all

`_SOFT_FACTORY_FOR_OP` maps a built-in operator to the soft-operator equivalent
descent uses. Signedness is part of that choice, and getting it wrong does not
produce a slower design, it produces a WRONG one — `_open_target`'s return-type
and arity checks cannot tell the difference, since the widths match and only the
answers differ.

| operator | unsigned | signed |
|---|---|---|
| PLUS / MINUS | ripple adder / subtract-via-add | same |
| MULT | shift-and-add | **not openable** — no signed soft multiplier exists |
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
| `autofsm_resources_test.py` — 6 multiplies + 5 adds | 11 | **2** | 6 | 7 |
| `autofsm_donut_update.py` — donut per-frame rotation | 28 | **9** | 8 | 9 |
| `float_sine_autofsm.py` — float64 degree-5 Horner | 19 | **4** | 14 | 15 |

Area, same design built both ways (yosys cell count, whole-design top):

```
combinational (--comb, no sharing):    12117 cells
resource-shared FSM              :      3392 cells      3.57x smaller
```

Under `--syn_tool sky130`, the real-area search (§3.7, §3.8) currently reaches
24,095.7 µm² total (14,278.9 combinational + 9,816.8 sequential, 201 real FF
cells) on a divider design, at 70.40 MHz — **10.62× smaller** than the lowest
committed AUTOPIPELINE/latchup.app reference for the same design (255,886.4
µm², asserted by `autofsm_real_area_compare_test.py`; the estimator is only
the ranking signal). The structural changes that contributed most:
deduplicating the output register bank (`make_stream_autofsm` owning the only
one, rather than a separate raw-AUTOFSM bank copied into it), factoring
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
(`--autofsm_budget_scale 1.5`): first build 30.46 MHz vs a 40 MHz goal (FAIL) →
budget tightened → 44.23 MHz (PASS), with no source change.

Latency capping: `AUTOFSM(add_chain, max_latency=4)` on five dependent adds that
would otherwise share one adder over 5 states (latency 6) builds 3 adders over 2
states (latency 3) instead. `max_latency=2` on the same design fails the build
with *"the shortest schedule … needs 2 states (latency 3) … raise max_latency to
at least 3"*.

---

## 5. Tests

| test | category | what it proves |
|---|---|---|
| `autofsm_test.py` | native_sim, (synth via wrapper) | the pure function's semantics, and the passthrough behaviour when unscheduled |
| `autofsm_unit_test.py` | unit | scheduler/codegen internals: binding, one-op-per-unit-per-state, dependency order, distinct-operand mux coalescing and common-glue factoring, same- and cross-FU register reuse, recovered rolling output and consume/produce storage, field-lifetime input compaction, optional output bank, automatic control encoding, budget → states, floors, determinism, schedule is carryable data, soft-operator equivalents, soft adder sign extension, `_TypeResolver` array reconstruction, real-sky130-area tiering (cold cache falls back to scaled abstract not zero, a cache hit wins over any abstract guess, `--autofsm_abstract_area`, real flip-flop area) |
| `area_model_test.py` (`src/tests/pypeline_tests/inst/`) | unit | not AUTOFSM-specific (SYN/DEVICE_MODELS leaf-area-cache coverage), but two tests here directly guard AUTOFSM.py's own constant: the committed `area_cache/` excludes STA-harness registers, and `AUTOFSM.UM2_PER_ABSTRACT_AREA_UNIT` refits to what is actually committed |
| `self_check_autofsm_test.py` | native_sim, vhdl_sim, synth ×2 | the FSM computes what the function did — in native sim, in GHDL, at latency 0 and at real latency |
| `stream_autofsm_test.py` | native_sim | `make_stream_autofsm`'s handshake protocol: ready deasserts while busy, latency/II == `fsm.latency + 1`, and — the property raw AUTOFSM cannot provide — a stalled consumer never loses a result and sees stable data while it's held |
| `self_check_stream_autofsm_test.py` | native_sim, vhdl_sim, synth ×2 | same shape as `self_check_autofsm_test.py`, one layer up: the wrapper's handshake + the real scheduled FSM underneath it compute and sequence what the function did, with real backpressure toggled from the testbench, in native sim, in GHDL, at latency 1 and at real latency |
| `qor/multiplier/autofsm.py`, `qor/divider/autofsm.py`, `qor/sqrt/autofsm.py` | synth | AUTOPIPELINE→`make_stream_autofsm` conversions of the QoR designs, real `PART("sky130")`/pyrtl builds with `ready` genuinely wired (never a constant 1); the multiplier is what exposed and pins the `_TypeResolver` array-reconstruction fix below |
| `autofsm_latency_test.py` | synth | end-to-end schedule; the generated VHDL instantiates exactly as many copies of each shared unit as the schedule claims |
| `autofsm_resources_compare_test.py` | synth | the FSM is actually smaller than the logic it replaces |
| `autofsm_area_sweep_compare_test.py` | synth | the area search does not make designs bigger, and its cost model agrees with yosys about which of two schedules is smaller — the calibration guard |
| `autofsm_min_area_verify_test.py` | synth | the search actually MOVES on a design built to reward moving, the move is smaller in real yosys cells, and no alternative point of the search space (built via `--autofsm_open` / `--autofsm_unshare`) is smaller still |
| `autofsm_real_area_compare_test.py` | build_report | same question under `--syn_tool sky130`, judged by real `Measured area:` rather than yosys cells: real-µm²-ranked vs `--autofsm_abstract_area` vs `--autofsm_no_area_sweep`, all three built; pins the 25k µm² v7 structural ceiling and beats the lowest committed AUTOPIPELINE/latchup.app divider area; plus AUTOFSM's own allocated-storage bit count against the build's real sequential cell count (the register-fidelity question §3.8 raises explicitly) |
| `autofsm_max_latency_test.py` | synth | a meetable `max_latency` is met by unsharing; an unmeetable one fails the build naming the latency actually needed |
| `autofsm_timing_iter_test.py` | synth | a critical path inside an FSM is found and fixed by rescheduling |
| `autofsm_ctl_compare_test.py` | synth | the constant-table control path is not bigger than the comparator chains it replaced, and the donut FSM still meets the clock goal that v2 misses |
| `double_parse_file_test.py` | elab | re-parsing an AUTOFSM design is reproducible |

`self_check_autofsm_test.py` is worth copying as a template: it reacts to
`resp.valid` rather than counting cycles, so one source file is correct at every
latency, which is what lets it be reused unchanged across four registrations.
`self_check_stream_autofsm_test.py` follows the same template one layer up —
it reacts to `stream_out_if.stream.valid & ready_now` (the real "consumed this
cycle" condition) instead, so it is equally correct at latency 1 (`--comb`)
and at `fsm.latency + 1` (scheduled).

---

## 6. Limitations and future work

**Current limitations**

- One argument (bundle into a struct); one computation in flight; the raw
  call site has no backpressure — `valid` while busy is ignored. Wrap with
  `make_stream_autofsm` (§2.1) for a real valid/ready port instead.
- The function must be pure: no `Reg`, `Feedback` or global wires anywhere in
  its subtree. Dynamic (non-constant) array indexing is not supported yet.
- An operation bigger than a state that cannot be decomposed *and* has no
  soft-operator equivalent sets a floor. That is honest — a float64 multiplier
  is not divisible by scheduling — but it means the clock goal must be reachable
  by the slowest single operation.
- Control overhead grows with the number of folded operations, because the
  operand multiplexers do. At tens of operations this is a clear win; at
  thousands the multiplexers would dominate (see "loop-preserving FSMs" below).
- The area model is still a model for every tool except sky130, and even under
  sky130 it is a per-leaf sum, not a whole-design synthesis: it ranks
  candidates in abstract units calibrated against yosys cell counts (§3.7),
  which is not the same thing as LUTs on the part you are targeting — on an
  FPGA, flip-flops come paired with the LUTs in front of them and are far
  cheaper than a cell count suggests. Under `--syn_tool sky130` (§3.8) the
  unit, register and multiplexer terms use real cached µm² instead, which
  fixes the FPGA-calibrated flip-flop term's biggest error (2.5x too cheap)
  but does not fix two gaps a per-leaf sum cannot see by construction: (1)
  **cross-instance combinational sharing** on wide operand-multiplexer
  trees — confirmed still present as a 256% whole-design overshoot on
  `qor/divider/autofsm.py`, versus only 4.65% on `qor/multiplier/autofsm.py`
  (which shares to one atomic unit with no wide muxes at all), so the gap is
  design-shape-dependent, not a constant to calibrate away; and (2)
  **`SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS`'s own FF-count overshoot**
  (5.7-5.9x; per-FF area is exact, so the error is entirely in the *count*,
  before any yosys-level FF optimization) — a different and much cruder count
  than AUTOFSM's own `ALLOCATE_REGISTERS` (§3.2c), which tracks genuinely
  live cross-state values rather than every declared bit, checked directly
  (not assumed) in `inst/autofsm_real_area_compare_test.py`. Neither gap is
  specific to the search's ranking: both are as true of
  `SYN.ESTIMATE_DESIGN_AREA`'s whole-design build-log estimate as of the
  terms feeding `ESTIMATE_SCHEDULE_AREA`. The anchor bounds model-space
  regressions; the real whole-design A/B tests guard the physical result.
- An ARRAY-typed operand cannot be shared. Its operand multiplexer is an array
  of arrays, and `T[A][B]` currently mis-elaborates to VHDL — a bare
  `make_operand_mux(uint2_t[16], 4)` design fails GHDL import with "can't match
  ... with type array type uint2_t_4", with no AUTOFSM involved. Reachable only
  from a schedule that shares an operation taking a whole array, which is rare;
  the underlying 2D-array bug is not an AUTOFSM one and is unfixed.
  **Not the same bug** as the array-reconstruction guarantee in §3.7's
  "Descending past the operator level" — this one is about SHARING an
  array-typed value across states (the mux), which is still open.

**Future work**

- **Width/capacity subsumption in binding and allocation.** This remains
  unimplemented: entities and ordinary value registers still require exact C
  types. A 32-bit adder can serve every compatible <=32-bit add by extending
  inputs and truncating the result, and a `uint32_t` physical register can hold
  non-overlapping `uint1_t`/`uint8_t`/`uint16_t`/`uint32_t` lifetimes if every
  read narrows back to the value's declared type. The seams are already in
  place: `schedule["fus"]` maps unit id → entity as an explicit indirection,
  per-node cast chains are the FU adapter mechanism, and live ranges are
  separate from physical register ids. The next implementation should be a
  weighted capacity search, not unconditional widening: a bigger unit, wider
  operand/writeback mux and extension logic can cost more than the narrow unit
  or FF bank it replaces. Legality is operation-specific too — unsigned
  add/bitwise operations are straightforward, while signed comparisons,
  shifts, overflow-visible results and mixed signedness require explicit rules.
  The current divider has only one scheduled width of each recurrent operation,
  so this axis would not change its measurement; heterogeneous arithmetic FSMs
  are the right regression designs for it.
- **Recurrent operator-chain binding.** A human FSM often executes
  `compute -> conditional select -> register` in one state and shares the whole
  chain across iterations. AUTOFSM binds each entity independently, so a
  one-time prologue use can phase-shift the recurrence and leave both the
  compute result and selected recurrence value registered. A forced second
  generic MUX experiment at the consume/produce-fusion stage did *not* help
  (25,476.9 → 27,973.6 µm²): ordinary copy binding split recurrence uses
  across both units and retained the same 105 working bits. A useful
  implementation needs chain-aware/prologue-aware
  binding, not merely another copy. This is likely the next large general gap
  to handwritten FSM area: human-written leaderboard implementations for this
  divider cluster around 10–17k µm² in the supplied latchup.app view, against
  this design's current 24,095.7 µm² (§4), so loop/control recovery and
  recurrent operator chaining still have meaningful headroom.
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
- **A max() chain fit.** The delay model sums a state's operation chain and its
  operand multiplexers. For the multiplexer that is not quite right: its select
  and its data arrive on independent paths, so the truth is
  `max(sel_path, data_path) + mux_delay`. Modelling that is what would let
  `CTL_LUT_DU` be charged honestly instead of pinned at 0.
- **A ROM/SRAM primitive.** Constant tables are built today as a constant local array
  read at a variable index, which elaborates to a full selection tree and only
  becomes cheap once synthesis folds the constants. It works (the whole v3
  control path depends on it) but the internal delay model prices the unfolded
  tree — a 5-entry table estimates at 4.8 ns where the module it sits in
  measures 1.9 ns. Harmless inside an AUTOFSM, whose delay is one measured
  whole-module number, but a real ROM/table primitive with its own cost model
  would make the idiom usable in ordinary designs. Likewise, a sufficiently
  large register file or lookup table could eventually map to SRAM, but no
  latchup-compatible inferred SRAM primitive exists in this flow yet; treating
  an ordinary array as one today only produces combinational logic.
- **A latent bit-slice bug in deeply-opened schedules.** Rescheduling the donut
  design under a tightened budget produces a 412-operation, 131-state plan whose
  generated source fails to elaborate: *"Bit index [14:14] out of range for
  uint9_t"*. This is unrelated to which control-path encoding is chosen — the
  constant-table default (§3.3, "The control path") only avoids triggering it
  by meeting timing, and therefore never opening the schedule this far, on
  the first pass — but it is reachable from any design the search opens far
  enough.
- **Multiple concurrent AUTOFSM threads sharing units.** Two FSMs that both need
  a float multiplier could share one, with arbitration. The binding step already
  keys on entity, so the scheduler generalizes; what is missing is the arbiter
  and a cross-FSM resource model.
- **Loop-preserving FSMs.** AUTOFSM schedules the *unrolled* graph, so control
  grows with the folded-operation count. The fix is real loop back-edges:
  schedule the body once, add an index register, and index operands from arrays.
  A user-facing sequential/`__clk()`-style layer for Pypeline would be the
  natural emission target for that — but note the dependency direction: such a
  layer does **not** help AUTOFSM as it stands, because per-state code regions
  would create one instance per call site and defeat the single-call-site
  sharing trick. AUTOFSM's emission helpers are reusable substrate for building
  it later, not the other way round.

## History

Why things are the way they are. Entries are keyed by **topic, not date** —
when something changes, revise the entry that owns that topic rather than
adding a new one. Keep a fact here only if it still changes a decision
today: an alternative someone would otherwise retry, a measurement that is
still a live regression reference, or the reason a default is what it is.

### Operand multiplexer costing

Sharing's entire cost side — the multiplexer selecting a shared unit's
operands per state (§3.2b) — used to be priced as a flat `MUX_PENALTY_DU = 10`
(1.0 ns) constant per scheduled operation. That was wrong in both directions
at once: over-charging a unit with two users, badly under-charging one with
twenty — exactly the range the area search explores. Measured directly, a
6-way `int16_t` mux costs 4.29 ns, a 4× error against the flat estimate, in
the one term that decides how much sharing is worth doing. Replaced with a
real, measured entity (`autofsm_operand_mux`, §3.2b), which also made
distinct-value coalescing and common-glue factoring possible — optimizations
a flat-cost model gave no reason to build, since it couldn't see the savings.

### Control-path encoding: constant tables, comparators, and one-hot

`--autofsm_ctl v2` (comparator chains) costs one equality comparator per fold
per unit plus one per state, each followed by a priority chain — O(states x
units) comparators in the path from the state register to every operand
multiplexer. `--autofsm_ctl v3` (constant lookup tables, what `auto`
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
