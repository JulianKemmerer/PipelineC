# AUTO_COMB_AREA_OPT / AUTO_COMB_DELAY_OPT: zero-cycle combinational HLS

`AUTO_COMB_AREA_OPT(func)` and `AUTO_COMB_DELAY_OPT(func)` reimplement a pure
`@hw_func` as a different, bit-exact, purely combinational function. Neither adds
registers, clock cycles, scheduling states or timing exceptions. They differ only
in the objective:

| Tag | Objective | Allowed to grow |
|---|---|---|
| `AUTO_COMB_AREA_OPT` | lower estimated combinational area | propagation delay, fanout |
| `AUTO_COMB_DELAY_OPT` | lower estimated input-to-output critical-path delay | area (no area budget or penalty) |

Both are experimental, bounded searches. Neither promises a global optimum, a
smaller vendor-mapped area, or faster post-route hardware.

- Implementation: [`src/AUTO_COMB_OPT.py`](../src/AUTO_COMB_OPT.py) (purity check,
  candidate preparation, emission, per-build pinning, reports), on top of the shared
  typed-graph search, area model and timing model in [`src/AUTO.py`](../src/AUTO.py)
  (see [`AUTO_DESIGN.md`](AUTO_DESIGN.md)).
- Tag classes in [`src/pypeline.py`](../src/pypeline.py); the elaborator hook in
  [`src/PY_TO_LOGIC.py`](../src/PY_TO_LOGIC.py).

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section rather
> than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

---

## 1. Contract and composition

```python
area = AUTO_COMB_AREA_OPT(my_comb_func)
delay = AUTO_COMB_DELAY_OPT(my_comb_func)
y = area(x)                           # same types and bits; zero added cycles
ap = AUTO_PIPELINE(area)              # insert registers into the reduced graph
ap2 = AUTO_PIPELINE(delay)            # ...or into the shallower one
fsm = AUTO_FSM(my_comb_func)          # considers both objectives' rewrites by default
```

Each tag exposes `.func` and `.latency == 0`, and preserves the function's annotated
signature; multiple input arguments are allowed. Construct tags outside a hardware
body, at module/factory level. Rewrapping with the same tag is idempotent. Mixed
nesting applies inside out: `AUTO_COMB_DELAY_OPT(AUTO_COMB_AREA_OPT(f))` is not
cancelled or unwrapped to `f`. `AUTO_PIPELINE` never requests either objective
implicitly.

The pipeline, FSM and multi-cycle stream factories accept a tag wherever they accept
a pure function; those wrappers still require one input argument (use a struct).
`AUTO_MULTI_CYCLE` tags registers, not a function: use
`make_stream_auto_multi_cycle(tag, ...)` or place `tag(...)` between MCP registers.
MCP timing constraints retain their Vivado requirement.

| Resource allocation | 0 added cycles | N cycles |
|---|---|---|
| Parallel / unsharing | Original; `AUTO_COMB_DELAY_OPT` | `AUTO_PIPELINE`, `AUTO_MULTI_CYCLE`; optionally after DELAY_OPT |
| Sharing transformation | `AUTO_COMB_AREA_OPT` | `AUTO_FSM`; AREA_OPT followed by pipeline/MCP |

Pipeline insertion and MCP both divide the time axis — one inserts registers, the
other widens the permitted settling interval. Neither inherently shares hardware.
The two combinational objectives change the resource/time trade-off *within* one
combinational evaluation; FSMs combine resource sharing with temporal scheduling.
Throughput, buffering, and physical placement/fanout are further, independent
choices.

**Purity.** Before optimization, the subtree is checked recursively: registers,
feedback, global wires and temporal AUTO calls are rejected
(`AUTO_COMB_OPT.check_pure`, raising `AUTO.AutoError` with an `AUTO_COMB_OPT:`
prefix). Raw VHDL is rejected because its purity cannot be established. An
unsupported decoded operation, or a scoped operator implementation anywhere in the
call tree, retains the original graph with a diagnostic — flattening a callable
must not discard an inherited operator scope. This conservative fallback is
distinct from accepting stateful input.

## 2. Architecture

| Component | Responsibility |
|---|---|
| `src/pypeline.py` | Lightweight callable tags, annotations, identity and native forwarding. `AUTO_COMB_DELAY_OPT` subclasses `AUTO_COMB_AREA_OPT` for signature forwarding and zero latency, but has its own pragma flag and canonical identity. |
| `src/PY_TO_LOGIC.py` | Recognizes either tag during live-call elaboration (before source unwrapping) and substitutes the selected callable via `AUTO_COMB_OPT.BUILD_FUNC`; one tag-to-entity map (`parser_state.pypeline_comb_opt_tag_entities`) serves both. |
| `src/AUTO_COMB_OPT.py` | Purity, candidate preparation (`prepare(..., objective="area"\|"delay")`), `CombEmitter`, per-build pinning, reports. |
| `src/AUTO.py` | Typed combinational DAG decoding (`BUILD_DAG`), candidate generation, predicate proofs, bounded search, delay rewrites, area model, read-only timing snapshots, and the `_GraphCodegen` emission base. See [`AUTO_DESIGN.md`](AUTO_DESIGN.md). |
| `include/pypeline/operators/comb_opt.py` | Exact unsigned integer implementation alternatives used as seeds. |
| `src/AUTO_FSM.py` | FSM scoring of the prepared candidates. |

