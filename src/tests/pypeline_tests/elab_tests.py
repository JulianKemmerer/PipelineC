#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipelinec --no_synth (elaboration only, no autopipelining/synthesis) tests.

Run standalone: python3 elab_tests.py [-j N]
"""

import sys

from common import INST_DIR, PIPELINEC, Test, main

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
    # Not run through the pipelinec CLI either: in-process PARSE_FILE regression
    # test for _process_imports only following ast.Import, never ast.ImportFrom --
    # checks parser_state.struct_to_field_type_dict directly for a struct only
    # reachable via a transitive ast.ImportFrom hop.
    tests.append(
        Test(
            name="importfrom_test",
            category="elab",
            cmd=[INST_DIR / "importfrom_test.py"],
        )
    )
    # Not run through the pipelinec CLI either: in-process PARSE_FILE regression
    # test for _elaborate_live_func's struct-registration fallback (used to
    # mis-stringify struct-typed fields via bare str(a) and never recurse into
    # nested struct-typed fields) -- checks parser_state.struct_to_field_type_dict
    # directly for a struct defined entirely inside a factory closure.
    tests.append(
        Test(
            name="closure_local_nested_struct_test",
            category="elab",
            cmd=[INST_DIR / "closure_local_nested_struct_test.py"],
        )
    )
    # Not run through the pipelinec CLI either: it checks the *type* of
    # exception PARSE_FILE raises for a genuinely-undefined reference
    # (PY_TO_LOGIC.ElaborationError, not a raw KeyError), which needs direct
    # in-process access to the exception object.
    tests.append(
        Test(
            name="pylist_value_context_error_test",
            category="elab",
            cmd=[INST_DIR / "pylist_value_context_error_test.py"],
        )
    )
    # Not run through the pipelinec CLI either: checks the *type* and message
    # of the ElaborationErrors global Wire[T] multi-writer split-field driving
    # raises (overlapping fields, writing an Input), plus a positive case
    # (disjoint constant-indexed array writes from two writers must NOT error)
    # -- needs direct in-process PARSE_FILE + exception inspection, same
    # pattern as pylist_value_context_error_test.py above.
    tests.append(
        Test(
            name="global_wire_errors_test",
            category="elab",
            cmd=[INST_DIR / "global_wire_errors_test.py"],
        )
    )
    # Not run through the pipelinec CLI either, for the same reason as
    # two_factory_wrappers_test.py: a naming collision between dot_a/dot_b
    # would be silent (same signature on both sides), so it's checked
    # in-process via PY_TO_LOGIC.PARSE_FILE + FuncLogicLookupTable inspection.
    tests.append(
        Test(
            name="factory_closure_list_test",
            category="elab",
            cmd=[INST_DIR / "factory_closure_list_test.py"],
        )
    )
    # Not run through the pipelinec CLI: calls PY_TO_LOGIC.PARSE_FILE twice in
    # one process (what the AUTOPIPELINE pin-and-confirm driver loop does) and
    # compares the resulting parser_states -- guards the sys.modules eviction
    # and trim-memo clearing that only repeated in-process parses exercise.
    tests.append(
        Test(
            name="double_parse_file_test",
            category="elab",
            cmd=[INST_DIR / "double_parse_file_test.py"],
        )
    )
    # Not run through the pipelinec CLI: pure-unit tests for the AUTOPIPELINE
    # .latency machinery (SYN.HARVEST_AUTOPIPELINE_LATENCIES grouping +
    # divergence detection, SYN.SEED_TIMING_PARAMS_FROM_PREVIOUS two-tier
    # matching + call-site-change detection, CANONICAL_CALLABLE_KEY
    # determinism, latency cache/read-flag behavior) against hand-built
    # fixtures -- no design build involved.
    tests.append(
        Test(
            name="autopipeline_harvest_test",
            category="elab",
            cmd=[INST_DIR / "autopipeline_harvest_test.py"],
        )
    )
    # Not run through the pipelinec CLI either: in-process PARSE_FILE
    # regression test for the _loc_str() multiline-instance-collision bug
    # (missing node.end_lineno let same-width, different-line BinOp operands
    # collide into the same submodule instance name and raise "Duplicate
    # submodule instance name") -- checks that a multi-line chained-XOR
    # expression designed to collide under the old end_col_offset-only
    # scheme elaborates cleanly.
    tests.append(
        Test(
            name="loc_str_multiline_binop_test",
            category="elab",
            cmd=[INST_DIR / "loc_str_multiline_binop_test.py"],
        )
    )
    # Not run through the pipelinec CLI either: checks the *type* and message of
    # the ElaborationError raised by Reg[T] where T is an @interface's .fwd_t/
    # .fb_t (a register is internal state, never a port, so it never needs -- or
    # should imply -- the port-pairing signal), plus positive cases
    # (Reg[.stream_t], Feedback[.fwd_t] must both stay clean) -- same in-process
    # PARSE_FILE + exception-inspection pattern as global_wire_errors_test.py.
    tests.append(
        Test(
            name="reg_interface_type_error_test",
            category="elab",
            cmd=[INST_DIR / "reg_interface_type_error_test.py"],
        )
    )
    # Not run through the pipelinec CLI either: same in-process PARSE_FILE +
    # ElaborationError-inspection pattern as reg_interface_type_error_test.py,
    # but for the generalized check -- no plain local variable (not just
    # Reg[T]) may be declared with an @interface's .fwd_t/.fb_t type. Also
    # covers the companion feature this generalization required: constructing
    # a .fwd_t/.fb_t value inline as a call argument (no local at all).
    tests.append(
        Test(
            name="local_var_interface_type_error_test",
            category="elab",
            cmd=[INST_DIR / "local_var_interface_type_error_test.py"],
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline elaboration-only (--no_synth) tests."))
