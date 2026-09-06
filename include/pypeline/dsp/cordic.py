# pyright: reportInvalidTypeForm=none
"""Vectoring-mode CORDIC: atan2(y, x) with no multiplier and no lookup ROM.

This is the missing primitive for measuring a pulse's *frequency*. The
estimator (see examples/pypeline/dsp/pdw/) accumulates a phasor
`sum(z[n] * conj(z[n-1]))` over a pulse in the 125 MSPS datapath -- cheap, four
multipliers -- and then needs the ANGLE of that one accumulated complex number,
once per pulse. That is exactly what this block computes.

Why not reuse examples/pypeline/vga_donut.py's `make_length_cordic`? It is the
same iteration, but it needs two changes rather than one:

  1. It has no angle accumulator -- it computes the magnitude and throws the
     angle away, which is the half we want.
  2. Its quadrant handling (`if x < 0: cx = -x`, y untouched) is a REFLECTION
     across the y-axis. That is correct for a length and wrong for an angle: it
     maps quadrant II onto I and III onto IV, so the recovered angle would be
     `pi - theta`, not `theta`. A true rotation is needed instead (see the
     pre-rotation table below).

Also note `make_length_cordic`'s `(cx>>1)+(cx>>3)-(cx>>6)` tail: that is the
CORDIC gain compensation, `1/K` with `K = prod(sqrt(1+2^-2i)) ~ 1.64676`. The
gain scales the MAGNITUDE rail only -- the angle is exact -- so there is no
gain compensation anywhere in this file.

Angles are in TURNS, not radians. A turn is one full circle, so converting to
Hz is a pure scale by the sample rate with no pi anywhere:

    freq_hz = angle_turns * fs

The output is a signed 16-bit fraction of a circle: the full int16 range
[-32768, 32767] spans [-0.5, +0.5) turns, i.e. one LSB is 1/65536 turn
(1907 Hz at 125 MSPS). Internally the angle rail carries 24 fractional bits.

STRUCTURE: a hand-built pipeline with one register stage per iteration, NOT an
unrolled combinational blob and NOT an AUTOFSM.

  * Combinational would put `n_iters` dependent add/subtracts in one path. Every
    testbench and synthesis top in the PDW project builds with `--comb` (no
    autopipelining), where that becomes the design's critical path outright.
  * AUTOFSM shares by entity, so 14 iterations x 3 rails = 42 same-width adds
    folded onto one unit -- 42 states, and src/tests/pypeline_tests/synth_tests.py
    documents the min-area search as superlinear in folds (it once hung for
    hours; SWEEP_LARGE_SCHEDULE_FOLDS is 64). Spending that on sharing a 26-bit
    adder is a bad trade. AUTOFSM earns its keep sharing multipliers and
    dividers, which is what the qor/ benchmarks share.

One register stage per iteration keeps the critical path at a single add/sub
regardless of build mode, accepts a new input every cycle (so there is no busy
signal and no overrun policy to get wrong), and costs ~1100 LUTs + ~1100 FFs --
under 2% of an xc7a100t.
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

# Fractional bits carried by the internal angle rail, in turns, for the
# default work_bits=26. Derived per instance as `work_bits - 2` -- see
# make_cordic_atan2. At 26 bits that is 2^-24 turn = 7.45 Hz at 125 MSPS, far
# finer than the iteration limit.
ANGLE_FRAC = 24


def atan_turns_table(n_iters, angle_frac):
    """The CORDIC angle table, `atan(2^-i)` expressed in turns.

    Plain Python ints, evaluated at elaboration time. Indexing this list by an
    unrolled loop variable folds each entry to a constant in the generated
    hardware -- the same pattern dsp/fir_common.py:220 already uses for its
    quantized coefficients (`CQ[j]`).
    """
    return [
        round(math.atan(2.0**-i) / (2.0 * math.pi) * (1 << angle_frac))
        for i in range(n_iters)
    ]


def make_cordic_atan2(in_val_t, n_iters=14, work_bits=26):
    """Build a pipelined atan2. Returns (cordic_atan2, cordic_atan2_t).

    in_val_t:  signed integer type of the x/y inputs (e.g. make_int_t(39)).
               x and y are treated as a ratio -- only their angle matters, so
               the block is scale invariant by construction (see normalization
               below).
    n_iters:   CORDIC iterations. Angle error is ~2^-n_iters turns: 14 gives
               7.6 kHz at 125 MSPS, comfortably below the estimator's own noise
               at any realistic SNR. 16 gives ~1.9 kHz.
    work_bits: internal rail width. Must leave room above the normalized
               operand for the K ~ 1.647 gain growth (0.72 bits) -- the
               normalization below reserves 2 bits.

        cordic_atan2(x_in, y_in, valid_in) -> cordic_atan2_t
        cordic_atan2_t: .angle (int16_t, turns x 2^16), .valid, .degenerate

    Latency is `n_iters + 2` cycles, fully pipelined: one result per cycle,
    no handshake. Read it from `.latency` rather than recomputing it.

    NORMALIZATION. Precision, not range, is what forces this. The `y >> i`
    shifts inside the iteration discard `i` low bits, so an operand sitting low
    in a wide accumulator runs out of significant bits before the iterations
    finish. Left-aligning both rails first makes accuracy independent of signal
    strength -- which matters, because a weak pulse's accumulated phasor can be
    20+ dB below a strong one's.

    Note what is NOT done: pre-scaling by a fixed right shift. Arithmetic shift
    right floors, so each truncated term biases both rails by -0.5 LSB; over N
    accumulated terms that rotates the phasor by a signal-independent constant
    (order 10 kHz at 125 MSPS). Normalize after accumulating, never before.

    The setup is spread over two registers -- magnitude, then
    count-leading-zeros, then (combinationally) the barrel shift. Each of those
    three is a wide structure on its own; measured on xc7a100t, running all
    three in one stage costs 12.9 ns against an 8 ns budget and makes this
    block, rather than the datapath it serves, the design's critical path.
    """
    if n_iters < 1:
        raise ValueError(f"make_cordic_atan2: n_iters must be >= 1, got {n_iters}")

    W = len(in_val_t)
    # Reserve 2 bits above the normalized MSB: 1 for sign, 1 for the CORDIC's
    # K ~ 1.647 magnitude growth (0.72 bits).
    TRUNC_SH = W - work_bits + 2
    if TRUNC_SH < 0:
        raise ValueError(
            f"make_cordic_atan2: work_bits ({work_bits}) must be at most "
            f"len(in_val_t) + 2 ({W + 2})"
        )
    if work_bits <= n_iters + 3:
        raise ValueError(
            f"make_cordic_atan2: work_bits ({work_bits}) too narrow for "
            f"n_iters ({n_iters}) -- the `>> i` shifts would run out of bits"
        )

    # The angle rail shares work_t with x and y, so its scale is set by the
    # rail width, NOT by a fixed constant. The pre-rotation leaves x >= 0, so
    # |angle| <= 0.5 turns, but intermediate z can reach 0.25 + sum(atan table)
    # = 0.5274 turns; work_bits - 2 fractional bits keeps that inside a signed
    # work_bits rail with room to spare (0.5274 * 2^(work_bits-2) < 2^(work_bits-1)).
    #
    # Getting this wrong is silent: a fixed 24 here works for the default
    # 26-bit rail and overflows the angle accumulator for any narrower one,
    # producing a plausible-looking but completely wrong angle.
    angle_frac = work_bits - 2
    if angle_frac < 16:
        raise ValueError(
            f"make_cordic_atan2: work_bits ({work_bits}) must be at least 18 -- "
            "the int16 turns output needs 16 angle fraction bits"
        )
    if angle_frac < n_iters + 2:
        raise ValueError(
            f"make_cordic_atan2: work_bits ({work_bits}) gives {angle_frac} angle "
            f"fraction bits, too coarse to represent {n_iters} iterations"
        )

    work_t = make_int_t(work_bits)
    ext_t = make_int_t(W + 1)  # holds -(-2^(W-1)) without overflowing
    mag_t = make_uint_t(W)
    clz_fn = make_clz(mag_t)
    shamt_t = make_uint_t(W.bit_length())
    shift_fn = make_shifter_sl(in_val_t, amount_t=shamt_t)

    ATAN = atan_turns_table(n_iters, angle_frac)
    QUARTER = 1 << (angle_frac - 2)  # 0.25 turns

    @struct
    class cordic_atan2_t(NamedTuple):
        angle: int16_t  # turns x 2^16; full int16 range spans [-0.5, +0.5)
        valid: uint1_t
        degenerate: uint1_t  # x == y == 0: the angle is meaningless, forced 0

    @hw_func
    def cordic_atan2(
        x_in: in_val_t, y_in: in_val_t, valid_in: uint1_t
    ) -> cordic_atan2_t:
        # ---- stage A: magnitude ------------------------------------------
        # Two wide negates and a wide compare. Measured on xc7a100t, chaining
        # these into the count-leading-zeros below and then into the barrel
        # shift is 12.9 ns against an 8 ns budget, so the setup is spread over
        # two registers rather than one.
        a_x: Reg[in_val_t]
        a_y: Reg[in_val_t]
        a_mag: Reg[mag_t]
        a_valid: Reg[uint1_t]
        a_degen: Reg[uint1_t]

        xe: ext_t = x_in
        ye: ext_t = y_in
        nxe: ext_t = -xe
        nye: ext_t = -ye
        axe: ext_t = nxe if xe < 0 else xe
        aye: ext_t = nye if ye < 0 else ye
        maxe: ext_t = axe if axe > aye else aye
        mag: mag_t = maxe[W - 1 : 0]

        # ---- stage B: count-leading-zeros --------------------------------
        b_x: Reg[in_val_t]
        b_y: Reg[in_val_t]
        b_sh: Reg[shamt_t]
        b_valid: Reg[uint1_t]
        b_degen: Reg[uint1_t]

        lz: shamt_t = clz_fn(a_mag)
        # clz returns W for an all-zero input; shifting by W-1 then yields 0,
        # which is the right answer for the rails -- the degenerate flag is
        # what tells the consumer the angle is meaningless.
        one_lz: shamt_t = 1
        zero_lz: shamt_t = 0
        shamt: shamt_t = (lz - one_lz) if lz >= one_lz else zero_lz

        # ---- normalize, truncate, quadrant pre-rotate --------------------
        # Combinational, between the stage A registers and xs[0]. This is the
        # half of the setup that is a barrel shift; the count-leading-zeros
        # half sits on the other side of stage A, which is the split the
        # factory docstring describes.
        xsl: in_val_t = shift_fn(b_x, b_sh)
        ysl: in_val_t = shift_fn(b_y, b_sh)
        xsr: in_val_t = xsl >> TRUNC_SH
        ysr: in_val_t = ysl >> TRUNC_SH
        x0: work_t = xsr[work_bits - 1 : 0]
        y0: work_t = ysr[work_bits - 1 : 0]

        # True rotation into the right half plane (x >= 0), which is where the
        # vectoring iteration converges:
        #     x >= 0        -> ( x,  y), z0 =  0
        #     x < 0, y >= 0 -> ( y, -x), z0 = +0.25 turns
        #     x < 0, y < 0  -> (-y,  x), z0 = -0.25 turns
        nx0: work_t = -x0
        ny0: work_t = -y0
        px: work_t
        py: work_t
        pz: work_t
        if x0 >= 0:
            px = x0
            py = y0
            pz = 0
        elif y0 >= 0:
            px = y0
            py = nx0
            pz = QUARTER
        else:
            px = ny0
            py = x0
            pz = -QUARTER

        # ---- iteration pipeline -----------------------------------------
        xs: Reg[work_t[n_iters + 1]]
        ys: Reg[work_t[n_iters + 1]]
        zs: Reg[work_t[n_iters + 1]]
        vs: Reg[uint1_t[n_iters + 1]]
        ds: Reg[uint1_t[n_iters + 1]]

        # Read the whole register array, build the next value locally, then
        # assign it wholesale -- the moving_avg.py:180-185 shift-register idiom.
        # A direct `xs[i+1] = xs[i]` loop would be wrong: Pypeline's blocking
        # assignment means iteration i+1 would read the value iteration i just
        # wrote, collapsing the pipeline into a single cycle.
        nxs: work_t[n_iters + 1]
        nys: work_t[n_iters + 1]
        nzs: work_t[n_iters + 1]
        nvs: uint1_t[n_iters + 1]
        nds: uint1_t[n_iters + 1]
        nxs[0] = px
        nys[0] = py
        nzs[0] = pz
        nvs[0] = b_valid
        nds[0] = b_degen
        for i in range(n_iters):
            cx: work_t = xs[i]
            cy: work_t = ys[i]
            cz: work_t = zs[i]
            dx: work_t = cy >> i  # arithmetic: work_t is signed
            dy: work_t = cx >> i
            atan_i: work_t = ATAN[i]  # folds to a constant, see fir_common.py:220
            if cy >= 0:
                # y positive -> rotate clockwise, angle accumulates positive
                nxs[i + 1] = cx + dx
                nys[i + 1] = cy - dy
                nzs[i + 1] = cz + atan_i
            else:
                nxs[i + 1] = cx - dx
                nys[i + 1] = cy + dy
                nzs[i + 1] = cz - atan_i
            nvs[i + 1] = vs[i]
            nds[i + 1] = ds[i]
        xs = nxs
        ys = nys
        zs = nzs
        vs = nvs
        ds = nds

        # Reverse pipeline order: each stage must read its predecessor from
        # before that predecessor is updated.
        b_x = a_x
        b_y = a_y
        b_sh = shamt
        b_valid = a_valid
        b_degen = a_degen
        a_x = x_in
        a_y = y_in
        a_mag = mag
        a_valid = valid_in
        a_degen = (x_in == 0) & (y_in == 0)

        # ---- output -------------------------------------------------------
        # Q(2^24) turns -> Q(2^16) turns, then keep the low 16 bits.
        # The pre-rotation leaves x >= 0, so the iteration contributes at most
        # +-0.25 turns and |angle| <= 0.5. The boundary is atan2(0, x<0) =
        # +0.5 turns exactly, which is one count past int16's positive range;
        # the iteration converges to it from below, and if truncation pushes a
        # near-boundary result over, the low-16 wrap to -0.5 is the SAME angle.
        # So take the wrap rather than saturating -- saturating would be the
        # wrong answer by a full LSB in one direction only.
        zf: work_t = zs[n_iters]
        zsh: work_t = zf >> (angle_frac - 16)
        o: cordic_atan2_t
        o.angle = zsh[15:0]
        o.valid = vs[n_iters]
        o.degenerate = ds[n_iters]
        if ds[n_iters]:
            o.angle = 0
        return o

    cordic_atan2.in_val_t = in_val_t
    cordic_atan2.out_t = cordic_atan2_t
    cordic_atan2.n_iters = n_iters
    cordic_atan2.work_bits = work_bits
    cordic_atan2.work_t = work_t
    cordic_atan2.angle_frac = angle_frac
    cordic_atan2.atan_table = ATAN
    cordic_atan2.trunc_sh = TRUNC_SH
    # Latency from `valid_in` to the matching `.valid`: two setup stages
    # (magnitude, then count-leading-zeros) plus one per iteration. The barrel
    # shift, truncation and quadrant pre-rotation ride the combinational path
    # out of the second stage into the first iteration register, so they cost
    # no extra cycle.
    cordic_atan2.latency = n_iters + 2
    return cordic_atan2, cordic_atan2_t


def make_cordic_rotate(amp_t, n_iters=16, work_bits=24, phase_bits=32):
    """Rotation-mode CORDIC: a phase-to-sine/cosine NCO with no lookup ROM.

    The mirror image of `make_cordic_atan2` -- same iteration hardware, same
    angle table -- driving the angle rail to zero instead of the y rail, which
    rotates a seed vector by the requested angle. Seeded with `(amplitude, 0)`
    it produces `(amplitude*cos(phase), amplitude*sin(phase))`.

    This is what lets a test stimulus have a CARRIER. There is no RAM or ROM
    primitive in the Pypeline library, so a quarter-wave sine table would have
    to be an unrolled constant mux, and a table coarse enough to be affordable
    would quantize the phase badly enough to bias a frequency measurement.
    The CORDIC has no table at all.

        cordic_rotate(phase, amplitude, valid_in) -> cordic_rotate_t
        cordic_rotate_t: .i, .q (amp_t), .valid

    phase:  unsigned `phase_bits` wide, the full circle -- turns x 2^phase_bits,
            wrapping naturally. Feed it from a free-running accumulator.
    amp_t:  signed output type (e.g. int16_t).

    Latency is `n_iters + 2` cycles, fully pipelined (the quadrant unfold is
    registered). Read it from `.latency`.

    CORDIC GAIN. The iteration scales the vector by K = prod(sqrt(1+2^-2i)) ~
    1.64676, so the seed is pre-divided by K. Rather than a multiplier, that
    uses the shift-add approximation 1/K ~ 1/2 + 1/8 - 1/64 = 0.609375 (the
    same one examples/pypeline/vga_donut.py:227 uses), which is 0.35% high.
    For a stimulus generator that is a deterministic 0.35% amplitude error, not
    a distortion -- the golden model reproduces it exactly, so tests stay
    bit-exact.

    QUADRANT FOLDING. The iteration only converges within +-0.2774 turns, so
    the top two phase bits select a quadrant, the rest is rotated within it,
    and the result is swapped/negated at the end:

        q=0 -> ( c,  s)    q=1 -> (-s,  c)
        q=2 -> (-c, -s)    q=3 -> ( s, -c)
    """
    angle_frac = work_bits - 2
    if angle_frac < n_iters + 2:
        raise ValueError(
            f"make_cordic_rotate: work_bits ({work_bits}) gives {angle_frac} angle "
            f"fraction bits, too coarse for {n_iters} iterations"
        )
    amp_bits = len(amp_t)
    if work_bits < amp_bits + 3:
        raise ValueError(
            f"make_cordic_rotate: work_bits ({work_bits}) needs at least 3 bits "
            f"of headroom over amp_t ({amp_bits}) for the K ~ 1.647 gain growth"
        )
    if phase_bits < angle_frac:
        raise ValueError(
            f"make_cordic_rotate: phase_bits ({phase_bits}) must be at least "
            f"angle_frac ({angle_frac})"
        )

    work_t = make_int_t(work_bits)
    phase_t = make_uint_t(phase_bits)
    quad_t = make_uint_t(2)
    # Within-quadrant phase -> angle rail units. The low phase_bits-2 bits span
    # 0.25 turns, which is 2^(angle_frac-2) in angle units.
    PHASE_SH = (phase_bits - 2) - (angle_frac - 2)
    ATAN = atan_turns_table(n_iters, angle_frac)

    @struct
    class cordic_rotate_t(NamedTuple):
        i: amp_t
        q: amp_t
        valid: uint1_t

    @hw_func
    def cordic_rotate(
        phase: phase_t, amplitude: amp_t, valid_in: uint1_t
    ) -> cordic_rotate_t:
        xs: Reg[work_t[n_iters + 1]]
        ys: Reg[work_t[n_iters + 1]]
        zs: Reg[work_t[n_iters + 1]]
        vs: Reg[uint1_t[n_iters + 1]]
        qs: Reg[quad_t[n_iters + 1]]

        # ---- output: quadrant unfold of the final rotated vector ----------
        # Registered. The unfold is two negates and a 4-way mux, and whatever
        # consumes it generally adds something and saturates -- in the PDW
        # generator that chain measured 8.23 ns against an 8 ns budget, i.e. it
        # was the composed design's last failing path by 0.2 ns.
        o_i_r: Reg[amp_t]
        o_q_r: Reg[amp_t]
        o_v_r: Reg[uint1_t]

        o: cordic_rotate_t
        o.i = o_i_r
        o.q = o_q_r
        o.valid = o_v_r

        fx: work_t = xs[n_iters]
        fy: work_t = ys[n_iters]
        fq: quad_t = qs[n_iters]
        nfx: work_t = -fx
        nfy: work_t = -fy
        oi: work_t = fx
        oq: work_t = fy
        if fq == 1:
            oi = nfy
            oq = fx
        elif fq == 2:
            oi = nfx
            oq = nfy
        elif fq == 3:
            oi = fy
            oq = nfx
        o_i_r = oi[amp_bits - 1 : 0]
        o_q_r = oq[amp_bits - 1 : 0]
        o_v_r = vs[n_iters]

        # ---- seed: gain pre-compensation and quadrant split ---------------
        amp_w: work_t = amplitude
        seed_x: work_t = (amp_w >> 1) + (amp_w >> 3) - (amp_w >> 6)  # ~ amp / K
        quad: quad_t = phase[phase_bits - 1 : phase_bits - 2]
        ph_lo: phase_t = phase & ((1 << (phase_bits - 2)) - 1)
        z0: work_t = ph_lo >> PHASE_SH

        # ---- iteration pipeline (drive z -> 0) ----------------------------
        nxs: work_t[n_iters + 1]
        nys: work_t[n_iters + 1]
        nzs: work_t[n_iters + 1]
        nvs: uint1_t[n_iters + 1]
        nqs: quad_t[n_iters + 1]
        nxs[0] = seed_x
        nys[0] = 0
        nzs[0] = z0
        nvs[0] = valid_in
        nqs[0] = quad
        for k in range(n_iters):
            cx: work_t = xs[k]
            cy: work_t = ys[k]
            cz: work_t = zs[k]
            dx: work_t = cy >> k
            dy: work_t = cx >> k
            atan_k: work_t = ATAN[k]
            if cz >= 0:
                nxs[k + 1] = cx - dx
                nys[k + 1] = cy + dy
                nzs[k + 1] = cz - atan_k
            else:
                nxs[k + 1] = cx + dx
                nys[k + 1] = cy - dy
                nzs[k + 1] = cz + atan_k
            nvs[k + 1] = vs[k]
            nqs[k + 1] = qs[k]
        xs = nxs
        ys = nys
        zs = nzs
        vs = nvs
        qs = nqs
        return o

    cordic_rotate.amp_t = amp_t
    cordic_rotate.out_t = cordic_rotate_t
    cordic_rotate.n_iters = n_iters
    cordic_rotate.work_bits = work_bits
    cordic_rotate.phase_bits = phase_bits
    cordic_rotate.angle_frac = angle_frac
    cordic_rotate.atan_table = ATAN
    cordic_rotate.phase_sh = PHASE_SH
    cordic_rotate.latency = n_iters + 2
    return cordic_rotate, cordic_rotate_t


def golden_cordic_rotate(rot, phase, amplitude):
    """Bit-exact Python model of `make_cordic_rotate`. Returns (i, q)."""
    work_bits = rot.work_bits
    amp_bits = len(rot.amp_t)
    n_iters = rot.n_iters
    phase_bits = rot.phase_bits
    atan = rot.atan_table

    amp_w = amplitude
    seed_x = (amp_w >> 1) + (amp_w >> 3) - (amp_w >> 6)
    quad = (phase >> (phase_bits - 2)) & 3
    ph_lo = phase & ((1 << (phase_bits - 2)) - 1)
    cx, cy, cz = seed_x, 0, ph_lo >> rot.phase_sh
    for k in range(n_iters):
        dx = cy >> k
        dy = cx >> k
        if cz >= 0:
            cx, cy, cz = cx - dx, cy + dy, cz - atan[k]
        else:
            cx, cy, cz = cx + dx, cy - dy, cz + atan[k]
        cx = _sext(cx, work_bits)
        cy = _sext(cy, work_bits)
        cz = _sext(cz, work_bits)
    if quad == 0:
        oi, oq = cx, cy
    elif quad == 1:
        oi, oq = -cy, cx
    elif quad == 2:
        oi, oq = -cx, -cy
    else:
        oi, oq = cy, -cx
    return _sext(oi, amp_bits), _sext(oq, amp_bits)



def _sext(v, bits):
    """Interpret the low `bits` of `v` as a two's-complement signed integer."""
    m = 1 << (bits - 1)
    return (v & ((1 << bits) - 1)) - ((v & m) << 1)


