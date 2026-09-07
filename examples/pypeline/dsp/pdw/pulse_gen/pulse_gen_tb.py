# pyright: reportInvalidTypeForm=none
"""Native-sim testbench for the PDW pulse generator (pulse_gen.py).

Three @MAINs, one per feature the generator gained when it stopped being a flat
DC step:

  * `pulse_gen_dc_tb`   -- freq=0: the original envelope/period checks, which
                           still have to hold.
  * `pulse_gen_tone_tb` -- a carrier: constant envelope through the pulse, and
                           a Q rail that is genuinely non-zero.
  * `pulse_gen_noise_tb`-- noise only: bounded, live, and ZERO MEAN.

All checks are structural (`sim_assert` on properties), not sample-by-sample
comparisons -- bit-exactness against `golden_pulse_gen` is checked by
../pdw_tb.py, which drives the real hardware through top.py's ports and has the
Python model available. This file's job is the properties that would still be
wrong if the model and the hardware agreed with each other but both drifted.

Run:
    pypelinec examples/pypeline/dsp/pdw/pulse_gen/pulse_gen_tb.py --sim --comb --run 600
"""

from pypeline import (
    MAIN,
    Reg,
    int16_t,
    int32_t,
    make_int_t,
    sim_assert,
    uint1_t,
    uint32_t,
)

from pulse_gen import make_pulse_gen

TEST_PRI = 50
TEST_WIDTH = 12
TEST_AMPLITUDE = 1000

# Quarter-rate carrier: 2^30 turns x 2^32 = 0.25 turns/sample = Fs/4.
TONE_FREQ = 1 << 30
NOISE_AMP = 400

pulse_gen, out_stream_t = make_pulse_gen()
LAT = pulse_gen.latency

# The CORDIC's 1/K seed compensation is the shift-add 0.609375 rather than the
# exact 0.607253, so the emitted amplitude runs ~0.36% high. Allow 3%.
AMP_LO = (TEST_AMPLITUDE * 97) // 100
AMP_HI = (TEST_AMPLITUDE * 103) // 100
MAG2_LO = AMP_LO * AMP_LO
MAG2_HI = AMP_HI * AMP_HI

acc_t = make_int_t(32)
mag_t = make_int_t(40)


def _expected_active_delayed(phase_reg_name_unused=None):
    """(documentation only -- see the inline delay line in each @MAIN)"""


@MAIN(125.0)
def pulse_gen_dc_tb():
    o = pulse_gen(TEST_PRI, TEST_WIDTH, TEST_AMPLITUDE, 0, 0, 0, 0)

    # Golden reference: an independent free-running PRI counter, DELAYED by the
    # generator's own latency. The envelope is applied as the NCO's seed
    # amplitude, so it comes out the far end of the CORDIC pipeline -- a
    # reference that did not delay would be `LAT` cycles early and every check
    # below would fail on the pulse edges only.
    phase: Reg[uint32_t] = 0
    active_now: uint1_t = phase < TEST_WIDTH
    if phase == (TEST_PRI - 1):
        phase = 0
    else:
        phase = phase + 1

    dly: Reg[uint1_t[LAT + 1]]
    ndly: uint1_t[LAT + 1]
    ndly[0] = active_now
    for k in range(LAT):
        ndly[k + 1] = dly[k]
    dly = ndly
    expected_active: uint1_t = dly[LAT]

    sim_assert(o.valid == 1, "pulse_gen output must always be valid")

    i_val: int16_t = o.data.i
    q_val: int16_t = o.data.q
    neg_i: int16_t = -i_val
    abs_i: int16_t = neg_i if i_val < 0 else i_val
    neg_q: int16_t = -q_val
    abs_q: int16_t = neg_q if q_val < 0 else q_val

    if expected_active:
        sim_assert(
            (abs_i >= AMP_LO) & (abs_i <= AMP_HI),
            f"in-pulse |i| out of range: got {abs_i}, want {AMP_LO}..{AMP_HI}",
        )
        # freq=0 means the phase never advances, so Q stays at the CORDIC's
        # residual -- a couple of LSBs, not a rail.
        sim_assert(abs_q <= 4, f"freq=0 should leave q ~ 0, got {q_val}")
    else:
        sim_assert(abs_i == 0, f"out-of-pulse i must be 0, got {i_val}")
        sim_assert(abs_q == 0, f"out-of-pulse q must be 0, got {q_val}")

    # Period measured off the observed stream, not the golden counter.
    prev_active: Reg[uint1_t] = 0
    cycles_since_edge: Reg[uint32_t] = 0
    saw_first_edge: Reg[uint1_t] = 0
    observed_active: uint1_t = (i_val != 0) | (q_val != 0)
    rising_edge: uint1_t = observed_active & ~prev_active
    if rising_edge:
        # Skip the first edge explicitly. It used to be enough to test
        # `cycles_since_edge != 0`, because with a zero-latency generator the
        # first edge landed on cycle 0 with the counter still at its reset
        # value. The NCO pipeline moved that edge to cycle LAT, so the counter
        # now reads LAT there and the implicit guard silently stopped working.
        if saw_first_edge:
            sim_assert(
                cycles_since_edge == TEST_PRI,
                f"pulse period wrong: expected {TEST_PRI}, measured {cycles_since_edge}",
            )
        saw_first_edge = 1
        cycles_since_edge = 1
    else:
        cycles_since_edge = cycles_since_edge + 1
    sim_assert(
        cycles_since_edge <= (TEST_PRI + LAT + 2),
        f"pulse generator stalled: no rising edge within a PRI period "
        f"(TEST_PRI={TEST_PRI})",
    )
    prev_active = observed_active


