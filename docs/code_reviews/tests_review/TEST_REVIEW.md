# Pypeline HDL test-suite review and reorganization proposal

Written for: you, as the basis for reorganizing the suite.

The suite's main problem is that selecting a feature does not reliably select the right execution modes or a predictable amount of work. Most small regression tests still make sense. The largest improvement will come from separating fast contracts from expensive real-build/application checks, then sharing or removing demonstrably repeated builds. Removing a large number of tiny tests would save little and risk losing useful regressions.

This source review is pinned to commit `ddd87701`; provenance is recorded under [History](#history). **No tests were run; compiler, test and registration sources were left unchanged.** Recommendations below are proposed work. Historical PASS/FAIL labels and durations are evidence from a retained partial run, not results for this commit.

The inventory was checked against all 454 evaluated registrations, 114 supporting-file rows, 1,271 case declarations and 443 source hashes; its local source links resolve. This checks document completeness and snapshot consistency, not test behavior.

The companion [TEST_INVENTORY.md](TEST_INVENTORY.md) lists every registered invocation, its purpose, execution mode, cost evidence and recommendation. It also accounts for supporting files and named test-case declarations. [REVIEW_MANIFEST.json](REVIEW_MANIFEST.json) retains exact commands, environment, dependencies, timeouts and source hashes. The existing [suite reference](../../pypeline_TESTS.md) remains the guide to current behavior; this document identifies places where implementation and prose disagree.

## 1. Recommended order of work

| Priority | Change | Benefit | Coverage condition |
|---|---|---|---|
| P0 | Fix exact-name/index selection and make filtered plans inspectable | A targeted command runs the intended tests | Preserve category-qualified identities; test selectors without invoking compilers |
| P0 | Record duration, mode, feature, tool and process-resource metadata | Fast/focused/deep runs become explicit and predictable | Unknown-cost tests remain visible and are measured, not silently excluded forever |
| P1 | Separate expensive FSM, RAM, PDW and board integration from routine checks | Largest reduction in routine waiting | Keep deep integration on scheduled runs and changes to the affected feature |
| P1 | Remove the extra scheduled stream-FSM synthesis job after preserving its evidence | Avoid an entire repeated real build | The scheduled native/GHDL job must prove it used device_models and still exercises long generated filenames |
| P1 | Split large mixed-cost files and use one local build for multiple compatible assertions | Short targeted runs without discarding cases | Preserve cold/warm, seed, process-isolation, mode and target distinctions |
| P2 | Introduce an HDL compile lane for legality-only fixtures | Avoid timing/mapping work where syntax/types are the actual contract | Retain representative Yosys/GHDL-plugin synthesis tests; compile success does not prove synthesizability |
| P2 | Fill the specific oracle gaps below | Better confidence with small tests | Add boundary cases to existing feature fixtures where possible |
| P3 | Move files into feature directories and generate reference tables | Easier navigation, less documentation drift | Do this after stable IDs and selection work, so moves do not obscure functional changes |

Do not begin with a mass file merge or deletion. First make the suite selectable, establish what each selected run proves, and retain a before/after coverage ledger.

## 2. What is actually in the suite

The refreshed registry has **454 invocations** across **17 nonempty categories**: **434 default runs** and **20 opt-in known-issue runs**. There are **53 names reused across categories**; those are often valid different modes of one design. The directory contains **425 source/support/evidence files**, of which **311** are direct registration targets and **114** are fixtures, harness files, benchmarks or evidence. Registered examples outside the directory are included in the inventory too.

All `inst/*_test.py` files currently have an actual registration. That does not mean all their assertions run. The case index contains **1,271 top-level `test_*` declarations**, including **15 HDL MAIN declarations**. A compiler registration imports a design as `pypeline_design` and skips its `__main__` block. Native `sim_call`, multi-MAIN native simulation, graph inspection, HDL compilation, cycle comparison and synthesis are distinct contracts. They should be represented explicitly in selection metadata.

The latest refresh adds `stateless_caller_sim_state_known_issue`, `global_wire_unshared_readback_known_issue`, and `scoped_operator_registration_known_issue`. These expose same-MAIN instance isolation, package emission without shared wires, and scoped operator specialization. Keep them: the superficially related factory-MAIN, shared-wire and generic-operator tests do not cover these shapes. The scoped-operator wrapper currently bundles top-level scope and shared-callee scope; split them into independently selectable checks when fixing those bugs, and exercise both caller orders.

The RAM QoR benchmark is a special case: although named `auto_pipeline_ram_qor_bench.py`, its bounded 64K/three-latency/one-seed subset **is** registered in `build_report_open_tools`. Other divider/operator/tool-comparison benchmarks are manual. Preserve this distinction when reorganizing.

## 3. Runtime evidence and its limits

The retained [timing records](REVIEW_MANIFEST.json) from the historical run log supply **367 durations**, totaling **32,745.3 summed test-seconds (9.10 h)**. These are elapsed durations under concurrency, not CPU usage or full-suite wall time. Job count, concurrent workload and full cache provenance are unavailable. The data excludes all build-report categories, vendor synthesis other than device_models, multi-clock, known issues, `pdw_tb`, and some later additions. **87 current registrations have no historical sample.**

| Category | Timed / current runs | Sum of old durations | Share of measured sum |
|---|---:|---:|---:|
| native_vs_vhdl_sim | 73 / 74 | 22,052.9 s | 67.3% |
| synth_device_models | 67 / 67 | 5,672.1 s | 17.3% |
| unit | 51 / 53 | 2,708.5 s | 8.3% |
| elab_introspect | 32 / 34 | 1,107.9 s | 3.4% |
| native_sim | 124 / 125 | 1,080.6 s | 3.3% |
| elab | 20 / 20 | 123.3 s | 0.4% |

The **15 native/GHDL entries whose names contain `auto_fsm` cost 16,377.7 s**, or **74.3% of that category**. Across measured categories, the 30 names containing `auto_fsm` account for **19,892.8 s (60.8%)**. This is an explicitly name-based grouping; composition/cache tests without that string add further FSM-related work, and unmeasured build reports are absent.

| Expensive invocation | Old elapsed time | Interpretation |
|---|---:|---|
| native_vs_vhdl_sim:self_check_auto_fsm_poly1305_test | 6,617.6 s, FAIL | Application-scale epilogue; log empty, cause unresolved |
| native_vs_vhdl_sim:self_check_auto_fsm_poly1305_prologue | 2,969.6 s | Different kernel; not redundant with epilogue |
| native_vs_vhdl_sim:self_check_auto_fsm_split_test | 2,721.0 s | Forced descent and split arithmetic |
| unit:auto_fsm_unit_test | 1,648.3 s | Real parsing/scheduling inside a nominal unit category |
| native_vs_vhdl_sim:self_check_auto_pipeline_ram_selected_plan_vivado | 1,226.0 s | Target-specific selected-plan replay and behavior |
| synth_device_models:float_ops_div_test | 1,068.1 s | Large unrolled float divider, build-only oracle |
| native_vs_vhdl_sim:self_check_auto_fsm_pipelined_unit_test | 943.2 s | Shared pipelined-unit latency and stalls |
| native_vs_vhdl_sim:self_check_auto_fsm_test | 747.6 s | Basic real scheduled FSM |
| native_vs_vhdl_sim:self_check_stream_auto_fsm_test | 734.2 s | Scheduled stream handshake and backpressure |
| native_vs_vhdl_sim:self_check_auto_fsm_select_share_test | 676.3 s | Indexed compound selection and sharing |

The first six rows account for **16,250.6 s (49.6%)** of the measured total. Moving their heavy cases out of routine feedback changes when that work runs; it does **not** save that time in an exhaustive run. Keep small witnesses for their contracts and trigger deep versions for relevant changes.

The current `area_model_test` source has already replaced the old failing absolute `MAE < 150` assertion with a per-bit residual `< 10` check. The old log's 1.5-second FAIL remains historical evidence, not an asserted present failure. The broader isolation concern remains: the calibration reads the mutable committed cache tree. Use a fixed, versioned calibration dataset for a deterministic unit test, with a separate whole-cache/model acceptance check. Do not merely loosen limits further.

The Poly1305 epilogue output log is zero bytes. The source comments mention much lower idle timings and severe contention. There is insufficient evidence to call the recorded failure an OOM, timeout or compiler bug. Capture launch metadata, child return codes and unbuffered progress before the next targeted reproduction.

Documented costs, kept separate from measurements: latency-memory builds 14–25 minutes; region minisweep/memory wrapper 6–14 minutes; minimum-area verification 840–1800 seconds; design-parameter pass-2 case and latency-sized FSM build about five minutes each; VGA donut about 30 minutes. `pdw_tb`'s roughly 9000-second projection was for an older CORDIC configuration, whereas the current default is ROM and its liveness deadline has just doubled. Do not budget today's PDW run from that old projection.

## 4. Fix targeting before changing coverage

[common.filter_tests](../../../src/tests/pypeline_tests/common.py#L503) has three relevant behaviors:

1. Exact selection constructs `{t.name: t}`. A reused name silently selects the last entry. For example, the default ordering puts `native_sim:ram_test` after `synth_device_models:ram_test`, so `-t ram_test` selects only the native one. Reordering categories can change that result.
2. `--list` prints `submission_order(tests)`, which moves `long_pole` entries first, but numeric `-t N` indexes the unsorted list. At this snapshot, displayed index 0 is the Poly1305 epilogue; `-t 0` selects `synth_vivado:stream_multi_cycle_test`.
3. `--list` returns before applying `-t` or `-k`. It cannot currently preview those filters. `-k` is a single name substring, not a dependency or feature selector.

These findings come from reading the selector and constructing registration lists only; no test command was launched.

Add an unambiguous stable ID, initially `category:name`, and reject ambiguous unqualified names with the matching IDs. Apply filters before rendering or execution, use the same ordered plan for listing and numeric selection, and prefer stable IDs over numbers in documentation. A `--plan`/JSON manifest should show why each test was selected, its modes, required tools, estimated cost and any stronger selected run that subsumes it.

Strengthen [registration_audit_test](../../../src/tests/pypeline_tests/inst/registration_audit_test.py). It currently regex-scans quoted filenames, including comments, and accepts a matching basename anywhere in several directories. Audit evaluated `Test` objects instead: unique IDs, real command paths, category-to-module routing, fixture ownership, declared capabilities and entrypoints that actually execute Python case functions. A comment mentioning a filename must not satisfy registration. The existing runner already detects stray categories; reuse that logic rather than maintaining a second list.

## 5. Duplication: what can be removed, and what should stay

### High-confidence repeated work

| Candidate | Action | Old cost available | Required preservation |
|---|---|---:|---|
| synth_device_models:self_check_stream_auto_fsm_test | Remove this build-only invocation after strengthening the scheduled comparison's evidence | 409.0 s | The native/GHDL scheduled comparison already prepares the same device_models build; retain the generated-filename regression and explicit backend confirmation |
| 16 native-only self-check registrations also present in comb cycle comparisons | Keep them selectable for tool-free/fast feedback; omit them from a combined plan that includes their native/GHDL counterpart | 24.1 s total | Match fixture, mode, parameters, environment and assertions; do not apply this rule to ordinary Python `test_*` entrypoints |
| pipelinec_native_sim_test and wire_discovery_passthrough_native_sim_test | Consolidate redundant CLI smoke after keeping one asserted entrypoint contract | 0.8 + 0.7 s | Retain direct runner discovery coverage and CLI forwarding/error behavior elsewhere |
| self_check_bit_math_test | Merge its constant cases into the asserted bit-math fixture, then remove the extra native invocation | 1.0 s | Check every expected value; keep nested_truncate's actual GHDL regression |

The 16 subsumed native invocations are `self_check_counter_test`, `self_check_fifo_test`, `self_check_stream_auto_pipeline_ii1_test`, `self_check_ram_test`, `self_check_loop_unpack_test`, `self_check_auto_fsm_comb_test`, `self_check_stream_auto_fsm_comb_test`, `struct_ctor_positional_test`, and the global-wire `partial_field`, `read_write`, `split_driver`, `readback`, `hier_writer`, `cond_driver`, `array_split`, and `dynamic_index_write` tests.

All four rows together represent only **435.6 historical test-seconds (7.26 minutes, 1.3% of the measured sum)** before replacement overhead. This is worthwhile cleanup, but it will not turn the exhaustive suite into a fast one. Wall-time savings may be smaller or differently distributed under concurrency.

### Consolidate setup while retaining the cases

- **Variable references:** `var_ref_test` and `if_test` contain the same ten base access shapes with and without conditions. Their two synthesis entries cost 34.3 and 45.4 seconds. Use shared design factories and one coherent compilation group, retaining unconditional writes, conditional false paths, mixed-granularity updates and the native nonzero-condition test. The 79.7 seconds is the current combined cost, **not** a savings estimate; the logic still needs compilation.
- **Global-wire semantics:** the small field/readback/conditional/array/hierarchy cases are good candidates for a shared HDL testbench compilation. Preserve named per-case output, independent wire ownership, fresh state, completion assertions and all distinct hierarchies. The new *unshared* readback reproducer must remain a separate no-shared-wire design; merging it with shared-wire cases would mask its failure.
- **Generated-name tests:** share process-launch and VHDL-comparison utilities among `generated_naming_build_test`, `var_ref_naming_test`, `duplicate_collapse_naming_test` and reader-order checks. Retain two explicit hash seeds, fresh-process tests, same-directory stale-input reuse and layout-changing reparse as different scenarios. One generic repeat-build is weaker.
- **FSM integration:** combine compatible schedule/unit-count assertions from `auto_fsm_latency_test` with a scheduled behavior fixture, and consider a warm-copy cache assertion using a preserved build from that integration job. A passing warm rebuild does not prove zero synthesis calls; retain explicit counters/log assertions. Do not replace `warm_copy_no_resynth_test` with a smaller fixture until it still changes package types and first-use built-in attribution across passes.
- **Tiny legacy smoke fixtures:** fold `old_sw_lib_ops` into operator lowering while retaining its mixed-width comparison; fold the helper-depth clock-inference and clock-pin smoke shapes into explicit parser/top-level assertions. There is no reason to lose those shapes just to reduce file count.

Only reuse a build when compiler/design bytes, parameters, backend/part, constraints, seed, build mode and relevant cache state match. Use immutable artifacts and private simulation directories. Fresh/cold/warm/cross-directory tests exist specifically to vary these conditions; global fixture reuse would invalidate them.

### Similar tests that are not duplicates

| Family | Distinction to retain |
|---|---|
| AUTO_FSM passthrough versus scheduled | Comb verifies tag forwarding and latency-agnostic stimulus; scheduled mode exercises emitted state machines and shared units |
| FSM constants / arrays / split / pipelined units / selection | Constant-width cleanup, aggregate mux shape, forced descent, multi-cycle completion and sharing each fail differently |
| Abstract area / real area / control-path comparisons | Mapped cell count, physical square-micron area and PyRTL-calibrated control timing are different oracles |
| Fixed RAM / selected RAM / source PART / CLI PART / Vivado / ECP5 | Constructor timing, hardware geometry, plan installation and physical mapping differ |
| `lut_atan2` five invocations | Native independent numerical checks; default HDL; 40-bit PDW input; reciprocal-slow and angle-slow latency orderings. Total 725.7 s, but not five equivalent tests |
| `self_check_dsp_rom_swap` | Opposite ROM latency ordering is deliberate alignment coverage |
| `reg_aug_assign` direct / convergence / GHDL | Typed rewrites, repeated evaluation before a clock edge and emitted hardware each have their own failure mode |
| `sweep_evidence_test` and seed777 | Seed-dependent nondeterminism is the point |
| Host generator versus host build | A correct generator does not ensure the CLI exports the right usable file |
| Global FIFO/instance/factory-MAIN comb diff versus sky130 synthesis | Simulator legality/behavior does not prove synthesis acceptance; 68.1 s across the three extra synthesis jobs is a tradeoff, not a proven duplicate |
| AUTO_COMB area/delay stream synth versus comb diff | Contrary to the early handoff, both synth entries are **non-comb**; they cost 29.9/24.2 s and are not identical to the comb comparison |
| Backend float32 matrix | Same source across tools deliberately exercises different backend adapters and targets |

## 6. A cheaper HDL legality lane

There is already an emission path: `pypelinec ... --comb --no_synth` writes fixed/comb HDL without a timing sweep. [generated_naming_build_test](../../../src/tests/pypeline_tests/inst/generated_naming_build_test.py) and [multi_clock_ghdl_test](../../../src/tests/pypeline_tests/inst/multi_clock_ghdl_test.py) demonstrate GHDL import/elaboration using the emitted file list. Factor that into a shared compile helper; no new compiler mode is required for the basic idea.

Start with VHDL identifier, port/type, aggregate-layout and interface-specialization regressions whose stated failure is illegal HDL: `underscore_name_test`, `array_compare_bracket_name_test`, `interface_factory_two_widths_test`, and selected language/serializer fixtures. Use the compiler's emitted ordered file list, actual emitted top name, VHDL-2008 and required RAM compatibility flags; support file lists without oversized single shell arguments. Assert that the expected entities and observables exist, so trimming does not make an empty design pass.

There are **54 direct `--comb` device_models registrations costing 3,440.8 s** in the old run. This is a candidate pool, not a claim that all 54 can lose synthesis. It includes float division, RAM, raw VHDL, library generation and examples with different requirements. The pool excludes non-comb AUTO_COMB stream tests. Measure a pilot set before projecting savings:

`actual saving = old mapped-build elapsed − new emit-and-GHDL-compile elapsed`

Keep real synthesis for memory inference/resource usage, raw-HDL technology acceptance, operator lowering, timing closure, MCP constraints, physical area, bitstream generation and representative end-to-end library builds. GHDL analysis alone does not cover the Yosys/GHDL-plugin frontend, unsupported synthesis constructs or mapping regressions.

## 7. Split cost from test category

Use three routine lanes plus explicitly requested issue/QoR work. Retain categories as execution/tool facets rather than using them as a promise about cost.

| Proposed lane | Contents | Invocation policy |
|---|---|---|
| Smoke | Small compiler/native contracts and a few representative HDL checks | Every relevant change; target a few minutes on a declared reference machine, then calibrate from actual results |
| Focused | All contracts for selected features, including representative real builds | Before completing a feature change; tool/backend checks only when affected |
| Deep | Large applications, extensive schedules, dense numeric sweeps, physical backend matrices, full QoR comparisons | Scheduled/merge gates and changes that touch those contracts; explicitly selectable locally |
| Issue/manual | Known bugs, setup-blocked backend probes and full opt-in benchmarks | When investigating the issue/backend or assessing QoR |

Suggested metadata on `Test` (proposal, not implemented): stable ID; `features`; `layer`; `tier`; explicit backend/part; capabilities including GHDL/cocotb and actual backend discovery; estimated duration plus measurement provenance; CPU/memory tokens; cold/warm/shared-cache requirements; and narrowly defined `subsumes` relationships. Keep mode/parameters as part of identity. Feature selection should form a union of required tests, deduplicate by stable ID, and print every selection reason. Unknown changed paths or shared compiler infrastructure should broaden the plan instead of silently selecting nothing.

Specific split points:

- `auto_fsm_unit_test`: separate synthetic cleanup/binding/serialization invariants from real-parse scheduling and large search cases. Preserve the current custom `check()` failure collection when moving cases.
- `auto_fsm_cache_test`, `auto_fsm_prefix_tree_test`, `plan_cuts_boundary_snap_test`: separate small deterministic cases from real parses and large stress matrices. Together with `auto_fsm_unit_test`, these cost 2,310.9 s, **85.3% of measured unit time**.
- `auto_comb_area_opt_test`, `auto_comb_delay_opt_test`, `double_parse_file_test`: split constructor/native or small graph checks from expensive full elaboration/reparse groups. Preserve source-freeze and process-global registry isolation.
- `design_params_build_test`: CLI errors, listing, reporting and native parameter propagation separately from the five-minute pass-2 build.
- `auto_pipeline_region_minisweep_test`: distinguish initial geometry/lock correctness from the extended memory replay/stale-edit/higher-goal sequence.
- `lut_atan2_test`: retain table-boundary/quadrant/degenerate/extreme/width witnesses in a fast sample; move exhaustive dense numeric sweeps into deep. Keep both unequal latency directions in HDL; only batch them if fixture interactions remain controlled.
- `pdw_tb`: retain the whole application oracle; add a deterministic reduced scenario exercising one accepted pulse, one rejection, packet/record pairing and relevant stalls. A smoke run that simply cuts the cycle count before the final checker is not a valid replacement.

Add case-level selection to the Python harness, then migrate suitable custom entrypoints. Blindly auto-running every `test_*` name would try to call the 15 HDL MAIN definitions as zero-argument tests. Require an explicit test-case marker or exclude HDL entrypoints, reject empty selections, and preserve a named failure for each case. Do not change tests whose fresh-process import/operator-registration state is part of their contract into one long-lived shared process.

## 8. A change-to-test map

This is a starting map for explicit feature tags, not a claim that names alone capture all dependencies. For each change, select the reproducer/new case, cheap contracts, and the matching integration oracle. Broaden for cross-cutting compiler changes; do not launch untouched vendor sweeps by default.

| Changed area | Fast/structural selection | Focused integration / deep escalation |
|---|---|---|
| `pypeline.py` types, casts, registers, operator dispatch | bit_math, cast*, reg*, struct_ctor*, sim_elab_operator_parity, soft_ops, operator_scope | Relevant GHDL width/truncation/loop cases; scoped-operator and stateless-caller reproducers where affected |
| `PY_TO_LOGIC.py` imports, naming, variable refs, wires | conditional_import, importfrom, local_shadow/binding, loop_iter_naming, global_wire_errors, name_index, two_factory_wrappers | Small GHDL var-ref/readback/name cases; repeated parsing and generated-name stability if discovery/identity changes |
| `pypeline_sim.py` / simulator internals | sim_loop_reg_state, reg_aug_assign, feedback_reeval, sim_model/FIFO/RAM convergence, factory_main_sim | Counter/FIFO/loop/width parity; fixed/pipelined region comparisons for timing-model changes; same-MAIN stateless isolation issue |
| `AUTO_FSM.py`, FSM operator transforms | transforms, attribution, small binding/cache/purity/variable-index cases | One scheduled raw and stream oracle; specific constants/array/selection/pipelined-unit/split test; Poly1305 and area matrix for scheduler/codegen/search changes |
| `AUTO_PIPELINE.py`, `SWEEP.py`, `RAW_VHDL.py`, pipeline maps | typed placement, boundary snap, floor/caps, harvest, region planning, scripted sweep evidence/recovery/cross-MAIN, history, scope | Typed alignment, fixed/discovered latency, planless/unpipelinable, one small real sweep; memory and full applications when replay/planning semantics change |
| `VHDL.py`, emitted names/packages | generated_naming, generated_vhdl_stability, port maps, isolated top, relayout | Compile fixtures plus representative cycle parity; unshared-readback and signed-prefix issues; selected RAM/MCP/backend acceptance when relevant |
| `SYN.py` caches or identity | device_models_sta identity, generated stability, latency-memory/store unit cases | syn_cache pyrtl/netlist, warm-copy no-resynth, var-ref naming; cold/warm isolation matched to the changed contract |
| RAM and `AUTO_PIPELINE` RAM planning | ram/stream_ram native, auto_pipeline_ram contracts, target boundary cases | Fixed/selected-plan parity; BRAM mapping on the changed backend; deep size/seed frontier only for planning/QoR changes |
| stream/interface/AXIS library | FIFO/skid/serializer/type/width-converter tests, II=1 and independent stream metrics | Relevant partial-frame/backpressure HDL composition; application PDW only when its composition is affected |
| DSP library | Relevant exact-integer/math oracle and stream throughput | NCO/log ROM or atan2 latency/width parity; small CORDIC HDL oracle once added; full PDW for composition changes |
| clocks/global FIFO/instances | clock_api, clock_domains_elab, async_fifo_elab/path, clock_mhz, factory/global API/path checks, native refusal | Named clock pin, two-clock GHDL FIFO, affected ECP5/Vivado clock constraints/timing; future ratio/stall cases |
| `DEVICE_MODELS.py` / area | STA fixtures, recipe/cache identity, pinned area fit | One small real mapped build plus relevant area/QoR gate; full divider benchmark only for model/recipe acceptance |
| a vendor backend | Its config/report/constraint fixtures; e.g. openxc7_unit or vivado_version | `sweep_float32_<that tool>` plus backend-specific RAM/MCP/clock/bitstream test; other tools only for shared adapter changes |
| runner/registrations/docs | Selector/audit/verdict/dependency checks; doc_links/path_portability where applicable | Tiny synthetic subprocess canaries; no application synthesis needed |

Safe examples using **existing** selection syntax, for future implementation work (none were run for this review):

```bash
python3 src/tests/pypeline_tests/run_all.py --category unit -t device_models_sta_test -j 1
python3 src/tests/pypeline_tests/run_all.py --category native_sim -t ram_test -j 1
python3 src/tests/pypeline_tests/run_all.py --category native_vs_vhdl_sim -t call_arg_width_test_comb -j 1
python3 src/tests/pypeline_tests/run_all.py --category multi_clock -t multi_clock_ghdl_test -j 1
python3 src/tests/pypeline_tests/run_all.py --category known_issues -t scoped_operator_registration_known_issue -j 1
```

Category qualification avoids current duplicate-name ambiguity. `--category ... --list` lists that category; adding `-t`/`-k` to the list command does not currently narrow the displayed plan. Proposed feature/tier/plan flags are deliberately not presented as runnable commands.

## 9. Missing or weak coverage to add

| Gap | Smallest useful addition | Why existing tests do not settle it |
|---|---|---|
| Primitive bit operations | Independent vectors for typed zero, max, sign/width preservation, rotate by 0/width/over-width, endian pack/unpack and invalid widths; one HDL self-check | bit_manip_test only elaborates. Native implementations now exist; the handoff's NotImplementedError claim is obsolete. Soft barrel rotate tests exercise a different implementation |
| CORDIC hardware | A small HDL compile and golden-output latency/CE check, preserving quadrant/degenerate edges | cordic_test is native-only; old 21-minute PyRTL synthesis is not evidence that a small GHDL check is too expensive |
| Nested multi-writer global wires | Re-run the specific missing comb GHDL scenario when implementation work begins; retain an explicit reproducer if it fails | Existing comment says the combination was not rechecked; plain synth/native success does not establish cycle parity |
| Discovered-latency stream AUTO_PIPELINE | Minimal real sweep with FIFO resized from the discovered latency, then GHDL order/stalls/II checks | native_pipelined_sim_test covers native only; fixed-latency II=1 tests do not reproduce the discovery/reparse path |
| Float divider numerical behavior | Reduced-format or short float32 HDL vectors against an independent documented numeric contract | float_ops_div_test only builds a large divider; successful synthesis is not a value oracle |
| Async FIFO behavior | Two-clock deterministic ratios/phases, producer-faster and consumer-faster cases, full/empty boundaries, wraparound, stalls and independent instances | Current two-clock GHDL check is a fixed 125/100 MHz progress/order scenario; API/path checks and synthesis do not cover all traffic states |
| Native test functions hidden behind compiler registrations | Decide intent for keyword_call and four sweep helpers; add asserted values or explicitly mark manual | Those five `test_*` helpers are invoked only from `__main__`; current elab/synth entries never execute them. The sweep helpers currently just print |
| Harness selection/verdict integrity | Small data/subprocess tests for duplicate IDs, ambiguous names, list/filter agreement, empty selections, timeout/dependency/XFAIL semantics | Current registration audit checks filenames, not selector behavior. cocotb_verdict covers simulator result reporting, a different layer |
| Backend failure diagnosis | Tiny saved-report/constraint fixtures per adapter, plus one real changed-backend sweep | A float32 full build is a costly way to discover a parser/schema error; several adapters have little focused coverage |

For async behavior, add reset/restart only where the FIFO API has a defined reset contract. A digital GHDL test verifies protocol behavior; it cannot establish physical metastability reliability. Do not try to add native multi-clock parity while native simulation intentionally refuses multiple clocks.

The newer three known-issue tests already fill previously unrepresented shapes. The next task there is to make the intended failure precise and promote fixed reproducers into the normal feature lane, not add another broad native test that misses the same instance/ownership boundaries.

## 10. Harness reliability, resource limits and evidence

The following are small infrastructure changes that help runtime and interpretation:

- **Track real resource use.** `run_all -j` limits outer tests, but the native/GHDL driver launches two compiler processes and the multi-clock Vivado wrapper launches XPM/builtin builds together. Compiler/backend `-j` adds another layer. Use CPU/memory/tool tokens or explicit inner-job caps; scheduling every expensive test first can worsen contention. Keep duration-based scheduling within the available resource budget, rather than relying on a Boolean `long_pole` forever.
- **Terminate whole child trees.** The current runner kills its immediate `Popen` on timeout/interruption. Wrappers can have synthesis/simulator grandchildren. Use isolated process groups with platform-appropriate termination and verify cancellation using tiny subprocess fixtures. This is a source-level gap, not a claim that an orphan was observed in this review.
- **Capture usable failure evidence.** Write launch command, source/commit, environment overrides, tool versions, status, return code and duration to JSON; flush progress promptly. Preserve logs for abnormal exits. For retained benchmarks, record exact final HDL and netlist identity, following the existing divider benchmark's approach.
- **Distinguish setup from regressions.** Current `requires` is an uneven PATH-only check, while compiler backends can use configured fallback locations. Use the same backend discovery as compilation. A requested required CI lane should report incomplete coverage when dependencies are missing; a zero exit with all tests skipped is not proof of coverage.
- **Make expected failures precise.** The common result object currently accepts any nonzero exit for `expect_fail=True`. A missing executable or unrelated assertion can therefore masquerade as the known bug. Verify a stable error signature or expected wrong artifact. Keep Gowin/Diamond license failures and the CC_TOOLS tool crash as setup/backend probes, separate from compiler semantic bugs. The finish/print-race reproducer is the exception with `expect_fail=False`; normalize its semantics deliberately rather than assuming all issue rows invert status.
- **Preserve evidence of actual synthesis.** `_check_syn_tool` requires a matching run for `synth_*`, but wrappers only reject a visible wrong tool. A silent wrapper can appear to satisfy a backend category without proving that backend ran. A structured child manifest should identify invoked/reused synthesis and its tool, including native/GHDL scheduled comparisons, which are not category-pinned by the same check.
- **Version timing data.** Store one result per stable ID, mode/parameters, source/tool version, cache policy and worker budget. Compute rolling median/high-percentile estimates only from comparable runs. Report compile, synthesis, native and HDL phases separately. Do not copy old durations into several comments as if they were stable properties.

## 11. Documentation and layout cleanup

Verified drift to fix alongside implementation:

| Location | Correction |
|---|---|
| AUTO_COMB composition docstrings | They say pipelined builds use PyRTL; registration uses device_models |
| sweep_comb / sweep_two_mains comments | They still describe PyRTL timing/no-attribution behavior; registered runs use device_models. Preserve any intended no-attribution check explicitly |
| native_vs_vhdl_ap / pipelined_main docstrings | Registration is in native_vs_vhdl_sim_tests, not synth_tests |
| auto_fsm_test docstring | No direct elab registration; distinguish native passthrough and wrapper-built scheduling |
| self_check_bit_math docstring | It is native-only, not registered in the HDL comparison. Native MAIN arguments are now supported, so the stated import rationale is also outdated |
| auto_fsm_unit timing prose | 615 s in registration, 358 s in reference and 1648.3 s in retained run; use provenance-tagged data, not “fast because no synthesis” |
| cordic / lut_nco comments | Their dedicated MAINs have no direct build registration. NCO does have separate DSP-ROM HDL coverage; do not label the entire feature untested |
| suite reference category prose | Unit/build_report are not accurate cost/tool guarantees; some wrappers emit HDL only |
| known_issues overview | There are now 20 entries; one uses normal semantics. Not every issue is a compiler bug; three are backend/setup failures |
| Efinity matrix docs | Reference says `-j 1`, current `SWEEP_FLOAT32_EXTRA_ARGS` supplies `-j 2`; make the cap an explicit reviewed resource setting |
| standalone synth/build_report docs | “all three” tool categories is stale; synth has six nonempty tools and build_report has four |
| area-model failure notes | Old absolute-MAE failure has a source correction; retain cache-isolation concern and do not present old FAIL as current |
| PDW runtime notes | Current ROM configuration and doubled liveness bound differ from the cited CORDIC projection |

Generate the registration/category/cost tables from one manifest. Keep handwritten purpose and rationale close to each feature, with an owner/issue link for special cases. This avoids a second giant hand-maintained registration list. The manifest's source hashes identify this review's snapshot; regenerate and re-review changed purposes rather than blindly treating generated prose as current.

A possible eventual layout:

```text
pypeline_tests/
  runner/                    # selection, capabilities, results and common helpers
  features/
    frontend/                # types, imports, naming, variable refs
    native_sim/              # convergence and instance state
    auto_pipeline/           # placement, replay, RAM planning
    auto_fsm/                # scheduler, emitted units, sharing
    streams/                 # FIFO, AXIS, interfaces and framing
    dsp/
    clocks/
    backends/
  fixtures/                  # only genuinely shared fixtures
  integration/               # full application and real-target compositions
  known_issues/              # expected-good reproducers plus failure signatures
  benchmarks/                # opt-in QoR drivers
  evidence/                  # versioned recipe/tool/source-linked measurements
```

Feature-local fixtures should usually stay with their feature instead of all moving into one shared directory. Preserve independent import modules and filename/line-sensitive naming cases during moves. Keep a compatibility ID/alias map so existing commands and issue references continue to work. Move the three top-level AUTO_FSM fixture files to clearly named fixture locations rather than relying on their being outside `inst/` to evade the filename audit.

## 12. Acceptance criteria for the reorganization

Implement in small reviewable changes:

1. **Selector and manifest first:** demonstrate every old `(category, name)` appears exactly once, ambiguous names fail explicitly, listing equals execution, and fixture paths are valid. Test this entirely with metadata and tiny subprocesses.
2. **Tags and lanes next:** produce a reviewable plan for a representative frontend, simulator, FSM, sweep, RAM and backend change. Show why each selected test is needed. Keep exhaustive selection available and list any exclusions.
3. **Then splits and deduplication:** record every moved/merged case, its independent oracle, old/new mode and preserving replacement. Re-run only affected cases/integration paths during each change. For important historical regressions, demonstrate that the preserving test still fails under the original bug or an equivalent targeted mutation.
4. **Pilot the HDL compile lane:** compare current real synthesis with emission+GHDL on a small legality-focused set. Keep synthesis canaries for acceptance classes compile-only cannot catch. Measure replacement time before claiming a saving.
5. **Only then move directories and regenerate docs:** maintain IDs and update exact fixture links; do not mix layout churn with scheduler or simulator semantics.

Success means a small change has a short, explainable test plan; every removed invocation has a named preserving oracle; important slow checks remain available in the right lane; tool/setup failures are distinguishable from regressions; and measured phase/job data shows where time was actually saved. No percentage reduction in full-suite wall time can be promised from the current partial, concurrent timing record.

## History

### Review provenance

The source review was completed on 2026-10-25 at commit `ddd87701a255e8e9de9383f94cf7814e4b0055b7`. Timings come from the 2026-10-22 partial run and are summed per-test elapsed time under concurrency, not CPU time or suite wall time. Worker count and full cache provenance were not retained. Exact commands, source hashes, timings and snapshot validation are preserved in [REVIEW_MANIFEST.json](REVIEW_MANIFEST.json). Moving these documents into the repository does not refresh the source review or establish current test status.

The original local timing log is `/media/1TB/tmp/global_inst/cat_run.log`. The zero-byte Poly1305 failure log was inspected at `/media/1TB/tmp/pypeline_run_all_ql580faa/native_vs_vhdl_sim/self_check_auto_fsm_poly1305_test/out.log`; these local artifacts are provenance references, not portable repository dependencies.
