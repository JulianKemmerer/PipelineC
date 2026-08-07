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
import functools

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

from operators.soft_add import make_soft_add_ripple, make_soft_add_carry_select, make_soft_sub
from operators.soft_mult import make_soft_mult_shift_add, make_soft_mult_karatsuba
from operators.soft_div import (
    make_soft_div, make_soft_mod, make_soft_signed_div, make_soft_signed_mod,
    make_soft_div_radix4, make_soft_mod_radix4,
    make_soft_div_signed_radix4, make_soft_mod_signed_radix4,
    make_soft_div_radix, make_soft_mod_radix,
    make_soft_div_signed_radix, make_soft_mod_signed_radix,
)
from operators.soft_cmp import (
    make_soft_cmp_sub, make_soft_cmp_sub_swapped, make_soft_cmp_bitwise,
    make_soft_cmp_prefix,
)
from operators.soft_shift import make_soft_shift_barrel_sl, make_soft_shift_barrel_sr
from operators.soft_misc import make_soft_negate, make_soft_eq, make_soft_mux


def register_soft_add(scope=None):
    register_operator("PLUS", any_integer_t, any_integer_t, make_soft_add_ripple, scope=scope)


def register_soft_add_carry_select(scope=None):
    register_operator(
        "PLUS", any_integer_t, any_integer_t, make_soft_add_carry_select, scope=scope
    )


def register_soft_sub(scope=None):
    register_operator("MINUS", any_integer_t, any_integer_t, make_soft_sub, scope=scope)


def register_soft_mult(scope=None):
    """make_soft_mult_shift_add registered for any_uint_t x any_uint_t only.

    Signed (and mixed-signedness) multiply is deliberately left unregistered.
    Both soft multipliers sum `a << i` over the set bits of b treating b as
    UNSIGNED, but for a signed b the MSB carries weight -2**(n-1), so the final
    partial product would have to be subtracted rather than added. Registering
    these for any_integer_t (as an earlier version did) silently emitted wrong
    hardware for signed operands -- e.g. int5_t (-16) * (-16) elaborated to -256
    instead of 256.

    Unlike the DIV/MOD split (where no inferred lowering exists, so signed hits
    the PYPELINE_NO_SW_LIB_GUARD guard and raises loudly), INFERRED_MULT *does*
    have a built-in lowering: an unregistered signed multiply falls through to
    the HDL `*` operator, which is correct for signed. So the failure mode here
    is not an error but a silent fallback to an inferred (DSP/LUT) multiplier --
    verified: a signed @MAIN elaborates to BIN_OP_INFERRED_MULT_int16_t_int16_t
    with zero soft-mult entities. Worth knowing if you called register_soft_ops
    specifically to keep hard multipliers out of a design: signed operands will
    still get one until a signed soft multiplier exists. When one is written,
    register it here for any_int_t the way make_soft_signed_div is.
    """
    register_operator(
        "INFERRED_MULT", any_uint_t, any_uint_t, make_soft_mult_shift_add, scope=scope
    )


def register_soft_mult_karatsuba(threshold=None, scope=None):
    """See register_soft_mult -- same unsigned-only restriction, same reason
    (make_soft_mult_karatsuba bottoms out in make_soft_mult_shift_add and
    inherits its unsigned-only partial-product summation).

    threshold: base-case width override, forwarded to make_soft_mult_karatsuba.
    Default None uses that factory's own default rather than duplicating the
    number here, so there is one source of truth for it -- see
    make_soft_mult_karatsuba's docstring and docs/SYN_DESIGN.md section 10 for
    the measurement behind the current default (16: no threshold below the
    operand width ever beat "don't split" at uint8/uint16, measured directly;
    unmeasured above 16 bits, where a real optimum may still exist)."""
    factory = make_soft_mult_karatsuba
    if threshold is not None:
        factory = functools.partial(make_soft_mult_karatsuba, threshold=threshold)
    register_operator("INFERRED_MULT", any_uint_t, any_uint_t, factory, scope=scope)


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


