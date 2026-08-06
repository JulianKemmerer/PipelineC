# AUTOFSM: pure functions as resource-shared state machines

`AUTOFSM(func)` implements a pure combinational function as a finite state
machine that holds **one copy of each distinct operation** and runs the function
over several clock cycles. It is the resource-minimizing dual of
[`AUTOPIPELINE`](SYN_DESIGN.md): where AUTOPIPELINE cuts one full copy of the
hardware into N pipeline stages (initiation interval 1, maximum throughput,
maximum area), AUTOFSM keeps one adder and uses it twelve times (initiation
interval N, minimum area).

Both are tool-driven: you write the function, state a clock goal, and the build
figures out the rest — how many stages, or how many states.

- Implementation: [`src/AUTOFSM.py`](../src/AUTOFSM.py), the tag class in
  [`src/pypeline.py`](../src/pypeline.py), the elaborator hook in
  [`src/PY_TO_LOGIC.py`](../src/PY_TO_LOGIC.py), the driver loop in
  [`src/pipelinec`](../src/pipelinec).
- Pypeline (Python) frontend only. The C frontend's `__clk()`-based FSM support
  ([`src/C_TO_FSM.py`](../src/C_TO_FSM.py)) is a different feature solving a
  different problem — there the *user* writes the states.

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
for how Python becomes a `Logic` graph, and `docs/pypeline_guide.md` §15 for
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
  the surrounding Python precisely so it can do that.
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

**`max_latency=N`** caps the FSM's in→out latency at N cycles (N−1 execution
states plus the accept cycle). It is a **hard constraint**: if no schedule
meeting the clock goal fits inside N cycles the build fails, with a message
naming the FSM and the latency it actually needs. The tool meets a cap the only
way a cap can be met — by giving back sharing and building a second (third, …)
copy of whatever unit is forcing the states. Note that "no cap" and "generous
cap" are not the same thing: the area search spends latency to buy area (§3.7),
and the cap bounds how much of it the search may spend.

```python
UPDATE = AUTOFSM(next_state, max_latency=8)   # never more than 8 cycles
```

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
   measured delay of that unit's operand multiplexer at its actual fold count
   (§3.2b — v1 charged a flat `MUX_PENALTY_DU` here instead);
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
the entire cost side of the sharing trade. v1 modelled it as a flat
`MUX_PENALTY_DU = 10` (1.0 ns) per scheduled operation — wrong in both
directions at once, over-charging a unit with two users and badly under-charging
one with twenty, which is exactly the range the area search explores.

v2 makes it a **real entity**, in `include/pypeline/operators/autofsm_mux.py`:

```python
@hw_func
def autofsm_operand_mux(sel: uint3_t, choices: int16_t[6]) -> int16_t:
    return choices[sel]
```

Three things follow from that shape.

**It is an array read, not an if/elif chain.** A variable array index elaborates
to the balanced binary `VAR_REF_RD` selection tree — log2(N) deep. The nested
if/elif form v1 emitted inline elaborates to a *priority* chain, N−1 deep.

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
`path_delay_cache`. *Note:* that predicate currently looks at
`inspect.getsourcefile` of the callable recorded in `pypeline_entity_callables`,
which is the `@hw_func` **wrapper** — whose source file is `pypeline.py`, not
the library module. So it does not fire today, for these multiplexers or for the
soft-operator library it was written for, and both are re-measured each build
rather than read from disk. One `inspect.unwrap` at that lookup fixes it; the
delays are correct either way, this is purely build time.

Real numbers matter here: on the PYRTL flow a 6-way `int16_t` mux measures
4.29 ns against the 1.0 ns v1 assumed — a 4× error in the one term that decides
how much sharing is worth doing.

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
arrayed falls back to v1's inline form.

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

Two values may share a register only if they have the same c type **and come
from the same functional unit**. The type rule is obvious. The same-unit rule is
what makes this free: the register's data input is then that unit's output local
in every state that writes it, so the register only gains a wider write enable —
no data path is added. Allowing cross-unit sharing puts a multiplexer directly
in front of a flip-flop, usually on the critical path; measured on the donut,
that cost 42.4 → 37.5 MHz in exchange for a handful of flip-flops. Registers are
cheap and the clock period is not.

