# AUTO: machinery shared by the AUTO features

[`src/AUTO.py`](../src/AUTO.py) holds what more than one AUTO feature needs:
the typed combinational DAG, the bounded candidate search over it, the delay
and area models used to rank candidates, and the helpers that turn a chosen
graph back into ordinary Pypeline source. Nothing here schedules, pipelines or
synthesizes anything by itself.

| consumer | uses |
|---|---|
| [`AUTO_COMB_AREA_OPT` / `AUTO_COMB_DELAY_OPT`](AUTO_COMB_OPT_DESIGN.md) (`src/AUTO_COMB_OPT.py`) | DAG decoding, search, delay rewrites, timing model, area model, `_GraphCodegen`, `AutoError` |
| [`AUTO_FSM`](AUTO_FSM_DESIGN.md) (`src/AUTO_FSM.py`) | DAG decoding (with descent into slow operations), soft equivalents, type resolution, the delay heuristics and area model its scheduler ranks with, `_Emitter` / `_exec_generated` / `_GraphCodegen`, `AutoError` |
| `src/pipelinec` | sets `FORCE_ABSTRACT_AREA` (`--auto_fsm_abstract_area`) |

The temporal AUTO features' shared machinery — iterating synthesis toward a
timing goal — is [`SWEEP_DESIGN.md`](SWEEP_DESIGN.md); the pipeline
representation is [`AUTO_PIPELINE_DESIGN.md`](AUTO_PIPELINE_DESIGN.md).

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section, if it
> has one, rather than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

---

## 1. The typed combinational DAG

`BUILD_DAG(parser_state, func_entity, delays, budget_du, opened=())` flattens an
elaborated pure function into a dataflow graph:

```python
{
  "nodes": {
    node_id: {                       # op name + source coordinates: a pure
                                     # function of the source, stable across
                                     # re-elaborations
      "kind": "binop" | "unaryop" | "mux" | "call" | "ref" | "assemble"
              | "copy" | "shift" | "bitmanip" | "inlined",
      "op": {...},                   # DECODE_OP's description of the construct
      "entity": "...",               # the elaborated entity it instantiates
      "operands": [ValueRef, ...],   # ["node", id] | ["in", port] | ["const", text]
      "casts": [[ctype, ...], ...],  # per operand: the narrowing/widening chain
                                     # between producer and port, producer first
      "port_types": [ctype, ...],
      "out_type": ctype,
      "delay_du": int,               # tenths of a nanosecond
    }, ...
  },
  "output": ValueRef, "out_type": ctype, "output_casts": [ctype, ...],
}
```

- **Decoding.** `DECODE_OP` works out which Python construct produced each
  elaborated operation, so re-emitting it at the original port types
  reproduces the identical entity and its cached delay. `_trace_operand`
  follows a port back through the wire graph to the value that feeds it and
  records the casts on the way (`_clean_cast_chain` keeps only those that
  change the value). Zero-delay operations — field reads, constant shifts,
  rewiring — are *glue*.
- **Descent.** An operation slower than `budget_du` is opened: its body is
  inlined (`_build_dag_level`, bounded by `_MAX_DESCEND_DEPTH`) and
  `_resolve_inlined` rewires references through the inlined call so every
  consumer sees one flat graph. `opened=` forces entities open regardless of
  delay; AUTO_COMB_OPT uses it for its hierarchy and soft-operator
  decomposition seeds. Only operations that came from Python source can be
  opened (`_is_decomposable`); a built-in operator is opened through its soft
  equivalent (`_open_target`).
- **Soft equivalents.** `PREPARE_SOFT_EQUIVALENTS` elaborates, on the bootstrap
  pass, a decomposable Pypeline implementation of each built-in operator
  (`_SOFT_FACTORY_FOR_OP`, `_soft_equivalent_callable`), uninstantiated, so a
  search has something to descend into. `_RESOLVE_BUILTIN_SUBMODULES`
  materializes the `Logic` of built-in operators inside such a candidate
  subtree.
- **Types.** The graph carries C type *names*. `_TypeResolver` maps them back
  to live pypeline types for generated annotations, seeded from every callable
  in the subtree (`_subtree_entities`); `_ctype_width` prices a type by bit
  width, summing struct fields recorded by `_seed_struct_widths`.

## 2. Graph utilities and the candidate search

`order` (topological order, rejecting any combinational cycle, including one
introduced by a selector), `prune`, `replace`, `add_node`, `mux`, `cast` and
`common_expressions` (typed CSE, with commutative matching only where operator
and port types allow it) operate on plain JSON-like graphs; `fingerprint`
hashes one. `_demanded_bits` propagates the low bits every consumer needs
backward through modular operators.

`search(dag, parser_state, seeds=(), timing=None)` is a bounded beam search:

| budget | value |
|---|---|
| `MAX_NODES` | 4,096 graph nodes |
| `MAX_CANDIDATES` | 96 distinct graphs |
| `MAX_ROUNDS` | 8 |
| `BEAM_WIDTH` | 4 |
| `MAX_BDD_NODES` | 8,192 |
| `MAX_EMITTED_CANDIDATES` | 8 (plus the original) |

Each round expands the beam with:

- `share_candidates` — bind mutually exclusive equal-signature operations to one
  unit with operand muxes. `demand_predicates` computes, for each node, the
  condition under which some consumer needs it; the small reduced ordered `BDD`
  proves two demands disjoint (unknown expressions are independent atoms, so
  unknown exclusivity never authorizes sharing).
- `factor_candidates` — move a mux through identical pure operations or wiring.
- `algebra_candidates` — exact distributive factoring in a uniform modular
  width.
