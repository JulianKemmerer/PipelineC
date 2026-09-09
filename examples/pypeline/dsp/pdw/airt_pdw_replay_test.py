#!/usr/bin/env python3
"""Exercise `airt_pdw_test.py`'s capture loop with no radio.

WHY THIS FILE EXISTS. `airt_pdw_test.py` is the only file in this project that
runs on the actual hardware, and until now it was the only one with no test at
all: the layouts are generated, `pdw_verify.py` has nineteen tests including ten
negative controls, `gr_pdw_record.py` has a self-test -- and the framing,
validation and capture loop that stand between them and a radio had never been
executed against so much as a synthetic byte. A bug there does not show up as a
wrong number; it shows up as a bring-up session that cannot be interpreted.

`--record` and `--replay` are what make this possible. The capture loop reads
through a `ReplaySource` that serves the same two calls a `RadioSource` does, so
what runs here is the real loop -- `validate_record`, the `pkt_samples` framing,
`pdw_verify.check`, the reporting -- not a copy of it.

The pulses are synthesised with `pdw_verify_test.py`'s own helpers, so the two
files agree on what a correct record looks like by construction rather than by
two people writing the same scalings twice.

MOST OF THIS FILE IS NEGATIVE CONTROLS, for the same reason `pdw_verify_test.py`
is: a capture loop that accepts everything would launder every future hardware
failure into a green run. Each one corrupts exactly one thing and asserts the
loop notices, and notices for the stated reason.

Run: python3 airt_pdw_replay_test.py
"""

import argparse
import contextlib
import io
import os
import struct
import tempfile

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

# ORDER MATTERS, exactly as in pdw_verify_test.py: airt_pdw_test imports the
# generated pypeline_host_types, which is deliberately not committed, so it has
# to be built and put on sys.path before that import happens.
import pdw_host_gen

HOST = pdw_host_gen.ensure_host_types()

import airt_pdw_test as A  # noqa: E402
import pdw_verify_test as V  # noqa: E402

FS = V.FS
# NOT V.AMP (12000). That amplitude's peak_power is `12000**2 << 12`, which
# overflows the record's uint32_t field -- fine for pdw_verify_test, whose other
# tests hand dicts straight to pdw_verify without ever serialising one, and
# fatal here where every record goes through valid_pdw_t.to_bytes.
AMP = 800
WIDTH = V.WIDTH
PRI = V.PRI
TOA0 = 1_000_000

_SCRATCH = "/media/1TB/tmp"


def _tmp(name):
    root = _SCRATCH if os.path.isdir(_SCRATCH) else None
    d = tempfile.mkdtemp(prefix="pdw_replay_", dir=root)
    return os.path.join(d, name)


def make_session(n_pulses=4, mutate=None, freq_frac=V.FREQ_FRAC, chirp=0.0):
    """-> a capture file holding `n_pulses` correct pulses.

    `mutate(index, rec_dict, packet_bytes) -> (rec_dict, packet_bytes)` is the
    hook every negative control below uses to break exactly one thing.
    """
    path = _tmp("session.pdwcap")
    f = A.capture_open(path, FS)
    try:
        for k in range(n_pulses):
            iq = V.make_pulse(n=WIDTH, amp=AMP, freq_frac=freq_frac, chirp=chirp)
            rec = V.make_record(
                iq, freq_frac=freq_frac, chirp=chirp,
                toa=TOA0 + k * PRI, pri=PRI,
            )
            pkt = iq.astype("<i2").tobytes()
            if mutate is not None:
                rec, pkt = mutate(k, rec, pkt)
            f.write(struct.pack(A.CAP_ITEM, HOST.valid_pdw_t.BYTE_LENGTH, len(pkt)))
            f.write(HOST.valid_pdw_t.to_bytes(HOST.valid_pdw_t(**rec)))
            f.write(pkt)
    finally:
        f.close()
    return path


