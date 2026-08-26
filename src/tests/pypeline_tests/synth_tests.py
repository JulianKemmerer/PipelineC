#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pypelinec elaboration + autopipelining + synthesis tests (no --no_synth).

"Does it build" -- exit code is the entire verdict. See build_report_tests.py
for wrapper scripts that run pypelinec themselves and assert on its log
output/artifacts, and native_vs_vhdl_sim_tests.py for the AUTOFSM/AUTOPIPELINE
cycle-accuracy compares that used to live here (autofsm_native_sim_test +
autofsm_vhdl_sim_test, native_vs_vhdl_pipelined_ap_test,
native_vs_vhdl_pipelined_main_test).

Run standalone: python3 synth_tests.py [-j N]
"""

import sys

from common import EXAMPLES_PYPELINE_DIR, INST_DIR, PYPELINEC, QOR_DIR, Test, main

# fmt: off
# (filename, source_dir, extra_args)
SYNTH_TEST_FILES = [
    # By far the slowest test in the suite (a ~48-stage unrolled float32
    # divider under real sky130 synth+STA, see float_ops_div_test.py's own
    # comment) -- listed FIRST so run_all.py's FIFO dispatch starts it
    # building at t=0, concurrent with the rest of the suite, instead of
    # gating on whatever alphabetically/positionally precedes it.
    ("float_ops_div_test.py", INST_DIR, ["--comb"]),
    # stream_pipeline_test.py's full-sweep build runs inside the
    # autopipeline_latency_test wrapper (added in get_tests below), which also
    # asserts on the AUTOPIPELINE .latency pin-and-confirm output -- not
    # listed here so the same sweep isn't paid for twice.
    # Planned throughput sweep tests (full sweep, no --comb)
    ("sweep_comb_test.py", INST_DIR, []),
    ("sweep_two_mains_test.py", INST_DIR, []),
    ("sweep_fsm_autopipeline_test.py", INST_DIR, []),
    ("sweep_stateful_boundary_test.py", INST_DIR, []),
    ("fir_sweep_test.py", INST_DIR, []),  # FIR blob retimes to a @MAIN goal
    # Non---comb build: proves make_stream_autofsm elaborates and synthesises
    # with a real AUTOFSM schedule installed underneath its handshake
    # registers, independent of the native-vs-VHDL cycle diff registered in
    # native_vs_vhdl_sim_tests.py.
    ("self_check_stream_autofsm_test.py", INST_DIR, []),
    ("valid_ready_mcp_test.py", INST_DIR, ["--comb"]),
    ("vga_donut.py", EXAMPLES_PYPELINE_DIR, ["--comb"]),
    ("vga_test_pattern.py", EXAMPLES_PYPELINE_DIR, ["--comb"]),
    ("float32_add_test.py", INST_DIR, ["--comb"]),
    ("float_ops_test.py", INST_DIR, ["--comb"]),
    ("fixed_point_test.py", INST_DIR, ["--comb"]),
    ("pypeline_test.py", INST_DIR, ["--comb"]),
    ("reg_init_test.py", INST_DIR, ["--comb"]),
    ("if_test.py", INST_DIR, ["--comb"]),
    ("var_ref_test.py", INST_DIR, ["--comb"]),
    ("bit_math_test.py", INST_DIR, ["--comb"]),
    ("old_sw_lib_ops.py", INST_DIR, ["--comb"]),
    ("vhdl_text_test.py", INST_DIR, ["--comb"]),
    ("fifo_test.py", INST_DIR, ["--comb"]),
    ("stream_fifo_test.py", INST_DIR, ["--comb"]),
    ("axis_test.py", INST_DIR, ["--comb"]),
    ("dwidth_converter_test.py", INST_DIR, ["--comb"]),
    ("axis_byte_stream_test.py", INST_DIR, ["--comb"]),
    ("enum_test.py", INST_DIR, ["--comb"]),
    ("char_array_test.py", INST_DIR, ["--comb"]),
    ("sim_print_test.py", INST_DIR, ["--comb"]),
    ("sim_assert_finish_test.py", INST_DIR, ["--comb"]),
    ("two_factory_wrappers_mixed_test.py", INST_DIR, ["--comb"]),
    ("underscore_name_test.py", INST_DIR, ["--comb"]),
    ("array_compare_bracket_name_test.py", INST_DIR, ["--comb"]),
    ("fir_test.py", INST_DIR, ["--comb"]),
    ("fir_decim_test.py", INST_DIR, ["--comb"]),
    ("fir_interp_test.py", INST_DIR, ["--comb"]),
    ("magnitude_test.py", INST_DIR, ["--comb"]),
    ("dc_block_test.py", INST_DIR, ["--comb"]),
    ("moving_avg_test.py", INST_DIR, ["--comb"]),
    ("interface_test.py", INST_DIR, ["--comb"]),
    ("interface_func_test.py", INST_DIR, ["--comb"]),
    ("interface_func_loop_test.py", INST_DIR, ["--comb"]),
    ("interface_boundary_test.py", INST_DIR, ["--comb"]),
    ("interface_array_port_test.py", INST_DIR, ["--comb"]),
    ("interface_mixing_rules_test.py", INST_DIR, ["--comb"]),
    ("fm_radio_decim.py", EXAMPLES_PYPELINE_DIR / "dsp", ["--comb"]),
    (
        "pulse_detect_synth_top.py",
        EXAMPLES_PYPELINE_DIR / "dsp" / "pdw" / "pulse_detect",
        ["--comb"],
    ),
    # global_wire_nested_split_test.py (structurally richest multi-writer global
    # wire design: 3 writers splitting nested struct leaves + a mixed-depth
    # whole-subtree claim + readback) moved to known_issues_tests.py --
    # ElaborationError: 'combined' reported as having two whole-wire writers
    # even though their driven fields are disjoint. See
    # global_wire_nested_split_known_issue there.
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")],
            category="synth",
            cmd=[PYPELINEC, source_dir / filename] + extra_args,
            needs_out_dir=True,
        )
        for filename, source_dir, extra_args in SYNTH_TEST_FILES
    ]
    # Pipelined (non---comb) NATIVE simulation: full build first, then the
    # native sim runs with the discovered latencies emulated. Self-checking
    # elastic stream design -- proves build -> harvest -> latency-emulated
    # native sim end to end (including the .latency-sized FIFO). Not in
    # native_vs_vhdl_sim_tests.py: its VHDL/cocotb run produced no debug
    # output at all despite the build succeeding cleanly -- see that file's
    # own comment for what's known about the discrepancy.
    tests.append(
        Test(
            name="native_pipelined_sim_test",
            category="synth",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_stream_pipeline_test.py",
                "--sim",
                "--run",
                "all",
            ],
            needs_out_dir=True,
        )
    )
    # AUTOPIPELINE -> make_stream_autofsm conversions of the qor/ QoR designs
    # (real valid/ready handshake, ready genuinely wired -- not a constant 1).
    # Each lives at qor/<domain>/autofsm.py -- named explicitly here rather
    # than through the SYNTH_TEST_FILES comprehension above, since that
    # derives a Test's name from the bare filename and all three share the
    # name "autofsm". Clock goals are lowered from each design's AUTOPIPELINE
    # original: AUTOFSM shares hardware across states instead of spreading it
    # across pipeline stages, so the goal that mattered for a free-running
    # pipeline does not carry over -- what matters here is a clean
    # synthesizing build, not matching the pipelined design's fmax (each
    # file's own comment records its measured floor). The multiplier is also
    # what exposed and pins the _TypeResolver array-reconstruction fix in
    # AUTOFSM.py (an AUTOFSM over a descended soft multiplier's local
    # partial-products array used to crash codegen with "cannot reconstruct a
    # live Python type for C type 'uint16_t[16]'").
    for qor_name in ("multiplier", "divider", "sqrt"):
        tests.append(
            Test(
                name=f"qor_{qor_name}_autofsm_test",
                category="synth",
                cmd=[PYPELINEC, QOR_DIR / qor_name / "autofsm.py"],
                needs_out_dir=True,
            )
        )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline full elaboration + synthesis tests."))
