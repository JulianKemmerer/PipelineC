from pypeline import *

# TWO sequential runtime (non-unrolled) variable-index writes to the SAME
# array, where the second write's covering wire is the first write's own
# alias -- an alias whose ref_toks contains a Python AST node (the variable
# index expression). Regression design for the entity-name-instability bug
# in PY_TO_LOGIC._var_ref_assign_func_name/_var_ref_rd_func_name/
# _const_ref_rd_func_name: str(ast_node) on a covering_ref_toks_list entry
# embeds a per-process repr memory address, so this exact shape got a
# different VAR_REF_ASSIGN_* entity name -- and therefore a different
# synthesis log file path -- every process, defeating --continue's log
# reuse (found via wireguard-fpga's chacha20 byte-sink writers, which have
# this exact two-sequential-variable-index-write shape).
CLK_RATE_MHZ = 300.0
PART("sky130_fd_sc_hvl")
clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)
arr_in: Input[uint8_t[4]]
i: Input[uint2_t]
a: Input[uint8_t]
j: Input[uint2_t]
b: Input[uint8_t]
arr_out: Output[uint8_t[4]]


@MAIN(CLK_RATE_MHZ)
def var_ref_naming_design():
    arr: uint8_t[4] = arr_in
    arr[i] = a
    arr[j] = b
    arr_out = arr
