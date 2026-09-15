# pyright: reportInvalidTypeForm=none
"""make_ram (include/pypeline/ram.py): simulation-model checks plus synthesis tops.

Registered twice: in native_sim_tests.py, where plain `python3` runs the test_*
functions against the @sim_model, and in synth_tests.py with --comb, where every
@MAIN below elaborates and synthesizes its generated raw VHDL. Cycle-by-cycle
agreement between the model and that VHDL is checked by self_check_ram_test.py.

The soak tests use a reference that shares nothing with the model's stage
mechanics. It only encodes the contract: a request's outputs appear `latency`
cycles later, echoing the request, and its read sees exactly the writes of
every EARLIER request (applied in cycle, then port, order) -- never its own
cycle's.
"""
import os
import random
import subprocess
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
from enum import IntEnum
from typing import NamedTuple

from pypeline import (
    MAIN,
    Reg,
    char_t,
    enum,
    hw_func,
    int16_t,
    sim_call,
    sim_reset,
    struct,
    uint1_t,
    uint4_t,
    uint8_t,
    uint16_t,
    uint32_t,
)

from ram import make_ram


@enum
class color_t(IntEnum):
    RED = 0
    GREEN = 1
    BLUE = 2


@struct
class pixel_t(NamedTuple):
    color: color_t
    level: uint4_t
    lit: uint1_t


# Single read+write port, block-RAM read (ram.h DECL_RAM_SP_RF_1 shape).
sp_ram, sp_ram_out_t = make_ram(
    uint32_t, 16, ports=("rw",), read_latency=1, init=[10, 11, 12, 13]
)
# Write port + read port, combinational read, struct elements, size 10 (wraps).
lut_ram, lut_ram_out_t = make_ram(
    pixel_t,
    10,
    ports=("w", "r"),
    read_latency=0,
    init={3: pixel_t(color=color_t.BLUE, level=9, lit=1)},
)
# Two read+write ports with an input and an output register: latency 3.
tdp_ram, tdp_ram_out_t = make_ram(
    int16_t,
    8,
    ports=("rw", "rw"),
    read_latency=1,
    in_regs=1,
    out_regs=1,
    init=[-1, -2, 300],
)
# Register file: two combinational read ports and one write port, array elements.
regfile, regfile_out_t = make_ram(uint8_t[4], 4, ports=("r", "r", "w"), read_latency=0)
# CPU-style memory with per-byte write enables.
cpu_mem, cpu_mem_out_t = make_ram(
    uint32_t,
    4,
    ports=("rw",),
    read_latency=1,
    byte_write_enables=True,
    init=[0x11223344],
)
# A ROM of strings.
rom, rom_out_t = make_ram(
    char_t[8], 3, ports=("r",), read_latency=1, init=["boot", "run", "halt"]
)

sp_ram_p0_in_t = sp_ram.p0_in_t
lut_ram_p0_in_t = lut_ram.p0_in_t
lut_ram_p1_in_t = lut_ram.p1_in_t
tdp_ram_p0_in_t = tdp_ram.p0_in_t
tdp_ram_p1_in_t = tdp_ram.p1_in_t
regfile_p0_in_t = regfile.p0_in_t
regfile_p1_in_t = regfile.p1_in_t
regfile_p2_in_t = regfile.p2_in_t
cpu_mem_p0_in_t = cpu_mem.p0_in_t
rom_p0_in_t = rom.p0_in_t


# ── Synthesis tops (synth_tests.py builds this file with --comb) ──


@MAIN
def ram_test_sp(p0: sp_ram_p0_in_t) -> sp_ram_out_t:
    return sp_ram(p0)


@MAIN
def ram_test_lut(p0: lut_ram_p0_in_t, p1: lut_ram_p1_in_t) -> lut_ram_out_t:
    return lut_ram(p0, p1)


@MAIN
def ram_test_tdp(p0: tdp_ram_p0_in_t, p1: tdp_ram_p1_in_t) -> tdp_ram_out_t:
    return tdp_ram(p0, p1)


@MAIN
def ram_test_regfile(
    p0: regfile_p0_in_t, p1: regfile_p1_in_t, p2: regfile_p2_in_t
) -> regfile_out_t:
    return regfile(p0, p1, p2)


