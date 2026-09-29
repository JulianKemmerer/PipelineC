# pyright: reportInvalidTypeForm=none
"""Table-lookup NCO: `phase -> amplitude * (cos, sin)` from a quarter-wave sine ROM.

The same interface as `dsp/cordic.py`'s `make_cordic_rotate`, built the other
way: one block-RAM ROM (`ram.make_ram`) read on two ports, and one multiplier
per rail, instead of `n_iters` shift-and-add stages.

    nco, nco_t = make_lut_nco(int16_t, table_bits=10, phase_bits=32)
    o = nco(phase, amplitude, valid_in)      # -> .i, .q, .valid

`phase` is unsigned `phase_bits` wide, turns x 2^phase_bits, wrapping
naturally -- feed it from a free-running accumulator, exactly as for the
CORDIC. `.i`/`.q` are `amplitude*cos(phase)` / `amplitude*sin(phase)`.

WHEN TO USE WHICH. Measured in the PDW example's generator
(examples/pypeline/dsp/pdw/pulse_gen_synth_top.py, xc7a100t, Vivado), where the
NCO is most of the block:

                     make_cordic_rotate (16 iters)   make_lut_nco (10 bits)
    whole generator  2742 LUTs, 1373 FFs, 2 DSP48    520 LUTs, 345 FFs, 4 DSP48,
                                                     one RAMB18
    generator fmax   133.3 MHz                       141.5 MHz
    NCO latency      18 cycles                       5 cycles
    amplitude        0.35% high (shift-add 1/K)      exact
    phase accuracy   ~2^-16 turn                     2^-(table_bits+3) turn

The CORDIC is the better choice only when a ROM is unavailable or an angle
error below ~2^-13 turn matters (raise `table_bits` first: each extra bit
doubles the ROM and buys ~6 dB of spur suppression).

QUARTER-WAVE, SAMPLED AT BIN CENTRES. The table holds
`S[k] = round(2^A * sin(pi/2 * (k + 0.5) / 2^table_bits))` for one quarter
turn, `A` being the amplitude width. Sampling at the centre of each phase bin
rather than its left edge is what makes the mirror a plain bitwise NOT:
`sin` over the second quarter is `S[~k]`, with no `2^N - k` subtraction and no
extra table entry at the end. It also makes the phase truncation round to the
nearest bin centre instead of flooring, so it adds no systematic phase offset.
The top two phase bits pick the quadrant:

    quad   cos            sin
     0     +S[~k]         +S[k]
     1     -S[k]          +S[~k]
     2     -S[~k]         -S[k]
     3     +S[k]          -S[~k]

One ROM serves both rails because the two addresses are read on the ROM's two
ports, and the signs are applied to the AMPLITUDE before the multiply (a 17-bit
negate) rather than to the product.

PHASE TRUNCATION DOES NOT BIAS A FREQUENCY MEASUREMENT. The phase accumulator
feeding this block is exact; only the table index is truncated. The error that
truncation adds to each sample's phase is bounded by half a bin, and a
phasor-difference frequency estimator (the PDW's `freq_accum`) sums phase
DIFFERENCES, which telescope: over a block of M products the accumulated error
is at most one bin, i.e. 2^-(table_bits+2)/M turns of frequency -- below one
LSB of a 16-bit turns output at the defaults. What truncation does produce is
spurs, about 6 dB per index bit below the carrier (~72 dBc at table_bits=10).

Latency is `.latency` = 5, fully pipelined, one result per cycle:
  3  the ROM -- input register, block-RAM read, block-RAM output register
  1  the multiply (one DSP48 per rail: 17-bit signed x 18-bit signed)
  1  round, saturate, output register
"""

import math

from pypeline import (
    NamedTuple,
    Reg,
    hw_func,
    make_int_t,
    make_uint_t,
    struct,
    uint1_t,
)

from ram import make_ram


def sine_quarter_table(table_bits, table_frac):
    """The ROM contents: one quarter turn of sine, sampled at bin centres.

    `round(2^table_frac * sin(pi/2 * (k + 0.5) / 2^table_bits))`. The last
    entry rounds up to exactly `2^table_frac` once the table is fine enough,
    which is why the ROM word is one bit wider than `table_frac`.
    """
    n = 1 << table_bits
    scale = 1 << table_frac
    return [
        int(round(scale * math.sin(0.5 * math.pi * (k + 0.5) / n))) for k in range(n)
    ]


