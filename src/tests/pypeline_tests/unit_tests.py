#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure compiler-helper unit tests -- no design build (PARSE_FILE may be
called incidentally, but that's not what's under test). See
elab_introspect_tests.py for tests whose whole point IS parsing a design and
inspecting the resulting parser_state/FuncLogicLookupTable/raised errors.

Run standalone: python3 unit_tests.py [-j N]
"""

import sys

from common import INST_DIR, Test, main


def get_tests() -> list:
    tests = []
    # Global FIFO API: Fifo[T], global_fifo/global_sync_fifo, the stream-module
    # port helper and the FIFO MAIN generator's names.
    tests.append(
        Test(
            name="global_fifo_api_unit_test",
            category="unit",
            cmd=[INST_DIR / "global_fifo_api_unit_test.py"],
        )
    )
    # The sweep's view of a FIFO MAIN: paths inside it go to it alone, a path
    # leaving it to the user MAIN; WHY_NOT_SLICEABLE; the TIMING NOT MET name.
    tests.append(
        Test(
            name="global_fifo_path_unit_test",
            category="unit",
            cmd=[INST_DIR / "global_fifo_path_unit_test.py"],
        )
    )
    # The clock API: make_clock identity and port names (agreeing with the
    # back end's), clock conflicts, MAIN's clock forms, the ASYNC/VOLATILE/
    # clock markers, global_async_fifo and impl=.
    tests.append(
        Test(
            name="clock_api_unit_test",
            category="unit",
            cmd=[INST_DIR / "clock_api_unit_test.py"],
        )
    )
    # The sweep's and back end's view of an async FIFO: paths inside its
    # clk_cross instance go to the side MAIN of their clock; side MAINs, not
    # the crossing, are its MAINs; CLK_CROSS_USES_XPM per tool and impl=.
    tests.append(
        Test(
            name="async_fifo_path_unit_test",
            category="unit",
            cmd=[INST_DIR / "async_fifo_path_unit_test.py"],
        )
    )
    # Global instance API: Inst[f], the ports and wire type it derives from f,
    # its errors, the MAIN generator's source and names, and MAIN() checking
    # a user's name= where an instance's own MAIN name is not checked.
    tests.append(
        Test(
            name="global_inst_api_unit_test",
            category="unit",
            cmd=[INST_DIR / "global_inst_api_unit_test.py"],
        )
    )
    # The sweep's view of instance MAINs: paths inside one go to it alone; a
    # path leaving a stateful instance goes to the user MAIN, one into an
    # AUTO_PIPELINE instance to both; WHY_NOT_SLICEABLE; the TIMING NOT MET name.
    tests.append(
        Test(
            name="global_inst_path_unit_test",
            category="unit",
            cmd=[INST_DIR / "global_inst_path_unit_test.py"],
        )
    )
    # @MAIN registration for MAINs made in code: MAIN's forms and name=, the
    # default name, its errors, the duplicate-name message, native sim's name
    # map for build results and the MAIN-named ELABORATE_LIVE_ROOTS root.
    tests.append(
        Test(
            name="factory_main_api_unit_test",
            category="unit",
            cmd=[INST_DIR / "factory_main_api_unit_test.py"],
        )
    )
    # Wrapper suffixes can exceed the body-name budget; select the emitted name.
    tests.append(
        Test(
            name="isolated_top_name_test",
            category="unit",
            cmd=[INST_DIR / "isolated_top_name_test.py"],
        )
    )
    # Single-object factory results, callable return metadata, caches and ops bundles.
    tests.append(
        Test(
            name="factory_api_test",
            category="unit",
            cmd=[INST_DIR / "factory_api_test.py"],
        )
    )
    # Two pinned hash seeds: no sweep decision may depend on set iteration order.
    for name, seed in (("sweep_evidence_test", "1"), ("sweep_evidence_test_seed777", "777")):
        tests.append(
            Test(
                name=name,
                category="unit",
                cmd=[INST_DIR / "sweep_evidence_test.py"],
                env={"PYTHONHASHSEED": seed},
            )
        )
    tests.append(
        Test(
            name="added_latency_context_test",
            category="unit",
            cmd=[INST_DIR / "added_latency_context_test.py"],
        )
    )
    # Cold scheduling: only pipeline hierarchy, required primitives and MCP endpoints.
    tests.append(
        Test(
            name="synthesis_scope_test",
            category="unit",
            cmd=[INST_DIR / "synthesis_scope_test.py"],
        )
    )
    # Failed trims test fresh locks/MCP repairs; later opaque paths still refine.
    # Flattened device-model paths must retain multi-MAIN timing feedback.
    tests.append(
        Test(
            name="sweep_refinement_recovery_test",
            category="unit",
            cmd=[INST_DIR / "sweep_refinement_recovery_test.py"],
        )
    )
    # Native pipelined-region model of global wires: own-read view, delayed
    # AUTO_PIPELINE writes, nested-read refusal (no build)
    tests.append(
        Test(
            name="native_pipeline_region_test",
            category="unit",
            cmd=[INST_DIR / "native_pipeline_region_test.py"],
        )
    )
    tests.append(
        Test(
            name="auto_pipeline_ram_test",
            category="unit",
            cmd=[INST_DIR / "auto_pipeline_ram_test.py"],
        )
    )
    tests.append(
        Test(
            name="generated_naming_test",
            category="unit",
            cmd=[INST_DIR / "generated_naming_test.py"],
        )
    )
    # Native-sim vs. elaboration operator parity: the unary-negate widening
    # rule, matcher ("generic") registrations actually reaching sim, the
    # constant-vs-variable shift split that keeps a registered barrel shifter
    # from recursing, and the scoped-registration leak. Pure in-process
    # registry/SimVal work -- no design build.
    tests.append(
        Test(
            name="sim_elab_operator_parity_test",
            category="unit",
            cmd=[INST_DIR / "sim_elab_operator_parity_test.py"],
        )
    )
    # AUTO_FSM scheduler/code-generator unit tests: exact schedule, register
    # allocation, byte-identical generated source across re-elaborations --
    # not visible in a build log, would otherwise only be checked indirectly
    # by full synthesis runs. Calls PY_TO_LOGIC.PARSE_FILE incidentally.
    tests.append(
        Test(
            name="auto_fsm_unit_test",
            category="unit",
            # Measured 615 s, by far the longest test in unit -- the category
            # run_all.py submits LAST, since the other 20 finish in seconds.
            long_pole=True,
            cmd=[INST_DIR / "auto_fsm_unit_test.py"],
        )
    )
    # Legality/refusal proofs for selectors, unsigned adapters and closed pairs,
    # next-wider merge steps and trimmed measurement roots; measured 4.2 s.
    tests.append(
        Test(
            name="auto_fsm_transforms_test",
            category="unit",
            cmd=[INST_DIR / "auto_fsm_transforms_test.py"],
        )
    )
    # Stale source/target schedules, applied forced schedules, provenance,
    # serial unit characterization and search results reused across builds
    # (identical inputs only; stale delay files, pruning); measured 74 s.
    tests.append(
        Test(
            name="auto_fsm_cache_test",
            category="unit",
            cmd=[INST_DIR / "auto_fsm_cache_test.py"],
        )
    )
    # Ordered Vivado arcs, verified sky130 endpoint aliases, late selection, local
    # edge repair and measured pinned-unit stages; measured 1.3 s.
    tests.append(
        Test(
            name="auto_fsm_attribution_test",
            category="unit",
            cmd=[INST_DIR / "auto_fsm_attribution_test.py"],
        )
    )
    # Derived hierarchy estimates are measured before they decide forced
    # descent, array input elements render as indexes, a register-free MAIN
    # gets its scheduled FSM's clock enable, and pipelined helpers are not
    # blocked descents; measured 54.6 s idle, 102.5 s on a loaded machine.
    tests.append(
        Test(
            name="auto_fsm_prefix_tree_test",
            category="unit",
            cmd=[INST_DIR / "auto_fsm_prefix_tree_test.py"],
        )
    )
    # Pure-unit tests for the AUTO_PIPELINE .latency machinery
    # (AUTO_PIPELINE.HARVEST_AUTO_PIPELINE_LATENCIES grouping + divergence detection,
    # AUTO_PIPELINE.SEED_TIMING_PARAMS_FROM_PREVIOUS concrete region replay + call-site-change
    # detection, CANONICAL_CALLABLE_KEY determinism, latency cache/read-flag
    # behavior) against hand-built fixtures -- no design build involved.
    tests.append(
        Test(
            name="auto_pipeline_harvest_test",
            category="unit",
            cmd=[INST_DIR / "auto_pipeline_harvest_test.py"],
        )
    )
    # Constrained AUTO_PIPELINE regions (latency= / start_latency= /
    # max_latency=): count-targeted cut planning, plan trimming, cap
    # bookkeeping and hotspot-to-region attribution on synthetic landscapes.
    tests.append(
        Test(
            name="auto_pipeline_region_planning_test",
            category="unit",
            cmd=[INST_DIR / "auto_pipeline_region_planning_test.py"],
        )
    )
    # make_stream_auto_pipeline / DSP factory latency= / start_latency= /
    # max_latency= forwarding to the single core AUTO_PIPELINE: .latency
    # served per build mode, errors, identity, and native-sim cycle behavior.
    tests.append(
        Test(
            name="stream_auto_pipeline_latency_args_test",
            category="unit",
            cmd=[INST_DIR / "stream_auto_pipeline_latency_args_test.py"],
        )
    )
    # Design parameters: param() precedence (-D, env=, default), conversion
    # and choices errors, duplicate declarations, one resolution per process,
    # cpp-style injected globals and the post-import -D checks, per-parse
    # re-registration, and the report/--list_params/provenance records.
    tests.append(
        Test(
            name="design_params_test",
            category="unit",
            cmd=[INST_DIR / "design_params_test.py"],
        )
    )
    # The bottom-up value report: .latency read sites (direct and via a
    # library factory) and RECORD_LATENCY_PASS's read-vs-built rows.
    tests.append(
        Test(
            name="bottom_up_report_test",
            category="unit",
            cmd=[INST_DIR / "bottom_up_report_test.py"],
        )
    )
    # AUTO_MULTI_CYCLE: constructor/.latency/keys/read tracking, identity following
    # the cycle count, SYN constraint overrides + hash, SWEEP report matching
    # and grow-only feedback, elaboration + cache re-parse renaming, and the
    # unread-tag refusal -- no synthesis tool involved.
    tests.append(
        Test(
            name="auto_multi_cycle_unit_test",
            category="unit",
            cmd=[INST_DIR / "auto_multi_cycle_unit_test.py"],
        )
    )
    # Latency memory and --latency_hints (SWEEP.py "Latency memory"): hints
    # formats, profile verdicts, zero-clock subtree digests, goal/digest/part/
    # tool piece selection, per-piece recording, store layout and prune, lock
    # JSON round trips, winner RTL bytes, restored bounds/lower-goal floors, and a
    # dependent body-to-MCP resolution (two re-parses)
    tests.append(
        Test(
            name="latency_memory_unit_test",
            category="unit",
            cmd=[INST_DIR / "latency_memory_unit_test.py"],
        )
    )
    # Up-to-date builds (SIM.BUILD_INPUTS, SIM.BUILT_HARDWARE_IS_CURRENT) on
    # written records: which sources, -D values, settings, hint contents,
    # compiler and environment knobs make a build run again, and which
    # operational settings don't
    tests.append(
        Test(
            name="built_hardware_current_test",
            category="unit",
            cmd=[INST_DIR / "built_hardware_current_test.py"],
        )
    )
    # Pure-unit tests for readable, hierarchical canonical names of
    # factory-closure functions (_canonical_func_name/_callable_canonical_name)
    # against hand-built fixtures, plus a PARSE_FILE regression test for the
    # factory-closure ast_meta src_file/line fix.
    tests.append(
        Test(
            name="factory_closure_naming_test",
            category="unit",
            cmd=[INST_DIR / "factory_closure_naming_test.py"],
        )
    )
    # Meta-test: every inst/*_test.py file must be registered in some
    # category module (see the file's own docstring) -- catches dead test
    # files and stale registrations after a rename/delete.
    tests.append(
        Test(
            name="registration_audit_test",
            category="unit",
            cmd=[INST_DIR / "registration_audit_test.py"],
        )
    )
    # Meta-test: every markdown link/anchor in the repo resolves (in-page and
    # cross-file) -- catches stale doc links after a heading rename/move.
    tests.append(
        Test(
            name="doc_links_test",
            category="unit",
            cmd=[INST_DIR / "doc_links_test.py"],
        )
    )
    # Every src module imports first in a fresh interpreter (import cycles stay
    # import-time safe), a .py build needs no C preprocessor (#363), and a
    # build with no synthesis tool for its part falls back to --comb --no_synth
    # (re-elaborating a design that read a start_latency= .latency).
    tests.append(
        Test(
            name="src_module_import_test",
            category="unit",
            cmd=[INST_DIR / "src_module_import_test.py"],
        )
    )
    # Raw-HDL leaf split model: SPLIT_KIND classification (RAW_VHDL.
    # GET_LEAF_SPLIT_KIND/LEAF_MAX_SPLIT_SLICES) and the equal-width bit
    # allocator (RAW_VHDL._EQUAL_WIDTH_BITS_PER_STAGE_DICT) that replaced an
    # earlier, real-synthesis-disproven curve-inversion approach -- see the
    # test file's own docstring for what broke and why.
    tests.append(
        Test(
            name="leaf_split_unit_test",
            category="unit",
            cmd=[INST_DIR / "leaf_split_unit_test.py"],
        )
    )
    # SWEEP.PLAN_CUTS boundary-snap: prefer a real segment boundary over a
    # mid-segment cut within a bounded budget overrun, found necessary by
    # testing the real divider design against real sky130 synthesis (a low
    # cut count merged a SLICEABLE_1LL leaf into a neighboring stage instead
    # of getting its own boundary) -- see the test file's own docstring.
    tests.append(
        Test(
            name="plan_cuts_boundary_snap_test",
            category="unit",
            cmd=[INST_DIR / "plan_cuts_boundary_snap_test.py"],
        )
    )
    # Three bugs found during this session's audit, previously undetected:
    # SWEEP.AT_PREDICTED_FLOOR's missing upper bound (a floor-stop could
    # fire arbitrarily far above a stale/under-predicted floor),
    # SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS (restoring the best-seen result
    # never re-checked whether it actually met its goal before writing it
    # out), and RAW_VHDL.GET_LEAF_BIT_WIDTH + the SLICEABLE legal-unit cap
    # (a narrow leaf could accept far more cuts than its own width usefully
    # supports) -- see the test file's own docstring.
    tests.append(
        Test(
            name="floor_and_bits_cap_unit_test",
            category="unit",
            cmd=[INST_DIR / "floor_and_bits_cap_unit_test.py"],
        )
    )
    # sweep_history.json "final" record semantics: an assumed-met main is a
    # goal lower bound (never a measured fmax), a timing failure overrides the
    # outcome, confirmation runs and restored snapshots keep their own
    # provenance, unverified builds carry no verdict.
    tests.append(
        Test(
            name="sweep_history_record_unit_test",
            category="unit",
            cmd=[INST_DIR / "sweep_history_record_unit_test.py"],
        )
    )
    # SWEEP.AT_PLATEAU: flat measured fmax while cuts grow stops the sweep
    # even when the soft-floor prediction is wrong.
    tests.append(
        Test(
            name="sweep_plateau_unit_test",
            category="unit",
            cmd=[INST_DIR / "sweep_plateau_unit_test.py"],
        )
    )
    # SYN.PrimitiveDelayModel width fits, refusals and AUTO_FSM's rule to
    # measure only estimates near a state budget.
    tests.append(
        Test(
            name="primitive_delay_model_test",
            category="unit",
            cmd=[INST_DIR / "primitive_delay_model_test.py"],
        )
    )
    # SYN.PHASE build-phase timers: nested phases charge exclusive time, and
    # the end-of-build summary lists them.
    tests.append(
        Test(
            name="build_phase_timer_test",
            category="unit",
            cmd=[INST_DIR / "build_phase_timer_test.py"],
        )
    )
    # Typed operation-boundary/bit-internal placement and direct lowering.
    tests.append(
        Test(
            name="typed_pipeline_placement_test",
            category="unit",
            cmd=[INST_DIR / "typed_pipeline_placement_test.py"],
        )
    )
    # SWEEP.RANK_PATH_FUNC_CANDIDATES / RESOLVE_PIPELINABLE_HOTSPOT: critical
    # path attribution ranked candidates by summed matched-substring length,
    # which has no depth signal (every ancestor's name is a substring of a
    # descendant register's name) and so always favored the single longest
    # candidate name. Found for real on wireguard-fpga's decrypt path: a
    # long auto-generated interface-func wrapper name outscored the actual
    # on-path `chacha20_chacha20_block_step`, so the sweep declared the path
    # unpipelinable (feedback_vars on the wrapper) and stopped 3x too early
    # -- see the test file's own docstring.
    tests.append(
        Test(
            name="path_attribution_test",
            category="unit",
            cmd=[INST_DIR / "path_attribution_test.py"],
        )
    )
    # Multi-MAIN feedback (real WireGuard shared 70 MHz names): a path that
    # only crosses a MAIN never re-pipelines it, attribution sees only the
    # plan's own MAIN, best-result ties go to met own paths then fewer
    # stages, and start_latency= regions take the mini-sweep ladder.
    tests.append(
        Test(
            name="sweep_cross_main_test",
            category="unit",
            cmd=[INST_DIR / "sweep_cross_main_test.py"],
        )
    )
    # Generated VHDL doesn't change between parse passes of one run:
    # c_structs_pkg only grows within one output directory, and shared C
    # built-in entities name no call site. Every synthesized leaf hashes these
    # files, so a flip re-synthesizes leaves even on a warm rerun. The package
    # is merged by emitted VHDL type name: a type whose layout changes between
    # passes under one name starts it over instead of being declared twice.
    tests.append(
        Test(
            name="generated_vhdl_stability_test",
            category="unit",
            cmd=[INST_DIR / "generated_vhdl_stability_test.py"],
        )
    )
    # DEVICE_MODELS sky130 STA diagnostics and fixed internal synthesis
    # recipes: component sums, endpoint semantics, structured arc traces,
    # and recipe-scoped cache/artifact identities. Uses tiny mapped-JSON
    # fixtures only; no external synthesis tool is invoked.
    tests.append(
        Test(
            name="device_models_sta_test",
            category="unit",
            cmd=[INST_DIR / "device_models_sta_test.py"],
        )
    )
    # sky130 area model: liberty area extraction, mapped-netlist area
    # summation, the leaf cache/area (SYN.GET_AREA_CACHE_DIR and friends),
    # and the whole-hierarchy estimate. Tiny synthetic fixtures only; no
    # external synthesis tool is invoked.
    tests.append(
        Test(
            name="area_model_test",
            category="unit",
            cmd=[INST_DIR / "area_model_test.py"],
        )
    )
    # Fast schema/parser coverage for the opt-in, hours-long Divider sky130
    # QoR harness.  The real benchmark itself is intentionally not in run_all.
    tests.append(
        Test(
            name="divider_qor_bench_unit_test",
            category="unit",
            cmd=[INST_DIR / "divider_qor_bench_unit_test.py"],
        )
    )
    # SWEEP.DROP_NON_DEEPENING_PLACEMENTS / CHUNK_SELECTED_MUX_OUTPUT_BANKS:
    # the mux select-fanout cliff. A planned register can materialize (a
    # real register was set) without deepening the schedule at all when it
    # lands on a parallel branch whose sibling already bounds a shared
    # downstream consumer's readiness -- found for real on soft_shift_rot's
    # funnel-shift muxes under real sky130 STA (105.95 -> 377.41 MHz at an
    # unchanged --no_hier_syn --no_sweep target, once both the wasted cut is
    # dropped and the remaining wide MUX banks are chunked by default) --
    # see the test file's own docstring and docs/SWEEP_DESIGN.md's mux
    # select-fanout cliff history.
    tests.append(
        Test(
            name="mux_fanout_planning_test",
            category="unit",
            cmd=[INST_DIR / "mux_fanout_planning_test.py"],
        )
    )
    # WRITE_LOGIC_ENTITY's joined submodule port maps: exact items per
    # instance, including a stateful submodule's leading clk + CLOCK_ENABLE.
    tests.append(
        Test(
            name="vhdl_submodule_port_map_test",
            category="unit",
            cmd=[INST_DIR / "vhdl_submodule_port_map_test.py"],
        )
    )
    # GET_PIPELINE_MAP scheduler worklists (PR #312 + latency buckets):
    # linear readiness/sort work for zero and nonzero latency chains, and a
    # stuck graph fails fast naming the waiting submodule.
    tests.append(
        Test(
            name="pipeline_map_scheduler_scalability_test",
            category="unit",
            cmd=[INST_DIR / "pipeline_map_scheduler_scalability_test.py"],
        )
    )
    # Byte-count regression for the cocotb/yosys "Argument list too long"
    # bug: a large design's VHDL file list, inlined whole into a single
    # generated recipe/command-line argument, can exceed Linux's
    # MAX_ARG_STRLEN (131072 bytes per argv/envp string) independent of the
    # much larger overall ARG_MAX -- see the test file's own docstring.
    tests.append(
        Test(
            name="long_file_list_arg_len_test",
            category="unit",
            cmd=[INST_DIR / "long_file_list_arg_len_test.py"],
            requires=["make", "ghdl"],
        )
    )
    # Every repo path checks out on Windows (PR #298: a Gowin PART:VERSION part
    # name became a committed cache/delay dir with a ':' in it), and the Gowin
    # delay-cache lookup still lands on the committed, sanitized directory.
    tests.append(
        Test(
            name="path_portability_test",
            category="unit",
            cmd=[INST_DIR / "path_portability_test.py"],
        )
    )
    # Pure configuration/selection coverage for the Xilinx 7-series open-source
    # flow. No FPGA tools are invoked.
    tests.append(
        Test(
            name="openxc7_unit_test",
            category="unit",
            cmd=[INST_DIR / "openxc7_unit_test.py"],
        )
    )
    # `vivado -version` parsing: three-part update releases and the
    # pre-2022.2 fixed_pkg cutoff. No Vivado run.
    tests.append(
        Test(
            name="vivado_version_unit_test",
            category="unit",
            cmd=[INST_DIR / "vivado_version_unit_test.py"],
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline pure compiler-helper unit tests."))
