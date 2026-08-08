# pyright: reportInvalidTypeForm=none
"""KNOWN ISSUE (reproducer, not a fix): SYN._IS_PYPELINE_OPERATOR_LIBRARY_CODE
never returns True for any real operator-library callable, so operator-
library entities (AUTOFSM's operand muxes, the soft-operator library under
include/pypeline/operators/) never get cached in path_delay_cache the way
the predicate exists to enable -- delays for them are re-measured on every
build instead of read from cache. Effect is BUILD TIME ONLY; delay numbers
themselves are correct either way (see src/SYN.py's own comment right above
_autofsm_mux_entities_cache, ~line 4064).

Root cause (documented in src/SYN.py, not fixed here): the predicate calls
inspect.getsourcefile() on the callable recorded in
parser_state.pypeline_entity_callables, which is deliberately the @hw_func
WRAPPER (see PY_TO_LOGIC._elaborate_live_func) -- and a wrapper's source file
is always pypeline.py, never the operator-library file that defined the
wrapped function. `inspect.unwrap(live_callable)` before getsourcefile()
would fix it.

This test elaborates a design that calls a real operator-library function
(register_soft_add, via the soft-operator library that
_IS_PYPELINE_OPERATOR_LIBRARY_CODE was written to classify) and asserts the
predicate returns True for its Logic -- which currently fails, proving the
bug in-process rather than only by reading the source comment.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)


def test_operator_library_predicate_fires_for_soft_op_callable():
    import tempfile

    import PY_TO_LOGIC
    import SYN

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(
        prefix="operator_library_predicate_test_"
    )
    parser_state = PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))

    entity_callables = getattr(parser_state, "pypeline_entity_callables", {})
    soft_op_logics = [
        logic
        for func_name, logic in parser_state.FuncLogicLookupTable.items()
        if "soft_add" in func_name or "soft_cmp" in func_name
    ]
    assert soft_op_logics, (
        "expected at least one soft-operator-library Logic in "
        "FuncLogicLookupTable -- design below must call one"
    )

    fires_for_any = any(
        SYN._IS_PYPELINE_OPERATOR_LIBRARY_CODE(logic, parser_state)
        for logic in soft_op_logics
    )
    assert fires_for_any, (
        "SYN._IS_PYPELINE_OPERATOR_LIBRARY_CODE never returned True for any "
        "soft-operator-library Logic -- known issue: it inspects the "
        "@hw_func WRAPPER's source file (always pypeline.py) instead of the "
        "wrapped function's; inspect.unwrap() at that lookup would fix it. "
        "If this assertion now passes, the bug is fixed -- promote this test "
        "out of known_issues."
    )


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()


# Below: a minimal design that reaches the soft-operator library so PARSE_FILE
# (invoked above, on this same file) has a real soft_add Logic to inspect --
# make_soft_add_ripple() is the exact factory _autofsm_mux_entities_cache's
# comment (src/SYN.py) names as one of the callables this predicate should
# classify as library code.
from pypeline import MAIN, uint17_t

from operators.soft_add import make_soft_add_ripple

soft_add_ripple = make_soft_add_ripple(uint17_t, uint17_t)


@MAIN
def operator_library_predicate_design(a: uint17_t, b: uint17_t) -> uint17_t:
    return soft_add_ripple(a, b)