def golden_cordic_atan2(cordic, x, y):
    """Bit-exact Python model of `make_cordic_atan2`'s output.

    Returns `(angle_raw, degenerate)` where `angle_raw` is the int16 the
    hardware emits (turns x 2^16). Mirrors the hardware step for step,
    including the arithmetic-shift floor semantics -- Python's `>>` on a
    negative int floors exactly as a signed hardware shift does, so the two
    agree bit for bit rather than approximately.

    Measured against `math.atan2` over 20k random points spanning magnitudes
    2^4..2^37, the worst error is 3.4e-5 turns (~4.3 kHz at 125 MSPS) and is
    flat across that whole magnitude range -- which is the property the
    normalization exists to provide.
    """
    W = len(cordic.in_val_t)
    work_bits = cordic.work_bits
    n_iters = cordic.n_iters
    af = cordic.angle_frac
    trunc_sh = cordic.trunc_sh
    atan = cordic.atan_table
    quarter = 1 << (af - 2)

    if x == 0 and y == 0:
        return 0, True

    mag = max(abs(x), abs(y))
    lz = W - mag.bit_length()  # make_clz over a W-bit unsigned
    shamt = lz - 1 if lz >= 1 else 0
    xsl = _sext(x << shamt, W)
    ysl = _sext(y << shamt, W)
    x0 = _sext(xsl >> trunc_sh, work_bits)
    y0 = _sext(ysl >> trunc_sh, work_bits)

    if x0 >= 0:
        cx, cy, cz = x0, y0, 0
    elif y0 >= 0:
        cx, cy, cz = y0, -x0, quarter
    else:
        cx, cy, cz = -y0, x0, -quarter

    for i in range(n_iters):
        dx = cy >> i
        dy = cx >> i
        if cy >= 0:
            cx, cy, cz = cx + dx, cy - dy, cz + atan[i]
        else:
            cx, cy, cz = cx - dx, cy + dy, cz - atan[i]

    return _sext((cz >> (af - 16)) & 0xFFFF, 16), False