`ALLOCATE_REGISTERS` is used by both the code generator (which declares the
registers) and the area model (which prices them), so the model cannot drift
from what gets built.

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
    v0_r: Reg[_af_t6]           # one register per value crossing a state boundary
    v1_r: Reg[_af_t6]
    out_data_r: Reg[_af_t3]
    out_valid_r: Reg[_af_t5]
    # Snapshot committed state before any write below (pypeline assignment is sequential)
    st: _af_t4 = st_r
    in_v: _af_t2 = in_r
    v0: _af_t6 = v0_r
    v1: _af_t6 = v1_r
    o: _af_t1
    o.data = out_data_r         # registered outputs: data holds, valid pulses
    o.valid = out_valid_r
    out_valid_r = 0
    # Accept a new input only while idle (II == latency)
    if (st == 0) & s.valid:
        in_r = s.data
        st_r = 1
    # BIN_OP_PLUS_int16_t_int16_t: 3 operation(s) sharing one unit
    u0_a0: _af_t3 = in_v.a      # first user's operands double as the mux default
    u0_a1: _af_t3 = in_v.b
    if st == 2:
        u0_a0 = v0
        u0_a1 = in_v.c
    elif st == 3:
        u0_a0 = v1
        u0_a1 = in_v.d
    u0_o: _af_t6 = (u0_a0 + u0_a1)      # THE one hardware adder
    # Writebacks and next state
    if st == 1:
        v0_r = u0_o
        st_r = 2
    elif st == 2:
        v1_r = u0_o
        st_r = 3
    elif st == 3:
        out_data_r = u0_o
        out_valid_r = 1
        st_r = 0
    return o
```

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

`run_autofsm_schedule_passes` in [`src/pipelinec`](../src/pipelinec) wraps
`run_sweep_and_autopipeline` (the extracted sweep + AUTOPIPELINE convergence
flow). Each pass: measure → schedule → install → re-execute the design →
full sweep + AUTOPIPELINE convergence → check timing.

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

Two axes, which are the two directions off v1's schedule:

| move | what it changes | what it buys | what it costs |
|---|---|---|---|
| **open** an entity | one operation becomes its constituent operations | fewer distinct units; different entities may converge on the same smaller pieces and share them | more operations → more states, registers, multiplexers |
| **unshare** an entity | one more physical copy of a unit | narrower multiplexers; fewer states, so fewer registers | one more unit |

v1 could do neither deliberately. It opened an operation only when it was too
slow to fit a state — a correctness last resort, not a search — and it shared
everything unconditionally, which for anything cheaper than its own multiplexer
(a one-bit OR, say) is a straight loss.

#### Descending past the operator level

v1's descent bottomed out at built-in operators: a `BIN_OP_PLUS_uint32_t_uint32_t`
has no Python source, so there is nothing to re-express. v2 asks the
soft-operator library (`include/pypeline/operators/`) for an equivalent that
does — `make_soft_ripple_add`, `make_soft_shift_add_mult`,
`make_soft_sub_cmp_swapped`, … — whose own leaves are inferred bitwise
operations. Descent can therefore continue all the way down to gates.

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

#### The search itself

```
anchor = the plain share-everything schedule      # candidate zero and incumbent
repeat up to MAX_SWEEP_MOVES times:
    for each openable entity:   reschedule the WHOLE function with it opened
    for each shared entity:     reschedule the WHOLE function with one more unit
    take the cheapest feasible result, even if it is worse than the incumbent
    if it beats the best-so-far by > SWEEP_MIN_IMPROVEMENT: it becomes the best
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
the result is the best point ever seen. A mis-ranking costs an opportunity,
never a regression — which is what makes it safe to leave on by default.

**The search may not spend timing margin.** A candidate whose worst state is
longer than the anchor's is rejected outright, even though it still "fits the
budget" by the delay model's reckoning. The budget is a guess at how much of the
clock period the FSM's own control will leave, and a schedule that eats the
difference is buying area with margin that may not be there. This is not
hypothetical: on the donut example the search found a real 8% area saving by
opening three comparators onto a shared subtractor, pushed the worst state from
13.7 ns to 17.1 ns, and turned a design that met 40 MHz into one that missed at
36 MHz. Trading latency for timing is the **driver's** job (§3.4 — it tightens
the per-state budget and reschedules); the search's job is area at
equal-or-better timing, and nothing else.

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
- **multiplexers** — one per unit input port, sized by fold count. The term
  sharing grows, and the reason sharing more finely eventually stops paying.
- **registers** — cross-state values after allocation, plus the output and state
  registers.
- **state decode**.

The constants are normalised so one bit of an adder is 1.0, with ratios taken
from real yosys cell counts (a 16-bit add ≈ 100 cells ≈ 6.25 cells/bit; a
flip-flop, a 2-input gate and a 2:1 mux bit ≈ 1 cell each ≈ 0.16). **The single
most important ratio is arithmetic against multiplexer-and-register**, because
that is the entire sharing trade. An early cut of this model priced a 16-bit
adder the same as a 16-bit register, duly decided that unsharing cheap adders was
a win, and produced a design real synthesis measured 4.5% *worse*. An adder bit
is about six of the things sharing costs, not one.
`autofsm_area_sweep_compare_test.py` is where that correspondence is held to
account.

#### Where the stopping point comes from

