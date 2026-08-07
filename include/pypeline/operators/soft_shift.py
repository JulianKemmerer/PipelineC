"""Soft variable-amount barrel shifter and rotator.

Variable-amount << / >> have no built-in inferred path at all -- PY_TO_LOGIC
raises NotImplementedError unless something is registered (register_left_
operator, since the shift amount type is derived from the value width, not
matched exactly). This is a log2(n)-stage barrel-shift structure registered
as a left-operator so it applies to any width automatically.

Each stage lowers to a raw-HDL MUX_<type> leaf entity (the constant shift
beside it, `result << (1<<i)`, is pure rewiring -- CONST_SL/SR built-ins,
zero delay). Every mux in a design shares ONE cached delay regardless of
width or type (src/SYN.py's GET_CACHED_LOGIC_FILE_KEY collapses the key to
the literal string "mux" -- "Mux is same delay no matter type"), and a MUX
entity is exactly one logic level. So a barrel shifter's comb delay, slicing
floor, and useful cut count are all governed by ONE number: how many stages
it has. That is the one lever that matters here -- see the QoR investigation
referenced in docs/SYN_DESIGN.md.

`amount_bits = max(1, (n_bits - 1).bit_length())` -- shift/rotate amounts
0..n_bits-1 need exactly this many bits, one fewer stage than an earlier
version that sized amount_bits off n_bits.bit_length() (n_bits=32 -> 6
stages instead of 5, the 6th only ever able to produce zero). Confirmed by
measurement (PyRTL + Vivado, xc7a200tffg1156-2): the minimal-stage shape
matches or beats every other structural variant tried (masked/AND-OR
select, one-hot decode, per-stage @hw_func composition, reversed stage
order, VAR_REF_RD array-index select) at every cut count, and reaches the
1-mux-delay slicing floor one full clock sooner than the extra-stage shape.
Masking tricks that avoid the MUX entity looked competitive on *comb* delay
alone but priced worse once sliced, because PyRTL's per-op delay model
under-predicts them relative to what real synthesis measures, which throws
off the coarse slicer's even-fraction cut placement -- a reminder that comb
delay alone is not the decision metric (see docs/SYN_DESIGN.md section 8's
"pipelined per-stage delay at n_cuts >= 1, not comb delay" rule, which
applies here too).
"""
from pypeline import hw_func, make_uint_t, rotl as _const_rotl, rotr as _const_rotr, concat


def _amount_bits(n_bits):
    return max(1, (n_bits - 1).bit_length())


def _make_barrel(value_t, left):
    n_bits = len(value_t)
    amount_bits = _amount_bits(n_bits)
    amount_t = make_uint_t(amount_bits)

    @hw_func
    def barrel(v: value_t, amount: amount_t) -> value_t:
        result: value_t = v
        for i in range(amount_bits):
            shift_amt = 1 << i
            if left:
                shifted: value_t = result << shift_amt
            else:
                shifted: value_t = result >> shift_amt
            if amount[i]:
                result = shifted
        return result

    return barrel


def make_soft_barrel_sl(value_t):
    return _make_barrel(value_t, left=True)


def make_soft_barrel_sr(value_t):
    return _make_barrel(value_t, left=False)


def _make_barrel_rot(value_t, left):
    """Variable-amount rotate: same log2(n)-stage barrel, using the
    constant-amount rotl/rotr built-in (also free rewiring -- VHDL `rol`/
    `ror`) as each stage's operation instead of a shift. Rotation is mod
    n_bits, so this needs no oversize guard and no dead stage."""
    n_bits = len(value_t)
    amount_bits = _amount_bits(n_bits)
    amount_t = make_uint_t(amount_bits)
    const_rot = _const_rotl if left else _const_rotr

    @hw_func
    def barrel_rot(v: value_t, amount: amount_t) -> value_t:
        result: value_t = v
        for i in range(amount_bits):
            shift_amt = 1 << i
            shifted: value_t = const_rot(result, shift_amt)
            if amount[i]:
                result = shifted
        return result

    return barrel_rot


def make_soft_barrel_rotl(value_t):
    return _make_barrel_rot(value_t, left=True)


def make_soft_barrel_rotr(value_t):
    return _make_barrel_rot(value_t, left=False)


def make_soft_shift_rot(value_t):
    """Unified 4-mode shift/rotate -- one left-shift-only funnel barrel
    used for both directions, instead of composing separate sl/sr/rotl/rotr
    barrels (the shape of the pasted latchup_rotate C: two barrels plus a
    subtract plus an OR for rotate alone, four barrels total across both
    directions). Roughly half the serial mux depth and a quarter the area
    of that composition, at the cost of one extra port (`direction`) beyond
    a plain rotate call.

        v: value_t          the value to shift/rotate
        amount: amount_t     shift/rotate amount, 0..n_bits-1
        direction: uint1_t    1 = left, 0 = right
        rotate: uint1_t       1 = rotate (wrap), 0 = shift (fill zero)

    Derivation: let hi = rotate ? v : 0. For direction=left, funnel
    w = concat(v, hi) (v in the upper half of a 2n-bit word) and left-shift
    w by `amount`; the upper n bits of the result are exactly
    (v << amount) | (hi >> (n - amount)), i.e. shift when hi=0, rotate when
    hi=v. For direction=right, mirror the concat order (w = concat(hi, v))
    and shift by (n_bits - amount) instead -- right-shift-by-d is exactly
    left-funnel-shift-by-(n-d) taking the same upper half (verified: for
    v=11 (0b1011), n=8, d=1, rotate=1: concat(hi=11,v=11) << 7, taking the
    top byte, gives 133 = 0b10000101, matching (v>>1)|((v&1)<<7)). The
    amount=0 case is handled as an explicit identity override rather than
    letting eff_amt represent n_bits itself, which would need one more bit
    than amount_t otherwise carries.
    """
    from pypeline import uint1_t

    n_bits = len(value_t)
    amount_bits = _amount_bits(n_bits)
    amount_t = make_uint_t(amount_bits)
    wide_t = make_uint_t(2 * n_bits)

    @hw_func
    def shift_rot(v: value_t, amount: amount_t, direction: uint1_t, rotate: uint1_t) -> value_t:
        hi: value_t = 0
        if rotate:
            hi = v
        w: wide_t = 0
        if direction:
            w = concat(v, hi)
        else:
            w = concat(hi, v)
        eff_amt: amount_t = amount
        if not direction:
            if amount != 0:
                eff_amt = n_bits - amount
        for i in range(amount_bits):
            shift_amt = 1 << i
            shifted: wide_t = w << shift_amt
            if eff_amt[i]:
                w = shifted
        out: value_t = w[2 * n_bits - 1:n_bits]
        if amount == 0:
            out = v
        return out

    return shift_rot
