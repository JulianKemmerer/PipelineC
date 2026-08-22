#!/usr/bin/env python
import copy
import math
import sys

import C_TO_LOGIC
import SW_LIB
import VHDL
from pycparser import c_ast, c_parser  # bleh for now


# ═══════════════════════════════════════════════════════════════════════════
# Leaf split-kind classification: how a raw HDL leaf's own combinational
# delay may legally be divided by added pipeline register slices.
#
#  - SPLIT_KIND_BITS: the operator's own bit width can be partitioned across
#    stages (PLUS/MINUS/EQ/NEQ/GT/GTE/LT/LTE/accum) - see
#    GET_BITS_PER_STAGE_DICT, which does the actual split.
#  - SPLIT_KIND_MUX_BITS: MUXes retain an atomic planner landscape, but typed
#    same-depth refinement may split the packed output bits of any supported
#    scalar or aggregate data type across stages to reduce select fanout.
#  - SPLIT_KIND_1LL ("one logic level"): AND/OR/XOR/NOT/NEGATE/MULT.
#    Their generators (the repeated `stage_for_1ll`/`stage_for_op` pattern,
#    e.g. GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT)
#    always places the WHOLE operation in exactly one stage no matter the
#    latency - only the register BOUNDARY moves (latency 1: the op sits in
#    stage 0 xor stage 1 depending on which side of 0.5 the slice fraction
#    falls on - i.e. one boundary register; latency 2: registers on both
#    sides, logic in the untouched middle stage). A 3rd slice is provably
#    wasted - the remaining stage is a bare register around logic that never
#    shrinks - see LEAF_MAX_SPLIT_SLICES.
#  - SPLIT_KIND_NONE: leaves with no stage-dependent behavior at all
#    (bit-manip/cast/const-shift/const-ref raw HDL - anything not matched
#    below). A slice here would be a bug; in practice unreachable since
#    LOGIC_IS_ZERO_DELAY already excludes these from ever getting cuts.
#
# Single source of truth for both SWEEP.py's landscape/PLAN_CUTS legality
# and SYN.py's slice-descend guard, so the two can't independently drift on
# what a leaf may legally accept (they are already documented at their call
# sites as manually mirrored descend rules).
SPLIT_KIND_BITS = "bits"
SPLIT_KIND_MUX_BITS = "mux_bits"
SPLIT_KIND_1LL = "1ll"
SPLIT_KIND_NONE = "none"

def GET_LEAF_SPLIT_KIND(logic):
    """Raw HDL leaf only (len(logic.submodule_instances)==0). Dispatch
    mirrors GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT's func_name prefix
    matching (below) - kept as simple prefix checks, not a shared helper,
    since that function's own dispatch is what it must stay in sync with.
    The op-name tuples are built locally, not at module scope: RAW_VHDL is
    imported partway through C_TO_LOGIC's own top-level execution (via
    SW_LIB -> SYN -> CC_TOOLS -> VHDL -> RAW_VHDL), so C_TO_LOGIC.BIN_OP_*_
    NAME constants don't exist yet at RAW_VHDL's own module-load time -
    only safe to read once some function here actually runs."""
    bits_bin_ops = (
        C_TO_LOGIC.BIN_OP_EQ_NAME,
        C_TO_LOGIC.BIN_OP_NEQ_NAME,
        C_TO_LOGIC.BIN_OP_PLUS_NAME,
        C_TO_LOGIC.BIN_OP_MINUS_NAME,
        C_TO_LOGIC.BIN_OP_GT_NAME,
        C_TO_LOGIC.BIN_OP_GTE_NAME,
        C_TO_LOGIC.BIN_OP_LT_NAME,
        C_TO_LOGIC.BIN_OP_LTE_NAME,
    )
    ll_bin_ops = (
        C_TO_LOGIC.BIN_OP_AND_NAME,
        C_TO_LOGIC.BIN_OP_OR_NAME,
        C_TO_LOGIC.BIN_OP_XOR_NAME,
        C_TO_LOGIC.BIN_OP_MULT_NAME,
        C_TO_LOGIC.BIN_OP_INFERRED_MULT_NAME,
    )
    fn = logic.func_name
    if fn.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_"):
        for bits_op in bits_bin_ops:
            if fn.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + bits_op + "_"):
                return SPLIT_KIND_BITS
        for ll_op in ll_bin_ops:
            if fn.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + ll_op + "_"):
                return SPLIT_KIND_1LL
        return SPLIT_KIND_NONE  # SL/SR/MOD/DIV/... not raw-HDL split here
    if fn.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_"):
        if fn.startswith(
            C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX
            + "_"
            + C_TO_LOGIC.UNARY_OP_NOT_NAME
            + "_"
        ) or fn.startswith(
            C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX
            + "_"
            + C_TO_LOGIC.UNARY_OP_NEGATE_NAME
            + "_"
        ):
            return SPLIT_KIND_1LL
        return SPLIT_KIND_NONE
    if fn.startswith(C_TO_LOGIC.MUX_LOGIC_NAME):
        return SPLIT_KIND_MUX_BITS
    if fn.startswith(C_TO_LOGIC.ACCUM_FUNC_NAME + "_"):
        return SPLIT_KIND_BITS
    return SPLIT_KIND_NONE


def LEAF_MAX_SPLIT_SLICES(logic):
    """Cap on len(timing_params._slices) for this raw HDL leaf, or None for
    SPLIT_KIND_BITS/SPLIT_KIND_MUX_BITS (capped instead by width - see
    GET_BITS_PER_STAGE_DICT's own W+1 ceiling). See SPLIT_KIND_1LL above for
    why 2 is the real ceiling there: stage_for_1ll's own code already handles
    0/1/2 correctly (that IS the boundary-register mechanism, the same "0 bits
    this stage" concept a bit-splittable leaf uses at its own boundary), and
    every latency beyond that is a bare register around logic that never
    shrinks."""
    kind = GET_LEAF_SPLIT_KIND(logic)
    if kind == SPLIT_KIND_NONE:
        return 0
    if kind == SPLIT_KIND_1LL:
        return 2
    return None


def GET_MUX_DATA_WIDTH(logic, parser_state):
    """Return the canonical packed width of a raw-HDL MUX data bank.

    MUX inputs may be scalar vectors, enums, arrays, structs, or arbitrary
    nested combinations of those types.  The c_structs_pkg SLV conversion
    contract is the single source of truth for their physical bit width.
    """
    data_wires = list(logic.inputs[1:]) + list(logic.outputs)
    if len(logic.inputs[1:]) != 2 or not data_wires:
        raise ValueError(f"Malformed MUX ports for {logic.func_name}")
    widths = []
    for wire in data_wires:
        c_type = logic.wire_to_c_type.get(wire)
        if c_type is None:
            raise ValueError(f"MUX {logic.func_name} has no type for {wire}")
        widths.append(VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(c_type, parser_state))
    if len(set(widths)) != 1:
        raise ValueError(
            f"MUX {logic.func_name} data ports have different packed widths: "
            f"{widths}"
        )
    return widths[0]


def GET_LEAF_BIT_WIDTH(logic, parser_state):
    """Best-available proxy for a bit-splittable raw HDL leaf's own
    carry/comparison width - the same "widest input/output" every such
    leaf's own codegen (e.g. GET_BIN_OP_MINUS_C_BUILT_IN_UINT_N_..., which
    sets width = max(left_width, right_width)) already uses as the
    `num_bits` argument to GET_BITS_PER_STAGE_DICT. Returns None if no
    widths are found (caller must then treat this leaf as uncapped, same as
    before this existed).

    Used by SWEEP.BUILD_SLICE_LANDSCAPE to cap how many legal cut units a
    SLICEABLE segment offers: an N-bit leaf can hold at most N-1 interior
    registers (N stages) - offering more legal positions than that produces
    interior zero-bit stages once GET_BITS_PER_STAGE_DICT actually
    allocates bits (a bare register around no logic, the same failure class
    SPLIT_KIND_1LL's own 2-slice cap above exists to prevent)."""
    if GET_LEAF_SPLIT_KIND(logic) == SPLIT_KIND_MUX_BITS:
        return GET_MUX_DATA_WIDTH(logic, parser_state)

    widths = []
    for wire in list(logic.inputs) + list(logic.outputs):
        c_type = logic.wire_to_c_type.get(wire)
        if c_type is None:
            continue
        try:
            widths.append(VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type))
        except Exception:
            continue
    return max(widths) if widths else None


# Declare variables used internally to c built in C logic
def GET_RAW_HDL_WIRES_DECL_TEXT(inst_name, logic, parser_state, timing_params):
    LogicInstLookupTable = parser_state.LogicInstLookupTable

    if logic.func_name.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_UNARY_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
        return wires_decl_text
    elif logic.func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
        return wires_decl_text
    elif logic.func_name.startswith(C_TO_LOGIC.ACCUM_FUNC_NAME + "_"):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_ACCUM_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
        return wires_decl_text
    elif logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
        return wires_decl_text
    # Is this bit manip raw HDL?
    elif SW_LIB.IS_BIT_MANIP(logic):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params
        )
        return wires_decl_text
    # Mem uses no internal signals right now
    elif SW_LIB.IS_MEM(logic):
        return ""
    elif logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_CONST_REF_RD_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            inst_name, logic, parser_state, timing_params
        )
        return wires_decl_text
    elif logic.func_name.startswith(
        C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SL_NAME
    ) or logic.func_name.startswith(
        C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SR_NAME
    ):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_CONST_SHIFT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
        return wires_decl_text
    elif logic.func_name.startswith(C_TO_LOGIC.CAST_FUNC_NAME_PREFIX):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_CAST_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
        return wires_decl_text
    else:
        print("GET_RAW_HDL_WIRES_DECL_TEXT for", logic.func_name, "?")
        sys.exit(-1)


def GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT(
    inst_name, logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # Unary ops !
    if logic.func_name.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_UNARY_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
        return package_stages_text
    # Binary ops + , ==, > etc
    elif logic.func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
        return package_stages_text
    elif logic.func_name.startswith(C_TO_LOGIC.ACCUM_FUNC_NAME + "_"):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_ACCUM_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
        return package_stages_text
    # IF STATEMENTS
    elif logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
        return package_stages_text
    # Is this bit manip raw HDL?
    elif SW_LIB.IS_BIT_MANIP(logic):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params
        )
        return package_stages_text
    elif logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_CONST_REF_RD_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            inst_name, logic, parser_state, timing_params
        )
        return package_stages_text
    elif logic.func_name.startswith(
        C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SL_NAME
    ) or logic.func_name.startswith(
        C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SR_NAME
    ):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_CONST_SHIFT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
        return package_stages_text
    elif logic.func_name.startswith(C_TO_LOGIC.CAST_FUNC_NAME_PREFIX):
        (
            wires_decl_text,
            package_stages_text,
        ) = GET_CAST_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
        return package_stages_text
    else:
        print("GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT for", logic.func_name, "?")
        sys.exit(-1)


def GET_MEM_ARCH_DECL_TEXT(Logic, parser_state, TimingParamsLookupTable):
    for ram_prefix in [SW_LIB.RAM_SP_RF, SW_LIB.RAM_DP_RF]:
        for ram_latency in range(0, 3):
            ram_type = ram_prefix + "_" + str(ram_latency)
            if Logic.func_name.endswith("_" + ram_type):
                if ram_prefix == SW_LIB.RAM_SP_RF:
                    return GET_RAM_RF_ARCH_DECL_TEXT(
                        Logic, parser_state, TimingParamsLookupTable, "SP", ram_latency
                    )
                elif ram_prefix == SW_LIB.RAM_DP_RF:
                    return GET_RAM_RF_ARCH_DECL_TEXT(
                        Logic, parser_state, TimingParamsLookupTable, "DP", ram_latency
                    )

    print("GET_MEM_ARCH_DECL_TEXT for func", Logic.func_name, "?")
    sys.exit(-1)


def GET_MEM_PIPELINE_LOGIC_TEXT(Logic, parser_state, TimingParamsLookupTable):
    for ram_prefix in [SW_LIB.RAM_SP_RF, SW_LIB.RAM_DP_RF]:
        for ram_latency in range(0, 3):
            ram_type = ram_prefix + "_" + str(ram_latency)
            if Logic.func_name.endswith("_" + ram_type):
                if ram_prefix == SW_LIB.RAM_SP_RF:
                    return GET_RAM_RF_LOGIC_TEXT(
                        Logic, parser_state, TimingParamsLookupTable, "SP", ram_latency
                    )
                elif ram_prefix == SW_LIB.RAM_DP_RF:
                    return GET_RAM_RF_LOGIC_TEXT(
                        Logic, parser_state, TimingParamsLookupTable, "DP", ram_latency
                    )

    print("GET_MEM_PIPELINE_LOGIC_TEXT for func", Logic.func_name, "?")
    sys.exit(-1)


