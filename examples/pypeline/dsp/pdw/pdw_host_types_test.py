#!/usr/bin/env python3
"""Guard the host-side copies of this design's wire formats against drift.

Three files are meant to be copied onto a radio running AirStack, where there is
no Pypeline checkout: `pdw_ctrl_record.py` (builds control frames),
`gr_pdw_record.py` (parses PDW records) and `pdw_verify.py` (checks a record
against its samples). Each carries the layout in pure `struct` or as plain
constants rather than importing the compiler.

That duplication is the price of not dragging Pypeline onto the radio, and this
file is what makes it safe. Everything here runs where Pypeline IS importable
and compares the host copies against the hardware's own definitions -- so a
change to `pdw_ctrl_t`, `valid_pdw_t` or `power_t` that is not mirrored fails a
test in seconds rather than producing a well-formed frame that loads the wrong
values into the wrong registers.

Why that failure mode deserves a dedicated test: a drifted control frame is
still exactly 40 bytes with `tlast` in the right place, so the deserializer
accepts it and the design runs -- on silently wrong thresholds. Nothing else in
the suite would notice. `gr_pdw_record.py` has no fast test of its own either;
it is otherwise exercised only inside pdw_tb.py's ~22-minute run.

Run: python3 pdw_host_types_test.py
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
for _d in (
    os.path.join(_ROOT, "src"),
    os.path.join(_ROOT, "include", "pypeline"),
    os.path.join(_HERE, "pulse_detect"),
    os.path.join(_HERE, "pdw_engine"),
    os.path.join(_HERE, "pdw_ctrl"),
    _HERE,
):
    sys.path.insert(0, _d)

from pypeline import byte_length, type_from_bytes, type_to_bytes

import gr_pdw_record
import pdw_ctrl_record
import pdw_verify
from pdw_ctrl import CTRL_DEFAULTS, CTRL_FLAG_LOOPBACK_EN, pdw_ctrl_t
from pdw_engine import make_pdw_engine
from pulse_detect import make_detect_pulses

_detect_pulses, _ = make_detect_pulses()
_pdw_engine, _ = make_pdw_engine(_detect_pulses)
valid_pdw_t = _pdw_engine.valid_pdw_t


# Test vectors, chosen so that EVERY field's width and signedness is load-bearing.
#
# This is not decoration. An earlier version used plausible-looking values and a
# deliberate uint64 -> int64 corruption of the record format produced identical
# bytes, because the `toa` in it was small and positive -- the negative control
# did not fire, and the test was weaker than it looked. So: every unsigned field
# carries its top bit set (so reading it as signed changes the bytes), every
# signed field is negative (so reading it as unsigned changes the bytes), and no
# two same-width neighbours share a value (so a swapped pair cannot still match).
SAMPLE_CFG = {
    "pulse_gen_pri": 0xF000_0001,  # uint32, top bit set
    "pulse_gen_width": 0x8000_0207,  # uint32, top bit set
    "pulse_gen_freq": -536_870_912,  # int32, negative
    "pulse_gen_chirp_rate": -2_097_152,  # int32, negative
    "pulse_gen_amplitude": -12_345,  # int16, negative
    "pulse_gen_noise_amp": 0xC0DE,  # uint16, top bit set
    "threshold_high": 0xDEAD_BEEF,  # uint32, top bit set
    "threshold_low": 0x8642_1357,  # uint32, top bit set
    "max_width": 0xFEDC_BA98,  # uint32, top bit set
    "min_width": 0x9876_5432,  # uint32, top bit set
    "flags": 0xA5A5_A5A5 | CTRL_FLAG_LOOPBACK_EN,
}

SAMPLE_REC = {
    "toa": 0xFEDC_BA98_7654_3210,  # uint64, top bit set
    "pulse_width": 0x8000_0205,  # uint32, top bit set
    "peak_power": 0xDEAD_BEEF,  # uint32, top bit set
    "pkt_samples": 0x9ABC_DEF0,  # uint32, top bit set
    "pri": 0x8765_4321,  # uint32, top bit set
    "peak_power_db": -14_231,  # int16, negative
    "noise_power_db": -8_765,  # int16, negative
    "freq_start": -8_192,  # int16, negative
    "freq_stop": -32_768,  # int16, most negative
    "status_flags": 0xA5A5_A5A5,  # uint32, top bit set
    "channel": 0xBEEF,  # uint16, top bit set
    "padding": 0xC0FE,  # uint16, top bit set
}


def test_ctrl_sizes_match():
    hw = byte_length(pdw_ctrl_t)
    assert pdw_ctrl_record.CTRL_BYTES == hw, (
        f"pdw_ctrl_record.CTRL_BYTES={pdw_ctrl_record.CTRL_BYTES} but "
        f"byte_length(pdw_ctrl_t)={hw}"
    )
    print(f"test_ctrl_sizes_match passed ({hw} bytes)")


def test_record_sizes_match():
    hw = byte_length(valid_pdw_t)
    assert gr_pdw_record.RECORD_BYTES == hw, (
        f"gr_pdw_record.RECORD_BYTES={gr_pdw_record.RECORD_BYTES} but "
        f"byte_length(valid_pdw_t)={hw}"
    )
    print(f"test_record_sizes_match passed ({hw} bytes)")


def test_ctrl_field_names_match():
    """The host tuple must name the same fields, in the same order. Order is
    what `type_to_bytes` serialises by, so a reordering here would produce a
    frame that packs cleanly and means something entirely different."""
    hw = tuple(pdw_ctrl_t._fields)
    assert pdw_ctrl_record.CTRL_FIELDS == hw, (
        f"field order differs:\n  host: {pdw_ctrl_record.CTRL_FIELDS}\n" f"  hw:   {hw}"
    )
    print("test_ctrl_field_names_match passed")


def test_record_field_names_match():
    hw = tuple(valid_pdw_t._fields)
    assert gr_pdw_record.RECORD_FIELDS == hw, (
        f"field order differs:\n  host: {gr_pdw_record.RECORD_FIELDS}\n" f"  hw:   {hw}"
    )
    print("test_record_field_names_match passed")


def test_ctrl_pack_matches_hardware_layout():
    """The real check: identical bytes, host packer vs the hardware's own."""
    host = pdw_ctrl_record.pack(SAMPLE_CFG)
    hw = type_to_bytes(pdw_ctrl_t, pdw_ctrl_t(**SAMPLE_CFG))
    assert (
        host == hw
    ), f"control frame differs:\n  host: {host.hex()}\n  hw:   {hw.hex()}"
    # And the hardware's unpacker agrees with the host's packer, which is the
    # direction that actually happens on the wire.
    back = type_from_bytes(pdw_ctrl_t, host)
    for f, want in SAMPLE_CFG.items():
        assert (
            int(getattr(back, f)) == want
        ), f"field {f}: hardware read back {int(getattr(back, f))}, sent {want}"
    print("test_ctrl_pack_matches_hardware_layout passed")