Nothing in the code says "stop when the multiplexer delay exceeds the unit
delay". That behaviour falls out of the cost model. Walk the granularity axis far
enough and a 16-bit adder becomes 150-odd gates sharing three one-bit units
across 150-odd states — three tiny units, and multiplexers and registers costing
an order of magnitude more than the adder did. The estimate turns back up and
the search stops.

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

**v1 → v2**, same designs, same flow:

| design | v1 cells | v2 cells | change | note |
|---|---|---|---|---|
| `autofsm_resources_test.py` | 3605 | **3392** | **−5.9%** | array multiplexers + register allocation |
| `autofsm_donut_update.py` | 2680 | 2745 | +2.4% | still meets its 40 MHz goal (41.4 vs 42.3 MHz) |
| `autofsm_test.py` (blob) | — | 758 | — | the search evaluates 24 candidates and correctly declines all of them |

Worth being straight about what moved and what did not. The **codegen** changes
(measured array multiplexers, register allocation) are where the area came from.
The **search** declines to move on most of these designs — which is the right
answer: v1's share-everything binding really is close to optimal when every
shared unit is an expensive multiply or a wide add. The search earns its keep by
(a) proving that, cheaply and per-design, instead of assuming it, and (b) being
there for the designs where it is not true — cheap operations behind wide
multiplexers, or several composite units built from the same smaller pieces.

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
| `autofsm_unit_test.py` | elab | scheduler/codegen internals: binding, one-op-per-unit-per-state, dependency order, register allocation, budget → states, floors, determinism, schedule is carryable data |
| `self_check_autofsm_test.py` | native_sim, vhdl_sim, synth ×2 | the FSM computes what the function did — in native sim, in GHDL, at latency 0 and at real latency |
| `autofsm_latency_test.py` | synth | end-to-end schedule; the generated VHDL instantiates exactly as many copies of each shared unit as the schedule claims |
| `autofsm_resources_compare_test.py` | synth | the FSM is actually smaller than the logic it replaces |
| `autofsm_area_sweep_compare_test.py` | synth | the area search does not make designs bigger, and its cost model agrees with yosys about which of two schedules is smaller — the calibration guard |
| `autofsm_max_latency_test.py` | synth | a meetable `max_latency` is met by unsharing; an unmeetable one fails the build naming the latency actually needed |
| `autofsm_timing_iter_test.py` | synth | a critical path inside an FSM is found and fixed by rescheduling |
| `double_parse_file_test.py` | elab | re-parsing an AUTOFSM design is reproducible |

`self_check_autofsm_test.py` is worth copying as a template: it reacts to
`resp.valid` rather than counting cycles, so one source file is correct at every
latency, which is what lets it be reused unchanged across four registrations.

---

## 6. Limitations and future work

**Current limitations**

- One argument (bundle into a struct); one computation in flight; no
  backpressure — `valid` while busy is ignored.
- The function must be pure: no `Reg`, `Feedback` or global wires anywhere in
  its subtree. Dynamic (non-constant) array indexing is not supported yet.
- An operation bigger than a state that cannot be decomposed *and* has no
  soft-operator equivalent sets a floor. That is honest — a float64 multiplier
  is not divisible by scheduling — but it means the clock goal must be reachable
  by the slowest single operation.
- Control overhead grows with the number of folded operations, because the
  operand multiplexers do. At tens of operations this is a clear win; at
  thousands the multiplexers would dominate (see "loop-preserving FSMs" below).
- The area model is a model. It ranks candidates in abstract units calibrated
  against yosys cell counts, which is not the same thing as LUTs on the part you
  are targeting — on an FPGA, flip-flops come paired with the LUTs in front of
  them and are far cheaper than a cell count suggests. The anchor guarantee
  bounds the damage of a mis-ranking to a missed opportunity.

**Future work**

- **Width subsumption in binding.** A 32-bit adder can serve a 16-bit add with
  pad/truncate adapters on its ports; today those are two entities and therefore
  two units. The seams are already in place: `schedule["fus"]` maps unit id →
  entity as an explicit indirection rather than assuming they are the same
  string, per-node operand cast chains are the adapter mechanism, and the area
  model already prices "one bigger unit plus waste" against "two units".
- **Per-node grain**, rather than per-entity. Opening an operation today opens
  every use of it, because every use must stay bound to one unit for sharing to
  mean anything.
- **Soft-operator flavor search.** One fixed flavor per operator today (ripple
  adder, shift-add multiplier, subtract comparator); the library ships several,
  and which one decomposes best is a second search axis.
- **Cross-unit register sharing under a timing model.** Today registers merge
  only within one producing unit, because merging across units puts a
  multiplexer in front of a flip-flop and cost the donut example 5 MHz. With a
  per-path timing estimate the safe cases could be taken.
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
