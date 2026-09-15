# Pypeline test suite

`src/tests/pypeline_tests/` exercises the Pypeline compiler end to end against real
`.py` design files in `inst/`. There is no test-discovery mechanism -- every test is a
hand-written entry in one of eight category modules, run together via `run_all.py`.

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section rather
> than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## Categories

| Category | What it checks | Verdict |
|---|---|---|
| `native_sim` | Python golden-model checks (`sim_call`) and `pypeline_sim.py` multi-MAIN runs; fixed user pipelines selectively prepare alignment | exit code, plus in-process `assert`s |
| `native_vs_vhdl_sim` | Runs a design's native (Python) sim and its real cocotb+GHDL sim via `pypeline_sim_debug.py`, and diffs their `sim_print(..., debug=True)` output cycle by cycle | exit code (MATCH/MISMATCH) |
| `elab` | `pypelinec --no_synth` -- does it elaborate | exit code only |
| `elab_introspect` | Calls `PY_TO_LOGIC.PARSE_FILE` in-process and asserts on `parser_state` / `FuncLogicLookupTable` / a raised `ElaborationError`'s type and message | in-process `assert`s |
| `unit` | Pure compiler-helper tests against hand-built fixtures -- no design build | in-process `assert`s |
| `synth` | Full elaboration + auto-pipelining + synthesis (no `--no_synth`) | exit code only |
| `build_report` | Wrapper scripts that run `pypelinec` themselves and assert on its build log or generated artifacts (yosys/PYRTL cell counts, `TIMING NOT MET` text, `sweep_history.json`) | in-process `assert`s over subprocess output |
| `known_issues` | Reproducers for known, unfixed compiler bugs. **Excluded from `run_all.py`'s default set** -- run explicitly with `--category known_issues`. Every entry has `expect_fail=True`: a passing run means the bug is still present (XFAIL); a clean run means it got fixed without the test being updated (XPASS, reported as a *failure* -- promote the test out of this category) | inverted exit code (or, where exit code doesn't capture the issue, an explicit log-content assertion -- see that entry's own docstring) |

`elab_introspect` vs `unit` is decided by the file's *purpose*, not by whether
`PARSE_FILE` happens to appear in it: a 600-line scheduler/codegen test that calls
`PARSE_FILE` incidentally is `unit`; a test whose whole point is parsing a design and
inspecting the resulting `parser_state` is `elab_introspect`.

## Naming convention in `inst/`

- `*_test.py` -- a registered test file. Every one **must** appear in some category
  module's list (enforced by `registration_audit_test.py`, in `unit`).
- `*_design.py` -- a fixture another test builds or imports. Never registered directly.
- `_test_main.py` -- shared `__main__` harness (leading underscore, not a test).

A fixture that another test builds as a subprocess may instead live one level up, in
`src/tests/pypeline_tests/` itself, keeping its original `*_test.py` name -- e.g.
`auto_fsm_resources_test.py`, `auto_fsm_div_share_test.py`, `auto_fsm_tighten_test.py`,
each built by a corresponding wrapper in `inst/`. Being outside `inst/` is what keeps
them out of the registration audit; they are not part of the `run_all.py` suite.

## Adding a test

Prefer adding a `test_*` function to an **existing** file over creating a new one --
each registration pays its own elaboration/synthesis/GHDL start cost, so fewer, larger
files are the goal, not more files. A file's `__main__` block should read:

```python
if __name__ == "__main__":
    from _test_main import run_module_tests
    run_module_tests()
```

`run_module_tests()` auto-discovers every `test_*` callable defined at module scope
and runs it, so adding a function is enough -- no separate `__main__` call list to
remember to update. It only fires under `python3 inst/X.py` (`__name__ ==
"__main__"`); `pypelinec` imports the same file as module `"pypeline_design"`
(`PY_TO_LOGIC.PARSE_FILE`), so `elab`/`synth`-category registrations of a file never
run its `test_*` functions -- those categories check elaboration/build only.

## Fixed user pipeline coverage

