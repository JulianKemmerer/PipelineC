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

`max_latency=` is reserved for the planned "don't trade all the latency for
area" cap and currently raises `NotImplementedError` rather than being silently
ignored.

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

Descent only enters entities with a recorded live Python callable — i.e. things
that came from Python source that can be regenerated. A built-in operator
entity is atomic no matter how slow, because its innards are the C/VHDL support
library, not Python. Descent is also **best-effort**: a body that cannot be
regenerated falls back to keeping the operation atomic (reported as a floor),
rather than failing the build.

`_trace_operand` also records the **cast chain**: every intermediate wire type
between producer and consumer. Assigning a wire narrows to the destination's
width, so a value that passed through a narrower variable in the original code
must pass through the same narrowing in the FSM, or the FSM would compute
something the pure function does not.

### 3.2 Scheduling and binding

`SCHEDULE_DAG` is a list scheduler. Per state, it walks the ready operations in
longest-remaining-chain order and places one if:

1. **its unit is free this state** — one operation per unit per state;
2. **the chain still fits the budget** —
   `chain_start + delay + MUX_PENALTY_DU ≤ budget_du`, where
   `budget_du = period_ns × 10 × budget_scale`;
3. **the units' emission order stays acyclic** — generated source declares units
   in a fixed order, so if unit A feeds unit B in one state, B can never feed A
   in another.

If nothing at all fits an empty state, the cheapest ready operation is forced in
alone and the schedule is flagged **`at_floor`**: one indivisible operation that
no number of extra states can speed up. The driver stops tightening when it sees
this, instead of looping to its pass cap.

Constants: `DEFAULT_BUDGET_SCALE = 0.9` (the delay model does not account for the
multiplexers sharing adds, so leave headroom), `MUX_PENALTY_DU = 10` (1.0 ns
charged per operation for its operand mux and writeback enable),
`BUDGET_TIGHTEN_FACTOR = 0.75`, `MAX_SCHEDULE_PASSES = 4`. Override the starting
budget with `--autofsm_budget_scale`.

Determinism is load-bearing: node ids come from source coordinates, ties break
on node id, and the schedule is a pure function of (Logic graphs, delays,
budget_scale). Independence from the surrounding design is what makes the
driver's loop converge trivially — only an explicit tightening can change the
answer, so there is no fixed-point search.

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

---

## 4. Results

Measured on this repo with the PYRTL/yosys flow (`src/tests/pypeline_tests/inst/`
and `examples/pypeline/`):

| design | operations | shared units | states | latency |
|---|---|---|---|---|
| `autofsm_resources_test.py` — 6 multiplies + 5 adds | 11 | **2** | 6 | 7 |
| `autofsm_donut_update.py` — donut per-frame rotation | 28 | **9** | 8 | 9 |
| `float_sine_autofsm.py` — float64 degree-5 Horner | 19 | **4** | 16 | 17 |

Area, same design built both ways (yosys cell count, whole-design top):

```
combinational (--comb, no sharing):    12117 cells
resource-shared FSM              :      3605 cells      3.36x smaller
```

Timing iteration, starting from a deliberately over-packed schedule
(`--autofsm_budget_scale 1.5`): first build 33.03 MHz vs a 40 MHz goal (FAIL) →
budget tightened → 44.23 MHz (PASS), with no source change.

---

## 5. Tests

| test | category | what it proves |
|---|---|---|
| `autofsm_test.py` | native_sim, (synth via wrapper) | the pure function's semantics, and the passthrough behaviour when unscheduled |
| `autofsm_unit_test.py` | elab | scheduler/codegen internals: binding, one-op-per-unit-per-state, dependency order, register allocation, budget → states, floors, determinism, schedule is carryable data |
| `self_check_autofsm_test.py` | native_sim, vhdl_sim, synth ×2 | the FSM computes what the function did — in native sim, in GHDL, at latency 0 and at real latency |
| `autofsm_latency_test.py` | synth | end-to-end schedule; exactly ONE instance of each shared unit in the generated VHDL |
| `autofsm_resources_compare_test.py` | synth | the FSM is actually smaller than the logic it replaces |
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
- Share-all binding: exactly one unit per entity. There is no knob to keep two
  adders for speed.
- An operation bigger than a state that cannot be decomposed sets a floor. That
  is honest — a float64 multiplier is not divisible by scheduling — but it means
  the clock goal must be reachable by the slowest single operation.
- Control overhead grows with the number of folded operations, because the
  operand multiplexers do. At tens of operations this is a clear win; at
  thousands the multiplexers would dominate (see "loop-preserving FSMs" below).

**Future work**

- **`max_latency`**: cap the latency instead of always minimizing area. The
  scheduler already takes a budget; this needs the inverse search (fewest units
  that fit a latency bound) plus a real pinning mechanism.
- **Multiple concurrent AUTOFSM threads sharing units.** Two FSMs that both need
  a float multiplier could share one, with arbitration. The binding step already
  keys on entity, so the scheduler generalizes; what is missing is the arbiter
  and a cross-FSM resource model.
- **K units per entity**, so a design can buy back speed with area between the
  current "one unit" and full parallelism.
- **Register sharing.** Values with disjoint live ranges could share a register
  (classic left-edge allocation); today each cross-state value gets its own.
- **Loop-preserving FSMs.** v1 schedules the *unrolled* graph, so control logic
  grows with the folded-operation count. The fix is real loop back-edges:
  schedule the body once, add an index register, and index operands from arrays.
  A user-facing sequential/`__clk()`-style layer for Pypeline would be the
  natural emission target for that — but note the dependency direction: such a
  layer does **not** help v1, because per-state code regions would create one
  instance per call site and defeat the single-call-site sharing trick. v1's
  emission helpers are reusable substrate for building it later, not the other
  way round.