@MAIN(125.0)
def pulse_gen_tone_tb():
    """A carrier must have a CONSTANT ENVELOPE and a live Q rail.

    Envelope is the property that catches a broken CORDIC: a wrong quadrant
    fold, a missing gain compensation or a bad seed all show up as a magnitude
    that varies with phase, while the individual I and Q samples still look
    like plausible numbers.
    """
    o = pulse_gen(TEST_PRI, TEST_WIDTH, TEST_AMPLITUDE, TONE_FREQ, 0, 0, 0)

    phase: Reg[uint32_t] = 0
    active_now: uint1_t = phase < TEST_WIDTH
    if phase == (TEST_PRI - 1):
        phase = 0
    else:
        phase = phase + 1
    dly: Reg[uint1_t[LAT + 1]]
    ndly: uint1_t[LAT + 1]
    ndly[0] = active_now
    for k in range(LAT):
        ndly[k + 1] = dly[k]
    dly = ndly
    expected_active: uint1_t = dly[LAT]

    iw: mag_t = o.data.i
    qw: mag_t = o.data.q
    mag2: mag_t = (iw * iw) + (qw * qw)

    if expected_active:
        sim_assert(
            (mag2 >= MAG2_LO) & (mag2 <= MAG2_HI),
            f"tone envelope not constant: i^2+q^2 = {mag2}, want "
            f"{MAG2_LO}..{MAG2_HI}",
        )
    else:
        sim_assert(mag2 == 0, f"out-of-pulse energy must be 0, got {mag2}")

    # At Fs/4 the carrier visits +-amp on each rail in turn, so a Q rail stuck
    # at zero -- the old generator's behaviour -- must fail here.
    saw_big_q: Reg[uint1_t] = 0
    qneg: int16_t = -o.data.q
    absq: int16_t = qneg if o.data.q < 0 else o.data.q
    if absq > AMP_LO:
        saw_big_q = 1
    seen_cycles: Reg[uint32_t] = 0
    seen_cycles = seen_cycles + 1
    if seen_cycles > (LAT + 2 * TEST_PRI):
        sim_assert(
            saw_big_q == 1,
            "carrier never drove the Q rail -- generator is still emitting a "
            "real-only signal",
        )


@MAIN(125.0)
def pulse_gen_noise_tb():
    """Noise must be bounded, actually present, and ZERO MEAN.

    The mean is the load-bearing check. The LFSR bytes are unsigned as sliced;
    summing them without reinterpreting each as int8 gives noise with a large
    positive DC offset, which reads as a signal at 0 Hz and biases every
    frequency measurement downstream toward DC. That bug produces noise that
    looks perfectly reasonable on a scope.
    """
    o = pulse_gen(TEST_PRI, TEST_WIDTH, 0, 0, 0, NOISE_AMP, 0)

    # amplitude=0, so everything here is noise.
    bound: int16_t = (512 * NOISE_AMP) >> 8
    i_val: int16_t = o.data.i
    q_val: int16_t = o.data.q
    ni: int16_t = -i_val
    ai: int16_t = ni if i_val < 0 else i_val
    nq: int16_t = -q_val
    aq: int16_t = nq if q_val < 0 else q_val
    sim_assert(ai <= bound, f"noise |i|={ai} exceeds bound {bound}")
    sim_assert(aq <= bound, f"noise |q|={aq} exceeds bound {bound}")

    sum_i: Reg[acc_t] = 0
    sum_q: Reg[acc_t] = 0
    nonzero: Reg[uint1_t] = 0
    n_cyc: Reg[uint32_t] = 0
    sum_i = sum_i + i_val
    sum_q = sum_q + q_val
    if (i_val != 0) | (q_val != 0):
        nonzero = 1
    n_cyc = n_cyc + 1

    if n_cyc == 500:
        sim_assert(nonzero == 1, "noise source produced nothing in 500 cycles")
        # A zero-mean walk over 500 samples of sigma ~ 230 stays well inside
        # +-20000; a DC-offset bug would accumulate ~500 * 800 = 400,000.
        nsi: acc_t = -sum_i
        asi: acc_t = nsi if sum_i < 0 else sum_i
        nsq: acc_t = -sum_q
        asq: acc_t = nsq if sum_q < 0 else sum_q
        sim_assert(
            asi < 20000,
            f"noise I is not zero mean: sum over 500 cycles = {sum_i} "
            "(LFSR bytes are probably being read unsigned)",
        )
        sim_assert(
            asq < 20000,
            f"noise Q is not zero mean: sum over 500 cycles = {sum_q} "
            "(LFSR bytes are probably being read unsigned)",
        )