- with `timing`: `speculate`, `balanced` and `expand` (§3).

Candidates are ranked by `area(dag, parser_state)` (§4), or by the timing
model's delay first when `timing` is given. Hitting a budget stops the search
and is reported; it never relaxes a semantic check.

## 3. Delay: rewrites, heuristics and the timing model

**Delay rewrites** (used by `AUTO_COMB_DELAY_OPT` and the FSM's delay
finalists): `speculate` moves a common selector after a total integer
primitive, expanding correlated operands together; `balanced` rebalances
modular unsigned sums and associative bitwise trees; `expand` distributes in a
uniform modular ring or Boolean algebra. `delay_implementation_seeds` swaps in
exact library implementations (carry-save sums from
`include/pypeline/operators/comb_opt.py`, carry-select adders, prefix
comparators, shift/add and Karatsuba multipliers) — their graphs are scored,
their names are not trusted.

**Operation delays** (`_resolve_delay_du`), in order of preference: what this
pass measured (or a pinned snapshot), the `Logic`'s own measured delay, the
on-disk path-delay cache (how a never-instantiated descent candidate gets a
real number), then `_heuristic_leaf_delay_du`, a width-based guess only a cold
cache ever sees. `_mux_delay_du` prices an n-way operand mux: measured when the
mux entity exists (`_mux_callable` / `_mux_entity`,
`include/pypeline/operators/auto_fsm_mux.py`), else a measurement remembered
from an earlier pass, else `MUX_BASE_DU + MUX_PER_LEVEL_DU * ceil(log2 n)`.

**`TimingModel`** is the read-only timing objective for whole graphs. It walks
longest dependency paths — serial operations add, parallel branches take the
maximum — and recursively decodes Python hierarchy so a child's unused inputs
and constant-driven paths keep their own arcs (child entity delays are never
simply summed). Primitive arcs prefer the combinational component of a
measurement (see [`SYN_DESIGN.md`](SYN_DESIGN.md#6-caches)); a total-delay
proxy is labelled as one. No synthesis runs. `report(dag)` returns the delay,
critical path, provenance and `TIMING_VERSION`; its `snapshot` is pinned by
`AUTO_COMB_OPT` so choices stay stable across reparses.

## 4. Area

`ESTIMATE_ENTITY_AREA(parser_state, entity)` (memoized) prices an entity and
everything it instantiates; `area(dag, parser_state)` prices a graph from its
nodes' entities and mux banks, returning `(area, coverage tally)`.

- **Abstract units.** `AREA_PER_BIT_*` constants price one bit of an adder
  (1.0), comparator, bitwise gate, mux, variable shift, multiplier/divider bit
  pair and flip-flop (`_leaf_area`).
- **Real units.** Under `DEVICE_MODELS` the model reports µm²:
  `_area_unit_scale` multiplies abstract units by `UM2_PER_ABSTRACT_AREA_UNIT`,
  and `_leaf_area_um2` / `_ff_area_um2` / `_mux_bank_area_um2` use real cached
  sky130 measurements (`SYN.GET_CACHED_LEAF_AREA*`,
  `DEVICE_MODELS.GET_SEQUENTIAL_CELL_AREA`) when they exist. A leaf that would
  price at zero is never treated as free wiring.
- **`FORCE_ABSTRACT_AREA`** (set by `pipelinec --auto_fsm_abstract_area`) keeps
  abstract units under sky130, for A/B comparison. It is part of
  `AUTO_COMB_OPT`'s plan key. Other modules read and write it as
  `AUTO.FORCE_ABSTRACT_AREA`.

How the FSM scheduler adds registers and control to this, and how the model was
calibrated, is in [`AUTO_FSM_DESIGN.md`](AUTO_FSM_DESIGN.md#38-consuming-real-sky130-area).

## 5. Emitting source

- `_Emitter` accumulates generated source lines plus the namespace of live
  objects they refer to; injected names derive only from the graph, so one
  graph always produces byte-identical source (and stable entity names).
- `_exec_generated(name, src, globals)` execs that source into a synthetic
  module with a `linecache` entry, so the elaborator's `inspect.getsource`
  works on it.
- `_render_op` renders one decoded operation as an expression.
- **`_GraphCodegen`** renders DAG nodes without any scheduler: operand cast
  chains (`_render_operand`, `_cast_local`), glue (`_render_glue`), compound
  assembly (`_render_assemble`) and constants (`_render_const`). A subclass
  supplies `_render_ref` — `AUTO_COMB_OPT.CombEmitter` gives each node one local;
  `AUTO_FSM._Codegen` reads per-state registers and shared-unit outputs — and the
  attributes listed in the class docstring.

## 6. Errors and versions

`AutoError` is the design-level error every AUTO feature raises, always with a
message naming the feature and the offending function or operation.
`AUTO_FSM.AutoFsmInternalError` subclasses it for compiler invariants.

`GRAPH_VERSION` and `TIMING_VERSION` are part of `AUTO_COMB_OPT`'s plan key and
the timing report; bump the first when a rewrite or the graph encoding changes
meaning, the second when the timing model does.

## 7. Tests

`auto_comb_area_opt_test.py` and `auto_comb_delay_opt_test.py` exercise the
search, BDD predicates, CSE, rewrites and timing model directly;
`auto_fsm_unit_test.py` covers DAG decoding, descent, type resolution and the
area model inside scheduling; `area_model_test.py` holds the area constants
to the committed sky130 `area_cache/`. See
[`pypeline_TESTS.md`](pypeline_TESTS.md).