def _args(**over):
    a = argparse.Namespace(
        pulses=100, duration=0.0, record=None, csv=None, ref_level_db=0.0,
        pulses_per_sec=4.0, resync_on_error=False, max_resyncs=5,
    )
    for k, v in over.items():
        setattr(a, k, v)
    return a


def _replay(path, cfg=None, **over):
    """-> (n_failed, printed_output). Runs the real capture loop."""
    if cfg is None:
        cfg = V.cfg_for(amp=AMP, width=WIDTH, pri=PRI)
    src = A.ReplaySource(path)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        n_failed = A.capture(src, cfg, FS, _args(**over))
    return n_failed, out.getvalue()


# ─────────────────────────────────────────────
# Positive: a correct session must pass cleanly
# ─────────────────────────────────────────────


def test_clean_session_replays_with_no_failures():
    n_failed, out = _replay(make_session(4))
    assert n_failed == 0, f"a correct session reported {n_failed} failures:\n{out}"
    assert "4 pulses captured" in out, out
    assert "replay complete" in out, out
    print("test_clean_session_replays_with_no_failures passed")


def test_chirped_session_replays():
    """A chirp is the only stimulus where freq_start and freq_stop differ, so
    it is the only one where the loop carrying both fields is really tested."""
    path = make_session(3, chirp=1e-5)
    cfg = V.cfg_for(amp=AMP, width=WIDTH, pri=PRI, chirp=1)
    n_failed, out = _replay(path, cfg=cfg)
    assert n_failed == 0, f"chirped session reported {n_failed} failures:\n{out}"
    print("test_chirped_session_replays passed")


def test_record_bytes_survive_the_round_trip():
    """The framing's foundation: what capture_write stores is what
    valid_pdw_t.from_bytes reads back."""
    path = make_session(2)
    fs, items = A.capture_read(path)
    assert fs == FS
    assert len(items) == 2, f"expected 2 items, got {len(items)}"
    for rec_raw, pkt_raw in items:
        assert len(rec_raw) == HOST.valid_pdw_t.BYTE_LENGTH
        rec = HOST.valid_pdw_t.from_bytes(rec_raw)._asdict()
        assert rec["pkt_samples"] * A.BYTES_PER_ELEM == len(pkt_raw), (
            f"record says {rec['pkt_samples']} samples, file holds {len(pkt_raw)} bytes"
        )
        assert A.validate_record(rec) == []
    print("test_record_bytes_survive_the_round_trip passed")


# ─────────────────────────────────────────────
# Negative: validate_record's invariants
# ─────────────────────────────────────────────


def _expect_caught(path, want, cfg=None, **over):
    n_failed, out = _replay(path, cfg=cfg, **over)
    assert n_failed > 0, f"corruption was NOT caught:\n{out}"
    assert want in out, f"caught, but not for the stated reason ({want!r}):\n{out}"
    return out


def _corrupt_field(field, value, at=1):
    def m(k, rec, pkt):
        if k == at:
            rec = dict(rec, **{field: value})
        return rec, pkt
    return m


def test_nonzero_channel_is_caught():
    """`channel` and `padding` are four bytes of known zero in every record --
    the cheapest desync detector there is, and the whole reason a slipped
    stream is noticed before its pkt_samples is used to allocate memory."""
    _expect_caught(make_session(4, _corrupt_field("channel", 7)),
                   "channel is 7")
    print("test_nonzero_channel_is_caught passed")


def test_nonzero_padding_is_caught():
    _expect_caught(make_session(4, _corrupt_field("padding", 1)), "padding is 1")
    print("test_nonzero_padding_is_caught passed")


def test_pkt_samples_disagreeing_with_pulse_width_is_caught():
    """Two independently-transmitted fields that must be equal while the
    N_pre/N_post margins are unbuilt."""
    _expect_caught(make_session(4, _corrupt_field("pkt_samples", WIDTH + 3)),
                   "!= pulse_width")
    print("test_pkt_samples_disagreeing_with_pulse_width_is_caught passed")


