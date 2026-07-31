"""Activation layer for the soft-operator library.

Nothing in this package changes hardware behavior merely by being imported --
unlike floating_point.py's float16/32/64_t side effect, every registration
here happens only when one of these register_* functions is actually called
(see docs: this deliberately avoids that import-time-side-effect pattern
for new library code). Register once, globally, or scoped to one function:

    from operators.soft import register_soft_ops
    register_soft_ops()                      # whole design, all the way to bitwise leaves
    register_soft_ops(scope=my_func)          # only my_func's own body

    from operators.soft import register_soft_mult, register_soft_mult_karatsuba
    register_soft_mult()                      # shift-and-add (default flavor)
    register_soft_mult_karatsuba()            # overrides it -- last registration wins
"""
from pypeline import (
    register_operator,
    register_left_operator,
    register_unary_operator,
    any_uint_t,
    any_int_t,
    any_integer_t,
    INFERRED,
)

from operators.soft_add import make_soft_ripple_add, make_soft_carry_select_add, make_soft_sub
from operators.soft_mult import make_soft_shift_add_mult, make_soft_karatsuba_mult
from operators.soft_div import make_soft_div, make_soft_mod
from operators.soft_cmp import make_soft_sub_cmp, make_soft_bitwise_cmp
from operators.soft_shift import make_soft_barrel_sl, make_soft_barrel_sr
from operators.soft_misc import make_soft_negate, make_soft_eq


def register_soft_add(scope=None):
    register_operator("PLUS", any_integer_t, any_integer_t, make_soft_ripple_add, scope=scope)


def register_soft_add_carry_select(scope=None):
    register_operator(
        "PLUS", any_integer_t, any_integer_t, make_soft_carry_select_add, scope=scope
    )


def register_soft_sub(scope=None):
    register_operator("MINUS", any_integer_t, any_integer_t, make_soft_sub, scope=scope)


def register_soft_mult(scope=None):
    register_operator(
        "INFERRED_MULT", any_integer_t, any_integer_t, make_soft_shift_add_mult, scope=scope
    )


def register_soft_mult_karatsuba(scope=None):
    register_operator(
        "INFERRED_MULT", any_integer_t, any_integer_t, make_soft_karatsuba_mult, scope=scope
    )


def register_soft_div(scope=None):
    register_operator("DIV", any_integer_t, any_integer_t, make_soft_div, scope=scope)


def register_soft_mod(scope=None):
    register_operator("MOD", any_integer_t, any_integer_t, make_soft_mod, scope=scope)


def register_soft_cmp(scope=None):
    """Default comparator flavor: widen, subtract, take the sign bit."""
    for op in ("GT", "GTE", "LT", "LTE"):
        register_operator(op, any_integer_t, any_integer_t, make_soft_sub_cmp(op), scope=scope)


def register_soft_cmp_bitwise(scope=None):
    """Alternate comparator flavor: MSB-first bitwise magnitude compare."""
    for op in ("GT", "GTE", "LT", "LTE"):
        register_operator(op, any_integer_t, any_integer_t, make_soft_bitwise_cmp(op), scope=scope)


def register_soft_eq(scope=None):
    register_operator("EQ", any_integer_t, any_integer_t, make_soft_eq(negate=False), scope=scope)
    register_operator("NEQ", any_integer_t, any_integer_t, make_soft_eq(negate=True), scope=scope)


def register_soft_shift(scope=None):
    register_left_operator("SL", any_integer_t, make_soft_barrel_sl, scope=scope)
    register_left_operator("SR", any_integer_t, make_soft_barrel_sr, scope=scope)


def register_soft_negate(scope=None):
    register_unary_operator("NEGATE", any_integer_t, make_soft_negate, scope=scope)


def register_inferred_ops(mult=False, add=False, sub=False, cmp=False, scope=None):
    """Escape hatch: pin specific ops back to the built-in inferred path,
    overriding a broader soft registration for this scope (e.g. keep one
    hot function's multiply on a DSP while the rest of the design is soft)."""
    if mult:
        register_operator("INFERRED_MULT", any_integer_t, any_integer_t, INFERRED, scope=scope)
    if add:
        register_operator("PLUS", any_integer_t, any_integer_t, INFERRED, scope=scope)
    if sub:
        register_operator("MINUS", any_integer_t, any_integer_t, INFERRED, scope=scope)
    if cmp:
        for op in ("GT", "GTE", "LT", "LTE"):
            register_operator(op, any_integer_t, any_integer_t, INFERRED, scope=scope)


def register_soft_ops(scope=None):
    """Register every soft operator implementation in this library, default
    flavor for each op. Composes: a soft multiply's internal adds, a soft
    divide's internal compares/subtracts, etc. all resolve through the same
    registry -- so this renders arithmetic all the way down to bitwise
    AND/OR/XOR/NOT leaves (plus MUX/wiring, which this pass does not route
    through the operator registry -- see docs for the current limitation)."""
    register_soft_add(scope=scope)
    register_soft_sub(scope=scope)
    register_soft_mult(scope=scope)
    register_soft_div(scope=scope)
    register_soft_mod(scope=scope)
    register_soft_cmp(scope=scope)
    register_soft_eq(scope=scope)
    register_soft_shift(scope=scope)
    register_soft_negate(scope=scope)