`PY_TO_LOGIC` checks `_is_auto_comb_delay_opt_pragma` **before**
`_is_auto_comb_area_opt_pragma`: the subclass inherits the base attribute.

The DAG is the shared AUTO representation: operations, input/constant/node
references, input port types, result types and **ordered edge cast chains**.
Synthetic literal and wiring nodes support the rewrites. Reachability pruning and
topological validation remove dead alternatives and reject combinational cycles.
Typed CSE includes commutative matching only for supported integer operators with
compatible ports.

`CombEmitter` derives from `AUTO._GraphCodegen` — the typed operand/glue emitter
the FSM codegen also uses — without any scheduler, register or state machinery. It
emits a local for each topologically ordered node, keeping truncation and sign
extension at the original boundaries. Generated functions are ordinary `@hw_func`s
(named `auto_comb_area_opt_<hash>` / `auto_comb_delay_opt_<hash>`), re-elaborated
into ordinary `Logic`; pipeline placement can therefore see inside them, and no
C-to-VHDL primitive is involved. Compiler-generated primitive helpers carry isolated
operator scopes (`operators.comb_opt._primitive_math`), so an inferred operation at
a new width cannot accidentally invoke a user's custom operator.

FSM operand-equivalence keys preserve shared subexpressions as a DAG, with memoized
traversal, cached hashing and iterative structural equality; hash collisions still
require an exact comparison. Input-storage and output-pack reachability share
visited sets, and per-state input visitation prevents reconvergent carry-save glue
from expanding as paths. Primitive-only generated helpers can be safely opened
across nested objectives.

**Candidate preparation and pinning.** The original function is always candidate
zero. `prepare` materializes candidates once per parser state, in separate tables
per objective (`pypeline_comb_area_opt_candidates`,
`pypeline_comb_delay_opt_candidates`); common helper seeds are materialized once
(`pypeline_hls_seeds`). A process-local plan cache (`_PLANS`) stores only plain
graphs, scores, reports and (for delay) a timing snapshot — never live callables or
type objects. Its key covers the objective, source/dependency structure,
`AUTO.GRAPH_VERSION`, `AUTO.TIMING_VERSION`, target tool/part/library and
`AUTO.FORCE_ABSTRACT_AREA`. The pinned plan keeps the choice stable while timing
measurements accumulate during re-elaboration, so timing-cache warming cannot
silently change the circuit being placed. A fresh build can choose differently
with different area or timing information.

## 3. Area objective

**Acceptance.** Only strictly lower estimated area replaces the original, with
deterministic tie-breaking. Delay is not a constraint. Area uses the shared entity
area estimates and mux-bank costs (see [`AUTO_DESIGN.md`](AUTO_DESIGN.md)); known
wiring is free, unresolved operators are not. Cached measured area is used where
the selected model provides it, with explicit estimated fallbacks otherwise.

**Search moves** (composable):

- **Exclusive functional-unit sharing.** Replace multiple equal-signature units
  with one unit and operand muxes. Demand is propagated backward from every output
  and consumer, not inferred from one output mux alone. A bounded reduced ordered
  BDD proves that demands do not overlap. It understands one-bit Boolean logic and
  compatible unsigned equality/inequality-to-constant predicates up to 64 bits;
  other conditions are independent opaque atoms. Unknown exclusivity never
  authorizes sharing. Selector dependencies must remain acyclic.
- **Mux and Boolean factoring.** Move a mux through identical pure operations or
  wiring structure; remove duplicate choices. Outside consumers remain live and
  their area is charged. Distributive bitwise factoring and typed CSE can expose
  further common work.
- **Modular arithmetic factoring.** Factor repeated products such as `x*a + x*b`
  only when product-to-sum edges preserve the demanded unsigned low bits. Operand
  casts are replayed before widening; the factored sum keeps its carry bit up to the
  demanded width. Integer promotion does not justify dropping an intermediate
  product truncation. Signed and floating-point reassociation is excluded.
- **Constant arithmetic.** Signed-digit shift/add/subtract networks for unsigned
  constant multiplication, and shift/mask forms of unsigned power-of-two
  division/remainder. Zero divisors are not strength-reduced; signed intermediate
  constant casts are retained conservatively.
