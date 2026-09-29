# pyright: reportInvalidTypeForm=none
"""Linear power -> decibels: a count-leading-zeros exponent plus a mantissa term.

A pulse detector measures power as a plain linear I^2+Q^2 sum, but every
consumer of a pulse descriptor word wants dB: gr-pdw reports pulse power and
noise power in dBFS (or dBm once a calibration offset is added), and a dB
difference is how you get SNR. This block is that conversion.

    v = 2^e * (1 + m),   0 <= m < 1
    log2(v) = e + log2(1 + m)
    dB      = 10*log10(v) = (10/log2(10)) * log2(v) = 3.0103 * log2(v)

Two implementations of the same interface, chosen by `method=`:

  "rom" (default)  Both terms are table lookups, from two `ram.make_ram` ROMs:
                   `(e - frac_bits) * 3.0103 dB` indexed by the leading-zero
                   count, and `3.0103 * log2(1 + m)` indexed by the top
                   `mant_bits` (10) mantissa bits. Every table entry is rounded
                   from the exact value once, at elaboration time, so there is
                   no multiplier, no shift-add tree and no approximation beyond
                   those two roundings and the mantissa truncation. Worst-case
                   end-to-end error **0.008 dB** (2 LSB of Q8.8), measured over
                   300k random inputs against `10*log10`. Costs one RAMB18 for
                   the mantissa table (shared by every instance with the same
                   `mant_bits`) plus a 2^ceil(log2(W+1))-entry exponent table.

  "pwl"            No ROM. The mantissa term is a chord over 2^seg_bits equal
                   segments -- one small multiply and one add -- and the exponent
                   is scaled by the integer constant 771 (10/log2(10) * 256,
                   rounded) with a shift-add tree. Worst case **0.046 dB**,
                   nearly all of it the chords and the 8-bit mantissa (0.0455
                   dB with an exact constant in place of 771). Use it where a
                   ROM is unwanted.

The mantissa table is sampled at each bin's LEFT edge, not its centre, so an
exact power of two -- `1.0`, `2.0`, ... -- converts to exactly `0`, `3.0103`,
... dB rather than half a bin high. The cost is that the truncation error is
one-sided (always low, by at most one bin, 0.0042 dB at mant_bits=10).

THE FRACTIONAL-BITS SUBTRACTION IS NOT OPTIONAL. `in_t` is a fixed_t, so the
integer the hardware holds is `2^frac_bits` times the value it represents.
Taking dB of the raw integer instead both reports the wrong number and
overflows the output: for the PDW project's 46-bit, 12-fraction-bit `power_t`
the raw range reaches 135.5 dB, past Q8.8's +128, while the true represented
range is -36.1 .. +99.4 dB and fits comfortably. Both methods compute
`dB(e - in_t.frac_bits)`, not `dB(e)`.

Output is signed Q8.8 dB (one LSB = 1/256 dB), saturated at the ends. Both
methods have `.latency` 4 and the same ports, so they are interchangeable.
"""

import math

from pypeline import (
    NamedTuple,
    Reg,
    hw_func,
    int16_t,
    make_int_t,
    make_uint_t,
    struct,
    uint1_t,
)

from bits import make_clz, make_shifter_sl
from ram import make_ram

# dB per unit of log2, in the output's Q8.8 units: 10/log2(10) * 256. The "pwl"
# method uses it rounded; the "rom" method folds the exact value into its tables.
Q8_PER_LOG2 = 2560.0 * math.log10(2.0)  # 770.637
DB_PER_LOG2_Q8 = round(Q8_PER_LOG2)  # 771
# Set-bit positions of that constant, for the shift-add in place of a multiply.
K_SHIFTS = [i for i in range(DB_PER_LOG2_Q8.bit_length()) if (DB_PER_LOG2_Q8 >> i) & 1]
N_K_TERMS = len(K_SHIFTS)

LOG2_DB_METHODS = ("rom", "pwl")


