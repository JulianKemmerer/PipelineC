# CC_TOOLS complexity review

CologneChip GateMate adapter. Small code size hides weak report validation and shared-directory/process assumptions. See [SYN design](../SYN_DESIGN.md#3-the-backend-contract).

Source: [CC_TOOLS.py](../../src/CC_TOOLS.py). Reviewed on the working tree based on `9eafa7d8`, including concurrent multi-clock changes. Potential failures are not reproduced defects unless stated.

## Table of Contents

- [Measurements](#measurements)
- [Ranked hotspots](#ranked-hotspots)
- [Duplication and simplification](#duplication-and-simplification)
- [Validation](#validation)

## Measurements

| Physical lines | Lizard NLOC | Functions | Functions with CCN > 15 | Maximum function CCN |
|---:|---:|---:|---:|---:|
| 207 | 139 | 5 | 0 | 5 |

Highest-scoring functions: `SYN_AND_REPORT_TIMING_NEW` (89–207, CCN 5); `__init__` (38–54, CCN 3); `__init__` (28–34, CCN 2).

CCN is a branch-count heuristic, not a defect count. File hash and reproducible measurement method are in [the measurement record](METRICS.json) and [experiments](REVIEW_EXPERIMENTS.md#measurement-method).

## Ranked hotspots

1. **Accepting absent timing** — `ParsedTimingReport` (28–34), `PathReport` (38–54). The constructor inserts one path even if no frequency was parsed, then checks whether the dictionary is empty. That check cannot detect the absent timing. `path_group` is assigned 'clk' then overwritten with None.
2. **Tool and workspace paths** — module setup and `SYN_AND_REPORT_TIMING_NEW` (89–207). A temporary directory under the tool installation is named by top entity, removed and recreated. Concurrent builds of that top can collide, and installations may be read-only. Tool root derivation concatenates a directory with `../../` instead of joining components.
3. **Two-command execution** — generated Yosys and place/route shell commands are separate unchecked lines. A failed synthesis followed by a later command can obscure the original failure or consume stale files.

## Duplication and simplification

**Confirmed parser defect:** `ParsedTimingReport("no timing information")` returns `{None: path}` with `path_delay_ns is None`; see the [probe](REVIEW_EXPERIMENTS.md#backend-adapter-probes). Reject missing/nonpositive/nonfinite frequency before creating a usable observation.

Use the shared runner with a unique workspace inside the build output, explicit tool paths, and checked subprocess stages. The identical single-instance wrapper belongs in common code. Report capabilities should explicitly say endpoint/clock evidence is unavailable rather than synthesizing a partly populated success object.

## Validation

The parser probe ran; GateMate tools did not. Test absent/zero/malformed Fmax, paths with spaces and two jobs with the same top name in different builds. Confirm failed synthesis prevents place/route and cache recording.

See the [cross-module recommendations](REVIEW_COMPLEXITY.md).

