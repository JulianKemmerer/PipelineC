#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cycle-accurate native-vs-VHDL simulation tests, via pypeline_sim_debug.py.

Every entry here runs a design's native (Python) sim and its real cocotb+GHDL
sim, and diffs their sim_print(..., debug=True) console output cycle by cycle
(pypeline_sim_debug.py). MATCH (exit 0) proves the two sims agree, not just
that each one self-checks -- strictly stronger than running the same design
through native_sim_tests.py and (the now-removed) vhdl_sim_tests.py
separately, which only proved each sim's own sim_assert/sim_finish passed.

Designs registered here must:
  - emit at least one sim_print(..., debug=True) probe covering the values
    their sim_assert already checks;
  - never emit a debug=True print on the same cycle sim_finish() is called
    (GHDL's std.env.finish vs write-flush is a process-ordering race the
    diff must not depend on -- see the design files' own comments, and
    known_issues_tests.py's sim_finish_debug_print_race_test for a direct
    reproduction of what happens if this rule is broken);
  - for a non---comb (pipelined) entry, put every probe inside a stateful
    (0-latency) MAIN, and valid-/count-gate it so VHDL's undefined ('U')
    warm-up registers can't be compared against native's typed zeros.

See docs/pypeline_TESTS.md and docs/pypeline_sim_DESIGN.md's Limitations
section for the full probe-placement contract.

Run standalone: python3 native_vs_vhdl_sim_tests.py [-j N]
"""

import sys

from common import EXAMPLES_PYPELINE_DIR, INST_DIR, PYPELINE_SIM_DEBUG, Test, main

# fmt: off
# (filename, source_dir, extra_args) -- extra_args always includes --sim and
# --run; --comb selects the fast passthrough-latency compare, its absence
# selects the full-build pipelined compare (pypeline_sim_debug.py builds once
# then runs native + VHDL concurrently against the same warm out_dir).
COMB_TEST_FILES = [
    ("self_check_counter_test.py", INST_DIR, []),
    ("self_check_fifo_test.py", INST_DIR, []),
    # self_check_bit_math_test.py is deliberately NOT here: its whole body is
    # one combinational block that calls sim_finish() the very same cycle it
    # computes everything, with nothing before that cycle to safely print --
    # structurally incompatible with the "no debug print on the sim_finish()
    # cycle" rule (see module docstring). It also currently trips a real,
    # unrelated hardware bug (nested_truncate(200) computes a different value
    # in GHDL than in native sim) -- see
    # known_issues_tests.py:nested_truncate_int16_vhdl_mismatch_test.
    ("struct_ctor_positional_test.py", INST_DIR, []),
    # AUTOFSM through real GHDL in --comb mode (passthrough, latency 0). The
    # scheduled FSM hardware is exercised by the non---comb entry below.
    ("self_check_autofsm_test.py", INST_DIR, []),
    ("global_wire_partial_field_test.py", INST_DIR, []),
    ("global_wire_read_write_test.py", INST_DIR, []),
    ("global_wire_split_driver_test.py", INST_DIR, []),
    ("global_wire_readback_test.py", INST_DIR, []),
    # global_wire_nested_split_test.py is deliberately NOT here: under this
    # exact combination (--comb --sim --cocotb --ghdl) elaboration raises
    # "Global Output 'combined' has multiple writer functions with
    # overlapping driven fields: 'combiner' drives (whole wire) and
    # 'soft_cmp_prefix_n_leaves_8_level_5ca4ac95' drives (whole wire)" --
    # an internal soft-compare submodule is being misidentified as a second
    # writer of the global wire. It still builds fine under plain --comb
    # (synth_tests.py) and passes native_sim. See
    # known_issues_tests.py:global_wire_soft_cmp_false_writer_test.
    ("global_wire_hier_writer_test.py", INST_DIR, []),
    ("global_wire_cond_driver_test.py", INST_DIR, []),
    ("global_wire_array_split_test.py", INST_DIR, []),
    ("global_wire_dynamic_index_write_test.py", INST_DIR, []),
]
# Non---comb (pipelined/scheduled) compares: full build, then native sim runs
# with the discovered latencies emulated, diffed against real pipelined VHDL.
NON_COMB_TEST_FILES = [
    # Same self-checking design as the --comb entry above, but now through
    # the REAL scheduled FSM (replaces synth_tests.py's former
    # autofsm_native_sim_test + autofsm_vhdl_sim_test pair with one cycle diff).
    ("self_check_autofsm_test.py", INST_DIR, []),
    # self_check_stream_pipeline_test.py is deliberately NOT here: its VHDL
    # sim produced zero debug output cycle over cycle (pypeline_sim_debug.py
    # reported a MISMATCH against native's real output) despite the build
    # itself succeeding cleanly (met timing, 4 pipeline stages). Root cause
    # not established -- may be a cocotb/GHDL interaction specific to this
    # design's FIFO-sized-by-.latency shape, not necessarily a compiler bug.
    # It keeps its original native-only registration in build_report_tests.py
    # (native_pipelined_sim_test) pending investigation.
    ("native_vs_vhdl_ap_test.py", INST_DIR, []),
    (
        "native_vs_vhdl_pipelined_main_test.py",
        INST_DIR,
        ["--pipeline_min_effort", "0"],
    ),
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")] + "_comb",
            category="native_vs_vhdl_sim",
            cmd=[PYPELINE_SIM_DEBUG, source_dir / filename, "--sim", "--comb", "--run", "all"]
            + extra_args,
            needs_out_dir=True,
        )
        for filename, source_dir, extra_args in COMB_TEST_FILES
    ]
    tests += [
        Test(
            name=filename[: -len(".py")],
            category="native_vs_vhdl_sim",
            cmd=[PYPELINE_SIM_DEBUG, source_dir / filename, "--sim", "--run", "all"]
            + extra_args,
            needs_out_dir=True,
        )
        for filename, source_dir, extra_args in NON_COMB_TEST_FILES
    ]
    return tests


if __name__ == "__main__":
    sys.exit(
        main(
            get_tests,
            "PipelineC pypeline native-vs-VHDL cycle-accurate simulation tests.",
        )
    )
