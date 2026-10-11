#!/usr/bin/env python3
"""Contract tests for RAM plans, native memory state, and stream credits."""

import os
import random
import sys
from types import SimpleNamespace
from unittest.mock import patch
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
import pypeline as py
from AUTO_PIPELINE import RamPlan, RAM_CANDIDATES as candidates
import AUTO_PIPELINE as ap
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


def targets_and_resources():
    import SYN
    import VIVADO
    import OPEN_TOOLS
    import DEVICE_MODELS
    import PY_TO_LOGIC

    # Boundaries of every RAMB36 aspect ratio, SDP vs TDP, and byte lanes.
    for width, depth in (
        (1, 32768),
        (2, 16384),
        (4, 8192),
        (9, 4096),
        (18, 2048),
        (36, 1024),
        (72, 512),
    ):
        for size, splits in (
            (depth - 1, 0),
            (depth, 0),
            (depth + 1, 1),
            (depth * 4, 2),
        ):
            assert (
                ap.RAM_MAX_SPLIT_DEPTH(size, width, ("w", "r"), False, "vivado")
                == splits
            )
    assert ap.RAM_MAX_SPLIT_DEPTH(1024, 64, ("rw", "rw"), False, "vivado") == 0
    assert ap.RAM_MAX_SPLIT_DEPTH(1024, 64, ("w", "r"), False, "vivado") == 1
    assert ap.RAM_MAX_SPLIT_DEPTH(1024, 64, ("r",), False, "vivado") == 1
    assert ap.RAM_MAX_SPLIT_DEPTH(1024, 64, ("r", "r"), False, "vivado") == 0
    assert ap.RAM_MAX_SPLIT_DEPTH(4096, 9, ("rw",), True, "vivado") == 1
    assert ap.RAM_MAX_SPLIT_DEPTH(1024, 32, ("w", "r"), True, "vivado") == 0
    assert ap.RAM_MAX_SPLIT_DEPTH(1024, 32, ("w", "r"), False, "ecp5") == 1
    raises(lambda: candidates(1024, 32, ("r",), False, target="unknown"), "unsupported")
    for target in ("ecp5", "vivado"):
        for latency in range(1, 16):
            assert all(
                p.latency == latency
                for p in candidates(
                    65536, 32, ("rw", "rw"), True, latency=latency, target=target
                )
            )

    text = """| Site Type | Used | Fixed | Prohibited | Available | Util% |
| Slice LUTs* | 1,234 | 0 | 0 | 134600 | 1 |
| LUT as Memory | 111 | 0 | 0 | 30000 | 1 |
| Slice Registers | 876 | 0 | 0 | 269200 | 1 |
| Block RAM Tile | 6 | 0 | 0 | 365 | 1 |
| RAMB36/FIFO* | 5 | 0 | 0 | 365 | 1 |
| RAMB18 | 2 | 0 | 0 | 730 | 1 |
| DSPs | 3 | 0 | 0 | 740 | 1 |"""
    counts = VIVADO.PARSE_RAM_RESOURCES(text)
    assert counts == dict(LUT=1234, FF=876, RAMB36=5, RAMB18=2, DSP=3), counts
    assert ap.RAM_RESOURCE_SCORE(counts) == (12, 1234, 876)
    assert ap.RAM_RESOURCE_SCORE(dict(LUT=19, FF=7)) == (0, 19, 7)
    assert ap.RAM_RESOURCE_SCORE(dict(DP16KD=8, LUT4=32, DFF=16)) == (8, 32, 16)
    assert ap.RAM_RESOURCE_SCORE(
        dict(RAMB36=1, RAMB18=0, LUT=10, FF=2)
    ) < ap.RAM_RESOURCE_SCORE(dict(RAMB36=0, RAMB18=2, LUT=11, FF=0))

    # Bootstrap parsing used ECP5 geometry before PART/CLI resolution. Even a
    # fixed-only build must re-elaborate its callers with the resolved plan.
    options = dict(
        size=1024,
        width=32,
        ports=("w", "r"),
        byte_write_enables=False,
        latency=7,
        start_latency=None,
        max_latency=None,
    )

    def state(plan):
        return SimpleNamespace(
            part="xc7a200tffg1156-2",
            syn_tool_name="vivado",
            FuncToInstances={"ram": ["top.ram"]},
            auto_pipeline_rams={"ram": dict(key="key", options=options, plan=plan)},
        )

    original = state(candidates(**options, target="ecp5")[0])
    saved = py.AUTO_PIPELINE_RAM_PLAN_CACHE()
    py.SET_AUTO_PIPELINE_BUILD_MODE("fixed_only")
    try:
        with patch.object(SYN, "SYN_TOOL", VIVADO), patch.object(
            PY_TO_LOGIC,
            "PARSE_FILE",
            side_effect=lambda path: state(py.AUTO_PIPELINE_RAM_PLAN_CACHE()["key"]),
        ) as parse:
            updated = ap.RAM_PREPARE_TARGET(original, "fixture.py")
            parse.assert_called_once_with("fixture.py")
            assert ap.RAM_PLANS_FROM_STATE(updated)["key"].split_depth == 0
            assert updated.part == original.part and updated.syn_tool_name == "vivado"
            ap.RAM_VALIDATE_BACKEND(updated)
        # HDL emission still uses the requested part's geometry when Vivado
        # is unavailable; a missing tool never activates a start-latency guess.
        with patch.object(SYN, "SYN_TOOL", None), patch.object(
            PY_TO_LOGIC,
            "PARSE_FILE",
            side_effect=lambda path: state(py.AUTO_PIPELINE_RAM_PLAN_CACHE()["key"]),
        ):
            updated = ap.RAM_PREPARE_TARGET(original, "fixture.py")
            assert ap.RAM_TARGET(updated) == "vivado"
            assert ap.RAM_PLANS_FROM_STATE(updated)["key"].split_depth == 0
            options = dict(options, latency=None, start_latency=3)
            py.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
            updated = ap.RAM_PREPARE_TARGET(state(RamPlan(1, 1)), "fixture.py")
            assert ap.RAM_PLANS_FROM_STATE(updated)["key"].latency == 1
        for tool, part, supported in (
            (OPEN_TOOLS, "LFE5U-85F-6BG381C", True),
            (OPEN_TOOLS, "ice40up5k-sg48", False),
            (DEVICE_MODELS, "sky130", False),
        ):
            original.part = part
            with patch.object(SYN, "SYN_TOOL", tool):
                if supported:
                    ap.RAM_VALIDATE_BACKEND(original)
                else:
                    raises(lambda: ap.RAM_VALIDATE_BACKEND(original), "Vivado or ECP5")
    finally:
        py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(saved)
        py.SET_AUTO_PIPELINE_BUILD_MODE(None)