def pwl_log2_tables(mant_bits=8, seg_bits=2):
    """Chord endpoints for log2(1+m) over 2^seg_bits segments, in Q8.8 dB.

    Returns `(A, B)` such that, for a mantissa `m` of `mant_bits` bits,
    with `s = m >> low_bits` and `ml = m & (2^low_bits - 1)`:

        correction_q8 = A[s] + ((B[s] * ml) >> low_bits)

    Chords sit slightly below the (concave) true curve, so the error is
    one-sided; at 4 segments it is small enough (0.031 dB over the mantissa
    alone) that correcting for it is not worth a second constant.
    """
    n_seg = 1 << seg_bits
    scale = 256.0 * 10.0 / math.log2(10.0)
    A = []
    B = []
    for s in range(n_seg):
        x0 = s / n_seg
        x1 = (s + 1) / n_seg
        f0 = math.log2(1.0 + x0)
        f1 = math.log2(1.0 + x1)
        A.append(round(scale * f0))
        B.append(round(scale * (f1 - f0)))
    return A, B


def rom_log2_tables(width, frac_bits, mant_bits=10):
    """The "rom" method's two ROM contents, in Q8.8 dB.

    Returns `(LOG_TAB, EXP_TAB)`:

        LOG_TAB[m]  = round(Q8_PER_LOG2 * log2(1 + m / 2^mant_bits))
        EXP_TAB[lz] = round(Q8_PER_LOG2 * ((width - 1 - lz) - frac_bits))

    indexed by the mantissa's top `mant_bits` bits and by the leading-zero
    count of a `width`-bit magnitude. EXP_TAB has 2^ceil(log2(width + 1))
    entries so the count indexes it directly; entries at and past `lz = width`
    (a zero input, which is floored instead) are 0.
    """
    log_tab = [
        round(Q8_PER_LOG2 * math.log2(1.0 + m / float(1 << mant_bits)))
        for m in range(1 << mant_bits)
    ]
    n_exp = 1 << width.bit_length()
    exp_tab = [
        round(Q8_PER_LOG2 * ((width - 1 - lz) - frac_bits)) if lz < width else 0
        for lz in range(n_exp)
    ]
    return log_tab, exp_tab


def make_log2_db(in_t, mant_bits=None, seg_bits=2, method="rom"):
    """Build a linear->dB converter. Returns (log2_db, log2_db_t).

    in_t:      a `fixed_t` (from fixed_point.make_fixed_t). Its `.frac_bits`
               sets the scaling, and a signed `in_t` is clamped at zero -- a
               DC-blocked power estimate legitimately goes negative between
               pulses, and dB of a non-positive number does not exist.
    method:    "rom" (default) or "pwl" -- see the module docstring.
    mant_bits: mantissa bits used. Default 10 for "rom" (a 1024-entry table,
               one RAMB18) and 8 for "pwl".
    seg_bits:  "pwl" only: 2^seg_bits chord segments.

        log2_db(v: in_t, valid_in: uint1_t) -> log2_db_t
        log2_db_t: .db (int16_t, Q8.8 dB), .valid, .floored

    `.floored` marks an input at or below zero, whose `.db` is the floor value
    (the dB of the smallest representable positive quantity) rather than a
    measurement.

    Latency is 4 cycles for both methods, fully pipelined. Read `.latency`
    rather than assuming it.
    """
    if method not in LOG2_DB_METHODS:
        raise ValueError(
            f"make_log2_db: method must be one of {LOG2_DB_METHODS}, got {method!r}"
        )
    if method == "rom":
        return _make_log2_db_rom(in_t, 10 if mant_bits is None else mant_bits)
    return _make_log2_db_pwl(in_t, 8 if mant_bits is None else mant_bits, seg_bits)


