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
from pypeline import MAIN, sim_call, sim_reset, uint1_t, uint8_t

from axi.axis import (
    make_split_to_chunks,
    make_assemble_chunks,
    make_dwidth_widen,
    make_dwidth_narrow,
    _make_dwidth_types,
)

N = 4  # narrow_n (elements per narrow beat)
RATIO = 4  # wide_n = N * RATIO = 16

(
    narrow_bus_t,
    wide_bus_t,
    narrow_frag_t,
    wide_frag_t,
    narrow_axis_t,
    wide_axis_t,
) = _make_dwidth_types(uint8_t, N, RATIO)

chunks_t = narrow_axis_t[RATIO]

split_to_chunks = make_split_to_chunks(N, RATIO, narrow_axis_t, wide_frag_t)
assemble_chunks = make_assemble_chunks(N, RATIO, narrow_axis_t, wide_frag_t)
dwidth_widen, _narrow_axis_t_w, _wide_axis_t_w = make_dwidth_widen(uint8_t, N, RATIO)
dwidth_narrow, _wide_axis_t_n, _narrow_axis_t_n = make_dwidth_narrow(uint8_t, N, RATIO)

# dwidth_widen/dwidth_narrow return an internal result struct type built inside their
# factory (not exposed by make_dwidth_widen/make_dwidth_narrow's return tuple) — pull it
# from the already-decorated function's own return annotation instead of re-deriving it.
dwidth_widen_result_t = dwidth_widen.__annotations__["return"]
dwidth_narrow_result_t = dwidth_narrow.__annotations__["return"]

# Top-level entry points so `pipelinec --comb` elaborates/synthesizes the same hardware
# functions exercised below, mirroring axis_test.py/multi_cycle_test.py. MAIN(...) only
# works as a decorator on a function def — wrap each call instead of calling it directly.


@MAIN
def split_to_chunks_main(wide: wide_frag_t) -> chunks_t:
    return split_to_chunks(wide)


@MAIN
def assemble_chunks_main(chunks: chunks_t) -> wide_frag_t:
    return assemble_chunks(chunks)


@MAIN
def dwidth_widen_main(
    narrow_in: narrow_axis_t, wide_out_ready: uint1_t
) -> dwidth_widen_result_t:
    return dwidth_widen(narrow_in, wide_out_ready)


@MAIN
def dwidth_narrow_main(
    wide_in: wide_axis_t, narrow_out_ready: uint1_t
) -> dwidth_narrow_result_t:
    return dwidth_narrow(wide_in, narrow_out_ready)


def mk_narrow(data, keep, eod0, valid):
    return narrow_axis_t(
        data=narrow_frag_t(frag=narrow_bus_t(data=data, keep=keep), eod=[eod0]),
        valid=valid,
    )


def mk_wide(data, keep, eod0, valid):
    return wide_axis_t(
        data=wide_frag_t(frag=wide_bus_t(data=data, keep=keep), eod=[eod0]),
        valid=valid,
    )


def test_split_assemble_round_trip():
    wide_in = wide_frag_t(frag=wide_bus_t(data=list(range(16)), keep=[1] * 16), eod=[1])
    chunks = sim_call(split_to_chunks, wide_in)
    assert [int(c.valid) for c in chunks] == [1, 1, 1, 1]
    assert [int(c.data.eod[0]) for c in chunks] == [0, 0, 0, 1]
    assert list(chunks[0].data.frag.data) == [0, 1, 2, 3]
    assert list(chunks[3].data.frag.data) == [12, 13, 14, 15]

    wide_out = sim_call(assemble_chunks, chunks)
    assert list(wide_out.frag.data) == list(range(16))
    assert list(wide_out.frag.keep) == [1] * 16
    assert int(wide_out.eod[0]) == 1
    print("test_split_assemble_round_trip PASSED")


def test_widen_full_beats():
    """4 fully-kept narrow beats, eod[0] only on the 4th -> exactly one full wide beat."""
    sim_reset()
    for i in range(4):
        nin = mk_narrow(
            data=[i * N + b for b in range(N)],
            keep=[1] * N,
            eod0=1 if i == 3 else 0,
            valid=1,
        )
        r = sim_call(dwidth_widen, nin, 1)
        assert int(r.narrow_in_ready) == 1, f"expected ready to accept beat {i}"
        assert (
            int(r.wide_out.valid) == 0
        ), f"unexpected wide_out before accumulation done (i={i})"

    idle = mk_narrow(data=[0] * N, keep=[0] * N, eod0=0, valid=0)
    r = sim_call(
        dwidth_widen, idle, 1
    )  # one extra cycle for the 4th beat to incorporate
    assert int(r.wide_out.valid) == 0

    r = sim_call(dwidth_widen, idle, 1)
    assert int(r.wide_out.valid) == 1
    assert list(r.wide_out.data.frag.data) == list(range(16))
    assert list(r.wide_out.data.frag.keep) == [1] * 16
    assert int(r.wide_out.data.eod[0]) == 1
    print("test_widen_full_beats PASSED")