def GET_RAM_RF_ARCH_DECL_TEXT(
    Logic, parser_state, TimingParamsLookupTable, sp_dp, clocks
):
    # Func is known to have made it look like is using var?
    var_name = list(Logic.state_regs.keys())[0]
    reg_info = Logic.state_regs[var_name]
    c_type = Logic.wire_to_c_type[var_name]
    vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state)

    # Know func looks like (addr0_t addr0,...,addrN_t addrN, elem_t wd, uint1_t we)
    # Construct a single 'addr' signal to uspose when addressing ram
    # Need to overide type to 'unroll' arrays into single address BRAM
    # How many addresses
    elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
    out_t = elem_type
    elem_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(elem_type, parser_state)
    out_vhdl_type = elem_vhdl_type
    # How many address bits?
    addr_bits = 0
    for addr_i in range(0, len(dims)):
        addr_i_t = Logic.wire_to_c_type[Logic.inputs[addr_i]]
        width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(addr_i_t)
        addr_bits += width

    # Combine addr signal
    addr_t = "uint" + str(addr_bits) + "_t"
    addr_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(addr_t, parser_state)
    if sp_dp == "SP":
        rv = (
            """
  signal addr : """
            + addr_vhdl_type
            + """ := """
            + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(addr_t, parser_state)
            + """;
"""
        )
    else:  # DP
        rv = (
            """
  signal addr_w : """
            + addr_vhdl_type
            + """ := """
            + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(addr_t, parser_state)
            + """;
  signal addr_r : """
            + addr_vhdl_type
            + """ := """
            + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(addr_t, parser_state)
            + """;
"""
        )

    # Ram registers but renamed to be single dimension if needed
    if len(dims) > 1:
        num_entries = 2**addr_bits
        unrolled_c_type = elem_type + "[" + str(num_entries) + "]"
        # unrolled_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(unrolled_c_type,parser_state)
        # Determine if possible to init - unrolled is special case of STATE_REG_TO_VHDL_INIT_STR essentially
        unrolled_init_vhdl_str = None
        # If none use null
        if reg_info.init is None:
            unrolled_init_vhdl_str = VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(
                unrolled_c_type, parser_state
            )
        elif type(reg_info.init) is str:
            # Raw VHDL init string?
            init_file = reg_info.init
            # Ugh need to todo some kind of relative file path support
            f = open(init_file)
            text = f.read()
            f.close()
            unrolled_init_vhdl_str = text
        else:
            raise Exception("Unsupport init for multi dim arrays!")

        rv += (
            """
  type """
            + vhdl_type
            + """_unrolled is array(0 to """
            + str(num_entries - 1)
            + """) of """
            + elem_vhdl_type
            + """;
  signal """
            + var_name
            + """ : """
            + vhdl_type
            + """_unrolled := """
            + unrolled_init_vhdl_str
            + """;
"""
        )
    else:
        rv += (
            """
  signal """
            + var_name
            + """ : """
            + vhdl_type
            + """ := """
            + VHDL.STATE_REG_TO_VHDL_INIT_STR(var_name, Logic, parser_state)
            + """;
"""
        )

    # Include IO regs if needed
    if clocks == 0:
        pass
    elif clocks == 1:
        rv += (
            """
    signal return_output_r : """
            + out_vhdl_type
            + """ := """
            + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(out_t, parser_state)
            + """;
"""
        )
    elif clocks == 2:
        if sp_dp == "SP":
            rv += (
                """
    signal addr_r : """
                + addr_vhdl_type
                + """ := """
                + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(addr_t, parser_state)
                + """;
    """
            )
        else:  # DP
            rv += (
                """
    signal addr_w_r : """
                + addr_vhdl_type
                + """ := """
                + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(addr_t, parser_state)
                + """;
    signal addr_r_r : """
                + addr_vhdl_type
                + """ := """
                + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(addr_t, parser_state)
                + """;
    """
            )
        rv += (
            """
    signal wd_r : """
            + elem_vhdl_type
            + """ := """
            + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(elem_type, parser_state)
            + """;
    signal we_r : std_logic;
    signal return_output_r : """
            + out_vhdl_type
            + """ := """
            + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(out_t, parser_state)
            + """;
"""
        )
    else:
        print("Do other clocks for RAMRF")
        sys.exit(-1)

    return rv


def GET_RAM_RF_LOGIC_TEXT(Logic, parser_state, TimingParamsLookupTable, sp_dp, clocks):
    # Func is known to have made it look like is using var?
    var_name = list(Logic.state_regs.keys())[0]
    c_type = Logic.wire_to_c_type[var_name]
    # Is a clocked process assigning to global reg
    # global_name = Logic.func_name.split("_"+SW_LIB.RAM_SP_RF)[0]
    # global_c_type = Logic.wire_to_c_type[list(Logic.state_regs.keys())[0]]
    # global_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(global_c_type,parser_state)

    # Know func looks like (addr0_t addr0,...,addrN_t addrN, elem_t wd, uint1_t we)
    # Construct a single 'addr' signal to use when addressing ram
    # Need to overide type to 'unroll' arrays into single address BRAM
    # How many addresses
    elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)

    # Know func looks like (addr0_t addr0,...,addrN_t addrN, elem_t wd, uint1_t we)
    # Combine addr signals
    rv = ""
    if sp_dp == "SP":
        rv += "    addr <= "
        for dim_i in range(0, len(dims)):
            rv += "addr" + str(dim_i) + " & "
        rv = rv.strip(" ").strip("&")
        rv += ";\n"
    else:  # DP
        for port_postfix in ["r", "w"]:
            rv += "    addr_" + port_postfix + " <= "
            for dim_i in range(0, len(dims)):
                rv += "addr_" + port_postfix + str(dim_i) + " & "
            rv = rv.strip(" ").strip("&")
            rv += ";\n"

    if clocks == 0:
        if sp_dp == "SP":  # 0 clock
            rv += (
                """
    process(clk) is
    begin
      if rising_edge(clk) then
        if """
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + """(0)='1' then
          if we(0) = '1' then
            """
                + var_name
                + """(to_integer(addr)) <= wd; 
          end if;
        end if;
      end if;
    end process;
    -- Read first
    return_output <= """
                + var_name
                + """(to_integer(addr));
"""
            )
        else:  # DP 0 clock
            rv += (
                """
    process(clk) is
    begin
      if rising_edge(clk) then
        if """
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + """(0)='1' then
          if we(0) = '1' then
            """
                + var_name
                + """(to_integer(addr_w)) <= wd; 
          end if;
        end if;
      end if;
    end process;
    -- Read first
    return_output <= """
                + var_name
                + """(to_integer(addr_r));
"""
            )

    elif clocks == 1:
        # Just out regs
        if sp_dp == "SP":  # 1 clock
            rv += (
                """
      process(clk) is
      begin
        if rising_edge(clk) then
          if """
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + """(0)='1' then            
            -- Read first
            return_output_r <= """
                + var_name
                + """(to_integer(addr));
            -- RAM logic    
            if we(0) = '1' then
              """
                + var_name
                + """(to_integer(addr)) <= wd; 
            end if;
          end if;
        end if;
      end process;
      -- Tie output reg to output
      return_output <= return_output_r;
      """
            )
        else:  # DP 1 clock
            rv += (
                """
        process(clk)
        begin
          if rising_edge(clk) then
            if """
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + """(0)='1' then
              -- Write port
              if we(0) = '1' then
                """
                + var_name
                + """(to_integer(addr_w)) <= wd;
              end if;

              -- Read port
              return_output_r <= """
                + var_name
                + """(to_integer(addr_r));
            end if;
          end if;
        end process;
        -- Tie output reg to output
        return_output <= return_output_r;
      """
            )

    elif clocks == 2:
        # In and out regs
        if sp_dp == "SP":  # 2 clock
            rv += (
                """
      process(clk) is
      begin
        if rising_edge(clk) then
          if """
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + """(0)='1' then
            -- Register inputs
            addr_r <= addr;
            wd_r <= wd;
            we_r <= we(0);
            
            -- Read first
            return_output_r <= """
                + var_name
                + """(to_integer(addr_r));
            -- RAM logic    
            if we_r = '1' then
              """
                + var_name
                + """(to_integer(addr_r)) <= wd_r; 
            end if;
          end if;
        end if;
      end process;
      -- Tie output reg to output
      return_output <= return_output_r;
      """
            )
        else:  # DP 2 clock
            rv += (
                """
        process(clk)
        begin
          if rising_edge(clk) then
            if """
                + C_TO_LOGIC.CLOCK_ENABLE_NAME
                + """(0)='1' then
              -- Register inputs
              addr_w_r <= addr_w;
              addr_r_r <= addr_r;
              wd_r <= wd;
              we_r <= we(0);

              -- Write port
              if we_r = '1' then
                """
                + var_name
                + """(to_integer(addr_w_r)) <= wd_r;
              end if;

              -- Read port
              return_output_r <= """
                + var_name
                + """(to_integer(addr_r_r));
            end if;
          end if;
        end process;
        -- Tie output reg to output
        return_output <= return_output_r;
      """
            )

    else:
        # Built to Spill - When Not Being Stupid Is Not Enough
        print("Do other clocks for RAMRF fool")  # still a fool, fools knows a fool
        sys.exit(-1)

    return rv


def GET_UNARY_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, LogicInstLookupTable, timing_params, parser_state
):
    if logic.func_name.startswith(
        C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.UNARY_OP_NOT_NAME + "_"
    ):
        return GET_UNARY_OP_NOT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
    elif logic.func_name.startswith(
        C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX
        + "_"
        + C_TO_LOGIC.UNARY_OP_NEGATE_NAME
        + "_"
    ):
        return (
            GET_UNARY_OP_NEGATE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
                logic, LogicInstLookupTable, timing_params, parser_state
            )
        )
    else:
        print(
            "GET_UNARY_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT for",
            str(logic.c_ast_node.op),
        )
        sys.exit(-1)


def GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    bin_op_eq = logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_EQ_NAME + "_"
    )
    bin_op_neq = logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_NEQ_NAME + "_"
    )
    bin_op_gt = logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GT_NAME + "_"
    )
    bin_op_gte = logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GTE_NAME + "_"
    )
    bin_op_lt = logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LT_NAME + "_"
    )
    bin_op_lte = logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LTE_NAME + "_"
    )
    if bin_op_eq or bin_op_neq:
        return GET_BIN_OP_EQ_NEQ_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic,
            LogicInstLookupTable,
            timing_params,
            parser_state,
            "==" if bin_op_eq else "!=",
        )
    elif logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_AND_NAME + "_"
    ):
        return GET_BIN_OP_AND_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
    elif logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_PLUS_NAME + "_"
    ):
        return GET_BIN_OP_PLUS_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    elif logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MINUS_NAME + "_"
    ):
        return GET_BIN_OP_MINUS_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    elif bin_op_gt or bin_op_gte:
        return GET_BIN_OP_GT_GTE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params, ">" if bin_op_gt else ">="
        )
    elif bin_op_lt or bin_op_lte:
        return GET_BIN_OP_LT_LTE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params, "<" if bin_op_lt else "<="
        )
    elif logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_OR_NAME + "_"
    ):
        return GET_BIN_OP_OR_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, LogicInstLookupTable, timing_params, parser_state
        )
    elif logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_XOR_NAME + "_"
    ):
        return GET_BIN_OP_XOR_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    elif logic.func_name.startswith(
        C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX
        + "_"
        + C_TO_LOGIC.BIN_OP_INFERRED_MULT_NAME
        + "_"
    ):
        return GET_BIN_OP_MULT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    else:
        print(
            "GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT for",
            logic.func_name,
        )
        sys.exit(-1)


def GET_BIN_OP_XOR_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # ONLY INTS FOR NOW
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
    max_input_width = max(left_width, right_width)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)

    wires_decl_text = (
        """
  left_resized : """
        + output_vhdl_type
        + """;
  right_resized : """
        + output_vhdl_type
        + """;
  return_output : """
        + output_vhdl_type
        + """;
  right : """
        + right_vhdl_type
        + """;
  left : """
        + left_vhdl_type
        + """;
"""
    )

    # MAx clocks is input reg and output reg
    # max_clocks = 2
    latency = len(timing_params._slices)
    # Which stage gets the 1 LL ?
    stage_for_1ll = None
    if latency == 0:
        stage_for_1ll = 0
    elif latency == 1:
        # Rely on percent
        stage_for_1ll = 0
        # If slice is to left logic is on right
        if timing_params._slices[0] < 0.5:
            stage_for_1ll = 1
    elif latency == 2:
        # INput reg and output reg logic in middle
        # IN stage 1 :  0 | 1 | 2
        stage_for_1ll = 1
    # Shouldnt need this but can do it
    elif latency % 2 == 0:
        # Even
        # Ex. 4 | | | |
        #      0 1 2 3 4
        # Jsut put in middle stage
        stage_for_1ll = int(latency / 2)
    else:
        # Odd, ex 5:  | | | | |
        #                 ^
        # Depends on position of middle slice
        middle_index = int(latency / 2)
        middle_slice = timing_params._slices[middle_index]
        # If slice is to left, logic is on right
        stage_for_1ll = middle_index
        if middle_slice < 0.5:
            stage_for_1ll = middle_index + 1

    # 1 LL VHDL
    # VHDL text is just the IF for the stage in question
    text = ""
    text += (
        """
    if STAGE = """
        + str(stage_for_1ll)
        + """ then
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(output_width)
        + """);
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(output_width)
        + """);
      write_pipe.return_output := write_pipe.left_resized xor write_pipe.right_resized; 
    end if;     
  """
    )

    return wires_decl_text, text


def GET_CONST_REF_RD_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    inst_name, logic, parser_state, timing_params
):
    # print "======="
    # print "logic.func_name",logic.func_name

    containing_inst = C_TO_LOGIC.GET_CONTAINER_INST(inst_name)
    local_inst_name = C_TO_LOGIC.LEAF_NAME(inst_name, True)
    container_logic = parser_state.LogicInstLookupTable[containing_inst]

    # Copy parser state since not intending to change existing logic in this func
    parser_state_copy = copy.copy(parser_state)
    parser_state_copy.existing_logic = container_logic
    ref_toks = container_logic.ref_submodule_instance_to_ref_toks[local_inst_name]
    orig_var_name = ref_toks[0]
    # print orig_var_name
    # sys.exit(-1)

    # print("local_inst_name",local_inst_name)
    # print("container_logic.func_name", container_logic.func_name)
    # print("container_logic.wire_to_c_type",container_logic.wire_to_c_type)
    # BAH fuck is this normal? ha yes, doing for var ref rd too
    base_c_type = container_logic.wire_to_c_type[orig_var_name]
    base_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(
        base_c_type, parser_state_copy
    )  # Structs handled and have same name as C types

    wires_decl_text = ""
    wires_decl_text += (
        """ 
  variable base : """
        + base_vhdl_type
        + """;"""
    )

    # print "logic.func_name",logic.func_name

    # Then output
    output_c_type = logic.wire_to_c_type[logic.outputs[0]]
    output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(
        output_c_type, parser_state_copy
    )
    wires_decl_text += (
        """ 
  variable return_output : """
        + output_vhdl_type
        + """;"""
    )

    # The text is the writes in correct order
    text = ""
    # Inputs drive base, any undriven wires here should have syn error right?

    driven_ref_toks_list = (
        container_logic.ref_submodule_instance_to_input_port_driven_ref_toks[
            local_inst_name
        ]
    )
    driven_ref_toks_i = 0
    for input_port in logic.inputs:
        # input_port = input_port_inst_name.replace(local_inst_name+C_TO_LOGIC.SUBMODULE_MARKER,"")
        vhdl_input_port = VHDL.WIRE_TO_VHDL_NAME(input_port, logic)
        # print "input_port",input_port

        # ref toks not from port name
        driven_ref_toks = driven_ref_toks_list[driven_ref_toks_i]
        driven_ref_toks_i += 1
        var_ref_toks = not C_TO_LOGIC.C_AST_REF_TOKS_ARE_CONST(driven_ref_toks)
        driven_ref_toks_c_type = logic.wire_to_c_type[input_port]

        # Read just the variable indicies from the right side
        # Get ref tok index of variable indicies
        var_ref_tok_indicies = []
        for ref_tok_i in range(0, len(driven_ref_toks)):
            driven_ref_tok = driven_ref_toks[ref_tok_i]
            if not C_TO_LOGIC.C_AST_REF_TOK_IS_CONST(driven_ref_tok):
                var_ref_tok_indicies.append(ref_tok_i)

        expanded_ref_tok_list = C_TO_LOGIC.EXPAND_REF_TOKS_OR_STRS(
            driven_ref_toks, logic.c_ast_node, parser_state_copy
        )
        # EXPAND_REF_TOKS_OR_STRS returns a set, whose iteration order for
        # str-containing tuples is randomized per-process (PYTHONHASHSEED) --
        # each iteration below emits one VHDL assignment line, so that order
        # otherwise leaks into the generated text and defeats byte-identical
        # output across processes (confirmed: identical design, two fresh
        # builds, only line order differed). Sort by str(tok) rather than the
        # raw tuples -- ref toks mix int and str, which isn't orderable.
        for expanded_ref_toks in sorted(
            expanded_ref_tok_list, key=lambda t: tuple(str(x) for x in t)
        ):
            # Build vhdl str doing the reference assignment to base
            vhdl_ref_str = ""
            for ref_tok in expanded_ref_toks[1:]:  # Dont need base var name
                if type(ref_tok) is int:
                    vhdl_ref_str += "(" + str(ref_tok) + ")"
                elif type(ref_tok) is str:
                    vhdl_ref_str += "." + ref_tok
                else:
                    print(
                        "Only constant references here!",
                        ref_tok,
                        "from",
                        driven_ref_toks,
                    )
                    sys.exit(-1)

            # Var ref needs to read input port differently than const
            expr = """      base""" + vhdl_ref_str + """ := """ + vhdl_input_port
            if var_ref_toks:
                # Index into RHS
                # Uses that array struct thing?
                # Hacky struct type needs .data
                if SW_LIB.C_TYPE_IS_ARRAY_STRUCT(driven_ref_toks_c_type, parser_state):
                    # Need to have ".data"?
                    expr += ".data"
                for var_ref_tok_index in var_ref_tok_indicies:
                    val = expanded_ref_toks[var_ref_tok_index]
                    expr += "(" + str(val) + ")"

            # Append to text
            text += expr + ";\n"

    # Then base drives return_output
    # Need to parse func name
    # Build vhdl str doing the output reference
    vhdl_ref_str = ""
    # THIS IS A CONSTANT REF READ SO NO VAR TOKS

    for ref_tok in ref_toks[1:]:  # Skip base var name
        if type(ref_tok) is int:
            vhdl_ref_str += "(" + str(ref_tok) + ")"
        elif type(ref_tok) is str:
            vhdl_ref_str += "." + ref_tok
        else:
            print(
                "Only constant references right now blbblbaaaghghhh!", c_ast_ref.coord
            )
            sys.exit(-1)

    text += (
        """
      return_output := base"""
        + vhdl_ref_str
        + """;
      return return_output; """
    )

    # print "=="
    # print "logic.func_name",logic.func_name
    # print wires_decl_text
    # print  text
    # sys.exit(-1)

    return wires_decl_text, text


