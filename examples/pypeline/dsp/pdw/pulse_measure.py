# pyright: reportInvalidTypeForm=none
"""Per-pulse measurement: phasor -> frequency, linear power -> dB, TOA -> PRI.

The second half of the fast-path / measurement-path split described in
README.md. Everything here runs ONCE PER PULSE, on the cycle the hysteresis
SM closes one (`gate_last`), rather than once per sample at 125 MSPS. This
separates the per-sample arithmetic from the angle and logarithm conversions.
Both angle methods are fully pipelined; idle intervals do not relax their
single-cycle timing requirement.

Inputs are the raw accumulations Path A already produced -- see
make_freq_accum and the hysteresis SM's `noise_est` in
pulse_detect.py. This block only converts them:

    first_re/first_im  --atan2-->  freq_start   (turns x 2^16)
    last_re /last_im   --atan2-->  freq_stop    (turns x 2^16)
    peak_power         --log-->    peak_power_db  (Q8.8 dB re 1 count squared)
    noise_est          --log-->    noise_power_db (Q8.8 dB re 1 count squared)
    toa - prev_toa     -------->   pri            (samples)

FULLY PIPELINED, NO BACKPRESSURE. Both angle methods and the log converter accept
a new input every cycle, so this block does too: there is no busy state. The hysteresis SM
can close a pulse as often as every couple of samples and every one of them
gets measured within the bounded outstanding-work capacity. Queue heads join
the two angles, both logarithms and PRI metadata by completion. The storage
engine waits for the measurement before releasing a packet (see
pulse_extract.py) -- the packet's own beats are still filling the
data FIFO meanwhile, so the wait is free.

WHY dB HAS NO SNR FIELD. SNR is `peak_power_db - noise_power_db`, and both are
in the emitted record, so the host can subtract. Doing it here would need a
third field whose range (+-135 dB) does not fit the Q8.8 the other two use.
gr-pdw's own file record likewise carries pulse power and noise power as
separate columns rather than an SNR.
"""

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

from pypeline import (
    NamedTuple,
    Reg,
    hw_func,
    int16_t,
    make_uint_t,
    struct,
    uint1_t,
    uint32_t,
    uint64_t,
)

from dsp.cordic import golden_cordic_atan2, make_cordic_atan2
from dsp.lut_atan2 import golden_lut_atan2, make_lut_atan2
from dsp.log2_db import golden_log2_db, make_log2_db
from pypeline import param
from stream.valid_join import make_valid_join


