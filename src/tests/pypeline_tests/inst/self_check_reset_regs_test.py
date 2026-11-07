# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test of synchronous resets of user registers. Two
resets on one clock: the pin rst, the clock's primary reset, which the
harness pulses in cycle 0, and gen_rst, a Wire made by the MAIN rst_gen, which
pulses it in cycle RESET_AT.

- dut_all (reset_registers="all", reset=gen_rst) resets scalar, signed,
  array, struct and enum registers to their initializers, keeps its
  Reg[T, NO_RESET] counting, and resets a clock-enabled callee in the very
  cycle its call is skipped (reset before clock enable).
- dut_req (the default "requested", on clk.reset) resets only its
  Reg[T, RESET] in cycle 0 and keeps a plain register counting; it also
  calls the callee dut_all calls, which is one entity reset under dut_all
  and another without reset under dut_req.
- checker mirrors every register with ordinary logic: `if rst:` (a manual
  reset, reading the pin as data) and the cycle number of gen_rst, and
  asserts each DUT value equals its mirror.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from typing import NamedTuple

from pypeline import (
    MAIN,
    NO_RESET,
    RESET,
    Input,
    Reg,
    Wire,
    enum,
    hw_func,
    int8_t,
    make_clock,
    make_reset,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint8_t,
)

RESET_AT = 7  # odd: the clock-enabled call of counter is skipped then
N_CYCLES = 14


@struct
class pt_t(NamedTuple):
    x: uint8_t
    y: int8_t


@enum
class color_t:
    RED = 0
    GREEN = 1
    BLUE = 2


rst: Input[uint1_t] = make_reset()
clk = make_clock(100.0, reset=rst)
gen_rst: Wire[uint1_t] = make_reset()

t_out: Wire[uint8_t]
s_out: Wire[int8_t]
a_out: Wire[uint8_t[3]]
p_out: Wire[pt_t]
c_out: Wire[color_t]
h_out: Wire[uint8_t]
cnt_all_out: Wire[uint8_t]
pc_out: Wire[uint8_t]
plain_out: Wire[uint8_t]
cnt_req_out: Wire[uint8_t]


@MAIN(clk)
def rst_gen():
    t: Reg[uint8_t]
    gen_rst = t == RESET_AT
    t_out = t
    t = t + 1


@hw_func
def counter() -> uint8_t:
    count: Reg[uint8_t] = 3
    rv: uint8_t = count
    count = count + 1
    return rv


@MAIN(clk, reset=gen_rst, reset_registers="all")
def dut_all():
    s: Reg[int8_t] = -5
    a: Reg[uint8_t[3]] = [1, 2, 3]
    p: Reg[pt_t] = pt_t(x=4, y=-2)
    c: Reg[color_t] = color_t.BLUE
    h: Reg[uint8_t, NO_RESET]
    s_out = s
    a_out = a
    p_out = p
    c_out = c
    h_out = h
    # Called only in even cycles; in odd cycles its registers hold, and in
    # cycle RESET_AT (odd) they reset all the same
    cnt: uint8_t = 0
    if (t_out & 1) == 0:
        cnt = counter()
    cnt_all_out = cnt
    s = s + 1
    a[0] = a[0] + 1
    a[2] = a[2] + 2
    p.x = p.x + 1
    p.y = p.y - 1
    if c == color_t.BLUE:
        c = color_t.RED
    elif c == color_t.RED:
        c = color_t.GREEN
    else:
        c = color_t.BLUE
    h = h + 1


@MAIN(clk)
def dut_req():
    pc: Reg[uint8_t, RESET] = 7
    plain: Reg[uint8_t] = 1
    pc_out = pc
    plain_out = plain
    cnt_req_out = counter()
    pc = pc + 1
    plain = plain + 1


@MAIN(clk)
def checker():
    # Mirrors with ordinary logic: rst read as data (manual reset), gen_rst's
    # cycle by number
    m_pc: Reg[uint8_t] = 7
    m_plain: Reg[uint8_t] = 1
    m_cnt_req: Reg[uint8_t] = 3
    m_s: Reg[int8_t] = -5
    m_a0: Reg[uint8_t] = 1
    m_a2: Reg[uint8_t] = 3
    m_px: Reg[uint8_t] = 4
    m_py: Reg[int8_t] = -2
    m_c: Reg[uint8_t] = 2
    m_cnt_all: Reg[uint8_t] = 3
    t: uint8_t = t_out
    # Finish a cycle after the last print: a print and sim_finish() in one
    # cycle are not ordered in VHDL simulation
    if t == N_CYCLES + 1:
        sim_finish()
    sim_assert(pc_out == m_pc, f"pc {pc_out} != {m_pc} at {t}")
    sim_assert(plain_out == m_plain, f"plain {plain_out} != {m_plain} at {t}")
    sim_assert(cnt_req_out == m_cnt_req, f"cnt_req {cnt_req_out} != {m_cnt_req} at {t}")
    sim_assert(s_out == m_s, f"s {s_out} != {m_s} at {t}")
    sim_assert((a_out[0] == m_a0) & (a_out[1] == 2) & (a_out[2] == m_a2), f"a at {t}")
    sim_assert((p_out.x == m_px) & (p_out.y == m_py), f"p at {t}")
    c: uint8_t = 0
    if c_out == color_t.GREEN:
        c = 1
    elif c_out == color_t.BLUE:
        c = 2
    sim_assert(c == m_c, f"c {c} != {m_c} at {t}")
    sim_assert(h_out == t, f"NO_RESET h {h_out} != {t}")
    if (t & 1) == 0:
        sim_assert(cnt_all_out == m_cnt_all, f"cnt_all {cnt_all_out} != {m_cnt_all} at {t}")
    if t <= N_CYCLES:
        sim_print(
            f"t={t} pc={pc_out} plain={plain_out} s={s_out} a0={a_out[0]} px={p_out.x} "
            f"c={c} h={h_out} cnt_all={cnt_all_out} cnt_req={cnt_req_out}",
            debug=True,
        )
    # Next values: the clock's reset rst in cycle 0 resets pc only
    if rst:
        m_pc = 7
    else:
        m_pc = m_pc + 1
    m_plain = m_plain + 1
    m_cnt_req = m_cnt_req + 1
    # gen_rst in cycle RESET_AT resets everything in dut_all but h
    if t == RESET_AT:
        m_s = -5
        m_a0 = 1
        m_a2 = 3
        m_px = 4
        m_py = -2
        m_c = 2
        m_cnt_all = 3
    else:
        m_s = m_s + 1
        m_a0 = m_a0 + 1
        m_a2 = m_a2 + 2
        m_px = m_px + 1
        m_py = m_py - 1
        if m_c == 2:
            m_c = 0
        elif m_c == 0:
            m_c = 1
        else:
            m_c = 2
        if (t & 1) == 0:
            m_cnt_all = m_cnt_all + 1
