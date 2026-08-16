"""Cycle-accurate checker for the exact final Divider VHDL artifact.

The benchmark driver supplies the reported end-to-end slice latency through
``DIVIDER_QOR_LATENCY`` and compiles a small scalar-port wrapper around the
generated record-port ``top``.  No source model is imported here: expected
quotient/remainder values come from Python integer arithmetic.
"""

import json
import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer


MASK32 = (1 << 32) - 1


def _golden(dividend, divisor):
    if divisor == 0:
        return MASK32, MASK32
    return dividend // divisor, dividend % divisor


def _vectors():
    edge = [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
        (MASK32, 0),
        (MASK32, 1),
        (MASK32, MASK32),
        (1, MASK32),
        (0x80000000, 2),
        (0x80000000, 0x7FFFFFFF),
        (0x7FFFFFFF, 0x80000000),
        (0xAAAAAAAA, 0x55555555),
        (0x55555555, 0xAAAAAAAA),
    ]
    for bit in range(32):
        value = 1 << bit
        edge.append((value, 1))
        edge.append((MASK32, value))
    rng = random.Random(0xD1A1DE2)
    count = int(os.environ.get("DIVIDER_QOR_RANDOM_VECTORS", "64"))
    return edge + [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(count)]


def _schedule():
    vectors = _vectors()
    schedule = []
    # Defined invalid values first make the later warm-up/flush checks useful.
    schedule.extend([(False, 0, 1), (False, MASK32, 0)])
    for i, pair in enumerate(vectors):
        # The first block is continuous-valid; the remainder contains regular
        # single- and double-cycle bubbles without reordering the transactions.
        if i >= 24 and i % 7 == 0:
            schedule.append((False, 0xDEADBEEF, 3))
        if i >= 24 and i % 19 == 0:
            schedule.append((False, 0x12345678, 0))
        schedule.append((True, pair[0], pair[1]))
    return schedule


def _resolved_int(signal):
    bits = str(signal.value).lower()
    if any(ch not in "01" for ch in bits):
        return None
    return int(signal.value)


@cocotb.test()
async def exact_final_vhdl_divider(dut):
    latency = int(os.environ["DIVIDER_QOR_LATENCY"])
    assert latency >= 0
    schedule = _schedule()
    expected_outputs = [
        (dividend, divisor, *_golden(dividend, divisor))
        for valid, dividend, divisor in schedule
        if valid
    ]

    dut.clk.value = 0
    dut.input_dividend.value = 0
    dut.input_divisor.value = 1
    dut.input_valid.value = 0
    await Timer(1, units="ns")
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start(start_high=False))

    seen = []
    flush = latency + 3
    for cycle in range(len(schedule) + flush):
        if cycle < len(schedule):
            valid, dividend, divisor = schedule[cycle]
        else:
            valid, dividend, divisor = False, 0, 1
        dut.input_valid.value = int(valid)
        dut.input_dividend.value = dividend
        dut.input_divisor.value = divisor

        await RisingEdge(dut.clk)
        await ReadOnly()

        ready = _resolved_int(dut.input_ready)
        assert ready == 1, f"input_ready={ready!r} at cycle {cycle}, expected 1"

        # With N inserted register slices, data driven before an edge is
        # observable after the Nth edge.  A zero-slice comb build is observable
        # at the first sampled edge as well.
        input_index = cycle if latency == 0 else cycle + 1 - latency
        if input_index < 0:
            await Timer(1, units="ps")
            continue  # uninitialized pipeline warm-up may legally be U/X
        expected_valid = (
            int(schedule[input_index][0]) if input_index < len(schedule) else 0
        )
        got_valid = _resolved_int(dut.output_valid)
        assert got_valid == expected_valid, (
            f"valid mismatch at cycle {cycle}: got {got_valid!r}, expected "
            f"{expected_valid} (input cycle {input_index}, latency {latency})"
        )
        if not expected_valid:
            await Timer(1, units="ps")
            continue

        dividend, divisor = schedule[input_index][1:]
        expected_q, expected_r = _golden(dividend, divisor)
        got_q = _resolved_int(dut.output_quotient)
        got_r = _resolved_int(dut.output_remainder)
        assert (got_q, got_r) == (expected_q, expected_r), (
            f"data mismatch for 0x{dividend:08x}/0x{divisor:08x} at cycle "
            f"{cycle}: got q/r={got_q!r}/{got_r!r}, expected "
            f"0x{expected_q:08x}/0x{expected_r:08x}"
        )
        seen.append((dividend, divisor, got_q, got_r))
        # Leave cocotb's read-only phase before the next iteration drives a
        # new transaction.
        await Timer(1, units="ps")

    assert len(seen) == len(expected_outputs), (
        f"pipeline flush produced {len(seen)} valid outputs; expected "
        f"{len(expected_outputs)}"
    )
    assert seen == expected_outputs, "valid output transactions were reordered"

    result_path = Path(os.environ["DIVIDER_QOR_FUNCTIONAL_RESULT"])
    result_path.write_text(
        json.dumps(
            {
                "passed": True,
                "latency_slices": latency,
                "cycles": len(schedule) + flush,
                "valid_vectors": len(expected_outputs),
                "coverage": {
                    "continuous_valid": True,
                    "bubbles": True,
                    "divide_by_zero": True,
                    "edge_cases": True,
                    "ordering": True,
                    "valid_timing": True,
                    "pipeline_flush": True,
                    "input_ready_constant_one": True,
                    "output_backpressure": False,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
