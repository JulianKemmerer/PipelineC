"""Soft restoring divider/modulo.

make_soft_div/make_soft_mod are unsigned-only (the restoring-division loop
below only ever produces a non-negative quotient/remainder). Signed division
(make_soft_signed_div/make_soft_signed_mod) wraps the unsigned divider with
the same abs-operands-then-fix-sign structure
SW_LIB.GET_BIN_OP_DIV_INT_N_C_CODE / GET_BIN_OP_MOD_INT_N_C_CODE used to
generate as C: divide magnitudes unsigned, then negate the result if the
operand signs differed (quotient) or, matching that same (already a bit
unusual -- see the C version's own "TODO is the sign fixing here right for
signed modulo?" comment) sign rule, for the remainder too. Kept bit-for-bit
behaviorally identical to the old SW_LIB lowering rather than "fixed" to a
different convention, since nothing depended on this being C-style
truncating modulo and changing it now would be a silent behavior change of
its own.
"""
from pypeline import hw_func, uint1_t, bit_assign, concat, arith_result_type, make_int_t, make_uint_t


def _make_restoring(want_remainder):
    def factory(l_t, r_t):
        eff_l_t, eff_r_t, out_t = arith_result_type("DIV", l_t, r_t)
        n_bits = len(eff_l_t)

        @hw_func
        def soft_div_restoring(a: l_t, b: r_t) -> out_t:
            ae: eff_l_t = a
            be: eff_r_t = b
            rem: eff_l_t = 0
            quot: eff_l_t = 0
            for bit_idx in range(n_bits):
                i = n_bits - 1 - bit_idx
                rem = (rem << 1) | ae[i]
                quot_bit: uint1_t = 0
                if rem >= be:
                    rem = rem - be
                    quot_bit = 1
                quot = bit_assign(quot, quot_bit, i)
            result: out_t = 0
            if want_remainder:
                result = rem
            else:
                result = quot
            return result

        return soft_div_restoring

    return factory


make_soft_div = _make_restoring(want_remainder=False)
make_soft_mod = _make_restoring(want_remainder=True)


def _make_signed(want_remainder):
    def factory(l_t, r_t):
        eff_l_t, eff_r_t, out_t = arith_result_type("DIV", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t))
        signed_t = make_int_t(width)
        unsigned_t = make_uint_t(width)
        unsigned_impl = _make_restoring(want_remainder)(unsigned_t, unsigned_t)

        @hw_func
        def soft_div_signed_restoring(a: l_t, b: r_t) -> out_t:
            ae: signed_t = a
            be: signed_t = b
            l_sign: uint1_t = ae[width - 1]
            r_sign: uint1_t = be[width - 1]
            # Two's-complement negate via bitwise primitives (~x + 1), not
            # the NEGATE operator, so this never depends on what (if
            # anything) is registered for unary "-".
            a_abs: signed_t = ae
            if l_sign:
                a_abs = (~ae) + 1
            b_abs: signed_t = be
            if r_sign:
                b_abs = (~be) + 1
            a_u: unsigned_t = a_abs
            b_u: unsigned_t = b_abs
            u_result: unsigned_t = unsigned_impl(a_u, b_u)
            result: out_t = u_result
            if l_sign ^ r_sign:
                signed_result: signed_t = u_result
                result = (~signed_result) + 1
            return result

        return soft_div_signed_restoring

    return factory


make_soft_signed_div = _make_signed(want_remainder=False)
make_soft_signed_mod = _make_signed(want_remainder=True)


# Op codes for the elaboration-time multiple-build plan below. PY_TO_LOGIC's
# factory-closure canonical-naming pass only accepts ints/bools/None/callables
# /lists-tuples-thereof as closure values -- a plan dict, or string op names
# inside tuples, both raise ElaborationError (confirmed by hitting both while
# building this). So the plan is a plain tuple of (op_code, a, b) int-triples,
# list-index m -> multiple m's build step (index 0 unused padding).
_OP_BASE, _OP_SHL1, _OP_ADD, _OP_SUB = 0, 1, 2, 3