def make_lut_nco(amp_t, table_bits=10, phase_bits=32):
    """Build a ROM-based NCO. Returns (lut_nco, lut_nco_t).

        lut_nco(phase, amplitude, valid_in) -> lut_nco_t
        lut_nco_t: .i, .q (amp_t), .valid

    amp_t:      signed output (and amplitude input) type, e.g. int16_t.
    table_bits: quarter-wave table index width. 2^table_bits entries of
                len(amp_t)+1 bits: the default 10 is 1024 x 17 bits, one RAMB18.
    phase_bits: width of the phase input. Only the top table_bits+2 bits are
                used; the rest is what makes the accumulator's frequency exact.

    `amplitude` may be negative (the output is then inverted). The one value
    whose product does not fit, `amplitude = -2^(A-1)` at the positive peak,
    saturates to `2^(A-1) - 1` instead of wrapping.
    """
    A = len(amp_t)
    N = table_bits
    if N < 2:
        raise ValueError(f"make_lut_nco: table_bits must be >= 2, got {N}")
    if phase_bits < N + 2:
        raise ValueError(
            f"make_lut_nco: phase_bits ({phase_bits}) must be at least "
            f"table_bits + 2 ({N + 2}) -- two bits pick the quadrant"
        )
    TF = A  # table fraction bits: the product's top A bits are the sample
    TABLE = sine_quarter_table(N, TF)

    tab_t = make_uint_t(TF + 1)  # holds 2^TF exactly (see sine_quarter_table)
    # in_regs=1 isolates the quadrant-fold logic from the block RAM's address
    # setup, out_regs=1 is the block RAM's own output register, so the DSP48
    # after it starts from a register rather than a ~2.5 ns clock-to-out.
    rom, _rom_t = make_ram(
        tab_t,
        1 << N,
        ports=("r", "r"),
        read_latency=1,
        in_regs=1,
        out_regs=1,
        init=TABLE,
    )
    ROM_LAT = rom.latency
    phase_t = make_uint_t(phase_bits)
    addr_t = rom.addr_t
    quad_t = make_uint_t(2)
    samp_t = make_int_t(A + 1)  # +-amplitude, including -(-2^(A-1))
    tabs_t = make_int_t(TF + 2)  # the ROM word as a signed multiplier operand
    prod_t = make_int_t(A + TF + 3)
    res_t = make_int_t(A + 2)
    RND = 1 << (TF - 1)
    OUT_HI = (1 << (A - 1)) - 1
    OUT_LO = -(1 << (A - 1))
    INDEX_MASK = (1 << N) - 1

    @struct
    class lut_nco_t(NamedTuple):
        i: amp_t
        q: amp_t
        valid: uint1_t

    @hw_func
    def lut_nco(phase: phase_t, amplitude: amp_t, valid_in: uint1_t) -> lut_nco_t:
        # ---- output stage: round, saturate, register ----------------------
        # Presented first, then computed, so the output is a real register.
        o_i_r: Reg[amp_t]
        o_q_r: Reg[amp_t]
        o_v_r: Reg[uint1_t]
        o: lut_nco_t
        o.i = o_i_r
        o.q = o_q_r
        o.valid = o_v_r

        p_i_r: Reg[prod_t]
        p_q_r: Reg[prod_t]
        p_v_r: Reg[uint1_t]

        rnd: prod_t = RND
        pr_i: prod_t = p_i_r + rnd
        pr_q: prod_t = p_q_r + rnd
        r_i: res_t = pr_i >> TF  # arithmetic: prod_t is signed
        r_q: res_t = pr_q >> TF
        hi: res_t = OUT_HI
        lo: res_t = OUT_LO
        sat_i: res_t = r_i
        if r_i > hi:
            sat_i = hi
        elif r_i < lo:
            sat_i = lo
        sat_q: res_t = r_q
        if r_q > hi:
            sat_q = hi
        elif r_q < lo:
            sat_q = lo

        # ---- quadrant fold and ROM request ---------------------------------
        quad: quad_t = phase[phase_bits - 1 : phase_bits - 2]
        k: addr_t = phase[phase_bits - 3 : phase_bits - 2 - N]
        index_mask: addr_t = INDEX_MASK
        k_mirror: addr_t = k ^ index_mask  # S[~k]: the bin-centre mirror
        odd: uint1_t = quad[0]
        a_cos: addr_t = k if odd else k_mirror
        a_sin: addr_t = k_mirror if odd else k
        neg_cos: uint1_t = quad[1] ^ quad[0]  # quadrants 1 and 2
        neg_sin: uint1_t = quad[1]  # quadrants 2 and 3

        amp_w: samp_t = amplitude
        amp_n: samp_t = -amp_w
        s_cos: samp_t = amp_n if neg_cos else amp_w
        s_sin: samp_t = amp_n if neg_sin else amp_w

        r = rom(
            rom.p0_in_t(addr=a_cos, valid=valid_in),
            rom.p1_in_t(addr=a_sin, valid=valid_in),
        )

        # The signed amplitudes ride alongside the ROM read. Read the tail
        # BEFORE shifting: it then holds the value from exactly ROM_LAT cycles
        # ago, which is the request r.p0/r.p1 are answering this cycle.
        sc_d: Reg[samp_t[ROM_LAT]]
        ss_d: Reg[samp_t[ROM_LAT]]
        sc_tail: samp_t = sc_d[ROM_LAT - 1]
        ss_tail: samp_t = ss_d[ROM_LAT - 1]
        nsc: samp_t[ROM_LAT]
        nss: samp_t[ROM_LAT]
        nsc[0] = s_cos
        nss[0] = s_sin
        for j in range(ROM_LAT - 1):
            nsc[j + 1] = sc_d[j]
            nss[j + 1] = ss_d[j]

        t_cos: tabs_t = r.p0.rd_data
        t_sin: tabs_t = r.p1.rd_data

        # Register updates in reverse pipeline order: each stage reads its
        # predecessor's value from before that predecessor is updated.
        o_i_r = sat_i[A - 1 : 0]
        o_q_r = sat_q[A - 1 : 0]
        o_v_r = p_v_r
        p_i_r = sc_tail * t_cos
        p_q_r = ss_tail * t_sin
        p_v_r = r.p0.valid
        sc_d = nsc
        ss_d = nss
        return o

    lut_nco.amp_t = amp_t
    lut_nco.out_t = lut_nco_t
    lut_nco.table_bits = N
    lut_nco.table_frac = TF
    lut_nco.phase_bits = phase_bits
    lut_nco.table = TABLE
    lut_nco.rom = rom
    # ROM (input register, block-RAM read, output register) + multiply +
    # output register. Read this rather than recomputing it.
    lut_nco.latency = ROM_LAT + 2
    # To native simulation this is a STATEFUL block, like make_cordic_rotate: it
    # takes the ROM's physical outputs and aligns them with its own registers,
    # so there is nothing outside it to align around the ROM. Saying so stops a
    # standalone sim_call from running the pure-caller alignment pass over it,
    # which it does not need -- and which currently fails on it (handoff
    # sim_call_pipeline_latency_compare_handoff.md). Same attribute, same
    # reason, as stream/stream_ram.py's handshake controller.
    lut_nco._sim_clocked_pipeline_boundary = True
    return lut_nco, lut_nco_t


def golden_lut_nco(nco, phase, amplitude):
    """Bit-exact Python model of `make_lut_nco`. Returns (i, q)."""
    N = nco.table_bits
    TF = nco.table_frac
    pb = nco.phase_bits
    A = len(nco.amp_t)
    table = nco.table
    mask = (1 << N) - 1

    quad = (phase >> (pb - 2)) & 3
    k = (phase >> (pb - 2 - N)) & mask
    k_mirror = k ^ mask
    odd = quad & 1
    a_cos = k if odd else k_mirror
    a_sin = k_mirror if odd else k
    neg_cos = ((quad >> 1) ^ quad) & 1
    neg_sin = (quad >> 1) & 1
    s_cos = -amplitude if neg_cos else amplitude
    s_sin = -amplitude if neg_sin else amplitude

    hi = (1 << (A - 1)) - 1
    lo = -(1 << (A - 1))

    def _out(s, t):
        return max(lo, min(hi, (s * t + (1 << (TF - 1))) >> TF))

    return _out(s_cos, table[a_cos]), _out(s_sin, table[a_sin])
