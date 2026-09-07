#!/usr/bin/env python3
"""Unit test for pdw_measure.py: the per-pulse measurement engine.

../pdw_tb.py already checks this block bit-exactly inside the whole pipeline,
but only over the handful of phasor magnitudes and power levels that the real
detector happens to produce. This drives it directly over the full input range
-- phasor magnitudes from 2^10 to 2^36, power and noise across their whole
spans -- which is where a width or normalization mistake would show up.

Run: python3 pdw_measure_test.py
"""

import math
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
for _d in (
    os.path.join(_ROOT, "src"),
    os.path.join(_ROOT, "include", "pypeline"),
    os.path.join(_HERE, "..", "pulse_detect"),
    _HERE,
):
    sys.path.insert(0, _d)

from pypeline import sim_call, sim_reset

from pulse_detect import make_detect_pulses
from pdw_measure import golden_pdw_measure, make_pdw_measure

_DP, _ = make_detect_pulses()
meas, meas_t = make_pdw_measure(_DP)
FA = _DP.freq_accum_t
PT = _DP.power_t
NT = _DP.noise_t


def _drive(stim):
    """Push one stimulus dict per cycle, drain, return the emitted results."""
    sim_reset()
    got = []
    zero = FA(first_re=0, first_im=0, last_re=0, last_im=0, valid=0)
    for c in range(len(stim) + meas.latency + 4):
        if c < len(stim):
            s = stim[c]
            fa = FA(
                first_re=s["fre"], first_im=s["fim"],
                last_re=s["lre"], last_im=s["lim"], valid=1,
            )
            r = sim_call(meas, fa, NT(val=s["noise"]), PT(val=s["peak"]),
                         s["toa"], 1, s["accept"], 0)  # rst
        else:
            r = sim_call(meas, zero, NT(val=0), PT(val=0), 0, 0, 0, 0)  # rst
        if int(r.valid):
            got.append({
                "freq_start": int(r.freq_start), "freq_stop": int(r.freq_stop),
                "peak_power_db": int(r.peak_power_db),
                "noise_power_db": int(r.noise_power_db),
                "pri": int(r.pri), "freq_degenerate": int(r.freq_degenerate),
                "pri_valid": int(r.pri_valid),
            })
    return got


def _golden(stim):
    prev_toa, have_prev = 0, False
    exp = []
    for s in stim:
        exp.append(golden_pdw_measure(
            meas, s["fre"], s["fim"], s["lre"], s["lim"],
            s["noise"], s["peak"], s["toa"], prev_toa, have_prev))
        if s["accept"]:
            prev_toa, have_prev = s["toa"], True
    return exp


def _rand_stim(n, seed):
    rng = random.Random(seed)
    out = []
    toa = 1000
    for _ in range(n):
        m1 = 2 ** rng.randint(10, 36)
        m2 = 2 ** rng.randint(10, 36)
        a1, a2 = rng.uniform(-math.pi, math.pi), rng.uniform(-math.pi, math.pi)
        toa += rng.randrange(50, 5000)
        out.append({
            "fre": int(m1 * math.cos(a1)), "fim": int(m1 * math.sin(a1)),
            "lre": int(m2 * math.cos(a2)), "lim": int(m2 * math.sin(a2)),
            "noise": rng.randrange(1, 1 << 26),
            "peak": rng.randrange(1 << 20, 1 << 44),
            "toa": toa, "accept": rng.randrange(2),
        })
    return out


def test_matches_golden_model():
    stim = _rand_stim(120, 20260905)
    got, exp = _drive(stim), _golden(stim)
    assert len(got) == len(stim), f"{len(got)} results for {len(stim)} inputs"
    for i, (g, e) in enumerate(zip(got, exp)):
        assert g == e, f"measurement {i}:\n  hw={g}\n  model={e}"
    print(f"test_matches_golden_model passed ({len(stim)} measurements)")


def test_known_angles_and_levels():
    """Hand-checkable values, so a model-and-hardware-agree-but-both-wrong
    failure has somewhere to show up."""
    stim = [
        # +45 deg and -45 deg -> +1/8 and -1/8 turn.
        {"fre": 1 << 30, "fim": 1 << 30, "lre": 1 << 30, "lim": -(1 << 30),
         "noise": 1 << 20, "peak": 1 << 40, "toa": 5000, "accept": 1},
        # Exactly on the +y axis -> +1/4 turn; PRI = 5500 - 5000.
        {"fre": 0, "fim": 1 << 30, "lre": 1 << 30, "lim": 0,
         "noise": 1 << 20, "peak": 1 << 40, "toa": 5500, "accept": 1},
    ]
    got = _drive(stim)
    assert abs(got[0]["freq_start"] / 65536.0 - 0.125) < 1e-3, got[0]
    assert abs(got[0]["freq_stop"] / 65536.0 + 0.125) < 1e-3, got[0]
    assert abs(got[1]["freq_start"] / 65536.0 - 0.25) < 1e-3, got[1]
    assert abs(got[1]["freq_stop"] / 65536.0) < 1e-3, got[1]
    # noise_t has 0 fractional bits: 2^20 -> 10*log10(2^20) = 60.2 dB.
    assert abs(got[0]["noise_power_db"] / 256.0 - 60.2) < 0.1, got[0]
    # power_t has 12: 2^40 / 4096 -> 84.3 dB.
    assert abs(got[0]["peak_power_db"] / 256.0 - 84.3) < 0.1, got[0]
    assert got[0]["pri_valid"] == 0 and got[0]["pri"] == 0, got[0]
    assert got[1]["pri_valid"] == 1 and got[1]["pri"] == 500, got[1]
    print("test_known_angles_and_levels passed")


def test_pri_counts_accepted_pulses_only():
    """A rejected pulse must not become the reference for the next PRI."""
    stim = [
        {"fre": 1 << 30, "fim": 0, "lre": 1 << 30, "lim": 0, "noise": 1 << 20,
         "peak": 1 << 40, "toa": t, "accept": a}
        for t, a in ((1000, 1), (1100, 0), (1500, 1))
    ]
    got = _drive(stim)
    assert got[2]["pri"] == 500, (
        f"PRI must be measured from the last ACCEPTED pulse (1500-1000=500), "
        f"got {got[2]['pri']} -- a rejected pulse leaked into the reference"
    )
    print("test_pri_counts_accepted_pulses_only passed")


def test_degenerate_phasor_is_flagged():
    stim = [{"fre": 0, "fim": 0, "lre": 0, "lim": 0, "noise": 1 << 20,
             "peak": 1 << 40, "toa": 9000, "accept": 1}]
    got = _drive(stim)
    assert got[0]["freq_degenerate"] == 1, got[0]
    assert got[0]["freq_start"] == 0 and got[0]["freq_stop"] == 0, got[0]
    print("test_degenerate_phasor_is_flagged passed")


if __name__ == "__main__":
    test_matches_golden_model()
    test_known_angles_and_levels()
    test_pri_counts_accepted_pulses_only()
    test_degenerate_phasor_is_flagged()
    print("All pdw_measure tests passed")
