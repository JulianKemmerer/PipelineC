#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipelinec --no_synth (elaboration only, no autopipelining/synthesis) tests.

Run standalone: python3 elab_tests.py [-j N]
"""

import sys

from common import INST_DIR, PIPELINEC, Test, main

# fmt: off
NO_SYNTH_TEST_FILES = [
    "autopipeline_test.py",
    "global_wires_test.py",
    "compound_init_test.py",
    "bit_manip_test.py",
    "import_test.py",
    "func_wires_test.py",
    "dangling_logic_test.py",
    "stream_pipeline_test.py",
    "enum_test.py",
    "char_array_test.py",
    "sim_print_test.py",
]
# fmt: on


def get_tests() -> list:
    return [
        Test(
            name=filename[: -len(".py")],
            category="elab",
            cmd=[PIPELINEC, INST_DIR / filename, "--no_synth"],
            needs_out_dir=True,
        )
        for filename in NO_SYNTH_TEST_FILES
    ]


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline elaboration-only (--no_synth) tests."))
