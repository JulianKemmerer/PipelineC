# AUTO complexity review

Shared typed combinational graph construction, cleanup, rewrite search, costing and source regeneration. [AUTO design](../AUTO_DESIGN.md) documents substantial reuse already achieved between AUTO_FSM and AUTO_COMB_OPT.

Source: [AUTO.py](../../src/AUTO.py). This is a targeted structural review of the working tree based on commit `9eafa7d8`, including concurrent multi-clock changes. Function names are the stable navigation aid; line numbers describe the measured snapshot. Suspected failure cases are not confirmed bugs unless explicitly labeled.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 3,458 | 2,365 | 115 | 17 | 57 |

Highest-scoring functions: `_cleanup_once` (290–478, CCN 57); `PREPARE_CONSTANT_SPECIALIZATIONS` (576–723, CCN 40); `delay_implementation_seeds` (1102–1173, CCN 35).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Typed cleanup** — `_cleanup_once` (290–478). Constant folding, mux selection, arithmetic identities, power-of-two multiplication, range proofs, pruning and CSE interact with ordered edge casts. Algebraically valid integer rewrites can be wrong after truncation or sign extension. The explicit cast replay already present is essential.
2. **Recovering an operation from Logic** — `DECODE_OP` (1822–1945), `_trace_operand`, `_build_dag_level` (2633–2857). The code reconstructs syntax from entity names, reference tokens, retained live callables and port metadata. Inlining changes scope and namespaces while preserving widths, constants and measurement identity. This decoding layer exists because Logic does not carry a complete typed opcode.
3. **Preparing implementations** — `PREPARE_CONSTANT_SPECIALIZATIONS` (576–723), soft/split equivalents, `delay_implementation_seeds` (1102–1173). New Python functions are generated and elaborated just to obtain alternative graphs and measurements. Scoped implementations and pure/stateful boundaries must survive that round trip.
4. **Search and proof infrastructure** — graph fingerprints, deepcopy-based candidates, known/demanded bits, value ranges and predicate proofs. Candidate equivalence is not textual equivalence; widths, port ordering and cast chains are part of semantics. Broad exception catches in optional heuristics can make unsupported cases look like successful no-op optimization.
5. **Source rendering and type reconstruction** — `_TypeResolver`, `_Emitter`, `_GraphCodegen`, `_exec_generated`. These bridge typed names back to Python objects and then back to Logic. Generated-source identity and retained globals become additional compiler state.

## Duplication and simplification

AUTO's shared graph utilities and emission base are worth preserving. Avoid rebuilding them in another optimizer. The clone scan's repeated windows around rewrite generation overlap, so they are evidence of repeated patterns rather than a valid removable-line total.

Introduce typed node/value/cast records and an explicit operator specification. Turn rewrites into small rules with legality predicates and a result/rejection reason. Replace repeated full deepcopy with immutable nodes plus candidate-local maps only after profiling candidate cost.

The substantial deletion opportunity is direct lowering of AUTO graphs into the shared typed IR. Keep generated Python as a diagnostic view if useful, but it should not be the only route back to hardware. This would remove parts of decoding, type resurrection and scope reconstruction. It requires a representation of custom calls and effects first.

## Validation

No new semantic defect was demonstrated. Exhaustive small-width comparisons should cover signed/unsigned boundaries, intermediate casts, overflow, division/modulo, oversized shifts and custom operator scopes. Check each rewrite preserves values independently of its area/delay score. Measure generated candidate count, elaboration work and cache hits on the same designs before claiming a search speedup.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