@MAIN
def ram_test_cpu_mem(p0: cpu_mem_p0_in_t) -> cpu_mem_out_t:
    return cpu_mem(p0)


@MAIN
def ram_test_rom(p0: rom_p0_in_t) -> rom_out_t:
    return rom(p0)


# ── Callers: a stateful one (uses the physical output) and a pure one (aligned) ──

counter_ram, counter_ram_out_t = make_ram(
    uint8_t, 4, ports=("rw",), read_latency=1, out_regs=1
)
counter_ram_p0_in_t = counter_ram.p0_in_t


@hw_func
def stateful_writer(x: uint8_t) -> uint8_t:
    n: Reg[uint8_t]
    req: counter_ram_p0_in_t
    req.addr = n
    req.wr_data = x
    req.wr_en = 1
    req.valid = 1
    resp: counter_ram_out_t = counter_ram(req)
    n = n + 1
    return resp.p0.wr_data


table_rom, table_rom_out_t = make_ram(
    uint8_t, 8, ports=("r",), read_latency=1, out_regs=1, init=[i * 10 for i in range(8)]
)
table_rom_p0_in_t = table_rom.p0_in_t


@hw_func
def pure_lookup_plus(x: uint8_t) -> uint16_t:
    req: table_rom_p0_in_t
    req.addr = x
    req.valid = 1
    resp: table_rom_out_t = table_rom(req)
    return resp.p0.rd_data + x


@hw_func
def two_instances(x: uint32_t) -> uint32_t:
    toggle: Reg[uint1_t]
    wr: sp_ram_p0_in_t
    wr.addr = 5
    wr.wr_data = x
    wr.wr_en = 1
    wr.valid = 1
    first: sp_ram_out_t = sp_ram(wr)
    rd: sp_ram_p0_in_t
    rd.addr = 5
    rd.valid = 1
    second: sp_ram_out_t = sp_ram(rd)
    toggle = ~toggle
    return (first.p0.rd_data << 16) | second.p0.rd_data


# ── Helpers ──


def plain(v):
    """A sim value as plain Python: ints, lists, tuples of fields."""
    if isinstance(v, tuple) and hasattr(v, "_fields"):
        return tuple(plain(getattr(v, f)) for f in v._fields)
    if isinstance(v, list):
        return [plain(x) for x in v]
    return int(v)


def expect_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} from {fn.__name__}{args}{kwargs}")


# ── Tests ──


def test_attributes():
    assert (sp_ram.latency, lut_ram.latency, tdp_ram.latency) == (1, 0, 3)
    assert (sp_ram._pipeline_latency, lut_ram._pipeline_latency, tdp_ram._pipeline_latency) == (1, 0, 3)
    assert sp_ram.addr_t.width == 4 and lut_ram.addr_t.width == 4 and rom.addr_t.width == 2
    assert tdp_ram.ports == ("rw", "rw") and tdp_ram.in_regs == 1 and tdp_ram.out_regs == 1
    assert sp_ram.p0_in_t._fields == ("addr", "wr_data", "wr_en", "valid")
    assert sp_ram.p0_out_t._fields == ("addr", "wr_data", "wr_en", "valid", "rd_data")
    assert regfile.p0_in_t._fields == ("addr", "valid")
    assert regfile.p0_out_t._fields == ("addr", "valid", "rd_data")
    assert regfile.p2_out_t._fields == ("addr", "wr_data", "wr_en", "valid")
    assert sp_ram_out_t._fields == ("p0",) and regfile_out_t._fields == ("p0", "p1", "p2")
    assert str(cpu_mem.we_t) == "uint1_t[4]" and cpu_mem.byte_write_enables
    # Same configuration and contents -> the same function (one entity).
    again, again_t = make_ram(uint32_t, 16, ports=("rw",), read_latency=1, init=[10, 11, 12, 13])
    assert again is sp_ram and again_t is sp_ram_out_t


