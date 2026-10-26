# pypeline_host complexity review

Generates a standalone Python serializer module for host programs. [The API design's shared-layout section](../../pypeline_DESIGN.md#one-walk-three-consumers) is an existing example of successful semantic reuse.

Source: [pypeline_host.py](../../../src/pypeline_host.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Locations refer to that snapshot. Failure scenarios are hypotheses unless explicitly confirmed.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 682 | 508 | 18 | 0 | 12 |

Highest-scoring functions: `_value_literal` (226–247, CCN 12); `_byte_map` (525–549, CCN 10); `_emit_type` (552–592, CCN 10).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Host names and dependency order** — `_deps`, `_assign_host_names`, `_emit_order`, `_check_emittable`. Nested structs/enums require dependency-first emission and unique valid Python identifiers. Short-name collisions fall back to canonical names; cross-collisions with generated runtime names and exported constants deserve specific tests.
2. **Generic versus fast serialization** — `_shape_expr`, `_struct_format`, generated `_RUNTIME`, `_emit_type` (552–592). Generic recursive walking and struct-module fast paths must agree on endian order, non-byte widths, sign interpretation and char arrays.
3. **Exported literal generation** — `_value_literal` (226–247), `_value_literal_of`, `generate` (595–660). Value/type naming must agree and emitted Python must remain valid for nested constants and enums.
4. **Output lifecycle** — `write_host_types`. A build with no exports returns without writing. Reusing an output directory that still contains a prior host module can leave a stale file visible; this is an artifact-lifecycle risk, not a reproduced serialization bug.

## Duplication and simplification

Preserve reuse of pypeline's leaf walk, sizes and cast parameters. This already avoids re-deriving the wire format in a second generator. The standalone runtime is an intentional deployment requirement, so importing the full compiler at runtime would not be a simplification for users.

Use one exported schema/name table to render generic shape data, fast-path descriptors and constants. Reserve all generated global identifiers in the same allocator. Put host artifacts in the build manifest, with explicit handling of a previously emitted module when exports disappear.

## Validation

No serialization defect was reproduced. Compare generated host bytes with pypeline software and simulated hardware for nested arrays/structs, signed non-byte widths, both endians, enums and char arrays. Compile/execute generated modules with colliding names and constants. Keep the stdlib-only deployment test.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

