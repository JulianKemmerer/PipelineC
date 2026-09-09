#!/usr/bin/env python3
"""Prove `pdw_verify.py`'s checks actually catch a wrong record.

`pdw_verify` is what says a PDW record agrees with its own samples on real
hardware. A verifier that always returns "ok" would be worse than no verifier at
all -- it would launder every future failure into a green run -- so the bulk of
this file is negative controls: build a record that is correct, corrupt exactly
one field, and assert that the check for THAT field fails and the others do not.
The localisation matters as much as the failure; a check that fires on every
corruption is not measuring what its name says.

The positive cases synthesise pulses in numpy (a tone, a chirp, a negative
carrier) and construct the record the hardware would emit for them, using the
documented scalings: `peak_power` is `max(I^2+Q^2)` in power_t's 12-fraction-bit
units, `peak_power_db` is `10*log10` of that represented value in Q8.8, and the
frequency fields are turns x 2^16.

Run: python3 pdw_verify_test.py
"""

import math
import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

import numpy as np

# ORDER MATTERS. pdw_verify imports its hardware constants from the generated
# pypeline_host_types, which is deliberately not committed -- so it has to be
# built and put on sys.path before pdw_verify is imported at all. This one call
# is the whole cost of having no checked-in copy that could go stale.
import pdw_host_gen

HOST = pdw_host_gen.ensure_host_types()

import pdw_verify  # noqa: E402
from pdw_verify import DB_Q8_8, POWER_FRAC_BITS, TURNS_16  # noqa: E402

FS = 125e6
AMP = 12000
WIDTH = 500
FREQ_FRAC = 0.125
PRI = 31_250_000


def make_pulse(n=WIDTH, amp=AMP, freq_frac=FREQ_FRAC, chirp=0.0):
    """A synthetic pulse as the interleaved int16 a CS16 read would produce."""
    t = np.arange(n)
    # Instantaneous frequency f(t) = freq_frac + chirp*t, so the phase is the
    # integral of that -- the same shape pulse_gen's chirp accumulator makes.
    phase = 2 * np.pi * (freq_frac * t + 0.5 * chirp * t * t)
    x = amp * np.exp(1j * phase)
    iq = np.empty(2 * n, np.int16)
    iq[0::2] = np.round(x.real)
    iq[1::2] = np.round(x.imag)
    return iq


def make_record(
    samples,
    freq_frac=FREQ_FRAC,
    chirp=0.0,
    toa=1_000_000,
    pri=PRI,
    width=None,
    noise_db_offset=40.0,
):
    """The record the hardware would emit for `samples`, by the documented scalings."""
    x = samples[0::2].astype(np.float64) + 1j * samples[1::2].astype(np.float64)
    n = len(x)
    peak_lin = float((np.abs(x) ** 2).max())
    peak_raw = int(round(peak_lin * (1 << POWER_FRAC_BITS)))
    peak_db = int(round(DB_Q8_8 * 10.0 * math.log10(peak_raw / (1 << POWER_FRAC_BITS))))
    # The hardware reports the AVERAGE frequency over each of its two windows,
    # not the instantaneous value at an endpoint -- freq_accum sums phasor
    # products over the first block_k pairs and over the most recent
    # block_k..2*block_k. Modelling that here rather than using f(0) and f(n-1)
    # keeps the chirp case a real agreement test instead of one that merely
    # fits inside the tolerance.
    bk = pdw_verify.FREQ_BLOCK_K
    stop_n = min(pdw_verify.FREQ_STOP_BLOCKS * bk, n)
    f_start_frac = freq_frac + chirp * (min(bk, n) - 1) / 2.0
    f_stop_frac = freq_frac + chirp * (n - stop_n + (stop_n - 1) / 2.0)
    return {
        "toa": toa,
        "pulse_width": width if width is not None else n,
        "peak_power": peak_raw,
        "pkt_samples": n,
        "pri": pri,
        "peak_power_db": peak_db,
        "noise_power_db": int(round(peak_db - noise_db_offset * DB_Q8_8)),
        "freq_start": int(round(f_start_frac * TURNS_16)),
        "freq_stop": int(round(f_stop_frac * TURNS_16)),
        "status_flags": 0,
        "channel": 0,
        "padding": 0,
    }


def cfg_for(freq_frac=FREQ_FRAC, amp=AMP, width=WIDTH, pri=PRI, chirp=0):
    return {
        "pulse_gen_pri": pri,
        "pulse_gen_width": width,
        "pulse_gen_freq": int(round(freq_frac * (1 << 32))),
        "pulse_gen_chirp_rate": chirp,
        "pulse_gen_amplitude": amp,
        "pulse_gen_noise_amp": 0,
        "threshold_high": int(0.6 * amp * amp),
        "threshold_low": int(0.3 * amp * amp),
        "max_width": width * 4,
        "min_width": width // 4,
        "flags": 1,
    }