def test_distinct_contents_distinct_functions():
    a, _ = make_ram(uint8_t, 4, ports=("r",), read_latency=0, init=[1, 2, 3, 4])
    b, _ = make_ram(uint8_t, 4, ports=("r",), read_latency=0, init=[4, 3, 2, 1])
    c, _ = make_ram(uint8_t, 4, ports=("r",), read_latency=0, init=(1, 2, 3, 4))
    zeros, _ = make_ram(uint8_t, 4, ports=("r",), read_latency=0, init=[0, 0])
    empty, _ = make_ram(uint8_t, 4, ports=("r",), read_latency=0)
    assert a is c, "init as list or tuple of the same values is one RAM"
    assert zeros is empty, "an all-zero init is the same RAM as no init"
    assert a is not b and a.__name__ != b.__name__
    sim_reset()
    assert int(sim_call(a, a.p0_in_t(addr=1, valid=1)).p0.rd_data) == 2
    assert int(sim_call(b, b.p0_in_t(addr=1, valid=1)).p0.rd_data) == 3


def test_sp_bram_read_first_and_passthrough():
    sim_reset()
    got = []
    for addr, data, we in [(0, 0, 0), (1, 5, 0), (2, 99, 1), (2, 0, 0), (2, 0, 0)]:
        o = sim_call(sp_ram, sp_ram.p0_in_t(addr=addr, wr_data=data, wr_en=we, valid=1))
        got.append(plain(o.p0))
    # (addr, wr_data, wr_en, valid, rd_data), one cycle after each request
    assert got == [
        (0, 0, 0, 0, 0),
        (0, 0, 0, 1, 10),
        (1, 5, 0, 1, 11),
        (2, 99, 1, 1, 12),  # the write's own read is read-first: old value
        (2, 0, 0, 1, 99),
    ], got


def test_valid_gates_writes():
    sim_reset()
    sim_call(sp_ram, sp_ram.p0_in_t(addr=7, wr_data=1234, wr_en=1, valid=0))
    sim_call(sp_ram, sp_ram.p0_in_t(addr=7, wr_data=0, wr_en=0, valid=1))
    o = sim_call(sp_ram, sp_ram.p0_in_t(addr=0, wr_data=0, wr_en=0, valid=1))
    assert int(o.p0.rd_data) == 0 and int(o.p0.valid) == 1, plain(o.p0)


def test_comb_read_struct_elements_and_wrap():
    sim_reset()
    blue = pixel_t(color=color_t.BLUE, level=9, lit=1)
    green = pixel_t(color=color_t.GREEN, level=4, lit=0)
    o = sim_call(
        lut_ram,
        lut_ram.p0_in_t(addr=3, wr_data=green, wr_en=1, valid=1),
        lut_ram.p1_in_t(addr=3, valid=1),
    )
    assert plain(o.p1.rd_data) == plain(blue), "combinational read sees the pre-edge value"
    assert plain(o.p0.wr_data) == plain(green) and int(o.p1.addr) == 3
    # Address 13 is out of range for a 10-entry RAM: simulation wraps it to 3,
    # while the echoed addr stays 13.
    o = sim_call(
        lut_ram,
        lut_ram.p0_in_t(addr=0, wr_data=blue, wr_en=0, valid=1),
        lut_ram.p1_in_t(addr=13, valid=1),
    )
    assert plain(o.p1.rd_data) == plain(green) and int(o.p1.addr) == 13


def test_latency3_ports_and_write_collision():
    sim_reset()

    def step(a0=0, d0=0, w0=0, v0=0, a1=0, d1=0, w1=0, v1=0):
        o = sim_call(
            tdp_ram,
            tdp_ram.p0_in_t(addr=a0, wr_data=d0, wr_en=w0, valid=v0),
            tdp_ram.p1_in_t(addr=a1, wr_data=d1, wr_en=w1, valid=v1),
        )
        return plain(o.p0), plain(o.p1)

    outs = [
        # c0: both ports write address 1: the higher port index wins
        step(a0=1, d0=100, w0=1, v0=1, a1=1, d1=200, w1=1, v1=1),
        # c1: port 0 reads 2 while port 1 writes 2 on the same edge
        step(a0=2, v0=1, a1=2, d1=-7, w1=1, v1=1),
        step(a0=1, v0=1),  # c2: read the collided address
        step(a0=2, v0=1),  # c3: read the address written in c1
        step(),
        step(),
        step(),
    ]
    assert outs[0] == ((0, 0, 0, 0, 0), (0, 0, 0, 0, 0)) and outs[2][0][3] == 0
    assert outs[3] == ((1, 100, 1, 1, -2), (1, 200, 1, 1, -2)), outs[3]
    assert outs[4][0] == (2, 0, 0, 1, 300), "same-edge cross-port read is read-first"
    assert outs[4][1] == (2, -7, 1, 1, 300)
    assert outs[5][0] == (1, 0, 0, 1, 200), "port 1's write won the collision"
    assert outs[6][0] == (2, 0, 0, 1, -7)