def _make_log2_db_rom(in_t, mant_bits):
    """method="rom". Returns (log2_db, log2_db_t)."""
    val_t = in_t.typeof("val")
    W = len(val_t)
    F = in_t.frac_bits
    M = mant_bits
    if M < 1:
        raise ValueError(f"make_log2_db: mant_bits must be >= 1, got {M}")
    if M >= W:
        raise ValueError(
            f"make_log2_db: mant_bits ({M}) must be less than in_t's width ({W})"
        )

    LOG_TAB, EXP_TAB = rom_log2_tables(W, F, M)
    DB_FLOOR = round(-F * Q8_PER_LOG2)  # dB of the smallest representable value
    DB_MAX = 32767
    DB_MIN = -32768

    mag_t = make_uint_t(W)
    shamt_t = make_uint_t(W.bit_length())
    clz_fn = make_clz(mag_t)
    shift_fn = make_shifter_sl(mag_t, amount_t=shamt_t)
    mant_t = make_uint_t(M)

    log_elem_t = make_uint_t(max(max(LOG_TAB), 1).bit_length())
    exp_span = max(max(abs(x) for x in EXP_TAB), abs(DB_FLOOR), 1)
    exp_elem_t = make_int_t(exp_span.bit_length() + 1)
    acc_t = make_int_t(max(exp_span.bit_length() + 3, 18))

    # read_latency=1 is the block RAM's own read register; out_regs=1 its
    # optional output register, so the add below starts from a register rather
    # than a ~2.5 ns block-RAM clock-to-out. That puts the whole ROM stage in
    # the two cycles the "pwl" method spends on its multiply, so both methods
    # have the same latency.
    log_rom, _log_rom_t = make_ram(
        log_elem_t, 1 << M, ports=("r",), read_latency=1, out_regs=1, init=LOG_TAB
    )
    exp_rom, _exp_rom_t = make_ram(
        exp_elem_t, len(EXP_TAB), ports=("r",), read_latency=1, out_regs=1, init=EXP_TAB
    )
    if log_rom.latency != exp_rom.latency:
        raise ValueError("make_log2_db: the two ROMs must have equal latency")
    ROM_LAT = log_rom.latency

    @struct
    class log2_db_t(NamedTuple):
        db: int16_t  # Q8.8 dB
        valid: uint1_t
        floored: uint1_t  # input was <= 0; .db is the floor, not a measurement

    @hw_func
    def log2_db(v: in_t, valid_in: uint1_t) -> log2_db_t:
        # Present the registered result first, then compute the next one.
        c_db: Reg[int16_t]
        c_valid: Reg[uint1_t]
        c_floored: Reg[uint1_t]
        o: log2_db_t
        o.db = c_db
        o.valid = c_valid
        o.floored = c_floored

        # ---- stage A: clamp + count-leading-zeros ------------------------
        a_mag: Reg[mag_t]
        a_lz: Reg[shamt_t]
        a_valid: Reg[uint1_t]
        a_floored: Reg[uint1_t]

        raw: val_t = v.val
        nonpos: uint1_t = raw <= 0
        zero_mag: mag_t = 0
        mag_in: mag_t = zero_mag if nonpos else raw[W - 1 : 0]
        lz_in: shamt_t = clz_fn(mag_in)

        # ---- stage B: normalize, then both lookups ------------------------
        # Left-align so the leading 1 sits at bit W-1; the mantissa is the
        # next M bits below it. The leading-zero count indexes the exponent
        # table directly -- (e - F) * 3.0103 dB, rounded per entry.
        norm: mag_t = shift_fn(a_mag, a_lz)
        mant: mant_t = norm[W - 2 : W - 1 - M]
        lr = log_rom(log_rom.p0_in_t(addr=mant, valid=a_valid))
        er = exp_rom(exp_rom.p0_in_t(addr=a_lz, valid=a_valid))

        # The floored flag rides alongside the ROM reads. Read the tail before
        # shifting: it is then the flag of the request the ROMs answer now.
        fl_d: Reg[uint1_t[ROM_LAT]]
        fl_tail: uint1_t = fl_d[ROM_LAT - 1]
        nfl: uint1_t[ROM_LAT]
        nfl[0] = a_floored
        for j in range(ROM_LAT - 1):
            nfl[j + 1] = fl_d[j]

        # ---- stage C: sum and clamp ----------------------------------------
        l_val: acc_t = lr.p0.rd_data
        e_val: acc_t = er.p0.rd_data
        total: acc_t = e_val + l_val
        floor_acc: acc_t = DB_FLOOR
        hi_acc: acc_t = DB_MAX
        lo_acc: acc_t = DB_MIN
        picked: acc_t = floor_acc if fl_tail else total
        clamped: acc_t = picked
        if picked > hi_acc:
            clamped = hi_acc
        elif picked < lo_acc:
            clamped = lo_acc

        # Register updates last, in REVERSE pipeline order (see the "pwl"
        # method's note on why that order is load-bearing).
        c_db = clamped[15:0]
        c_valid = lr.p0.valid
        c_floored = fl_tail
        fl_d = nfl
        a_mag = mag_in
        a_lz = lz_in
        a_valid = valid_in
        a_floored = nonpos
        return o

    log2_db.method = "rom"
    log2_db.in_t = in_t
    log2_db.out_t = log2_db_t
    log2_db.mant_bits = M
    log2_db.log_table = LOG_TAB
    log2_db.exp_table = EXP_TAB
    log2_db.db_floor = DB_FLOOR
    log2_db.frac_bits = F
    log2_db.width = W
    log2_db.log_rom = log_rom
    log2_db.exp_rom = exp_rom
    # stage A + the ROM (read register + output register) + stage C.
    log2_db.latency = 1 + ROM_LAT + 1
    # A stateful block to native simulation, exactly like the "pwl" method: it
    # aligns the ROMs' physical outputs with its own registers, so nothing
    # outside needs aligning around them. See dsp/nco.py's identical note.
    log2_db._sim_clocked_pipeline_boundary = True
    return log2_db, log2_db_t


