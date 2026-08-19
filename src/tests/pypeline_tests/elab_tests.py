#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pypelinec --no_synth (elaboration only, no autopipelining/synthesis) tests.

"Does it elaborate" only -- exit code is the entire verdict. See
elab_introspect_tests.py for tests that call PY_TO_LOGIC.PARSE_FILE
in-process and assert on parser_state/FuncLogicLookupTable/raised
ElaborationErrors, and unit_tests.py for pure compiler-helper tests that
don't build a design at all.

Run standalone: python3 elab_tests.py [-j N]
"""

import sys

from common import INST_DIR, PYPELINEC, Test, main

# fmt: off
NO_SYNTH_TEST_FILES = [
    # Only files not already elaborated for free as part of synth_tests.py
    # (which runs full elaboration + synthesis, a superset of --no_synth) belong
    # here -- e.g. designs that don't synthesize well/fast, or aren't in
    # synth_tests.py's SYNTH_TEST_FILES for some other reason. Anything also
    # listed there should NOT be duplicated here.
    "autopipeline_test.py",
    "global_wires_test.py",
    "clock_domain_inference_test.py",
    "user_clock_test.py",
    "compound_init_test.py",
    "bit_manip_test.py",
    "import_test.py",
    "func_wires_test.py",
    "dangling_logic_test.py",
    "type_bytes_test.py",
    "sim_input_output_elab_test.py",
    "array_2d_order_test.py",
    "pylist_value_context_test.py",
    "keyword_call_test.py",
    "cast_test.py",
    "cast_interface_test.py",
    "cast_hw_func_test.py",
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")],
            category="elab",
            cmd=[PYPELINEC, INST_DIR / filename, "--no_synth"],
            needs_out_dir=True,
        )
        for filename in NO_SYNTH_TEST_FILES
    ]
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline elaboration-only (--no_synth) tests."))
