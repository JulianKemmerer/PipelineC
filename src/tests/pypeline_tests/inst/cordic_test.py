# pyright: reportInvalidTypeForm=none
"""dsp/cordic.py make_cordic_atan2 tests.

Two layers, because they cover different things (see the native-sim scope note
in the Pypeline docs): `sim_call` below exercises the Layer 1 simulator and
checks numeric behaviour against `golden_cordic_atan2` and against
`math.atan2`; the `@MAIN` entry points give `pypelinec cordic_test.py --comb`
Layer 2 elaboration coverage, which is the only thing that produces VHDL and
therefore the only thing that can catch a synthesis-only mistake.

Plain `python3 cordic_test.py` runs the sim_call tests.
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

from pypeline import MAIN, make_int_t, sim_call, sim_reset, uint1_t

from dsp.cordic import golden_cordic_atan2, make_cordic_atan2

acc_t = make_int_t(39)  # the PDW phasor accumulator width
cordic, cordic_t = make_cordic_atan2(acc_t)

narrow_t = make_int_t(20)
cordic_narrow, cordic_narrow_t = make_cordic_atan2(narrow_t, n_iters=10, work_bits=20)


@MAIN(125.0)
def cordic_main(x_in: acc_t, y_in: acc_t, valid_in: uint1_t) -> cordic_t:
    return cordic(x_in, y_in, valid_in)


@MAIN(125.0)
def cordic_narrow_main(
    x_in: narrow_t, y_in: narrow_t, valid_in: uint1_t
) -> cordic_narrow_t:
    return cordic_narrow(x_in, y_in, valid_in)


def _run(block, pairs):
    """Push `pairs` in one per cycle, drain, return the emitted angles in order."""
    out = []
    lat = block.latency
    for c in range(len(pairs) + lat + 8):
        if c < len(pairs):
            x, y = pairs[c]
            v = 1
        else:
            x, y, v = 0, 0, 0
        r = sim_call(block, x, y, v)
        if int(r.valid):
            out.append((int(r.angle), int(r.degenerate)))
    return out


def _ref_turns(x, y):
    t = math.atan2(y, x) / (2.0 * math.pi)
    if t >= 0.5:
        t -= 1.0
    return t


def _err_turns(raw, x, y):
    e = abs(raw / 65536.0 - _ref_turns(x, y))
    return min(e, abs(e - 1.0))  # +-0.5 turn is the same angle


def test_matches_golden_model():
    """Hardware and the Python model must agree BIT for bit, not approximately."""
    sim_reset()
    rng = random.Random(31337)
    pairs = []
    for _ in range(400):
        mag = 2 ** rng.randint(4, 37)
        ang = rng.uniform(-math.pi, math.pi)
        x, y = int(mag * math.cos(ang)), int(mag * math.sin(ang))
        pairs.append((x, y))
    got = _run(cordic, pairs)
    assert len(got) == len(pairs), f"{len(got)} results for {len(pairs)} inputs"
    for (x, y), (raw, degen) in zip(pairs, got):
        g_raw, g_degen = golden_cordic_atan2(cordic, x, y)
        assert raw == g_raw, f"atan2({x},{y}): hw {raw} != model {g_raw}"
        assert degen == int(g_degen)
    print("test_matches_golden_model passed")


def test_accuracy_all_quadrants():
    sim_reset()
    rng = random.Random(4242)
    pairs = []
    # Axes and quadrant boundaries first -- the pre-rotation's edge cases.
    for m in (1, 2**20, 2**37):
        pairs += [(m, 0), (0, m), (-m, 0), (0, -m), (m, m), (-m, m), (-m, -m), (m, -m)]
    for _ in range(400):
        mag = 2 ** rng.randint(3, 37)
        ang = rng.uniform(-math.pi, math.pi)
        pairs.append((int(mag * math.cos(ang)), int(mag * math.sin(ang))))
    pairs = [p for p in pairs if p != (0, 0)]
    got = _run(cordic, pairs)
    worst = 0.0
    for (x, y), (raw, _d) in zip(pairs, got):
        worst = max(worst, _err_turns(raw, x, y))
    # 2^-14 turns algorithmic + 2^-16 output quantization.
    assert worst < 6.0e-5, f"worst angle error {worst:.3e} turns"
    print(f"test_accuracy_all_quadrants passed (worst {worst:.3e} turns)")


def test_accuracy_is_scale_invariant():
    """The whole point of the input normalization: a weak phasor must be as
    accurately measured as a strong one."""
    sim_reset()
    rng = random.Random(99)
    worst_by_mag = {}
    for shift in (3, 8, 16, 24, 34):
        pairs = []
        for _ in range(120):
            ang = rng.uniform(-math.pi, math.pi)
            m = 2**shift
            x, y = int(m * math.cos(ang)), int(m * math.sin(ang))
            if (x, y) != (0, 0):
                pairs.append((x, y))
        got = _run(cordic, pairs)
        worst_by_mag[shift] = max(
            _err_turns(raw, x, y) for (x, y), (raw, _d) in zip(pairs, got)
        )
    for shift, w in worst_by_mag.items():
        assert w < 6.0e-5, f"|phasor|=2^{shift}: worst error {w:.3e} turns"
    lo, hi = worst_by_mag[3], worst_by_mag[34]
    assert hi < 4.0 * lo and lo < 4.0 * hi, (
        f"error is not scale invariant: 2^3 -> {lo:.3e}, 2^34 -> {hi:.3e} turns"
    )
    print("test_accuracy_is_scale_invariant passed " + str(
        {k: round(v, 8) for k, v in worst_by_mag.items()}
    ))


def test_degenerate_zero_input():
    sim_reset()
    got = _run(cordic, [(0, 0), (1 << 30, 0), (0, 0)])
    assert got[0] == (0, 1), f"atan2(0,0) should be degenerate, got {got[0]}"
    assert got[1] == (0, 0), f"atan2(2^30,0) should be 0 and NOT degenerate, got {got[1]}"
    assert got[2] == (0, 1)
    print("test_degenerate_zero_input passed")


def test_negative_x_axis():
    """atan2(y=0, x<0) is exactly +0.5 turns -- the one angle that sits on the
    int16 boundary, since +0.5 and -0.5 are the same direction. Either sign is
    correct; what must hold is that the result is within a LSB of the boundary
    rather than landing somewhere in the middle of the circle."""
    sim_reset()
    for x in (-(1 << 30), -1, -(1 << 37)):
        got = _run(cordic, [(x, 0)])
        raw = got[0][0]
        assert abs(abs(raw) - 32768) <= 1, (
            f"atan2(0,{x}) should be +-0.5 turn (+-32768), got {raw}"
        )
    print("test_negative_x_axis passed")


def test_pipeline_throughput_and_latency():
    """One result per cycle, in order, at the advertised latency."""
    sim_reset()
    pairs = [(1 << 20, k) for k in range(1, 33)]
    lat = cordic.latency
    seen = []
    for c in range(len(pairs) + lat + 4):
        if c < len(pairs):
            x, y, v = pairs[c][0], pairs[c][1], 1
        else:
            x, y, v = 0, 0, 0
        r = sim_call(cordic, x, y, v)
        if int(r.valid):
            seen.append(c)
    assert len(seen) == len(pairs), f"{len(seen)} valids for {len(pairs)} inputs"
    assert seen[0] == lat, f"first result at cycle {seen[0]}, expected {lat}"
    assert seen == list(range(lat, lat + len(pairs))), "not one result per cycle"
    print("test_pipeline_throughput_and_latency passed")


def test_narrow_instance():
    """A second instantiation with different widths must also be exact."""
    sim_reset()
    rng = random.Random(5150)
    pairs = []
    for _ in range(150):
        mag = 2 ** rng.randint(3, 18)
        ang = rng.uniform(-math.pi, math.pi)
        x, y = int(mag * math.cos(ang)), int(mag * math.sin(ang))
        if (x, y) != (0, 0):
            pairs.append((x, y))
    got = _run(cordic_narrow, pairs)
    for (x, y), (raw, _d) in zip(pairs, got):
        g_raw, _g = golden_cordic_atan2(cordic_narrow, x, y)
        assert raw == g_raw, f"narrow atan2({x},{y}): hw {raw} != model {g_raw}"
    print("test_narrow_instance passed")


if __name__ == "__main__":
    test_matches_golden_model()
    test_accuracy_all_quadrants()
    test_accuracy_is_scale_invariant()
    test_degenerate_zero_input()
    test_negative_x_axis()
    test_pipeline_throughput_and_latency()
    test_narrow_instance()
    print("All cordic tests passed")