def test_record_pack_matches_hardware_layout():
    host = gr_pdw_record.pack_record(SAMPLE_REC)
    hw = type_to_bytes(valid_pdw_t, valid_pdw_t(**SAMPLE_REC))
    assert host == hw, f"record differs:\n  host: {host.hex()}\n  hw:   {hw.hex()}"
    # The direction the design actually uses: hardware bytes -> host parse.
    (parsed,) = gr_pdw_record.unpack_records(hw)
    assert parsed == SAMPLE_REC, f"host parse of hardware bytes differs: {parsed}"
    print("test_record_pack_matches_hardware_layout passed")


def test_ctrl_defaults_match():
    """CTRL_DEFAULTS is the power-on/in-reset state. If the host's mirror of it
    drifts, `--dry-run` output and any 'did my write land' reasoning is wrong
    about what the design starts from."""
    for f in pdw_ctrl_record.CTRL_FIELDS:
        host = pdw_ctrl_record.CTRL_DEFAULTS[f]
        hw = int(getattr(CTRL_DEFAULTS, f))
        assert host == hw, f"CTRL_DEFAULTS.{f}: host {host}, hw {hw}"
    print("test_ctrl_defaults_match passed")


def test_loopback_flag_matches():
    assert pdw_ctrl_record.CTRL_FLAG_LOOPBACK_EN == CTRL_FLAG_LOOPBACK_EN
    print("test_loopback_flag_matches passed")


def test_power_frac_bits_matches():
    """pdw_verify converts peak_power to dB with 10*log10(raw / 2**frac_bits).
    That exponent comes from power_t and nothing on the radio can look it up."""
    hw = _detect_pulses.power_t.frac_bits
    assert pdw_verify.POWER_FRAC_BITS == hw, (
        f"pdw_verify.POWER_FRAC_BITS={pdw_verify.POWER_FRAC_BITS} but "
        f"power_t.frac_bits={hw}"
    )
    print(f"test_power_frac_bits_matches passed (2**{hw})")