def test_regfile_array_elements():
    sim_reset()

    def step(r0, r1, w_addr, w_data, we):
        o = sim_call(
            regfile,
            regfile.p0_in_t(addr=r0, valid=1),
            regfile.p1_in_t(addr=r1, valid=1),
            regfile.p2_in_t(addr=w_addr, wr_data=w_data, wr_en=we, valid=1),
        )
        return plain(o.p0.rd_data), plain(o.p1.rd_data), plain(o.p2.wr_data)

    assert step(3, 0, 3, [1, 2, 3, 4], 1) == ([0, 0, 0, 0], [0, 0, 0, 0], [1, 2, 3, 4])
    assert step(3, 2, 2, [9, 9, 9, 9], 1) == ([1, 2, 3, 4], [0, 0, 0, 0], [9, 9, 9, 9])
    assert step(2, 3, 0, [0, 0, 0, 0], 0) == ([9, 9, 9, 9], [1, 2, 3, 4], [0, 0, 0, 0])


def test_byte_write_enables():
    sim_reset()

    def step(addr, data, en):
        return sim_call(cpu_mem, cpu_mem.p0_in_t(addr=addr, wr_data=data, wr_en=en, valid=1))

    step(0, 0xAABBCCDD, [1, 0, 1, 0])  # bytes 0 and 2
    step(0, 0, [0, 0, 0, 0])
    o = step(1, 0xFFFFFFFF, [0, 0, 0, 1])  # read address 0; write only byte 3 of address 1
    assert int(o.p0.rd_data) == 0x11BB33DD, hex(int(o.p0.rd_data))
    step(1, 0, [0, 0, 0, 0])
    o = step(0, 0, [0, 0, 0, 0])
    assert int(o.p0.rd_data) == 0xFF000000, hex(int(o.p0.rd_data))
    assert plain(o.p0.wr_en) == [0, 0, 0, 0]


def test_rom_of_strings():
    sim_reset()
    got = []
    for addr in (0, 1, 2, 0):
        o = sim_call(rom, rom.p0_in_t(addr=addr, valid=1))
        got.append(str(o.p0.rd_data))
    assert got[1:] == ["boot", "run", "halt"], got


def test_init_forms():
    sim_reset()
    r, _ = make_ram(pixel_t, 3, ports=("r",), read_latency=0, init=[{"level": 3}, (color_t.GREEN, 5, 1)])
    assert plain(sim_call(r, r.p0_in_t(addr=0, valid=1)).p0.rd_data) == (0, 3, 0)
    assert plain(sim_call(r, r.p0_in_t(addr=1, valid=1)).p0.rd_data) == (1, 5, 1)
    assert plain(sim_call(r, r.p0_in_t(addr=2, valid=1)).p0.rd_data) == (0, 0, 0)
    wrapped, _ = make_ram(uint8_t, 4, ports=("r",), read_latency=0, init=range(250, 254))
    assert int(sim_call(wrapped, wrapped.p0_in_t(addr=3, valid=1)).p0.rd_data) == 253
    masked, _ = make_ram(uint4_t, 2, ports=("r",), read_latency=0, init=[0x1F])
    assert int(sim_call(masked, masked.p0_in_t(addr=0, valid=1)).p0.rd_data) == 0xF


