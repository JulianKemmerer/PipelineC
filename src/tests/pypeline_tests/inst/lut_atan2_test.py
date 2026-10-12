# pyright: reportInvalidTypeForm=none
"""Independent numeric oracle, cycle contract, and native/GHDL ROM atan2 parity."""

import math
import random
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
import pypeline as py
from pypeline import (
    MAIN,
    Reg,
    param,
    make_int_t,
    uint16_t,
    uint1_t,
    sim_assert,
    sim_print,
    sim_finish,
)
from dsp.lut_atan2 import make_lut_atan2, golden_lut_atan2
from AUTO_PIPELINE import RamPlan

W = param("ATAN2_TEST_INPUT_WIDTH", 39)
input_t = make_int_t(W)
block, _out_t = make_lut_atan2(input_t)
RL = param("ATAN2_TEST_RECIP_LATENCY", type=int)
AL = param("ATAN2_TEST_ANGLE_LATENCY", type=int)
if RL is not None and AL is not None:
    plans = py.AUTO_PIPELINE_RAM_PLAN_CACHE()
    plans.update(
        {
            block.reciprocal_rom._auto_pipeline_ram["key"]: RamPlan(1, RL - 2)
            if RL > 2
            else RamPlan(0, RL - 1),
            block.angle_rom._auto_pipeline_ram["key"]: RamPlan(1, AL - 2)
            if AL > 2
            else RamPlan(0, AL - 1),
        }
    )
    py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(plans)
    block, _out_t = make_lut_atan2(input_t)
rng = random.Random(718)
MIN, MAX = -(1 << (W - 1)), (1 << (W - 1)) - 1
VECTORS = [
    (0, 0),
    (0, 1),
    (1, 0),
    (-1, 0),
    (0, -1),
    (-1, -1),
    (1, -1),
    (MIN, MIN),
    (MIN, 0),
    (MIN, 1),
    (1, MIN),
    (MIN, MAX),
    (MAX, MIN),
]
VECTORS += [
    (rng.randrange(MIN, MAX + 1), rng.randrange(MIN, MAX + 1))
    for _ in range(64 - len(VECTORS))
]
XS, YS = tuple(x for x, y in VECTORS), tuple(y for x, y in VECTORS)
EXPECTED = tuple(golden_lut_atan2(block, x, y)[0] for x, y in VECTORS)
DEGENERATE = tuple(int(x == 0 and y == 0) for x, y in VECTORS)
COUNT = len(VECTORS)


@MAIN(125.0)
def lut_atan2_check() -> uint16_t:
    xs: input_t[COUNT] = XS
    ys: input_t[COUNT] = YS
    expected_angles: input_t[COUNT] = EXPECTED
    degenerate: uint1_t[COUNT] = DEGENERATE
    tick: Reg[uint16_t]
    sent: Reg[uint16_t]
    received: Reg[uint16_t]
    last: Reg[uint16_t]
    if (tick & 3) != 1:
        index: uint16_t = sent & 63
        x: input_t = xs[index]
        y: input_t = ys[index]
        valid: uint1_t = sent < COUNT
        result = block(x, y, valid, 0)
        if result.valid:
            expected: input_t = expected_angles[received & 63]
            degen: uint1_t = degenerate[received & 63]
            sim_assert(result.angle == expected, "ROM atan2 data/CE alignment")
            sim_assert(result.degenerate == degen, "ROM atan2 zero vector")
            last = result.angle
            sim_print(f"atan {last}", debug=True)
            received += 1
        sent += 1
    if tick == 180:
        sim_assert(received == COUNT, "ROM atan2 response count")
        sim_finish()
    tick += 1
    return last


