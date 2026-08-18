#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-process compiler-internals tests: each calls PY_TO_LOGIC.PARSE_FILE
directly (not via the pypelinec CLI) and asserts on the resulting
parser_state / FuncLogicLookupTable / raised ElaborationError -- checks that
are otherwise invisible to a bare "did it elaborate" check (elab_tests.py) or
to sim_call (a native-Python path that never touches these compiler
internals at all). See unit_tests.py for compiler-helper tests that don't
build a design at all.

Run standalone: python3 elab_introspect_tests.py [-j N]
"""

import sys

from common import INST_DIR, Test, main


def get_tests() -> list:
    tests = []
    # Regression-tests a FuncLogicLookupTable closure-callable naming
    # collision: same signature on both sides means no type error either
    # way, so it's undetectable except by inspecting FuncLogicLookupTable
    # directly after PARSE_FILE.
    tests.append(
        Test(
            name="two_factory_wrappers_test",
            category="elab_introspect",
            cmd=[INST_DIR / "two_factory_wrappers_test.py"],
        )
    )
    # A silent miscompile (stale self.env entry after a coarser-granularity
    # write) with no ElaborationError on either side of the fix -- checked via
    # PY_TO_LOGIC.PARSE_FILE + direct Logic() object inspection.
    tests.append(
        Test(
            name="mixed_granularity_reassign_test",
            category="elab_introspect",
            cmd=[INST_DIR / "mixed_granularity_reassign_test.py"],
        )
    )
    # In-process PARSE_FILE regression test for _process_imports only
    # following ast.Import, never ast.ImportFrom -- checks
    # parser_state.struct_to_field_type_dict directly for a struct only
    # reachable via a transitive ast.ImportFrom hop.
    tests.append(
        Test(
            name="importfrom_test",
            category="elab_introspect",
            cmd=[INST_DIR / "importfrom_test.py"],
        )
    )
    # In-process PARSE_FILE regression test for _elaborate_live_func's
    # struct-registration fallback -- checks
    # parser_state.struct_to_field_type_dict directly for a struct defined
    # entirely inside a factory closure.
    tests.append(
        Test(
            name="closure_local_nested_struct_test",
            category="elab_introspect",
            cmd=[INST_DIR / "closure_local_nested_struct_test.py"],
        )
    )
    # Checks the *type* of exception PARSE_FILE raises for a genuinely
    # undefined reference (PY_TO_LOGIC.ElaborationError, not a raw KeyError).
    tests.append(
        Test(
            name="pylist_value_context_error_test",
            category="elab_introspect",
            cmd=[INST_DIR / "pylist_value_context_error_test.py"],
        )
    )
    # Checks the *type* and message of the ElaborationErrors global Wire[T]
    # multi-writer split-field driving raises (overlapping fields, writing an
    # Input), plus a positive case (disjoint constant-indexed array writes
    # from two writers must NOT error).
    tests.append(
        Test(
            name="global_wire_errors_test",
            category="elab_introspect",
            cmd=[INST_DIR / "global_wire_errors_test.py"],
        )
    )
    # Calls PY_TO_LOGIC.PARSE_FILE twice in one process (what the
    # AUTOPIPELINE pin-and-confirm driver loop does) and compares the
    # resulting parser_states -- guards the sys.modules eviction and
    # trim-memo clearing that only repeated in-process parses exercise.
    tests.append(
        Test(
            name="double_parse_file_test",
            category="elab_introspect",
            cmd=[INST_DIR / "double_parse_file_test.py"],
        )
    )
    # In-process PARSE_FILE regression test for the _loc_str()
    # multiline-instance-collision bug (missing node.end_lineno let
    # same-width, different-line BinOp operands collide into the same
    # submodule instance name).
    tests.append(
        Test(
            name="loc_str_multiline_binop_test",
            category="elab_introspect",
            cmd=[INST_DIR / "loc_str_multiline_binop_test.py"],
        )
    )
    # Checks the *type* and message of the ElaborationError raised when a
    # non-port construct is declared with an @interface's .fwd_t/.fb_t
    # port-pairing type -- merged from four originally separate files, one
    # per declaration site checked: Reg[T]/Feedback[T] (a register is
    # internal state, never a port), local variables (the same restriction,
    # generalized), global Wire[T]/Input[T]/Output[T], and a plain
    # (non-hw_func) function's return value. Plus each site's positive case
    # (the correct .stream_t / inline-constructor-at-a-real-port replacement
    # must stay clean). See the file's own docstring for the full mapping.
    tests.append(
        Test(
            name="interface_type_error_test",
            category="elab_introspect",
            cmd=[INST_DIR / "interface_type_error_test.py"],
        )
    )
    # In-process PARSE_FILE + FuncLogicLookupTable/submodule_instances
    # inspection for the matcher-based generic operator registry --
    # what got instantiated (built-in BIN_OP_* vs. a resolved generic impl)
    # is not visible to sim_call or a bare "does it elaborate" check.
    tests.append(
        Test(
            name="operator_scope_test",
            category="elab_introspect",
            cmd=[INST_DIR / "operator_scope_test.py"],
        )
    )
    # Checks parser_state.clk_mhz / SYN.GET_ALL_USER_CLOCKS directly for
    # make_clock(), plus the *type* of ElaborationError each invalid use
    # raises (non-uint1_t wire, tagging an Output, two clocks at the same
    # rate, a rate matching no @MAIN) -- none of which is visible to a bare
    # "does it elaborate" check the way user_clock_test.py (in elab_tests.py)
    # only proves the happy path builds.
    tests.append(
        Test(
            name="clock_mhz_pragma_test",
            category="elab_introspect",
            cmd=[INST_DIR / "clock_mhz_pragma_test.py"],
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(
        main(
            get_tests,
            "PipelineC pypeline in-process compiler-internals (PARSE_FILE + "
            "parser_state) tests.",
        )
    )