def _build_multiples(top):
    """Elaboration-time only. Returns a tuple indexed 0..top (index 0 unused)
    of (op_code, a, b) build steps for each multiple m in 1..top of the
    divisor, chosen by a min-depth DP: d[2j] = d[j] << 1 is free (a constant
    shift, pure rewiring -- not a chained adder), else d[m] = d[a] +/- d[b]
    minimizing max(depth[a], depth[b]) + 1. Subtraction matters: e.g.
    d[15] = (d[1]<<4) - d[1] is depth 1, where a naive d[m] = d[m-1] + d[1]
    chain is depth 3 -- and that chain sits directly on the critical path,
    ahead of every step's compare."""
    depth = {1: 0}
    plan = {1: (_OP_BASE, 0, 0)}
    for m in range(2, top + 1):
        best = None
        if m % 2 == 0 and (m // 2) in depth:
            cand = (depth[m // 2], (_OP_SHL1, m // 2, 0))
            if best is None or cand[0] < best[0]:
                best = cand
        for a in range(1, m):
            b = m - a
            if a in depth and b in depth:
                d = max(depth[a], depth[b]) + 1
                cand = (d, (_OP_ADD, a, b))
                if best is None or cand[0] < best[0]:
                    best = cand
        for a in range(m + 1, top + 1):
            b = a - m
            if a in depth and b in depth:
                d = max(depth[a], depth[b]) + 1
                cand = (d, (_OP_SUB, a, b))
                if best is None or cand[0] < best[0]:
                    best = cand
        assert best is not None, f"no build plan found for multiple {m}"
        depth[m] = best[0]
        plan[m] = best[1]
    return tuple(plan.get(m, (_OP_BASE, 0, 0)) for m in range(top + 1))


def _make_radix_restoring(bits_per_step, want_remainder):
    """Radix-2**bits_per_step restoring divider: bits_per_step quotient bits
    per step instead of 1, cutting the step count of _make_restoring by that
    factor for a deeper per-step shape (one widened compare-and-subtract per
    step, now against 2**bits_per_step - 1 precomputed multiples of the
    divisor instead of 1).

    bits_per_step=2 (the make_soft_div_radix4/mod default below) measured
    best of an autopipelined-fmax sweep across bits_per_step in {1..6} and
    seven algorithmic variants including non-restoring and a signed-digit/
    carry-save-shaped design (docs: div_fmax_sweep exploration) -- 34.1 MHz
    at 16 pipeline stages under PyRTL estimates on latchup.app's 32-bit
    divider, vs. 22.4-22.9 MHz for every radix-2 shape tried and 25.5 MHz for
    non-restoring. bits_per_step=3 was close behind (33.0 MHz); 1 gave no
    benefit over plain radix-2; 4+ elaborates and sims correctly (see
    div_variants2.py) but wasn't benchmarked here -- PyRTL synthesis of the
    2**4-1=15-way precompute/priority-select didn't finish in 5 minutes, so
    it's reported as unmeasured, not as ranked last.

    This function replaces an earlier bits_per_step=2-only version that had
    two real defects, not just cosmetic ones: `d2 = d1 + d1` (a full adder
    where `d1 << 1` is pure rewiring) and n_bits+8 guard bits (n_bits+
    bits_per_step is provably sufficient). Fixing both was the single
    biggest lever in the sweep -- the old shape measured 26.6 MHz at 16
    stages under the same harness, so the defects cost ~28% fmax on their
    own, independent of any radix choice.

    Unsigned-only, same as _make_restoring -- make_soft_div_signed_radix4/mod
    below wrap this with the same abs-then-fix-sign structure
    make_soft_signed_div/mod use.

    A partial leading step of n_bits % bits_per_step bits runs first when
    n_bits isn't a multiple of bits_per_step, so every remaining step is a
    clean bits_per_step-bit group -- entirely at elaboration time (n_bits and
    bits_per_step are closure constants, so the Python here shapes which HDL
    gets generated, not hardware itself)."""
    k = bits_per_step
    top = (1 << k) - 1
    plan = _build_multiples(top)

    def factory(l_t, r_t):
        eff_l_t, eff_r_t, out_t = arith_result_type("DIV", l_t, r_t)
        n_bits = len(eff_l_t)
        # n_bits+k guard bits are provably sufficient: rem < 2**n_bits after
        # every step's subtract, so rem<<k | bits < 2**(n_bits+k), and
        # (2**k-1)*divisor < 2**(n_bits+k) too (divisor < 2**n_bits).
        wide_t = make_uint_t(n_bits + k)
        kbits_t = make_uint_t(k) if k > 1 else uint1_t

        # Elaboration-time step list: k-bit (hi..lo) groups from the MSB
        # down, with a leading (n_bits % k)-bit group first when it's nonzero.
        steps = []
        idx = n_bits - 1
        if n_bits % k != 0:
            lead = n_bits % k
            steps.append(tuple(range(idx, idx - lead, -1)))
            idx -= lead
        while idx >= k - 1:
            steps.append(tuple(range(idx, idx - k, -1)))
            idx -= k

        @hw_func
        def soft_div_radix(a: l_t, b: r_t) -> out_t:
            ae: eff_l_t = a
            be: eff_r_t = b
            # d[0] unused; d[1..top] the precomputed multiples of the
            # divisor. A real hardware array (not a python list of wires)
            # with elaboration-time-constant indices.
            d: wide_t[top + 1]
            d[1] = be
            for m in range(2, top + 1):
                # plan is a closure constant and m a constant loop index, so
                # this unpack is elaboration-time-free Python bookkeeping.
                op, pa, pb = plan[m]
                if op == _OP_SHL1:
                    d[m] = d[pa] << 1
                elif op == _OP_ADD:
                    d[m] = d[pa] + d[pb]
                elif op == _OP_SUB:
                    d[m] = d[pa] - d[pb]

            rem: eff_l_t = 0
            quot: eff_l_t = 0
            for step_bits in steps:
                sw = len(step_bits)
                if sw == 1:
                    i = step_bits[0]
                    rem_ext: wide_t = concat(rem[n_bits - 2:0], ae[i])
                    rem_new: wide_t = rem_ext
                    qbit: uint1_t = 0
                    if rem_ext >= d[1]:
                        rem_new = rem_ext - d[1]
                        qbit = 1
                    rem = rem_new[n_bits - 1:0]
                    quot = bit_assign(quot, qbit, i)
                else:
                    bits_k: kbits_t = 0
                    for j in range(sw):
                        bit_i = step_bits[j]
                        bits_k = bit_assign(bits_k, ae[bit_i], sw - 1 - j)
                    rem_ext: wide_t = concat(rem[n_bits - 1 - sw:0], bits_k)
                    rem_new: wide_t = rem_ext
                    qk: kbits_t = 0
                    # `break` isn't supported by the elaborator; a `decided`
                    # flag gives the same first-match-from-the-top priority
                    # select without it -- same pattern make_soft_cmp_bitwise
                    # (soft_cmp.py) uses for its MSB-first magnitude scan.
                    decided: uint1_t = 0
                    for m in range(top, 0, -1):
                        ge: uint1_t = 0
                        if rem_ext >= d[m]:
                            ge = 1
                        take: uint1_t = (1 - decided) & ge
                        if take:
                            rem_new = rem_ext - d[m]
                            qk = m
                            decided = 1
                    rem = rem_new[n_bits - 1:0]
                    for j in range(sw):
                        bit_i = step_bits[j]
                        quot = bit_assign(quot, qk[sw - 1 - j], bit_i)

            result: out_t = 0
            if want_remainder:
                result = rem
            else:
                result = quot
            return result

        return soft_div_radix

    return factory


def make_soft_div_radix(bits_per_step):
    """Generalized radix-2**bits_per_step unsigned divider factory. See
    _make_radix_restoring's docstring for the sweep this is based on and its
    measured/unmeasured range. make_soft_div_radix4 below is the
    bits_per_step=2 instance, the one actually measured best."""
    return _make_radix_restoring(bits_per_step, want_remainder=False)


def make_soft_mod_radix(bits_per_step):
    """See make_soft_div_radix -- same radix family, for the remainder."""
    return _make_radix_restoring(bits_per_step, want_remainder=True)


make_soft_div_radix4 = make_soft_div_radix(2)
make_soft_mod_radix4 = make_soft_mod_radix(2)


def _make_signed_radix(bits_per_step, want_remainder):
    def factory(l_t, r_t):
        eff_l_t, eff_r_t, out_t = arith_result_type("DIV", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t))
        signed_t = make_int_t(width)
        unsigned_t = make_uint_t(width)
        unsigned_impl = _make_radix_restoring(bits_per_step, want_remainder)(
            unsigned_t, unsigned_t
        )

        @hw_func
        def soft_div_signed_radix(a: l_t, b: r_t) -> out_t:
            ae: signed_t = a
            be: signed_t = b
            l_sign: uint1_t = ae[width - 1]
            r_sign: uint1_t = be[width - 1]
            a_abs: signed_t = ae
            if l_sign:
                a_abs = (~ae) + 1
            b_abs: signed_t = be
            if r_sign:
                b_abs = (~be) + 1
            a_u: unsigned_t = a_abs
            b_u: unsigned_t = b_abs
            u_result: unsigned_t = unsigned_impl(a_u, b_u)
            result: out_t = u_result
            if l_sign ^ r_sign:
                signed_result: signed_t = u_result
                result = (~signed_result) + 1
            return result

        return soft_div_signed_radix

    return factory


def make_soft_div_signed_radix(bits_per_step):
    return _make_signed_radix(bits_per_step, want_remainder=False)


def make_soft_mod_signed_radix(bits_per_step):
    return _make_signed_radix(bits_per_step, want_remainder=True)


make_soft_div_signed_radix4 = make_soft_div_signed_radix(2)
make_soft_mod_signed_radix4 = make_soft_mod_signed_radix(2)
