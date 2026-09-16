# AUTO_COMB_UNSHARE: delay-first combinational HLS

`AUTO_COMB_UNSHARE(func)` returns a bit-exact, pure combinational callable with
the original signature, `.func`, and `.latency == 0`. It seeks lower estimated
input-to-output critical-path delay, allowing area growth without an area
budget or penalty. It does not stop at the enclosing clock goal. There are no
inserted registers, scheduling states, or timing exceptions in the core.

```python
acu = AUTO_COMB_UNSHARE(my_comb_func)
y = acu(x)
ap = AUTO_PIPELINE(acu)
```

The original is retained unless an emitted candidate has **strictly lower
estimated delay**. Area breaks ties between improving candidates. Neither a
global minimum nor faster post-route hardware is guaranteed. Search work is
bounded; “unbounded area” describes the objective, not infinite compiler work.

## Time and resource allocation

| Resource allocation | 0 added cycles | N cycles |
|---|---|---|
| Parallel / unsharing | Original; `AUTO_COMB_UNSHARE` | `AUTO_PIPELINE`, MCP; optionally after UNSHARE |
| Sharing | `AUTO_COMB_SHARE` | `AUTO_FSM`; SHARE followed by pipeline/MCP |

Pipelining and MCP both divide the time axis, by registers and timing
constraints respectively. SHARE and UNSHARE change the resource/time tradeoff
*within* a combinational evaluation. Throughput, buffering, and physical
placement/fanout are additional degrees of freedom.

## Shared implementation

This is the delay objective of the existing combinational HLS implementation,
not an independent frontend or backend:

- `pypeline.py` holds both lightweight tags. UNSHARE reuses signature forwarding
  and zero latency, but has a separate pragma flag and canonical identity.
- `PY_TO_LOGIC.py` dispatches both tags to `AUTO_COMB_SHARE.BUILD_FUNC` before
  source unwrapping. The existing tag-to-entity map serves both.
- `AUTO_COMB_SHARE.prepare(..., objective="delay")` shares purity, typed graph
  decoding, helper creation, emission, and area estimation with SHARE/FSM.
  Area and delay candidate tables are separate. Common helper seeds are
  materialized once per parser state.
- `HLS.py` supplies bounded search, typed CSE, pruning and cycle checking.
  `HLS_SPEED.py` supplies delay-oriented rewrites and implementation seeds.
- `HLS_TIMING.py` supplies read-only timing snapshots and dependency analysis.
- Generated functions are ordinary Pypeline. Existing pipeline placement,
  MCP constraints, C-to-VHDL lowering and simulation consume them unchanged.

Ordered edge casts and all outside consumers are retained. Compiler-generated
primitive helpers carry isolated operator scopes, preventing an inferred
operation at a new width from accidentally invoking a user's custom operator.
Unrelated user scopes still retain the original with a diagnostic. Stateful
functions, temporal AUTO calls, global wires and raw VHDL fail the same purity
check as SHARE.

## Timing objective and cache lifetime

Graph timing uses longest dependency paths: serial operations add delay,
parallel branches take their maximum. Python hierarchy is recursively decoded
and retains input-to-output arcs, including unused inputs and internally
constant-driven paths. It does **not** sum distinct child entity delays.

Primitive timing prefers live/cached combinational timing components. Legacy
cache entries and live measurements without components are explicitly labelled
total-delay proxies. Missing measurements use the existing width and mux
heuristics; only known wiring is free. Unresolved entities are errors, not
zero-cost operations. Estimates use the backend delay units (ten units/ns).
Scalar primitive arcs remain conservative: this is not bit-level physical STA
or a placement/fanout model.

Selection never launches extra synthesis jobs. Candidate emission is followed
by re-elaboration and scoring of the actual emitted graph, including casts and
helper structure. Normal downstream builds may independently measure the
chosen implementation, but those measurements do not reshuffle its choice in
the current pipeline/FSM reparse loop.

The process-local plan stores plain graphs, scores and a timing snapshot, not
live functions/types. Its key includes source/dependency shapes, optimizer and
timing-model versions, objective, target tool/part/library and area mode.
Nested wrapper identity includes written order. Snapshots include newly
materialized candidate entities and stay pinned across reparses. A fresh build
may choose differently after the timing cache has changed.

## Candidate families and safety

- **Correlated speculation:** `F(mux(s,a,b))` becomes
  `mux(s,F(a),F(b))`. Operands with the same selector are expanded together,
  never as independent choices. Selector and branch casts are replayed.
  Only total integer primitives are eligible. Calls, division/remainder and
  variable shifts are not speculated into previously unselected inputs.
- **Distributive expansion:** modular unsigned multiplication over addition,
  and the valid Boolean distributive identities. Every intermediate boundary
  must retain all demanded bits; signed or narrowing boundaries that would
  change the result prohibit the move.
