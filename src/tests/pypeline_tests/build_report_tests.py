#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wrapper-script tests: each runs pypelinec itself (as a subprocess) and
asserts on its build LOG output or generated artifacts -- yosys/PYRTL cell
counts, "TIMING NOT MET" error text, sweep_history.json, AUTO_FSM schedule
reports. This is a real full build in every case, just with the assertion
living one process layer below the runner instead of being "exit code only"
(that's synth_tests.py).

Each Test's category names the synthesis tool its wrapper's builds use
(build_report_<tool>, one per backend in common.SYN_TOOLS). The wrapper itself
passes the matching --syn_tool (or its design sets a PART that selects the same
tool), and run_all's tool check fails the test if the log shows any other tool. DEVICE_MODELS (sky130) is the default; the few wrappers
that build no synthesis at all (--no_synth, or sim-only) also live under
build_report_device_models.

Run standalone: python3 build_report_tests.py [-j N]
"""

import sys

from common import INST_DIR, Test, main, syn_tool_category

DM = syn_tool_category("build_report", "device_models")
VIVADO = syn_tool_category("build_report", "vivado")
PYRTL = syn_tool_category("build_report", "pyrtl")


def get_tests() -> list:
    tests = []
    tests.append(Test(name="auto_comb_delay_opt_build_test", category=DM,
                      cmd=[INST_DIR / "auto_comb_delay_opt_build_test.py"], needs_out_dir=True,
                      requires=["yosys", "ghdl"]))
    tests.append(Test(name="auto_comb_area_opt_build_test", category=DM,
                      cmd=[INST_DIR / "auto_comb_area_opt_build_test.py"], needs_out_dir=True,
                      requires=["yosys", "ghdl"]))
    tests.append(
        Test(
            name="generated_naming_build_test",
            category=DM,
            cmd=[INST_DIR / "generated_naming_build_test.py"],
            needs_out_dir=True,
            requires=["ghdl"],
        )
    )
    # Unreachable goal: under sky130 the sweep stops on the
    # prediction-independent plateau. (The wrapper's --syn_tool pyrtl mode,
    # which checks the empirical-floor stop instead, is kept for manual runs
    # but not registered: one tool per test.)
    tests.append(
        Test(
            name="sweep_floor_detect_test",
            category=DM,
            cmd=[INST_DIR / "sweep_floor_detect_test.py", "--syn_tool", "device_models"],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sweep_unpipelinable_test",
            category=DM,
            cmd=[INST_DIR / "sweep_unpipelinable_test.py"],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sweep_planless_test",
            category=DM,
            cmd=[INST_DIR / "sweep_planless_test.py"],
            needs_out_dir=True,
        )
    )
    # Full-sweep build of stream_auto_pipeline_test.py plus assertions on the
    # AUTO_PIPELINE .latency pin-and-confirm loop (pass 2 runs, discovers a
    # real >0 latency, one seeded confirmation syn passes with no fallback
    # sweep and no pass 3, harvested latency appears in sweep_history.json).
    tests.append(
        Test(
            name="auto_pipeline_latency_test",
            category=DM,
            cmd=[INST_DIR / "auto_pipeline_latency_test.py"],
            needs_out_dir=True,
        )
    )
    # AUTO_PIPELINE latency constraints end to end: latency=2 / start_latency=1
    # call sites built with exactly those counts and the pin-and-confirm pass
    # skipped (every .latency read already matched), plus a max_latency=1 cap
    # that stops an unreachable goal promptly with a warning naming it.
    tests.append(
        Test(
            name="auto_pipeline_constraints_test",
            category=DM,
            cmd=[INST_DIR / "auto_pipeline_constraints_test.py"],
            needs_out_dir=True,
        )
    )
    # C frontend `#pragma AUTOPIPELINE N`: a fixed latency, built with exactly
    # N clocks even by a --comb build.
    tests.append(
        Test(
            name="auto_pipeline_c_pragma_test",
            category=DM,
            cmd=[INST_DIR / "auto_pipeline_c_pragma_test.py"],
            needs_out_dir=True,
        )
    )
    # AUTO_MULTI_CYCLE under a real Vivado sweep (Xilinx part): from the default start
    # the sweep raises the multi-cycle count until timing is met, pass 2
    # re-elaborates the handshake and the pipelined native sim asserts it
    # waits latency + 1 cycles; restarting at that count settles immediately
    # with pass 2 skipped; a max_latency=1 cap fails the build naming it.
    tests.append(
        Test(
            name="auto_multi_cycle_sweep_test",
            category=VIVADO,
            cmd=[INST_DIR / "auto_multi_cycle_sweep_test.py"],
            needs_out_dir=True,
        )
    )
    # ── AUTO_FSM: pure function -> resource-shared FSM ──
    # Full build of auto_fsm_test.py plus assertions on the schedule: several
    # same-kind operations folded onto fewer shared units, latency matching the
    # state count, and exactly ONE instance of each shared unit in the
    # generated VHDL (the sharing claim, checked in the output rather than
    # trusted from the scheduler's own report).
    tests.append(
        Test(
            name="auto_fsm_latency_test",
            category=DM,
            cmd=[INST_DIR / "auto_fsm_latency_test.py"],
            needs_out_dir=True,
        )
    )
    # A copy of a warm output directory (what pypeline_sim_debug.py gives each
    # sim run) re-synthesizes no DEVICE_MODELS leaf: no generated file may
    # change between parse passes, and cache identity must not depend on the
    # directory's location.
    tests.append(
        Test(
            name="warm_copy_no_resynth_test",
            category=DM,
            cmd=[INST_DIR / "warm_copy_no_resynth_test.py"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
        )
    )
    # The reason AUTO_FSM exists: builds the same design as parallel
    # combinational logic and as a scheduled FSM, and compares yosys cell
    # counts. Guards against a regression that keeps working and meeting timing
    # while quietly no longer sharing anything.
    tests.append(
        Test(
            name="auto_fsm_resources_compare_test",
            category=DM,
            cmd=[INST_DIR / "auto_fsm_resources_compare_test.py"],
            needs_out_dir=True,
        )
    )
    # The minimum-area search, built both ways and compared on yosys cell
    # counts. This is the ONLY place a real area number enters the picture: the
    # search itself ranks candidates with an internal model, because timing is
    # the only quantity every synthesis backend reports in a parseable form.
    # So this test is where that model is held to account.
    tests.append(
        Test(
            name="auto_fsm_area_sweep_compare_test",
            category=DM,
            cmd=[INST_DIR / "auto_fsm_area_sweep_compare_test.py"],
            needs_out_dir=True,
        )
    )
    # Compare the chosen design against real mapped alternatives. Staying at
    # the sharing-everything anchor is valid; no move is required. The default
    # must remain within 3% of the smallest measured implementation.
    # Four sequential full builds (default, share-everything, and two forced
    # points), each verifying a distinct point of the search space -- this is
    # the slowest AUTO_FSM test in the suite (measured 840-1800s across three
    # runs). timeout=2700 documents that cost as known rather than letting it
    # run against the 7200s category default unremarked.
    tests.append(
        Test(
            name="auto_fsm_min_area_verify_test",
            category=DM,
            cmd=[INST_DIR / "auto_fsm_min_area_verify_test.py"],
            needs_out_dir=True,
            timeout=2700,
        )
    )
    # Same question as the two tests above -- does ranking candidates with a
    # model actually pick the smaller real design? -- but under real sky130
    # synthesis (docs/AUTO_FSM_DESIGN.md section 3.8): real cached leaf/
    # register/multiplexer um2 vs the abstract per-bit model, judged by real
    # measured area rather than yosys cell counts. Three real sky130 builds
    # of qor/divider/auto_fsm.py, so this is the slowest AUTO_FSM build_report
    # test in the file.
    tests.append(
        Test(
            name="auto_fsm_real_area_compare_test",
            category=DM,
            cmd=[INST_DIR / "auto_fsm_real_area_compare_test.py"],
            needs_out_dir=True,
        )
    )
    # The FSM's CONTROL path, built under both --auto_fsm_ctl modes and compared
    # on yosys cell counts, plus the timing consequence on a design that sits at
    # its clock goal. Guards the constant-table decode that replaced v2's
    # per-state comparator chains -- a regression there is invisible to every
    # correctness test in this suite, since both control paths compute the same
    # thing.
    tests.append(
        Test(
            name="auto_fsm_ctl_compare_test",
            category=PYRTL,
            cmd=[INST_DIR / "auto_fsm_ctl_compare_test.py"],
            needs_out_dir=True,
        )
    )
    # max_latency= as a HARD constraint, both halves: a cap the tool can meet
    # is met (by unsharing, the only thing that shortens a schedule), and a cap
    # it cannot meet fails the build with a message naming the latency actually
    # needed -- rather than quietly returning a slower FSM.
    tests.append(
        Test(
            name="auto_fsm_max_latency_test",
            category=DM,
            cmd=[INST_DIR / "auto_fsm_max_latency_test.py"],
            needs_out_dir=True,
        )
    )
    # Synthesis iterations that find a critical path inside an AUTO_FSM and fix
    # it: a deliberately loose starting budget over-packs the states, the first
    # build misses the clock, and the driver must tighten the budget and
    # reschedule until it passes -- the AUTO_FSM analogue of the sweep adding
    # pipeline stages.
    tests.append(
        Test(
            name="auto_fsm_timing_iter_test",
            category=DM,
            cmd=[INST_DIR / "auto_fsm_timing_iter_test.py"],
            needs_out_dir=True,
        )
    )
    # ...and the other half: when rescheduling cannot move the critical path
    # (sky130, a goal above the FSM's input-capture fanout path), the driver
    # stops after the first tightened build that gains no fmax, instead of
    # shrinking the budget into gate-level schedules and a 30-minute hang.
    tests.append(
        Test(
            name="auto_fsm_tighten_stall_test",
            category=DM,
            cmd=[INST_DIR / "auto_fsm_tighten_stall_test.py"],
            needs_out_dir=True,
        )
    )
    # @initial/@final hooks through a sky130 build + native sim, and a --comb
    # build + cocotb+GHDL sim: syn hooks once each, before elaboration / after
    # the final VHDL, sim hooks around the clock loop
    tests.append(
        Test(
            name="hooks_order_native_pipelined",
            category=DM,
            cmd=[INST_DIR / "hooks_order_test.py", "--variant", "native_pipelined"],
            needs_out_dir=True,
            requires=["yosys"],
        )
    )
    tests.append(
        Test(
            name="hooks_order_vhdl_comb",
            category=DM,
            cmd=[INST_DIR / "hooks_order_test.py", "--variant", "vhdl_comb"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
        )
    )
    # Regression guard for src/COCOTB.py's PASS/FAIL reporting: runs one
    # passing and one failing design through --cocotb --ghdl --run all and
    # asserts each is scored correctly. See COCOTB.py's CHECK_COCOTB_RESULTS
    # docstring for the bug this guards (every --run all sim used to report
    # FAIL in cocotb's own summary regardless of the actual outcome).
    tests.append(
        Test(
            name="cocotb_verdict_test",
            category=DM,
            cmd=[INST_DIR / "cocotb_verdict_test.py"],
            needs_out_dir=True,
            requires=["ghdl"],
        )
    )
    # Regression guard for the D1 fix (RAW_VHDL.SPLIT_KIND_1LL leaves -
    # MUX/AND/OR/XOR - expose real operation boundaries without pretending
    # their one logic level has an arbitrary interior): a serial 1LL-only gate
    # chain under real sky130 timing must never let one of them exceed its
    # real slice ceiling, must still get pipelined at all (not collapse
    # into one uncuttable atomic span), and must show up in the fmax floor
    # report as a real bottleneck instead of "no unsliceable spans".
    tests.append(
        Test(
            name="leaf_1ll_cap_test",
            category=DM,
            cmd=[INST_DIR / "leaf_1ll_cap_test.py"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
        )
    )
    # Regression guard for two process-nondeterminism bugs that defeated
    # --continue's synthesis-log reuse on designs with sequential runtime
    # variable-index array writes (found via wireguard-fpga): unstable
    # VAR_REF_ASSIGN/VAR_REF_RD/CONST_REF_RD entity NAMES (a repr memory
    # address leaking through str(ast_node) into a name hash) and unstable
    # entity CONTENT (PYTHONHASHSEED-salted set iteration order leaking into
    # generated VHDL line order). Builds real sky130 synthesis twice into the
    # same out_dir (names + log reuse) and once each into two independent
    # out_dirs (byte-identical content).
    tests.append(
        Test(
            name="var_ref_naming_test",
            category=DM,
            cmd=[INST_DIR / "var_ref_naming_test.py"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
        )
    )
    # Regression guard for a third process-nondeterminism bug in the same
    # family as var_ref_naming_test above, this time in
    # C_TO_LOGIC.TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE's duplicate-submodule
    # collapsing pass: the "_lNN_lMM" source-coordinate fragment of a
    # collapsed instance's name was built by iterating a set of ASTMeta
    # directly, and ASTMeta.__hash__ is a PYTHONHASHSEED-salted str hash.
    # Pins PYTHONHASHSEED to two seeds confirmed to disagree pre-fix and
    # diffs the resulting VHDL byte-for-byte -- a bare repeat-build only
    # catches a 2-element set flip about half the time. Uses --comb
    # --no_synth so it needs no yosys/ghdl and runs in seconds.
    tests.append(
        Test(
            name="duplicate_collapse_naming_test",
            category=DM,
            cmd=[INST_DIR / "duplicate_collapse_naming_test.py"],
            needs_out_dir=True,
        )
    )
    # A design that synthesizes away to nothing (no top-level outputs) must
    # fail its pipelined build with the clear PYRTL "no timing paths" error --
    # not the old divide-by-zero / float-parse failure, and not by getting
    # stuck in the single-stateful-main coarse sweep first.
    tests.append(
        Test(
            name="pyrtl_no_timing_paths_build_report_test",
            category=PYRTL,
            cmd=[INST_DIR / "pyrtl_no_timing_paths_build_report_test.py"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
        )
    )
    # Regression guard for the D2 fix (RAW_VHDL._EQUAL_WIDTH_BITS_PER_STAGE_
    # DICT) and the §6a/§6b reporting fixes, against a real multi-cut sky130
    # build in both the planned sweep and --coarse paths.
    tests.append(
        Test(
            name="split_model_build_report_test",
            category=DM,
            cmd=[INST_DIR / "split_model_build_report_test.py"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
        )
    )
    # sky130 area estimate/measurement reporting, both operating modes:
    # mode 1 (--no_hier_syn --no_sweep) prints an estimate and leaves every
    # leaf area-cached; mode 2 (a real confirmation/sweep synthesis) also
    # prints the exact measured area from that run's own mapped netlist.
    tests.append(
        Test(
            name="area_estimate_build_report_test",
            category=DM,
            cmd=[INST_DIR / "area_estimate_build_report_test.py"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
        )
    )
    # The generated host module: a real build must drop one in <out_dir>/host/
    # whose bytes agree with pypeline's own type_to_bytes for the design's type.
    tests.append(
        Test(
            name="host_types_build_test",
            category=DM,
            cmd=[INST_DIR / "host_types_build_test.py"],
            needs_out_dir=True,
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(
        main(
            get_tests,
            "PipelineC pypeline build-log/artifact wrapper-script tests.",
        )
    )