def test_threshold_scaling_matches():
    """The thresholds a host writes are compared against power_t, which carries
    fractional bits -- so the integer on the wire is `power << frac_bits`, not
    the power itself.

    This is the single easiest thing to get wrong in a host program, and it
    fails silently in both directions: 4096x too small is crossed by the noise
    floor and the detector declares one endless pulse, 4096x too large is never
    crossed and the device looks dead. Both present as "the hardware is broken"
    rather than as a software bug."""
    hw = _detect_pulses.power_t.frac_bits
    assert pdw_ctrl_record.POWER_FRAC_BITS == hw, (
        f"pdw_ctrl_record.POWER_FRAC_BITS={pdw_ctrl_record.POWER_FRAC_BITS} but "
        f"power_t.frac_bits={hw} -- every threshold this builds is off by "
        f"2**{abs(pdw_ctrl_record.POWER_FRAC_BITS - hw)}"
    )
    # The two host modules must agree with each other as well as with hardware.
    assert pdw_ctrl_record.POWER_FRAC_BITS == pdw_verify.POWER_FRAC_BITS
    print(f"test_threshold_scaling_matches passed (power << {hw})")


def test_amplitude_cap_prevents_overflow():
    """MAX_AMPLITUDE exists because threshold_high and the record's peak_power
    are both uint32 holding `power << frac_bits`. Prove the cap is where the
    overflow actually is -- one below it must fit, one above must be refused."""
    scale = 1 << pdw_ctrl_record.POWER_FRAC_BITS
    cap = pdw_ctrl_record.MAX_AMPLITUDE
    assert cap * cap * scale < (1 << 32), (
        f"MAX_AMPLITUDE={cap} already overflows: {cap * cap * scale} >= 2**32"
    )
    assert (cap + 1) * (cap + 1) * scale >= (1 << 32), (
        f"MAX_AMPLITUDE={cap} is more conservative than it needs to be"
    )
    cfg = pdw_ctrl_record.build_config(125e6, amplitude=cap)
    assert cfg["threshold_high"] < (1 << 32), "threshold_high overflows at the cap"
    try:
        pdw_ctrl_record.build_config(125e6, amplitude=cap + 1)
        raise AssertionError("amplitude above the cap was accepted")
    except ValueError:
        pass
    print(f"test_amplitude_cap_prevents_overflow passed (cap {cap})")


def test_freq_block_k_matches():
    """pdw_verify takes its FFT over the same window freq_accum accumulates
    over. That only matters for a MODULATED pulse -- on a chirp the frequency
    genuinely differs across the pulse, so a mismatched window would make the
    two disagree for a legitimate reason and the check would be measuring
    window choice rather than correctness."""
    hw = _detect_pulses.freq_block_k
    assert pdw_verify.FREQ_BLOCK_K == hw, (
        f"pdw_verify.FREQ_BLOCK_K={pdw_verify.FREQ_BLOCK_K} but "
        f"freq_accum's block_k={hw}"
    )
    print(f"test_freq_block_k_matches passed (block_k={hw})")


def test_status_bits_match():
    """pdw_verify keys the PRI check off STATUS_PRI_INVALID; a shifted bit
    would make it silently skip that check rather than fail it."""
    from pdw_engine import STATUS_PRI_INVALID

    assert pdw_verify.STATUS_PRI_INVALID == STATUS_PRI_INVALID
    assert gr_pdw_record.STATUS_PRI_INVALID == STATUS_PRI_INVALID
    print("test_status_bits_match passed")


def test_build_config_round_trips_through_hardware():
    """End to end: the frame the script would actually send, decoded by the
    hardware's own unpacker, must carry the values build_config computed."""
    cfg = pdw_ctrl_record.build_config(125e6, pulses_per_sec=4.0, pulse_width_s=4e-6)
    back = type_from_bytes(pdw_ctrl_t, pdw_ctrl_record.pack(cfg))
    for f, want in cfg.items():
        assert (
            int(getattr(back, f)) == want
        ), f"{f}: got {int(getattr(back, f))}, want {want}"
    assert cfg["pulse_gen_pri"] >= cfg["pulse_gen_width"] + pdw_ctrl_record.IDLE_MARGIN
    print("test_build_config_round_trips_through_hardware passed")


if __name__ == "__main__":
    print("pdw_host_types_test: host copies vs the hardware's own layouts")
    test_ctrl_sizes_match()
    test_record_sizes_match()
    test_ctrl_field_names_match()
    test_record_field_names_match()
    test_ctrl_pack_matches_hardware_layout()
    test_record_pack_matches_hardware_layout()
    test_ctrl_defaults_match()
    test_loopback_flag_matches()
    test_power_frac_bits_matches()
    test_threshold_scaling_matches()
    test_amplitude_cap_prevents_overflow()
    test_freq_block_k_matches()
    test_status_bits_match()
    test_build_config_round_trips_through_hardware()
    print("All pdw_host_types tests passed")
