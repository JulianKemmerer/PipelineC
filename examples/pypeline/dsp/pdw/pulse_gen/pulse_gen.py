# pyright: reportInvalidTypeForm=none
"""Pulse Generator for the AIR7310 PDW pipeline (see ../README.md, step 1).

A free-running PRI/width counter gating a complex pulse onto an always-valid
stream(iq_t), with three things a bare amplitude step does not have:

  * a CARRIER, from a phase accumulator driving a rotation-mode CORDIC
    (dsp/cordic.py). `freq` is the phase increment per sample, in turns x 2^32,
    so 0 is DC and 2^31 is Fs/2.
  * an LFM CHIRP, from `chirp_rate` added to that increment on every sample of
    the pulse, so the tone sweeps within the pulse.
  * NOISE, from two Galois LFSRs, scaled by `noise_amp`.

WHY THESE ARE NOT OPTIONAL. The first version emitted `iq_t(amplitude, 0)` --
Q hardwired to zero, a flat DC step. That is a signal at exactly 0 Hz, and it
makes every frequency measurement downstream untestable: an estimator with an
inverted sign, a broken quadrant fix, or one that returns a constant zero all
agree with the correct answer on a 0 Hz input. `chirp_rate` matters for the
same reason one level up -- with a pure tone, start frequency and stop
frequency are bit-identical, so a wrong stop-frequency implementation still
passes. The noise source mirrors the Gaussian source in gr-pdw's own reference
flowgraph, and it is what makes a measured noise floor and SNR mean anything.

All three are deterministic, so golden models stay bit-exact -- `noise_amp`
seeds a fixed LFSR, not a random number generator.

TIMING. The whole output is delayed by `pulse_gen.latency` cycles relative to
the internal PRI counter, because the pulse envelope is applied as the CORDIC's
seed amplitude and therefore rides through its pipeline. That is deliberate:
gating the seed rather than the output keeps the envelope and the carrier
aligned with each other for free. The noise is added after the CORDIC and is
NOT delayed, which is immaterial for noise but does mean a golden model must
pair sample `n` with LFSR step `n`, not `n - latency`.

`pulse_gen` is a plain reusable @hw_func submodule -- no Input[T]/Output[T]
ports of its own. Its arguments are conceptually "as if from ctrl regs"; a
top-level @MAIN is responsible for supplying them.
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "..", "..", "include", "pypeline",
    ),
)

from pypeline import (
    NamedTuple,
    Reg,
    hw_func,
    int16_t,
    int32_t,
    make_int_t,
    struct,
    uint1_t,
    uint16_t,
    uint32_t,
)

from stream.stream import make_stream_t
from dsp.cordic import golden_cordic_rotate, make_cordic_rotate

# Galois LFSR feedback polynomials (maximal length, period 2^32-1) and seeds.
# Two different polynomials rather than two seeds of one polynomial, so the I
# and Q noise streams are structurally independent rather than time shifts of
# each other.
LFSR_POLY_I = 0xA3000000
LFSR_POLY_Q = 0xD0000001
LFSR_SEED_I = 0x1234ABCD
LFSR_SEED_Q = 0x89ABCDEF

NOISE_SHIFT = 8  # noise = (sum of 4 signed bytes) * noise_amp >> NOISE_SHIFT


@struct
class iq_t(NamedTuple):
    i: int16_t
    q: int16_t


def _sat16(v):
    return max(-32768, min(32767, v))


def make_pulse_gen(
    pri_t=uint32_t,
    width_t=uint32_t,
    amplitude_t=int16_t,
    nco_iters=16,
    nco_work_bits=24,
):
    """Build a pulse generator. Returns (pulse_gen, out_stream_t).

        pulse_gen(pri, width, amplitude, freq, chirp_rate, noise_amp)
            -> stream(iq_t)

    pri:        pulse repetition interval, in samples.
    width:      pulse width, in samples.
    amplitude:  peak I/Q amplitude of the carrier.
    freq:       phase increment per sample, turns x 2^32 (signed: negative is a
                negative frequency). 0 gives the old DC-step behaviour.
    chirp_rate: added to the phase increment on each sample of a pulse, so the
                instantaneous frequency ramps linearly (LFM). 0 gives a tone.
    noise_amp:  0 disables noise entirely.
    """
    out_stream_t = make_stream_t(iq_t)
    nco, nco_t = make_cordic_rotate(
        amplitude_t, n_iters=nco_iters, work_bits=nco_work_bits, phase_bits=32
    )
    # 4 signed bytes summed: +-512, so 11 bits signed; times a 16-bit scale.
    byte_t = make_int_t(8)  # reinterpret an LFSR byte as signed
    nsum_t = make_int_t(11)
    nprod_t = make_int_t(11 + 16)
    wide_t = make_int_t(32)

    @hw_func
    def pulse_gen(
        pri: pri_t,
        width: width_t,
        amplitude: amplitude_t,
        freq: int32_t,
        chirp_rate: int32_t,
        noise_amp: uint16_t,
    ) -> out_stream_t:
        pri_counter: Reg[pri_t] = 0
        phase_acc: Reg[uint32_t] = 0
        chirp_acc: Reg[int32_t] = 0
        lfsr_i: Reg[uint32_t] = LFSR_SEED_I
        lfsr_q: Reg[uint32_t] = LFSR_SEED_Q

        pulse_active: uint1_t = pri_counter < width

        # Gate the CORDIC's SEED, not its output: the envelope then travels
        # down the same pipeline as the carrier and cannot drift out of step
        # with it.
        zero_amp: amplitude_t = 0
        amp_now: amplitude_t = amplitude if pulse_active else zero_amp
        n = nco(phase_acc, amp_now, 1)

        # ---- noise: 4 disjoint bytes of each LFSR, read as SIGNED, summed --
        # The intermediate int8_t is load bearing. Slicing a uint32_t yields an
        # unsigned field, so summing the four bytes directly would give a
        # 0..1020 range -- a +510 DC offset on both rails. A DC offset is the
        # one impairment a conjugate-product frequency estimator cannot ignore:
        # it adds a 0 Hz component that drags every measurement toward zero.
        # Reading each byte as int8 makes the noise zero mean instead.
        bi0: byte_t = lfsr_i[7:0]
        bi1: byte_t = lfsr_i[15:8]
        bi2: byte_t = lfsr_i[23:16]
        bi3: byte_t = lfsr_i[31:24]
        bq0: byte_t = lfsr_q[7:0]
        bq1: byte_t = lfsr_q[15:8]
        bq2: byte_t = lfsr_q[23:16]
        bq3: byte_t = lfsr_q[31:24]
        i0: nsum_t = bi0
        i1: nsum_t = bi1
        i2: nsum_t = bi2
        i3: nsum_t = bi3
        q0: nsum_t = bq0
        q1: nsum_t = bq1
        q2: nsum_t = bq2
        q3: nsum_t = bq3
        nsum_i: nsum_t = i0 + i1 + i2 + i3
        nsum_q: nsum_t = q0 + q1 + q2 + q3
        amp_n: nprod_t = noise_amp
        nsum_i_r: Reg[nsum_t]
        nsum_q_r: Reg[nsum_t]
        noise_i_r: Reg[nprod_t]
        noise_q_r: Reg[nprod_t]
        noise_i_next: nprod_t = (nsum_i_r * amp_n) >> NOISE_SHIFT
        noise_q_next: nprod_t = (nsum_q_r * amp_n) >> NOISE_SHIFT

        # ---- sum and saturate to the int16 rails --------------------------
        # The noise path is pipelined and the result registered, which is not
        # cosmetic. This generator's output feeds the detector's magnitude
        # multiplier in the SAME clock domain, so without these registers the
        # path runs from an LFSR flop, through four byte adds, a scaling
        # multiply, the saturating adder and the top-level loopback mux,
        # straight into a DSP48's B port: measured 15.3 ns against an 8 ns
        # budget, and it dragged the whole composed design to 63 MHz while each
        # half met timing on its own. It is the one path no per-block synthesis
        # check can see.
        sig_i: wide_t = n.i
        sig_q: wide_t = n.q
        ni_w: wide_t = noise_i_r
        nq_w: wide_t = noise_q_r
        sum_i: wide_t = sig_i + ni_w
        sum_q: wide_t = sig_q + nq_w
        hi: wide_t = 32767
        lo: wide_t = -32768
        sat_i: wide_t = sum_i
        if sum_i > hi:
            sat_i = hi
        elif sum_i < lo:
            sat_i = lo
        sat_q: wide_t = sum_q
        if sum_q > hi:
            sat_q = hi
        elif sum_q < lo:
            sat_q = lo

        # ---- state advance ------------------------------------------------
        if pri_counter == (pri - 1):
            pri_counter = 0
        else:
            pri_counter = pri_counter + 1

        if pulse_active:
            # Read-before-write: this sample used the pre-increment phase, so
            # the first sample of every pulse is at phase 0.
            phase_acc = phase_acc + freq + chirp_acc
            chirp_acc = chirp_acc + chirp_rate
        else:
            phase_acc = 0
            chirp_acc = 0

        fb_i: uint32_t = LFSR_POLY_I
        fb_q: uint32_t = LFSR_POLY_Q
        zero32: uint32_t = 0
        lfsr_i = (lfsr_i >> 1) ^ (fb_i if lfsr_i[0] else zero32)
        lfsr_q = (lfsr_q >> 1) ^ (fb_q if lfsr_q[0] else zero32)

        out_i_r: Reg[int16_t]
        out_q_r: Reg[int16_t]
        sample: iq_t = iq_t(i=out_i_r, q=out_q_r)

        # Register updates in reverse pipeline order.
        out_i_r = sat_i[15:0]
        out_q_r = sat_q[15:0]
        noise_i_r = noise_i_next
        noise_q_r = noise_q_next
        nsum_i_r = nsum_i
        nsum_q_r = nsum_q
        return out_stream_t(sample, 1)  # always valid: fixed-rate DAC stream

    pulse_gen.iq_t = iq_t
    pulse_gen.out_stream_t = out_stream_t
    pulse_gen.nco = nco
    pulse_gen.latency = nco.latency + 1
    pulse_gen.lfsr_seeds = (LFSR_SEED_I, LFSR_SEED_Q)
    pulse_gen.lfsr_polys = (LFSR_POLY_I, LFSR_POLY_Q)
    pulse_gen.noise_shift = NOISE_SHIFT
    # LFSR steps between a noise sample being generated and reaching the
    # output: two register stages (byte sum, then scaling) plus the output
    # register.
    pulse_gen.noise_pipe = 3
    return pulse_gen, out_stream_t


def golden_pulse_gen(gen, n_samples, _pri, _width, _amplitude, _freq=0,
                     _chirp_rate=0, _noise_amp=0):
    """Bit-exact Python model of `make_pulse_gen`'s output stream.

    Returns a list of `(i, q)` int16 pairs, one per cycle, INCLUDING the
    `gen.latency` cycles of CORDIC fill at the start (during which the carrier
    is zero but the noise is already running -- see the module docstring).

    Every parameter may be either a scalar or a per-cycle sequence. The
    sequence form exists because the generator's state -- the LFSRs, the phase
    accumulator, and the NCO pipeline -- is CONTINUOUS across a run. A
    testbench that sweeps settings cannot model each segment with a separate
    scalar call and concatenate the results; it has to drive one model through
    the whole run exactly as it drives the hardware through it.
    """
    def _at(v, k):
        return v[k] if isinstance(v, (list, tuple)) else v
    nco = gen.nco
    seed_i, seed_q = gen.lfsr_seeds
    poly_i, poly_q = gen.lfsr_polys
    nsh = gen.noise_shift
    mask32 = (1 << 32) - 1

    def s8(v):
        return v - 256 if v >= 128 else v

    def s32(v):
        v &= mask32
        return v - (1 << 32) if v >= (1 << 31) else v

    pri_counter = 0
    phase_acc = 0
    chirp_acc = 0
    li, lq = seed_i, seed_q
    pipe = []  # (phase, amp) awaiting the CORDIC's latency
    # The noise path's own registers: byte sum, then scaled value, then the
    # shared output register. Mirrored exactly rather than approximated -- the
    # whole point of an LFSR source is that the model stays bit-exact.
    nsum_r = (0, 0)
    noise_r = (0, 0)
    out_r = (0, 0)
    out = []
    for _k in range(n_samples):
        pri = _at(_pri, _k)
        width = _at(_width, _k)
        amplitude = _at(_amplitude, _k)
        freq = _at(_freq, _k)
        chirp_rate = _at(_chirp_rate, _k)
        noise_amp = _at(_noise_amp, _k)
        pulse_active = pri_counter < width
        amp_now = amplitude if pulse_active else 0
        pipe.append((phase_acc, amp_now))

        if len(pipe) > nco.latency:
            ph, am = pipe.pop(0)
            ci, cq = golden_cordic_rotate(nco, ph, am)
        else:
            ci, cq = 0, 0

        nsum_i = sum(s8((li >> k) & 0xFF) for k in (0, 8, 16, 24))
        nsum_q = sum(s8((lq >> k) & 0xFF) for k in (0, 8, 16, 24))
        ni, nq = noise_r
        out.append(out_r)
        out_r = (_sat16(ci + ni), _sat16(cq + nq))
        noise_r = ((nsum_r[0] * noise_amp) >> nsh, (nsum_r[1] * noise_amp) >> nsh)
        nsum_r = (nsum_i, nsum_q)

        pri_counter = 0 if pri_counter == (pri - 1) else pri_counter + 1
        if pulse_active:
            phase_acc = (phase_acc + freq + chirp_acc) & mask32
            chirp_acc = s32(chirp_acc + chirp_rate)
        else:
            phase_acc = 0
            chirp_acc = 0
        li = (li >> 1) ^ (poly_i if li & 1 else 0)
        lq = (lq >> 1) ^ (poly_q if lq & 1 else 0)
    return out
