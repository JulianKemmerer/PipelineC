# pyright: reportInvalidTypeForm=none
"""Observable ECP5 RAM fixture; env controls the QoR/constraint test matrix."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
from pypeline import MAIN, uint32_t
from ram import make_auto_pipeline_ram


def optional_int(name):
    value = os.environ.get(name)
    return int(value) if value else None


ram, out_t = make_auto_pipeline_ram(
    uint32_t,
    int(os.environ.get("AUTO_PIPELINE_RAM_SIZE", "4096")),
    ports=tuple(os.environ.get("AUTO_PIPELINE_RAM_PORTS", "w,r").split(",")),
    latency=optional_int("AUTO_PIPELINE_RAM_LATENCY"),
    start_latency=optional_int("AUTO_PIPELINE_RAM_START"),
    max_latency=optional_int("AUTO_PIPELINE_RAM_MAX"),
    byte_write_enables=os.environ.get("AUTO_PIPELINE_RAM_BYTES") == "1",
    init={0: 123, 1023: 456},
)
p0_t, p1_t = ram.p0_in_t, ram.p1_in_t
p2_t = p3_t = ram.in_ts[-1]
N_PORTS = len(ram.ports)
goal = float(os.environ.get("AUTO_PIPELINE_RAM_MHZ", "80"))


@MAIN(goal)
def auto_pipeline_ram_design(p0: p0_t, p1: p1_t, p2: p2_t, p3: p3_t) -> out_t:
    if N_PORTS == 4:
        return ram(p0, p1, p2, p3)
    else:
        return ram(p0, p1)
