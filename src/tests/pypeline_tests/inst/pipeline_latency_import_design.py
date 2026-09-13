# pyright: reportInvalidTypeForm=none
"""Imported fixed pipeline fixture; deliberately has no MAIN registration."""
from pypeline import Reg, pipeline_latency, uint16_t


@pipeline_latency(1)
def imported_delay(x: uint16_t) -> uint16_t:
    saved: Reg[uint16_t]
    result: uint16_t = saved
    saved = x
    return result