def test_numeric_accuracy():
    pairs = [(x, y) for x in range(-127, 128) for y in range(-127, 128)]
    rng = random.Random(4242)
    for _ in range(40000):
        w = rng.randrange(3, W + 1)
        pairs.append(
            (
                rng.randrange(-(1 << (w - 1)), 1 << (w - 1)),
                rng.randrange(-(1 << (w - 1)), 1 << (w - 1)),
            )
        )
    # Both sides of every reciprocal and angle bin, at weak and strong scales.
    for i in range(4096):
        for delta in (-1, 0, 1):
            pairs += [(65536 + 16 * i + delta, 32767), (65536, 16 * i + delta)]
    pairs += [(MIN, y) for y in (MIN, -1, 0, 1, MAX)]
    worst = 0.0
    for x, y in pairs:
        value, degen = golden_lut_atan2(block, x, y)
        assert degen == int(x == 0 and y == 0)
        if not degen:
            error = abs(
                (value / 65536 - math.atan2(y, x) / (2 * math.pi) + 0.5) % 1 - 0.5
            )
            worst = max(worst, error)
            assert error < 6e-5, (x, y, error)
    print(f"ROM atan2 {len(pairs)} vectors: worst {worst:.8g} turns")


def check_pipeline(unit, vectors=VECTORS, bubbles=True):
    py.sim_reset()
    pending = deque()
    for cycle in range(len(vectors) + unit.get_latency() + 4):
        active = cycle < len(vectors) and (not bubbles or cycle % 5 != 2)
        x, y = vectors[cycle] if cycle < len(vectors) else (0, 0)
        pending.append((active, golden_lut_atan2(unit, x, y)))
        result = py.sim_call(unit, x, y, int(active), 0)
        if cycle >= unit.get_latency():
            valid, expected = pending.popleft()
            assert bool(result.valid) == valid, (cycle, unit.get_latency())
            if valid:
                assert (int(result.angle), int(result.degenerate)) == expected, (
                    cycle,
                    x,
                    y,
                    result,
                    expected,
                )


def test_scale_and_corner_pipeline():
    vectors = [(x, y) for x in range(-8, 9) for y in range(-8, 9)]
    for x, y in ((3, 5), (-3, 5), (3, -5), (-3, -5), (511, 512), (65536, 65535)):
        for shift in range(W - max(abs(x), abs(y)).bit_length()):
            a, b = x << shift, y << shift
            value, _ = golden_lut_atan2(block, a, b)
            error = abs(
                (value / 65536 - math.atan2(b, a) / (2 * math.pi) + 0.5) % 1 - 0.5
            )
            assert error < 6e-5, (a, b, error)
            vectors.append((a, b))
    vectors += [(MIN, y) for y in (MIN, -1, 0, 1, MAX)]
    check_pipeline(block, vectors, bubbles=False)


def test_pipeline_and_selected_plans():
    check_pipeline(block)
    saved = py.AUTO_PIPELINE_RAM_PLAN_CACHE()
    try:
        for rlat, alat in ((3, 1), (1, 3), (3, 2)):
            py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(
                {
                    block.reciprocal_rom._auto_pipeline_ram["key"]: RamPlan(1, rlat - 2)
                    if rlat > 1
                    else RamPlan(),
                    block.angle_rom._auto_pipeline_ram["key"]: RamPlan(1, alat - 2)
                    if alat > 2
                    else RamPlan(0, alat - 1),
                }
            )
            unit, _ = make_lut_atan2(input_t)
            assert unit.get_latency() == rlat + alat + 12
            check_pipeline(unit)
    finally:
        py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(saved)


def test_table_boundaries_pipeline():
    # Exercise actual normalization, ROM addressing and multiplication on
    # both sides of every bin boundary, as a continuous enabled-clock stream.
    vectors = []
    for i in range(4096):
        for delta in (-1, 0, 1):
            vectors.extend(((65536 + 16 * i + delta, 32767), (65536, 16 * i + delta)))
    check_pipeline(block, vectors, bubbles=False)


def test_pdw_width_pipeline():
    unit, _ = make_lut_atan2(make_int_t(40))
    rng = random.Random(4040)
    low, high = -(1 << 39), (1 << 39) - 1
    vectors = [(low, y) for y in (low, -1, 0, 1, high)]
    vectors.extend(
        (rng.randrange(low, high + 1), rng.randrange(low, high + 1)) for _ in range(512)
    )
    for x, y in vectors:
        value, _ = golden_lut_atan2(unit, x, y)
        error = abs((value / 65536 - math.atan2(y, x) / (2 * math.pi) + 0.5) % 1 - 0.5)
        assert error < 6e-5, (x, y, error)
    check_pipeline(unit, vectors, bubbles=False)


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
