# pyright: reportInvalidTypeForm=none
"""A 4096 x 32 write/read RAM under reset_registers="all", for
ram_reset_inference_test.py: -D RAM_RESET_KIND=plain builds make_ram (an input
register, the memory read register and an output register), =auto builds
make_auto_pipeline_ram at a fixed latency of 3."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
from pypeline import MAIN, Input, make_clock, make_reset, param, uint1_t, uint32_t
from ram import make_auto_pipeline_ram, make_ram

KIND = param("RAM_RESET_KIND", "plain")
if KIND == "plain":
    ram = make_ram(uint32_t, 4096, ports=("w", "r"), read_latency=1, in_regs=1, out_regs=1)
else:
    ram = make_auto_pipeline_ram(uint32_t, 4096, ports=("w", "r"), latency=3)
p0_t, p1_t = ram.p0_in_t, ram.p1_in_t
out_t = ram.return_t

rst: Input[uint1_t] = make_reset()
clk = make_clock(80.0, reset=rst)


@MAIN(clk, reset_registers="all")
def ram_reset_inference_design(p0: p0_t, p1: p1_t) -> out_t:
    return ram(p0, p1)
