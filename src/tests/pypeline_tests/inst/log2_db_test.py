# pyright: reportInvalidTypeForm=none
"""dsp/log2_db.py make_log2_db tests: linear power -> Q8.8 dB.

Both methods -- "rom" (the default: exponent and mantissa tables in make_ram
ROMs) and "pwl" (piecewise-linear chords, no ROM) -- go through every check,
each against its own accuracy budget, and then against each other.

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

# The same two shapes through the ROM-less method.
log2_db_pwl, log2_db_pwl_t = make_log2_db(power_t, method="pwl")
log2_db_pwl_mean, log2_db_pwl_mean_t = make_log2_db(mean_t, method="pwl")

# (block, block on mean_t, worst-case dB error allowed against 10*log10)
METHODS = (
    (log2_db, log2_db_mean, 0.01),
    (log2_db_pwl, log2_db_pwl_mean, 0.10),
)


@MAIN(125.0)
def log2_db_main(v: power_t, valid_in: uint1_t) -> log2_db_t:
    return log2_db(v, valid_in)


@MAIN(125.0)
def log2_db_mean_main(v: mean_t, valid_in: uint1_t) -> log2_db_mean_t:
    return log2_db_mean(v, valid_in)


@MAIN(125.0)
def log2_db_pwl_main(v: power_t, valid_in: uint1_t) -> log2_db_pwl_t:
    return log2_db_pwl(v, valid_in)


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
    for block, _mean_block, _budget in METHODS:
        sim_reset()
        rng = random.Random(24601)
        raws = [1, 2, 3, 4, 4095, 4096, 4097, (1 << 45) - 1]
        raws += [rng.randrange(1, 1 << 45) for _ in range(400)]
        got = _run(block, power_t, raws)
        assert len(got) == len(raws)
        for raw, (db, fl) in zip(raws, got):
            g_db, g_fl = golden_log2_db(block, raw)
            assert db == g_db, f"{block.method}: raw={raw}: hw {db} != model {g_db}"
            assert fl == int(g_fl)
    print("test_matches_golden_model passed")


def test_accuracy_vs_log10():
    """The hardware on 600 inputs, then its bit-exact model on 300k -- the
    number the module docstring quotes for each method."""
    for block, _mean_block, budget in METHODS:
        sim_reset()
        rng = random.Random(777)
        raws = [rng.randrange(1, 1 << 45) for _ in range(600)]
        got = _run(block, power_t, raws)
        worst = 0.0
        for raw, (db, _f) in zip(raws, got):
            worst = max(worst, abs(db / 256.0 - _ref_db(raw, 12)))
        assert worst < budget, f"{block.method}: worst dB error {worst:.4f}"
        model_worst = 0.0
        for _ in range(300000):
            raw = rng.randrange(1, 1 << 45)
            db, _f = golden_log2_db(block, raw)
            model_worst = max(model_worst, abs(db / 256.0 - _ref_db(raw, 12)))
        assert model_worst < budget, f"{block.method}: model worst {model_worst:.4f}"
        print(f"test_accuracy_vs_log10 passed ({block.method}: worst {worst:.4f} dB "
              f"in hardware, {model_worst:.4f} dB over 300k in the model)")


def test_methods_agree():
    """The two methods are independent constructions of the same function, so
    each checks the other: they must agree to within their combined budget."""
    rng = random.Random(4242)
    worst = 0
    for _ in range(50000):
        raw = rng.randrange(1, 1 << 45)
        a, _fa = golden_log2_db(log2_db, raw)
        b, _fb = golden_log2_db(log2_db_pwl, raw)
        worst = max(worst, abs(a - b))
    assert worst / 256.0 < 0.06, f"methods disagree by {worst / 256.0:.4f} dB"
    print(f"test_methods_agree passed (worst {worst / 256.0:.4f} dB apart)")


def test_fractional_bits_are_subtracted():
    """The headline correctness trap: dB must be of the VALUE, not of the raw
    integer. power_t carries 12 fractional bits, so raw == 4096 is 1.0 -> 0 dB.
    Taking dB of the raw integer would report +36.1 dB here, and would overflow
    Q8.8 at the top of the range."""
    for block, _mean_block, _budget in METHODS:
        sim_reset()
        got = _run(block, power_t, [1 << 12])
        assert got[0][0] == 0, f"{block.method}: raw=4096 (value 1.0) should be 0 dB, got {got[0][0]/256.0}"
        # Full-scale must still fit in int16 -- this is what the subtraction buys.
        got = _run(block, power_t, [(1 << 45) - 1])
        db = got[0][0] / 256.0
        assert 95.0 < db < 100.0, f"{block.method}: full scale should be ~99.4 dB, got {db}"
        assert -32768 <= got[0][0] <= 32767
    print(f"test_fractional_bits_are_subtracted passed (full scale {db:.2f} dB)")


def test_decade_and_octave_steps():
    """A factor of 10 is 10 dB and a factor of 2 is 3.0103 dB, within the
    approximation's error budget."""
    for block, _mean_block, budget in METHODS:
        sim_reset()
        base = 1 << 30
        raws = [base, base * 2, base * 4, base * 10, base * 100]
        got = _run(block, power_t, raws)
        d = [g[0] / 256.0 for g in got]
        tol = 2 * budget
        assert abs((d[1] - d[0]) - 3.0103) < tol, f"{block.method}: octave step {d[1]-d[0]}"
        assert abs((d[2] - d[0]) - 6.0206) < tol, f"{block.method}: two octaves {d[2]-d[0]}"
        assert abs((d[3] - d[0]) - 10.0) < tol, f"{block.method}: decade step {d[3]-d[0]}"
        assert abs((d[4] - d[0]) - 20.0) < tol, f"{block.method}: two decades {d[4]-d[0]}"
    print("test_decade_and_octave_steps passed")