def native_target_and_replay():
    import SYN

    options = dict(
        size=1024,
        width=32,
        ports=("w", "r"),
        byte_write_enables=False,
        latency=7,
        start_latency=None,
        max_latency=None,
    )
    saved = py.AUTO_PIPELINE_RAM_PLAN_CACHE()
    served = py._auto_pipeline_ram_served
    try:
        py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE({})
        py._auto_pipeline_ram_served = {
            "key": dict(
                options=options, plan=candidates(**options)[0], from_cache=False
            )
        }
        with patch.object(py, "_part_registry", None), patch.object(
            py, "_syn_tool_registry", None
        ), patch.object(SYN, "CHECK_TOOL_INSTALLED") as check:
            assert ap.RAM_PREPARE_NATIVE("xc7a200tffg1156-2") == "vivado"
            check.assert_not_called()
            assert py.AUTO_PIPELINE_RAM_PLAN_CACHE()["key"].split_depth == 0
            explicit = RamPlan(0, 6)
            py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE({"key": explicit})
            py._auto_pipeline_ram_served["key"].update(plan=explicit, from_cache=True)
            assert ap.RAM_PREPARE_NATIVE("xc7a200tffg1156-2") is None
            assert py.AUTO_PIPELINE_RAM_PLAN_CACHE()["key"] == explicit
            raises(
                lambda: ap.RAM_PREPARE_NATIVE("LFE5U-85F-6BG381C", "vivado"),
                "contradicts",
            )
    finally:
        py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(saved)
        py._auto_pipeline_ram_served = served


