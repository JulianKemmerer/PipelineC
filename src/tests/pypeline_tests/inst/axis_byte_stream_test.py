# pyright: reportInvalidTypeForm=none
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
from pypeline import MAIN, Feedback, sim_call, sim_reset, uint1_t, uint8_t, uint32_t, hw_return_type

from axi.axis import make_axis_interface, make_axis_byte_source, make_axis_byte_sink
from axi.axis_sim import AxisSimSource, AxisSimSink, Scoreboard

N = 4  # lanes per beat
MAX_BYTES = 32

axis_intrf = make_axis_interface(N)
byte_source, byte_source_t = make_axis_byte_source(axis_intrf, N, MAX_BYTES)
byte_sink, byte_sink_t = make_axis_byte_sink(axis_intrf, N, MAX_BYTES)

buf_t = uint8_t[MAX_BYTES]


# Top-level entry points so `pypelinec --comb` elaborates/synthesizes the same
# hardware functions exercised below, mirroring dwidth_converter_test.py.
@MAIN
def byte_source_main(
    load: uint1_t, load_data: buf_t, load_len: uint32_t, stream_out_if: axis_intrf.fb_t
) -> byte_source_t:
    return byte_source(load, load_data, load_len, stream_out_if)


@MAIN
def byte_sink_main(stream_in_if: axis_intrf.fwd_t) -> byte_sink_t:
    return byte_sink(stream_in_if)


def _round_trip_hw(frame_bytes):
    """Drive byte_source -> byte_sink via sim_call, cycle by cycle, returning
    the collected frame once byte_sink signals frame_valid."""
    sim_reset()
    frame_len = len(frame_bytes)
    load_data = list(frame_bytes) + [0] * (MAX_BYTES - frame_len)
    sink_ready = axis_intrf.fb_t(ready=1)
    got = None
    for cycle in range(50):
        load = 1 if cycle == 0 else 0
        src = sim_call(byte_source, load, load_data, frame_len, sink_ready)
        snk = sim_call(byte_sink, src.stream_out_if)
        sink_ready = snk.stream_in_if
        if snk.frame_valid:
            got = list(snk.frame_data[:frame_len])
            break
    assert got is not None, "byte_sink never signaled frame_valid"
    assert got == list(frame_bytes), (got, list(frame_bytes))


def test_hw_round_trip_full_beats():
    """Frame length is an exact multiple of the lane width."""
    _round_trip_hw(bytes(range(1, N * 3 + 1)))
    print("test_hw_round_trip_full_beats PASSED")


def test_hw_round_trip_partial_final_beat():
    """Frame length is NOT a multiple of the lane width -- exercises
    partial-keep on the last beat."""
    _round_trip_hw(bytes(range(1, N * 2 + 3)))
    print("test_hw_round_trip_partial_final_beat PASSED")


def _make_stream(data, keep, eod, valid=1):
    """Hand-craft an axis_intrf.fwd_t word with arbitrary data/keep/eod --
    bypassing byte_source, whose own derivation can't produce a non-compliant
    beat -- so the compliance-check tests below can drive one directly."""
    frag_t = axis_intrf.stream_t.typeof("data")
    bus_t = frag_t.typeof("frag")
    return axis_intrf.fwd_t(
        axis_intrf.stream_t(
            data=frag_t(frag=bus_t(data=data, keep=keep), eod=[eod]),
            valid=valid,
        )
    )


def test_hw_sink_rejects_mid_packet_hole():
    """byte_sink's Xilinx-style compliance check (wireguard-fpga issue #44):
    a partial-keep beat that does NOT carry eod (an embedded null byte mid
    packet) must raise via sim_assert."""
    sim_reset()
    word = _make_stream(data=[1, 2, 0, 0], keep=[1, 1, 0, 0], eod=0)
    try:
        sim_call(byte_sink, word)
    except AssertionError:
        print("test_hw_sink_rejects_mid_packet_hole PASSED")
        return
    raise AssertionError("byte_sink accepted a mid-packet tkeep hole without raising")


def test_hw_sink_rejects_non_prefix_keep():
    """Even on the eod beat, a non-contiguous keep pattern (a hole before the
    last kept lane) must raise -- Xilinx-style tkeep is always a prefix."""
    sim_reset()
    word = _make_stream(data=[1, 0, 3, 4], keep=[1, 0, 1, 1], eod=1)
    try:
        sim_call(byte_sink, word)
    except AssertionError:
        print("test_hw_sink_rejects_non_prefix_keep PASSED")
        return
    raise AssertionError("byte_sink accepted a non-prefix tkeep pattern without raising")