def test_nonpositive_is_floored_and_flagged():
    """A DC-blocked power estimate legitimately goes negative between pulses;
    dB of it does not exist, so it must be flagged rather than wrapped."""
    for block, _mean_block, _budget in METHODS:
        sim_reset()
        got = _run(block, power_t, [0, -1, -(1 << 40), 1 << 20])
        for i, (db, fl) in enumerate(got[:3]):
            assert fl == 1, f"{block.method}: input {i} should be flagged floored"
            assert db == block.db_floor, f"{block.method}: expected floor {block.db_floor}, got {db}"
        assert got[3][1] == 0, "positive input must not be flagged"
        assert got[3][0] > 0
    print(f"test_nonpositive_is_floored_and_flagged passed "
          f"(floor {log2_db.db_floor/256.0:.2f} dB)")


def test_different_binary_point_instance():
    """mean_t has 10 fractional bits, not 12. The dB of the same VALUE must
    match across the two instances even though the raw integers differ."""
    for block, mean_block, _budget in METHODS:
        sim_reset()
        got_p = _run(block, power_t, [1 << 12, 1 << 22])          # values 1.0, 1024.0
        got_m = _run(mean_block, mean_t, [1 << 10, 1 << 20])      # values 1.0, 1024.0
        for (dp, _a), (dm, _b) in zip(got_p, got_m):
            assert dp == dm, f"{block.method}: same value, different frac_bits: {dp} vs {dm}"
        assert got_p[0][0] == 0
        assert abs(got_p[1][0] / 256.0 - 30.103) < 0.1
    print("test_different_binary_point_instance passed")


def test_monotonic():
    """dB must be non-decreasing in the input -- a segment-boundary mistake in
    the piecewise-linear table shows up here and almost nowhere else."""
    for block, _mean_block, _budget in METHODS:
        sim_reset()
        raws = [(1 << 20) + k * 977 for k in range(600)]
        got = _run(block, power_t, raws)
        prev = -1 << 30
        for raw, (db, _f) in zip(raws, got):
            assert db >= prev, f"{block.method}: non-monotonic at raw={raw}: {db} < {prev}"
            prev = db
        # Octave boundaries are where the two ROM tables hand over -- every one,
        # in the model, from just below to just above.
        for e in range(1, 45):
            below, _f = golden_log2_db(block, (1 << e) - 1)
            at, _f = golden_log2_db(block, 1 << e)
            assert at >= below, f"{block.method}: non-monotonic across 2^{e}: {at} < {below}"
    print("test_monotonic passed")


def test_pipeline_latency():
    for block, _mean_block, _budget in METHODS:
        sim_reset()
        seen = []
        n = 12
        for c in range(n + block.latency + 4):
            v = 1 if c < n else 0
            r = sim_call(block, power_t(val=(1 << 20) + c), v)
            if int(r.valid):
                seen.append(c)
        assert seen == list(range(block.latency, block.latency + n)), seen
    assert log2_db.latency == log2_db_pwl.latency, "the methods are meant to be interchangeable"
    print("test_pipeline_latency passed")


if __name__ == "__main__":
    test_matches_golden_model()
    test_accuracy_vs_log10()
    test_methods_agree()
    test_fractional_bits_are_subtracted()
    test_decade_and_octave_steps()
    test_nonpositive_is_floored_and_flagged()
    test_different_binary_point_instance()
    test_monotonic()
    test_pipeline_latency()
    print("All log2_db tests passed")
