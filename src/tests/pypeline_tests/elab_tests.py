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
    "two_factory_wrappers_mixed_test.py",
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")],
            category="elab",
            cmd=[PIPELINEC, INST_DIR / filename, "--no_synth"],
            needs_out_dir=True,
        )
        for filename in NO_SYNTH_TEST_FILES
    ]
    # Not run through the pipelinec CLI like the rest of this list: it calls
    # PY_TO_LOGIC.PARSE_FILE directly (in-process) and inspects the resulting
    # FuncLogicLookupTable, since the FuncLogicLookupTable closure-callable
    # collision it regression-tests is otherwise undetectable -- same
    # signature on both sides means no type error either way, and it's not
    # reachable via sim_call (a native-Python path that never touches
    # FuncLogicLookupTable at all).
    tests.append(
        Test(
            name="two_factory_wrappers_test",
            category="elab",
            cmd=[INST_DIR / "two_factory_wrappers_test.py"],
        )
    )
    # Not run through the pipelinec CLI either, for the same reason: it's a silent
    # miscompile (stale self.env entry after a coarser-granularity write) with no
    # ElaborationError on either side of the fix, so it's checked in-process via
    # PY_TO_LOGIC.PARSE_FILE + direct Logic() inspection.
    tests.append(
        Test(
            name="mixed_granularity_reassign_test",
            category="elab",
            cmd=[INST_DIR / "mixed_granularity_reassign_test.py"],
        )
    )
    # Not run through the pipelinec CLI either: pure-unit + in-process
    # PARSE_FILE regression tests for _canonical_func_name/_callable_canonical_name
    # readable-naming behavior and the factory-closure ast_meta src_file/line fix.
    tests.append(
        Test(
            name="factory_closure_naming_test",
            category="elab",
            cmd=[INST_DIR / "factory_closure_naming_test.py"],
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline elaboration-only (--no_synth) tests."))