def GET_UNARY_OP_NEGATE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, LogicInstLookupTable, timing_params, parser_state
):
    # ONLY FLOATS FOR NOW FOR NOW
    input_type = logic.wire_to_c_type[logic.inputs[0]]
    assert "float" in input_type
    input_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(input_type, parser_state)
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)

    wires_decl_text = (
        """
  return_output : """
        + output_vhdl_type
        + """;
  expr : """
        + input_vhdl_type
        + """;
"""
    )

    # MAx clocks is input reg and output reg
    # max_clocks = 2
    latency = len(timing_params._slices)
    num_stages = latency + 1
    # Which stage gets the 1 LL ?
    stage_for_1ll = None
    if latency == 0:
        stage_for_1ll = 0
    elif latency == 1:
        # Rely on percent
        stage_for_1ll = 0
        # If slice is to left logic is on right
        if timing_params._slices[0] < 0.5:
            stage_for_1ll = 1
    elif latency == 2:
        # INput reg and output reg logic in middle
        # IN stage 1 :  0 | 1 | 2
        stage_for_1ll = 1
    # Shouldnt need this but can do it
    elif latency % 2 == 0:
        # Even
        # Ex. 4 | | | |
        #      0 1 2 3 4
        # Jsut put in middle stage
        stage_for_1ll = int(latency / 2)
    else:
        # Odd, ex 5:  | | | | |
        #                 ^
        # Depends on position of middle slice
        middle_index = int(latency / 2)
        middle_slice = timing_params._slices[middle_index]
        # If slice is to left, logic is on right
        stage_for_1ll = middle_index
        if middle_slice < 0.5:
            stage_for_1ll = middle_index + 1

    # 1 LL VHDL
    # VHDL text is just the IF for the stage in question
    text = ""
    text += (
        """
    if STAGE = """
        + str(stage_for_1ll)
        + """ then
      -- Same value
      write_pipe.return_output := write_pipe.expr; 
      -- With left most sign bit inverted
      write_pipe.return_output(write_pipe.return_output'left) := not write_pipe.expr(write_pipe.expr'left);
    end if;     
  """
    )

    return wires_decl_text, text


def GET_UNARY_OP_NOT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, LogicInstLookupTable, timing_params, parser_state
):
    # ONLY INTS FOR NOW
    input_type = logic.wire_to_c_type[logic.inputs[0]]
    input_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(input_type, parser_state)
    input_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, input_type)
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)

    wires_decl_text = (
        """
  expr_resized : """
        + output_vhdl_type
        + """;
  return_output : """
        + output_vhdl_type
        + """;
  expr : """
        + input_vhdl_type
        + """;
"""
    )

    # MAx clocks is input reg and output reg
    # max_clocks = 2
    latency = len(timing_params._slices)
    num_stages = latency + 1
    # Which stage gets the 1 LL ?
    stage_for_1ll = None
    if latency == 0:
        stage_for_1ll = 0
    elif latency == 1:
        # Rely on percent
        stage_for_1ll = 0
        # If slice is to left logic is on right
        if timing_params._slices[0] < 0.5:
            stage_for_1ll = 1
    elif latency == 2:
        # INput reg and output reg logic in middle
        # IN stage 1 :  0 | 1 | 2
        stage_for_1ll = 1
    # Shouldnt need this but can do it
    elif latency % 2 == 0:
        # Even
        # Ex. 4 | | | |
        #      0 1 2 3 4
        # Jsut put in middle stage
        stage_for_1ll = int(latency / 2)
    else:
        # Odd, ex 5:  | | | | |
        #                 ^
        # Depends on position of middle slice
        middle_index = int(latency / 2)
        middle_slice = timing_params._slices[middle_index]
        # If slice is to left, logic is on right
        stage_for_1ll = middle_index
        if middle_slice < 0.5:
            stage_for_1ll = middle_index + 1

    # 1 LL VHDL
    # VHDL text is just the IF for the stage in question
    text = ""
    text += (
        """
    if STAGE = """
        + str(stage_for_1ll)
        + """ then
      write_pipe.expr_resized := resize(write_pipe.expr, """
        + str(output_width)
        + """);
      write_pipe.return_output := not write_pipe.expr_resized;
    end if;     
  """
    )

    return wires_decl_text, text


def GET_BIN_OP_AND_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, LogicInstLookupTable, timing_params, parser_state
):
    # ONLY INTS FOR NOW
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
    max_input_width = max(left_width, right_width)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)

    wires_decl_text = (
        """
  left_resized : """
        + output_vhdl_type
        + """;
  right_resized : """
        + output_vhdl_type
        + """;
  return_output : """
        + output_vhdl_type
        + """;
  right : """
        + right_vhdl_type
        + """;
  left : """
        + left_vhdl_type
        + """;
"""
    )

    # MAx clocks is input reg and output reg
    # max_clocks = 2
    latency = len(timing_params._slices)
    num_stages = latency + 1
    # Which stage gets the 1 LL ?
    stage_for_1ll = None
    if latency == 0:
        stage_for_1ll = 0
    elif latency == 1:
        # Rely on percent
        stage_for_1ll = 0
        # If slice is to left logic is on right
        if timing_params._slices[0] < 0.5:
            stage_for_1ll = 1
    elif latency == 2:
        # INput reg and output reg logic in middle
        # IN stage 1 :  0 | 1 | 2
        stage_for_1ll = 1
    # Shouldnt need this but can do it
    elif latency % 2 == 0:
        # Even
        # Ex. 4 | | | |
        #      0 1 2 3 4
        # Jsut put in middle stage
        stage_for_1ll = int(latency / 2)
    else:
        # Odd, ex 5:  | | | | |
        #                 ^
        # Depends on position of middle slice
        middle_index = int(latency / 2)
        middle_slice = timing_params._slices[middle_index]
        # If slice is to left, logic is on right
        stage_for_1ll = middle_index
        if middle_slice < 0.5:
            stage_for_1ll = middle_index + 1

    # 1 LL VHDL
    # VHDL text is just the IF for the stage in question
    text = ""
    text += (
        """
    if STAGE = """
        + str(stage_for_1ll)
        + """ then
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(output_width)
        + """);
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(output_width)
        + """);
      write_pipe.return_output := write_pipe.left_resized and write_pipe.right_resized;   
    end if;     
  """
    )

    return wires_decl_text, text


def GET_BIN_OP_OR_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, LogicInstLookupTable, timing_params, parser_state
):
    # ONLY INTS FOR NOW
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
    max_input_width = max(left_width, right_width)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)

    wires_decl_text = (
        """
  left_resized : """
        + output_vhdl_type
        + """;
  right_resized : """
        + output_vhdl_type
        + """;
  return_output : """
        + output_vhdl_type
        + """;
  right : """
        + right_vhdl_type
        + """;
  left : """
        + left_vhdl_type
        + """;
"""
    )

    # MAx clocks is input reg and output reg
    # max_clocks = 2
    latency = len(timing_params._slices)
    num_stages = latency + 1
    # Which stage gets the 1 LL ?
    stage_for_1ll = None
    if latency == 0:
        stage_for_1ll = 0
    elif latency == 1:
        # Rely on percent
        stage_for_1ll = 0
        # If slice is to left logic is on right
        if timing_params._slices[0] < 0.5:
            stage_for_1ll = 1
    elif latency == 2:
        # INput reg and output reg logic in middle
        # IN stage 1 :  0 | 1 | 2
        stage_for_1ll = 1
    # Shouldnt need this but can do it
    elif latency % 2 == 0:
        # Even
        # Ex. 4 | | | |
        #      0 1 2 3 4
        # Jsut put in middle stage
        stage_for_1ll = int(latency / 2)
    else:
        # Odd, ex 5:  | | | | |
        #                 ^
        # Depends on position of middle slice
        middle_index = int(latency / 2)
        middle_slice = timing_params._slices[middle_index]
        # If slice is to left, logic is on right
        stage_for_1ll = middle_index
        if middle_slice < 0.5:
            stage_for_1ll = middle_index + 1

    # 1 LL VHDL
    # VHDL text is just the IF for the stage in question
    text = ""
    text += (
        """
    if STAGE = """
        + str(stage_for_1ll)
        + """ then
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(output_width)
        + """);
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(output_width)
        + """);
      write_pipe.return_output := write_pipe.left_resized or write_pipe.right_resized;    
    end if;     
  """
    )

    return wires_decl_text, text


def GET_BIN_OP_EQ_NEQ_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, LogicInstLookupTable, timing_params, parser_state, op_str
):
    # Binary operation between what two types?
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
    right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)

    # Cannot do compare operations between mixed compound types right now...
    # arrays vs non arrays, structs vs non structs
    if (
        C_TO_LOGIC.C_TYPE_IS_ARRAY(left_type) != C_TO_LOGIC.C_TYPE_IS_ARRAY(right_type)
    ) or (
        C_TO_LOGIC.C_TYPE_IS_STRUCT(left_type, parser_state)
        != C_TO_LOGIC.C_TYPE_IS_STRUCT(right_type, parser_state)
    ):
        raise Exception(
            f"Unsupported == or != compare between array/struct and non array/struct. {logic.c_ast_node.coord}"
        )

    # Only ints+floats for now, check all inputs
    if (
        VHDL.WIRES_ARE_INT_N(logic.inputs, logic)
        or VHDL.WIRES_ARE_UINT_N(logic.inputs, logic)
        or VHDL.WIRES_ARE_ENUM(logic.inputs, logic, parser_state)
    ):
        # HACK OH GOD NO dont look up enums
        left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
        right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
        max_width = max(left_width, right_width)
        left_cast_toks = ["std_logic_vector(resize(", "," + str(max_width) + "))"]
        right_cast_toks = ["std_logic_vector(resize(", "," + str(max_width) + "))"]
    elif C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_type, right_type]):
        left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
        right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
        max_width = max(left_width, right_width)
        left_cast_toks = ["", ""]
        right_cast_toks = ["", ""]
    else:
        # Some other type, rely on built in to from slv funcs
        left_width = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(left_type, parser_state)
        right_width = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(right_type, parser_state)
        max_width = max(left_width, right_width)
        left_cast_toks = [left_vhdl_type + "_to_slv(", ")"]
        right_cast_toks = [right_vhdl_type + "_to_slv(", ")"]

    wires_decl_text = (
        """
  left_resized : std_logic_vector("""
        + str(max_width - 1)
        + """ downto 0);
  right_resized : std_logic_vector("""
        + str(max_width - 1)
        + """ downto 0);
  return_output_bool : boolean;
  return_output : unsigned(0 downto 0);
  right : """
        + right_vhdl_type
        + """;
  left :  """
        + left_vhdl_type
        + """;
"""
    )

    # Set width equal to max width
    width = max_width

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1
    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)

    # Write loops to do operation
    text = ""
    text += (
        """
    -- COMPARE N bits per clock, 
    -- num_stages = """
        + str(num_stages)
        + "\n"
    )
    text += "\n"
    # This needs to be in stage 0
    text += (
        """
    if STAGE = 0 then     
      write_pipe.return_output_bool := true;
      write_pipe.left_resized := """
        + left_cast_toks[0]
        + """write_pipe.left"""
        + left_cast_toks[1]
        + """;
      write_pipe.right_resized := """
        + right_cast_toks[0]
        + """write_pipe.right"""
        + right_cast_toks[1]
        + """;
  """
    )
    # Write bound of loop per stage
    stage = 0
    # Top start, only increment up_bound, low_bound is calculated each iteration
    up_bound = width - 1
    for stage in range(0, num_stages):
        # Top start moving down
        low_bound = up_bound - bits_per_stage_dict[stage] + 1

        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """   
      -- bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """
      """
            )
            text += (
                """
        -- Assign output based on range for this stage
        write_pipe.return_output_bool := write_pipe.return_output_bool and (write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) = write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) );
        """
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage so no else if
            # optional negate
            maybe_not = ""
            if op_str == "!=":
                maybe_not = "not"

            text += (
                """
      if """
                + maybe_not
                + """ write_pipe.return_output_bool then
        write_pipe.return_output := (others => '1');
      else
        write_pipe.return_output := (others => '0');
      end if;
      
    end if;
    """
            )
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Top start, moving down decrement up_bound only
            up_bound = up_bound - bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_BIN_OP_MINUS_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    max_input_width = max(left_width, right_width)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
    wires_decl_text = (
        """
  carry : std_logic_vector(0 downto 0);
  intermediate : std_logic_vector("""
        + str(max_input_width)
        + """ downto 0);
  left_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  right_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  left_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  right_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  full_width_return_output : signed("""
        + str(max_input_width)
        + """ downto 0);
  return_output : signed("""
        + str(output_width - 1)
        + """ downto 0);
  right : signed("""
        + str(right_width - 1)
        + """ downto 0);
  left : signed("""
        + str(left_width - 1)
        + """ downto 0);
