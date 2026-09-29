# pyright: reportInvalidTypeForm=none
"""dsp/nco.py make_lut_nco tests: phase -> amplitude * (cos, sin) from a ROM.

`sim_call` checks the hardware against `golden_lut_nco` bit for bit, and the
golden model against `math.cos`/`math.sin` -- the second is what makes the
first worth anything, since a model and a block that share a wrong quadrant
table agree perfectly. The `@MAIN` gives `pypelinec lut_nco_test.py --comb`
elaboration coverage. Plain `python3 lut_nco_test.py` runs the sim_call tests.
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
import cmath
import math
import random

from pypeline import MAIN, int16_t, sim_call, sim_reset, uint1_t, uint32_t

from dsp.nco import golden_lut_nco, make_lut_nco, sine_quarter_table


nco, nco_t = make_lut_nco(int16_t)  # the PDW generator's configuration

# A second, coarser instance: a table/index mistake that happens to cancel at
# one size rarely does at two.
nco_small, nco_small_t = make_lut_nco(int16_t, table_bits=6, phase_bits=20)

TURN = 1 << 32


@MAIN(125.0)
def lut_nco_main(phase: uint32_t, amplitude: int16_t, valid_in: uint1_t) -> nco_t:
    return nco(phase, amplitude, valid_in)


def _run(block, reqs):
    """Push (phase, amplitude) one per cycle, drain, return emitted (i, q)."""
    out = []
    for c in range(len(reqs) + block.latency + 4):
        if c < len(reqs):
            ph, am = reqs[c]
            v = 1
        else:
            ph, am, v = 0, 0, 0
        r = sim_call(block, ph, am, v)
        if int(r.valid):
            out.append((int(r.i), int(r.q)))
    return out


def _phase_err_bound(block, amplitude):
    """Half a bin of phase error, as an amplitude error, plus rounding."""
    half_bin_rad = 2.0 * math.pi / (1 << (block.table_bits + 3))
    return abs(amplitude) * half_bin_rad + 1.0


def test_table_contents():
    t = sine_quarter_table(10, 16)
    assert len(t) == 1024
    assert t == sorted(t), "quarter-wave sine must be increasing"
    assert t[-1] == 1 << 16, "the last bin centre rounds to exactly 2^16 at 10 bits"
    assert max(t) < 1 << 17, "ROM word is table_frac + 1 bits"
    print("test_table_contents passed")


def test_matches_golden_model():
    sim_reset()
    rng = random.Random(8675309)
    reqs = [(0, 1000), (1 << 30, 1000), (1 << 31, 1000), (3 << 30, 1000)]
    reqs += [(rng.randrange(TURN), rng.randrange(-32768, 32768)) for _ in range(500)]
    reqs += [(rng.randrange(TURN), a) for a in (-32768, 32767, 0, -1, 1) for _ in range(20)]
    got = _run(nco, reqs)
    assert len(got) == len(reqs)
    for (ph, am), hw in zip(reqs, got):
        g = golden_lut_nco(nco, ph, am)
        assert hw == g, f"phase={ph:#010x} amp={am}: hw {hw} != model {g}"
    print("test_matches_golden_model passed")


def test_golden_accuracy_vs_math():
    """Every phase bin, both instances, against amplitude*cos/sin evaluated at
    the ACTUAL phase (not the bin centre). The error allowed is half a bin of
    phase plus one LSB of rounding -- a wrong quadrant sign or a mirror that is
    off by one bin misses this by orders of magnitude."""
    for block, amp in ((nco, 30000), (nco, -777), (nco_small, 20000)):
        pb = block.phase_bits
        n_bins = 1 << (block.table_bits + 2)
        rng = random.Random(block.table_bits)
        bound = _phase_err_bound(block, amp)
        worst = 0.0
        for b in range(n_bins):
            ph = (b << (pb - block.table_bits - 2)) + rng.randrange(
                1 << (pb - block.table_bits - 2)
            )
            theta = 2.0 * math.pi * ph / (1 << pb)
            i, q = golden_lut_nco(block, ph, amp)
            err = max(abs(i - amp * math.cos(theta)), abs(q - amp * math.sin(theta)))
            worst = max(worst, err)
        assert worst <= bound, f"table_bits={block.table_bits} amp={amp}: worst {worst:.2f} > {bound:.2f}"
        print(f"test_golden_accuracy_vs_math: table_bits={block.table_bits} amp={amp} "
              f"worst {worst:.2f} LSB (bound {bound:.2f})")


def test_quadrant_axes():
    """The four axis crossings, from just either side. The sign of each rail is
    unambiguous there, so a swapped sign table cannot hide."""
    amp = 10000
    eps = 1 << 12
    cases = [
        (0 + eps, +1, +1),  # just past 0: cos +, sin + (tiny)
        ((1 << 30) - eps, +1, +1),
        ((1 << 30) + eps, -1, +1),
        ((1 << 31) - eps, -1, +1),
        ((1 << 31) + eps, -1, -1),
        ((3 << 30) - eps, -1, -1),
        ((3 << 30) + eps, +1, -1),
        (TURN - eps, +1, -1),
    ]
    for ph, si, sq in cases:
        i, q = golden_lut_nco(nco, ph, amp)
        assert (i > 0) == (si > 0) and i != 0, f"phase {ph:#x}: i={i}, want sign {si}"
        assert (q > 0) == (sq > 0) and q != 0, f"phase {ph:#x}: q={q}, want sign {sq}"
    i, q = golden_lut_nco(nco, 0, amp)
    assert i == amp and abs(q) <= 8, f"phase 0 should be (amp, ~0), got ({i}, {q})"
    print("test_quadrant_axes passed")


def test_constant_envelope_and_zero_mean():
    """Over every bin: |z| stays at the amplitude, and the rails average to
    zero. A per-quadrant rounding asymmetry shows up as a DC term here, which a
    phasor frequency estimator reads as a signal at 0 Hz."""
    amp = 1000
    n_bins = 1 << (nco.table_bits + 2)
    step = 1 << (32 - nco.table_bits - 2)
    si = sq = 0
    lo = hi = None
    for b in range(n_bins):
        i, q = golden_lut_nco(nco, b * step + step // 2, amp)
        m2 = i * i + q * q
        lo = m2 if lo is None else min(lo, m2)
        hi = m2 if hi is None else max(hi, m2)
        si += i
        sq += q
    assert (amp - 2) ** 2 <= lo and hi <= (amp + 2) ** 2, f"envelope {lo}..{hi}"
    # Exact cancellation except where a product lands on exactly half an LSB,
    # which round-half-up treats asymmetrically: a count or two, not a bias.
    assert abs(si) <= 4 and abs(sq) <= 4, f"full-circle sums must cancel: {si}, {sq}"
    print("test_constant_envelope_and_zero_mean passed")


def test_saturation_not_wrap():
    """amplitude = -32768 at the positive peak is the one product that does
    not fit int16. It must clamp to +32767, not wrap to -32768."""
    i, _q = golden_lut_nco(nco, 1 << 31, -32768)  # cos(pi) * -32768 = +32768
    assert i == 32767, f"expected saturation to 32767, got {i}"
    sim_reset()
    got = _run(nco, [((1 << 31) + (1 << 20), -32768)])
    assert got[0][0] == 32767, got
    print("test_saturation_not_wrap passed")


def test_spur_level():
    """Measured spur-free dynamic range for a tone whose frequency is not a
    multiple of the bin size, so phase truncation error is as bad as it gets.
    The docstring's ~6 dB-per-index-bit claim is what this pins."""
    try:
        import numpy as np
    except ImportError:
        print("test_spur_level skipped (no numpy)")
        return
    n = 1 << 14
    freq = int(0.1234567 * TURN)
    amp = 20000
    z = np.empty(n, dtype=complex)
    ph = 0
    for k in range(n):
        i, q = golden_lut_nco(nco, ph, amp)
        z[k] = complex(i, q)
        ph = (ph + freq) % TURN
    spec = np.abs(np.fft.fft(z * np.blackman(n)))
    peak = int(np.argmax(spec))
    guard = 8
    mask = np.ones(n, dtype=bool)
    for d in range(-guard, guard + 1):
        mask[(peak + d) % n] = False
    sfdr = 20.0 * math.log10(spec[peak] / spec[mask].max())
    assert sfdr > 66.0, f"SFDR {sfdr:.1f} dB"
    print(f"test_spur_level passed (SFDR {sfdr:.1f} dBc at table_bits={nco.table_bits})")


