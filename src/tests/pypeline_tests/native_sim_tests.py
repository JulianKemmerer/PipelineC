#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native (Python-only) simulation tests -- no VHDL/GHDL involved. See
native_vs_vhdl_sim_tests.py for the self-checking designs that ALSO run
through real cocotb+GHDL, with the two sims' sim_print(debug=True) output
diffed cycle by cycle.

Run standalone: python3 native_sim_tests.py [-j N]
"""

import sys

from common import EXAMPLES_PYPELINE_DIR, INST_DIR, PYPELINEC, PYPELINE_SIM, Test, main

# fmt: off
PLAIN_PYTHON_TEST_FILES = [
    "stream_pipeline_test.py",
    "autopipeline_test.py",
    "autofsm_test.py",
    "valid_ready_mcp_test.py",
    "float32_add_test.py",
    "float_ops_test.py",
    "fixed_point_test.py",
    "pypeline_test.py",
    "reg_init_test.py",
    "reg_bitwise_mask_test.py",
    "struct_ctor_narrow_test.py",
    "cast_test.py",
    "cast_interface_test.py",
    "cast_hw_func_test.py",
    "reg_undefined_width_test.py",
    "feedback_reeval_test.py",
    "bit_math_test.py",
    "vhdl_text_test.py",
    "fifo_test.py",
    "stream_fifo_test.py",
    "axis_test.py",
    "dwidth_converter_test.py",
    "axis_byte_stream_test.py",
    "func_wires_test.py",
    "if_test.py",
    "enum_test.py",
    "char_array_test.py",
    "sim_print_test.py",
    "sim_assert_finish_test.py",
    "type_bytes_test.py",
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
    # dsp/dsp_tb.py testbench-library end-to-end examples (each file drives two
    # @MAINs -- elastic + valid_only -- so --run must exceed both tbs' deadlines).
    DSP_DIR = EXAMPLES_PYPELINE_DIR / "dsp"
    for fname, run_n in [
        ("magnitude_tb.py", 1000),
        ("dc_block_tb.py", 4000),
        ("moving_avg_tb.py", 3000),
    ]:
        tests.append(
            Test(
                name=fname[: -len(".py")],
                category="native_sim",
                cmd=[PYPELINEC, DSP_DIR / fname, "--sim", "--comb", "--run", str(run_n)],
            )
        )
    # PDW project: hysteresis SM / candidate-PDW extractor (3 @MAINs --
    # elastic, valid_only, and a CW/jamming max_width-cap check).
    tests.append(
        Test(
            name="pulse_detect_tb",
            category="native_sim",
            cmd=[
                PYPELINEC,
                EXAMPLES_PYPELINE_DIR / "dsp" / "pdw" / "pulse_detect" / "pulse_detect_tb.py",
                "--sim",
                "--comb",
                "--run",
                "500",
            ],
        )
    )
    # PDW project: top-level testbench (top.py) -- exact golden model of the
    # whole pulse_gen -> detect_pulses chain, several pulse settings incl.
    # filtered-out ones and the CW/max_width cap.
    #
    # pdw_tb.py itself is registered in known_issues_tests.py, not here:
    # PATH_B_SKEW = 0 -- the CORRECT Path B alignment -- is EXPECTED to fail
    # until pulse_detect.py's delay line is fixed to match (see that
    # function's docstring and README.md section 5's "Known gap" note). Once
    # that hardware fix lands, pdw_tb.py becomes its acceptance test and
    # should move here.
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
    # AUTOFSM in --comb mode: the call site is still the combinational
    # passthrough (latency 0), so this also proves the self-checking testbench
    # is latency-agnostic -- the same source is correct whether the FSM is
    # scheduled or not, which is what lets it be reused unchanged in both of
    # native_vs_vhdl_sim_tests.py's entries (--comb and full-build).
    tests.append(
        Test(
            name="self_check_autofsm_comb_test",
            category="native_sim",
            cmd=[
                PYPELINEC,
                INST_DIR / "self_check_autofsm_test.py",
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
    return tests


if __name__ == "__main__":
    sys.exit(
        main(get_tests, "PipelineC pypeline native (Python-only) simulation tests.")
    )
