# pyright: reportInvalidTypeForm=none
"""NCO and log ROM latency alignment, bubbles and CE in native and GHDL."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
import pypeline as py
from pypeline import (
    MAIN,
    Reg,
    param,
    int16_t,
    uint1_t,
    uint16_t,
    uint32_t,
    sim_assert,
    sim_print,
    sim_finish,
)
from fixed_point import make_fixed_t
from dsp.nco import make_lut_nco, golden_lut_nco
from dsp.log2_db import make_log2_db, golden_log2_db
from AUTO_PIPELINE import RamPlan

power_t = make_fixed_t(34, 12, signed=True)
nco = make_lut_nco(int16_t)
log = make_log2_db(power_t)
swap = param("DSP_ROM_SWAP", False)
py.SET_AUTO_PIPELINE_RAM_PLAN_CACHE(
    {
        nco.rom._auto_pipeline_ram["key"]: RamPlan(1, 2),
        log.log_rom._auto_pipeline_ram["key"]: RamPlan(0, 0 if swap else 3),
        log.exp_rom._auto_pipeline_ram["key"]: RamPlan(0, 3 if swap else 0),
    }
)
nco = make_lut_nco(int16_t)
log = make_log2_db(power_t)
PHASE = tuple((i * 177777777) & 0xFFFFFFFF for i in range(32))
AMP = tuple(i * 1777 - 32768 for i in range(32))
POWER = tuple([-100, 0, 1, 4096] + [(i + 1) * 91919 for i in range(28)])
I = tuple(golden_lut_nco(nco, ph, amp)[0] for ph, amp in zip(PHASE, AMP))
Q = tuple(golden_lut_nco(nco, ph, amp)[1] for ph, amp in zip(PHASE, AMP))
DB = tuple(golden_log2_db(log, raw)[0] for raw in POWER)
FLOOR = tuple(int(raw <= 0) for raw in POWER)


@MAIN(125.0)
def self_check_dsp_rom() -> uint16_t:
    phases: uint32_t[32] = PHASE
    amps: int16_t[32] = AMP
    powers: py.int32_t[32] = POWER
    exp_i: int16_t[32] = I
    exp_q: int16_t[32] = Q
    exp_db: int16_t[32] = DB
    exp_floor: uint1_t[32] = FLOOR
    tick: Reg[uint16_t]
    sent: Reg[uint16_t]
    n_received: Reg[uint16_t]
    l_received: Reg[uint16_t]
    last: Reg[uint16_t]
    rst: uint1_t = (tick >= 5) & (tick < 30)
    if (tick & 3) != 1:
        active: uint1_t = ~rst & (sent < 32) & ((tick & 7) != 3)
        idx: uint16_t = sent & 31
        nr = nco(phases[idx], amps[idx], active, rst)
        lr = log(power_t(val=powers[idx]), active, rst)
        sim_assert(~(rst & (nr.valid | lr.valid)), "DSP response leaked during reset")
        if active:
            sent += 1
        if nr.valid:
            sim_assert(nr.i == exp_i[n_received & 31], "NCO selected ROM latency I")
            sim_assert(nr.q == exp_q[n_received & 31], "NCO selected ROM latency Q")
            sim_print(f"nco {nr.i} {nr.q}", debug=True)
            n_received += 1
        if lr.valid:
            sim_assert(lr.db == exp_db[l_received & 31], "unequal log ROM data")
            sim_assert(
                lr.floored == exp_floor[l_received & 31], "unequal log ROM floor"
            )
            sim_print(f"log {lr.db} {lr.floored}", debug=True)
            l_received += 1
            last = lr.db
    if rst:
        sent = 0
        n_received = 0
        l_received = 0
    if tick == 140:
        sim_assert(n_received == 32, "NCO response count")
        sim_assert(l_received == 32, "log response count")
        sim_finish()
    tick += 1
    return last
