# pyright: reportInvalidTypeForm=none
"""dsp/log2_db.py make_log2_db tests: linear power -> Q8.8 dB.

`sim_call` checks numeric behaviour against `golden_log2_db` and against
`10*log10`; the `@MAIN` entry points give `pypelinec log2_db_test.py --comb`
elaboration coverage. Plain `python3 log2_db_test.py` runs the sim_call tests.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
import math
import random

from pypeline import MAIN, sim_call, sim_reset, uint1_t

from fixed_point import make_fixed_t
from dsp.log2_db import golden_log2_db, make_log2_db

# The PDW project's power_t: 46 bits, 12 fractional (dc_k=10 + log2(ma_n)=2).
power_t = make_fixed_t(34, 12, signed=True)
log2_db, log2_db_t = make_log2_db(power_t)

# A second shape with a different binary point -- the noise estimate carries 10
# fractional bits, not 12, and getting that scaling wrong is silent.
mean_t = make_fixed_t(33, 10, signed=True)
log2_db_mean, log2_db_mean_t = make_log2_db(mean_t)


@MAIN(125.0)
def log2_db_main(v: power_t, valid_in: uint1_t) -> log2_db_t:
    return log2_db(v, valid_in)


@MAIN(125.0)
def log2_db_mean_main(v: mean_t, valid_in: uint1_t) -> log2_db_mean_t:
    return log2_db_mean(v, valid_in)


def _run(block, in_t, raws):
    out = []
    for c in range(len(raws) + block.latency + 4):
        if c < len(raws):
            v, val = 1, raws[c]
        else:
            v, val = 0, 0
        r = sim_call(block, in_t(val=val), v)
        if int(r.valid):
            out.append((int(r.db), int(r.floored)))
    return out


def _ref_db(raw, frac_bits):
    return 10.0 * math.log10(raw / float(1 << frac_bits))


def test_matches_golden_model():
    sim_reset()
    rng = random.Random(24601)
    raws = [1, 2, 3, 4, 4095, 4096, 4097, (1 << 45) - 1]
    raws += [rng.randrange(1, 1 << 45) for _ in range(400)]
    got = _run(log2_db, power_t, raws)
    assert len(got) == len(raws)
    for raw, (db, fl) in zip(raws, got):
        g_db, g_fl = golden_log2_db(log2_db, raw)
        assert db == g_db, f"raw={raw}: hw {db} != model {g_db}"
        assert fl == int(g_fl)
    print("test_matches_golden_model passed")


def test_accuracy_vs_log10():
    sim_reset()
    rng = random.Random(777)
    raws = [rng.randrange(1, 1 << 45) for _ in range(600)]
    got = _run(log2_db, power_t, raws)
    worst = 0.0
    for raw, (db, _f) in zip(raws, got):
        worst = max(worst, abs(db / 256.0 - _ref_db(raw, 12)))
    assert worst < 0.10, f"worst dB error {worst:.4f}"
    print(f"test_accuracy_vs_log10 passed (worst {worst:.4f} dB)")


def test_fractional_bits_are_subtracted():
    """The headline correctness trap: dB must be of the VALUE, not of the raw
    integer. power_t carries 12 fractional bits, so raw == 4096 is 1.0 -> 0 dB.
    Taking dB of the raw integer would report +36.1 dB here, and would overflow
    Q8.8 at the top of the range."""
    sim_reset()
    got = _run(log2_db, power_t, [1 << 12])
    assert got[0][0] == 0, f"raw=4096 (value 1.0) should be 0 dB, got {got[0][0]/256.0}"
    # Full-scale must still fit in int16 -- this is what the subtraction buys.
    got = _run(log2_db, power_t, [(1 << 45) - 1])
    db = got[0][0] / 256.0
    assert 95.0 < db < 100.0, f"full scale should be ~99.4 dB, got {db}"
    assert -32768 <= got[0][0] <= 32767
    print(f"test_fractional_bits_are_subtracted passed (full scale {db:.2f} dB)")


def test_decade_and_octave_steps():
    """A factor of 10 is 10 dB and a factor of 2 is 3.0103 dB, within the
    approximation's error budget."""
    sim_reset()
    base = 1 << 30
    raws = [base, base * 2, base * 4, base * 10, base * 100]
    got = _run(log2_db, power_t, raws)
    d = [g[0] / 256.0 for g in got]
    assert abs((d[1] - d[0]) - 3.0103) < 0.1, f"octave step {d[1]-d[0]}"
    assert abs((d[2] - d[0]) - 6.0206) < 0.1, f"two octaves {d[2]-d[0]}"
    assert abs((d[3] - d[0]) - 10.0) < 0.1, f"decade step {d[3]-d[0]}"
    assert abs((d[4] - d[0]) - 20.0) < 0.1, f"two decades {d[4]-d[0]}"
    print("test_decade_and_octave_steps passed")


def test_nonpositive_is_floored_and_flagged():
    """A DC-blocked power estimate legitimately goes negative between pulses;
    dB of it does not exist, so it must be flagged rather than wrapped."""
    sim_reset()
    got = _run(log2_db, power_t, [0, -1, -(1 << 40), 1 << 20])
    for i, (db, fl) in enumerate(got[:3]):
        assert fl == 1, f"input {i} should be flagged floored"
        assert db == log2_db.db_floor, f"expected floor {log2_db.db_floor}, got {db}"
    assert got[3][1] == 0, "positive input must not be flagged"
    assert got[3][0] > 0
    print(f"test_nonpositive_is_floored_and_flagged passed "
          f"(floor {log2_db.db_floor/256.0:.2f} dB)")


def test_different_binary_point_instance():
    """mean_t has 10 fractional bits, not 12. The dB of the same VALUE must
    match across the two instances even though the raw integers differ."""
    sim_reset()
    got_p = _run(log2_db, power_t, [1 << 12, 1 << 22])       # values 1.0, 1024.0
    got_m = _run(log2_db_mean, mean_t, [1 << 10, 1 << 20])   # values 1.0, 1024.0
    for (dp, _a), (dm, _b) in zip(got_p, got_m):
        assert dp == dm, f"same value, different frac_bits: {dp} vs {dm}"
    assert got_p[0][0] == 0
    assert abs(got_p[1][0] / 256.0 - 30.103) < 0.1
    print("test_different_binary_point_instance passed")


def test_monotonic():
    """dB must be non-decreasing in the input -- a segment-boundary mistake in
    the piecewise-linear table shows up here and almost nowhere else."""
    sim_reset()
    raws = [(1 << 20) + k * 977 for k in range(600)]
    got = _run(log2_db, power_t, raws)
    prev = -1 << 30
    for raw, (db, _f) in zip(raws, got):
        assert db >= prev, f"non-monotonic at raw={raw}: {db} < {prev}"
        prev = db
    print("test_monotonic passed")


def test_pipeline_latency():
    sim_reset()
    seen = []
    n = 12
    for c in range(n + log2_db.latency + 4):
        v = 1 if c < n else 0
        r = sim_call(log2_db, power_t(val=(1 << 20) + c), v)
        if int(r.valid):
            seen.append(c)
    assert seen == list(range(log2_db.latency, log2_db.latency + n)), seen
    print("test_pipeline_latency passed")


if __name__ == "__main__":
    test_matches_golden_model()
    test_accuracy_vs_log10()
    test_fractional_bits_are_subtracted()
    test_decade_and_octave_steps()
    test_nonpositive_is_floored_and_flagged()
    test_different_binary_point_instance()
    test_monotonic()
    test_pipeline_latency()
    print("All log2_db tests passed")