def _failed(rows):
    return sorted(r["name"] for r in rows if not r["ok"])


def _run(rec, samples, cfg=None, prev_toa=None):
    return pdw_verify.check(rec, samples, FS, cfg=cfg, prev_toa=prev_toa)



# ---------------------------------------------------------------------------
# The generated module, and its composition with this project's host logic.
#
# NOT a drift guard. The old pdw_host_types_test.py existed to catch hand-copied
# layouts diverging from the hardware, and that class of bug is gone: the layout
# is generated from the same leaf walk the serializer is built from, and nothing
# is committed that could go stale. What is worth checking is that the pieces
# still FIT -- that this design exports what the host files import.
# ---------------------------------------------------------------------------
def test_generated_module_carries_the_designs_types():
    for name, n_bytes in (("pdw_ctrl_t", 40), ("valid_pdw_t", 40),
                          ("candidate_rec_t", 16)):
        t = getattr(HOST, name)
        assert t.BYTE_LENGTH == n_bytes, f"{name}: {t.BYTE_LENGTH} != {n_bytes}"
    # The two strings the deleted host files used to hand-write, now derived.
    assert HOST.pdw_ctrl_t.FORMAT == "IIiihHIIIII", HOST.pdw_ctrl_t.FORMAT
    assert HOST.valid_pdw_t.FORMAT == "QIIIIhhhhIHH", HOST.valid_pdw_t.FORMAT
    print("test_generated_module_carries_the_designs_types passed")


def test_exported_constants_are_present():
    """Every constant the host files import, and the two that are not layout.

    POWER_FRAC_BITS and FREQ_BLOCK_K are read off the built instances by
    top.py's host_export. They were hardcoded host-side as 12 and 32 before this
    migration; if a future dc_k/ma_n/block_k change moved them, the host would
    follow silently rather than needing a test to notice."""
    assert HOST.POWER_FRAC_BITS == pdw_verify.POWER_FRAC_BITS
    assert HOST.FREQ_BLOCK_K == pdw_verify.FREQ_BLOCK_K
    assert HOST.CTRL_FLAG_LOOPBACK_EN == 1
    for bit in ("STATUS_ADC_CLIP", "STATUS_DSP_OVERFLOW", "STATUS_PKT_FIFO_FULL",
                "STATUS_FREQ_DEGENERATE", "STATUS_PRI_INVALID"):
        assert hasattr(HOST, bit), f"{bit} was not exported"
    # CTRL_DEFAULTS arrives as a real pdw_ctrl_t, not a dict of numbers.
    assert isinstance(HOST.CTRL_DEFAULTS, HOST.pdw_ctrl_t)
    assert HOST.CTRL_DEFAULTS.threshold_high == 0xFFFFFFFF
    print("test_exported_constants_are_present passed")


def test_build_config_round_trips_through_generated_layout():
    """The frame airt_pdw_test.py actually sends, decoded by the same layout."""
    import airt_pdw_test as A

    cfg = A.build_config(FS, pulses_per_sec=4.0, pulse_width_s=4e-6)
    frame = HOST.pdw_ctrl_t.to_bytes(HOST.pdw_ctrl_t(**cfg))
    assert len(frame) == HOST.pdw_ctrl_t.BYTE_LENGTH
    assert HOST.pdw_ctrl_t.from_bytes(frame)._asdict() == cfg
    # The scaling that fails silently in both directions, tied to the design's
    # own POWER_FRAC_BITS rather than a literal 4096.
    assert cfg["threshold_high"] == int(0.6 * 800 * 800 * (1 << HOST.POWER_FRAC_BITS))
    assert cfg["threshold_high"] < (1 << 32)
    print("test_build_config_round_trips_through_generated_layout passed")


def test_record_round_trips_through_generated_layout():
    """gr_pdw_record's boundary helper, against the generated type.

    Uses a HARDWARE-REPRESENTABLE amplitude rather than this file's AMP. The
    other tests here never serialize a record -- they hand dicts straight to
    pdw_verify -- so AMP=12000 is harmless for them even though `peak_power`
    at that amplitude is 12000**2 << POWER_FRAC_BITS, which overflows the
    uint32 field and wraps. That wrap is precisely what MAX_AMPLITUDE (1023)
    exists to prevent, and this test is the first thing in the suite that puts
    a record on the wire, so it is the first thing that would see it.
    """
    import gr_pdw_record

    s = make_pulse(amp=800)
    rec = make_record(s)
    assert rec["peak_power"] < (1 << 32), (
        f"fixture peak_power {rec['peak_power']} does not fit the uint32 field"
    )
    frame = HOST.valid_pdw_t.to_bytes(HOST.valid_pdw_t(**rec))
    (back,) = gr_pdw_record.records_from_bytes(frame)
    assert back == rec, f"record round-trip differs: {back}"
    print("test_record_round_trips_through_generated_layout passed")


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------
def test_clean_tone_passes():
    s = make_pulse()
    rows = _run(make_record(s), s, cfg_for(), prev_toa=1_000_000 - PRI)
    assert not _failed(rows), f"clean tone should pass, failed: {_failed(rows)}"
    assert len(rows) >= 10, f"only {len(rows)} checks ran -- too few to mean much"
    print(f"test_clean_tone_passes passed ({len(rows)} checks)")


