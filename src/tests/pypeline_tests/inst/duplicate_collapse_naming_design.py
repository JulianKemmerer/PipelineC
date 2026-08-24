from pypeline import *

# ONE bit-select (d[33]) read twice at two DIFFERENT source lines with the
# SAME driver wire (d). C_TO_LOGIC.TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE's
# duplicate-submodule-collapsing pass merges the two "uint34_33_33"
# bit-select instances (same func, same input driver) into one, and since
# they come from two distinct ASTMeta (different source lines), the merge
# falls into the multi-coordinate naming branch that used to leak
# PYTHONHASHSEED-salted set iteration order into the generated entity name.
# See duplicate_collapse_naming_test.py.
CLK_RATE_MHZ = 100.0
PART("sky130_fd_sc_hvl")
clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)
a: Input[uint34_t]
b: Input[uint34_t]
q: Output[uint1_t]
r: Output[uint1_t]


@MAIN(CLK_RATE_MHZ)
def duplicate_collapse_naming_design():
    d: uint34_t = a - b
    q = ~d[33]
    r = d[33]
