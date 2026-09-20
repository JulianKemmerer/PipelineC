#!/usr/bin/env python3
"""Contract tests for RAM plans, native memory state, and stream credits."""

import random
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
import pypeline as py
from AUTO_PIPELINE import RamPlan, RAM_CANDIDATES as candidates
from ram import make_auto_pipeline_ram, ram_flatten
from stream.stream_ram import make_stream_auto_pipeline_ram


def raises(call, text):
    try:
        call()
    except (ValueError, TypeError) as e:
        assert text in str(e), str(e)
    else:
        raise AssertionError("expected " + text)


def plans_and_validation():
    for kwargs in (
        dict(latency=0),
        dict(latency=True),
        dict(max_latency=0),
        dict(start_latency=-1),
    ):
        raises(lambda: make_auto_pipeline_ram(py.uint32_t, 16, **kwargs), ">= 1")
    raises(
        lambda: make_auto_pipeline_ram(py.uint32_t, 16, latency=2, max_latency=3),
        "cannot be combined",
    )
    raises(
        lambda: make_auto_pipeline_ram(py.uint32_t, 16, start_latency=3, max_latency=2),
        "exceeds",
    )
    raises(
        lambda: make_auto_pipeline_ram(py.uint32_t, 16, ports=("w", "w", "r")),
        "unsupported BRAM",
    )
    all_plans = candidates(65536, 32, ("w", "r"), False)
    assert all_plans[:4] == [RamPlan(), RamPlan(0, 1), RamPlan(1, 0), RamPlan(1, 1)]
    assert all(
        p.input_regs == 1 and p.output_regs >= 1 for p in all_plans if p.split_depth
    )
    assert len({p.fingerprint for p in all_plans}) == len(all_plans)
    for latency in range(1, 18):
        fixed = candidates(65536, 32, ("w", "r"), False, latency=latency)
        assert fixed and all(p.latency == latency for p in fixed)
    assert all(
        p.latency <= 5 for p in candidates(65536, 32, ("w", "r"), False, max_latency=5)
    )
    for mode in (None, "fixed_only", "sweep"):
        py.SET_AUTO_PIPELINE_BUILD_MODE(mode)
        ram, _ = make_auto_pipeline_ram(py.uint32_t, 16, start_latency=3)
        assert ram.latency == (3 if mode == "sweep" else 1)
    py.SET_AUTO_PIPELINE_BUILD_MODE(None)


def memory_contract(latency, byte_enables=False, ports=("w", "r"), elem_t=py.uint32_t):
    ram, _ = make_auto_pipeline_ram(
        elem_t, 2049, ports=ports, latency=latency, byte_write_enables=byte_enables
    )
    py.sim_reset()
    rng = random.Random(712 + latency)
    memory = [0] * ram.size
    expected = deque()
    addresses = [0, 511, 512, 1023, 1024, 2048]
    # Deliberate banks/byte-lane boundaries, followed by reads after visibility.
    for cycle in range(180 + latency):
        args, responses = [], []
        writing = cycle < 60
        reading = 80 <= cycle < 160
        for i, kind in enumerate(ports):
            addr = addresses[(cycle + i) % len(addresses)]
            wr = writing and kind != "r"
            valid = wr or (reading and kind != "w")
            # Distinct simultaneous writers use distinct addresses.
            value = rng.getrandbits(32)
            if str(elem_t) == "uint8_t[4]":
                value = [(value >> (8 * j)) & 255 for j in range(4)]
            mask = (
                [int((cycle + j) % 3 != 0) for j in range(4)]
                if byte_enables and wr
                else ([0] * 4 if byte_enables else int(wr))
            )
            fields = dict(addr=addr, valid=int(valid))
            if kind != "r":
                fields.update(wr_data=value, wr_en=mask)
            args.append(ram.in_ts[i](**fields))
            responses.append((valid, addr, memory[addr] if reading else None))
            if wr:
                flat = ram_flatten(elem_t, py._sim_cast_deep(value, elem_t))
                bits = (
                    sum(255 << (8 * j) for j, enabled in enumerate(mask) if enabled)
                    if byte_enables
                    else (1 << 32) - 1
                )
                memory[addr] = (memory[addr] & ~bits) | (flat & bits)
        expected.append(responses)
        out = py.sim_call(ram, *args)
        if cycle >= latency:
            exp = expected.popleft()
            for i, (valid, addr, data) in enumerate(exp):
                actual = getattr(out, f"p{i}")
                assert int(actual.valid) == int(valid), (latency, cycle, i)
                if valid:
                    assert int(actual.addr) == addr
                    if data is not None:
                        assert ram_flatten(elem_t, actual.rd_data) == data, (
                            latency,
                            cycle,
                            i,
                            actual,
                            data,
                        )


