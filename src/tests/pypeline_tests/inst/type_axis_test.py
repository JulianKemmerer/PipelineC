# pyright: reportInvalidTypeForm=none
"""axi/type_axis.py -- struct stream <-> AXI-Stream frames, all four variants.

Covers the framing policy this layer adds on top of stream/type_byte_stream.py:
one-struct-per-packet with a length limiter, many-structs-per-packet, runt
recovery, and tkeep-aware partial beats in both directions. Several tests are
named regressions for old PipelineC defects; each says which.
"""
import os
import sys

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
from typing import NamedTuple

from pypeline import (
    MAIN,
    byte_length,
    sim_call,
    sim_reset,
    struct,
    type_to_bytes,
    uint8_t,
    uint16_t,
    uint32_t,
)

from axi.type_axis import make_axis_to_type, make_type_to_axis

N = 4


# 7 bytes on a 4-byte bus: partial final beat, and smaller than a minimum
# Ethernet frame, so the limiter has real work to do.
@struct
class hdr_t(NamedTuple):
    version: uint8_t
    length: uint16_t
    flags: uint32_t


# 3 bytes: several fit in one packet and their boundaries straddle beats.
@struct
class pt_t(NamedTuple):
    x: uint8_t
    y: uint16_t


rx_one, rx_one_t = make_axis_to_type(hdr_t, N)
tx_one, tx_one_t = make_type_to_axis(hdr_t, N)
rx_many, rx_many_t = make_axis_to_type(pt_t, N, frame="many_per_packet")
tx_many, tx_many_t = make_type_to_axis(
    pt_t, N, frame="many_per_packet", structs_per_packet=3
)
rx_pad, rx_pad_t = make_axis_to_type(pt_t, N, frame="many_per_packet", on_runt="zero_pad")
rx_ignore, rx_ignore_t = make_axis_to_type(
    pt_t, N, frame="many_per_packet", on_runt="ignore"
)


@MAIN
def rx_one_main(
    axis_in_if: rx_one.axis_intrf.fwd_t, stream_out_if: rx_one.out_fb_t
) -> rx_one_t:
    return rx_one(axis_in_if, stream_out_if)


@MAIN
def tx_one_main(
    stream_in_if: tx_one.in_intrf.fwd_t, axis_out_if: tx_one.axis_fb_t
) -> tx_one_t:
    return tx_one(stream_in_if, axis_out_if)


@MAIN
def rx_many_main(
    axis_in_if: rx_many.axis_intrf.fwd_t, stream_out_if: rx_many.out_fb_t
) -> rx_many_t:
    return rx_many(axis_in_if, stream_out_if)


@MAIN
def tx_many_main(
    stream_in_if: tx_many.in_intrf.fwd_t, axis_out_if: tx_many.axis_fb_t
) -> tx_many_t:
    return tx_many(stream_in_if, axis_out_if)


@MAIN
def rx_pad_main(
    axis_in_if: rx_pad.axis_intrf.fwd_t, stream_out_if: rx_pad.out_fb_t
) -> rx_pad_t:
    return rx_pad(axis_in_if, stream_out_if)


@MAIN
def rx_ignore_main(
    axis_in_if: rx_ignore.axis_intrf.fwd_t, stream_out_if: rx_ignore.out_fb_t
) -> rx_ignore_t:
    return rx_ignore(axis_in_if, stream_out_if)


# ── helpers ───────────────────────────────────


def _in_beat(mod, data, keep, eod, valid=1):
    st = mod.axis_intrf.stream_t
    frag_t = st.typeof("data")
    bus_t = frag_t.typeof("frag")
    data = list(data) + [0] * (N - len(data))
    keep = list(keep) + [0] * (N - len(keep))
    return mod.axis_intrf.fwd_t(
        st(data=frag_t(frag=bus_t(data=data, keep=keep), eod=[eod]), valid=valid)
    )


def _frame(payload):
    """Bytes -> full-keep beats with eod on the last."""
    beats = []
    for i in range(0, len(payload), N):
        chunk = list(payload[i : i + N])
        beats.append(
            (
                chunk + [0] * (N - len(chunk)),
                [1] * len(chunk) + [0] * (N - len(chunk)),
                1 if i + N >= len(payload) else 0,
            )
        )
    return beats


def _rx(top, mod, beats, cycles=60):
    """Feed AXIS beats in; return (recovered values as bytes, runt pulses)."""
    sim_reset()
    got = []
    runts = 0
    bi = 0
    for _ in range(cycles):
        inp = (
            _in_beat(mod, *beats[bi])
            if bi < len(beats)
            else _in_beat(mod, [0] * N, [0] * N, 0, valid=0)
        )
        r = sim_call(top, inp, mod.out_fb_t(ready=1))
        runts += int(r.runt)
        if int(r.stream_out_if.stream.valid):
            got.append(type_to_bytes(mod.t, r.stream_out_if.stream.data.frag))
        if bi < len(beats) and int(r.axis_in_if.ready):
            bi += 1
    return got, runts


