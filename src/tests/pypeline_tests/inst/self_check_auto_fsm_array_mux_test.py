# pyright: reportInvalidTypeForm=none
"""Self-checking AUTO_FSM design whose shared unit takes and returns ARRAYS, so
its operand multiplexers select between whole `uint2_t[4]` values.

make_operand_mux(t, n) (include/pypeline/operators/auto_fsm_mux.py) once
declared its choices as `t[n]`. For an array `t` that appends an INNER
dimension (C order), so a 5-way mux over `uint2_t[4]` got `uint2_t[4][5]`
choices: native sim was fine and GHDL/Vivado rejected the generated VHDL. It
now uses make_array_t(t, n) -> `uint2_t[5][4]`.

Two checks, each with unequal dimensions (a square array hides the bug):
  * Direct muxes: 5- and 7-way over `uint2_t[4]`, plus scalar and struct
    controls, cycling every selector. Every lane value is a different function
    of (selector, lane, case), and the expected value is computed by
    arithmetic, not by indexing, so a swapped dimension or a truncated selector
    is caught.
  * AUTO_FSM: seven chained `lane_mix` calls share one unit (7 states). Its
    `b` port selects among 5 `uint2_t[4]` input fields -- the 5-way shape
    WireGuard's Poly1305 epilogue failed on -- its `a` port between the input
    and the one `uint2_t[4]` register the chain reuses, and `k` among 7 bytes.
    The result is checked against a table computed by plain Python at import.

Registered in native_vs_vhdl_sim_tests.py twice: --comb (direct muxes; the FSM
is a passthrough) and non---comb (the scheduled FSM). The testbench reacts to
`o.valid`, so it is correct at any latency.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]

from operators.auto_fsm_mux import make_operand_mux, mux_sel_t
from pypeline import (
    AUTO_FSM,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint2_t,
    uint4_t,
    uint6_t,
    uint8_t,
    uint16_t,
)

NUM_CASES = 35  # lcm(5, 7): every selector of both muxes, many lane values
N_K = 7
N_LANES = 4
lanes_t = uint2_t[N_LANES]


@struct
class pair_t(NamedTuple):
    a: uint4_t
    b: uint8_t


MUX5 = make_operand_mux(lanes_t, 5)
MUX7 = make_operand_mux(lanes_t, 7)
MUX_SCALAR = make_operand_mux(uint8_t, 5)
MUX_STRUCT = make_operand_mux(pair_t, 7)
choices5_t = MUX5.__annotations__["choices"]
choices7_t = MUX7.__annotations__["choices"]
choices_scalar_t = MUX_SCALAR.__annotations__["choices"]
choices_struct_t = MUX_STRUCT.__annotations__["choices"]
sel5_t = mux_sel_t(5)
sel7_t = mux_sel_t(7)


@struct
class chain_in_t(NamedTuple):
    p: lanes_t
    q: lanes_t
    r: lanes_t
    s: lanes_t
    u: lanes_t
    v: lanes_t
    k: uint8_t[N_K]


@hw_func
def lane_mix(a: lanes_t, b: lanes_t, k: uint8_t) -> lanes_t:
    """Lane-wise add of a, reversed b, and a byte of k*k: an 8x8 multiply,
    so the unit is worth sharing over its operand muxes."""
    m: uint16_t = k * k
    o: lanes_t
    for i in range(N_LANES):
        o[i] = a[i] + b[N_LANES - 1 - i] + (m >> (4 * i))
    return o


@hw_func
def chain(x: chain_in_t) -> lanes_t:
    """Seven dependent calls; `b` sees 5 distinct sources, `k` 7."""
    t0 = lane_mix(x.p, x.q, x.k[0])
    t1 = lane_mix(t0, x.r, x.k[1])
    t2 = lane_mix(t1, x.s, x.k[2])
    t3 = lane_mix(t2, x.u, x.k[3])
    t4 = lane_mix(t3, x.v, x.k[4])
    t5 = lane_mix(t4, x.q, x.k[5])
    t6 = lane_mix(t5, x.r, x.k[6])
    return t6


CHAIN_FSM = AUTO_FSM(chain)


# Plain-Python reference for the testbench inputs below.
def _in_lane(c, src, i):
    return (c * (src + 1) + 3 * i + src) & 3


def _in_k(c, j):
    return (c * 29 + j * 53 + 7) & 0xFF


def _ref_chain(c):
    srcs = [[_in_lane(c, s, i) for i in range(N_LANES)] for s in range(6)]
    p, q, r, s, u, v = srcs

    def mix(a, b, k):
        m = (k * k) & 0xFFFF
        return [
            (a[i] + b[N_LANES - 1 - i] + (m >> (4 * i))) & 3 for i in range(N_LANES)
        ]

    t = mix(p, q, _in_k(c, 0))
    for b, j in ((r, 1), (s, 2), (u, 3), (v, 4), (q, 5), (r, 6)):
        t = mix(t, b, _in_k(c, j))
    return sum(t[i] << (2 * i) for i in range(N_LANES))


EXPECTED_CHAIN = [_ref_chain(c) for c in range(NUM_CASES)]


# A different 2-bit function of the choice index k per lane; lanes 0 and 1
# together identify any index below 16. The testbench recomputes these from
# the selector with the same operators.
LANE_FIELD = [[k & 3, (k >> 2) & 3, ~k & 3, (k >> 1) & 3] for k in range(7)]


@MAIN(25.0)
def self_check_auto_fsm_array_mux() -> uint8_t:
    # A real output port keeps synthesis from deleting the logic.
    last: Reg[uint8_t]
    case_idx: Reg[uint6_t]
    busy: Reg[uint1_t]
    # case_idx % 5 and case_idx % 7, kept as counters.
    sel5: Reg[sel5_t]
    sel7: Reg[sel7_t]

    # ---- direct muxes, checked every cycle ----
    ch5: choices5_t
    ch7: choices7_t
    for k in range(7):
        for lane in range(N_LANES):
            if k < 5:
                ch5[k][lane] = LANE_FIELD[k][lane] + case_idx + lane
            ch7[k][lane] = LANE_FIELD[k][lane] + case_idx + 2 * lane
    got5 = MUX5(sel5, ch5)
    got7 = MUX7(sel7, ch7)
    want5: lanes_t
    want7: lanes_t
    want5[0] = (sel5 & 3) + case_idx
    want5[1] = (sel5 >> 2) + case_idx + 1
    want5[2] = (~sel5 & 3) + case_idx + 2
    want5[3] = (sel5 >> 1) + case_idx + 3
    want7[0] = (sel7 & 3) + case_idx
    want7[1] = (sel7 >> 2) + case_idx + 2
    want7[2] = (~sel7 & 3) + case_idx + 4
    want7[3] = (sel7 >> 1) + case_idx + 6
    for lane in range(N_LANES):
        sim_assert(got5[lane] == want5[lane], "5-way array mux lane mismatch")
        sim_assert(got7[lane] == want7[lane], "7-way array mux lane mismatch")

    chs: choices_scalar_t
    chp: choices_struct_t
    for k in range(7):
        if k < 5:
            chs[k] = k * 37 + case_idx
        chp[k].a = k + case_idx
        chp[k].b = k * 19 + case_idx
    got_s = MUX_SCALAR(sel5, chs)
    got_p = MUX_STRUCT(sel7, chp)
    want_s: uint8_t = sel5 * 37 + case_idx
    want_pa: uint4_t = sel7 + case_idx
    want_pb: uint8_t = sel7 * 19 + case_idx
    sim_assert(got_s == want_s, "scalar mux mismatch")
    sim_assert(got_p.a == want_pa, "struct mux field a mismatch")
    sim_assert(got_p.b == want_pb, "struct mux field b mismatch")

    # ---- AUTO_FSM sharing lane_mix ----
    x: chain_in_t
    for i in range(N_LANES):
        x.p[i] = case_idx * 1 + 3 * i + 0
        x.q[i] = case_idx * 2 + 3 * i + 1
        x.r[i] = case_idx * 3 + 3 * i + 2
        x.s[i] = case_idx * 4 + 3 * i + 3
        x.u[i] = case_idx * 5 + 3 * i + 4
        x.v[i] = case_idx * 6 + 3 * i + 5
    for j in range(N_K):
        x.k[j] = case_idx * 29 + j * 53 + 7

    s: CHAIN_FSM.in_stream_t
    s.data = x
    s.valid = 0
    if busy == 0:
        s.valid = 1
        busy = 1

    o = CHAIN_FSM(s)

    if o.valid:
        packed: uint8_t = 0
        for i in range(N_LANES):
            lane8: uint8_t = o.data[i]
            packed = packed | (lane8 << (2 * i))
        table: uint8_t[NUM_CASES] = EXPECTED_CHAIN
        want_chain: uint8_t = table[case_idx]
        sim_assert(packed == want_chain, "AUTO_FSM array-operand chain mismatch")
        last = packed ^ got_s ^ got_p.b ^ got5[1] ^ got7[2]
        busy = 0
        # No debug print on the sim_finish() cycle -- see self_check_counter_test.py.
        if case_idx < NUM_CASES - 1:
            sim_print(
                f"self_check_auto_fsm_array_mux case_idx={case_idx} chain={packed} "
                f"mux5={got5[1]} mux7={got7[2]} scalar={got_s} struct={got_p.b}",
                debug=True,
            )
        if case_idx == NUM_CASES - 1:
            sim_finish()
        case_idx += 1
        sel5 = 0 if sel5 == 4 else sel5 + 1
        sel7 = 0 if sel7 == 6 else sel7 + 1

    return last