def register_soft_div_radix4(scope=None):
    """Alternate DIV flavor: radix-4 restoring division (2 quotient bits per
    step instead of 1, half the steps of register_soft_div's plain restoring
    divider). Autopipelined-fmax-sweep-confirmed (docs: div_fmax_sweep
    exploration; see make_soft_div_radix's docstring in soft_div.py) at 34.1
    MHz vs. 22.4-22.9 MHz for the plain restoring divider at 16 pipeline
    stages under PyRTL estimates -- the best of bits_per_step in {1,2,3} and
    six other algorithmic variants tried there (non-restoring, a
    signed-digit/carry-save-shaped design, and four quotient-assembly/compare
    micro-variants of plain radix-2). Same unsigned/signed split as
    register_soft_div; last registration for an overlapping matcher wins, so
    calling this after register_soft_div (or as part of a fresh
    register_soft_ops-style call) overrides DIV's flavor for this scope
    without touching MOD unless register_soft_mod_radix4 is also called."""
    register_operator("DIV", any_uint_t, any_uint_t, make_soft_div_radix4, scope=scope)
    register_operator("DIV", any_int_t, any_int_t, make_soft_div_signed_radix4, scope=scope)


def register_soft_mod_radix4(scope=None):
    """See register_soft_div_radix4 -- same radix-4 flavor, for MOD."""
    register_operator("MOD", any_uint_t, any_uint_t, make_soft_mod_radix4, scope=scope)
    register_operator("MOD", any_int_t, any_int_t, make_soft_mod_signed_radix4, scope=scope)


def register_soft_div_radix(bits_per_step, scope=None):
    """Generalized form of register_soft_div_radix4 for any bits_per_step.
    bits_per_step=2 (what register_soft_div_radix4 calls) measured best in
    the fmax sweep; bits_per_step=3 was close behind (33.0 MHz); 1 gives no
    benefit over register_soft_div; 4+ elaborates and sims correctly but
    wasn't benchmarked there (PyRTL synthesis of the resulting
    2**bits_per_step-1-way precompute/priority-select didn't finish in 5
    minutes for bits_per_step=4's 15-way select) -- use higher values with
    that unmeasured-not-ranked-last caveat in mind. Same unsigned/signed
    split and last-registration-wins semantics as register_soft_div_radix4."""
    register_operator(
        "DIV", any_uint_t, any_uint_t, make_soft_div_radix(bits_per_step), scope=scope
    )
    register_operator(
        "DIV", any_int_t, any_int_t, make_soft_div_signed_radix(bits_per_step), scope=scope
    )


def register_soft_mod_radix(bits_per_step, scope=None):
    """See register_soft_div_radix -- same generalized radix family, for MOD."""
    register_operator(
        "MOD", any_uint_t, any_uint_t, make_soft_mod_radix(bits_per_step), scope=scope
    )
    register_operator(
        "MOD", any_int_t, any_int_t, make_soft_mod_signed_radix(bits_per_step), scope=scope
    )


def register_soft_cmp(scope=None):
    """Default comparator flavor (changed 2026-08, see docs/SYN_DESIGN.md
    section 8): log2(n)-deep parallel-prefix magnitude compare -- combines
    per-bit (gt,lt) codes with an associative leader-select operator in a
    balanced tree, one @hw_func per tree level.

    Vivado-confirmed (xc7a200tffg1156-2, all 32 (op,width) combinations
    measured) to win 28/32 vs. the previous default (make_soft_cmp_sub_swapped,
    still available via register_soft_cmp_sub_swapped) at n_cuts>=1 -- the win
    is decisive and widens with operand width across all four ops (up to 40%
    faster at deep cuts for uint64 GTE). The 4 losses are GTE/LTE specifically
    at the two narrowest widths (uint8, uint16): the previous default's
    GTE/LTE cost equals its GT/LT cost (one subtract, operand-swapped), and
    Vivado already optimizes that single small subtract very well at 8-16
    bits, so this structure's fixed per-level tree overhead doesn't pay for
    itself until the comparator is wide enough to be the real bottleneck.
    Promoted anyway as the unconditional default -- see make_soft_cmp_prefix's
    docstring in soft_cmp.py for the full numbers and register_soft_cmp_sub_swapped
    below for the narrow-GTE/LTE-favoring alternative."""
    for op in ("GT", "GTE", "LT", "LTE"):
        register_operator(op, any_integer_t, any_integer_t, make_soft_cmp_prefix(op), scope=scope)


