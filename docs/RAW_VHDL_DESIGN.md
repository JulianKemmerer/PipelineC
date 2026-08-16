# Raw VHDL leaf generation and split semantics

`src/RAW_VHDL.py` renders the built-in, leaf-most operations used by both the
C and Pypeline front ends. A raw leaf has no submodule instances: its VHDL
generator is the final authority on whether a requested pipeline placement
can divide logic, can only register an operation boundary, or is illegal.

This document describes that lowering contract. The planner which chooses
placements is documented in [`SYN_DESIGN.md`](SYN_DESIGN.md); construction of
complete entities and inter-stage wiring is documented in
[`VHDL_DESIGN.md`](VHDL_DESIGN.md).

## Dispatch

`GET_RAW_HDL_WIRES_DECL_TEXT` and
`GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT` dispatch from a `Logic.func_name` to
the generator for unary and binary operators, accumulators, muxes, memories,
bit manipulation, constant references and shifts, and casts. The split-kind
classification deliberately mirrors this dispatch. A new raw operator is not
complete until its classification and generator agree.

Raw VHDL passthrough supplied by a user is a different feature. It is treated
as an opaque implementation boundary rather than one of the built-in leaves
described here.

## Slices and stages

`TimingParams._slices` contains register placements local to one entity. A
leaf with `N` slices has latency `N` clocks and `N + 1` combinational stages.
The floating-point values identify relative positions for planning and entity
hashing, but their exact meaning depends on the split kind below.

`GET_LEAF_SPLIT_KIND` is the shared legality source for the planner and the
lowering backstop:

| kind | current operations | generated structure |
|---|---|---|
| `SPLIT_KIND_BITS` | `PLUS`, `MINUS`, `EQ`, `NEQ`, `GT`, `GTE`, `LT`, `LTE`, accumulator | genuinely partitions the operator's bit work across stages |
| `SPLIT_KIND_1LL` | mux, bitwise `AND`/`OR`/`XOR`, `NOT`, `NEGATE`, multiply | keeps the whole operation in one stage and moves registers to its boundaries |
| `SPLIT_KIND_NONE` | zero-delay bit manipulation, casts and other unsupported interiors | accepts no pipeline slice |

These are implementation facts, not estimates. Timing measurements may
change where the planner prefers to place a boundary, but may not override a
generator's legal structure.

## Genuine bit-internal splits

For `SPLIT_KIND_BITS`, `GET_BITS_PER_STAGE_DICT` divides the operator width as
evenly as possible across `len(_slices) + 1` chunks.
`GET_EQUAL_WIDTH_BIT_BOUNDARIES` is the shared, side-effect-free source for
those emitted boundaries. During planning, nominal raster sites select the
number and ordering of cuts in a leaf; before lowering they are replaced by
physical ordinal/count-aware placements at the exact equal-width bit
boundaries. The placement trace therefore distinguishes nonphysical requests
from emitted coordinates rather than implying that an arbitrary fraction
selects an uneven bit coordinate. Equal-width chunks minimize the widest stage
for the current carry/comparison generators.

`GET_LEAF_BIT_WIDTH` gives the planner the same widest-input/output width the
generators use. An `N`-bit operation has at most `N - 1` useful internal
registers. Both the placement candidate inventory and
`GET_BITS_PER_STAGE_DICT` reject schedules that would create an interior
zero-bit stage. Leading or trailing zero-bit work can be meaningful when it
represents an operation-boundary register; an empty stage in the interior is
padding and is not legal.

## One-logic-level leaves

The repeated `stage_for_1ll`/`stage_for_op` generators put all of a 1LL
operation in exactly one stage. With one slice, the fraction chooses which
side of the operation is registered. With two slices, the operation sits
between input and output registers. A third slice cannot shorten the logic,
so `LEAF_MAX_SPLIT_SLICES` caps these leaves at two and the typed planner
normally exposes their useful output boundary directly.

A wide mux is consequently not bit-chunked today. Its width still affects the
measured delay and cache key, but relaxing the 1LL cap requires a genuinely
chunked mux generator and separate functional/timing evidence; changing the
classification alone would only add padding registers.

## Operation-boundary lowering

An `instance_output` placement is lowered by setting the target instance's
output-register flag. It does not get projected recursively into every child.
A `bit_internal` placement is legal only for a `SPLIT_KIND_BITS` leaf and is
lowered into that leaf's `_slices`. The normal VHDL pipeline map then delays
other live wires as needed to keep dependencies aligned.

This distinction is important for ordinary user code. A user need not write
helper functions that are approximately one stage long: elaboration already
turns operations in a flat expression or statement sequence into instances,
and their legal output boundaries are candidates. Source hierarchy remains
useful metadata and a tie-break, not a requirement for finding stages.

## Invariants and tests

Fast tests under `src/tests/pypeline_tests/inst/` cover leaf split
classification, the 1LL cap, width caps, equal-width allocation, typed
bit-internal placement, and the absence of padding-only interior stages. Any
new generator or classification change should add both structure assertions
and a generated-VHDL elaboration/simulation case. Real sky130 comparisons are
opt-in benchmarks because they are too expensive for the normal unit suite.