- **Balanced reductions:** unsigned addition and associative bitwise trees.
  Low-bit demand accounts for all consumers. Leaves retain their casts;
  signed and floating-point reassociation is excluded.
- **Carry-save sums:** a three-operand sum can use XOR/majority reduction and
  one carry-propagating addition instead of two. The implementation is typed
  modulo the demanded width and is scored after elaboration.
- **Operator alternatives:** existing carry-select adders, prefix comparators,
  shift/add multiplier trees and Karatsuba decomposition. Their names do not
  imply a win: their actual graphs are scored against the incumbent.
- **Shared cleanup and area rewrites:** typed CSE, constant arithmetic,
  demanded/known-bit narrowing, helper opening and mux factoring remain
  available as seeds/cleanup when they also improve delay.

Pure fanout-only cloning is deliberately deferred: the current scalar model
cannot price its benefit, and ordinary backend CSE would merge identical
copies. Specialized speculative branches have different operands and can
survive lowering without global `dont_touch` constraints.

Search uses the shared limits: 96 graph candidates, four beam members, eight
rounds, 4096 graph nodes, and at most eight emitted alternatives plus the
original. Reduction flattening is limited to 64 leaves; operator alternatives
to 16 shapes and widths up to 64 bits; carry-save seeds to 16 reductions.
These are compiler-work limits, not a resource budget. Exhaustion is reported.

## Composition and FSM access

`AUTO_PIPELINE(acu)`, pipeline streams, MCP streams, and `AUTO_FSM(acu)` use the
selected zero-cycle function. MCP keeps its existing target restrictions.
Repeating the same tag is idempotent. Mixed nesting applies inside out:
`AUTO_COMB_UNSHARE(AUTO_COMB_SHARE(f))` is not cancelled or unwrapped to `f`.
AUTO_PIPELINE itself does not automatically request UNSHARE.

Default AUTO_FSM preserves its original and area-oriented candidates and
additionally schedules up to two delay-ranked finalists. Its acceptance
criterion remains **complete scheduled area** (units, muxes, storage and
control), subject to its timing/latency constraints. Thus the same new knobs
are available to FSM optimization without making the delay winner mandatory.

`make_stream_auto_comb_unshare(func)` returns the usual function/result-type
pair. It shares the two-bank elastic implementation with SHARE, exposes `.acu`
and the usual interface attributes, has unstalled latency **2**, and **II=1**.
Backpressure holds data/valid stable; ready propagates through occupancy logic.
The core is not internally pipelined. Use a pipeline/MCP wrapper for that.

Native simulation forwards to the original without importing the optimizer.
There is no new state model in `pypeline_sim.py`; the common elastic shell and
composed temporal wrappers use their existing simulation behavior.

## Diagnostics, testing, and FSM runtime repair

Explicit tags write `auto_comb_unshare_report.json`: delay and area before/after,
units, critical-path nodes, timing provenance/snapshot, moves and search limits.
Generated inspection sources for both objectives remain in
`auto_comb_share_generated/`, with distinct `auto_comb_unshare_*` names. These
sources use injected globals and are not standalone importable modules.

`auto_comb_unshare_test.py` checks native isolation, timing dependencies,
candidate equivalence, casts, arithmetic families, nesting, purity and repeated
parses. Stream/composition fixtures compare native and GHDL behavior, including
stall stability, exact latency/II, fixed/discovered pipelines and FSM (no MCP
member: MULTI_CYCLE constraints need Vivado, and the composition build runs
under `--syn_tool pyrtl`).
`auto_comb_unshare_build_test.py` proves a mux-speculation example with Yosys SAT,
checks that the core has no registers/latches, and separately builds both
variants for sky130 timing. These validation builds are not part of selection.

Profiling `qor_multiplier_auto_fsm_test` found input-storage analysis expanding
reconvergent glue as paths: over 85 million visits in five minutes. It now uses
an iterative visited set per state; related reachability walks share visited
sets too. Operand equivalence memoization is reused across one FU's ports and
factoring recursion, never across mutable schedules. A deterministic diamond-
graph regression bounds node accesses instead of relying on a flaky stopwatch.
The large-fold notice is a latency/search-size advisory, not a timing failure.

The min-area verification keeps its four real builds and 3% tolerance, with
live per-variant `build.log` files and elapsed/status summaries. Its search is
allowed to retain the original; a move is not required. Divider locals no
longer use VHDL's reserved `rem` identifier.

Run targeted regressions with their registered timeouts, then the full suite:

```sh
python3 src/tests/pypeline_tests/run_all.py -t qor_multiplier_auto_fsm_test -j 1
python3 src/tests/pypeline_tests/run_all.py -t auto_fsm_min_area_verify_test -j 1
python3 src/tests/pypeline_tests/run_all.py -j 4 --no_timeout
```