def test_sim_source_sink_round_trip():
    """Plain-Python AxisSimSource/AxisSimSink, no hardware involved."""
    src = AxisSimSource(axis_intrf, N)
    snk = AxisSimSink(axis_intrf, N)
    frame = bytes(range(1, N * 2 + 3))  # not a multiple of N
    src.send(frame)

    got = None
    for _ in range(20):
        word = src.step(True)
        snk.step(word)
        f = snk.recv_nowait()
        if f is not None:
            got = f
            break
    assert got == frame, (got, frame)
    print("test_sim_source_sink_round_trip PASSED")


def test_sim_sink_rejects_mid_packet_hole():
    """AxisSimSink's Xilinx-style compliance check -- the plain-Python mirror
    of test_hw_sink_rejects_mid_packet_hole."""
    snk = AxisSimSink(axis_intrf, N)
    word = _make_stream(data=[1, 2, 0, 0], keep=[1, 1, 0, 0], eod=0)
    try:
        snk.step(word)
    except AssertionError:
        print("test_sim_sink_rejects_mid_packet_hole PASSED")
        return
    raise AssertionError("AxisSimSink accepted a mid-packet tkeep hole without raising")


def test_sim_source_pause_generator():
    """set_pause_generator holds the emitted word at valid=0 for the
    generator's truthy entries, without losing/corrupting the frame."""
    src = AxisSimSource(axis_intrf, N)
    snk = AxisSimSink(axis_intrf, N)
    frame = bytes(range(1, N + 1))
    src.send(frame)
    src.set_pause_generator([1, 1, 0, 0, 0, 0, 0, 0])

    valids = []
    got = None
    for _ in range(20):
        word = src.step(True)
        valids.append(bool(word.stream.valid))
        snk.step(word)
        f = snk.recv_nowait()
        if f is not None:
            got = f
            break
    assert valids[0] is False and valids[1] is False, valids
    assert got == frame, (got, frame)
    print("test_sim_source_pause_generator PASSED")


def test_scoreboard_pass_and_fail():
    """Scoreboard.expect()/check() -- direct API, no AXIS involved."""
    sb = Scoreboard()
    sb.expect(b"abc", idx=0)
    sb.expect(b"def", idx=1, tag="second")

    r0 = sb.check(b"abc")
    assert r0["passed"] and r0["idx"] == 0 and r0["expected"] == b"abc"

    r1 = sb.check(b"xyz")  # wrong value for the queued b"def"
    assert not r1["passed"] and r1["idx"] == 1 and r1["tag"] == "second"
    assert r1["expected"] == b"def" and r1["got"] == b"xyz"

    r2 = sb.check(b"anything")  # nothing left queued
    assert not r2["passed"] and "error" in r2
    print("test_scoreboard_pass_and_fail PASSED")


def test_axis_sim_sink_check_nowait():
    """AxisSimSink(scoreboard=...) -- check_nowait() combines recv + check."""
    sb = Scoreboard()
    src = AxisSimSource(axis_intrf, N)
    snk = AxisSimSink(axis_intrf, N, scoreboard=sb)

    good = bytes(range(1, N + 3))
    bad = bytes(range(1, N + 2))  # one byte short of what's expected
    src.send(good)
    sb.expect(good, idx=0)
    src.send(bad)
    sb.expect(bytes(range(1, N + 3)), idx=1)  # expect the wrong (longer) value

    results = []
    for _ in range(30):
        word = src.step(True)
        snk.step(word)
        r = snk.check_nowait()
        if r is not None:
            results.append(r)
        if len(results) == 2:
            break

    assert results[0]["passed"] and results[0]["idx"] == 0
    assert not results[1]["passed"] and results[1]["idx"] == 1
    print("test_axis_sim_sink_check_nowait PASSED")


if __name__ == "__main__":
    test_hw_round_trip_full_beats()
    test_hw_round_trip_partial_final_beat()
    test_hw_sink_rejects_mid_packet_hole()
    test_hw_sink_rejects_non_prefix_keep()
    test_sim_source_sink_round_trip()
    test_sim_sink_rejects_mid_packet_hole()
    test_sim_source_pause_generator()
    test_scoreboard_pass_and_fail()
    test_axis_sim_sink_check_nowait()
    print("ALL axis_byte_stream_test TESTS PASSED")