def make_pulse_measure(
    pulse_detect, cordic_iters=14, *, atan2_method=None, join_depth=32
):
    """Build the per-pulse measurement block. Returns pulse_measure, with its complete return type at pulse_measure.return_t.

        pulse_measure(freq_acc, noise_est, peak_power, toa, valid_in, count_pri,
                    rst) -> pulse_measure_t

    `valid_in` is the gate_last / candidate cycle. `count_pri` should be the
    qualification verdict's accept bit: PRI is measured between ACCEPTED
    pulses, so a rejected glitch does not corrupt the interval reported for the
    next real pulse. PRI follows the accepted-sample TOA counter; input-valid
    gaps pause that counter. Pipeline transport latency does not need to be
    subtracted from either timestamp before taking their difference.

    `rst` is active high and clears the PRI state. It MUST be driven from the
    same reset that clears pulse_detect's `toa_counter`, since PRI is a
    difference of two TOAs and the two would otherwise straddle a counter
    epoch -- see the reset block for what that produces.

    All outputs describe the same candidate when `.valid` asserts.
    PDW_ATAN2_METHOD=cordic|rom selects the angle implementation (default rom);
    atan2_method overrides it for a factory call. All measurement fields align
    in request order through bounded queues; `join_depth` defaults to 32
    memory words per branch. Overflow reaches the extraction alarm. Reset
    drains all joins and clears PRI history. `get_latency()` is available to
    tests/models under continuous CE, without any eager latency query.
    """
    power_t = pulse_detect.power_t
    noise_t = pulse_detect.noise_t
    acc_t = pulse_detect.freq_acc_t

    if atan2_method is None:
        atan2_method = param(
            "PDW_ATAN2_METHOD",
            "rom",
            choices=("cordic", "rom"),
            env="PDW_ATAN2_METHOD",
        )
    if atan2_method == "cordic":
        angle_unit = make_cordic_atan2(acc_t, n_iters=cordic_iters)
        angle_t = angle_unit.return_t
    elif atan2_method == "rom":
        angle_unit = make_lut_atan2(acc_t, join_depth=join_depth)
        angle_t = angle_unit.return_t
    else:
        raise ValueError("make_pulse_measure: atan2_method must be cordic or rom")
    # Two separate converters: peak power is the dc-blocked, moving-averaged
    # `power_t` (12 fractional bits) and the noise floor is the raw
    # `magnitude` output (0 fractional bits). Feeding both through one
    # instance would silently mis-scale one of them by 36 dB.
    log_db = make_log2_db(power_t, join_depth=join_depth)

    log_db_noise = make_log2_db(noise_t, join_depth=join_depth)

    @struct
    class pri_meta_t(NamedTuple):
        pri: uint32_t
        valid: uint1_t

    join = make_valid_join(
        (angle_t, angle_t, log_db.out_t, log_db_noise.out_t, pri_meta_t), join_depth
    )

    @struct
    class pulse_measure_t(NamedTuple):
        freq_start: int16_t  # turns x 2^16; multiply by fs for Hz
        freq_stop: int16_t
        peak_power_db: int16_t  # Q8.8 dB re 1 count squared
        noise_power_db: int16_t  # Q8.8 dB re 1 count squared
        pri: uint32_t  # samples since the previous accepted pulse
        valid: uint1_t
        freq_degenerate: uint1_t  # phasor was exactly zero; frequencies are 0
        pri_valid: uint1_t  # 0 on the first accepted pulse after reset
        overflow: uint1_t  # sticky alignment-queue overflow; reset required

    @hw_func
    def pulse_measure(
        freq_acc: pulse_detect.freq_accum_t,
        noise_est: noise_t,
        peak_power: power_t,
        toa: uint64_t,
        valid_in: uint1_t,
        count_pri: uint1_t,
        rst: uint1_t,
    ) -> pulse_measure_t:
        # ---- frequency: one atan2 per endpoint, in parallel ---------------
        if atan2_method == "rom":
            cs = angle_unit(
                x_in=freq_acc.first_re,
                y_in=freq_acc.first_im,
                valid_in=valid_in,
                rst=rst,
            )
            ce = angle_unit(
                x_in=freq_acc.last_re,
                y_in=freq_acc.last_im,
                valid_in=valid_in,
                rst=rst,
            )
            angle_overflow: uint1_t = cs.overflow | ce.overflow
        else:
            cs = angle_unit(
                x_in=freq_acc.first_re,
                y_in=freq_acc.first_im,
                valid_in=valid_in & ~rst,
            )
            ce = angle_unit(
                x_in=freq_acc.last_re,
                y_in=freq_acc.last_im,
                valid_in=valid_in & ~rst,
            )
            angle_overflow: uint1_t = 0

        # ---- power and noise in dB ----------------------------------------
        lp = log_db(v=peak_power, valid_in=valid_in, rst=rst)
        ln = log_db_noise(v=noise_est, valid_in=valid_in, rst=rst)

        # ---- PRI ----------------------------------------------------------
        prev_toa: Reg[uint64_t]
        have_prev: Reg[uint1_t]
        take: uint1_t = valid_in & count_pri & ~rst
        delta: uint64_t = toa - prev_toa
        zero32: uint32_t = 0
        pri_now: uint32_t = delta[31:0] if have_prev else zero32
        pri_ok: uint1_t = have_prev
        if take:
            prev_toa = toa
            have_prev = 1

        # Every branch supplies one word per candidate, including rejected
        # candidates. Join the oldest complete transaction without counting
        # cycles or deriving any storage size from a converter's latency.
        j = join(
            cs,
            cs.valid,
            ce,
            ce.valid,
            lp,
            lp.valid,
            ln,
            ln.valid,
            pri_meta_t(pri=pri_now, valid=pri_ok),
            valid_in,
            rst,
        )

        # ---- reset ---------------------------------------------------------
        # NOT optional, and not merely tidy: pulse_detect's `toa_counter` is
        # cleared by the same reset, so a `prev_toa` carried across it would be
        # a TOA from a counter epoch that no longer exists. `delta = toa -
        # prev_toa` on the first pulse after release would then be a huge
        # wrapped value reported as a real PRI. Clearing `have_prev` alongside
        # makes that pulse report pri_valid=0 / STATUS_PRI_INVALID instead --
        # exactly what the first accepted pulse after power-on already does.
        # The join drains in-flight PRI metadata as well. The extraction
        # engine also blocks release and drains descriptors during reset.
        if rst:
            prev_toa = 0
            have_prev = 0

        o: pulse_measure_t
        o.freq_start = j.p0.angle
        o.freq_stop = j.p1.angle
        o.peak_power_db = j.p2.db
        o.noise_power_db = j.p3.db
        o.pri = j.p4.pri
        o.valid = j.valid
        o.freq_degenerate = j.p0.degenerate | j.p1.degenerate
        o.pri_valid = j.p4.valid
        o.overflow = j.overflow | angle_overflow | lp.overflow | ln.overflow
        return o

    pulse_measure.out_t = pulse_measure_t
    pulse_measure.angle_unit = angle_unit
    pulse_measure.atan2_method = atan2_method
    pulse_measure.log_db = log_db
    pulse_measure.log_db_noise = log_db_noise
    pulse_measure.noise_t = noise_t
    pulse_measure.power_t = power_t
    pulse_measure.acc_t = acc_t
    angle_latency = (
        angle_unit.get_latency if atan2_method == "rom" else lambda: angle_unit.latency
    )
    pulse_measure.get_latency = (
        lambda: max(angle_latency(), log_db.get_latency(), log_db_noise.get_latency())
        + 3
    )
    pulse_measure.join_depth = join_depth
    pulse_measure._sim_clocked_pipeline_boundary = True
    return pulse_measure


