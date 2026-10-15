# pyright: reportInvalidTypeForm=none
"""Fixed RAM geometry must agree in native and HDL, including a late PART."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
from pypeline import (
    MAIN,
    PART,
    param,
    Reg,
    uint16_t,
    uint32_t,
    sim_assert,
    sim_print,
    sim_finish,
)
from ram import make_auto_pipeline_ram

ram = make_auto_pipeline_ram(uint32_t, 1024, ports=("w", "r"), latency=7)

GAP = ram.read_after_write_gap
if param("RAM_TARGET_IN_SOURCE", True):
    PART("xc7a200tffg1156-2")


@MAIN(125.0)
def self_check_auto_pipeline_ram_target() -> uint32_t:
    tick: Reg[uint16_t]
    checked: Reg[uint16_t]
    last: Reg[uint32_t]
    result = ram(
        ram.p0_in_t(addr=17, wr_data=99, wr_en=1, valid=tick == 0),
        ram.p1_in_t(addr=17, valid=tick == GAP),
    )
    if result.p1.valid:
        sim_assert(result.p1.rd_data == 99, "fixed RAM dependent read")
        sim_print(f"target RAM {GAP} {result.p1.rd_data}", debug=True)
        checked += 1
        last = result.p1.rd_data
    if tick == 25:
        sim_assert(checked == 1, "fixed RAM response count")
        sim_finish()
    tick += 1
    return last