"""
    )

    # Do each bit over a clock cycle

    # TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
    width = max_input_width

    # Output width must be ???
    # Is vhdl allowing equal or larger assignments?

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1
    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)

    # Write loops to do operation
    text = ""
    text += """
  --
  -- One bit adder with carry
"""

    text += (
        """
  -- num_stages = """
        + str(num_stages)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      -- This stuff must be in stage 0
      write_pipe.carry := (others => '0'); -- One bit unsigned  
      write_pipe.intermediate := (others => '0'); -- N bit unused depending on bits per stage
      write_pipe.left_resized := unsigned(resize(write_pipe.left, """
        + str(width)
        + """));
      write_pipe.right_resized := unsigned(resize(write_pipe.right, """
        + str(width)
        + """));
      write_pipe.return_output := (others => '0');
      write_pipe.full_width_return_output := (others => '0');
      """
    )

    # Write bound of loop per stage
    stage = 0
    # Bottom start only increment low_bound, up_bound is calculated each iteration
    low_bound = 0
    for stage in range(0, num_stages):
        # Bottom start moving upward
        up_bound = low_bound + bits_per_stage_dict[stage] - 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """
        write_pipe.left_range_slv := (others => '0');
        write_pipe.right_range_slv := (others => '0');
        write_pipe.left_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));
        write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));  

        -- DOING SUB OP,  carry indicates -1
        -- Sub signed values
        write_pipe.intermediate := (others => '0'); -- Zero out for this stage
        """
            )
            if stage == (num_stages - 1):
                text += (
                    """
        -- Last stage uses actual sign bit, no & '0'
        write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0) := std_logic_vector( resize(signed(write_pipe.left_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)), """
                    + str(bits_per_stage_dict[stage] + 1)
                    + """) - resize(signed(write_pipe.right_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)), """
                    + str(bits_per_stage_dict[stage] + 1)
                    + """) - signed('0' & write_pipe.carry) );
        """
                )
            else:
                text += (
                    """
        write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0) := std_logic_vector( signed('0' & write_pipe.left_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) - signed('0' & write_pipe.right_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) - signed('0' & write_pipe.carry) );
        --write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0) := std_logic_vector( resize(signed(write_pipe.left_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)), """
                    + str(bits_per_stage_dict[stage] + 1)
                    + """) - resize(signed(write_pipe.right_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)),"""
                    + str(bits_per_stage_dict[stage] + 1)
                    + """) - signed('0' & write_pipe.carry) );
        """
                )
            text += (
                """
        -- New carry is sign (negative carry)
        write_pipe.carry(0) := write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """);
        -- Assign output bits into full width
        --write_pipe.full_width_return_output("""
                + str(up_bound + 1)
                + """ downto """
                + str(low_bound)
                + """) := signed(write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0));
        write_pipe.full_width_return_output("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) := signed(write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0));
        --write_pipe.return_output("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) := signed(write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0));
      """
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage
            # sign is in last stage
            # depends on carry
            text += (
                """
      -- Last stage
      --write_pipe.return_output := write_pipe.full_width_return_output; 
      write_pipe.full_width_return_output("""
                + str(max_input_width)
                + """) := write_pipe.carry(0);
      write_pipe.return_output := resize(write_pipe.full_width_return_output("""
                + str(max_input_width)
                + """ downto 0), """
                + str(output_width)
                + """);      
"""
            )
            # Last stage so no else if
            text += """
    end if;
    """
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Do stage logic / bit pos increment
            # Bottom start moving upward, increment low_bound only
            low_bound = low_bound + bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_BIN_OP_MINUS_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable

    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    max_input_width = max(left_width, right_width)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
    wires_decl_text = (
        """
  carry : std_logic_vector(0 downto 0);
  intermediate : std_logic_vector("""
        + str(max_input_width)
        + """ downto 0);
  left_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  right_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  left_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  right_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  full_width_return_output : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  return_output : unsigned("""
        + str(output_width - 1)
        + """ downto 0);
  right : unsigned("""
        + str(right_width - 1)
        + """ downto 0);
  left : unsigned("""
        + str(left_width - 1)
        + """ downto 0);
"""
    )

    # Do each bit over a clock cycle

    # TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
    width = max_input_width

    # Output width must be ???
    # Is vhdl allowing equal or larger assignments?

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1
    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)

    # Write loops to do operation
    text = ""
    text += """
  --
  -- One bit adder with carry
"""

    text += (
        """
  -- num_stages = """
        + str(num_stages)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      -- This stuff must be in stage 0
      write_pipe.carry := (others => '0'); -- One bit unsigned  
      write_pipe.intermediate := (others => '0'); -- N bit unused depending on bits per stage
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(width)
        + """);
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(width)
        + """);
      write_pipe.return_output := (others => '0');
      write_pipe.full_width_return_output := (others => '0');
      """
    )

    # Write bound of loop per stage
    stage = 0
    # Bottom start only increment low_bound, up_bound is calculated each iteration
    low_bound = 0
    for stage in range(0, num_stages):
        # Bottom start moving upward
        up_bound = low_bound + bits_per_stage_dict[stage] - 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """
        write_pipe.left_range_slv := (others => '0');
        write_pipe.right_range_slv := (others => '0');
        write_pipe.left_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));
        write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));  

        -- DOIGN SUB OP,  carry indicates -1
        -- Sub signed values
        write_pipe.intermediate := (others => '0'); -- Zero out for this stage
        write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0) := std_logic_vector( signed('0' & write_pipe.left_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0)) - signed('0' & write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0)) - signed('0' & write_pipe.carry) ); 
  """
            )

            text += (
                """
        -- New carry is sign (negative carry)
        write_pipe.carry(0) := write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """);
        -- Assign output bits
        write_pipe.full_width_return_output("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) := unsigned(write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0));
      """
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage
            # sign is in last stage
            # depends on carry
            text += (
                """
      write_pipe.return_output := resize(write_pipe.full_width_return_output("""
                + str(max_input_width - 1)
                + """ downto 0), """
                + str(output_width)
                + """);      
"""
            )
            # Last stage so no else if
            text += """
    end if;
    """
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Bottom start moving upward, increment low_bound only
            low_bound = low_bound + bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_BIN_OP_MINUS_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable

    # Binary operation between what two types?
    # Only ints for now, check all inputs
    if VHDL.WIRES_ARE_UINT_N(logic.inputs, logic):
        return GET_BIN_OP_MINUS_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    elif VHDL.WIRES_ARE_INT_N(logic.inputs, logic):
        return GET_BIN_OP_MINUS_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    else:
        print("Only u/int binary op minus raw vhdl for now!", logic.wire_to_c_type)
        sys.exit(-1)


def SLICES_TO_SIZE_LIST(slices):
    removed_percent = 0.0
    adj_percents = []
    # This does for >= 1clks
    for raw_hdl_slice in slices:
        adj_percent = raw_hdl_slice - removed_percent
        adj_percents.append(adj_percent)
        removed_percent += adj_percent
    # Do last/default stage0 only stage
    remaining_percent = 1.0 - removed_percent
    adj_percents.append(remaining_percent)
    return adj_percents


def GET_EQUAL_WIDTH_BIT_BOUNDARIES(num_bits, num_slices):
    """Return the cumulative bit boundaries physically emitted for a
    ``SPLIT_KIND_BITS`` leaf with ``num_slices`` internal registers.

    Slice *fractions* stored in ``TimingParams`` do not select these
    boundaries; the raw generators deliberately balance chunk widths from
    the final slice count.  The typed planner uses this function too, so its
    ordinal placement metadata and trace describe the same boundaries the
    VHDL generators consume below.
    """
    if num_bits <= 0:
        raise ValueError(f"num_bits must be positive, got {num_bits}")
    if num_slices < 0:
        raise ValueError(f"num_slices must be non-negative, got {num_slices}")
    chunks = num_slices + 1
    boundaries = []
    prev_boundary = 0
    for ordinal in range(1, chunks):
        boundary = int(round(ordinal * num_bits / float(chunks)))
        boundary = max(prev_boundary, min(num_bits, boundary))
        boundaries.append(boundary)
        prev_boundary = boundary
    return boundaries


def _EQUAL_WIDTH_BITS_PER_STAGE_DICT(num_bits, num_slices):
    """D2 fix, corrected: the naive read of timing_params._slices as bit
    boundaries to hit via a delay-fraction curve inversion (an earlier
    version of this function) turned out to model the WRONG quantity, found
    by testing against real sky130 synthesis (see docs/SYN_DESIGN.md) - it
    made highly-sliced leaves noticeably WORSE than the plain linear split
    it was replacing, not better.

    Why: once a stage boundary is registered, stage k's own generated VHDL
    (see e.g. GET_BIN_OP_MINUS_C_BUILT_IN_UINT_N_..._TEXT above) computes
    ONLY that stage's bits_per_stage_dict[k] bits, from a REGISTERED 1-bit
    carry-in - i.e. a FRESH bits_per_stage_dict[k]-wide computation, timing-
    wise equivalent to an isolated same-width leaf, not a marginal
    extension of a longer unregistered chain. So stage k's real delay is
    ~D(chunk_width_k), not D(cumulative_boundary_k) - D(cumulative_
    boundary_{k-1}) (what the curve-inversion version computed). Since a
    real D(w) is monotonic increasing in w, minimizing the WORST stage's
    delay for a fixed chunk COUNT means making every chunk as close to
    EQUAL WIDTH as possible - regardless of D's concave shape, and
    regardless of the specific delay fractions PLAN_CUTS happened to
    request for this leaf (those fractions reflect this leaf's POSITION in
    the domain's wider delay-budget walk, not a meaningful signal for how
    ITS OWN bits should be divided). This also directly eliminates the old
    linear model's degenerate near-boundary splits (a request near the
    leaf's own edge used to produce a lopsided {31,3}-bit split of a 34-bit
    op; a single cut now always produces a balanced {17,17}-style split,
    regardless of the requested fraction).

    OPEN QUESTION (2026-08-21) -- two halves of the above have aged
    differently, and neither is a reason to change this function today, but
    do not read it as settled:

    1. The REASONING (stage delay depends only on its own chunk width, so for
       a fixed count equal widths minimize the worst chunk) is
       model-independent and still stands.
    2. The EMPIRICAL claim (that the curve-inversion version measurably lost
       against real sky130) was measured under the previous device model and
       synthesis recipe, both since replaced -- DEVICE_MODELS.MODEL_VERSION
       is now 4 on `early_flatten_noabc`. It has not been re-run. Unverified,
       not disproven.

    The more interesting gap is that this argument is purely LOCAL: it shows
    equal widths are best for this leaf in isolation, and says nothing about
    whether that boundary is right GLOBALLY when neighbouring atomic
    operations constrain where a stage can end. SWEEP's planner requests a
    delay fraction and gets back the nearest equal-width boundary, which can
    be far away -- the radix-2 divider asked for 3.9%, 11.8% and 51.3% of its
    34-bit subtractors and got bit 17 for all three. That mismatch is
    handled upstream by SWEEP.PLAN_PIPELINE_PLACEMENTS working WITHIN this
    contract: it re-plans against the exact boundaries this function will
    emit and ranks the results, so a plan is never costed at a position that
    lowering then moves. That was enough to reach intermediate pipeline
    depths at all, with no equal-latency fmax regression. It is not proof the
    constraint is free: the intermediate depth it now reaches is itself
    suboptimal (48 slices at 164.69 MHz on the divider, below the 32-slice
    plan's 169.57 MHz), which is the shape of result a leaf-split interface
    able to honor a requested fraction might improve. Deciding that means
    measuring both under the current model. See docs/SYN_DESIGN.md section 2,
    "Open question (2026-08-21)"."""
    chunks = num_slices + 1
    boundaries = GET_EQUAL_WIDTH_BIT_BOUNDARIES(num_bits, num_slices)
    bits_per_stage_dict = {}
    prev_boundary = 0
    for stage in range(chunks):
        # Last stage's boundary is forced to num_bits exactly rather than
        # trusting round(chunks*num_bits/chunks) to land there - guarantees
        # sum(bits_per_stage_dict) == num_bits with no float-rounding edge
        # case, no separate excess/deficit fixup pass needed.
        boundary = num_bits if stage == chunks - 1 else boundaries[stage]
        bits_per_stage_dict[stage] = boundary - prev_boundary
        prev_boundary = boundary
    return bits_per_stage_dict


def GET_EQUAL_WIDTH_BITS_PER_STAGE_DICT(num_bits, num_slices):
    """Public, side-effect-free view of the bit chunks raw VHDL will emit.

    The typed placement planner uses this for validation and trace metadata;
    keeping the implementation above as the single source of truth prevents
    planner ordinals from drifting from code generation.
    """
    return _EQUAL_WIDTH_BITS_PER_STAGE_DICT(num_bits, num_slices)


# TODO min bits per stage roughly based on smallest add op in one lut/carry?
def GET_BITS_PER_STAGE_DICT(num_bits, timing_params):
    exact_boundaries = getattr(timing_params, "_exact_bit_boundaries", None)
    if exact_boundaries is None:
        bits_per_stage_dict = _EQUAL_WIDTH_BITS_PER_STAGE_DICT(
            num_bits, len(timing_params._slices)
        )
    else:
        boundaries = [int(boundary) for boundary in exact_boundaries]
        if (
            boundaries != sorted(set(boundaries))
            or any(boundary <= 0 or boundary >= num_bits for boundary in boundaries)
            or len(boundaries) != len(timing_params._slices)
        ):
            raise ValueError(
                f"Invalid exact bit boundaries {boundaries} for {num_bits}-bit "
                f"leaf with slices {timing_params._slices}"
            )
        bits_per_stage_dict = {}
        previous = 0
        for stage, boundary in enumerate(boundaries + [num_bits]):
            bits_per_stage_dict[stage] = boundary - previous
            previous = boundary

    # sanity check (the boundary construction above guarantees this by
    # telescoping sum + an exact final boundary, not a fixup loop)
    maybe_num_bits = sum(bits_per_stage_dict.values())
    if maybe_num_bits != num_bits:
        print("maybe_num_bits != num_bits")
        print("maybe_num_bits", maybe_num_bits)
        print("num_bits", num_bits)
        print(0 / 0)
        sys.exit(-1)

    # A leading or trailing zero-bit stage is fine (an IO-boundary register
    # with no logic on the outer side of it). An INTERIOR zero-bit stage is
    # not: it's a bare register wired straight through, computing no new
    # bits of the operation at all - only possible once more slices are
    # requested than this leaf's own width can usefully support (e.g. 14
    # slices on a 4-bit op: [0,1,0,0,0,1,0,0,0,1,0,0,0,1,0]). The real
    # prevention is upstream, capping legal cut units by leaf bit width in
    # SWEEP.BUILD_SLICE_LANDSCAPE (RAW_VHDL.GET_LEAF_BIT_WIDTH) - this is a
    # backstop so a landscape/planner disagreement fails loud instead of
    # silently wasting a stage.
    n_stages = len(bits_per_stage_dict)
    for stage in range(1, n_stages - 1):
        if bits_per_stage_dict[stage] == 0:
            raise Exception(
                f"GET_BITS_PER_STAGE_DICT: interior zero-bit stage {stage} of "
                f"{n_stages} for a {num_bits}-bit op ({len(timing_params._slices)} "
                f"slices requested) - bits_per_stage_dict={bits_per_stage_dict}"
            )

    return bits_per_stage_dict


def GET_BIN_OP_PLUS_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    max_input_width = max(left_width, right_width)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
    wires_decl_text = (
        """
  carry : std_logic_vector(0 downto 0);
  intermediate : std_logic_vector("""
        + str(max_input_width)
        + """ downto 0);
  left_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  right_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  left_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  right_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  full_width_return_output : unsigned("""
        + str(max_input_width)
        + """ downto 0);
  return_output : unsigned("""
        + str(output_width - 1)
        + """ downto 0);
  right : unsigned("""
        + str(right_width - 1)
        + """ downto 0);
  left : unsigned("""
        + str(left_width - 1)
        + """ downto 0);
"""
    )

    # Do each bit over a clock cycle

    # TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
    width = max_input_width

    # Output width must be ???
    # Is vhdl allowing equal or larger assignments?

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1
    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)
    # print "num_stages",num_stages
    # print "bits_per_stage_dict",bits_per_stage_dict

    # Write loops to do operation
    text = ""
    text += """
  --
  -- One bit adder with carry
"""

    text += (
        """
  -- width = """
        + str(width)
        + """
  -- num_stages = """
        + str(num_stages)
        + """
  -- bits per stage = """
        + str(bits_per_stage_dict)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      -- This stuff must be in stage 0
      write_pipe.carry := (others => '0'); -- One bit unsigned
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(width)
        + """);
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(width)
        + """);
      write_pipe.return_output := (others => '0');
      write_pipe.full_width_return_output := (others => '0');
      """
    )

    # Write bound of loop per stage
    stage = 0
    # Bottom start only increment low_bound, up_bound is calculated each iteration
    low_bound = 0
    for stage in range(0, num_stages):
        # Bottom start moving upward
        up_bound = low_bound + bits_per_stage_dict[stage] - 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """
        write_pipe.left_range_slv := (others => '0');
        write_pipe.right_range_slv := (others => '0');
        write_pipe.left_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));
        write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));  

        -- Adding unsigned values
        write_pipe.intermediate := (others => '0'); -- Zero out for this stage"""
            )

            # No carry for stage 0
            if stage == 0:
                text += (
                    """
        write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0) := std_logic_vector( unsigned('0' & write_pipe.left_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) + unsigned('0' & write_pipe.right_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) );"""
                )
            else:
                text += (
                    """
        write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0) := std_logic_vector( unsigned('0' & write_pipe.left_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) + unsigned('0' & write_pipe.right_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) + unsigned(write_pipe.carry) );"""
                )

            text += (
                """
        -- New carry is msb of intermediate
        write_pipe.carry(0) := write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """);
        -- Assign output bits
        -- Carry full_width_return_output(up_bound+1) will be overidden in next iteration and included as carry
        write_pipe.full_width_return_output("""
                + str(up_bound + 1)
                + """ downto """
                + str(low_bound)
                + """) := unsigned(write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0));
      """
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage
            # sign is in last stage
            # depends on carry
            text += (
                """
      write_pipe.return_output := resize(write_pipe.full_width_return_output("""
                + str(max_input_width)
                + """ downto 0), """
                + str(output_width)
                + """);      
