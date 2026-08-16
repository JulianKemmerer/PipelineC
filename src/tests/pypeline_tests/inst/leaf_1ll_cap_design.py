from pypeline import *

# Synthetic stand-in for the real ~24k-gate gate-level radix-2 divider
# (outside this repo): a short serial chain of nothing but SPLIT_KIND_1LL
# leaves (AND/OR/XOR/MUX), no SPLIT_KIND_BITS leaf anywhere - the shape
# where the old false-interior split model was most misleading. The planner
# must use real operation boundaries instead of collapsing the chain into one
# atomic span. The production early-flatten recipe shortened the measured
# root enough that 2000 MHz requested only one boundary; 4000 MHz remains
# below this fixture's reported 1LL floor while forcing several boundaries.
CLK_RATE_MHZ = 4000.0
PART("sky130_fd_sc_hvl")
clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)
a: Input[uint32_t]
b: Input[uint32_t]
sel: Input[uint1_t]
c: Output[uint32_t]


@MAIN(CLK_RATE_MHZ)
def leaf_1ll_cap_design():
    x0: uint32_t = a & b
    x1: uint32_t = x0 | a
    x2: uint32_t = x1 ^ b
    x3: uint32_t = x2 & a
    x4: uint32_t = x3 | b
    x5: uint32_t = x4 ^ a
    x6: uint32_t = x5 if sel else x4
    x7: uint32_t = x6 & b
    x8: uint32_t = x7 | a
    x9: uint32_t = x8 ^ b
    c = x9