def test_widen_partial_final_beat():
    """Only 2 narrow beats before eod[0], 2nd one partially kept -> realigned/right-justified
    wide output covering just those 2 beats worth of data."""
    sim_reset()
    nin0 = mk_narrow(data=[10, 11, 12, 13], keep=[1, 1, 1, 1], eod0=0, valid=1)
    r = sim_call(dwidth_widen, nin0, 1)
    assert int(r.narrow_in_ready) == 1

    nin1 = mk_narrow(data=[20, 21, 0, 0], keep=[1, 1, 0, 0], eod0=1, valid=1)
    r = sim_call(dwidth_widen, nin1, 1)
    assert int(r.narrow_in_ready) == 1
    assert int(r.wide_out.valid) == 0

    idle = mk_narrow(data=[0] * N, keep=[0] * N, eod0=0, valid=0)
    r = sim_call(
        dwidth_widen, idle, 1
    )  # one extra cycle for the 2nd beat to incorporate
    assert int(r.wide_out.valid) == 0

    r = sim_call(dwidth_widen, idle, 1)
    assert int(r.wide_out.valid) == 1, "expected the short packet to flush out"
    assert list(r.wide_out.data.frag.data) == [10, 11, 12, 13, 20, 21, 0, 0] + [0] * 8
    assert list(r.wide_out.data.frag.keep) == [1, 1, 1, 1, 1, 1, 0, 0] + [0] * 8
    assert int(r.wide_out.data.eod[0]) == 1
    print("test_widen_partial_final_beat PASSED")


def test_widen_back_to_back_packets():
    """8 full narrow beats spanning 2 wide outputs, eod[0] only on the very last (8th) beat ->
    first wide beat eod[0]=0, second wide beat eod[0]=1."""
    sim_reset()
    idle = mk_narrow(data=[0] * N, keep=[0] * N, eod0=0, valid=0)
    wide_outs = []
    for i in range(8):
        nin = mk_narrow(
            data=[i * N + b for b in range(N)],
            keep=[1] * N,
            eod0=1 if i == 7 else 0,
            valid=1,
        )
        r = sim_call(dwidth_widen, nin, 1)
        if r.wide_out.valid:
            wide_outs.append(r.wide_out)
    for _ in range(2):
        r = sim_call(dwidth_widen, idle, 1)
        if r.wide_out.valid:
            wide_outs.append(r.wide_out)

    assert len(wide_outs) == 2, f"expected 2 wide beats out, got {len(wide_outs)}"
    assert list(wide_outs[0].data.frag.data) == list(range(16))
    assert int(wide_outs[0].data.eod[0]) == 0
    assert list(wide_outs[1].data.frag.data) == list(range(16, 32))
    assert int(wide_outs[1].data.eod[0]) == 1
    print("test_widen_back_to_back_packets PASSED")


def test_narrow_full_beat_drain():
    """One fully-kept wide beat with eod[0]=1 -> drains into 4 narrow beats, eod[0] only on
    the last (highest-address) one drained."""
    sim_reset()
    win = mk_wide(data=list(range(16)), keep=[1] * 16, eod0=1, valid=1)
    win_idle = mk_wide(data=[0] * 16, keep=[0] * 16, eod0=0, valid=0)

    r = sim_call(dwidth_narrow, win, 1)
    assert int(r.wide_in_ready) == 1

    drained = []
    for _ in range(5):
        r = sim_call(dwidth_narrow, win_idle, 1)
        if r.narrow_out.valid:
            drained.append(
                (list(r.narrow_out.data.frag.data), int(r.narrow_out.data.eod[0]))
            )

    assert len(drained) == 4, f"expected 4 narrow beats drained, got {len(drained)}"
    assert drained[0][0] == [0, 1, 2, 3]
    assert drained[1][0] == [4, 5, 6, 7]
    assert drained[2][0] == [8, 9, 10, 11]
    assert drained[3][0] == [12, 13, 14, 15]
    assert [d[1] for d in drained] == [
        0,
        0,
        0,
        1,
    ], "eod[0] should land only on the last chunk"
    print("test_narrow_full_beat_drain PASSED")


def test_widen_narrow_round_trip():
    """narrow -> dwidth_widen -> dwidth_narrow -> narrow reproduces the original stream."""
    sim_reset()
    idle_n = mk_narrow(data=[0] * N, keep=[0] * N, eod0=0, valid=0)
    idle_w = mk_wide(data=[0] * 16, keep=[0] * 16, eod0=0, valid=0)

    original = [
        mk_narrow(
            data=[i * N + b for b in range(N)],
            keep=[1] * N,
            eod0=1 if i == 3 else 0,
            valid=1,
        )
        for i in range(4)
    ]

    wide_outs = []
    for nin in original:
        r = sim_call(dwidth_widen, nin, 1)
        if r.wide_out.valid:
            wide_outs.append(r.wide_out)
    for _ in range(2):
        r = sim_call(dwidth_widen, idle_n, 1)
        if r.wide_out.valid:
            wide_outs.append(r.wide_out)
    assert len(wide_outs) == 1

    drained = []
    win = wide_outs[0]
    r = sim_call(dwidth_narrow, win, 1)
    if r.narrow_out.valid:
        drained.append(r.narrow_out)
    for _ in range(5):
        r = sim_call(dwidth_narrow, idle_w, 1)
        if r.narrow_out.valid:
            drained.append(r.narrow_out)

    assert len(drained) == 4
    for orig, got in zip(original, drained):
        assert list(got.data.frag.data) == list(orig.data.frag.data)
        assert list(got.data.frag.keep) == list(orig.data.frag.keep)
        assert int(got.data.eod[0]) == int(orig.data.eod[0])
    print("test_widen_narrow_round_trip PASSED")


if __name__ == "__main__":
    test_split_assemble_round_trip()
    test_widen_full_beats()
    test_widen_partial_final_beat()
    test_widen_back_to_back_packets()
    test_narrow_full_beat_drain()
    test_widen_narrow_round_trip()
    print("ALL dwidth_converter_test TESTS PASSED")