def test_factory_validation():
    expect_raises(ValueError, make_ram, uint8_t, 0)
    expect_raises(ValueError, make_ram, uint8_t, 4, ports=())
    expect_raises(ValueError, make_ram, uint8_t, 4, ports=("rx",))
    expect_raises(ValueError, make_ram, uint8_t, 4, read_latency=2)
    expect_raises(ValueError, make_ram, uint8_t, 4, in_regs=-1)
    expect_raises(ValueError, make_ram, uint8_t, 4, out_regs=True)
    expect_raises(TypeError, make_ram, int, 4)
    expect_raises(ValueError, make_ram, uint8_t, 2, init=[1, 2, 3])
    expect_raises(ValueError, make_ram, uint8_t, 2, init={2: 1})
    expect_raises(TypeError, make_ram, uint8_t, 2, init=[1.5])
    expect_raises(ValueError, make_ram, uint8_t[4], 2, init=[[1, 2]])
    expect_raises(ValueError, make_ram, pixel_t, 2, init=[{"bogus": 1}])
    expect_raises(ValueError, make_ram, uint4_t, 2, byte_write_enables=True)
    expect_raises(ValueError, make_ram, pixel_t, 2, byte_write_enables=True)
    expect_raises(ValueError, make_ram, uint16_t, 2, ports=("r",), byte_write_enables=True)


def test_two_call_sites_are_two_rams_and_reset_restores_init():
    sim_reset()
    got = [int(sim_call(two_instances, x)) for x in (7, 8, 9, 10)]
    # The first call site writes address 5 every cycle and reads it back;
    # the second only reads address 5 of ITS OWN memory, which stays zero.
    assert got == [0, 0, 7 << 16, 8 << 16], [hex(g) for g in got]
    sim_call(sp_ram, sp_ram.p0_in_t(addr=0, wr_data=1, wr_en=1, valid=1))
    sim_reset()
    sim_call(sp_ram, sp_ram.p0_in_t(addr=0, wr_data=0, wr_en=0, valid=1))
    o = sim_call(sp_ram, sp_ram.p0_in_t(addr=0, wr_data=0, wr_en=0, valid=0))
    assert int(o.p0.rd_data) == 10, "sim_reset restores the initial contents"


def test_reevaluation_commits_only_the_final_writes():
    """pypeline_sim.py re-evaluates a model several times per cycle while wires
    converge. Only the last evaluation's writes may land, exactly once."""
    import pypeline as p

    stale = pixel_t(color=color_t.RED, level=1, lit=1)
    final = pixel_t(color=color_t.GREEN, level=2, lit=0)
    sim_reset()
    p._sim_active = True
    p._sim_reg_begin_buffer()
    try:
        sim_call(lut_ram, lut_ram.p0_in_t(addr=1, wr_data=stale, wr_en=1, valid=1), lut_ram.p1_in_t(addr=0, valid=1))
        sim_call(lut_ram, lut_ram.p0_in_t(addr=2, wr_data=final, wr_en=1, valid=1), lut_ram.p1_in_t(addr=0, valid=1))
    finally:
        p._sim_reg_flush_buffer()
        p._sim_active = False
    o = sim_call(lut_ram, lut_ram.p0_in_t(addr=0, wr_data=stale, wr_en=0, valid=1), lut_ram.p1_in_t(addr=1, valid=1))
    assert plain(o.p1.rd_data) == (0, 0, 0), "the discarded evaluation's write must not land"
    o = sim_call(lut_ram, lut_ram.p0_in_t(addr=0, wr_data=stale, wr_en=0, valid=1), lut_ram.p1_in_t(addr=2, valid=1))
    assert plain(o.p1.rd_data) == plain(final)


def test_stateful_caller_uses_physical_output():
    sim_reset()
    got = [int(sim_call(stateful_writer, v)) for v in (10, 20, 30, 40)]
    assert got == [0, 0, 10, 20], got


def test_pure_caller_is_aligned():
    sim_reset()
    got = [int(sim_call(pure_lookup_plus, v)) for v in (1, 2, 3, 4, 5, 6)]
    # The compiler delays `x` to meet the 2-clock read: rom[x(t-2)] + x(t-2).
    assert got[2:] == [11, 22, 33, 44], got