`pipeline_latency_test.py` covers `@pipeline_latency` validation and stacking,
factory specialization, fixed-latency metadata across repeated elaboration, serial
and parallel composition, bypass alignment, conditional enables, dynamic array
reads/writes, initialization, reset and convergence. Its subprocess gate tests
forbid importing the pipeline model in untagged `--comb` CLI builds and also
forbid the elaborator in direct native runs, covering arithmetic, registers,
AUTO_PIPELINE and AUTO_FSM. Unrelated roots, zero-cycle declarations and
direct calls to tagged bodies also forbid model preparation.
Alternating live roots check that shared helper models retain separate state.
Explicit placement tests reject cuts both at and inside a fixed boundary.

`pipeline_latency_sim_test.py` runs in both native-versus-VHDL categories, with
and without `--comb`. It checks independently calculated data, sequence order and
constant observed latency for unequal fixed pipelines in both a naturally
pipelined MAIN and an AUTO_PIPELINE region. Valid-gated debug probes compare exact
clock timing against GHDL, including draining the pipeline, register initialization,
synchronous reset and clock enables within a stateful caller.

## AUTO_PIPELINE latency constraint coverage

Each test below covers `AUTO_PIPELINE(func, latency= / start_latency= / max_latency=)`
from a different angle:
- `auto_pipeline_harvest_test.py` (unit):
  - constructor validation;
  - identity suffixes (an unconstrained tag's key and `pypeline_names` identity are
    unchanged);
  - `.latency` per build mode and cache;
  - the served-value predicate behind the pin-and-confirm pass-2 skip;
  - `SYN.CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED`.
- `auto_pipeline_region_planning_test.py` (unit): `SWEEP.COUNT_TARGETED_PLACEMENTS`,
  plan trimming, cap bookkeeping, and hotspot-to-region attribution on synthetic
  landscapes.
- `auto_pipeline_fixed_latency_sim_test.py` (native_sim): plain native sim emulates a
  fixed latency and ignores start/max. `pipeline_latency_test.py`'s gate test also runs
  it, both directly and through `pypelinec --sim --comb`, with the compiler import
  forbidden.
- `auto_pipeline_constraints_test.py` (build_report): fixed and start regions are built
  exactly and pass 2 is skipped, and a `max_latency` cap stops an unreachable goal
  promptly.
- `auto_pipeline_c_pragma_test.py` (build_report): C `#pragma AUTOPIPELINE N` under
  `--comb`.
- `self_check_fixed_auto_pipeline_test.py` (both native_vs_vhdl categories): compares
  the native delay line against the `--comb` VHDL's fixed registers, and against the
  planned sweep's enforced region.

## AUTO_MULTI_CYCLE coverage

`AUTO_MULTI_CYCLE(latency= / start_latency= / max_latency=)` and the multi-cycle stream wrappers:
- `auto_multi_cycle_unit_test.py` (unit):
  - constructor validation and `.latency` resolution;
  - construction-site keys and the inline-construction guard;
  - design-read vs. compiler-read tracking;
  - identity that follows the resolved count;
  - `SYN` constraint overrides and the timing-params hash;
  - `SWEEP` report matching and grow-only feedback on a synthetic Vivado report;
  - elaboration into `Logic.auto_multi_cycle_tuples`, where a cache re-parse changes the count and
    renames the holding entity;
  - an unread tag refused by `SYN.CHECK_AUTO_MULTI_CYCLE_TAGS_READ`.
- `stream_auto_multi_cycle_test.py` (native_sim and synth `--comb`): the handshake waits
  `.latency + 1` cycles for `start_latency=` and fixed `latency=`, and the Xilinx-part
  `--comb` build emits both `set_multicycle_path` constraints.
- `stream_multi_cycle_test.py` (native_sim and synth `--comb`): the fixed
  `make_stream_multi_cycle`.
- `auto_multi_cycle_sweep_test.py` (build_report, **real Vivado**, `auto_multi_cycle_sweep_design.py`):
  - from the default start, the sweep raises the count until the path meets timing;
    pass 2 re-elaborates, the final XDC carries the count, and the pipelined native
    `--sim`'s `sim_assert` checks the handshake;
  - restarting at that count settles immediately, with pass 2 skipped;
  - `max_latency=1` fails the build naming the cap.

## AUTO_COMB_SHARE coverage

`AUTO_COMB_SHARE` is exercised at the callable, graph, RTL and stream boundaries:

