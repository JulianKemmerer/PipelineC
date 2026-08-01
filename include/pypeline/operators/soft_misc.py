"""Soft unary negate, soft eq/neq (bitwise xor-reduce), and soft MUX."""
from pypeline import hw_func, uint1_t, bit_dup


def make_soft_negate(t):
    """-x == ~x + 1, matching SW_LIB.GET_UNARY_OP_NEGATE_INT_UINT_C_CODE's
    structure exactly (int NEGATE widens by 1 bit and becomes signed -- the
    same typing rule PY_TO_LOGIC._elab_unary already applies to the built-in
    path, at PY_TO_LOGIC.py:4142-4144 -- so the caller must pass the same
    output type here)."""
    from pypeline import make_int_t

    width = len(t)
    out_t = make_int_t(width + 1)

    @hw_func
    def soft_negate(x: t) -> out_t:
        wide: out_t = x
        not_wide: out_t = ~wide
        result: out_t = not_wide + 1
        return result

    return soft_negate


def make_soft_eq(negate=False):
    """Return a factory(l_t, r_t) -> hw_func implementing EQ (or NEQ) via
    bitwise xor-reduce: equal iff every bit of (a ^ b) is 0."""

    def factory(l_t, r_t):
        n_bits = max(len(l_t), len(r_t))
        l_bits = len(l_t)
        r_bits = len(r_t)

        @hw_func
        def soft_eq(a: l_t, b: r_t) -> uint1_t:
            diff_bits: uint1_t = 0
            for i in range(n_bits):
                ai: uint1_t = 0
                bi: uint1_t = 0
                if i < l_bits:
                    ai = a[i]
                if i < r_bits:
                    bi = b[i]
                diff_bits = diff_bits | (ai ^ bi)
            result: uint1_t = 0
            if negate:
                result = diff_bits
            else:
                result = 1 - diff_bits
            return result

        return soft_eq

    return factory


def make_soft_mux(t):
    """MUX(cond, iftrue, iffalse) via bitwise select: broadcast cond to the
    full width with bit_dup, then (mask & iftrue) | (~mask & iffalse) --
    integer types only (register_mux_impl's caller, the VAR_REF_RD binary
    mux tree, only ever looks this up for scalar leaf types)."""
    width = len(t)

    @hw_func
    def soft_mux(cond: uint1_t, iftrue: t, iffalse: t) -> t:
        mask: t = bit_dup(cond, width)
        result: t = (mask & iftrue) | (~mask & iffalse)
        return result

    return soft_mux