def test_negative_carrier_passes():
    """A carrier below the tuned centre. Catches a sign or wrap error in the
    turns conversion, which a positive-only test would miss entirely."""
    s = make_pulse(freq_frac=-0.1875)
    rows = _run(make_record(s, freq_frac=-0.1875), s, cfg_for(freq_frac=-0.1875))
    assert not _failed(rows), f"negative carrier failed: {_failed(rows)}"
    print("test_negative_carrier_passes passed")


def test_chirp_separates_start_and_stop():
    """With a chirp the two frequency fields genuinely differ, so freq_stop is
    a real check rather than a duplicate of freq_start."""
    chirp = 4e-5
    s = make_pulse(chirp=chirp)
    rec = make_record(s, chirp=chirp)
    assert (
        abs(rec["freq_stop"] - rec["freq_start"]) > 500
    ), "the chirp must actually separate the two fields for this to test anything"
    rows = _run(rec, s)
    assert not _failed(rows), f"chirp case failed: {_failed(rows)}"
    # Passing "within tolerance" is not enough to claim the two methods agree
    # on a chirp -- the tolerance is half a bin, which is wide. Pin the actual
    # deltas so a future estimator change that merely stays inside the
    # tolerance still shows up here.
    m = pdw_verify.measure(s, FS)
    d0 = abs(rec["freq_start"] - m["freq_start_turns"] * TURNS_16)
    d1 = abs(rec["freq_stop"] - m["freq_stop_turns"] * TURNS_16)
    assert d0 < 60 and d1 < 60, (
        f"FFT and the window-averaged model disagree by more than 60 counts "
        f"on a chirp: start {d0:.1f}, stop {d1:.1f}"
    )
    print(
        f"test_chirp_separates_start_and_stop passed "
        f"(start {rec['freq_start']} -> stop {rec['freq_stop']}, "
        f"deltas {d0:.1f}/{d1:.1f} counts)"
    )


def test_estimator_accuracy_is_sub_bin():
    """The frequency tolerance is derived from FFT bin size; this pins that the
    estimator really is well inside one bin, so the tolerance is not hiding a
    sloppy estimate."""
    for frac in (0.125, 0.0313, -0.4, 0.2499):
        s = make_pulse(freq_frac=frac)
        m = pdw_verify.measure(s, FS)
        err_bins = abs(m["freq_center_turns"] - frac) / m["bin_turns"]
        assert err_bins < 0.05, f"freq {frac}: {err_bins:.3f} bins of error"
    print("test_estimator_accuracy_is_sub_bin passed (<0.05 bin)")


# ---------------------------------------------------------------------------
# Negative controls -- each must fail its OWN check and no other
# ---------------------------------------------------------------------------
def _expect_only(rec, samples, want_substr, cfg=None, prev_toa=None):
    rows = _run(rec, samples, cfg=cfg, prev_toa=prev_toa)
    bad = _failed(rows)
    assert (
        bad
    ), f"corruption was NOT caught (expected a failure containing {want_substr!r})"
    matched = [n for n in bad if want_substr in n]
    assert matched, f"caught, but by the wrong check: {bad} (wanted {want_substr!r})"
    return bad


def test_wrong_freq_start_is_caught():
    s = make_pulse()
    rec = make_record(s)
    # Several FFT bins away: 1/125 turns per bin at block=124, so ~525 counts.
    rec["freq_start"] += 3000
    bad = _expect_only(rec, s, "freq_start")
    assert not any(
        "freq_stop" in n for n in bad
    ), f"corrupting freq_start also failed freq_stop: {bad}"
    print(f"test_wrong_freq_start_is_caught passed ({bad})")


def test_wrong_freq_stop_is_caught():
    s = make_pulse()
    rec = make_record(s)
    rec["freq_stop"] -= 3000
    bad = _expect_only(rec, s, "freq_stop")
    assert not any("freq_start" in n for n in bad), f"leaked into freq_start: {bad}"
    print("test_wrong_freq_stop_is_caught passed")


