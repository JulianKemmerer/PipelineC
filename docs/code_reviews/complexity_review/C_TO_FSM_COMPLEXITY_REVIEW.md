# C_TO_FSM complexity review

Source: [C_TO_FSM.py](../../src/C_TO_FSM.py). This is a scope/boundary review of the legacy C FSM frontend, based on `9eafa7d8`; it is not a detailed correctness audit of C parsing. The requested Python HDL focus places this below every shared compiler pass.

## Table of Contents

- [Measurements](#measurements)
- [Pypeline relevance](#pypeline-relevance)
- [Complexity and recommendation](#complexity-and-recommendation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 2,444 | 1,848 | 29 | 8 | 56 |

Highest-scoring functions: `FSM_LOGIC_TO_C_CODE` (771–1261, CCN 56); `C_AST_FSM_FUNDEF_BODY_TO_LOGIC` (1994–2204, CCN 46); `STATE_GROUP_TO_C_CODE` (233–768, CCN 39).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Pypeline relevance

This module consumes pycparser nodes, recognizes the C `__clk`/`__in`/`__out`/`__io` convention and generates C FSM source. Pypeline's AUTO_FSM works from typed combinational graphs and has its own scheduling/lowering path. The scan of other compiler modules found no direct calls into C_TO_FSM outside the excluded C front end; LOGIC retains fields explicitly documented as C-only. Transitive import availability is not evidence of a Python execution path.

## Complexity and recommendation

The large `STATE_GROUP_TO_C_CODE`, `FSM_LOGIC_TO_C_CODE`, control-flow-to-state conversion and `GET_GROUPED_STATE_TRANSITIONS` routines mix graph traversal, state numbering and C emission. They would need independent C-language tests before refactoring. No behavior of those routines was executed or proven faulty in this review.

Keep the legacy frontend boundary explicit. Do not merge this state machine representation with AUTO_FSM merely because both emit FSMs: one lowers sequential C control flow, the other schedules resource-shared hardware operations. Moving legacy-only fields out of shared LOGIC can reduce Pypeline's conceptual load, but deleting C support is a separate product decision. No legacy lines are credited as Pypeline simplification savings.

See the [scope and coverage](REVIEW_COMPLEXITY.md#scope-and-coverage).
