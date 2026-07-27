#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native (Python-only) simulation tests -- no VHDL/GHDL involved. See
vhdl_sim_tests.py for the subset of self-checking designs also run through real
VHDL simulation (--cocotb --ghdl).

Run standalone: python3 native_sim_tests.py [-j N]
"""

import sys

from common import INST_DIR, PIPELINEC, PYPELINE_SIM, Test, main

# fmt: off
PLAIN_PYTHON_TEST_FILES = [
    "stream_pipeline_test.py",
    "autopipeline_test.py",
    "valid_ready_mcp_test.py",
    "float32_add_test.py",
    "float_ops_test.py",
    "fixed_point_test.py",
    "pypeline_test.py",
    "reg_init_test.py",
    "reg_bitwise_mask_test.py",
    "struct_ctor_narrow_test.py",
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
    "interface_test.py",
    "interface_func_test.py",
    "interface_func_loop_test.py",
    "interface_boundary_test.py",
    "interface_array_port_test.py",
    "interface_mixing_rules_test.py",
    "interface_hw_func_pairing_error_test.py",
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
                PIPELINEC,
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
                PIPELINEC,
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
    # Self-checking sim_assert/sim_finish designs -- no external Python
    # sim_call/assert harness needed. Same source files are also registered in
    # vhdl_sim_tests.py under --cocotb --ghdl, proving native and VHDL sim agree.
    tests.append(
        Test(
            name="self_check_counter_test",
            category="native_sim",
            cmd=[
                PIPELINEC,
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
                PIPELINEC,
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
            name="self_check_bit_math_test",
            category="native_sim",
            cmd=[
                PIPELINEC,
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
            name="global_wire_partial_field_test",
            category="native_sim",
            cmd=[
                PIPELINEC,
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
                PIPELINEC,
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
                PIPELINEC,
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
    # vhdl_sim_tests.py so native sim and hardware are held to the same golden
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
                    PIPELINEC,
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