def test_frequency_estimate_unbiased():
    """The PDW measures frequency as the angle of sum(z[n] * conj(z[n-1])).
    Phase truncation must not bias that: over a 32-product block its share of
    the error telescopes to at most one bin / 32 = 2^-17 turn. Output rounding
    adds the same order again, so the bound is 2^-15 -- under half the CORDIC
    atan2's own worst case (3.4e-5 turn) that measures it."""
    amp = 800
    worst = 0.0
    for f_turns in (0.125, -0.125, 0.0371, 0.31):
        freq = int(round(f_turns * TURN)) % TURN
        ph = 0
        prev = None
        acc = 0j
        for _k in range(33):
            i, q = golden_lut_nco(nco, ph, amp)
            z = complex(i, q)
            if prev is not None:
                acc += z * prev.conjugate()
            prev = z
            ph = (ph + freq) % TURN
        est = cmath.phase(acc) / (2.0 * math.pi)
        want = freq / TURN if freq < TURN // 2 else freq / TURN - 1.0
        err = abs(est - want)
        worst = max(worst, err)
        assert err < 2.0 ** -15, f"f={f_turns}: estimate {est} vs {want} (err {err:.2e})"
    print(f"test_frequency_estimate_unbiased passed (worst {worst:.2e} turn)")


def test_pipeline_latency():
    sim_reset()
    seen = []
    n = 12
    for c in range(n + nco.latency + 4):
        v = 1 if c < n else 0
        r = sim_call(nco, c << 24, 1000, v)
        if int(r.valid):
            seen.append(c)
    assert seen == list(range(nco.latency, nco.latency + n)), seen
    print(f"test_pipeline_latency passed (latency {nco.latency})")


if __name__ == "__main__":
    test_table_contents()
    test_matches_golden_model()
    test_golden_accuracy_vs_math()
    test_quadrant_axes()
    test_constant_envelope_and_zero_mean()
    test_saturation_not_wrap()
    test_spur_level()
    test_frequency_estimate_unbiased()
    test_pipeline_latency()
    print("All lut_nco tests passed")