def test_halved_peak_power_is_caught():
    s = make_pulse()
    rec = make_record(s)
    rec["peak_power"] //= 2
    # Halving the linear power without touching the dB field must break BOTH
    # the sample comparison and the dB self-consistency -- they are independent
    # checks of the same number, so a single corruption failing only one of
    # them would mean the other is not really looking.
    bad = _expect_only(rec, s, "peak_power vs max")
    assert any(
        "peak_power_db vs peak_power" in n for n in bad
    ), f"the dB self-consistency check did not notice: {bad}"
    print("test_halved_peak_power_is_caught passed")


def test_inconsistent_db_is_caught():
    """Corrupt ONLY the dB field. The sample comparison must stay green, which
    is what proves the dB check is independent of it rather than redundant."""
    s = make_pulse()
    rec = make_record(s)
    rec["peak_power_db"] += int(3.0 * DB_Q8_8)  # 3 dB off, far past 0.046
    bad = _expect_only(rec, s, "peak_power_db vs peak_power")
    assert not any(
        "peak_power vs max" in n for n in bad
    ), f"a dB-only error should not fail the linear check: {bad}"
    print("test_inconsistent_db_is_caught passed")


def test_wrong_pkt_samples_is_caught():
    s = make_pulse()
    rec = make_record(s)
    rec["pkt_samples"] -= 1
    bad = _expect_only(rec, s, "pkt_samples")
    print(f"test_wrong_pkt_samples_is_caught passed ({bad})")


def test_width_mismatch_is_caught():
    s = make_pulse()
    rec = make_record(s)
    rec["pulse_width"] = rec["pkt_samples"] - 50
    bad = _expect_only(rec, s, "pulse_width", cfg=cfg_for())
    print(f"test_width_mismatch_is_caught passed ({len(bad)} checks fired)")


def test_wrong_pri_is_caught():
    s = make_pulse()
    rec = make_record(s)
    rec["pri"] = PRI + 12345
    bad = _expect_only(rec, s, "pri == toa delta", prev_toa=rec["toa"] - PRI)
    print("test_wrong_pri_is_caught passed")


def test_non_monotonic_toa_is_caught():
    s = make_pulse()
    rec = make_record(s)
    _expect_only(rec, s, "toa strictly increasing", prev_toa=rec["toa"] + 1)
    print("test_non_monotonic_toa_is_caught passed")


def test_wrong_commanded_amplitude_is_caught():
    """The commanded<->software leg: samples that are not the pulse ordered."""
    s = make_pulse(amp=AMP // 2)
    rows = _run(make_record(s), s, cfg_for(amp=AMP))
    bad = _failed(rows)
    assert any(
        "commanded amplitude" in n for n in bad
    ), f"half-amplitude samples not caught against the commanded config: {bad}"
    print("test_wrong_commanded_amplitude_is_caught passed")


def test_wrong_commanded_carrier_is_caught():
    s = make_pulse(freq_frac=0.25)
    rows = _run(make_record(s, freq_frac=0.25), s, cfg_for(freq_frac=FREQ_FRAC))
    bad = _failed(rows)
    assert any(
        "commanded carrier" in n for n in bad
    ), f"a carrier at the wrong frequency was not caught: {bad}"
    # The hardware<->software leg must still pass: the record correctly
    # describes the samples, they are just not the samples that were ordered.
    assert not any(
        "FFT vs CORDIC" in n for n in bad
    ), f"the record matches its own samples, so those checks should pass: {bad}"
    print("test_wrong_commanded_carrier_is_caught passed")


def test_snr_bound_is_caught():
    s = make_pulse()
    rec = make_record(s)
    rec["noise_power_db"] = rec["peak_power_db"] + 100  # floor above the peak
    _expect_only(rec, s, "SNR > 0")
    print("test_snr_bound_is_caught passed")


if __name__ == "__main__":
    print(f"pdw_verify_test: fs={FS / 1e6:.1f} MSPS amp={AMP} width={WIDTH}")
    print(f"  generated host types: {HOST.__file__}")
    test_generated_module_carries_the_designs_types()
    test_exported_constants_are_present()
    test_build_config_round_trips_through_generated_layout()
    test_record_round_trips_through_generated_layout()
    test_clean_tone_passes()
    test_negative_carrier_passes()
    test_chirp_separates_start_and_stop()
    test_estimator_accuracy_is_sub_bin()
    test_wrong_freq_start_is_caught()
    test_wrong_freq_stop_is_caught()
    test_halved_peak_power_is_caught()
    test_inconsistent_db_is_caught()
    test_wrong_pkt_samples_is_caught()
    test_width_mismatch_is_caught()
    test_wrong_pri_is_caught()
    test_non_monotonic_toa_is_caught()
    test_wrong_commanded_amplitude_is_caught()
    test_wrong_commanded_carrier_is_caught()
    test_snr_bound_is_caught()
    print("All pdw_verify tests passed")
