# pyright: reportInvalidTypeForm=none
"""Self-checking make_ram / make_stream_ram design, diffed cycle by cycle
between native simulation and real GHDL (native_vs_vhdl_sim_tests.py, with
and without --comb; also run natively in native_sim_tests.py).

`make_ram`'s VHDL and its Python model are maintained side by side, so this is
where the two must agree exactly:

  1. init readback: ROMs of uint1_t, int1_t, a 64-bit signed value, an @enum,
     a struct holding an enum and a uint1_t, a 2-D array, char_t[8], fixed and
     float point -- each generated from Python values -- at latencies 0 to 3,
     plus two same-shaped RAMs with different contents (distinct entities);
  2. two read+write ports with input and output registers (latency 3):
     pass-through fields, read-first reads, written data read back;
     and per-byte write enables;
  3. a PURE @MAIN reading a @pipeline_latency RAM: the compiler aligns the
     address with the 2-clock read, the stateful checker verifies the pair;
  4. a stream RAM under toggling backpressure: every response, in order.

Probes follow the native_vs_vhdl rules: every debug print is in the stateful
checker, valid-gated, below 2**31, and never on the sim_finish() cycle.
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
from enum import IntEnum
from typing import NamedTuple

from pypeline import (
    MAIN,
    Reg,
    Wire,
    char_t,
    enum,
    int16_t,
    int64_t,
    make_int_t,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint2_t,
    uint4_t,
    uint8_t,
    uint16_t,
    uint32_t,
)

from fixed_point import make_fixed_t
from floating_point import make_float_t
from ram import make_ram
from stream.stream_ram import make_stream_ram

int1_t = make_int_t(1)
fix_t = make_fixed_t(4, 4)
flt_t = make_float_t(5, 10)


@enum
class mode_t(IntEnum):
    IDLE = 0
    RUN = 1
    HALT = 2


@struct
class flags_t(NamedTuple):
    mode: mode_t
    armed: uint1_t
    count: uint4_t


# ── 1. ROMs generated from Python values ──

bit_rom, bit_rom_out_t = make_ram(uint1_t, 4, ports=("r",), read_latency=0, init=[1, 0, 1, 1])
sbit_rom, sbit_rom_out_t = make_ram(int1_t, 4, ports=("r",), read_latency=1, init=[-1, 0, -1, 0])
wide_rom, wide_rom_out_t = make_ram(
    int64_t, 4, ports=("r",), read_latency=1, in_regs=1, out_regs=1,
    init=[-5, 1 << 40, -(1 << 62), 7],
)
mode_rom, mode_rom_out_t = make_ram(mode_t, 4, ports=("r",), read_latency=0, init=[mode_t.HALT, mode_t.RUN])
flags_rom, flags_rom_out_t = make_ram(
    flags_t, 4, ports=("r",), read_latency=1,
    init=[{"mode": mode_t.RUN, "armed": 1, "count": 9}, {"mode": mode_t.HALT, "count": 15}],
)
grid_rom, grid_rom_out_t = make_ram(
    uint8_t[4][2], 4, ports=("r",), read_latency=0, init=[[[1, 2], [3, 4], [5, 6], [7, 8]]]
)
text_rom, text_rom_out_t = make_ram(char_t[8], 4, ports=("r",), read_latency=1, init=["boot", "run"])
fix_rom, fix_rom_out_t = make_ram(fix_t, 4, ports=("r",), read_latency=1, init=[{"val": -3}, {"val": 100}])
flt_rom, flt_rom_out_t = make_ram(flt_t, 4, ports=("r",), read_latency=1, init=[{"sign": 1, "exp": 17, "man": 513}])
twin_a, twin_a_out_t = make_ram(uint8_t, 4, ports=("r",), read_latency=1, init=[10, 20, 30, 40])
twin_b, twin_b_out_t = make_ram(uint8_t, 4, ports=("r",), read_latency=1, init=[40, 30, 20, 10])

bit_rom_in_t = bit_rom.p0_in_t
sbit_rom_in_t = sbit_rom.p0_in_t
wide_rom_in_t = wide_rom.p0_in_t
mode_rom_in_t = mode_rom.p0_in_t
flags_rom_in_t = flags_rom.p0_in_t
grid_rom_in_t = grid_rom.p0_in_t
text_rom_in_t = text_rom.p0_in_t
fix_rom_in_t = fix_rom.p0_in_t
flt_rom_in_t = flt_rom.p0_in_t
twin_a_in_t = twin_a.p0_in_t
twin_b_in_t = twin_b.p0_in_t

# ── 2. Read/write traffic ──

tdp_ram, tdp_ram_out_t = make_ram(
    uint16_t, 8, ports=("rw", "r"), read_latency=1, in_regs=1, out_regs=1, init=[5, 6, 7, 8]
)
tdp_p0_in_t = tdp_ram.p0_in_t
tdp_p1_in_t = tdp_ram.p1_in_t
bwe_ram, bwe_ram_out_t = make_ram(uint32_t, 4, ports=("rw",), read_latency=1, byte_write_enables=True)
bwe_in_t = bwe_ram.p0_in_t

# ── 3. A pure MAIN aligned around a fixed-latency RAM ──

square_rom, square_rom_out_t = make_ram(
    uint16_t, 16, ports=("r",), read_latency=1, out_regs=1, init=[i * i for i in range(16)]
)
square_in_t = square_rom.p0_in_t


@struct
class lookup_t(NamedTuple):
    addr: uint8_t
    square: uint16_t
    valid: uint1_t


lookup_addr: Wire[uint8_t]
lookup_valid: Wire[uint1_t]
lookup_result: Wire[lookup_t]


@MAIN(100.0)
def self_check_ram_lookup():
    req: square_in_t
    req.addr = lookup_addr
    req.valid = lookup_valid
    resp: square_rom_out_t = square_rom(req)
    result: lookup_t
    # The compiler delays lookup_addr/lookup_valid to meet the 2-clock read.
    result.addr = lookup_addr
    result.square = resp.p0.rd_data
    result.valid = lookup_valid
    lookup_result = result


# ── 4. Stream RAM ──

sram, sram_t = make_stream_ram(uint16_t, 16, ports=("rw",), read_latency=1, out_regs=1)
sram_req_payload_t = sram.p0_req_t
sram_req_stream_t = sram.p0_req_intrf.stream_t
sram_req_fwd_t = sram.p0_req_intrf.fwd_t
sram_resp_fb_t = sram.p0_resp_intrf.fb_t
sram_resp_stream_t = sram.p0_resp_intrf.stream_t


@MAIN
def self_check_ram_checker() -> lookup_t:
    c: Reg[uint8_t]
    done: Reg[uint1_t]
    rom_done: Reg[uint1_t]
    traffic_done: Reg[uint1_t]
    lookups_seen: Reg[uint8_t]
    req_idx: Reg[uint8_t]
    resp_idx: Reg[uint8_t]
    if done:
        sim_finish()

    # ── 1. ROM readback: address c, checked `latency` cycles later ──
    a: uint2_t = c
    bit_req: bit_rom_in_t
    bit_req.addr = a
    bit_req.valid = 1
    bit_resp: bit_rom_out_t = bit_rom(bit_req)
    sbit_req: sbit_rom_in_t
    sbit_req.addr = a
    sbit_req.valid = 1
    sbit_resp: sbit_rom_out_t = sbit_rom(sbit_req)
    wide_req: wide_rom_in_t
    wide_req.addr = a
    wide_req.valid = 1
    wide_resp: wide_rom_out_t = wide_rom(wide_req)
    mode_req: mode_rom_in_t
    mode_req.addr = a
    mode_req.valid = 1
    mode_resp: mode_rom_out_t = mode_rom(mode_req)
    flags_req: flags_rom_in_t
    flags_req.addr = a
    flags_req.valid = 1
    flags_resp: flags_rom_out_t = flags_rom(flags_req)
    grid_req: grid_rom_in_t
    grid_req.addr = a
    grid_req.valid = 1
    grid_resp: grid_rom_out_t = grid_rom(grid_req)
    text_req: text_rom_in_t
    text_req.addr = a
    text_req.valid = 1
    text_resp: text_rom_out_t = text_rom(text_req)
    fix_req: fix_rom_in_t
    fix_req.addr = a
    fix_req.valid = 1
    fix_resp: fix_rom_out_t = fix_rom(fix_req)
    flt_req: flt_rom_in_t
    flt_req.addr = a
    flt_req.valid = 1
    flt_resp: flt_rom_out_t = flt_rom(flt_req)
    twin_a_req: twin_a_in_t
    twin_a_req.addr = a
    twin_a_req.valid = 1
    twin_a_resp: twin_a_out_t = twin_a(twin_a_req)
    twin_b_req: twin_b_in_t
    twin_b_req.addr = a
    twin_b_req.valid = 1
    twin_b_resp: twin_b_out_t = twin_b(twin_b_req)

    a1: uint2_t = c - 1
    a3: uint2_t = c - 3
    bit_exp: uint1_t[4] = [1, 0, 1, 1]
    sbit_exp: int1_t[4] = [-1, 0, -1, 0]
    wide_hi_exp: uint16_t[4] = [0xFFFF, 0, 0xC000, 0]
    wide_mid_exp: uint16_t[4] = [0xFFFF, 0x0100, 0, 0]
    wide_lo_exp: uint16_t[4] = [0xFFFB, 0, 0, 7]
    mode_exp: uint2_t[4] = [2, 1, 0, 0]
    flags_mode_exp: uint2_t[4] = [1, 2, 0, 0]
    flags_armed_exp: uint1_t[4] = [1, 0, 0, 0]
    flags_count_exp: uint4_t[4] = [9, 15, 0, 0]
    text_c0_exp: uint8_t[4] = [98, 114, 0, 0]
    text_c2_exp: uint8_t[4] = [111, 110, 0, 0]
    fix_exp: int16_t[4] = [-3, 100, 0, 0]
    twin_a_exp: uint8_t[4] = [10, 20, 30, 40]
    twin_b_exp: uint8_t[4] = [40, 30, 20, 10]

    wide: int64_t = wide_resp.p0.rd_data
    wide_hi: uint16_t = wide[63:48]
    wide_mid: uint16_t = wide[47:32]
    wide_lo: uint16_t = wide[15:0]
    mode_val: uint2_t = mode_resp.p0.rd_data
    flags_mode: uint2_t = flags_resp.p0.rd_data.mode
    grid: uint8_t[4][2] = grid_resp.p0.rd_data
    text: char_t[8] = text_resp.p0.rd_data
    fix_val: int16_t = fix_resp.p0.rd_data.val
    text0: uint8_t = text[0]

    if (c >= 3) & (c < 16) & ~rom_done:
        sim_assert(bit_resp.p0.rd_data == bit_exp[a], "uint1_t ROM")
        sim_assert(mode_val == mode_exp[a], "@enum ROM")
        grid_sum: uint16_t = grid[0][0] + grid[1][1] + grid[3][0] + grid[3][1]
        if a == 0:
            sim_assert(grid_sum == 1 + 4 + 7 + 8, "2-D array ROM")
        else:
            sim_assert(grid_sum == 0, "2-D array ROM zero tail")
        sim_assert(sbit_resp.p0.rd_data == sbit_exp[a1], "int1_t ROM")
        sim_assert(flags_mode == flags_mode_exp[a1], "struct enum field")
        sim_assert(flags_resp.p0.rd_data.armed == flags_armed_exp[a1], "struct uint1_t field")
        sim_assert(flags_resp.p0.rd_data.count == flags_count_exp[a1], "struct uint4_t field")
        sim_assert(text[0] == text_c0_exp[a1], "char_t[8] ROM")
        sim_assert(text[2] == text_c2_exp[a1], "char_t[8] ROM")
        sim_assert(fix_val == fix_exp[a1], "fixed point ROM")
        if a1 == 0:
            sim_assert(flt_resp.p0.rd_data.sign == 1, "float sign")
            sim_assert(flt_resp.p0.rd_data.exp == 17, "float exp")
            sim_assert(flt_resp.p0.rd_data.man == 513, "float man")
        sim_assert(twin_a_resp.p0.rd_data == twin_a_exp[a1], "twin a")
        sim_assert(twin_b_resp.p0.rd_data == twin_b_exp[a1], "twin b")
        sim_assert(wide_hi == wide_hi_exp[a3], "int64 ROM high bits")
        sim_assert(wide_mid == wide_mid_exp[a3], "int64 ROM middle bits")
        sim_assert(wide_lo == wide_lo_exp[a3], "int64 ROM low bits")
        sim_print(
            f"rom c={c} bit={bit_resp.p0.rd_data} mode={mode_val} grid={grid_sum} "
            f"flags={flags_mode} cnt={flags_resp.p0.rd_data.count} text0={text0} "
            f"twins={twin_a_resp.p0.rd_data},{twin_b_resp.p0.rd_data} "
            f"wide={wide_hi},{wide_mid},{wide_lo}",
            debug=True,
        )
    if c == 15:
        rom_done = 1

    # ── 2. Traffic on a latency-3 rw+r RAM, and byte write enables ──
    t: uint8_t = c - 16
    p0: tdp_p0_in_t
    p0.addr = t
    p0.wr_data = t + 100
    p0.wr_en = 1
    p0.valid = (c >= 16) & (t < 8)
    p1: tdp_p1_in_t
    p1.addr = t
    if t >= 8:
        p1.addr = t - 8
    p1.valid = (c >= 16) & (t < 16)
    tdp: tdp_ram_out_t = tdp_ram(p0, p1)
    init_vals: uint16_t[8] = [5, 6, 7, 8, 0, 0, 0, 0]
    if (c >= 19) & (c < 35) & ~traffic_done:
        r: uint8_t = c - 19
        if r < 8:
            sim_assert(tdp.p0.valid == 1, "p0 valid")
            sim_assert(tdp.p0.addr == r, "p0 addr echo")
            sim_assert(tdp.p0.wr_data == r + 100, "p0 wr_data echo")
            sim_assert(tdp.p0.rd_data == init_vals[r], "p0 read-first")
            sim_assert(tdp.p1.rd_data == init_vals[r], "p1 same-edge read-first")
        else:
            sim_assert(tdp.p0.valid == 0, "p0 idle")
            sim_assert(tdp.p1.rd_data == r - 8 + 100, "p1 reads written data")
        sim_print(
            f"tdp c={c} p0v={tdp.p0.valid} p0a={tdp.p0.addr} p0rd={tdp.p0.rd_data} "
            f"p1v={tdp.p1.valid} p1a={tdp.p1.addr} p1rd={tdp.p1.rd_data}",
            debug=True,
        )

    bw: bwe_in_t
    bw.addr = 1
    bw.valid = 1
    bw.wr_data = 0
    bw.wr_en = [0, 0, 0, 0]
    if c == 16:
        bw.wr_data = 0x2ABBCCDD
        bw.wr_en = [1, 1, 1, 1]
    if c == 17:
        bw.wr_data = 0x11223344
        bw.wr_en = [1, 0, 0, 1]
    bwe: bwe_ram_out_t = bwe_ram(bw)
    if (c == 19) & ~traffic_done:
        sim_assert(bwe.p0.rd_data == 0x11BBCC44, "byte write enables")
        sim_print(f"bwe c={c} rd={bwe.p0.rd_data}", debug=True)
    if c == 34:
        traffic_done = 1

    # ── 3. Drive the pure lookup MAIN and check its aligned result ──
    lookup_addr = c
    lookup_valid = (c >= 1) & (c < 40)
    result: lookup_t = lookup_result
    if result.valid & ~done:
        square_exp: uint16_t[16] = [i * i for i in range(16)]
        idx: uint4_t = result.addr
        sim_assert(result.square == square_exp[idx], "pure caller alignment")
        sim_print(f"lookup addr={result.addr} square={result.square}", debug=True)
        lookups_seen += 1

    # ── 4. Stream RAM: 8 writes then 8 reads, ready low every third cycle ──
    req_s: sram_req_stream_t
    req_s.valid = (c >= 4) & (req_idx < 16)
    # Writes go to addresses 0..7, then the reads come back for 0..7.
    req_s.data.addr = req_idx
    if req_idx >= 8:
        req_s.data.addr = req_idx - 8
    req_s.data.wr_data = req_idx + 50
    req_s.data.wr_en = req_idx < 8
    resp_ready: uint1_t = (c % 3) != 0
    sr: sram_t = sram(sram_req_fwd_t(stream=req_s), sram_resp_fb_t(ready=resp_ready))
    resp_s: sram_resp_stream_t = sr.p0_resp_if.stream
    if req_s.valid & sr.p0_req_if.ready:
        req_idx += 1
    if resp_s.valid & resp_ready & ~done:
        k: uint4_t = resp_idx
        if resp_idx < 8:
            sim_assert(resp_s.data.addr == k, "stream write response order")
            sim_assert(resp_s.data.wr_en == 1, "stream write echo")
            sim_assert(resp_s.data.rd_data == 0, "stream write read-first")
        else:
            k8: uint4_t = resp_idx - 8
            sim_assert(resp_s.data.addr == k8, "stream read response order")
            sim_assert(resp_s.data.wr_en == 0, "stream read echo")
            sim_assert(resp_s.data.rd_data == k8 + 50, "stream read back")
        sim_print(
            f"stream c={c} addr={resp_s.data.addr} we={resp_s.data.wr_en} rd={resp_s.data.rd_data}",
            debug=True,
        )
        resp_idx += 1

    sim_assert(c < 120, "self_check_ram did not finish")
    if rom_done & traffic_done & (resp_idx == 16) & (lookups_seen >= 30):
        done = 1
    c += 1
    # A top-level output keeps this logic (and the RAM path behind it) in the
    # synthesized netlist: a design with no outputs optimizes away entirely,
    # and the pipelined build's timing analysis then has nothing to measure.
    return result