def native_run_target_isolation():
    import subprocess
    import tempfile

    # Same logical RAM, two source imports in one process. A prior Vivado
    # target/plan must not change a later source-only ECP5/default run.
    code = r'''
import pathlib, sys
import pypeline_sim
root = pathlib.Path(sys.argv[1])
template = """from pypeline import *
from ram import make_auto_pipeline_ram
ram, _ = make_auto_pipeline_ram(uint32_t, 1024, ports=('w', 'r'), latency=7)
{target}
@initial
def check_geometry():
    assert ram.read_after_write_gap == {gap}, ram.plan
@MAIN
def tick():
    return
"""
for name, target, gap in [('vivado', 'PART("xc7a200tffg1156-2")\nSYN_TOOL("vivado")', 2),
                          ('default', '', 3)]:
    path = root / (name + '.py')
    path.write_text(template.format(target=target, gap=gap))
    pypeline_sim.run_sim(str(path), 1)
print('isolated RAM targets')
'''
    with tempfile.TemporaryDirectory(prefix="ram_native_targets_") as temp:
        result = subprocess.run(
            [sys.executable, "-c", code, temp],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
        )
    assert result.returncode == 0 and "isolated RAM targets" in result.stdout, (
        result.stdout + result.stderr
    )


def measured_joint_trim_and_restoration():
    import json
    import tempfile
    from contextlib import ExitStack
    import C_TO_LOGIC
    import PY_TO_LOGIC
    import SYN
    import SWEEP
    import VIVADO

    options = dict(
        size=512,
        width=32,
        ports=("w", "r"),
        byte_write_enables=False,
        latency=None,
        start_latency=3,
        max_latency=None,
    )

    def state(plans):
        return SimpleNamespace(
            part="xc7a200tffg1156-2",
            syn_tool_name="vivado",
            main_mhz={"main": 100},
            FuncToInstances={k: [k] for k in plans},
            auto_pipeline_rams={
                k: dict(key=k, options=options, plan=p) for k, p in plans.items()
            },
        )

    saved = py.AUTO_PIPELINE_RAM_PLAN_CACHE()
    try:
        for reject_joint in (False, True):
            observed = []

            def report(ps, timing):
                plans = ap.RAM_PLANS_FROM_STATE(ps)
                a, b = plans["a"], plans["b"]
                observed.append((a.latency, b.latency, b.input_regs, b.output_regs))
                failed = reject_joint and (
                    a.latency == b.latency == 1 or b.latency == 2 and b.input_regs
                )
                return SimpleNamespace(
                    path_reports={
                        "clk": SimpleNamespace(
                            path_delay_ns=1000 / (90 if failed else 150)
                        )
                    },
                    ram_resources=dict(
                        RAMB18=2, RAMB36=0, LUT=10, FF=a.latency + b.latency
                    ),
                )

            with tempfile.TemporaryDirectory(
                prefix="ram_joint_search_"
            ) as temp, ExitStack() as stack:
                for obj, attr, value in (
                    (SYN, "SYN_TOOL", VIVADO),
                    (SYN, "SYN_OUTPUT_DIRECTORY", temp),
                    (SYN, "TOP_LEVEL_MODULE", "top"),
                    (SYN, "GET_TARGET_MHZ", lambda main, ps: 100),
                    (
                        SYN,
                        "GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH",
                        lambda ps: ({"clk": 100}, None),
                    ),
                    (SYN, "RUN_MULTIMAIN_SYN", report),
                    (
                        PY_TO_LOGIC,
                        "PARSE_FILE",
                        lambda path: state(py.AUTO_PIPELINE_RAM_PLAN_CACHE()),
                    ),
                    (C_TO_LOGIC, "WRITE_0_ADDED_CLKS_INIT_FILES", lambda ps: None),
                    (SWEEP, "WRITE_SWEEP_HISTORY", lambda *a, **k: None),
                ):
                    stack.enter_context(patch.object(obj, attr, value))
                final, timing = ap.RAM_SEARCH(
                    state({"a": RamPlan(1, 1), "b": RamPlan(1, 1)}),
                    None,
                    "fixture.py",
                    lambda ps: (ps, SimpleNamespace(sweep_timing_failures=[])),
                )
                winner = ap.RAM_PLANS_FROM_STATE(final)
                assert winner == py.AUTO_PIPELINE_RAM_PLAN_CACHE()
                history = json.loads(
                    (
                        Path(temp)
                        / SYN.TOP_LEVEL_MODULE
                        / "auto_pipeline_ram_history.json"
                    ).read_text()
                )
                assert history["selected"] == json.loads(
                    json.dumps(ap.RAM_REPORT_PLANS(final))
                )
                assert timing.auto_pipeline_ram_history[-1]["met"]
                assert observed[:2] == [(3, 3, 1, 1), (1, 1, 0, 0)]
                if reject_joint:
                    assert winner == {"a": RamPlan(), "b": RamPlan(0, 1)}
                    assert observed[-1] == observed[-3]  # restore after a losing probe
                else:
                    assert len(observed) == 2 and all(
                        p.latency == 1 for p in winner.values()
                    )
    finally:
        py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(saved)


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


