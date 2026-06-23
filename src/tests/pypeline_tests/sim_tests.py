#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plain `python3 <file>` simulation tests (no pipelinec elaboration/synthesis).

Run standalone: python3 sim_tests.py [-j N]
"""

import sys

from common import INST_DIR, PYPELINE_SIM, Test, main

# fmt: off
PLAIN_PYTHON_TEST_FILES = [
    "stream_pipeline_test.py",
    "valid_ready_mcp_test.py",
    "float32_add_test.py",
    "pypeline_test.py",
    "reg_init_test.py",
    "bit_math_test.py",
    "vhdl_text_test.py",
    "fifo_test.py",
    "stream_fifo_test.py",
    "axis_test.py",
    "dwidth_converter_test.py",
    "func_wires_test.py",
    "if_test.py",
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")],
            category="sim",
            cmd=[INST_DIR / filename],
        )
        for filename in PLAIN_PYTHON_TEST_FILES
    ]
    tests.append(
        Test(
            name="global_wires_sim_test",
            category="sim",
            cmd=[PYPELINE_SIM, INST_DIR / "global_wires_sim_test.py", "--run", "10"],
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline sim tests (plain python3 calls)."))