def _tx(top, mod, values, cycles=60):
    """Feed values in; return the emitted (data, keep, eod) beats."""
    frag_t = mod.in_intrf.stream_t.typeof("data")

    def word(v, valid=1, eod=0):
        return mod.in_intrf.fwd_t(
            mod.in_intrf.stream_t(data=frag_t(frag=v, eod=[eod]), valid=valid)
        )

    sim_reset()
    vi = 0
    beats = []
    for _ in range(cycles):
        inp = word(*values[vi]) if vi < len(values) else word(values[0][0], valid=0)
        r = sim_call(top, inp, mod.axis_fb_t(ready=1))
        if vi < len(values) and int(r.stream_in_if.ready):
            vi += 1
        s = r.axis_out_if.stream
        if int(s.valid):
            beats.append(
                (
                    [int(d) for d in s.data.frag.data],
                    [int(k) for k in s.data.frag.keep],
                    int(s.data.eod[0]),
                )
            )
    return beats


def _wire(beats):
    return bytes(d for (dat, keep, _) in beats for d, k in zip(dat, keep) if k)


HDR = hdr_t(version=0xAB, length=0x1234, flags=0xDEADBEEF)
PTS = [pt_t(x=i, y=0x1000 + i) for i in (1, 2, 3)]


# ── (a) one struct per packet, size-limited ───


def test_one_per_packet_exact_frame():
    got, runts = _rx(rx_one_main, rx_one, _frame(type_to_bytes(hdr_t, HDR)))
    assert got == [type_to_bytes(hdr_t, HDR)], got
    assert runts == 0
    print("test_one_per_packet_exact_frame PASS")


def test_one_per_packet_drops_ethernet_style_padding():
    """THE reason the limiter exists, and a REGRESSION for axis.h:527's
    underflow. A 7-byte struct arriving in a 16-byte padded frame must decode
    to exactly one value -- the padding dropped, not decoded as a second."""
    padded = list(type_to_bytes(hdr_t, HDR)) + [0xFF] * 9
    got, _ = _rx(rx_one_main, rx_one, _frame(padded))
    assert got == [type_to_bytes(hdr_t, HDR)], got
    print("test_one_per_packet_drops_ethernet_style_padding PASS")


def test_one_per_packet_back_to_back_frames_stay_aligned():
    """Two padded frames in a row: the limiter must re-arm per frame, so both
    decode identically and nothing drifts."""
    padded = list(type_to_bytes(hdr_t, HDR)) + [0xFF] * 9
    got, _ = _rx(rx_one_main, rx_one, _frame(padded) + _frame(padded), cycles=90)
    assert got == [type_to_bytes(hdr_t, HDR)] * 2, got
    print("test_one_per_packet_back_to_back_frames_stay_aligned PASS")


def test_tx_one_per_packet_tlast_and_partial_keep():
    """REGRESSION for axis.h:650 (tkeep hardcoded all-ones) and axis.h:653
    (tlast unqualified). Each value gets its own frame, ending in a beat whose
    keep is the real remaining byte count."""
    beats = _tx(tx_one_main, tx_one, [(HDR,)])
    assert _wire(beats) == type_to_bytes(hdr_t, HDR)
    assert sum(beats[-1][1]) == byte_length(hdr_t) % N == 3, beats[-1]
    eods = [e for (_, _, e) in beats]
    assert sum(eods) == 1 and eods[-1] == 1, eods
    print("test_tx_one_per_packet_tlast_and_partial_keep PASS")


def test_tx_one_per_packet_frames_each_value():
    beats = _tx(tx_one_main, tx_one, [(HDR,), (HDR,)], cycles=90)
    eods = [e for (_, _, e) in beats]
    assert sum(eods) == 2, eods  # one frame per value
    print("test_tx_one_per_packet_frames_each_value PASS")


def test_axis_round_trip_one_per_packet():
    beats = _tx(tx_one_main, tx_one, [(HDR,)])
    got, _ = _rx(rx_one_main, rx_one, beats)
    assert got == [type_to_bytes(hdr_t, HDR)], got
    print("test_axis_round_trip_one_per_packet PASS")


# ── (b) many structs per packet ───────────────


def test_many_per_packet_tx_one_frame():
    """The mode old axis_to_type was meant to be, shipped `#if 0`'d
    (axis.h:598) because of a stale signature. Three 3-byte values -> one
    9-byte frame, boundaries straddling beats, tlast only at the end."""
    beats = _tx(tx_many_main, tx_many, [(v,) for v in PTS])
    assert _wire(beats) == b"".join(type_to_bytes(pt_t, v) for v in PTS)
    eods = [e for (_, _, e) in beats]
    assert sum(eods) == 1 and eods[-1] == 1, eods
    print("test_many_per_packet_tx_one_frame PASS")


