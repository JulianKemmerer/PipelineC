# Raw VHDL leaf generation and split semantics

`src/RAW_VHDL.py` renders the built-in, leaf-most operations used by both the
C and Pypeline front ends. A raw leaf has no submodule instances: its VHDL
generator is the final authority on whether a requested pipeline placement
can divide logic, can only register an operation boundary, or is illegal.

This document describes that lowering contract. The planner which chooses
placements is documented in [`SYN_DESIGN.md`](SYN_DESIGN.md); construction of
complete entities and inter-stage wiring is documented in
[`VHDL_DESIGN.md`](VHDL_DESIGN.md).

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section, if it
> has one, rather than appending a new one. See
> [documentation conventions](README.md#documentation-conventions).

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
| `SPLIT_KIND_MUX_BITS` | every built-in mux | partitions the packed output bits when a physical bit placement is selected (a selected bank at least `SWEEP.DEFAULT_MUX_CHUNK_MIN_WIDTH` bits wide gets this by default now), while remaining atomic in the initial planner landscape |
| `SPLIT_KIND_1LL` | bitwise `AND`/`OR`/`XOR`, `NOT`, `NEGATE`, multiply | keeps the whole operation in one stage and moves registers to its boundaries |
| `SPLIT_KIND_NONE` | zero-delay bit manipulation, casts and other unsupported interiors | accepts no pipeline slice |

These are implementation facts, not estimates. Timing measurements may
change where the planner prefers to place a boundary, but may not override a
generator's legal structure.

## Genuine bit-internal splits

For ordinary `SPLIT_KIND_BITS` placement,
`GET_BITS_PER_STAGE_DICT` divides the operator width as evenly as possible
across `len(_slices) + 1` chunks.
`GET_EQUAL_WIDTH_BIT_BOUNDARIES` is the shared, side-effect-free source for
those emitted boundaries. During planning, nominal raster sites select the
number and ordering of cuts in a leaf; before lowering they are replaced by
physical ordinal/count-aware placements at the exact equal-width bit
boundaries. The placement trace therefore distinguishes nonphysical requests
from emitted coordinates rather than implying that an arbitrary fraction
selects an uneven bit coordinate. Equal-width chunks minimize the widest stage
for the current carry/comparison generators.

A typed exact placement instead installs a strictly increasing integer
boundary group in `TimingParams._exact_bit_boundaries`. The group, not merely
its fractional projection in `_slices`, participates in copying, validation,
entity hashing, lowering, and placement traces. This internal mechanism can
emit uneven chunks without changing the legacy equal-width behavior. It is
used by controlled QoR experiments and by the bounded packed-MUX refinement
described below.

`GET_LEAF_BIT_WIDTH` gives the planner the same effective packed width the
generators use. Binary arithmetic is sized from its inputs, so a widened carry
output is not mistaken for another splittable operand bit. An `N`-bit
operation has at most `N - 1` useful internal registers. Both the placement
candidate inventory and
`GET_BITS_PER_STAGE_DICT` reject schedules that would create an interior
zero-bit stage. Leading or trailing zero-bit work can be meaningful when it
represents an operation-boundary register; an empty stage in the interior is
padding and is not legal.

The two-stage, two-input-bit unsigned `PLUS` case uses a carry-prefix lowering.
Stage 0 registers both bits' propagate/generate values and the low result bit;
stage 1 combines the registered upper prefix with the registered low carry.
The ordinary one-bit-at-a-time lowering left a complete full-adder path in the
second stage, so splitting the leaf did not shorten its critical path. This
specialization changes neither the arithmetic nor the requested latency and
is independent of the target clock, device, and multiplier source shape.
Unsplit additions and all wider/chunkier additions retain the existing
inferred-add lowering. The additional prefix fields are part of the normal raw
leaf pipeline record, so hashing and stage transfer include them exactly like
the existing carry and partial-result fields.

## Packed MUX bit chunks and one-logic-level leaves

Every built-in MUX uses `SPLIT_KIND_MUX_BITS`. Its width is the packed width
defined by `c_structs_pkg`, recursively covering integers, floats, enums,
arrays, structs, and nested combinations. A MUX with one or more local slices
emits only the selected packed bit chunk in each stage and carries the partial
result through the normal leaf pipeline record. This is a genuine logic split:
each stage's one-bit select drives only its chunk rather than the complete
output bank.

Unsigned, signed, and plain `std_logic_vector` data retain the direct vector
lowering. For a composite or named user type, stage 0 converts both alternatives
with the generated `<type>_to_slv` function, the stages select their assigned
SLV ranges, and the final stage reconstructs the result with
`slv_to_<type>`. The condition, packed alternatives, and partial packed result
are ordinary pipeline-record fields, so the normal wire-alignment machinery
carries them across the leaf stages. The conversion preserves the canonical
`c_structs_pkg` field/element packing order; the splitter does not invent a
second type layout.

The initial landscape still treats a MUX interior as atomic so the fewest-stage
planner retains the established operation-boundary geometry. After a
full-design timing miss, the sweep may try one typed midpoint-chunk neighbor
before selecting a denser schedule. The exact/equal boundary rules are shared
with integer MUXes; no user-type-specific placement rule is involved.

The repeated `stage_for_1ll`/`stage_for_op` generators put all of a 1LL
operation in exactly one stage. With one slice, the fraction chooses which
side of the operation is registered. With two slices, the operation sits
between input and output registers. A third slice cannot shorten the logic,
so `LEAF_MAX_SPLIT_SLICES` caps these leaves at two and the typed planner
normally exposes their useful output boundary directly. This remains the
contract for the remaining 1LL operations. MUXes do not use this generator
path once pipelined; they use the packed-bit lowering above.

## Operation-boundary lowering

An `instance_output` placement is lowered by setting the target instance's
output-register flag. It does not get projected recursively into every child.
A `bit_internal` placement is legal only for a `SPLIT_KIND_BITS` or
`SPLIT_KIND_MUX_BITS` leaf and is lowered into that leaf's `_slices` plus,
for exact mode, `_exact_bit_boundaries`. The normal VHDL pipeline map then
delays other live wires as needed to keep dependencies aligned.

This distinction is important for ordinary user code. A user need not write
helper functions that are approximately one stage long: elaboration already
turns operations in a flat expression or statement sequence into instances,
and their legal output boundaries are candidates. Source hierarchy remains
useful metadata and a tie-break, not a requirement for finding stages.

## Invariants and tests

Fast tests under `src/tests/pypeline_tests/inst/` cover leaf split
classification, the 1LL cap, width caps, equal-width and exact allocation,
typed bit-internal placement, chunked packed-MUX refinement, composite SLV
conversion/reconstruction, the two-stage two-bit carry-prefix structure, and
the absence of padding-only interior stages. Any
new generator or classification change should add both structure assertions
and a generated-VHDL elaboration/simulation case. Real sky130 comparisons are
opt-in benchmarks because they are too expensive for the normal unit suite.
