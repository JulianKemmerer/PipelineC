# VHDL complexity review

The primary HDL renderer, used by Python builds for types, top-level connectivity, state and pipelined logic. Read [VHDL design](../../VHDL_DESIGN.md). Rendering correctness also determines synthesis-cache identity.

Source: [VHDL.py](../../../src/VHDL.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 7,500 | 6,074 | 70 | 15 | 203 |

Highest-scoring functions: `WRITE_MULTIMAIN_TOP` (417–1815, CCN 203); `GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT` (6617–7186, CCN 93); `GET_PIPELINE_ARCH_DECL_TEXT` (6195–6612, CCN 67).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Top-level assembly** — `WRITE_MULTIMAIN_TOP` (417–1815, CCN 203). Clock ports, globals, ordinary MAIN IO, global instances, FIFOs, arbitration and clock-crossing connections are decided while concatenating text. Connection planning and text rendering are inseparable, making partial-path or clock-domain mistakes hard to isolate.
2. **Pipeline architecture and process** — `GET_PIPELINE_ARCH_DECL_TEXT` (6195–6612), `GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT` (6617–7186). Both classify register banks, state, globals, clock enables, raw HDL and inline operations. Declarations, sensitivity lists, register liveness and assignments must describe the same circuit. A missing sensitivity dependency is a simulation failure even if synthesis recovers the intended logic.
3. **Clock-crossing entities** — `WRITE_CLK_CROSS_ENTITIES` (2328–3381). Vendor versus built-in FIFO implementations and other crossing shapes use large repeated templates. Clock and reset assumptions must match the Python front end's checked crossing records; this is a high-impact part of the concurrent work.
4. **Type packages and conversions** — `WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE`, `_WRITE_GROW_ONLY_C_STRUCTS_PACKAGE`, connection conversion helpers. Recursive arrays/records/enums, dependency ordering, case-insensitive names, widths and signedness meet here. The grow-only package sidecar exists partly to stabilize files across re-elaboration; a type redefinition must reset incompatible chunks.
5. **Artifact identity** — `WRITE_LOGIC_ENTITY`, `GET_ENTITY_NAME`. A physical entity name must determine its text. Planner-only state must not leak into rendered content under a reused name. This invariant is already documented and should be enforced at the emitter boundary.

## Duplication and simplification

Mirrored read/write clock-crossing connection loops and similar normal/crossing entity connections can share a port-map builder. Repeated register/global predicates should come from AUTO_PIPELINE's validated layout rather than being recomputed in declarations and processes.

First produce typed `TopConnections`, `EntityInterface` and `PipelineLayout` data; then render them. A small VHDL builder for declarations, associations and statements would remove delimiter trimming and string surgery. Keep specialized raw templates where they materially express hardware. A generic templating engine alone would move the complexity into templates.

Use content-addressed type dependencies and artifact manifests to reduce grow-only package and cache coupling over time. CIRCT's documented SystemVerilog path is an optional backend experiment; it does not directly replace the existing VHDL product.

## Validation

No new VHDL miscompile was reproduced. Compile generated VHDL with GHDL for nested aggregates, enum conversions, CE, fixed/automatic pipelines and supported FIFO crossings. Compare native/HDL cycle behavior where native simulation supports the design. Render the same entity twice from equivalent physical inputs under different planner states and require identical bytes.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

