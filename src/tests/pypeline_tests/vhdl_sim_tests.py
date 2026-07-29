#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real VHDL simulation tests (--sim --comb --cocotb --ghdl) -- exercises the
generated VHDL through GHDL, not just native Python simulation.

Only self-checking @MAIN designs that use sim_assert/sim_finish for in-hardware
checking are eligible here: @sim_input/@sim_output-based designs are invisible to
the hardware elaborator (no real VHDL is generated for them), so running them
through GHDL would not exercise anything meaningful. See native_sim_tests.py for
the full native-only test suite (most of which can't be reused here without
moving their Python-side golden-model/assert checking into hardware first).

Run standalone: python3 vhdl_sim_tests.py [-j N]
"""

import sys

from common import INST_DIR, PIPELINEC, Test, main

# fmt: off
# (filename, source_dir, run_arg)
VHDL_SIM_TEST_FILES = [
    ("self_check_counter_test.py", INST_DIR, "all"),
    ("self_check_fifo_test.py", INST_DIR, "all"),
    ("self_check_bit_math_test.py", INST_DIR, "all"),
    ("struct_ctor_positional_test.py", INST_DIR, "all"),
    # AUTOFSM through real GHDL in --comb mode (passthrough). The scheduled
    # FSM hardware is exercised by the non---comb autofsm_vhdl_sim_test in
    # synth_tests.py, which cannot live here (this list is --comb only).
    ("self_check_autofsm_test.py", INST_DIR, "all"),
    ("global_wire_partial_field_test.py", INST_DIR, "all"),
    ("global_wire_read_write_test.py", INST_DIR, "all"),
    ("global_wire_split_driver_test.py", INST_DIR, "all"),
    # Flattened-leaf semantics probes (multi-writer review pass): cross-writer
    # readback, 3-writer nested struct splits, hierarchy-buried writers,
    # conditional (clock-enable style) field drivers, constant-index array
    # element splits -- the same self-checking designs as their native_sim
    # registrations, proven against real GHDL.
    ("global_wire_readback_test.py", INST_DIR, "all"),
    ("global_wire_nested_split_test.py", INST_DIR, "all"),
    ("global_wire_hier_writer_test.py", INST_DIR, "all"),
    ("global_wire_cond_driver_test.py", INST_DIR, "all"),
    ("global_wire_array_split_test.py", INST_DIR, "all"),
    ("global_wire_dynamic_index_write_test.py", INST_DIR, "all"),
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")],
            category="vhdl_sim",
            cmd=[
                PIPELINEC,
                source_dir / filename,
                "--sim",
                "--comb",
                "--cocotb",
                "--ghdl",
                "--run",
                run_arg,
            ],
            needs_out_dir=True,
        )
        for filename, source_dir, run_arg in VHDL_SIM_TEST_FILES
    ]
    return tests


if __name__ == "__main__":
    sys.exit(
        main(get_tests, "PipelineC pypeline VHDL simulation (--cocotb --ghdl) tests.")
    )