- **Demanded/known-bit narrowing.** Propagate required low bits backward across
  supported modular operators, combining demands from all consumers; conservative
  forward unsigned bounds identify unused upper operand bits. Full width is
  retained across unknown operations or signed boundaries.
- **Hierarchy and soft-operator decomposition.** Open regenerable pure helpers and
  the exact soft equivalents to expose CSE and sharing below call boundaries.
  Opening both DIV and MOD exposes their common restoring arithmetic. Opening is a
  candidate, never a mandatory preprocessing step.

Simultaneously demanded independent outputs cannot time-multiplex one functional
unit in a zero-cycle circuit, and a serial chain cannot reuse a physical unit
without storage or a combinational loop; the area objective attempts neither.

## 4. Delay objective

**Acceptance.** The original is retained unless an emitted candidate has
**strictly lower estimated delay**; area breaks ties between improving candidates.
It does not stop at the enclosing clock goal. "Unbounded area" describes the
objective, not unbounded compiler work.

**Timing model.** Graph timing uses longest dependency paths: serial operations add
delay, parallel branches take their maximum. Python hierarchy is recursively decoded
and retains input-to-output arcs, including unused inputs and internally
constant-driven paths; distinct child entity delays are **not** summed. Primitive
timing prefers live/cached combinational timing components; legacy cache entries and
live measurements without components are labelled total-delay proxies. Missing
measurements use the shared width and mux heuristics; only known wiring is free, and
unresolved entities are errors. Estimates use backend delay units (ten units/ns).
Scalar primitive arcs remain conservative: this is not bit-level STA or a
placement/fanout model.

Selection never launches extra synthesis jobs. Each emitted candidate is
re-elaborated and scored as the *actual* emitted graph, including casts and helper
structure (`AUTO.TimingModel.report`). Snapshots include newly materialized
candidate entities and stay pinned across reparses. Downstream builds may measure
the chosen implementation, but those measurements do not reshuffle the choice in
the current pipeline/FSM reparse loop.

**Candidate families:**

- **Correlated speculation:** `F(mux(s,a,b))` becomes `mux(s,F(a),F(b))`. Operands
  with the same selector are expanded together, never as independent choices.
  Selector and branch casts are replayed. Only total integer primitives are
  eligible; calls, division/remainder and variable shifts are not speculated into
  previously unselected inputs.
- **Distributive expansion:** modular unsigned multiplication over addition, and
  the valid Boolean distributive identities. Every intermediate boundary must
  retain all demanded bits.
- **Balanced reductions:** unsigned addition and associative bitwise trees.
  Low-bit demand accounts for all consumers; leaves retain their casts; signed and
  floating-point reassociation is excluded.
- **Carry-save sums:** a three-operand sum can use XOR/majority reduction and one
  carry-propagating addition instead of two, typed modulo the demanded width.
- **Operator alternatives:** existing carry-select adders, prefix comparators,
  shift/add multiplier trees and Karatsuba decomposition. Their names do not imply
  a win: their actual graphs are scored against the incumbent.
- **Shared cleanup and area rewrites:** typed CSE, constant arithmetic,
  demanded/known-bit narrowing, helper opening and mux factoring remain available
  as seeds/cleanup when they also improve delay.

Pure fanout-only cloning is deliberately not implemented: the scalar model cannot
price its benefit, and ordinary backend CSE would merge identical copies.
Speculative branches have different operands and survive lowering without global
`dont_touch` constraints.

## 5. Search limits

The shared `AUTO` search is bounded by 4,096 graph nodes, 96 distinct candidates,
eight rounds, beam width four and 8,192 BDD nodes; pair checks are bounded too. At
most eight non-original graphs are emitted, preserving distinct rewrite families as
well as low-cost choices. The delay families add: reduction flattening up to 64
leaves; operator alternatives up to 16 shapes and 64 bits; carry-save seeds up to
16 reductions. These are compiler-work limits, not resource budgets; hits are
reported, and raising a limit never relaxes a semantic check.

## 6. FSM integration

Default `AUTO_FSM(func)` prepares the same candidates without requiring a tag: the
area objective's alternatives plus up to two delay-ranked finalists (the first
three delay-table entries, the first of which is the original). Each eligible candidate goes through the FSM's scheduling/binding search
and is compared by **total scheduled area** — units, operand/writeback muxes,
input/intermediate/output registers and control — with timing and latency caps as
hard constraints. The original scheduled design remains the incumbent; a smaller or
faster combinational graph is not assumed to make a smaller FSM. Expanded candidates
exceeding `max(128, 4 * incumbent node count)` are skipped; the FSM's own OPEN search
remains available. Forced schedules and `--auto_fsm_no_area_sweep` keep their
override semantics. FSM schedule summaries report the considered candidates
(`comb_opt_candidates`) and winning moves (`comb_opt_moves`).

