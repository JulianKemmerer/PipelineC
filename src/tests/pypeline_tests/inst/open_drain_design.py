# pyright: reportInvalidTypeForm=none
from pypeline import *

clk: Input[uint1_t] = make_clock(100.0)
PS2Clk: OpenDrain[uint1_t]
sampled: Output[uint1_t]

@MAIN(100.0)
def open_drain_main():
    sampled = PS2Clk
    PS2Clk = 1
