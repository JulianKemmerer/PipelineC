#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipelinec elaboration + autopipelining + synthesis tests (no --no_synth).

Run standalone: python3 synth_tests.py [-j N]
"""

import sys

from common import (
    EXAMPLES_PYPELINE_DIR,
    INST_DIR,
    PIPELINEC,
    PYPELINE_SIM_DEBUG,
    Test,
    main,
)

# fmt: off
# (filename, source_dir, extra_args)
SYNTH_TEST_FILES = [
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
    # Structurally richest multi-writer global wire design (3 writers splitting
    # nested struct leaves + a mixed-depth whole-subtree claim + readback):
    # proves the per-region top-level VHDL through real synthesis, not just GHDL.
    ("global_wire_nested_split_test.py", INST_DIR, ["--comb"]),
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")],
            category="synth",
            cmd=[PIPELINEC, source_dir / filename] + extra_args,
            needs_out_dir=True,
        )
        for filename, source_dir, extra_args in SYNTH_TEST_FILES
    ]
    # Wrapper scripts (run pipelinec themselves and assert on the sweep's output)
    tests.append(
        Test(
            name="sweep_floor_detect_test",
            category="synth",
            cmd=[INST_DIR / "sweep_floor_detect_test.py"],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sweep_unpipelinable_test",
            category="synth",
            cmd=[INST_DIR / "sweep_unpipelinable_test.py"],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sweep_planless_test",
            category="synth",
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
            category="synth",
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
            category="synth",
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
            category="synth",
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
            category="synth",
            cmd=[INST_DIR / "autofsm_area_sweep_compare_test.py"],
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
            category="synth",
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
            category="synth",
            cmd=[INST_DIR / "autofsm_timing_iter_test.py"],
            needs_out_dir=True,
        )
    )
    # Full build + latency-emulated native sim of the self-checking AUTOFSM
    # design: proves the native FSM model agrees with the schedule the build
    # produced (the design's sim_asserts hold at the real .latency, and it
    # reaches sim_finish).
    tests.append(
        Test(
            name="autofsm_native_sim_test",
            category="synth",
            cmd=[
                PIPELINEC,
                INST_DIR / "self_check_autofsm_test.py",
                "--sim",
                "--run",
                "all",
            ],
            needs_out_dir=True,
        )
    )
    # The same self-checking design built and run through real GHDL: the
    # generated FSM HARDWARE computes what the pure function did. Non---comb, so
    # this exercises the scheduled FSM rather than the bootstrap passthrough --
    # the strongest correctness evidence in the AUTOFSM suite.
    tests.append(
        Test(
            name="autofsm_vhdl_sim_test",
            category="synth",
            cmd=[
                PIPELINEC,
                INST_DIR / "self_check_autofsm_test.py",
                "--sim",
                "--cocotb",
                "--ghdl",
                "--run",
                "all",
            ],
            needs_out_dir=True,
        )
    )
    # Pipelined (non---comb) NATIVE simulation: full build first, then the
    # native sim runs with the discovered latencies emulated. Self-checking
    # elastic stream design -- proves build -> harvest -> latency-emulated
    # native sim end to end (including the .latency-sized FIFO).
    tests.append(
        Test(
            name="native_pipelined_sim_test",
            category="synth",
            cmd=[
                PIPELINEC,
                INST_DIR / "self_check_stream_pipeline_test.py",
                "--sim",
                "--run",
                "all",
            ],
            needs_out_dir=True,
        )
    )
    # Cycle-accuracy of the pipelined native sim vs real pipelined VHDL
    # (cocotb+GHDL): pypeline_sim_debug.py runs both (sequentially, warm
    # path-delay caches => identical discovered latencies) and exits 0 only
    # if every sim_print(debug=True) line matches cycle for cycle.
    # native_vs_vhdl_ap_test: AUTOPIPELINE call-site delay-line emulation.
    # native_vs_vhdl_pipelined_main_test: naturally-pipelined pure MAIN
    # write-side delay emulation.
    tests.append(
        Test(
            name="native_vs_vhdl_pipelined_ap_test",
            category="synth",
            cmd=[
                PYPELINE_SIM_DEBUG,
                INST_DIR / "native_vs_vhdl_ap_test.py",
                "--sim",
                "--run",
                "all",
            ],
            needs_out_dir=True,
        )
    )
    # --pipeline_min_effort 0: the design pairs the sliceable pure MAIN with
    # an unsliceable stateful checker in the same (wire-shared) clock domain;
    # PYRTL's no-attribution timing blames every co-domain main during the
    # post-met trim attempts' intentional failing iterations, and the
    # trim-restore path only restores the planned main's met status --
    # accepting the first met result avoids that sticky spurious failure.
    tests.append(
        Test(
            name="native_vs_vhdl_pipelined_main_test",
            category="synth",
            cmd=[
                PYPELINE_SIM_DEBUG,
                INST_DIR / "native_vs_vhdl_pipelined_main_test.py",
                "--sim",
                "--run",
                "all",
                "--pipeline_min_effort",
                "0",
            ],
            needs_out_dir=True,
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline full elaboration + synthesis tests."))
