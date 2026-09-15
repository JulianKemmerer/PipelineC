# AUTO_COMB_SHARE: area-first combinational HLS

`AUTO_COMB_SHARE(func)` implements a pure `@hw_func` with less estimated
combinational area, without introducing registers or clock cycles. It may
increase propagation delay and fanout. This is an experimental, bounded search,
not a proof of globally minimum area or a promise about a vendor's mapped area.

## Contract and composition

```python
acs = AUTO_COMB_SHARE(my_comb_func)
y = acs(x)                         # same types and bits; zero added cycles
ap = AUTO_PIPELINE(acs)             # insert registers into the reduced graph
fsm = AUTO_FSM(my_comb_func)        # considers combinational rewrites by default
```

The tag exposes `.func` and `.latency == 0`. It preserves the function's annotated
signature; multiple input arguments are allowed. Construct it outside a hardware
body, at module/factory level. Rewrapping an ACS tag is idempotent. The pipeline,
FSM and multi-cycle stream factories accept it wherever they accept a pure
function; those wrappers still require one input argument (use a struct).
`AUTO_MULTI_CYCLE` itself tags registers, not a function: use
`make_stream_auto_multi_cycle(acs, ...)` or place `acs(...)` between MCP registers.
MCP timing constraints retain their Vivado requirement.

| Resource allocation | 0 added cycles | N cycles |
|---|---|---|
| No sharing transformation | Original combinational function | `AUTO_PIPELINE`, `AUTO_MULTI_CYCLE` |
| Sharing transformation | `AUTO_COMB_SHARE` | `AUTO_FSM`; ACS followed by pipeline/MCP |

Both pipeline insertion and MCP divide computation temporally: one inserts
registers, the other changes the permitted settling interval. Neither inherently
shares the combinational hardware. ACS addresses spatial resource use; FSMs
combine resource sharing with temporal scheduling. Throughput, buffering and
timing targets are additional choices, not implied by these two axes.

Purity is checked recursively before optimization: registers, feedback, global
wires and temporal AUTO calls are rejected. Raw VHDL is rejected because its
purity cannot be established. An unsupported decoded operation or a scoped
operator implementation retains the original graph with a diagnostic. In
particular, flattening a callable must not discard an inherited operator scope.
This conservative fallback is distinct from accepting stateful input.

## Shared architecture

| Component | Responsibility |
|---|---|
| `src/pypeline.py` | Lightweight callable tag, annotations, identity and native forwarding |
| `src/PY_TO_LOGIC.py` | Recognize ACS during live-call elaboration and substitute its selected callable |
| `src/HLS.py` | Typed combinational DAG candidates, predicate proofs, rewrites, bounded area search |
| `src/AUTO_COMB_SHARE.py` | Purity, candidate preparation, emission, per-build pinning and reports |
| `include/pypeline/operators/comb_share.py` | Exact unsigned integer implementation alternatives |
| `src/AUTO_FSM.py` | Shared DAG decoding, casts, type resolution, soft equivalents, area model and FSM scoring |

The DAG uses the existing FSM representation: operations, input/constant/node
references, input port types, result types and **ordered edge cast chains**.
Synthetic literal and wiring nodes support the rewrites. Reachability pruning
and topological validation remove dead alternatives and reject combinational
cycles. Typed CSE includes commutative matching only for supported integer
operators with compatible ports.

`CombEmitter` reuses the FSM's typed operand/glue emitter without its scheduler,
registers or state. It emits a local for each topologically ordered node, keeping
truncation and sign extension at the original boundaries. Generated functions
are ordinary `@hw_func`s, re-elaborated into ordinary `Logic`; pipeline placement
can therefore see inside them. No ACS-specific C-to-VHDL primitive is required.

FSM operand-equivalence keys preserve shared subexpressions as a DAG, with
memoized traversal, cached hashing and iterative structural equality. Hash
collisions still require an exact comparison. This keeps heavily shared glue
from expanding into exponentially repeated work during candidate scoring.

The original function is always candidate zero. `prepare` materializes candidates
once per parser state. A process-local plan cache stores only plain graphs,
scores and reports, keyed by source/dependency structure, optimizer version and
area-model selection. It pins the candidate choice while timing measurements
accumulate during re-elaboration. Helpers are recreated in each parser state;
live callables and type objects never cross parser-state boundaries in this
cache. A fresh build can choose differently with different area information.

## Optimization choices

- **Exclusive functional-unit sharing.** Replace multiple equal-signature units
  with one unit and operand muxes. Demand is propagated backward from every
  output and consumer, not inferred from one output mux alone. A bounded reduced
  ordered BDD proves that demands do not overlap. It understands one-bit Boolean
  logic and compatible unsigned equality/inequality-to-constant predicates up to
  64 bits; other conditions are independent opaque atoms. Unknown exclusivity
  never authorizes sharing. Selector dependencies must remain acyclic.
- **Mux and Boolean factoring.** Move a mux through identical pure operations or
  wiring structure; remove duplicate choices. Outside consumers remain live and
  their area is charged. Distributive bitwise factoring and typed CSE can expose
  further common work.
- **Modular arithmetic factoring.** Factor repeated products such as
  `x*a + x*b` only when product-to-sum edges preserve the demanded unsigned
  low bits. Operand casts are replayed before widening; the factored sum keeps
  its carry bit up to the demanded width. Narrow operands can therefore share
  a multiplier even when the result is wider. Integer promotion does not
  justify dropping an intermediate product truncation. Signed and
  floating-point algebraic reassociation is excluded.