"""
            )
            # Last stage so no else if
            text += """
    end if;
    """
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Bottom start moving upward, increment low_bound only
            low_bound = low_bound + bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_BIN_OP_PLUS_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # Was confused abotu twos compliment ... I think you can just add and the sign takes care of self?
    # Especially if dont care about overflow or carry?
    # Uh too many drinks
    # Fuck this

    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    max_input_width = max(left_width, right_width)

    # Do each bit over a clock cycle
    width = max_input_width + 1

    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
    wires_decl_text = (
        """
  carry : std_logic_vector(0 downto 0);
  intermediate : std_logic_vector("""
        + str(max_input_width + 1)
        + """ downto 0);
  --left_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  --right_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  left_resized : unsigned("""
        + str(max_input_width)
        + """ downto 0);
  right_resized : unsigned("""
        + str(max_input_width)
        + """ downto 0);
  --left_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  --right_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  left_range_slv : std_logic_vector("""
        + str(max_input_width)
        + """ downto 0);
  right_range_slv : std_logic_vector("""
        + str(max_input_width)
        + """ downto 0);
  full_width_return_output : unsigned("""
        + str(max_input_width + 1)
        + """ downto 0);
  return_output : signed("""
        + str(output_width - 1)
        + """ downto 0);
  right : signed("""
        + str(right_width - 1)
        + """ downto 0);
  left : signed("""
        + str(left_width - 1)
        + """ downto 0);
"""
    )

    # Output width must be 1 greater than max of input widths
    # Is vhdl allowing equal or larger assignments?

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1
    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)

    # Write loops to do operation
    text = ""
    text += """
  --
  -- One bit adder with carry
"""

    text += (
        """
  -- num_stages = """
        + str(num_stages)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      -- This stuff must be in stage 0
      write_pipe.carry := (others => '0'); -- One bit unsigned  
      write_pipe.intermediate := (others => '0'); -- N bit unused depending on bits per stage
      write_pipe.left_resized := unsigned(std_logic_vector(resize(write_pipe.left, """
        + str(width)
        + """)));
      write_pipe.right_resized := unsigned(std_logic_vector(resize(write_pipe.right, """
        + str(width)
        + """)));
      write_pipe.full_width_return_output := (others => '0');
      write_pipe.return_output := (others => '0');
      """
    )

    # 1111111111111111111111111111111110000000000000000000000000000000
    # +
    # 1111111111111111111111111111111110000000000000000000000000000000
    # ===============================================================
    # 1111111111111111111111111111111100000000000000000000000000000000

    # Write bound of loop per stage
    stage = 0
    # Bottom start only increment low_bound, up_bound is calculated each iteration
    low_bound = 0
    for stage in range(0, num_stages):
        # Bottom start moving upward
        up_bound = low_bound + bits_per_stage_dict[stage] - 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """
        write_pipe.left_range_slv := (others => '0');
        write_pipe.right_range_slv := (others => '0');
        write_pipe.left_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));
        write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));  

        -- Adding unsigned values
        write_pipe.intermediate := (others => '0'); -- Zero out for this stage
        write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0) := std_logic_vector( unsigned('0' & write_pipe.left_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0)) + unsigned('0' & write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0)) + unsigned(write_pipe.carry) ); 
        --write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0) := std_logic_vector( unsigned('0' & write_pipe.left_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0)) + unsigned('0' & write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0))  ); 
        --write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0) := std_logic_vector( unsigned(write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0)) + unsigned(write_pipe.carry) );
        
  """
            )

            text += (
                """
        -- New carry is msb of intermediate
        write_pipe.carry(0) := write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """);
        -- Assign output bits
      """
            )
            # Only last iteration writes carry into full_width_return_output?
            if stage == (num_stages - 1):
                text += (
                    """
        -- Only last iteration writes carry into full_width_return_output?
        -- Carry full_width_return_output(up_bound+1) will be overidden in next iteration and included as carry
        write_pipe.full_width_return_output("""
                    + str(up_bound + 1)
                    + """ downto """
                    + str(low_bound)
                    + """) := unsigned(write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0));
      """
                )
            else:
                text += (
                    """
        -- Dont include carry since not last stage
        write_pipe.full_width_return_output("""
                    + str(up_bound)
                    + """ downto """
                    + str(low_bound)
                    + """) := unsigned(write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0));
      """
                )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage
            # sign is in last stage
            # depends on carry
            text += (
                """
      -- ???Full width output last bit is always dropped since DOING SIGNED ADD, can't meanfully overflow
      --???? SIGN EXTENSION DONE AS PART OF SIGNED RESIZED
      write_pipe.full_width_return_output("""
                + str(max_input_width + 1)
                + """) := '0';
      -- Resize from full width to output width
      --???write_pipe.return_output := resize(signed(std_logic_vector(write_pipe.full_width_return_output("""
                + str(max_input_width - 1)
                + """ downto 0))), """
                + str(output_width)
                + """);   
      write_pipe.return_output := resize(signed(std_logic_vector(write_pipe.full_width_return_output("""
                + str(max_input_width)
                + """ downto 0))), """
                + str(output_width)
                + """);    

"""
            )
            # Last stage so no else if
            text += """
    end if;
    """
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Bottom start moving upward, increment low_bound only
            low_bound = low_bound + bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


# Inferred mult using * operator - different from in fabric GET_BIN_OP_MULT_C_CODE
def GET_BIN_OP_MULT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params
):
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
    """
  output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
  left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
  right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
  max_input_width = max(left_width,right_width)
  """

    wires_decl_text = (
        """  
  left : """
        + left_vhdl_type
        + """;
  right : """
        + right_vhdl_type
        + """;
  return_output : """
        + output_vhdl_type
        + """;
"""
    )
    # Only have a few options for dsp mult inference it seems
    # IO regs plus a pipeline reg - cant have pipeline with IO it seems
    # MAx clocks is input reg and output reg
    # max_clocks = 2
    latency = len(timing_params._slices)
    num_stages = latency + 1
    # Which stage gets the '*' operator
    stage_for_op = None
    if latency == 0:
        # Comb. mult
        stage_for_op = 0
    elif latency == 1:
        # Rely on percent
        stage_for_op = 0
        # If slice is to left logic is on right
        if timing_params._slices[0] < 0.5:
            stage_for_op = 1
    elif latency == 2:
        # INput reg and output reg logic in middle
        # IN stage 1 :  0 | 1 | 2
        stage_for_op = 1
    # Mult needs special case 3 to put pipeline reg after always
    elif latency == 3:
        # IN stage 1 :  0 | 1 | 2 | 3
        stage_for_op = 1
    # Shouldnt need this but can do it
    elif latency % 2 == 0:
        # Even
        # Ex. 4 | | | |
        #      0 1 2 3 4
        # Jsut put in middle stage
        stage_for_op = int(latency / 2)
    else:
        # Odd, ex 5:  | | | | |
        #                 ^
        # Depends on position of middle slice
        middle_index = int(latency / 2)
        middle_slice = timing_params._slices[middle_index]
        # If slice is to left, logic is on right
        stage_for_op = middle_index
        if middle_slice < 0.5:
            stage_for_op = middle_index + 1

    text = ""
    text += (
        """
  if STAGE = """
        + str(stage_for_op)
        + """ then
    write_pipe.return_output := write_pipe.left * write_pipe.right;
  end if;
  """
    )

    return wires_decl_text, text


def GET_ACCUM_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params
):
    # Accum only for uint for now?
    if VHDL.WIRES_ARE_UINT_N(logic.inputs, logic):
        return GET_ACCUM_UINT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    elif VHDL.WIRES_ARE_INT_N([logic.inputs[0]], logic):
        return GET_ACCUM_INT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    else:
        print("What kind of accum?", logic.wire_to_c_type)
        sys.exit(-1)


def GET_ACCUM_UINT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    accum_type = logic.wire_to_c_type[logic.inputs[0]]
    reset_type = logic.wire_to_c_type[logic.inputs[1]]
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    accum_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, accum_type)
    reset_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, reset_type)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
    # Reuses names from adder -
    # trying to fit state into stateless write_pipe style pipelines will be fucky...
    # Oh shit theres no way to give the accum reg an initial value?
    #   The Flaming Lips - Will You Return / When You Come Down
    max_input_width = accum_width
    wires_decl_text = (
        """
  carry : std_logic_vector(0 downto 0);
  intermediate : std_logic_vector("""
        + str(max_input_width)
        + """ downto 0);
  --left_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  right_resized : unsigned("""
        + str(max_input_width - 1)
        + """ downto 0);
  --accum_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  right_range_slv : std_logic_vector("""
        + str(max_input_width - 1)
        + """ downto 0);
  full_width_return_output : unsigned("""
        + str(max_input_width)
        + """ downto 0);
  return_output : unsigned("""
        + str(output_width - 1)
        + """ downto 0);
  accum : unsigned("""
        + str(output_width - 1)
        + """ downto 0);
  reset_and_read : unsigned("""
        + str(reset_width - 1)
        + """ downto 0);
  increment : unsigned("""
        + str(accum_width - 1)
        + """ downto 0);
"""
    )

    # Do each bit over a clock cycle
    width = max_input_width
    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1
    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)
    # print "num_stages",num_stages
    # print "bits_per_stage_dict",bits_per_stage_dict

    # Write loops to do operation
    text = ""
    text += """
  --
  -- Down to one bit accumulator adder with carry