def initialization_and_roms():
    init = {0: 7, 511: 17, 512: 27, 1023: 37, 2048: 47, 5002: 57}
    rom, _ = make_auto_pipeline_ram(
        py.uint16_t, 5003, ports=("r", "r", "r", "r"), init=init, latency=7
    )
    py.sim_reset()
    pending = deque()
    addresses = [0, 1, 511, 512, 1023, 2048, 5002]
    for cycle in range(60 + rom.latency):
        reqs = [
            (addresses[(cycle + port) % len(addresses)], cycle < 60)
            for port in range(4)
        ]
        pending.append(reqs)
        result = py.sim_call(
            rom, *(t(addr=a, valid=v) for t, (a, v) in zip(rom.in_ts, reqs))
        )
        if cycle >= rom.latency:
            for port, (addr, valid) in enumerate(pending.popleft()):
                response = getattr(result, f"p{port}")
                assert bool(response.valid) == valid
                if valid:
                    assert int(response.addr) == addr and int(
                        response.rd_data
                    ) == init.get(addr, 0)
    # Two writes to disjoint byte lanes of the same word are legal. Neither
    # port may overwrite the other port's untouched lanes.
    dual, _ = make_auto_pipeline_ram(
        py.uint32_t, 32, ports=("rw", "rw"), byte_write_enables=True
    )
    py.sim_reset()
    py.sim_call(
        dual,
        dual.p0_in_t(addr=7, valid=1, wr_data=0x11223344, wr_en=[1, 0, 1, 0]),
        dual.p1_in_t(addr=7, valid=1, wr_data=0xAABBCCDD, wr_en=[0, 1, 0, 1]),
    )
    py.sim_call(
        dual, *(t(addr=7, valid=1, wr_data=0, wr_en=[0] * 4) for t in dual.in_ts)
    )
    result = py.sim_call(
        dual, *(t(addr=0, valid=0, wr_data=0, wr_en=[0] * 4) for t in dual.in_ts)
    )
    assert result.p0.rd_data == result.p1.rd_data == 0xAA22CC44


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
    targets_and_resources()
    native_target_and_replay()
    native_run_target_isolation()
    measured_joint_trim_and_restoration()
    for latency in (1, 2, 3, 4, 5, 6, 7, 9):
        memory_contract(latency)
        memory_contract(latency, True)
        streaming(latency, False)
        streaming(latency, True)
    memory_contract(5, ports=("rw", "rw"))
    memory_contract(5, True, ports=("rw", "rw"))
    memory_contract(5, ports=("w", "r", "r", "r"))
    memory_contract(5, elem_t=py.uint8_t[4])
    hazards_and_isolation()
    initialization_and_roms()
    convergence()
    print("All automatic pipeline RAM contract tests passed.")