- `auto_comb_share_test.py` (`elab_introspect`): metadata/native forwarding,
  generated candidate equivalence, exclusive predicates, multiple consumers,
  signed casts, modular factoring, constant arithmetic, demanded/known bits,
  custom narrow-width operators, scoped fallback, purity and repeat parsing.
- `auto_comb_share_build_test.py` (`build_report`, Yosys + GHDL): SAT proves
  bit-exact equivalence for all inputs of the two-multiplier/output-mux example;
  independent mapped-cell builds require a strict area reduction and no
  flip-flops/latches in the combinational replacement.
- `self_check_stream_auto_comb_share_test.py` (`synth`, native-vs-VHDL `--comb`):
  two-cycle registered boundaries, unstalled II=1, bubbles, backpressure and
  stable output while stalled.
- `self_check_auto_comb_share_composition_test.py` (both native-vs-VHDL modes):
  fixed/discovered pipelines, default raw-function FSM, explicit-ACS FSM, and
  MCP stream composition. The design selects an Artix-7 part because real MCP
  constraints require Vivado.

Run the full suite with `python3 src/tests/pypeline_tests/run_all.py -j 4 --no_timeout`.
Use `-k auto_comb_share` to select the feature tests. See
[`AUTO_COMB_SHARE_DESIGN.md`](AUTO_COMB_SHARE_DESIGN.md) for the contract and limits.

## RAM coverage

`make_ram` (`include/pypeline/ram.py`) and `make_stream_ram` (`stream/stream_ram.py`) share one
VHDL generator and one simulation model. Coverage:

- **`ram_test.py`** (`native_sim` and `synth --comb`).
  - Six `@MAIN` shapes, each with its own generated raw VHDL: single port, struct elements
    with a non-power-of-two size, two ports with input/output registers, an array register
    file, byte write enables, and a string ROM.
  - `sim_call` tests: latency and pass-through fields, read-first reads, write collisions,
    init forms and validation, instance independence and `sim_reset`, same-cycle
    re-evaluation, stateful versus pure (aligned) callers.
  - Seeded soaks against a reference with no stage bookkeeping: a request's read sees
    exactly the writes of earlier requests.
  - A `PARSE_FILE` check that every generated RAM carries its `func_fixed_latency`.
- **`stream_ram_test.py`** (`native_sim` and `synth --comb`): ready-as-clock-enable stall
  hold, bubble fill, exactly one write per accepted request, independent ports, latency 0,
  and a random-backpressure replay.
- **`ram_sim_model_test.py`** (`native_sim` via `pypeline_sim.py --run 30`): convergence
  safety of the shared-memory model. RAM accumulators are closed through wires, so every
  cycle re-evaluates them with stale inputs. Mutation-checked: a model that writes from
  re-run evaluations never converges.
- **`self_check_ram_test.py`** (both `native_vs_vhdl_sim` modes, plus `native_sim`):
  - init readback across element types (`uint1_t`, `int1_t`, 64-bit signed, enum, struct,
    2-D array, `char_t[8]`, fixed, float);
  - latency-3 traffic and byte write enables;
  - a pure `@MAIN(100.0)` aligned around the RAM;
  - a stream RAM under backpressure.

  The checker MAIN returns a value on purpose. A design with no top-level outputs synthesizes
  to nothing, and the pipelined build's PyRTL timing step then fails. The pure MAIN is also
  what keeps a pipelined build of this file off the single-stateful-MAIN coarse-sweep path.

## Generated-name regression coverage

`interface_factory_two_widths_test.py` is a normal synthesis test: the same design
instantiates broadcasts and skid buffers at four and eight byte lanes using their
original interface objects. `generated_naming_test.py` checks structural identity,
interface pairing and direction, typed parameter distinctions, returned-factory
closure identity, readable record names, overflow, case-insensitive collisions and
VHDL lexer/idempotence behavior.

`generated_naming_build_test.py` builds that design in two fresh processes with
separate output directories and different `PYTHONHASHSEED` values. It compares all
VHDL paths and bytes, checks name length and source/index coverage, and imports and
elaborates the real top with GHDL. `name_index_test.py` covers source tracing,
same-spelling definitions that must coexist, and a deliberately forced identity
collision that must fail clearly. Existing AUTO_FSM and native-versus-VHDL tests
exercise generated helpers and specialization reuse in real hardware builds.

## `native_vs_vhdl_sim` probe rules

