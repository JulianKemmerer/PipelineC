from pypeline import *

# A single wide subtract - exercises RAW_VHDL.GET_BITS_PER_STAGE_DICT's
# equal-width split (see docs/SYN_DESIGN.md) against a real multi-cut sky130
# build. Clock target is set to converge in very few sweep iterations (comb
# delay is ~3.76ns; 700 MHz asks for real registers without being so
# aggressive the sweep needs many synthesis rounds to converge) -
# split_model_build_report_test.py needs a real (non --no_sweep) sweep to
# check the pre-synthesis reporting line, and this keeps that fast.
CLK_RATE_MHZ = 700.0
PART("sky130_fd_sc_hvl")
clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)
a: Input[uint34_t]
b: Input[uint34_t]
c: Output[uint34_t]


@MAIN(CLK_RATE_MHZ)
def split_model_design():
    c = a - b
