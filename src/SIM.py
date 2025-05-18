import os

import COCOTB
import CXXRTL
import EDAPLAY
import MODELSIM
import SYN
import VERILATOR
import VHDL

# Default simulation tool is free online edaplayground
SIM_TOOL = EDAPLAY


def SET_SIM_TOOL(cmd_line_args):
    global SIM_TOOL
    if cmd_line_args.cocotb:
        SIM_TOOL = COCOTB
    elif cmd_line_args.edaplay:
        SIM_TOOL = EDAPLAY
    elif cmd_line_args.cxxrtl:
        SIM_TOOL = CXXRTL
    elif cmd_line_args.verilator:
        SIM_TOOL = VERILATOR
    elif cmd_line_args.modelsim:
        SIM_TOOL = MODELSIM


def DO_OPTIONAL_SIM(do_sim, parser_state, args, multimain_timing_params=None):
    if SIM_TOOL is COCOTB:
        if do_sim:
            COCOTB.DO_SIM(multimain_timing_params, parser_state, args)
    elif SIM_TOOL is EDAPLAY:
        if do_sim:
            EDAPLAY.SETUP_EDAPLAY(0)
    elif SIM_TOOL is MODELSIM:
        MODELSIM.DO_OPTIONAL_DEBUG(do_sim, 0)
    elif SIM_TOOL is CXXRTL:
        if do_sim:
            CXXRTL.DO_SIM(0, parser_state)
    elif SIM_TOOL is VERILATOR:
        if do_sim:
            VERILATOR.DO_SIM(multimain_timing_params, parser_state, args)
    else:
        print("WARNING: Unknown simulation tool:", SIM_TOOL.__name__)


def GET_SIM_FILES(latency=0):
    # Get all vhd files in syn output
    vhd_files = []
    for root, dirs, filenames in os.walk(SYN.SYN_OUTPUT_DIRECTORY):
        for f in filenames:
            if f.endswith(".vhd"):
                # print "f",f
                fullpath = os.path.join(root, f)
                abs_path = os.path.abspath(fullpath)
                # print "fullpath",fullpath
                # f
                if (
                    (root == SYN.SYN_OUTPUT_DIRECTORY + "/main")
                    and f.startswith("main_")
                    and f.endswith("CLK.vhd")
                ):
                    clks = int(f.replace("main_", "").replace("CLK.vhd", ""))
                    if clks == latency:
                        print("Using top:", abs_path)
                        vhd_files.append(abs_path)
                else:
                    vhd_files.append(abs_path)

    return vhd_files


# Common info about what to generate for simulation
class SimGenInfo:
    def __init__(self):
        self.clock_name_to_mhz = None
        self.debug_input_to_vhdl_name = {}
        self.debug_output_to_vhdl_name = {}
        self.main_func_to_latency = {}


def GET_SIM_GEN_INFO(parser_state, multimain_timing_params=None):
    sim_gen_info = SimGenInfo()
    # Clocks
    clock_name_to_mhz, out_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
        parser_state, None, True
    )
    # Which ones are not from the user internal
    for user_clk_name, clk_mhz in parser_state.clk_mhz.items():
        clk_name = "clk_" + VHDL.CLK_MHZ_GROUP_TEXT(clk_mhz, None)
        # Remove assumed internally produced user clocks from dict
        clock_name_to_mhz.pop(clk_name, None)
        # If clock is external input save with new user name
        if user_clk_name in parser_state.input_wires:
            clock_name_to_mhz[user_clk_name] = clk_mhz
    sim_gen_info.clock_name_to_mhz = clock_name_to_mhz

    # Debug ports
    for output in parser_state.output_wires:
        if output.endswith("_DEBUG"):
            debug_name = output.split("_DEBUG")[0]
            sim_gen_info.debug_output_to_vhdl_name[debug_name] = output
    for input in parser_state.input_wires:
        if input.endswith("_DEBUG"):
            debug_name = input.split("_DEBUG")[0]
            sim_gen_info.debug_input_to_vhdl_name[debug_name] = input

    # Main func latencies
    for func in parser_state.main_mhz:
        if multimain_timing_params is not None:
            main_timing_params = multimain_timing_params.TimingParamsLookupTable[func]
            main_latency = main_timing_params.GET_TOTAL_LATENCY(
                parser_state, multimain_timing_params.TimingParamsLookupTable
            )
        else:
            main_latency = 0
        sim_gen_info.main_func_to_latency[func] = main_latency

    return sim_gen_info