def golden_pulse_measure(
    meas,
    first_re,
    first_im,
    last_re,
    last_im,
    noise_raw,
    peak_raw,
    toa,
    prev_toa,
    have_prev,
):
    """Bit-exact Python model of one measurement.

    Returns a dict with the same field names as `pulse_measure_t` (minus
    `valid`). `prev_toa`/`have_prev` are the caller's running PRI state,
    which it must advance itself for accepted pulses only.
    """
    angle_model = (
        golden_cordic_atan2 if meas.atan2_method == "cordic" else golden_lut_atan2
    )
    fs_raw, fs_degen = angle_model(meas.angle_unit, first_re, first_im)
    fe_raw, fe_degen = angle_model(meas.angle_unit, last_re, last_im)
    pk_db, _pk_fl = golden_log2_db(meas.log_db, peak_raw)
    ns_db, _ns_fl = golden_log2_db(meas.log_db_noise, noise_raw)
    pri = ((toa - prev_toa) & ((1 << 32) - 1)) if have_prev else 0
    return {
        "freq_start": fs_raw,
        "freq_stop": fe_raw,
        "peak_power_db": pk_db,
        "noise_power_db": ns_db,
        "pri": pri,
        "freq_degenerate": 1 if (fs_degen or fe_degen) else 0,
        "pri_valid": 1 if have_prev else 0,
    }
