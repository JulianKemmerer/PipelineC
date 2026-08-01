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
    register_mux_impl,
    any_uint_t,
    any_int_t,
    any_integer_t,
    INFERRED,
)

from operators.soft_add import make_soft_ripple_add, make_soft_carry_select_add, make_soft_sub
from operators.soft_mult import make_soft_shift_add_mult, make_soft_karatsuba_mult
from operators.soft_div import make_soft_div, make_soft_mod, make_soft_signed_div, make_soft_signed_mod
from operators.soft_cmp import make_soft_sub_cmp, make_soft_sub_cmp_swapped, make_soft_bitwise_cmp
from operators.soft_shift import make_soft_barrel_sl, make_soft_barrel_sr
from operators.soft_misc import make_soft_negate, make_soft_eq, make_soft_mux


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
    """make_soft_div (unsigned restoring division) registered for
    any_uint_t x any_uint_t; make_soft_signed_div (abs-then-fix-sign, wraps
    the same unsigned divider) registered for any_int_t x any_int_t.
    Mixed-signedness DIV (int/uint) is deliberately left unregistered --
    it falls through to the built-in inferred path and from there into the
    PYPELINE_NO_SW_LIB_GUARD guard, which raises loudly, rather than
    matching a factory that was never verified for that case."""
    register_operator("DIV", any_uint_t, any_uint_t, make_soft_div, scope=scope)
    register_operator("DIV", any_int_t, any_int_t, make_soft_signed_div, scope=scope)


def register_soft_mod(scope=None):
    """See register_soft_div -- same unsigned/signed split."""
    register_operator("MOD", any_uint_t, any_uint_t, make_soft_mod, scope=scope)
    register_operator("MOD", any_int_t, any_int_t, make_soft_signed_mod, scope=scope)


def register_soft_cmp(scope=None):
    """Default comparator flavor: widen, subtract (operand order swapped per
    op), take the sign bit -- one subtract, no extra EQ+MUX for any of the
    four ops. QoR-confirmed (docs/SYN_DESIGN.md) to strictly dominate the
    un-swapped make_soft_sub_cmp for GT/LTE and match it for GTE/LT, across
    every measured width and pipeline cut count."""
    for op in ("GT", "GTE", "LT", "LTE"):
        register_operator(op, any_integer_t, any_integer_t, make_soft_sub_cmp_swapped(op), scope=scope)


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


def register_mux(scope=None):
    """Soft MUX for the VAR_REF_RD binary mux tree (variable array indexing)
    -- bitwise select instead of an inferred MUX. Struct/array MUX is
    untouched regardless (pure wiring; the elaborator never looks this
    registry up for those types)."""
    register_mux_impl(any_integer_t, make_soft_mux, scope=scope)


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


_sw_lib_replacements_registered = False


def register_sw_lib_replacements(scope=None):
    """The default-flip set: exactly the operator families that had no
    inferred lowering and used to reach SW_LIB/cpp/pycparser C generation --
    int NEGATE, int compares (GT/GTE/LT/LTE), DIV, MOD, and variable-amount
    shift. Called automatically, once per process, by PY_TO_LOGIC.PARSE_FILE
    so that path stays unreachable from any Pypeline build. Still overridable
    like any other registration -- a design (or this function called again
    with scope=) that registers something more specific afterward wins,
    since the registry always resolves most-recently-registered-first."""
    global _sw_lib_replacements_registered
    if scope is None:
        if _sw_lib_replacements_registered:
            return
        _sw_lib_replacements_registered = True
    register_soft_negate(scope=scope)
    register_soft_cmp(scope=scope)
    register_soft_div(scope=scope)
    register_soft_mod(scope=scope)
    register_soft_shift(scope=scope)


def register_soft_ops(scope=None):
    """Register every soft operator implementation in this library, default
    flavor for each op. Composes: a soft multiply's internal adds, a soft
    divide's internal compares/subtracts, etc. all resolve through the same
    registry -- so this renders arithmetic all the way down to bitwise
    AND/OR/XOR/NOT leaves. Includes the VAR_REF_RD variable-array-index mux
    tree (register_mux); struct/array MUX elsewhere stays inferred (pure
    wiring, never routed through the operator registry)."""
    register_soft_add(scope=scope)
    register_soft_sub(scope=scope)
    register_soft_mult(scope=scope)
    register_soft_div(scope=scope)
    register_soft_mod(scope=scope)
    register_soft_cmp(scope=scope)
    register_soft_eq(scope=scope)
    register_soft_shift(scope=scope)
    register_soft_negate(scope=scope)
    register_mux(scope=scope)
