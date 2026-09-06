# pyright: reportInvalidTypeForm=none
"""Per-pulse measurement: phasor -> frequency, linear power -> dB, TOA -> PRI.

The second half of the fast-path / measurement-path split described in
../README.md. Everything here runs ONCE PER PULSE, on the cycle the hysteresis
SM closes one (`gate_last`), rather than once per sample at 125 MSPS. That is
what makes a CORDIC and two logarithms affordable in a design with ~5% timing
margin: the expensive arithmetic sees a few thousand cycles of idle time
between pulses.

Inputs are the raw accumulations Path A already produced -- see
make_freq_accum and the hysteresis SM's `noise_est` in
../pulse_detect/pulse_detect.py. This block only converts them:

    first_re/first_im  --atan2-->  freq_start   (turns x 2^16)
    last_re /last_im   --atan2-->  freq_stop    (turns x 2^16)
    peak_power         --log-->    peak_power_db  (Q8.8 dBFS)
    noise_est          --log-->    noise_power_db (Q8.8 dBFS)
    toa - prev_toa     -------->   pri            (samples)

FULLY PIPELINED, NO BACKPRESSURE. Both the CORDIC and the log converter accept
a new input every cycle, so this block does too: there is no busy state, no
overrun case, and no "measurement invalid" status to define. The hysteresis SM
can close a pulse as often as every couple of samples and every one of them
gets measured. The cost is a fixed `.latency`, which the storage engine
absorbs by waiting for the measurement before releasing a packet (see
../pdw_engine/pdw_engine.py) -- the packet's own beats are still filling the
data FIFO meanwhile, so the wait is free.

WHY dB HAS NO SNR FIELD. SNR is `peak_power_db - noise_power_db`, and both are
in the emitted record, so the host can subtract. Doing it here would need a
third field whose range (+-135 dB) does not fit the Q8.8 the other two use.
gr-pdw's own file record likewise carries pulse power and noise power as
separate columns rather than an SNR.
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
    make_uint_t,
    struct,
    uint1_t,
    uint32_t,
    uint64_t,
)

from dsp.cordic import golden_cordic_atan2, make_cordic_atan2
from dsp.log2_db import golden_log2_db, make_log2_db


def make_pdw_measure(detect_pulses, cordic_iters=14):
    """Build the per-pulse measurement block. Returns (pdw_measure, pdw_measure_t).

        pdw_measure(freq_acc, noise_est, peak_power, toa, valid_in, count_pri)
            -> pdw_measure_t

    `valid_in` is the gate_last / candidate cycle. `count_pri` should be the
    qualification verdict's accept bit: PRI is measured between ACCEPTED
    pulses, so a rejected glitch does not corrupt the interval reported for the
    next real pulse. (PRI is also the one measurement immune to `toa`'s
    documented DSP-latency bias, since a constant offset cancels in a
    difference.)

    All outputs are co-timed, `.latency` cycles after `valid_in`.
    """
    power_t = detect_pulses.power_t
    noise_t = detect_pulses.noise_t
    acc_t = detect_pulses.freq_acc_t

    cordic, _cordic_t = make_cordic_atan2(acc_t, n_iters=cordic_iters)
    # Two separate converters: peak power is the dc-blocked, moving-averaged
    # `power_t` (12 fractional bits) and the noise floor is the raw
    # `magnitude` output (0 fractional bits). Feeding both through one
    # instance would silently mis-scale one of them by 36 dB.
    log_db, _log_db_t = make_log2_db(power_t)
    log_db_noise, _log_db_noise_t = make_log2_db(noise_t)

    LAT = cordic.latency
    # The logs finish long before the CORDIC; their results are delayed to
    # match so every field of a measurement is presented on one cycle.
    DB_DELAY = LAT - log_db.latency
    if log_db.latency != log_db_noise.latency:
        raise ValueError("make_pdw_measure: the two log converters must match in latency")
    if DB_DELAY < 0:
        raise ValueError(
            f"make_pdw_measure: log2_db latency ({log_db.latency}) exceeds "
            f"cordic latency ({LAT}); the alignment below assumes otherwise"
        )

    @struct
    class pdw_measure_t(NamedTuple):
        freq_start: int16_t  # turns x 2^16; multiply by fs for Hz
        freq_stop: int16_t
        peak_power_db: int16_t  # Q8.8 dBFS
        noise_power_db: int16_t  # Q8.8 dBFS
        pri: uint32_t  # samples since the previous accepted pulse
        valid: uint1_t
        freq_degenerate: uint1_t  # phasor was exactly zero; frequencies are 0
        pri_valid: uint1_t  # 0 on the first accepted pulse after reset

    @hw_func
    def pdw_measure(
        freq_acc: detect_pulses.freq_accum_t,
        noise_est: noise_t,
        peak_power: power_t,
        toa: uint64_t,
        valid_in: uint1_t,
        count_pri: uint1_t,
    ) -> pdw_measure_t:
        # ---- frequency: one atan2 per endpoint, in parallel ---------------
        cs = cordic(freq_acc.first_re, freq_acc.first_im, valid_in)
        ce = cordic(freq_acc.last_re, freq_acc.last_im, valid_in)

        # ---- power and noise in dB ----------------------------------------
        lp = log_db(peak_power, valid_in)
        ln = log_db_noise(noise_est, valid_in)

        # ---- PRI ----------------------------------------------------------
        prev_toa: Reg[uint64_t]
        have_prev: Reg[uint1_t]
        take: uint1_t = valid_in & count_pri
        delta: uint64_t = toa - prev_toa
        zero32: uint32_t = 0
        pri_now: uint32_t = delta[31:0] if have_prev else zero32
        pri_ok: uint1_t = have_prev
        if take:
            prev_toa = toa
            have_prev = 1

        # ---- align the short paths to the CORDIC ---------------------------
        db_p: Reg[int16_t[DB_DELAY + 1]]
        db_n: Reg[int16_t[DB_DELAY + 1]]
        pri_d: Reg[uint32_t[LAT + 1]]
        priv_d: Reg[uint1_t[LAT + 1]]
        ndb_p: int16_t[DB_DELAY + 1]
        ndb_n: int16_t[DB_DELAY + 1]
        npri: uint32_t[LAT + 1]
        npriv: uint1_t[LAT + 1]
        ndb_p[0] = lp.db
        ndb_n[0] = ln.db
        for k in range(DB_DELAY):
            ndb_p[k + 1] = db_p[k]
            ndb_n[k + 1] = db_n[k]
        npri[0] = pri_now
        npriv[0] = pri_ok
        for k in range(LAT):
            npri[k + 1] = pri_d[k]
            npriv[k + 1] = priv_d[k]

        # Advance the delay lines BEFORE reading their tails. The CORDIC
        # presents its result post-update too, so reading these pre-update
        # would put every dB and PRI field one cycle behind the frequency
        # fields of the same pulse -- each measurement would carry the previous
        # pulse's power. The frequencies would still look perfect, which is
        # what makes this worth stating rather than leaving to the reader.
        db_p = ndb_p
        db_n = ndb_n
        pri_d = npri
        priv_d = npriv

        o: pdw_measure_t
        o.freq_start = cs.angle
        o.freq_stop = ce.angle
        o.peak_power_db = db_p[DB_DELAY]
        o.noise_power_db = db_n[DB_DELAY]
        o.pri = pri_d[LAT]
        o.valid = cs.valid
        o.freq_degenerate = cs.degenerate | ce.degenerate
        o.pri_valid = priv_d[LAT]
        return o

    pdw_measure.out_t = pdw_measure_t
    pdw_measure.cordic = cordic
    pdw_measure.log_db = log_db
    pdw_measure.log_db_noise = log_db_noise
    pdw_measure.noise_t = noise_t
    pdw_measure.power_t = power_t
    pdw_measure.acc_t = acc_t
    pdw_measure.latency = LAT
    return pdw_measure, pdw_measure_t


def golden_pdw_measure(meas, first_re, first_im, last_re, last_im, noise_raw,
                       peak_raw, toa, prev_toa, have_prev):
    """Bit-exact Python model of one measurement.

    Returns a dict with the same field names as `pdw_measure_t` (minus
    `valid`). `prev_toa`/`have_prev` are the caller's running PRI state,
    which it must advance itself for accepted pulses only.
    """
    fs_raw, fs_degen = golden_cordic_atan2(meas.cordic, first_re, first_im)
    fe_raw, fe_degen = golden_cordic_atan2(meas.cordic, last_re, last_im)
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