"""

    text += (
        """
  -- width = """
        + str(width)
        + """
  -- num_stages = """
        + str(num_stages)
        + """
  -- bits per stage = """
        + str(bits_per_stage_dict)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      -- This stuff must be in stage 0
      write_pipe.carry := (others => '0'); -- One bit unsigned
      -- Left is the accumulated value
      -- Right increment
      write_pipe.right_resized := resize(write_pipe.increment, """
        + str(width)
        + """);
      write_pipe.return_output := (others => '0');
      write_pipe.full_width_return_output := (others => '0');
      """
    )

    # Write bound of loop per stage
    stage = 0
    # Bottom start only increment low_bound, up_bound is calculated each iteration
    low_bound = 0
    for stage in range(0, num_stages):
        # Bottom start moving upward
        up_bound = low_bound + bits_per_stage_dict[stage] - 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """
        write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));  
        -- Adding unsigned values
        write_pipe.intermediate := (others => '0'); -- Zero out for this stage"""
            )

            # No carry for stage 0
            if stage == 0:
                text += (
                    """
        write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0) := std_logic_vector( unsigned('0' & read_raw_hdl_pipeline_regs(STAGE).accum("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) + unsigned('0' & write_pipe.right_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) );"""
                )
            else:
                text += (
                    """
        write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0) := std_logic_vector( unsigned('0' & read_raw_hdl_pipeline_regs(STAGE).accum("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) + unsigned('0' & write_pipe.right_range_slv("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0)) + unsigned(write_pipe.carry) );"""
                )

            text += (
                """
        -- New carry is msb of intermediate
        write_pipe.carry(0) := write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """);
        -- Accum/output gets/is intermediate if not reset
        if(write_pipe.reset_and_read > 0) then
          -- Reset the accumulated value to zeros for now
          write_pipe.accum("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := (others => '0');
        else
          -- Not reset, accumulate
          write_pipe.accum("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := unsigned(write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0));   
        end if;
        -- Assign output bits
        -- Carry full_width_return_output(up_bound+1) will be overidden in next iteration and included as carry
        write_pipe.full_width_return_output("""
                + str(up_bound + 1)
                + """ downto """
                + str(low_bound)
                + """) := unsigned(write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0));
      """
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage
            # sign is in last stage
            # depends on carry
            text += (
                """
      write_pipe.return_output := resize(write_pipe.full_width_return_output("""
                + str(max_input_width)
                + """ downto 0), """
                + str(output_width)
                + """);      
"""
            )
            # Last stage so no else if
            text += """
    end if;
    """
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Bottom start moving upward, increment low_bound only
            low_bound = low_bound + bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_ACCUM_INT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    # This gets back to how much I hate twos complement
    #   Rush - Vital Signs
    # Fuck this
    # Left accum
    # Right is increment
    accum_type = logic.wire_to_c_type[logic.inputs[0]]
    reset_type = logic.wire_to_c_type[logic.inputs[1]]
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    accum_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, accum_type)
    reset_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, reset_type)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
    max_input_width = accum_width

    # Do each bit over a clock cycle
    width = max_input_width + 1  # Extra bit for sign?
    # YEah this whole business with signed numbers treated as unsigned is f'd below and in int add
    # Especially with use of min(, accum_width-1) below

    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
    wires_decl_text = (
        """
  carry : std_logic_vector(0 downto 0);
  intermediate : std_logic_vector("""
        + str(max_input_width + 1)
        + """ downto 0);
  right_resized : unsigned("""
        + str(max_input_width)
        + """ downto 0);
  right_range_slv : std_logic_vector("""
        + str(max_input_width)
        + """ downto 0);
  full_width_return_output : unsigned("""
        + str(max_input_width + 1)
        + """ downto 0);
  return_output : signed("""
        + str(output_width - 1)
        + """ downto 0);
  accum : unsigned("""
        + str(accum_width - 1)
        + """ downto 0); -- Lie about accum being signed
  increment : signed("""
        + str(accum_width - 1)
        + """ downto 0);
  reset_and_read : unsigned("""
        + str(reset_width - 1)
        + """ downto 0);
"""
    )

    # Output width must be 1 greater than max of input widths
    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1
    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)

    # Write loops to do operation
    text = ""
    text += """
  --
  -- One bit adder with carry
"""

    text += (
        """
  -- num_stages = """
        + str(num_stages)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      -- This stuff must be in stage 0
      -- Left is the accumulated value
      -- Right increment
      write_pipe.carry := (others => '0'); -- One bit unsigned  
      write_pipe.intermediate := (others => '0'); -- N bit unused depending on bits per stage
      write_pipe.right_resized := unsigned(std_logic_vector(resize(write_pipe.increment, """
        + str(width)
        + """)));
      write_pipe.full_width_return_output := (others => '0');
      write_pipe.return_output := (others => '0');
      """
    )

    # 1111111111111111111111111111111110000000000000000000000000000000
    # +
    # 1111111111111111111111111111111110000000000000000000000000000000
    # ===============================================================
    # 1111111111111111111111111111111100000000000000000000000000000000

    # Write bound of loop per stage
    stage = 0
    # Bottom start only increment low_bound, up_bound is calculated each iteration
    low_bound = 0
    for stage in range(0, num_stages):
        # Bottom start moving upward
        up_bound = low_bound + bits_per_stage_dict[stage] - 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            accum_upper_bound = min(bits_per_stage_dict[stage] - 1, accum_width - 1)
            accum_bits_this_stage = accum_upper_bound + 1
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """
        write_pipe.right_range_slv := (others => '0');
        write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0) := std_logic_vector(write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """));  

        -- Adding unsigned values
        write_pipe.intermediate := (others => '0'); -- Zero out for this stage
        write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """ downto 0) := std_logic_vector( unsigned('0' & read_raw_hdl_pipeline_regs(STAGE).accum("""
                + str(accum_upper_bound)
                + """ downto 0)) + unsigned('0' & write_pipe.right_range_slv("""
                + str(bits_per_stage_dict[stage] - 1)
                + """ downto 0)) + unsigned(write_pipe.carry) ); 
        
  """
            )

            text += (
                """
        -- New carry is msb of intermediate
        write_pipe.carry(0) := write_pipe.intermediate("""
                + str(bits_per_stage_dict[stage])
                + """);
        -- Assign output bits
        -- Accum/output gets/is intermediate if not reset
        if(write_pipe.reset_and_read > 0) then
          -- Reset accum to input value
          write_pipe.accum("""
                + str(accum_upper_bound)
                + """ downto 0) := unsigned(write_pipe.right_range_slv("""
                + str(accum_upper_bound)
                + """ downto 0));
          -- Read output is current accumulate value from reg
          write_pipe.full_width_return_output("""
                + str(low_bound + accum_bits_this_stage - 1)
                + """ downto """
                + str(low_bound)
                + """) := read_raw_hdl_pipeline_regs(STAGE).accum("""
                + str(accum_upper_bound)
                + """ downto 0);
        else
          -- Not reset, use accumualted value, and output is that value too
      """
            )
            # Only last iteration writes carry into full_width_return_output?
            if stage == (num_stages - 1):
                text += (
                    """
          -- Only last iteration writes carry into full_width_return_output?
          write_pipe.full_width_return_output("""
                    + str(up_bound + 1)
                    + """ downto """
                    + str(low_bound)
                    + """) := unsigned(write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage])
                    + """ downto 0));
      """
                )
            else:
                text += (
                    """
          -- Dont include carry since not last stage
          write_pipe.full_width_return_output("""
                    + str(up_bound)
                    + """ downto """
                    + str(low_bound)
                    + """) := unsigned(write_pipe.intermediate("""
                    + str(bits_per_stage_dict[stage] - 1)
                    + """ downto 0));
      """
                )
            text += (
                """
          -- Accumulate
          write_pipe.accum("""
                + str(accum_upper_bound)
                + """ downto 0) := unsigned(write_pipe.intermediate("""
                + str(accum_upper_bound)
                + """ downto 0));
       end if;"""
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage
            # sign is in last stage
            # depends on carry
            text += (
                """
      -- ???Full width output last bit is always dropped since DOING SIGNED ADD, can't meanfully overflow
      --???? SIGN EXTENSION DONE AS PART OF SIGNED RESIZED
      write_pipe.full_width_return_output("""
                + str(max_input_width + 1)
                + """) := '0';
      -- Resize from full width to output width
      write_pipe.return_output := resize(signed(std_logic_vector(write_pipe.full_width_return_output("""
                + str(max_input_width)
                + """ downto 0))), """
                + str(output_width)
                + """);    

"""
            )
            # Last stage so no else if
            text += """
    end if;
    """
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Bottom start moving upward, increment low_bound only
            low_bound = low_bound + bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_BIN_OP_PLUS_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # Binary operation between what two types?
    # Only ints for now, check all inputs
    if VHDL.WIRES_ARE_INT_N(logic.inputs, logic):
        return GET_BIN_OP_PLUS_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    elif VHDL.WIRES_ARE_UINT_N(logic.inputs, logic):
        return GET_BIN_OP_PLUS_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params
        )
    else:
        print("Only u/int binary op plus for now!", logic.wire_to_c_types)
        sys.exit(-1)


def GET_BIN_OP_LT_LTE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params, op_str
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # Binary operation between what two types?
    # Only ints for now, check all inputs
    if VHDL.WIRES_ARE_INT_N(logic.inputs, logic):
        return GET_BIN_OP_LT_LTE_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params, op_str
        )
    elif VHDL.WIRES_ARE_UINT_N(logic.inputs, logic):
        return GET_BIN_OP_LT_LTE_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params, op_str
        )
    else:
        print(logic.c_ast_node)
        print("Binary op LT/E for type?", logic.c_ast_node.coord)
        sys.exit(-1)


def GET_BIN_OP_GT_GTE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params, op_str
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # Binary operation between what two types?
    # Only ints for now, check all inputs
    if VHDL.WIRES_ARE_INT_N(logic.inputs, logic):
        return GET_BIN_OP_GT_GTE_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params, op_str
        )
    elif VHDL.WIRES_ARE_UINT_N(logic.inputs, logic):
        return GET_BIN_OP_GT_GTE_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params, op_str
        )
    else:
        print("Binary op GT/GTE for type?", logic.c_ast_node.coord)
        sys.exit(-1)


def GET_BIN_OP_GT_GTE_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params, op_str
):
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    max_width = max(left_width, right_width)
    wires_decl_text = (
        """ 
  return_output : unsigned(0 downto 0);
  return_output_bool : boolean;
  right : signed("""
        + str(right_width - 1)
        + """ downto 0);
  left : signed("""
        + str(left_width - 1)
        + """ downto 0);
  right_resized : signed("""
        + str(max_width - 1)
        + """ downto 0);
  left_resized : signed("""
        + str(max_width - 1)
        + """ downto 0);
  inequality_found : boolean;
  same_sign : boolean;
"""
    )

    # C built in VHDL GT uses 5 LLs, this is 6LLs ... OK for now....

    # Goal here is to have a maximum pipeline depth and crazy utilization if it meets timing
    # Whats the max number of clocks we can do?
    # Smallest possible computation of binary op should be one bit at a time?
    # WIKI:"we inspect the relative magnitudes of pairs of significant digits,
    # starting from the most significant bit, gradually proceeding towards
    # lower significant bits until an inequality is found.
    # When an inequality is found, if the corresponding bit of A is 1
    # and that of B is 0 then we conclude that A>B"

    # Do each bit over a clock cycle

    # TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
    width = max_width
    unsigned_width = width - 1  # sign bit
    max_clocks = unsigned_width
    if len(timing_params._slices) > max_clocks:
        print(
            "Cannot do a c built in int binary op GT operation of",
            unsigned_width,
            "bits in",
            len(timing_params._slices),
            "clocks!",
        )
        sys.exit(-1)  # Eventually fix

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1

    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(unsigned_width, timing_params)

    # Write loops to do operation
    text = ""
    text += (
        """
  -- we inspect the relative magnitudes of pairs of significant digits, 
  -- starting from the most significant bit, gradually proceeding towards 
  -- lower significant bits until an inequality is found. 
  -- When an inequality is found, if the corresponding bit of A is 1 
  -- and that of B is 0 then we conclude that A>B"
  --
  -- num_stages = """
        + str(num_stages)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(max_width)
        + """);
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(max_width)
        + """);
      write_pipe.inequality_found := false; -- Must be at stage 0     
      -- Default: assume signs are different
      -- -left > +right = false 
      -- left > -right = true
      write_pipe.return_output_bool := write_pipe.right_resized("""
        + str(width - 1)
        + """) = '1'; -- True if right is neg
      -- Check if signs are equal
      write_pipe.same_sign := write_pipe.left_resized("""
        + str(width - 1)
        + """) = write_pipe.right_resized("""
        + str(width - 1)
        + """);
  """
    )
    # Write bound of loop per stage
    stage = 0
    # Top start, only increment up_bound, low_bound is calculated each iteration
    up_bound = unsigned_width - 1  # Skip sign (which should be 0 for abs values)
    for stage in range(0, num_stages):
        # Top start moving down
        low_bound = up_bound - bits_per_stage_dict[stage] + 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """ 
        --- Assign output based on compare range for this stage
        if write_pipe.inequality_found = false then
          write_pipe.inequality_found := ( write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) /= write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) ) ;
          -- Check if signs are equal
          if write_pipe.same_sign then
            -- Same sign only compare unsigned magnitude, twos complement makes it make sense
            write_pipe.return_output_bool := ( unsigned(write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """)) > unsigned(write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """)) );
          end if;
        end if;"""
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage so no else if
            # Maybe include or equal in this last stage -  sad. Chaos Arpeggiating - of Montreal
            if op_str.endswith("="):
                text += """
      -- OR EQUAL
      write_pipe.return_output_bool := write_pipe.return_output_bool or (not write_pipe.inequality_found and write_pipe.same_sign);"""

            # Convert bool to unsigned
            text += """
      if write_pipe.return_output_bool then
        write_pipe.return_output := (others => '1');
      else
        write_pipe.return_output := (others => '0');
      end if;
      
    end if;"""
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Top start, moving down decrement up_bound only
            up_bound = up_bound - bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_BIN_OP_LT_LTE_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params, op_str
):
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    max_width = max(left_width, right_width)
    wires_decl_text = (
        """ 
  return_output : unsigned(0 downto 0);
  return_output_bool : boolean;
  right : signed("""
        + str(right_width - 1)
        + """ downto 0);
  left : signed("""
        + str(left_width - 1)
        + """ downto 0);
  right_resized : signed("""
        + str(max_width - 1)
        + """ downto 0);
  left_resized : signed("""
        + str(max_width - 1)
        + """ downto 0);
  inequality_found : boolean;
  same_sign : boolean;
"""
    )

    # Goal here is to have a maximum pipeline depth and crazy utilization if it meets timing
    # Do each bit over a clock cycle if needed

    # TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
    width = max_width
    unsigned_width = width - 1  # sign bit

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1
    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(unsigned_width, timing_params)

    # Write loops to do operation
    text = ""
    text += (
        """
  --
  -- num_stages = """
        + str(num_stages)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(max_width)
        + """);
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(max_width)
        + """);
      write_pipe.inequality_found := false; -- Must be at stage 0     
      -- Default: assume signs are different
      -- -left < +right = true 
      -- +left < -right = false
      write_pipe.return_output_bool := write_pipe.left_resized("""
        + str(width - 1)
        + """) = '1'; -- True if left is neg
      -- Check if signs are equal
      write_pipe.same_sign := write_pipe.left_resized("""
        + str(width - 1)
        + """) = write_pipe.right_resized("""
        + str(width - 1)
        + """);
  """
    )
    # Write bound of loop per stage
    stage = 0
    # Top start, only increment up_bound, low_bound is calculated each iteration
    up_bound = unsigned_width - 1  # Skip sign (which should be 0 for abs values)
    for stage in range(0, num_stages):
        # Top start moving down
        low_bound = up_bound - bits_per_stage_dict[stage] + 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """ 
        --- Assign output based on compare range for this stage
        if write_pipe.inequality_found = false then
          write_pipe.inequality_found := ( write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) /= write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) ) ;
          -- Check if signs are equal
          if write_pipe.same_sign then
            -- Same sign only compare unsigned magnitude, twos complement makes it make sense
            write_pipe.return_output_bool := ( unsigned(write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """)) < unsigned(write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """)) );
          end if;
        end if;"""
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage so no else if
            # Maybe include or equal in this last stage -  sad. Chaos Arpeggiating - of Montreal
            if op_str.endswith("="):
                text += """
      -- OR EQUAL
      write_pipe.return_output_bool := write_pipe.return_output_bool or (not write_pipe.inequality_found and write_pipe.same_sign);"""

            # Convert bool to unsigned
            text += """
      if write_pipe.return_output_bool then
        write_pipe.return_output := (others => '1');
      else
        write_pipe.return_output := (others => '0');
      end if;
      
    end if;"""
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Top start, moving down decrement up_bound only
            up_bound = up_bound - bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_BIN_OP_LT_LTE_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params, op_str
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    max_width = max(left_width, right_width)
    wires_decl_text = (
        """
  return_output_bool : boolean;
  return_output : unsigned(0 downto 0);
  right : unsigned("""
        + str(right_width - 1)
        + """ downto 0);
  left : unsigned("""
        + str(left_width - 1)
        + """ downto 0);
  right_resized : unsigned("""
        + str(max_width - 1)
        + """ downto 0);
  left_resized : unsigned("""
        + str(max_width - 1)
        + """ downto 0);
  inequality_found : boolean;