A design registered in `native_vs_vhdl_sim_tests.py` must:

- Emit at least one `sim_print(..., debug=True)` probe covering the values its
  `sim_assert`s already check.
- **Never** emit a `debug=True` print on the same cycle `sim_finish()` is called.
  Whether a same-cycle VHDL write flushes before `std.env.finish` kills GHDL is a
  process-ordering race the diff must not depend on -- the print is silently DROPPED
  from the VHDL/cocotb log entirely if this rule is broken (present in native sim,
  absent in VHDL -- not a text-visible failure, just a missing line the cycle diff
  will flag as a mismatch). This is a documented tool constraint, not a compiler
  bug -- see `known_issues_tests.py`'s `sim_finish_debug_print_race_test` for a
  direct reproduction of what happens if it's broken, and e.g.
  `self_check_counter_test.py` for the standard one-cycle gate
  (`if n < NUM_COUNTS - 1: sim_print(...)`).
- For a non-`--comb` (pipelined) entry: put every probe inside a stateful (0-latency)
  MAIN, and valid-/count-gate it, since VHDL's undefined (`'U'`) warm-up registers
  can't be compared against native's typed zeros.

- Keep every probed value under 2**31 if it is a `uint32_t`. `sim_print` lowers to
  `integer'image(to_integer(x))` and VHDL's `integer` is 32-bit *signed*, so GHDL
  aborts with `overflow detected` on a larger value while native sim prints it
  happily -- a VHDL-only failure by construction. `self_check_type_axis_test.py`
  carries a comment marking where it deliberately stays under the limit.

See `docs/pypeline_sim_DESIGN.md`'s Limitations section for the full contract
(including the two hard-error cases enforced by the elaborator/simulator directly).

## Testing generated host code

