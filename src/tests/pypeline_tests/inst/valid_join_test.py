# pyright: reportInvalidTypeForm=none
"""Independent arrivals, II=1, CE pauses, drain/reset and overflow for joins."""

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
import pypeline as py
from pypeline import MAIN, Reg, uint1_t, uint8_t, uint16_t, int32_t
from stream.valid_join import make_valid_join

join, _ = make_valid_join((uint16_t, int32_t, uint8_t))


@MAIN(125.0)
def valid_join_check() -> uint16_t:
    tick: Reg[uint16_t]
    sent0: Reg[uint16_t]
    sent1: Reg[uint16_t]
    sent2: Reg[uint16_t]
    received: Reg[uint16_t]
    rst: uint1_t = (tick >= 20) & (tick < 40)
    if (tick & 3) != 1:
        # The first epoch deliberately leaves branch 0 unmatched at reset.
        v0: uint1_t = ((tick < 20) | (tick >= 40)) & (sent0 < 40) & ((tick & 7) != 2)
        v1: uint1_t = (tick >= 47) & (sent1 < 40) & ((tick & 7) != 3)
        v2: uint1_t = (tick >= 41) & (sent2 < 40) & ((tick & 7) != 4)
        d0: uint16_t = sent0
        d1: int32_t = sent1
        d1 = -(d1 * 3)
        d2: uint8_t = sent2 ^ 81
        r = join(d0, v0, d1, v1, d2, v2, rst)
        py.sim_assert(~r.overflow, "join unexpectedly overflowed")
        py.sim_assert(~(rst & r.valid), "reset leaked a joined result")
        if r.valid:
            want1: int32_t = received
            want1 = -(want1 * 3)
            want2: uint8_t = received ^ 81
            py.sim_assert(r.p0 == received, "join branch 0/reset ordering")
            py.sim_assert(r.p1 == want1, "join branch 1 ordering")
            py.sim_assert(r.p2 == want2, "join branch 2 ordering")
            py.sim_print(f"joined {r.p0} {r.p1} {r.p2}", debug=True)
            received += 1
        if v0 & ~rst:
            sent0 += 1
        if v1:
            sent1 += 1
        if v2:
            sent2 += 1
    if rst:
        sent0 = 0
        sent1 = 0
        sent2 = 0
        received = 0
    if tick == 160:
        py.sim_assert(received == 40, "join response count")
        py.sim_finish()
    tick += 1
    return received


def test_independent_arrivals():
    py.sim_reset()
    rng = random.Random(793)
    arrivals = []
    for _ in range(3):
        when = 0
        branch = {}
        for i in range(150):
            when += rng.randrange(1, 4)
            branch[when] = i
        arrivals.append(branch)
    got = []
    for c in range(max(max(a) for a in arrivals) + 40):
        words = [a.get(c, 0) for a in arrivals]
        valids = [int(c in a) for a in arrivals]
        r = py.sim_call(
            join,
            words[0],
            valids[0],
            -3 * words[1],
            valids[1],
            words[2] ^ 81,
            valids[2],
            0,
        )
        assert not r.overflow
        if r.valid:
            got.append((int(r.p0), int(r.p1), int(r.p2)))
    assert got == [(i, -3 * i, i ^ 81) for i in range(150)], got


def test_one_result_per_clock():
    py.sim_reset()
    got, clocks = [], []
    for c in range(180):
        r = py.sim_call(
            join,
            c,
            int(c < 150),
            -(c - 7) * 3,
            int(7 <= c < 157),
            (c - 2) ^ 81,
            int(2 <= c < 152),
            0,
        )
        if r.valid:
            got.append((int(r.p0), int(r.p1), int(r.p2)))
            clocks.append(c)
    assert got == [(i, -3 * i, i ^ 81) for i in range(150)]
    assert clocks == list(range(clocks[0], clocks[0] + 150)), clocks


def test_overflow_is_detected():
    small, _ = make_valid_join((uint16_t, uint16_t), depth=2)
    py.sim_reset()
    try:
        for c in range(8):
            py.sim_call(small, c, 1, 0, 0, 0)
    except AssertionError as e:
        assert "unmatched-result FIFO overflow" in str(e)
    else:
        raise AssertionError("an unmatched full branch was silently overwritten")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