`AUTO_FSM(tag)` instead starts from the explicitly selected graph; pass the original
function for the broadest joint search. The large-fold notice is a latency/search-
size advisory, not a timing failure.

## 7. Stream wrappers and simulation

```python
from stream.stream_auto_comb_area_opt import make_stream_auto_comb_area_opt
from stream.stream_auto_comb_delay_opt import make_stream_auto_comb_delay_opt

stream, stream_t = make_stream_auto_comb_area_opt(func_or_tag)
```

Both factories return the usual function/result-type pair and share one elastic
shell (`_make_stream_auto_comb`, generated function `stream_auto_comb_opt`). Ports
are `stream.in_fwd_t` / `stream.out_fb_t`; the result contains `stream_in_if` and
`stream_out_if`. The function exposes the interface objects and `.comb_opt` (the
tag).

```text
input stream -> elastic input register -> optimized core -> elastic output register -> output stream
```

Both data/valid boundaries are registered: unstalled latency is **two cycles**,
initiation interval is **one**, with two storage slots. Downstream stalls hold
output data/valid and eventually deassert input ready. The ready path is
combinational occupancy logic and never traverses the computation. Output transfer,
internal advance and input acceptance may occur on the same cycle. The core is not
internally pipelined; if it is too slow for the clock goal, use a pipeline or MCP
wrapper around the tag instead.

Plain native simulation calls the original function and does not import the
optimizer; there is no state model or latency cache for these tags in
`pypeline_sim.py`. The shell is ordinary register/handshake code, and composed
pipelines and FSMs use their existing latency/schedule simulation — the bit-exact
contract makes native forwarding valid.

## 8. Reports and tests

`SYN.WRITE_FINAL_FILES` calls `AUTO_COMB_OPT.DUMP_GENERATED_SOURCE`, which writes:

- `auto_comb_area_opt_report.json` / `auto_comb_delay_opt_report.json` for explicit
  tags: area before/after, units, measured/estimated coverage, moves, candidate
  count and limits; the delay report adds delay before/after, units, critical-path
  nodes and timing provenance/snapshot.
- `auto_comb_opt_generated/*.py`: generated source for every prepared alternative of
  either objective, including those prepared only for FSMs. The sources use injected
  callable/type names for inspection; they are not importable replacement modules.

Tests in `src/tests/pypeline_tests/inst/`:

- `auto_comb_area_opt_test.py`: API, candidate semantics, predicates, multiple
  consumers, signed casts, arithmetic choices, custom narrow operators, purity,
  scoped fallback, deep DAGs, repeat-parse determinism and default FSM access to the
  candidates without regressing its scheduled-area incumbent; shared-glue key
  traversal and exact comparison despite hash collisions.
- `auto_comb_delay_opt_test.py`: native isolation, timing dependencies, candidate
  equivalence, casts, arithmetic families, nesting, purity and repeated parses.
- `auto_comb_area_opt_build_test.py` / `auto_comb_delay_opt_build_test.py`: Yosys
  SAT equivalence of the selected design for all inputs, absence of
  flip-flops/latches in the core, and independent mapped-cell (area) or sky130
  timing (delay) comparison of both variants. These builds are validation, not part
  of selection.
- `self_check_stream_auto_comb_area_opt_test.py` /
  `self_check_stream_auto_comb_delay_opt_test.py`: exact two-cycle latency, II=1,
  bubbles, backpressure and data stability, native vs GHDL.
- `self_check_auto_comb_area_opt_composition_test.py` /
  `self_check_auto_comb_delay_opt_composition_test.py`: fixed/discovered pipelines
  and raw-function/default and explicit-tag FSMs, compared against independent
  expected results in native and GHDL simulation. The pipelined builds run under
  `--syn_tool pyrtl`. There is no MCP member: MULTI_CYCLE constraints need Vivado.

A deterministic diamond-graph regression bounds node accesses of the FSM's
input-storage analysis instead of relying on a stopwatch.

```sh
python3 src/tests/pypeline_tests/run_all.py -k auto_comb -j 4
```

## History

### Why reconvergent glue walks use visited sets

Profiling `qor_multiplier_auto_fsm_test` showed input-storage analysis expanding
reconvergent carry-save glue as paths — tens of millions of visits. Input-storage
analysis now uses an iterative visited set per state, related reachability walks
share visited sets, and operand-equivalence memoization is reused across one
functional unit's ports and factoring recursion (never across mutable schedules).

### Why the tags are named by objective

The tags were first named `AUTO_COMB_SHARE` / `AUTO_COMB_UNSHARE`, after the
mechanism of the first area moves. Both objectives use many moves that are not
sharing (narrowing, constant arithmetic, speculation, balancing), so they are named
by what they optimize.