"""
    )

    # TODO: FIX extra logic levels

    # Do each bit over a clock cycle
    width = max_width

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1

    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)

    # Write loops to do operation
    text = ""
    text += (
        """
  -- num_stages = """
        + str(num_stages)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(max_width)
        + """);
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(max_width)
        + """);
      write_pipe.inequality_found := false; -- Must be at stage 0
  """
    )

    # Write bound of loop per stage
    stage = 0
    # Top start, only increment up_bound, low_bound is calculated each iteration
    up_bound = width - 1
    for stage in range(0, num_stages):
        # Top start moving down
        low_bound = up_bound - bits_per_stage_dict[stage] + 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """ 
        --- Assign output based on compare range for this stage
        if write_pipe.inequality_found = false then
          write_pipe.inequality_found := ( write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) /= write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) ) ;
          -- Compare magnitude
          write_pipe.return_output_bool := ( write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) < write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) );
        end if;"""
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage so no else if
            # Maybe include or equal in this last stage -  sad. How I Left the Ministry - The Mountain Goats
            if op_str.endswith("="):
                text += """
      -- OR EQUAL
      write_pipe.return_output_bool := write_pipe.return_output_bool or not write_pipe.inequality_found;"""

            # Convert bool to unsigned
            text += """
      if write_pipe.return_output_bool then
        write_pipe.return_output := (others => '1');
      else
        write_pipe.return_output := (others => '0');
      end if;
      
    end if;"""
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Top start, moving down decrement up_bound only
            up_bound = up_bound - bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


# TODO: Combine GT+LT? Since using op_str?


def GET_BIN_OP_GT_GTE_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params, op_str
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    left_type = logic.wire_to_c_type[logic.inputs[0]]
    right_type = logic.wire_to_c_type[logic.inputs[1]]
    left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
    max_width = max(left_width, right_width)
    wires_decl_text = (
        """ 
  return_output_bool : boolean;
  return_output : unsigned(0 downto 0);
  right : unsigned("""
        + str(right_width - 1)
        + """ downto 0);
  left : unsigned("""
        + str(left_width - 1)
        + """ downto 0);
  right_resized : unsigned("""
        + str(max_width - 1)
        + """ downto 0);
  left_resized : unsigned("""
        + str(max_width - 1)
        + """ downto 0);
  inequality_found : boolean;
"""
    )

    # C built in VHDL GT uses 5 LLs, this is 6LLs ... OK for now....

    # Goal here is to have a maximum pipeline depth and crazy utilization if it meets timing
    # Whats the max number of clocks we can do?
    # Smallest possible computation of binary op should be one bit at a time?
    # WIKI:"we inspect the relative magnitudes of pairs of significant digits,
    # starting from the most significant bit, gradually proceeding towards
    # lower significant bits until an inequality is found.
    # When an inequality is found, if the corresponding bit of A is 1
    # and that of B is 0 then we conclude that A>B"

    # Do each bit over a clock cycle
    width = max_width

    # How many bits per stage?
    # 0th stage is combinatorial logic
    num_stages = len(timing_params._slices) + 1

    bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)

    # Write loops to do operation
    text = ""
    text += (
        """
  -- we inspect the relative magnitudes of pairs of significant digits, 
  -- starting from the most significant bit, gradually proceeding towards 
  -- lower significant bits until an inequality is found. 
  -- When an inequality is found, if the corresponding bit of A is 1 
  -- and that of B is 0 then we conclude that A>B"
  --
  -- num_stages = """
        + str(num_stages)
        + """
  """
    )
    text += (
        """
    if STAGE = 0 then
      write_pipe.right_resized := resize(write_pipe.right, """
        + str(max_width)
        + """);
      write_pipe.left_resized := resize(write_pipe.left, """
        + str(max_width)
        + """);
      write_pipe.inequality_found := false; -- Must be at stage 0
  """
    )

    # Write bound of loop per stage
    stage = 0
    # Top start, only increment up_bound, low_bound is calculated each iteration
    up_bound = width - 1  # Skip sign (which should be 0 for abs values)
    for stage in range(0, num_stages):
        # Top start moving down
        low_bound = up_bound - bits_per_stage_dict[stage] + 1
        # Do stage logic / bit pos increment if > 0 bits this stage
        if bits_per_stage_dict[stage] > 0:
            text += (
                """
        --  bits_per_stage_dict["""
                + str(stage)
                + """] = """
                + str(bits_per_stage_dict[stage])
                + """ 
        --- Assign output based on compare range for this stage
        if write_pipe.inequality_found = false then
          write_pipe.inequality_found := ( write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) /= write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) ) ;
          -- Compare magnitude
          write_pipe.return_output_bool := ( write_pipe.left_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) """
                + op_str
                + """ write_pipe.right_resized("""
                + str(up_bound)
                + """ downto """
                + str(low_bound)
                + """) );
        end if;"""
            )

        # More stages?
        if stage == (num_stages - 1):
            # Last stage so no else if
            text += """
      
      if write_pipe.return_output_bool then
        write_pipe.return_output := (others => '1');
      else
        write_pipe.return_output := (others => '0');
      end if;
      
    end if;"""
            return wires_decl_text, text
        else:
            # Next stage
            # Set next vals
            stage = stage + 1
            # Top start, moving down decrement up_bound only
            up_bound = up_bound - bits_per_stage_dict[stage - 1]
            # More stages to go
            text += (
                """   
    elsif STAGE = """
                + str(stage)
                + """ then """
            )


def GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # Cond input is [0] and bool, look at true and false ones only
    tf_inputs = logic.inputs[1:]
    if len(tf_inputs) != 2:
        print("Not 2 input MUX??")
        for tf_input in tf_inputs:
            print(tf_input, logic.wire_to_c_type[tf_input])
        print("logic.inputs", logic.inputs)
        sys.exit(-1)

    # Doesnt need to be clock divisiable at least for now
    # Cond input is bool look at true and false ones only
    in_wire = tf_inputs[0]
    c_type = logic.wire_to_c_type[in_wire]
    input_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state)

    wires_decl_text = (
        """  
  return_output : """
        + input_vhdl_type
        + """;
  cond : unsigned(0 downto 0);
  iftrue : """
        + input_vhdl_type
        + """;
  iffalse : """
        + input_vhdl_type
        + """;
"""
    )

    latency = len(timing_params._slices)
    num_stages = latency + 1
    chunked = latency > 0
    direct_vector = input_vhdl_type.startswith(
        ("unsigned(", "signed(", "std_logic_vector(")
    )
    if chunked:
        width = GET_MUX_DATA_WIDTH(logic, parser_state)
        bits_per_stage = GET_BITS_PER_STAGE_DICT(width, timing_params)
        if not direct_vector:
            packed_len = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_STR(c_type, parser_state)
            wires_decl_text += (
                "  return_output_slv : std_logic_vector("
                + packed_len
                + "-1 downto 0);\n"
                + "  iftrue_slv : std_logic_vector("
                + packed_len
                + "-1 downto 0);\n"
                + "  iffalse_slv : std_logic_vector("
                + packed_len
                + "-1 downto 0);\n"
            )
            to_slv_toks = VHDL.VHDL_TYPE_TO_SLV_TOKS(
                input_vhdl_type, parser_state
            )
            from_slv_toks = VHDL.VHDL_TYPE_FROM_SLV_TOKS(
                input_vhdl_type, parser_state
            )
        text = ""
        low = 0
        for stage in range(num_stages):
            count = bits_per_stage[stage]
            high = low + count - 1
            keyword = "if" if stage == 0 else "elsif"
            text += f"\n    {keyword} STAGE = {stage} then\n"
            if stage == 0 and direct_vector:
                text += "      write_pipe.return_output := (others => '0');\n"
            elif stage == 0:
                text += (
                    "      write_pipe.return_output_slv := (others => '0');\n"
                    "      write_pipe.iftrue_slv := "
                    + to_slv_toks[0]
                    + "write_pipe.iftrue"
                    + to_slv_toks[1]
                    + ";\n"
                    "      write_pipe.iffalse_slv := "
                    + to_slv_toks[0]
                    + "write_pipe.iffalse"
                    + to_slv_toks[1]
                    + ";\n"
                )
            if count > 0:
                output_name = "return_output" if direct_vector else "return_output_slv"
                true_name = "iftrue" if direct_vector else "iftrue_slv"
                false_name = "iffalse" if direct_vector else "iffalse_slv"
                text += "      if write_pipe.cond=1 then\n"
                text += (
                    f"        write_pipe.{output_name}({high} downto {low}) := "
                    f"write_pipe.{true_name}({high} downto {low});\n"
                )
                text += "      else\n"
                text += (
                    f"        write_pipe.{output_name}({high} downto {low}) := "
                    f"write_pipe.{false_name}({high} downto {low});\n"
                )
                text += "      end if;\n"
            if stage == num_stages - 1 and not direct_vector:
                text += (
                    "      write_pipe.return_output := "
                    + from_slv_toks[0]
                    + "write_pipe.return_output_slv"
                    + from_slv_toks[1]
                    + ";\n"
                )
            low += count
        text += "    end if;\n"
        return wires_decl_text, text

    # Which stage gets the 1 LL ?
    stage_for_1ll = None
    if latency == 0:
        stage_for_1ll = 0
    elif latency == 1:
        # Rely on percent
        stage_for_1ll = 0
        # If slice is to left logic is on right
        if timing_params._slices[0] < 0.5:
            stage_for_1ll = 1
    elif latency == 2:
        # INput reg and output reg logic in middle
        # IN stage 1 :  0 | 1 | 2
        stage_for_1ll = 1
    # Shouldnt need this but can do it
    elif latency % 2 == 0:
        # Even
        # Ex. 4 | | | |
        #      0 1 2 3 4
        # Jsut put in middle stage
        stage_for_1ll = int(latency / 2)
    else:
        # Odd, ex 5:  | | | | |
        #                 ^
        # Depends on position of middle slice
        middle_index = int(latency / 2)
        middle_slice = timing_params._slices[middle_index]
        # If slice is to left, logic is on right
        stage_for_1ll = middle_index
        if middle_slice < 0.5:
            stage_for_1ll = middle_index + 1

    # VHDL text is just the IF for the stage in question
    text = ""
    text += (
        """
    if STAGE = """
        + str(stage_for_1ll)
        + """ then
      -- Assign output based on range for this stage
      if write_pipe.cond=1 then
        write_pipe.return_output := write_pipe.iftrue;
      else
        write_pipe.return_output := write_pipe.iffalse;
      end if;
    end if;     
  """
    )

    return wires_decl_text, text


def GET_CAST_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, LogicInstLookupTable, timing_params, parser_state
):
    # ONLY INTS FOR NOW
    in_type = logic.wire_to_c_type[logic.inputs[0]]
    in_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(in_type, parser_state)
    in_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_type)
    in_signed = VHDL.C_TYPE_IS_INT_N(in_type)
    output_type = logic.wire_to_c_type[logic.outputs[0]]
    output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
    output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
    out_signed = VHDL.C_TYPE_IS_INT_N(output_type)

    wires_decl_text = (
        """
  --variable rhs : """
        + in_vhdl_type
        + """;
  variable return_output : """
        + output_vhdl_type
        + """;
"""
    )
    text = ""
    if out_signed:
        text += (
            """
      return_output := signed(std_logic_vector(resize(rhs,"""
            + str(output_width)
            + """)));
    """
        )
    else:
        text += (
            """
      return_output := unsigned(std_logic_vector(resize(rhs,"""
            + str(output_width)
            + """)));
    """
        )
    text += """return return_output;"""

    return wires_decl_text, text


def GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    toks = logic.func_name.split("_")
    # Bit slice or concat?
    # print "toks",toks
    # Bit slice

    # New float_e_m_t bit select
    if len(toks) == 6 and "float" in logic.func_name:
        high = int(toks[4])
        low = int(toks[5])
        return GET_BIT_SLICE_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
            logic, parser_state, timing_params, high, low
        )

    elif len(toks) == 5 and "float" in logic.func_name:
        if "uint" in logic.func_name:
            # float_e_m_t_uintN construct
            return GET_FLOAT_UINT_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        elif toks[-1] == "abs":
            # float_e_m_t_abs
            return GET_FLOAT_ABS_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        elif toks[-1] == "sign":
            # float_e_m_t_sign
            return GET_FLOAT_SIGN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        else:
            print(
                "0GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT for ",
                logic.func_name,
                "?",
            )
            sys.exit(-1)

    elif len(toks) == 3:
        if (
            logic.func_name.startswith("float_")
            and not toks[1].isdigit()
            and not toks[2].isdigit()
        ):
            return GET_FLOAT_SEM_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        # Array to unsigned # uint8_array250_le
        elif "array" in toks[1]:
            return GET_ARRAY_TO_UNSIGNED_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        # Eith BIT SLICE #uint64_39_39(
        elif not toks[0].isdigit() and toks[1].isdigit() and toks[2].isdigit():
            high = int(toks[1])
            low = int(toks[2])
            return GET_BIT_SLICE_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params, high, low
            )
        # OR BIT ASSIGN # uint64_uint15_2(
        elif "int" in toks[0] and "int" in toks[1] and toks[2].isdigit():
            # Above will fail if is BIT assign
            # print("bit assign?",logic.func_name)
            return GET_BIT_ASSIGN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, timing_params, parser_state
            )
        # unsigned to array # uint64_8_be
        elif (
            "int" in toks[0]
            and (toks[2] == "be" or toks[2] == "le")
            and toks[1].isdigit()
        ):
            return GET_UNSIGNED_TO_ARRAY_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        else:
            print(
                "1GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT for ",
                logic.func_name,
                "?",
            )
            sys.exit(-1)

    elif len(toks) == 2:
        if toks[0] == "float" and "uint" in toks[1]:
            return GET_FLOAT_UINT_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        elif toks[0] == "bswap":
            # Byte swap
            return GET_BYTE_SWAP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        elif toks[0].startswith("rotl"):
            # Rotate left
            return GET_ROTL_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        elif toks[0].startswith("rotr"):
            # Rotate right
            return GET_ROTR_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        # Bit concat or bit duplicate?
        elif "int" in toks[0] and toks[1].isdigit():
            # Duplicate
            return GET_BIT_DUP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, timing_params, parser_state
            )
        elif "int" in toks[0] and "int" in toks[1]:
            # Concat
            return GET_BIT_CONCAT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        elif "float" in toks[0] and toks[1] == "abs":
            return GET_FLOAT_ABS_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
                logic, parser_state, timing_params
            )
        else:
            print(
                "2GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT for ",
                logic.func_name,
                "?",
            )
            sys.exit(-1)
    else:
        print(
            "3GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT for ",
            logic.func_name,
            "?",
        )
        sys.exit(-1)


def GET_FLOAT_SIGN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    in_type = logic.wire_to_c_type[logic.inputs[0]]
    in_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(in_type, parser_state)
    in_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_type)
    out_type = "uint1_t"
    out_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(out_type, parser_state)

    wires_decl_text = (
        """
  --variable x : """
        + in_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Float sign must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a float sign in multiple clocks!?")
        sys.exit(-1)

    text = """
    return_output(0) := x(x'left); -- left most sign bit
    return return_output;
"""

    return wires_decl_text, text


def GET_FLOAT_ABS_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    in_type = logic.wire_to_c_type[logic.inputs[0]]
    in_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(in_type, parser_state)
    in_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_type)
    out_type = logic.wire_to_c_type[logic.outputs[0]]
    out_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(out_type, parser_state)

    wires_decl_text = (
        """
  --variable x : """
        + in_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Float abs must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a float abs in multiple clocks!?")
        sys.exit(-1)

    text = """
    return_output := x; -- Same value
    return_output(return_output'left) := '0'; -- Clear sign bit
    return return_output;
"""

    return wires_decl_text, text


def GET_FLOAT_UINT_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    in_type = logic.wire_to_c_type[logic.inputs[0]]
    in_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(in_type, parser_state)
    in_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_type)
    out_width = in_width
    out_vhdl_type = "std_logic_vector(" + str(out_width - 1) + " downto 0)"

    wires_decl_text = (
        """
  --variable x : """
        + in_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Float constrcut must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a float UINT construct concat in multiple clocks!?")
        sys.exit(-1)

    text = """
    return_output := std_logic_vector(x);
    return return_output;
"""

    return wires_decl_text, text


def GET_FLOAT_SEM_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # TODO check for ints only as constructing elements?
    # ONLY INTS FOR NOW
    # print("logic.func_name",logic.func_name,logic.inputs)
    s_type = logic.wire_to_c_type[logic.inputs[0]]
    e_type = logic.wire_to_c_type[logic.inputs[1]]
    m_type = logic.wire_to_c_type[logic.inputs[2]]
    s_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(s_type, parser_state)
    e_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(e_type, parser_state)
    m_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(m_type, parser_state)
    s_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, s_type)
    e_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, e_type)
    m_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, m_type)
    out_width = s_width + e_width + m_width
    out_vhdl_type = "std_logic_vector(" + str(out_width - 1) + " downto 0)"

    wires_decl_text = (
        """
  --variable sign : """
        + s_vhdl_type
        + """;
  --variable exponent : """
        + e_vhdl_type
        + """;
  --variable mantissa : """
        + m_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Float constrcut must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a float construct concat in multiple clocks!?")
        sys.exit(-1)

    text = """
    return_output := std_logic_vector(sign) & std_logic_vector(exponent) & std_logic_vector(mantissa);
    return return_output;
"""

    return wires_decl_text, text


def GET_BIT_CONCAT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # TODO check for ints only?
    # ONLY INTS FOR NOW
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    y_type = logic.wire_to_c_type[logic.inputs[1]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    y_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(y_type, parser_state)
    x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
    y_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, y_type)
    out_width = x_width + y_width
    out_vhdl_type = "unsigned(" + str(out_width - 1) + " downto 0)"

    wires_decl_text = (
        """
  --variable x : """
        + x_vhdl_type
        + """;
  --variable y : """
        + y_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Bit concat must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a bit concat in multiple clocks!?")
        sys.exit(-1)

    text = """
    return_output := unsigned(std_logic_vector(x)) & unsigned(std_logic_vector(y));
    return return_output;
"""

    return wires_decl_text, text


def GET_BYTE_SWAP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    toks = logic.func_name.split("_")
    input_bit_width = int(toks[1])
    result_width = input_bit_width

    # print "logic.inputs",logic.inputs
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)

    wires_decl_text = (
        """
  --variable x : """
        + x_vhdl_type
        + """;
  variable return_output : """
        + x_vhdl_type
        + """;
"""
    )

    # Byte swap must be zero clocks
    if len(timing_params._slices) > 0:
        print("Cannot do a byte swap in multiple clocks!?")
        sys.exit(-1)

    text = """
    for i in 0 to (x'length/8)-1 loop
      -- j=((x'length/8)-1-i)
      return_output( (((x'length/8)-i)*8)-1 downto (((x'length/8)-1-i)*8) ) := x( ((i+1)*8)-1 downto (i*8) );
    end loop;
    
    return return_output;
"""

    return wires_decl_text, text


def GET_BIT_ASSIGN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, timing_params, parser_state
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    toks = logic.func_name.split("_")
    input_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
    assign_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[1] + "_t")
    low_index = int(toks[2])
    high_index = low_index + assign_width - 1
    result_width = input_bit_width

    in_type = logic.wire_to_c_type[logic.inputs[0]]
    in_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(in_type, parser_state)
    in_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_type)

    # print "logic.inputs",logic.inputs
    x_type = logic.wire_to_c_type[logic.inputs[1]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)

    intermediate_width = max(in_width, low_index + assign_width)
    intermediate_vhdl_type = "unsigned(" + str(intermediate_width - 1) + " downto 0)"

    wires_decl_text = (
        """
  --variable inp : """
        + in_vhdl_type
        + """;
  --variable x : """
        + x_vhdl_type
        + """;
  variable intermediate : """
        + intermediate_vhdl_type
        + """;
  variable return_output : """
        + in_vhdl_type
        + """;
"""
    )

    # Bit assign must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a bit assign in multiple clocks!?")
        sys.exit(-1)

    text = (
        """
    intermediate := (others => '0');
    intermediate("""
        + str(in_width - 1)
        + """ downto 0) := unsigned(inp);
    intermediate("""
        + str(high_index)
        + """ downto """
        + str(low_index)
        + """) := x;
    """
    )
    if in_type.startswith("int"):
        text += (
            """
    return_output := signed(intermediate("""
            + str(result_width - 1)
            + """ downto 0)) ;
    """
        )
    else:
        text += (
            """
    return_output := intermediate("""
            + str(result_width - 1)
            + """ downto 0) ;
    """
        )
    text += """
    return return_output;
"""

    return wires_decl_text, text


def GET_CONST_SHIFT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(
    logic, LogicInstLookupTable, timing_params, parser_state
):
    # TODO check for ints only?
    # ONLY INTS FOR NOW
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
    x_is_signed = VHDL.C_TYPE_IS_INT_N(x_type)

    # Shift functions are found in numeric_std package file
    # Shift functions can perform both logical (zero-fill) and arithmetic (keep sign) shifts
    # Type of shift depends on input to function. Unsigned=Logical, Signed=Arithmetic

    shift_func = None
    # Shift right might shift in sign bits if signed/arithmetic shfit
    if logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SL_NAME):
        shift_func = "shift_left"
    elif logic.func_name.startswith(
        C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SR_NAME
    ):
        shift_func = "shift_right"
    else:
        print(
            "Blaag: I should start putting the song I am listening too for debug if I remember"
        )
        print(
            """Brother Sport
        Animal Collective - Merriweather Post Pavilion
        """
        )
        sys.exit(-1)

    shift_const = None
    toks = logic.func_name.split("_")
    shift_const = toks[2]

    out_vhdl_type = x_vhdl_type

    wires_decl_text = (
        """
  x : """
        + x_vhdl_type
        + """;
  return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Const shift must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a const shift in multiple clocks!?")
        sys.exit(-1)

    text = (
        """
    write_pipe.return_output := """
        + shift_func
        + """(write_pipe.x, """
        + shift_const
        + """);"""
    )

    return wires_decl_text, text


def GET_BIT_SLICE_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params, high, low
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # TODO check for ints only?
    # ONLY INTS FOR NOW
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)

    if high >= low:
        out_width = high - low + 1
    else:
        out_width = low - high + 1

    out_vhdl_type = "unsigned(" + str(out_width - 1) + " downto 0)"

    wires_decl_text = (
        """--variable x : """
        + x_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;"""
    )

    # Bit slice must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a bit slice in multiple clocks!?")
        sys.exit(-1)

    if high > low:
        # Regular slice
        text = (
            """return_output := unsigned(std_logic_vector(x("""
            + str(high)
            + """ downto """
            + str(low)
            + """)));\n"""
        )
    else:
        # Reverse slice
        text = (
            """for i in 0 to return_output'length-1 loop
        return_output(i) := x("""
            + str(low)
            + """- i);
      end loop;\n"""
        )

    text += "return return_output;"

    return wires_decl_text, text


def GET_ARRAY_TO_UNSIGNED_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    parser_state.LogicInstLookupTable
    # TODO check for ints only?
    # ONLY INTS FOR NOW
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    # SHould be array
    elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(x_type)
    dim = dims[0]
    out_c_type = logic.wire_to_c_type[logic.outputs[0]]
    out_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(out_c_type, parser_state)

    wires_decl_text = (
        """
  --variable x : """
        + x_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Bit slice must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do array to unsigned in multiple clocks!?")
        sys.exit(-1)

    # Big bit concat
    text = "return_output := "
    be_range = list(range(0, dim))
    le_range = list(range(dim - 1, -1, -1))
    r = be_range
    if logic.func_name.endswith("_le"):
        r = le_range
    for i in r:
        text += "x(" + str(i) + ")&"
    text = text.strip("&")
    text += ";\n"
    text += "return return_output;"

    return wires_decl_text, text


def GET_UNSIGNED_TO_ARRAY_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    out_c_type = logic.wire_to_c_type[logic.outputs[0]]
    out_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(out_c_type, parser_state)
    # Should be array
    elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(out_c_type)
    dim = dims[0]

    wires_decl_text = (
        """
  --variable x : """
        + x_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
  constant ELEM_WIDTH : integer := return_output(0)'length;
"""
    )

    # must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do unsigned to array in multiple clocks!?")
        sys.exit(-1)

    if logic.func_name.endswith("_le"):
        text = """for i in 0 to return_output'length-1 loop
 return_output(i) := x((i+1)*ELEM_WIDTH-1 downto i*ELEM_WIDTH);
end loop;
return return_output;
"""
    else:
        text = """for i in 0 to return_output'length-1 loop
 return_output(i) := x((return_output'length - i)*ELEM_WIDTH-1 downto (return_output'length - i - 1)*ELEM_WIDTH);
end loop;
return return_output;
"""

    return wires_decl_text, text


def GET_BIT_DUP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, timing_params, parser_state
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # TODO check for ints only?
    # ONLY INTS FOR NOW
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
    # Multiplier
    multiplier = int(logic.func_name.split("_")[1])
    out_width = x_width * multiplier
    out_vhdl_type = "unsigned(" + str(out_width - 1) + " downto 0)"

    wires_decl_text = (
        """
  --variable x : """
        + x_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Bit slice must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a bit dup in multiple clocks!?")
        sys.exit(-1)

    text = (
        """
    for i in 0 to """
        + str(multiplier - 1)
        + """ loop
      return_output( (((i+1)*"""
        + str(x_width)
        + """)-1) downto (i*"""
        + str(x_width)
        + """)) := unsigned(std_logic_vector(x));
    end loop;
"""
    )

    text += "return return_output;"

    return wires_decl_text, text


def GET_ROTL_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # TODO check for ints only?
    # ONLY INTS FOR NOW
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
    # Rotate amount
    rot_amount = int(logic.func_name.split("_")[1])
    out_width = x_width
    out_vhdl_type = "unsigned(" + str(out_width - 1) + " downto 0)"

    wires_decl_text = (
        """
  --variable x : """
        + x_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Rotate must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a rotate left in multple clocks!?")
        sys.exit(-1)

    text = (
        """
    return_output := x rol """
        + str(rot_amount)
        + """;
    return return_output;
"""
    )

    return wires_decl_text, text


def GET_ROTR_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(
    logic, parser_state, timing_params
):
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    # TODO check for ints only?
    # ONLY INTS FOR NOW
    x_type = logic.wire_to_c_type[logic.inputs[0]]
    x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
    x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
    # Rotate amount
    rot_amount = int(logic.func_name.split("_")[1])
    out_width = x_width
    out_vhdl_type = "unsigned(" + str(out_width - 1) + " downto 0)"

    wires_decl_text = (
        """
  --variable x : """
        + x_vhdl_type
        + """;
  variable return_output : """
        + out_vhdl_type
        + """;
"""
    )

    # Rotate must always be zero clock
    if len(timing_params._slices) > 0:
        print("Cannot do a rotate right in multple clocks!?")
        sys.exit(-1)

    text = (
        """
    return_output := x ror """
        + str(rot_amount)
        + """;
    return return_output;
"""
    )

    return wires_decl_text, text