def _make_log2_db_pwl(in_t, mant_bits, seg_bits):
    """method="pwl": the piecewise-linear converter. Returns (log2_db, log2_db_t).

    in_t: a `fixed_t` (from fixed_point.make_fixed_t). Its `.frac_bits` sets
          the scaling, and a signed `in_t` is clamped at zero -- a DC-blocked
          power estimate legitimately goes negative between pulses, and dB of a
          non-positive number does not exist.

        log2_db(v: in_t, valid_in: uint1_t) -> log2_db_t
        log2_db_t: .db (int16_t, Q8.8 dB), .valid, .floored

    `.floored` marks an input at or below zero, whose `.db` is the floor value
    (the dB of the smallest representable positive quantity) rather than a
    measurement.

    Latency is 4 cycles, fully pipelined. As in dsp/cordic.py, the
    count-leading-zeros and the barrel shift it feeds are separated by a
    register: both are wide combinational structures and chaining them would
    make this block, rather than the datapath, the critical path.
    """
    val_t = in_t.typeof("val")
    W = len(val_t)
    F = in_t.frac_bits
    low_bits = mant_bits - seg_bits
    if low_bits < 1:
        raise ValueError(
            f"make_log2_db: mant_bits ({mant_bits}) must exceed seg_bits ({seg_bits})"
        )
    if mant_bits >= W:
        raise ValueError(
            f"make_log2_db: mant_bits ({mant_bits}) must be less than in_t's "
            f"width ({W})"
        )

    A_TAB, B_TAB = pwl_log2_tables(mant_bits, seg_bits)
    n_seg = 1 << seg_bits

    mag_t = make_uint_t(W)
    shamt_t = make_uint_t(W.bit_length())
    clz_fn = make_clz(mag_t)
    shift_fn = make_shifter_sl(mag_t, amount_t=shamt_t)

    # Widths: exponent-scaled term is (e - F) * 771 with e in 0..W-1, so the
    # accumulator must hold the full range plus the mantissa correction. Work
    # wide and saturate once at the end rather than reasoning per instance.
    acc_t = make_int_t(W.bit_length() + 12 + seg_bits + 2)
    exp_t = make_int_t(W.bit_length() + 2)
    seg_t = make_uint_t(seg_bits)
    low_t = make_uint_t(low_bits)
    mant_t = make_uint_t(mant_bits)
    # Size the piecewise-linear constants to what they actually hold. Left as a
    # wide accumulator type, `b_sel * low` infers a DSP48 and lands on the
    # critical path; at 8-ish x 6 bits it is a handful of LUTs instead.
    pwl_t = make_uint_t(max(max(B_TAB), 1).bit_length())
    off_t = make_int_t(max(max(A_TAB), 1).bit_length() + 2)
    prod_t = make_int_t(len(pwl_t) + low_bits + 1)

    DB_FLOOR = -F * DB_PER_LOG2_Q8  # dB of the smallest representable value
    DB_MAX = 32767
    DB_MIN = -32768

    @struct
    class log2_db_t(NamedTuple):
        db: int16_t  # Q8.8 dB
        valid: uint1_t
        floored: uint1_t  # input was <= 0; .db is the floor, not a measurement

    @hw_func
    def log2_db(v: in_t, valid_in: uint1_t) -> log2_db_t:
        b_db: Reg[int16_t]
        b_valid: Reg[uint1_t]
        b_floored: Reg[uint1_t]

        # Present the registered result first, then compute the next one --
        # this is what makes the output a real register boundary rather than a
        # combinational path straight out of the piecewise-linear table.
        o: log2_db_t
        o.db = b_db
        o.valid = b_valid
        o.floored = b_floored

        # ---- stage A: clamp + count-leading-zeros ------------------------
        a_mag: Reg[mag_t]
        a_lz: Reg[shamt_t]
        a_valid: Reg[uint1_t]
        a_floored: Reg[uint1_t]

        raw: val_t = v.val
        nonpos: uint1_t = raw <= 0
        zero_mag: mag_t = 0
        mag_in: mag_t = zero_mag if nonpos else raw[W - 1 : 0]
        lz_in: shamt_t = clz_fn(mag_in)

        # ---- stage B1: normalize and split the mantissa -------------------
        # Left-align so the leading 1 sits at bit W-1, then the mantissa is the
        # next `mant_bits` bits below it.
        b1_seg: Reg[seg_t]
        b1_low: Reg[low_t]
        b1_eadj: Reg[exp_t]
        b1_valid: Reg[uint1_t]
        b1_floored: Reg[uint1_t]

        norm: mag_t = shift_fn(a_mag, a_lz)
        mant: mant_t = norm[W - 2 : W - 1 - mant_bits]
        seg: seg_t = mant[mant_bits - 1 : mant_bits - seg_bits]
        low: low_t = mant[low_bits - 1 : 0]

        # exponent e = (W-1) - clz
        wm1: exp_t = W - 1
        lz_e: exp_t = a_lz
        e: exp_t = wm1 - lz_e
        fbits: exp_t = F
        e_adj: exp_t = e - fbits

        # ---- stage B2: table lookup, mantissa term, exponent scaling ------
        # Split from B1 because chaining the wide barrel shift into the segment
        # mux, the multiply and the final add measured 12.9 ns on xc7a100t --
        # this block, not the datapath it serves, was the design's critical path.
        b2_escaled: Reg[acc_t]
        b2_frac: Reg[acc_t]
        b2_off: Reg[off_t]
        b2_valid: Reg[uint1_t]
        b2_floored: Reg[uint1_t]

        a_sel: off_t = 0
        b_sel: pwl_t = 0
        for s in range(n_seg):
            if b1_seg == s:
                a_sel = A_TAB[s]
                b_sel = B_TAB[s]

        low_p: prod_t = b1_low
        b_p: prod_t = b_sel
        frac_term: acc_t = (b_p * low_p) >> low_bits
        e_acc: acc_t = b1_eadj

        # `exponent * 771` is a multiply by a COMPILE-TIME constant. Written as
        # one it infers a DSP48 whose ~4 ns propagation, plus the adds and the
        # clamp, missed the budget (91 MHz); written as a SERIAL shift-add over
        # the constant's set bits it missed by more (84 MHz), because four
        # dependent wide adds are worse than one DSP. A balanced TREE over
        # those same terms is the version that fits. (771 = 0b1100000011: four
        # terms, two levels.) The decomposition is derived from the constant
        # rather than written out, so changing the output's fractional bits
        # cannot leave a stale hand-expansion behind.
        e_terms: acc_t[N_K_TERMS]
        for _i in range(N_K_TERMS):
            e_terms[_i] = e_acc << K_SHIFTS[_i]
        _span = 1
        while _span < N_K_TERMS:
            for _i in range(0, N_K_TERMS - _span, 2 * _span):
                e_terms[_i] = e_terms[_i] + e_terms[_i + _span]
            _span = _span * 2
        e_scaled: acc_t = e_terms[0]

        # ---- stage B3: sum and clamp --------------------------------------
        a_acc: acc_t = b2_off
        total: acc_t = b2_escaled + a_acc + b2_frac

        floor_acc: acc_t = DB_FLOOR
        hi_acc: acc_t = DB_MAX
        lo_acc: acc_t = DB_MIN
        picked: acc_t = floor_acc if b2_floored else total
        clamped: acc_t = picked
        if picked > hi_acc:
            clamped = hi_acc
        elif picked < lo_acc:
            clamped = lo_acc

        # Register updates last, and in REVERSE pipeline order: each stage must
        # read its predecessor's value from before that predecessor is updated.
        # Writing `a_valid` first and then `b_valid = a_valid` would hand stage
        # B this cycle's flag while its data is still last cycle's -- the valid
        # would run one cycle ahead of the number it describes, and the block
        # would emit its own reset state as a real measurement.
        b_db = clamped[15:0]
        b_valid = b2_valid
        b_floored = b2_floored
        b2_escaled = e_scaled
        b2_frac = frac_term
        b2_off = a_sel
        b2_valid = b1_valid
        b2_floored = b1_floored
        b1_seg = seg
        b1_low = low
        b1_eadj = e_adj
        b1_valid = a_valid
        b1_floored = a_floored
        a_mag = mag_in
        a_lz = lz_in
        a_valid = valid_in
        a_floored = nonpos
        return o

    log2_db.method = "pwl"
    log2_db.in_t = in_t
    log2_db.out_t = log2_db_t
    log2_db.mant_bits = mant_bits
    log2_db.seg_bits = seg_bits
    log2_db.a_table = A_TAB
    log2_db.b_table = B_TAB
    log2_db.db_floor = DB_FLOOR
    log2_db.frac_bits = F
    log2_db.width = W
    log2_db.latency = 4
    return log2_db, log2_db_t


def golden_log2_db(block, raw):
    """Bit-exact Python model of `make_log2_db` (either method). Returns
    (db_q8, floored)."""
    W = block.width
    F = block.frac_bits
    mant_bits = block.mant_bits

    if raw <= 0:
        db = block.db_floor
    else:
        mag = raw & ((1 << W) - 1)
        lz = W - mag.bit_length()
        norm = (mag << lz) & ((1 << W) - 1)
        mant = (norm >> (W - 1 - mant_bits)) & ((1 << mant_bits) - 1)
        if block.method == "rom":
            db = block.exp_table[lz] + block.log_table[mant]
        else:
            seg_bits = block.seg_bits
            low_bits = mant_bits - seg_bits
            A_TAB, B_TAB = block.a_table, block.b_table
            seg = mant >> low_bits
            low = mant & ((1 << low_bits) - 1)
            e = (W - 1) - lz
            db = (e - F) * DB_PER_LOG2_Q8 + A_TAB[seg] + ((B_TAB[seg] * low) >> low_bits)
    db = max(-32768, min(32767, db))
    return db, raw <= 0
