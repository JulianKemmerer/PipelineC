# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test of a synchronous reset of a RAM: dut calls a
make_ram(latency 2) every cycle under reset_registers="all", reset by
gen_rst, which rst_gen pulses in cycle RESET_AT. The stimulus and checks are
in MAINs that the reset does not reset.

    cycles 0-5   write address t with t + 1
    cycle 6      read address 2: answered in cycle 8, before the reset
    cycle 7      read address 3: in flight at the reset, never answered
    cycle 8      write address 0 with 99: the reset suppresses it
    cycles 9-14  read addresses 0-5 back: the memory kept its contents

So after the reset no response is valid for two cycles, and address 0 still
holds 1.

Registered in native_vs_vhdl_sim_tests.py (--comb), which diffs native and
cocotb+GHDL sim_print(debug=True) output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Reg,
    Wire,
    make_clock,
    make_reset,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
)
from ram import make_ram

RESET_AT = 8
N_CYCLES = 18

ram = make_ram(uint8_t, 8, ports=("rw",), read_latency=1, out_regs=1)

clk = make_clock(100.0)
gen_rst: Wire[uint1_t] = make_reset()
t_out: Wire[uint8_t]
ram_in: Wire[ram.p0_in_t]
ram_out: Wire[ram.p0_out_t]


@MAIN(clk)
def rst_gen():
    t: Reg[uint8_t]
    gen_rst = t == RESET_AT
    t_out = t
    t += 1


@MAIN(clk, reset=gen_rst, reset_registers="all")
def dut():
    o = ram(ram_in)
    ram_out = o.p0


@MAIN(clk)
def stimulus():
    t: uint8_t = t_out
    req: ram.p0_in_t
    req.valid = 0
    if t <= 5:
        req = ram.p0_in_t(addr=t, wr_data=t + 1, wr_en=1, valid=1)
    elif t == 6:
        req = ram.p0_in_t(addr=2, wr_data=0, wr_en=0, valid=1)
    elif t == 7:
        req = ram.p0_in_t(addr=3, wr_data=0, wr_en=0, valid=1)
    elif t == 8:
        req = ram.p0_in_t(addr=0, wr_data=99, wr_en=1, valid=1)
    elif t <= 14:
        req = ram.p0_in_t(addr=t - 9, wr_data=0, wr_en=0, valid=1)
    ram_in = req


@MAIN(clk)
def checker():
    t: uint8_t = t_out
    o: ram.p0_out_t = ram_out
    if t == N_CYCLES + 1:
        sim_finish()
    if t == 8:
        sim_assert(o.valid & (o.rd_data == 3), f"read before the reset: {o.rd_data}")
    if (t == 9) | (t == 10):
        sim_assert(o.valid == 0, f"a request in flight at the reset answered at {t}")
    if (t >= 11) & (t <= 16):
        sim_assert(o.valid == 1, f"missing read at {t}")
        sim_assert(o.rd_data == t - 10, f"address {t - 11} holds {o.rd_data}")
    if (t >= 8) & (t <= N_CYCLES):
        sim_print(f"t={t} valid={o.valid} addr={o.addr} rd={o.rd_data}", debug=True)
