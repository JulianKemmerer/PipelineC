#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wrapper-script tests: each runs pypelinec itself (as a subprocess) and
asserts on its build LOG output or generated artifacts -- yosys/PYRTL cell
counts, "TIMING NOT MET" error text, sweep_history.json, AUTOFSM schedule
reports. This is a real full build in every case, just with the assertion
living one process layer below the runner instead of being "exit code only"
(that's synth_tests.py).

Run standalone: python3 build_report_tests.py [-j N]
"""

import sys

from common import INST_DIR, Test, main


def get_tests() -> list:
    tests = []
    tests.append(
        Test(
            name="sweep_floor_detect_test",
            category="build_report",
            cmd=[INST_DIR / "sweep_floor_detect_test.py"],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sweep_unpipelinable_test",
            category="build_report",
            cmd=[INST_DIR / "sweep_unpipelinable_test.py"],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sweep_planless_test",
            category="build_report",
            cmd=[INST_DIR / "sweep_planless_test.py"],
            needs_out_dir=True,
        )
    )
    # Full-sweep build of stream_pipeline_test.py plus assertions on the
    # AUTOPIPELINE .latency pin-and-confirm loop (pass 2 runs, discovers a
    # real >0 latency, one seeded confirmation syn passes with no fallback
    # sweep and no pass 3, harvested latency appears in sweep_history.json).
    tests.append(
        Test(
            name="autopipeline_latency_test",
            category="build_report",
            cmd=[INST_DIR / "autopipeline_latency_test.py"],
            needs_out_dir=True,
        )
    )
    # ── AUTOFSM: pure function -> resource-shared FSM ──
    # Full build of autofsm_test.py plus assertions on the schedule: several
    # same-kind operations folded onto fewer shared units, latency matching the
    # state count, and exactly ONE instance of each shared unit in the
    # generated VHDL (the sharing claim, checked in the output rather than
    # trusted from the scheduler's own report).
    tests.append(
        Test(
            name="autofsm_latency_test",
            category="build_report",
            cmd=[INST_DIR / "autofsm_latency_test.py"],
            needs_out_dir=True,
        )
    )
    # The reason AUTOFSM exists: builds the same design as parallel
    # combinational logic and as a scheduled FSM, and compares yosys cell
    # counts. Guards against a regression that keeps working and meeting timing
    # while quietly no longer sharing anything.
    tests.append(
        Test(
            name="autofsm_resources_compare_test",
            category="build_report",
            cmd=[INST_DIR / "autofsm_resources_compare_test.py"],
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
            name="autofsm_area_sweep_compare_test",
            category="build_report",
            cmd=[INST_DIR / "autofsm_area_sweep_compare_test.py"],
            needs_out_dir=True,
        )
    )
    # The stronger form of the same question. The compare test above only asks
    # "did the search make things worse?", which every design in this repo
    # answers by taking no moves at all -- passing it vacuously. This one uses a
    # design built to reward moving (three divides sharing one divider) and
    # asserts the search actually opens it up, that the move is smaller in real
    # cells, and that no alternative point of the search space -- built
    # explicitly with --autofsm_open/--autofsm_unshare -- is smaller still.
    tests.append(
        Test(
            name="autofsm_min_area_verify_test",
            category="build_report",
            cmd=[INST_DIR / "autofsm_min_area_verify_test.py"],
            needs_out_dir=True,
        )
    )
    # The FSM's CONTROL path, built under both --autofsm_ctl modes and compared
    # on yosys cell counts, plus the timing consequence on a design that sits at
    # its clock goal. Guards the constant-table decode that replaced v2's
    # per-state comparator chains -- a regression there is invisible to every
    # correctness test in this suite, since both control paths compute the same
    # thing.
    tests.append(
        Test(
            name="autofsm_ctl_compare_test",
            category="build_report",
            cmd=[INST_DIR / "autofsm_ctl_compare_test.py"],
            needs_out_dir=True,
        )
    )
    # max_latency= as a HARD constraint, both halves: a cap the tool can meet
    # is met (by unsharing, the only thing that shortens a schedule), and a cap
    # it cannot meet fails the build with a message naming the latency actually
    # needed -- rather than quietly returning a slower FSM.
    tests.append(
        Test(
            name="autofsm_max_latency_test",
            category="build_report",
            cmd=[INST_DIR / "autofsm_max_latency_test.py"],
            needs_out_dir=True,
        )
    )
    # Synthesis iterations that find a critical path inside an AUTOFSM and fix
    # it: a deliberately loose starting budget over-packs the states, the first
    # build misses the clock, and the driver must tighten the budget and
    # reschedule until it passes -- the AUTOFSM analogue of the sweep adding
    # pipeline stages.
    tests.append(
        Test(
            name="autofsm_timing_iter_test",
            category="build_report",
            cmd=[INST_DIR / "autofsm_timing_iter_test.py"],
            needs_out_dir=True,
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
            category="build_report",
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
            category="build_report",
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
            category="build_report",
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
            category="build_report",
            cmd=[INST_DIR / "duplicate_collapse_naming_test.py"],
            needs_out_dir=True,
        )
    )
    # Regression guard for the D2 fix (RAW_VHDL._EQUAL_WIDTH_BITS_PER_STAGE_
    # DICT) and the §6a/§6b reporting fixes, against a real multi-cut sky130
    # build in both the planned sweep and --coarse paths.
    tests.append(
        Test(
            name="split_model_build_report_test",
            category="build_report",
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
            category="build_report",
            cmd=[INST_DIR / "area_estimate_build_report_test.py"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
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