def test_many_per_packet_rx_splits_frame():
    payload = b"".join(type_to_bytes(pt_t, v) for v in PTS)
    got, runts = _rx(rx_many_main, rx_many, _frame(payload))
    assert got == [type_to_bytes(pt_t, v) for v in PTS], got
    assert runts == 0
    print("test_many_per_packet_rx_splits_frame PASS")


def test_many_per_packet_round_trip():
    beats = _tx(tx_many_main, tx_many, [(v,) for v in PTS])
    got, _ = _rx(rx_many_main, rx_many, beats)
    assert got == [type_to_bytes(pt_t, v) for v in PTS], got
    print("test_many_per_packet_round_trip PASS")


def test_structs_per_packet_counter_frames_every_k():
    """structs_per_packet=3: two frames' worth of values must produce exactly
    two tlasts, without the caller driving eod at all."""
    beats = _tx(tx_many_main, tx_many, [(v,) for v in PTS * 2], cycles=120)
    eods = [e for (_, _, e) in beats]
    assert sum(eods) == 2, eods
    print("test_structs_per_packet_counter_frames_every_k PASS")


# ── (c) runt / short-packet recovery ──────────


def test_runt_then_good_frame_resyncs():
    """REGRESSION for axis.h:561-595: old axis_packet_to_type never flushed the
    deserializer on tlast, so one short frame permanently desynced the value
    boundary. The good frame after a runt must decode correctly, and .runt must
    pulse exactly once."""
    payload = b"".join(type_to_bytes(pt_t, v) for v in PTS)
    runt = [([9, 9, 0, 0], [1, 1, 0, 0], 1)]  # 2 bytes, then eod; pt_t needs 3
    got, runts = _rx(rx_many_main, rx_many, runt + _frame(payload), cycles=90)
    assert got == [type_to_bytes(pt_t, v) for v in PTS], got
    assert runts == 1, runts
    print("test_runt_then_good_frame_resyncs PASS")


def test_runt_zero_pad_emits_padded_value():
    runt = [([9, 9, 0, 0], [1, 1, 0, 0], 1)]
    got, runts = _rx(rx_pad_main, rx_pad, runt)
    assert got == [bytes([9, 9, 0])], got  # zero-filled to 3 bytes
    assert runts == 1, runts
    print("test_runt_zero_pad_emits_padded_value PASS")


def test_runt_ignore_reproduces_old_desync():
    """Documents what this library deliberately no longer does by default."""
    payload = b"".join(type_to_bytes(pt_t, v) for v in PTS)
    runt = [([9, 9, 0, 0], [1, 1, 0, 0], 1)]
    got, _ = _rx(rx_ignore_main, rx_ignore, runt + _frame(payload), cycles=90)
    good = [type_to_bytes(pt_t, v) for v in PTS]
    assert got != good, "on_runt='ignore' should desync, that is the point"
    assert got[0] == bytes([9, 9]) + good[0][:1], got[0]
    print("test_runt_ignore_reproduces_old_desync PASS")


# ── (d) tkeep-aware partial beats ─────────────


def test_rx_consumes_partial_keep_beat():
    """REGRESSION for axis.h:587, which ignored tkeep for data and shifted all
    bus bytes in regardless. A frame whose last beat is partial must contribute
    only its kept bytes."""
    payload = b"".join(type_to_bytes(pt_t, v) for v in PTS)  # 9 bytes -> last beat keeps 1
    beats = _frame(payload)
    assert sum(beats[-1][1]) == 1, beats[-1]
    got, _ = _rx(rx_many_main, rx_many, beats)
    assert got == [type_to_bytes(pt_t, v) for v in PTS], got
    print("test_rx_consumes_partial_keep_beat PASS")


def test_tx_produces_contiguous_prefix_keep():
    """Every emitted beat must be Xilinx-style: full keep unless it carries
    eod, and a contiguous prefix even then."""
    for beats in (
        _tx(tx_one_main, tx_one, [(HDR,)]),
        _tx(tx_many_main, tx_many, [(v,) for v in PTS]),
    ):
        for data, keep, eod in beats:
            popcount = sum(keep)
            assert popcount == N or eod, (data, keep, eod)
            assert keep == [1] * popcount + [0] * (N - popcount), keep
    print("test_tx_produces_contiguous_prefix_keep PASS")


def test_bad_options_rejected():
    try:
        make_axis_to_type(hdr_t, N, frame="sometimes")
        raise AssertionError("expected ValueError for a bad frame mode")
    except ValueError:
        pass
    try:
        make_type_to_axis(hdr_t, N, structs_per_packet=3)
        raise AssertionError("expected ValueError: structs_per_packet needs many_per_packet")
    except ValueError as e:
        assert "many_per_packet" in str(e), str(e)
    try:
        make_type_to_axis(hdr_t, N, frame="many_per_packet", structs_per_packet=0)
        raise AssertionError("expected ValueError for structs_per_packet=0")
    except ValueError:
        pass
    print("test_bad_options_rejected PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