def test_absurd_pkt_samples_is_caught_before_allocating():
    """The failure this exists to prevent: on a desynced stream `pkt_samples`
    is arbitrary, and without the bound the first thing the script does with it
    is np.empty(2 * that)."""
    huge = HOST.PKT_FIFO_DEPTH * 1000
    def m(k, rec, pkt):
        if k == 1:
            rec = dict(rec, pkt_samples=huge, pulse_width=huge)
        return rec, pkt
    out = _expect_caught(make_session(4, m), "the data FIFO's depth")
    assert "MemoryError" not in out
    print("test_absurd_pkt_samples_is_caught_before_allocating passed")


def test_pkt_fifo_full_flag_is_caught():
    """A DELIVERED record cannot carry this bit: packet_store force-rejects any
    packet that lost beats (`accept & ~new_bad`) and flushes it, so its record
    never leaves. Seeing it means a desync -- or that the design changed and
    this invariant needs revisiting."""
    _expect_caught(
        make_session(4, _corrupt_field(
            "status_flags", HOST.STATUS_PKT_FIFO_FULL)),
        "cannot carry",
    )
    print("test_pkt_fifo_full_flag_is_caught passed")


def test_undefined_status_bit_is_caught():
    _expect_caught(make_session(4, _corrupt_field("status_flags", 1 << 20)),
                   "undefined bits")
    print("test_undefined_status_bit_is_caught passed")


def test_non_monotonic_toa_is_caught():
    _expect_caught(make_session(4, _corrupt_field("toa", TOA0 - 1)),
                   "did not advance")
    print("test_non_monotonic_toa_is_caught passed")


def test_width_outside_the_qualification_window_is_caught():
    """A width below min_width would have been glitch-rejected, so a record
    carrying one never came from the configuration we think is loaded."""
    def m(k, rec, pkt):
        if k == 1:
            rec = dict(rec, pulse_width=4, pkt_samples=4)
            pkt = pkt[: 4 * A.BYTES_PER_ELEM]
        return rec, pkt
    _expect_caught(make_session(4, m), "below min_width")
    print("test_width_outside_the_qualification_window_is_caught passed")


# ─────────────────────────────────────────────
# Negative: the framing and the file itself
# ─────────────────────────────────────────────


def test_packet_shorter_than_the_record_claims_is_caught():
    def m(k, rec, pkt):
        if k == 1:
            pkt = pkt[: len(pkt) - 8]  # record still says WIDTH samples
        return rec, pkt
    _expect_caught(make_session(4, m), "but 1992 were stored")
    print("test_packet_shorter_than_the_record_claims_is_caught passed")


def test_truncated_file_raises():
    path = make_session(3)
    with open(path, "rb") as f:
        blob = f.read()
    cut = path + ".cut"
    with open(cut, "wb") as f:
        f.write(blob[: len(blob) - 100])
    try:
        A.capture_read(cut)
    except ValueError as e:
        assert "truncated" in str(e) or "only" in str(e), e
        print("test_truncated_file_raises passed")
        return
    raise AssertionError("a truncated capture file was read as if complete")


def test_bad_magic_raises():
    path = _tmp("bogus.pdwcap")
    with open(path, "wb") as f:
        f.write(struct.pack(A.CAP_HEADER, b"NOTACAP1", FS))
    try:
        A.capture_read(path)
    except ValueError as e:
        assert "magic" in str(e), e
        print("test_bad_magic_raises passed")
        return
    raise AssertionError("a file with the wrong magic was accepted")


# ─────────────────────────────────────────────
# Negative: a record that is well formed but WRONG
# ─────────────────────────────────────────────


def test_wrong_frequency_reaches_pdw_verify():
    """Validation is about framing; it cannot tell whether a measurement is
    right. This proves a record that passes every structural check still gets
    compared against its own samples, and fails there."""
    def m(k, rec, pkt):
        if k == 1:
            rec = dict(rec, freq_start=rec["freq_start"] + 4000)
        return rec, pkt
    path = make_session(4, m)
    n_failed, out = _replay(path)
    assert n_failed > 0, f"a wrong freq_start was not caught:\n{out}"
    assert "record failed validation" not in out, (
        "caught by validation rather than by pdw_verify -- so this test is not "
        f"measuring what it says:\n{out}"
    )
    assert "freq_start" in out, out
    print("test_wrong_frequency_reaches_pdw_verify passed")


