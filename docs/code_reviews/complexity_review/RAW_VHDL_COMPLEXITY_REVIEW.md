# RAW_VHDL complexity review

Built-in operator and memory HDL templates, including genuine bit-internal pipeline splits. Despite C-oriented function names, these are used by Pypeline. [RAW_VHDL design](../RAW_VHDL_DESIGN.md) distinguishes bit-sliceable arithmetic from whole-operation boundaries.

Source: [RAW_VHDL.py](../../src/RAW_VHDL.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 4,997 | 3,929 | 57 | 3 | 35 |

Highest-scoring functions: `GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT` (4205–4339, CCN 35); `GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT` (3996–4157, CCN 22); `GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT` (788–870, CCN 16).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Carry/borrow/comparison chunk generators** — signed and unsigned PLUS, MINUS, LT/LTE, GT/GTE and ACCUM families. Each combines operand resizing, intermediate widths, stage partitions, carry/sign handling and output conversion. A correction applied to only one family can make signedness or split position change correctness.
2. **Stage geometry** — `GET_BITS_PER_STAGE_DICT` (2203–2255), leaf-width and slice-kind classification. Exact boundaries and equal-width division must agree with SWEEP's legal positions. The existing rejection of interior zero-bit stages is a useful invariant; leading/trailing empty stages have different meaning.
3. **Atomic operation placement** — AND/OR/XOR/MULT, unary NOT/NEGATE. Similar code chooses which stage contains the operation while surrounding stages are register-only. These operators cannot automatically be treated as bit-internal pipelineable just because the templates look like arithmetic templates.
4. **Aggregate mux/reference and bit manipulation dispatch** — `GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT`, `GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT`, constant reference reads. Array/record widths, slices, rotations, packing and element ordering are easy to conflate.
5. **Special QoR lowering** — the two-bit/two-stage unsigned adder has an explicit prefix implementation. It is a counterexample to merging every adder path mechanically: shared structure must leave legal target-independent special forms expressible.

## Duplication and simplification

This is the clearest large clone family. The inherited normalized-AST scan found high similarity across roughly eight 130–255-line arithmetic generators, and across the 75–91-line atomic generators. ROTL/ROTR share normalized structure. Those scores abstract identifiers/constants and do not prove semantic identity; overlapping clone windows are not additive.

Factor three concepts: operand/result type conversion, a validated stage partition, and operation-specific state/update expressions. Start with atomic bitwise/unary skeletons and rotations, then share carry-chain skeletons with explicit signedness/carry/compare policy. Retain ACCUM's state semantics separately. A typed operator table can drive dispatch, simulator evaluation and width rules, but one universal template with dozens of flags would recreate the current problem.

Estimated net deletion for the RAW_VHDL families is roughly 500–1,200 physical source lines after replacement helpers, an engineering estimate rather than an implemented diff.

## Validation

No new arithmetic error was reproduced. Exhaustively test widths 1–5, mixed input widths, signed extrema, every supported partition, carry/borrow propagation, comparison equality and exact boundaries. Compare generated HDL to explicit fixed-width arithmetic; for sequential templates compare after the declared latency with CE stalls. Snapshot-only tests cannot establish arithmetic equivalence.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

