# pyright: reportInvalidTypeForm=none
"""Regression test for array-typed == / != producing an illegal VHDL entity
name. PY_TO_LOGIC's built-in binary-operator naming (_bin_func_name,
PY_TO_LOGIC.py) used to f-string-interpolate each operand's raw C type string
directly into the BIN_OP_* entity name with no sanitization, so an
array-typed comparison (e.g. uint1_t[16] == uint1_t[16]) produced an entity
name containing unescaped '[' ']' (e.g. "BIN_OP_EQ_uint1_t[16]_uint1_t[16]")
-- illegal in a VHDL `entity ... is` / `end ...;` declaration. Scalar-typed
comparisons never hit this: scalar C type strings never contain brackets.

Run through real synthesis (not just elaboration) since that's what actually
parses/rejects the generated VHDL text -- an in-process
FuncLogicLookupTable/submodule_instances inspection only proves the
compiler's own bookkeeping is bracket-free, not that the emitted VHDL is
legal (see operator_scope_test.py's
test_array_equality_operator_names_are_bracket_free for that in-process
check, and factory_closure_naming_test.py for the pure-unit-level
_bin_func_name/_unary_func_name checks). Same bug class as
underscore_name_test.py (illegal-character VHDL identifier), different
illegal character.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, uint1_t


@MAIN
def array_compare_bracket_name_main(
    a: uint1_t[16], b: uint1_t[16], c: uint1_t[16]
) -> uint1_t:
    # eq/neq deliberately compare DIFFERENT operand pairs (a,b) vs (b,c) --
    # comparing the same pair with == and != would make them tautological
    # opposites, collapsing the mux below to a constant and optimizing every
    # input away (observed: PyRTL's Fmax calc then divides by a zero-length
    # critical path).
    eq: uint1_t = (a == b)
    neq: uint1_t = (b != c)
    result: uint1_t = eq
    if neq:
        result = neq
    return result
