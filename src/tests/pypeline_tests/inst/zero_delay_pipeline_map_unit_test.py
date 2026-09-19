#!/usr/bin/env python3
"""Regression for zero-delay generated helpers in pipeline-map timing.

CONST_REF_RD and similar helpers deliberately skip path-delay synthesis.  The
planner must normalize those known-zero children to delay=0 before performing
pipeline-map arithmetic, without masking genuinely unresolved timing data.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC
import AUTO_PIPELINE


def _parser_state(*logics):
    return SimpleNamespace(
        FuncLogicLookupTable={logic.func_name: logic for logic in logics},
        func_marked_wires=set(),
        func_marked_blackbox=set(),
        func_fixed_latency={},
    )


def test_const_ref_none_delay_is_normalized_to_zero():
    child = C_TO_LOGIC.Logic()
    child.func_name = C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX + "_fixture"
    assert child.delay is None

    parent = C_TO_LOGIC.Logic()
    parent.func_name = "parent"
    parent.submodule_instances["read_field"] = child.func_name

    parser_state = _parser_state(parent, child)
    unresolved = AUTO_PIPELINE.NORMALIZE_KNOWN_ZERO_DELAY_SUBMODULE_DELAYS(parent, parser_state)

    assert unresolved is None
    assert child.delay == 0


def test_unknown_none_delay_remains_an_error_candidate():
    child = C_TO_LOGIC.Logic()
    child.func_name = "ordinary_unmeasured_child"
    assert child.delay is None

    parent = C_TO_LOGIC.Logic()
    parent.func_name = "parent"
    parent.submodule_instances["child"] = child.func_name

    parser_state = _parser_state(parent, child)
    unresolved = AUTO_PIPELINE.NORMALIZE_KNOWN_ZERO_DELAY_SUBMODULE_DELAYS(parent, parser_state)

    assert unresolved is child
    assert child.delay is None


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