def register_soft_cmp_bitwise(scope=None):
    """Alternate comparator flavor: MSB-first bitwise magnitude compare."""
    for op in ("GT", "GTE", "LT", "LTE"):
        register_operator(op, any_integer_t, any_integer_t, make_soft_cmp_bitwise(op), scope=scope)


def register_soft_cmp_sub_swapped(scope=None):
    """Alternate comparator flavor: widen, subtract (operand order swapped
    per op), take the sign bit -- one subtract, no extra EQ+MUX for any of
    the four ops. The library default through 2026-08 (see
    docs/SYN_DESIGN.md section 8); superseded by register_soft_cmp's
    parallel-prefix default, but still Vivado-confirmed faster than it for
    GTE/LTE specifically at 8/16-bit operand widths -- reach for this via
    scope= on a function known to do narrow-width GTE/LTE comparisons."""
    for op in ("GT", "GTE", "LT", "LTE"):
        register_operator(op, any_integer_t, any_integer_t, make_soft_cmp_sub_swapped(op), scope=scope)


def register_soft_cmp_prefix(scope=None):
    """Alias for register_soft_cmp (the parallel-prefix comparator is the
    library default as of 2026-08) -- kept as an explicit name for callers
    that want to name the flavor regardless of which one is currently
    default. See register_soft_cmp's docstring for the measured numbers."""
    register_soft_cmp(scope=scope)


def register_soft_eq(scope=None):
    register_operator("EQ", any_integer_t, any_integer_t, make_soft_eq(negate=False), scope=scope)
    register_operator("NEQ", any_integer_t, any_integer_t, make_soft_eq(negate=True), scope=scope)


def register_soft_shift(scope=None):
    register_left_operator("SL", any_integer_t, make_soft_shift_barrel_sl, scope=scope)
    register_left_operator("SR", any_integer_t, make_soft_shift_barrel_sr, scope=scope)


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
    since the registry always resolves most-recently-registered-first.

    DIV/MOD default to the radix-4 flavor (register_soft_div_radix4/
    register_soft_mod_radix4), not the plain one-bit-per-step restoring
    divider -- autopipelined-fmax-sweep-confirmed at 34.1 MHz vs. 22.4-22.9
    MHz for plain restoring division at 16 pipeline stages under PyRTL
    estimates (docs: div_fmax_sweep exploration; see make_soft_div_radix's
    docstring in soft_div.py). This is the only automatic, zero-registration
    DIV/MOD path in Pypeline -- there is no inferred HDL '/' equivalent to
    the built-in '*' that register_soft_mult's callers can fall back to;
    an unregistered DIV/MOD hits C_TO_LOGIC.PYPELINE_NO_SW_LIB_GUARD and
    raises loudly instead. register_soft_ops (the separate, explicitly-
    opt-in "register everything soft" call below) still defaults DIV/MOD to
    the plain divider, unchanged -- this function is specifically the
    automatic fallback, not a general recommendation to prefer radix-4
    whenever soft division is registered by hand."""
    global _sw_lib_replacements_registered
    if scope is None:
        if _sw_lib_replacements_registered:
            return
        _sw_lib_replacements_registered = True
    register_soft_negate(scope=scope)
    register_soft_cmp(scope=scope)
    register_soft_div_radix4(scope=scope)
    register_soft_mod_radix4(scope=scope)
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