def test_stops_at_the_first_desync_by_default():
    """Framing is pure counting, so nothing after a desync is interpretable.
    Continuing would print plausible-looking garbage."""
    _n, out = _replay(make_session(6, _corrupt_field("channel", 3, at=2)))
    assert "pulse 3" not in out, (
        f"kept reading past a desync:\n{out}"
    )
    assert "2 pulses captured" in out, out
    print("test_stops_at_the_first_desync_by_default passed")


# ─────────────────────────────────────────────
# The resync path -- what a soak depends on
# ─────────────────────────────────────────────


def _replay_with_reset(path, reset_of, **over):
    """Run the loop with a `reset` callable, the way `run()` supplies one."""
    src = A.ReplaySource(path)
    cfg = V.cfg_for(amp=AMP, width=WIDTH, pri=PRI)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        n_failed = A.capture(
            src, cfg, FS, _args(resync_on_error=True, **over),
            reset=lambda: reset_of(src),
        )
    return n_failed, out.getvalue()


def test_resync_recovers_and_continues():
    """One bad record in the middle must not end a soak. On real hardware the
    reset callable resets the design; here it just steps past the bad item,
    which exercises the same control flow."""
    def skip(src):
        src.i += 1
    n_failed, out = _replay_with_reset(
        make_session(4, _corrupt_field("channel", 9, at=1)), skip
    )
    assert "resyncing" in out, out
    assert "3 pulses captured" in out, f"did not resume after the resync:\n{out}"
    assert "1 resyncs" in out, out
    assert n_failed == 1, f"expected exactly the one bad record to count: {n_failed}"
    print("test_resync_recovers_and_continues passed")


def test_resync_gives_up_on_a_persistent_fault():
    """A fault that reappears after every reset is not the transient kind a
    reset fixes. Without the bound this loop never terminates: a resync does
    not advance the pulse index, and --duration is unset."""
    def rewind(src):
        src.i = 0
    n_failed, out = _replay_with_reset(
        make_session(4, lambda k, rec, pkt: (dict(rec, channel=5), pkt)),
        rewind, max_resyncs=2,
    )
    assert "giving up after 2 resyncs" in out, f"did not stop:\n{out}"
    assert n_failed > 0
    print("test_resync_gives_up_on_a_persistent_fault passed")


def test_pulses_limit_is_honoured():
    n_failed, out = _replay(make_session(6), pulses=2)
    assert n_failed == 0 and "2 pulses captured" in out, out
    print("test_pulses_limit_is_honoured passed")


if __name__ == "__main__":
    print(f"airt_pdw_replay_test: amp={AMP} width={WIDTH} fs={FS / 1e6:.0f} MSPS")
    test_clean_session_replays_with_no_failures()
    test_chirped_session_replays()
    test_record_bytes_survive_the_round_trip()
    test_nonzero_channel_is_caught()
    test_nonzero_padding_is_caught()
    test_pkt_samples_disagreeing_with_pulse_width_is_caught()
    test_absurd_pkt_samples_is_caught_before_allocating()
    test_pkt_fifo_full_flag_is_caught()
    test_undefined_status_bit_is_caught()
    test_non_monotonic_toa_is_caught()
    test_width_outside_the_qualification_window_is_caught()
    test_packet_shorter_than_the_record_claims_is_caught()
    test_truncated_file_raises()
    test_bad_magic_raises()
    test_wrong_frequency_reaches_pdw_verify()
    test_stops_at_the_first_desync_by_default()
    test_resync_recovers_and_continues()
    test_resync_gives_up_on_a_persistent_fault()
    test_pulses_limit_is_honoured()
    print("All airt_pdw_replay tests passed")