def hazards_and_isolation():
    ram, _ = make_auto_pipeline_ram(py.uint32_t, 32, latency=3)
    py.sim_reset()
    py.sim_call(ram, ram.p0_in_t(addr=5, wr_data=19, wr_en=1, valid=1))
    raises(
        lambda: py.sim_call(ram, ram.p0_in_t(addr=5, wr_data=0, wr_en=0, valid=1)),
        "read_after_write_gap",
    )
    tdp, _ = make_auto_pipeline_ram(py.uint32_t, 32, ports=("rw", "rw"))
    py.sim_reset()
    raises(
        lambda: py.sim_call(
            tdp, *(t(addr=2, wr_data=7, wr_en=1, valid=1) for t in tdp.in_ts)
        ),
        "overlapping writes",
    )
    # Equal shapes with different initialization must have distinct identities.
    a, _ = make_auto_pipeline_ram(py.uint32_t, 32, init={3: 7})
    b, _ = make_auto_pipeline_ram(py.uint32_t, 32, init={3: 9})
    assert a._auto_pipeline_ram["key"] != b._auto_pipeline_ram["key"]


def convergence():
    ram, _ = make_auto_pipeline_ram(py.uint32_t, 2049, ports=("w", "r"), latency=5)
    py.sim_reset()
    py._sim_active = True
    py._sim_reg_begin_buffer()
    try:
        for address, value in ((1, 99), (2, 123)):
            py.sim_call(
                ram,
                ram.p0_in_t(addr=address, wr_data=value, wr_en=1, valid=1),
                ram.p1_in_t(addr=0, valid=0),
            )
    finally:
        py._sim_reg_flush_buffer()
        py._sim_active = False
    expected = deque()
    checked = []
    for cycle in range(25):
        valid = 8 <= cycle < 10
        addr = cycle - 7 if valid else 0
        expected.append((valid, addr))
        out = py.sim_call(
            ram,
            ram.p0_in_t(addr=0, wr_data=0, wr_en=0, valid=0),
            ram.p1_in_t(addr=addr, valid=int(valid)),
        )
        if cycle >= ram.latency:
            valid, addr = expected.popleft()
            assert bool(out.p1.valid) == valid
            if valid:
                checked.append(int(out.p1.rd_data))
    assert checked == [0, 123], checked  # discarded write never commits


def streaming(latency, stalled):
    ram, _ = make_stream_auto_pipeline_ram(
        py.uint32_t,
        2049,
        ports=("w", "r"),
        latency=latency,
        init={a: a * 3 + 1 for a in range(64)},
    )
    py.sim_reset()
    rng = random.Random(812)
    sent, received = [0, 0], [0, 0]
    pending = [deque(), deque()]
    held = [None, None]
    accepted_cycles = []
    for cycle in range(1400):
        args, ready_values = [], []
        for i in range(2):
            # Writes avoid the read port's address range; echo acknowledgements
            # check that accepted writes are neither dropped nor duplicated.
            addr = (sent[i] % 64) + (128 if i == 0 else 0)
            fields = dict(addr=addr)
            if i == 0:
                fields.update(wr_data=sent[i] + 200, wr_en=1)
            valid = int(sent[i] < 250)
            ready = int(not stalled or (cycle > 150 and rng.random() > 0.4))
            ready_values.append(ready)
            args += [
                ram.req_intrfs[i].fwd_t(
                    stream=ram.req_intrfs[i].stream_t(
                        data=ram.req_ts[i](**fields), valid=valid
                    )
                ),
                ram.resp_intrfs[i].fb_t(ready=ready),
            ]
        out = py.sim_call(ram, *args)
        for i in range(2):
            req, resp = (
                getattr(out, f"p{i}_req_if"),
                getattr(out, f"p{i}_resp_if").stream,
            )
            if sent[i] < 250 and int(req.ready):
                pending[i].append(sent[i])
                sent[i] += 1
                if i == 1:
                    accepted_cycles.append(cycle)
            if held[i] is not None:
                assert int(resp.valid) and resp.data == held[i], (
                    cycle,
                    i,
                    "stalled response changed",
                )
            held[i] = resp.data if int(resp.valid) and not ready_values[i] else None
            if int(resp.valid) and ready_values[i]:
                sequence = pending[i].popleft()
                assert int(resp.data.addr) == sequence % 64 + (128 if i == 0 else 0)
                if i == 0:
                    assert int(resp.data.wr_data) == sequence + 200
                else:
                    assert int(resp.data.rd_data) == (sequence % 64) * 3 + 1
                received[i] += 1
        if received == [250, 250]:
            break
    assert sent == received == [250, 250], (latency, sent, received)
    assert not any(pending)
    if not stalled:
        assert accepted_cycles == list(
            range(accepted_cycles[0], accepted_cycles[0] + 250)
        ), accepted_cycles


if __name__ == "__main__":
    plans_and_validation()
    for latency in (1, 2, 3, 4, 5, 6, 7, 9):
        memory_contract(latency)
        memory_contract(latency, True)
        streaming(latency, False)
        streaming(latency, True)
    memory_contract(5, ports=("rw", "rw"))
    memory_contract(5, ports=("w", "r", "r", "r"))
    memory_contract(5, elem_t=py.uint8_t[4])
    hazards_and_isolation()
    convergence()
    print("All automatic pipeline RAM contract tests passed.")