def _reference_soak(ram, size, steps, make_request, apply_write, seed):
    """Drive `ram` with random requests and compare every output field against
    the contract, computed without any stage bookkeeping."""
    rng = random.Random(seed)
    n = len(ram.ports)
    latency = ram.latency
    requests = [[make_request(rng, kind) for kind in ram.ports] for _ in range(steps)]
    mem_before = []
    mem = list(ram_init_snapshot(ram, size))
    for cycle in range(steps):
        mem_before.append(list(mem))
        for i, kind in enumerate(ram.ports):
            req = requests[cycle][i]
            if kind != "r" and req["valid"]:
                apply_write(mem, req["addr"] % size, req)
    sim_reset()
    for cycle in range(steps):
        args = [ram.in_ts[i](**requests[cycle][i]) for i in range(n)]
        out = sim_call(ram, *args)
        for i, kind in enumerate(ram.ports):
            got = plain(getattr(out, f"p{i}"))
            if cycle < latency:
                # Warm-up: the stage registers still hold their zero power-on value.
                assert got[ram.out_ts[i]._fields.index("valid")] == 0, (cycle, i, got)
                continue
            req = requests[cycle - latency][i]
            want = {f: plain_input(v) for f, v in req.items()}
            if kind != "w":
                want["rd_data"] = mem_before[cycle - latency][req["addr"] % size]
            expected = tuple(want[f] for f in ram.out_ts[i]._fields)
            assert got == expected, (ram.__name__, cycle, i, got, expected)


def plain_input(v):
    if isinstance(v, (list, tuple)) and not hasattr(v, "_fields"):
        return [plain_input(x) for x in v]
    if isinstance(v, tuple):
        return plain(v)
    return int(v)


def ram_init_snapshot(ram, size):
    """The initial contents, read back through a fresh model (comb or not)."""
    return [plain(v) for v in ram._sim_model_cell[0][0]().mem]


def test_reference_soak_latency3_signed():
    def make_request(rng, kind):
        return dict(
            addr=rng.randrange(8),
            wr_data=rng.randrange(-32768, 32768),
            wr_en=rng.randrange(2),
            valid=rng.randrange(4) != 0,
        )

    def apply_write(mem, addr, req):
        if req["wr_en"]:
            mem[addr] = req["wr_data"]

    _reference_soak(tdp_ram, 8, 300, make_request, apply_write, seed=1)


def test_reference_soak_byte_enables():
    def make_request(rng, kind):
        return dict(
            addr=rng.randrange(4),
            wr_data=rng.randrange(1 << 32),
            wr_en=[rng.randrange(2) for _ in range(4)],
            valid=rng.randrange(3) != 0,
        )

    def apply_write(mem, addr, req):
        for j, en in enumerate(req["wr_en"]):
            if en:
                mask = 0xFF << (8 * j)
                mem[addr] = (mem[addr] & ~mask) | (req["wr_data"] & mask)

    _reference_soak(cpu_mem, 4, 300, make_request, apply_write, seed=2)


def test_reference_soak_comb_arrays_and_structs():
    def make_array_request(rng, kind):
        req = dict(addr=rng.randrange(4), valid=rng.randrange(4) != 0)
        if kind != "r":
            req.update(wr_data=[rng.randrange(256) for _ in range(4)], wr_en=rng.randrange(2))
        return req

    def apply_write(mem, addr, req):
        if req["wr_en"]:
            mem[addr] = plain_input(req["wr_data"])

    _reference_soak(regfile, 4, 200, make_array_request, apply_write, seed=3)

    def make_pixel_request(rng, kind):
        req = dict(addr=rng.randrange(16), valid=rng.randrange(4) != 0)
        if kind != "r":
            req.update(
                wr_data=pixel_t(color=rng.randrange(3), level=rng.randrange(16), lit=rng.randrange(2)),
                wr_en=rng.randrange(2),
            )
        return req

    _reference_soak(lut_ram, 10, 200, make_pixel_request, apply_write, seed=4)


def test_file_parse_metadata():
    """Elaborating this file records every generated RAM with its latency."""
    code = """
import sys
import PY_TO_LOGIC as py
state = py.PARSE_FILE(sys.argv[1])
rams = {}
for name, fn in state.pypeline_entity_callables.items():
    cycles = getattr(fn, '_pipeline_latency', None)
    if cycles is not None:
        assert state.func_fixed_latency[name] == cycles, name
        if name.startswith('ram_'):
            rams[name] = cycles
assert len(rams) == 8 and sorted(rams.values()) == [0, 0, 1, 1, 1, 2, 2, 3], rams
print('fixed latency RAMs:', rams)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, os.path.abspath(__file__)],
        env=dict(
            os.environ,
            PYTHONPATH=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0, result.stdout


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