The standalone host module a build writes to `<out_dir>/host/` (see
[Host-Side Generated Types](pypeline_guide.md#host-side-generated-types)) is tested in a
way worth copying whenever "this artifact must work somewhere else" is the claim:

- `inst/host_types_test.py` (`native_sim`) checks the GENERATOR. It runs the generated
  text in a **subprocess whose `sys.path` cannot reach this repo** — and which asserts
  `import pypeline` fails before doing anything else — then compares what that process
  decodes and encodes against `pypeline.type_to_bytes`/`type_from_bytes`, over random
  frames in both endians.
- `inst/host_types_build_test.py` (`build_report`) checks the BUILD: it runs `pypelinec`
  for real, lifts the file out of the output directory, and repeats that comparison on it.

Two rules make those tests mean something, both learned by mutation-testing them:

- Drive them with **raw random bytes, not bytes canonicalized through pypeline first**. A
  canonicalized frame already has every ragged leaf (`uint3_t`) reduced to fit, so a
  generator that masked such a leaf to a whole byte decodes it identically and the bug
  walks straight through. Raw bytes force each leaf's mask to discard something.
- Compare the DECODED value field by field, not just the re-encoded bytes. Round-tripping
  inside the generated module alone passes for any self-consistent layout, including a
  wrong one — which is the exact failure mode (a well-formed frame of the right length,
  loading the wrong values) that generating the host's copy exists to prevent.

## Running

```
python3 src/tests/pypeline_tests/run_all.py                       # default categories, parallel
python3 src/tests/pypeline_tests/run_all.py -j 4 --no_timeout     # full suite, four workers, no timeout
python3 src/tests/pypeline_tests/run_all.py --category native_sim
python3 src/tests/pypeline_tests/run_all.py --category known_issues   # opt-in
python3 src/tests/pypeline_tests/run_all.py -t <name>              # one test, by name or list index
python3 src/tests/pypeline_tests/run_all.py -k <substring>          # tests whose name contains SUBSTRING
python3 src/tests/pypeline_tests/run_all.py --list                  # print the numbered list, don't run
python3 src/tests/pypeline_tests/run_all.py --timeout 60             # override every test's timeout
```

Each test gets an isolated `--out_dir` under a fresh tmp root (`common.py`'s
`make_tmp_root()` / `run_test()`), so tests run in parallel safely; a per-category
default timeout (`common.DEFAULT_CATEGORY_TIMEOUT_S`, overridable per `Test` or via
`--timeout`/`--no_timeout`) kills a hung subprocess instead of blocking the whole
suite. A summary table reports PASS/FAIL/XFAIL/XPASS/SKIP/TIMEOUT per test, with
output directories of any failed test printed for inspection.

Each category module can also run standalone, e.g.
`python3 src/tests/pypeline_tests/native_sim_tests.py [-j N]`.

## Related

- `src/tests/pypeline_tests/op_qor_bench.py` -- QoR benchmark (not a correctness test,
  not part of `run_all.py`), driving `pypelinec --coarse --sweep` and comparing yosys
  cell-count estimates against synthesized results across the operator library.

- Carry-save multiplier first-candidate QoR probe -- a manual, opt-in sky130
  acceptance check using the external latchup `solution.py`. Variants change
  only `CLK_RATE_MHZ`; the latchup-equivalent command is:

  ```text
  pypelinec <solution.py> --no_sweep --no_hier_syn --out_dir <out>
  ```

  Accepted model-V4/`early_flatten_noabc` results, with timing inputs held
  fixed, are:

  | requested MHz | added-clock latency | comb stages | measured fmax |
  |---:|---:|---:|---:|
  | 700 | 30 | 31 | 700.640825 MHz |
  | 701 | 59 | 60 | 909.794952 MHz |
  | 720 | 60 | 61 | 909.794952 MHz |
  | 905 | 60 | 61 | 909.794952 MHz |

  The 700 MHz result is the preserved baseline; the first deeper family at a
  701 MHz request is 29.852% faster and remains below 64 stages. The accepted
  mapped candidate has 7,164 cells, 4,605 sequential cells, and zero unmapped
  cells. The exact 720 MHz final VHDL passes 51 products with continuous data,
  bubbles, ordering, and exact 60-clock latency.

- `src/tests/pypeline_tests/divider_qor_bench.py` -- opt-in sky130 auto-pipelining
  benchmark and correctness gate, also excluded from `run_all.py` because a full gate
  Divider sweep can take about an hour. It has unchanged-logic arithmetic and gate-level
  143 MHz fixtures under `qor/divider/`. A normal run records a machine-readable
  `manifest.json` containing source/compiler/tool/liberty hashes, placement trace,
  exact final VHDL hashes, mapped-cell histogram/DFF count, timing components, runtime,
  and the acceptance verdict:

  ```text
  python3 src/tests/pypeline_tests/divider_qor_bench.py \
    --variant gate --out_dir /tmp/divider_gate
  ```

  The gate verdict requires correct final-VHDL output, fmax strictly above 143 MHz,
  and no more than 48 slices (49 combinational pipeline stages). The arithmetic
  regression requires the same correctness/fmax checks and at most 63 slices.
  The harness first copies the exact ordered `vhdl_files.txt` bytes into an
  evidence snapshot. Simulation compiles that snapshot with the pinned GHDL,
  and the accepted timing/cell result comes from remapping the same immutable
  snapshot rather than whichever netlist happened to be produced by the last
  sweep probe. It checks
  continuous-valid traffic, bubbles, edge cases, divide-by-zero, ordering, valid
  latency, input readiness, and pipeline flush. The fixture has no output-ready port,
  so this test intentionally makes no output-backpressure claim.

  `qor/divider_qor_acceptance.json` holds the acceptance record, taken under the
  V3 production recipe (`early_flatten_opt`, full decision in
  `qor/synthesis_recipe_forced32_matrix.json`): the automatic gate result is
  160.43 MHz at 31 slices / 32 combinational stages, and the arithmetic result is
  180.05 MHz at 32 slices / 33 stages. Both exact final-VHDL runs pass 141
  ordered vectors, have zero unmapped cells, and satisfy their slice limits.
  The corresponding clean-commit baselines required 66 and 64 slices. The
  current production recipe is `early_flatten_noabc` (see
  [`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md#history)'s History
  section) — this V3-era acceptance record has not been re-taken against it.
  Full sky130 runs remain opt-in.

  Controlled physical and recipe experiments remain internal to this harness. Use
  `--placement step-boundaries` to force every gate `step_gates` output boundary, or
  `--placement step-boundaries-div0` for the divide-zero-select output followed by
  the first 31 repeated-step outputs (32 slices / 33 combinational regions);
  `--elaborate-only --diagnostic` to emit/check that placement without a timing sweep;
  or `--frozen-vhdl-source <run>` with one of the fixed recipe IDs to remap byte-identical
  VHDL without re-planning. There is no arbitrary synthesis-flags or public slice-cap
  interface. A timing-miss compiler exit does not suppress exact-VHDL simulation when
  the final artifacts were still written. To import an already-completed run whose
  stdout was not redirected, use `--existing-build --existing-latency N` and optionally
  `--existing-runtime-seconds S --existing-returncode RC`; the return code is
  required for a non-diagnostic acceptance import. The manifest marks any pre-existing `build.log` as
  incomplete/unverified rather than presenting an injected depth line as full stdout.
  `--compiler-commit` and `--source-sha256` attach the compiler/source snapshot which
  actually launched that completed build; the manifest records the current worktree
  separately so later documentation changes cannot be misattributed to the old run.
  Normal and frozen runs reject nonempty destination directories, liberty
  overrides, source drift during the run, mismatched recipe/model identities,
  unmapped cells, incomplete topology, or a timing report whose VHDL/mapped
  hashes do not match the immutable snapshot. A nonzero simulator return code
  cannot be overridden by a stale `functional_results.json` pass marker.
- `src/tests/pypeline_tests/divider_continuity_bench.py` -- opt-in arithmetic-
  only model-V4 continuity benchmark, also excluded from `run_all.py`. It
  requires the unchanged latchup source SHA-256
  `cfde3ad82985716544df580bb9415c6cbc4efa03ed4687b14a774e1bda56f70f`,
  derives temporary variants by changing only `CLK_RATE_MHZ`, and rejects any
  change to `DEVICE_MODELS.py` or the `early_flatten_noabc` identity. A full
  run is:

  ```text
  python3 src/tests/pypeline_tests/divider_continuity_bench.py \
    --out_dir /media/1TB/tmp/divider_continuity
  ```

  It scans the requested-frequency/first-plan frontier, deduplicates physical
  placement fingerprints, maps and exact-simulates every useful initial shape,
  then runs ordinary sweeps at 135.5, 180, and 210 MHz. Acceptance is based on
  the immutable final artifacts those normal sweeps actually return; rejected
  first guesses remain in `initial_plan_diagnostic_points`. Returned depths
  must be target-monotonic, each deeper returned schedule must gain more than
  the 1% noise band, the endpoints must remain within 1%, and the 45--53-stage
  point must be at least 10% faster than the 33-stage point. Every accepted
  artifact must pass the same 141-vector protocol/latency test and mapping
  checks as the main Divider harness.

  The accepted midpoint mechanism first measures the 48-slice/49-stage control
  at 164.69 MHz, then tries one generic chunked-MUX neighbor and returns
  49 slices / 50 stages at 194.22 MHz. Negative A/B evidence is retained for
  all exact subtract boundaries, periodic phase variants (see
  [`SYN_DESIGN.md`'s Divider acceptance entry](SYN_DESIGN.md#divider-acceptance-and-the-48-slice-intermediate-level)
  for what distinguishes a phase variant from a real level), stage-local
  ripple borrow, and chunking without the terminal MUX. `--plans-only`, `--continue`,
  and the exact-boundary options support diagnosis; none is a public compiler
  interface.

  The harness normalizes the trailing per-build content hash out of
  `_DUPLICATE_<hash>` names for placement deduplication (it is unrelated to
  physical placement identity); the source-coordinate fragment itself is
  compiler-sorted and does not need canonicalizing. Actual VHDL hashes and
  immutable mapped bytes are never canonicalized.
- `src/tests/pypeline_tests/divider_struct_mux_bench.py` -- focused opt-in
  verification of generic packed-MUX lowering and canonical delay caching. Its
  arithmetic fixture wraps `left_eff` and the loop-carried `remainder` in a
  one-field 32-bit struct while leaving ports, arithmetic, quotient behavior,
  and the 180 MHz goal unchanged. Run it with an empty caller-selected output
  directory (the harness creates an isolated empty path-delay cache inside):

  ```text
  python3 src/tests/pypeline_tests/divider_struct_mux_bench.py \
    --out_dir /media/1TB/tmp/divider_struct_mux
  ```

  The acceptance requires 49 slices / 50 stages, timing met within 1% of the
  194.22 MHz plain-integer result, schema-5 trace evidence for 32-bit midpoint
  splitting including the terminal wrapper MUX, all 141 functional vectors,
  complete mapped topology, and only the canonical `MUX_uint32_t.delay` plus
  timing sidecar in the cache. The accepted run measured 194.2227 MHz and
  recorded 17 wrapper-MUX chunk placements. `--continue` reuses completed
  evidence and `--diagnostic` prints failures without changing the verdict.

  Fast unit tests separately cover recursive packed widths, aggregate SLV
  rendering/reconstruction, scalar and aggregate cache-key equivalence,
  collapsed-mode compatibility, and the exception that makes built-in typed
  MUXes cacheable while leaving unrelated user functions non-cacheable.

- `src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py` -- fast
  unit coverage for typed placement lowering and mini-sweep boundary
  coalescing. It builds synthetic serial, fanout, fanin, alias, and
  intervening-operation graphs without an external synthesis tool, proving
  that a repeated helper chain uses one input-or-output bank per direct edge,
  respects `FUNC_NO_ADD_IO_REGS`, and fingerprints the selected lock banks.
  It also covers synchronized parallel-output and bit-internal frontiers,
  rejects serial peers, proves a provisional bit frontier may move together
  to one equal-width physical unit, and preserves a cheaper coherent ancestor
  boundary. The floor/bit-cap tests cover grouped physical fingerprints and
  atomic removal of a non-deepening boundary group. A dedicated case covers
  two peer leaves each collecting two crossing bit requests -- the shape
  that once crashed a real build
  (`src/tests/pypeline_tests/inst/typed_placement_alignment_test.py`, run
  under `native_vs_vhdl_sim_tests.py`): both leaves' realized boundaries
  move together off the one-cut
  prediction their groups were stamped with when formed, and
  `SUMMARIZE_PLACEMENT_GROUPS` must accept that coherent move while still
  rejecting a genuine split (members realizing on different units) or a lost
  member. Two more cases confirm `CHUNK_SELECTED_MUX_OUTPUT_BANKS` carries a
  group's identity through its same-depth lowering and leaves a group alone
  when only some of its members clear the chunking width gate.
  Full WireGuard synthesis remains the integration/physical QoR gate.

- WireGuard integration (opt-in, long-running) -- from a generated-output-free
  copy of `wireguard-fpga/3.build/pypeline_build`, run
  `PYPELINEC=<repo>/src/pypelinec ./build.py --shared --sim --syn_tb`.
  The accepted result passes cocotb/GHDL and Vivado confirmation at
  84.45 MHz against an 80 MHz goal, with 19 slices / 20 stages. Its schema-5 trace
  records ten half-sliced block steps and nine shared producer-output banks. A
  superseded baseline from before topology-aware boundary-lock selection (the
  older per-instance input-plus-output lock policy) is kept as a regression
  floor, not a target: that policy met 80 MHz only at 30 slices / 31 stages,
  against a failing 62.3 MHz at 40 slices / 41 stages -- the current result
  must never regress past this older, strictly worse shape.
- `src/tests/c_tests/test_builds.sh` -- legacy smoke-build script for the C frontend
  (`.c` designs under `examples/`), independent of this Python suite.

## History

Why things are the way they are. Entries are keyed by **topic, not date** — when
something changes, revise the entry that owns that topic rather than adding a new
one. Keep a fact here only if it still changes a decision today: an alternative
someone would otherwise retry, or a measurement that is still a live regression
reference.

### Why there is no `vhdl_sim` category

A `vhdl_sim` category once existed: self-checking designs run through `--cocotb
--ghdl`, proving each sim self-checks on its own. It was removed rather than kept
alongside `native_sim`, because every one of its entries turned out to be the same
source file as a `native_sim` entry with `--cocotb --ghdl` added -- so all 14
collapsed into one `native_vs_vhdl_sim` cycle-diff test each. That merge is
strictly stronger, not just smaller: a cycle-diff test proves the native and VHDL
sims *agree*, where the two separate tests it replaced only proved each one
passed on its own (which two independently-buggy-but-matching sims could still
do). Adding a new `vhdl_sim`-style test today would be a step backward for the
same reason -- fold it into `native_vs_vhdl_sim_tests.py` instead.