- **Constant arithmetic.** Consider signed-digit shift/add/subtract networks for
  unsigned constant multiplication and shift/mask implementations of unsigned
  power-of-two division/remainder. Zero divisors are not strength-reduced;
  signed intermediate constant casts are retained conservatively, including
  their sign extension before a wider unsigned operation or comparison.
- **Demanded/known-bit narrowing.** Propagate required low bits backward across
  supported modular operators, combining demands from all consumers. Conservative
  forward unsigned bounds identify unused upper operand bits. Retain full width
  across unknown operations or signed boundaries. Replacement helpers implement
  compiler primitives with scoped inferred arithmetic, so a custom operator at
  the narrower width cannot change their meaning.
- **Hierarchy and soft-operator decomposition.** Open regenerable pure helpers
  and the FSM's exact soft equivalents to expose CSE and sharing below call
  boundaries. Division and remainder can expose common restoring arithmetic.
  Existing signedness and oversized-shift safeguards still apply. Opening is a
  candidate, never a mandatory preprocessing step.

These are composable search moves. Simultaneously demanded independent outputs
cannot simply time-multiplex one functional unit in a zero-cycle circuit. A
serial chain cannot reuse a physical unit without storage or a combinational
loop; ACS does not attempt either.

## Objective, limits and FSM integration

ACS uses the FSM's entity-area estimates and mux-bank costs; known wiring is
free, unresolved operators are not. Cached measured area is used where the
selected model provides it, with explicit estimated fallbacks otherwise. Delay
is not an acceptance constraint. Only strictly lower estimated area replaces
the original, with deterministic tie-breaking between alternatives.

`HLS` bounds search by 4,096 graph nodes, 96 distinct candidates, eight rounds,
beam width four and 8,192 BDD nodes. Pair checks are also bounded. At most eight
non-original graphs are emitted, preserving distinct rewrite families as well
as low-area choices. Limit hits are reported; increasing a limit does not relax
semantic checks. This is an area-first heuristic, not exhaustive minimization.

Default `AUTO_FSM(func)` prepares the same candidates without requiring an ACS
tag. Each eligible candidate goes through the existing scheduling/binding search
and is compared by **total FSM area**, including input/intermediate/output
registers, operand/writeback muxes and control logic. Timing and latency caps
remain hard constraints. The original scheduled design remains an incumbent;
a smaller combinational graph is not assumed to make a smaller FSM. The extra
search skips expanded candidates exceeding `max(128, 4 * incumbent node count)`;
the FSM's existing OPEN search remains available. Explicit forced schedules and
`--auto_fsm_no_area_sweep` retain their override semantics.

`AUTO_FSM(acs)` instead starts with the explicitly selected combinational graph.
For the broadest default joint search, pass the original function directly.

## Stream wrapper and simulation

```python
from stream.stream_auto_comb_share import make_stream_auto_comb_share

stream, stream_t = make_stream_auto_comb_share(acs)
```

The wrapper returns the usual function/result-type pair. Its ports are
`stream.in_fwd_t`, `stream.out_fb_t`, and its result contains `stream_in_if`
and `stream_out_if`. It exposes the corresponding interface objects and `.acs`.

```text
input stream -> elastic input register -> ACS -> elastic output register -> output stream
```

Both data/valid boundaries are registered: unstalled latency is **two cycles**,
initiation interval is **one**, and there are two storage slots. Downstream
stalls hold output data/valid and eventually deassert input ready. The ready
path is combinational occupancy logic; it does not traverse the user's
computation. Output transfer, internal advance and input acceptance may occur
on the same cycle. This wrapper does not automatically meet a clock goal if
the shared core is too slow; choose a pipeline or MCP wrapper around ACS then.

Plain native simulation calls the original function and does not import the
optimizer. There is no ACS state model or latency cache in `pypeline_sim.py`.
The wrapper is ordinary register/handshake code. Composed pipelines and FSMs
use their existing latency/schedule simulation; the optimized function's
bit-exact contract makes native forwarding valid.

## Reports and tests

Build output contains `auto_comb_share_report.json` for explicit ACS tags and
`auto_comb_share_generated/*.py` for prepared alternatives (including those
prepared for FSMs). Generated source uses injected callable/type names for
inspection; it is not a standalone importable replacement module. Reports
include area before/after, units, measured/estimated coverage, moves, candidate
count and limits. FSM schedule summaries report considered combinational
candidates and the winning moves.

Tests in `src/tests/pypeline_tests/inst/`:

- `auto_comb_share_test.py`: API, candidate semantics, predicates, multiple
  consumers, signed casts, arithmetic choices, custom narrow operators, purity,
  scoped fallback, deep DAGs, repeat-parse determinism and default FSM access to
  shared candidates without regressing its original scheduled-area incumbent;
  shared-glue key traversal and exact comparison despite hash collisions.
- `auto_comb_share_build_test.py`: Yosys SAT equivalence of the selected two-
  multiplier mux design for all inputs; independent mapped-cell comparison and
  absence of flip-flops/latches in the transformed core.
- `self_check_stream_auto_comb_share_test.py`: exact two-cycle latency, II=1,
  bubbles, backpressure and data stability, with native/GHDL comparison.
- `self_check_auto_comb_share_composition_test.py`: fixed/discovered pipelines,
  raw-function/default and explicit-ACS FSMs, and MCP streams, compared against
  independent expected results in native and GHDL simulation. Payloads are
  also exported as hardware outputs so synthesis retains the tested datapaths
  and MCP capture registers.

Run the entire registered suite with no timeout:

```sh
python3 src/tests/pypeline_tests/run_all.py -j 4 --no_timeout
```
