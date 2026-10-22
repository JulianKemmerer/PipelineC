#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native (Python-only) simulation tests -- no VHDL/GHDL involved. See
native_vs_vhdl_sim_tests.py for the self-checking designs that ALSO run
through real cocotb+GHDL, with the two sims' sim_print(debug=True) output
diffed cycle by cycle.

Run standalone: python3 native_sim_tests.py [-j N]
"""

import sys

from common import (
    EXAMPLES_PYPELINE_DIR,
    INST_DIR,
    NO_TIMEOUT_S,
    PYPELINEC,
    PYPELINE_SIM,
    Test,
    main,
)

# fmt: off
PLAIN_PYTHON_TEST_FILES = [
    "stream_auto_pipeline_test.py",
    "stream_ii1_throughput_test.py",
    "auto_pipeline_test.py",
    "auto_pipeline_fixed_latency_sim_test.py",
    "auto_fsm_test.py",
    "stream_auto_fsm_test.py",
    "stream_multi_cycle_test.py",
    "stream_auto_multi_cycle_test.py",
    "float32_add_test.py",
    "float_ops_test.py",
    "fixed_point_test.py",
    "cordic_test.py",
    "lut_nco_test.py",
    "lut_atan2_test.py",
    "log2_db_test.py",
    "pypeline_test.py",
    "sim_loop_reg_state_test.py",
    "reg_init_test.py",
    "reg_bitwise_mask_test.py",
    "struct_ctor_narrow_test.py",
    "cast_test.py",
    "cast_interface_test.py",
    "cast_hw_func_test.py",
    "reg_undefined_width_test.py",
    "feedback_reeval_test.py",
    "reg_aug_assign_test.py",
    "bit_math_test.py",
    "vhdl_text_test.py",
    "fifo_test.py",
    "stream_fifo_test.py",
    "valid_join_test.py",
    "self_timed_factory_test.py",
    "skid_buffer_test.py",
    "stream_perf_test.py",
    "ram_test.py",
    "stream_ram_test.py",
    "axis_test.py",
    "dwidth_converter_test.py",
    "axis_byte_stream_test.py",
    "func_wires_test.py",
    "pipeline_latency_test.py",
    "factory_arg_port_annotation_test.py",
    "live_root_default_ops_test.py",
    "if_test.py",
    "enum_test.py",
    "char_array_test.py",
    "sim_print_test.py",
    "sim_assert_finish_test.py",
    "hooks_test.py",
    "type_bytes_test.py",
    "type_bytes_sw_test.py",
    "host_types_test.py",
    "serdes_test.py",
    "type_byte_stream_test.py",
    "axis_max_len_limiter_test.py",
    "type_axis_test.py",
    "sim_model_test.py",
    "array_2d_order_test.py",
    "pylist_value_context_test.py",
    "fir_test.py",
    "fir_decim_test.py",
    "fir_interp_test.py",
    "magnitude_test.py",
    "dc_block_test.py",
    "moving_avg_test.py",
    "interface_test.py",
    "interface_func_test.py",
    "interface_func_loop_test.py",
    "interface_boundary_test.py",
    "interface_array_port_test.py",
    "interface_mixing_rules_test.py",
    "interface_hw_func_pairing_error_test.py",
    "soft_ops_test.py",
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")],
            category="native_sim",
            cmd=[INST_DIR / filename],
        )
        for filename in PLAIN_PYTHON_TEST_FILES
    ]
    tests.append(
        Test(
            name="global_wires_sim_test",
            category="native_sim",
            cmd=[PYPELINE_SIM, INST_DIR / "global_wires_sim_test.py", "--run", "10"],
        )
    )
    # Loop-instance identity is arithmetic-mode independent.  Strict mode is
    # covered by the direct sim_call regression above and the native-vs-GHDL
    # compare; exercise the two alternate wrapper variants through the
    # multi-MAIN clock-cycle runner as well.
    for mode in ("loose", "raw"):
        tests.append(
            Test(
                name=f"sim_loop_reg_state_{mode}_test",
                category="native_sim",
                cmd=[
                    PYPELINE_SIM,
                    INST_DIR / "sim_loop_reg_state_test.py",
                    "--run",
                    "all",
                    "--mode",
                    mode,
                ],
            )
        )
    # Augmented assignment through the multi-evaluation clock runner
    # (convergence loop + final pass): a `reg[i] += 1` must not reach the
    # committed register before the clock edge.
    tests.append(
        Test(
            name="reg_aug_assign_convergence_test",
            category="native_sim",
            cmd=[PYPELINE_SIM, INST_DIR / "reg_aug_assign_test.py", "--run", "all"],
        )
    )
    # @MAIN arguments are undriven top-level input ports: native sim passes
    # typed zeros (it used to call every MAIN with no arguments and crash).
    tests.append(
        Test(
            name="main_args_sim_test",
            category="native_sim",
            cmd=[PYPELINE_SIM, INST_DIR / "main_args_sim_test.py", "--run", "all"],
        )
    )
    # In-design stream performance probes under the real multi-MAIN runner:
    # MAIN-qualified tap names, one count per cycle through Feedback[T]
    # convergence, and the bottleneck verdict (checked in its @final hook).
    tests.append(
        Test(
            name="stream_perf_probe_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "stream_perf_probe_test.py",
                "--sim",
                "--comb",
                "--run",
                "200",
            ],
            needs_out_dir=True,
        )
    )
    # A complete stream performance testbench (PhaseRunner, converged AXIS
    # source/sink, probed FIFO + skid buffer), checked in its @final hook.
    tests.append(
        Test(
            name="stream_perf_tb_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "stream_perf_tb_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sim_model_convergence_test",
            category="native_sim",
            cmd=[PYPELINE_SIM, INST_DIR / "sim_model_test.py", "--run", "20"],
        )
    )
    tests.append(
        Test(
            name="fifo_sim_model_convergence_test",
            category="native_sim",
            cmd=[PYPELINE_SIM, INST_DIR / "fifo_sim_model_test.py", "--run", "16"],
        )
    )
    # make_ram's model shares one memory list between evaluations; this runs a
    # RAM accumulator closed through wires so every cycle re-evaluates it with
    # stale inputs, and checks each write still lands exactly once.
    tests.append(
        Test(
            name="ram_sim_model_convergence_test",
            category="native_sim",
            cmd=[PYPELINE_SIM, INST_DIR / "ram_sim_model_test.py", "--run", "30"],
        )
    )
    tests.append(
        Test(
            name="pipelinec_native_sim_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "global_wires_sim_test.py",
                "--sim",
                "--comb",
                "--run",
                "10",
            ],
        )
    )
    tests.append(
        Test(
            name="wire_discovery_passthrough_sim_test",
            category="native_sim",
            cmd=[
                PYPELINE_SIM,
                INST_DIR / "wire_discovery_passthrough_sim_test.py",
                "--run",
                "3",
            ],
        )
    )
    tests.append(
        Test(
            name="wire_discovery_passthrough_native_sim_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "wire_discovery_passthrough_sim_test.py",
                "--sim",
                "--comb",
                "--run",
                "3",
            ],
        )
    )
    tests.append(
        Test(
            name="sim_output_direct_wire_test",
            category="native_sim",
            cmd=[
                PYPELINE_SIM,
                INST_DIR / "sim_output_direct_wire_test.py",
                "--run",
                "20",
            ],
        )
    )
    tests.append(
        Test(
            name="sim_input_test",
            category="native_sim",
            cmd=[PYPELINE_SIM, INST_DIR / "sim_input_test.py", "--run", "25"],
        )
    )
    tests.append(
        Test(
            # dsp/fir_tb.py testbench-library end-to-end (@sim_input driver +
            # @sim_output checker); --run must exceed both tbs' deadlines.
            name="fir_sim_tb_test",
            category="native_sim",
            cmd=[PYPELINE_SIM, INST_DIR / "fir_sim_tb_test.py", "--run", "1400"],
        )
    )
    # The dsp/ library's worked examples, run as tests. They are demos first --
    # each is cited by name in include/pypeline/dsp/pypeline_dsp_guide.md, and
    # the library's real unit tests live in inst/ (magnitude_test.py,
    # dc_block_test.py, fir_test.py, ...) -- but running them here is what
    # keeps a documented example from rotting unnoticed. The dsp_tb.py three
    # each drive two @MAINs (elastic + valid_only), and the fir_tb.py three one
    # each, so --run must exceed every tb's own deadline; each count is the one
    # in that file's own "Run the simulation:" line.
    DSP_DIR = EXAMPLES_PYPELINE_DIR / "dsp"
    for fname, run_n in [
        ("magnitude_tb.py", 1000),
        ("dc_block_tb.py", 4000),
        ("moving_avg_tb.py", 3000),
        ("fir_lowpass_tb.py", 2400),
        ("fir_decim_tb.py", 1800),
        ("fir_interp_tb.py", 1600),
    ]:
        tests.append(
            Test(
                name=fname[: -len(".py")],
                category="native_sim",
                cmd=[
                    PYPELINEC,
                    DSP_DIR / fname,
                    "--sim",
                    "--comb",
                    "--run",
                    str(run_n),
                ],
            )
        )
    # docs/README.md's getting-started examples, for the same reason. Each run
    # count is the one in that file's README command (pipeline.py has none, and
    # its @MAIN arguments read as zero here, so 2 cycles just checks it runs).
    for fname, run_n in [
        ("blink.py", 3),
        ("counter.py", 3),
        ("fsm.py", 7),
        ("pipeline.py", 2),
        ("stream_pipeline.py", 20),
    ]:
        tests.append(
            Test(
                name=f"example_{fname[: -len('.py')]}_sim",
                category="native_sim",
                cmd=[
                    PYPELINEC,
                    EXAMPLES_PYPELINE_DIR / fname,
                    "--sim",
                    "--comb",
                    "--run",
                    str(run_n),
                ],
                needs_out_dir=True,
            )
        )
    # PDW project: the suite's only PDW test, the most current whole design.
    # Its block-level tests (examples/pypeline/dsp/pdw/*_test.py, *_tb.py) run
    # by hand; see that directory's README. Top-level testbench (top.py) -- exact
    # golden model of the WHOLE pipeline, pulse_gen -> pulse_detect -> pulse_measure -> pulse_extract,
    # across eight pulse settings: released ones, two that Path A never
    # detects, two that it detects and the engine then rejects (glitch and
    # CW), and an LFM chirp. Also the acceptance test for Path B's
    # sample-exact delay-line alignment, for every measured field (frequency,
    # dB power, noise floor, PRI) against a bit-exact model, and -- since every
    # top-level port is now a flattened AXI-Stream -- for the control-frame
    # write path, both record serializers and the released-packet broadcast.
    tests.append(
        Test(
            name="pdw_tb",
            category="native_sim",
            # The longest single test in the suite. Its category is
            # second-to-last in run_all.py's order, so without this it starts
            # once nearly everything else has been submitted and lands in the
            # tail. Once measured at 1435 s; with native sim executing
            # matcher-registered soft operators by default it measured
            # ~523 ms/cycle alone (~148 with PYPELINE_SIM_SOFT_OPS=none) and
            # reached only 5846 of its 7323 cycles in 7200 s under run_all -j 5
            # (~1.23 s/cycle, ~9000 s projected; those figures are for the
            # cordic atan2, this runs the default rom). It once ran past a
            # 4-hour timeout on a loaded machine, so it has none: it ends
            # itself (sim_finish or its deadline assert, below).
            long_pole=True,
            timeout=NO_TIMEOUT_S,
            cmd=[
                PYPELINEC,
                EXAMPLES_PYPELINE_DIR / "dsp" / "pdw" / "pdw_tb.py",
                "--sim",
                "--comb",
                # Ends itself: sim_finish() once every output has arrived, or
                # its deadline assert; its @final hook checks the run finished
                "--run",
                "all",
                # The design's default PDW_ATAN2_METHOD (rom)
            ],
        )
    )
    # @initial/@final hooks around a --sim --comb run, through the driver
    # (build variants: elab_tests.py, build_report_tests.py)
    tests.append(
        Test(
            name="hooks_order_native_comb",
            category="native_sim",
            cmd=[INST_DIR / "hooks_order_test.py", "--variant", "native_comb"],
            needs_out_dir=True,
        )
    )
    # Self-checking sim_assert/sim_finish designs -- no external Python
    # sim_call/assert harness needed. Same source files are also registered in
    # native_vs_vhdl_sim_tests.py, where the native and cocotb+GHDL sims are
    # run together and their debug output diffed cycle by cycle.
    tests.append(
        Test(
            name="self_check_counter_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_counter_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="self_check_fifo_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_fifo_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="self_check_stream_auto_pipeline_ii1_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_stream_auto_pipeline_ii1_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="self_check_ram_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_ram_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="self_check_loop_unpack_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_loop_unpack_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    # AUTO_FSM in --comb mode: the call site is still the combinational
    # passthrough (latency 0), so this also proves the self-checking testbench
    # is latency-agnostic -- the same source is correct whether the FSM is
    # scheduled or not, which is what lets it be reused unchanged in both of
    # native_vs_vhdl_sim_tests.py's entries (--comb and full-build).
    tests.append(
        Test(
            name="self_check_auto_fsm_comb_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_auto_fsm_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    # Same reasoning as self_check_auto_fsm_comb_test above, one layer up: the
    # make_stream_auto_fsm wrapper's handshake never reads .latency, so the
    # same source is correct whether the FSM underneath it is scheduled or
    # still the --comb passthrough -- reused unchanged in both of
    # native_vs_vhdl_sim_tests.py's entries below.
    tests.append(
        Test(
            name="self_check_stream_auto_fsm_comb_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_stream_auto_fsm_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="self_check_bit_math_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_bit_math_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="struct_ctor_positional_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "struct_ctor_positional_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="global_wire_partial_field_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "global_wire_partial_field_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="global_wire_read_write_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "global_wire_read_write_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    tests.append(
        Test(
            name="global_wire_split_driver_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "global_wire_split_driver_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    # Flattened-leaf semantics probes added by the multi-writer review pass:
    # cross-writer readback, 3-writer nested struct splits, hierarchy-buried
    # writers, conditionally (clock-enable style) driven fields, and
    # constant-index array element splits. Each also runs through real GHDL in
    # native_vs_vhdl_sim_tests.py (except global_wire_nested_split_test.py --
    # see that file) so native sim and hardware are held to the same golden
    # behavior.
    for fname in [
        "global_wire_readback_test.py",
        "global_wire_nested_split_test.py",
        "global_wire_hier_writer_test.py",
        "global_wire_cond_driver_test.py",
        "global_wire_array_split_test.py",
        "global_wire_dynamic_index_write_test.py",
    ]:
        tests.append(
            Test(
                name=fname[: -len(".py")],
                category="native_sim",
                cmd=[
                    PYPELINEC,
                    INST_DIR / fname,
                    "--sim",
                    "--comb",
                    "--run",
                    "all",
                ],
            )
        )
    # Global FIFOs, Fifo[T]: order and backpressure through each initializer
    # kind (global_fifo, global_sync_fifo, make_stream_fifo, make_skid_buffer)
    # and a FIFO declared in an imported module.
    tests.append(
        Test(
            name="global_fifo_sim_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "global_fifo_sim_test.py",
                "--sim",
                "--comb",
                "--run",
                "all",
            ],
        )
    )
    # Native sim refuses @MAINs that name more than one rate (#354), through
    # pypeline_sim.py and pypelinec --sim --comb; a bare MAIN still simulates.
    tests.append(
        Test(
            name="multi_rate_sim_refusal_test",
            category="native_sim",
            cmd=[INST_DIR / "multi_rate_sim_refusal_test.py"],
        )
    )
    # @MAINs made in code under pypeline_sim.py: lanes from one factory keep
    # their own registers, wire elements and FIFO model state; duplicate MAIN
    # names stop the run; the multi-rate refusal names made MAINs; MAIN() in a
    # sim hook is an error.
    tests.append(
        Test(
            name="factory_main_sim_test",
            category="native_sim",
            cmd=[INST_DIR / "factory_main_sim_test.py"],
        )
    )
    # Two factory-made lanes calling one @pipeline_latency helper from one
    # source line, with build timing that differs per lane: each lane's call
    # dispatches to its own stage graph (by its MAIN's root frame).
    tests.append(
        Test(
            name="factory_main_pipeline_latency_test",
            category="native_sim",
            cmd=[INST_DIR / "factory_main_pipeline_latency_test.py"],
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(
        main(get_tests, "PipelineC pypeline native (Python-only) simulation tests.")
    )
