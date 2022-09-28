import os
import sys

import C_TO_LOGIC
import SYN
import VHDL
from utilities import GET_TOOL_PATH


def DO_SIM(multimain_timing_params, parser_state, args):
    print(
        "================== Doing cocotb Simulation ================================",
        flush=True,
    )

    # Check for cocotb-config tool
    tool_path = GET_TOOL_PATH("cocotb-config")
    if tool_path is None:
        raise Exception("cocotb does not appear installed. cocotb-config not in path!")
    print(tool_path)

    # Generate a template py script and make file
    # Or use user specified makefile(and .py)
    COCOTB_OUT_DIR = SYN.SYN_OUTPUT_DIRECTORY + "/cocotb"
    if not os.path.exists(COCOTB_OUT_DIR):
        os.makedirs(COCOTB_OUT_DIR)
    if args.makefile:
        # Existing makefile
        makefile_path = os.path.abspath(args.makefile)
        makefile_dir = os.path.dirname(makefile_path)
    else:
        # Generate makefile (and dummy tb)
        makefile_path = COCOTB_OUT_DIR + "/" + "Makefile"
        makefile_dir = COCOTB_OUT_DIR
        py_basename = "test_" + SYN.TOP_LEVEL_MODULE
        # What sim tool?
        sim_make_args = ""
        if args.ghdl:
            sim_make_args += "SIM ?= ghdl\n"
            sim_make_args += "EXTRA_ARGS += --std=08\n"
            sim_tool_path = GET_TOOL_PATH("ghdl")
            if sim_tool_path is None:
                raise Exception("GHDL does not appear installed. ghdl not in path!")
        else:
            raise NotImplementedError("No supported cocotb simulator specified!")

        # Write make file
        makefile_text = f"""
{sim_make_args}
TOPLEVEL_LANG ?= vhdl

#VERILOG_SOURCES += $(PWD)/my_design.sv
# use VHDL_SOURCES for VHDL files
VHDL_SOURCES += $(shell cat "{SYN.SYN_OUTPUT_DIRECTORY}/vhdl_files.txt")

# TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = {SYN.TOP_LEVEL_MODULE}

# MODULE is the basename of the Python test file
MODULE = {py_basename}

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
      """
        f = open(makefile_path, "w")
        f.write(makefile_text)
        f.close()

        # Write template testbench (TODO make verilator compatible?)
        # What clock is being used?
        # Clocks
        clock_name_to_mhz, out_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
            parser_state, None, True
        )
        # Which ones are not from the user internal
        clock_port_is_clk = True
        for clk_mhz in parser_state.clk_mhz.values():
            clk_name = "clk_" + VHDL.CLK_MHZ_GROUP_TEXT(clk_mhz, None)
            # Remove user clocks from dict
            clock_name_to_mhz.pop(clk_name, None)
        # Only support one clock for now (otherwise do multiple parallel clock gens)
        if len(clock_name_to_mhz) != 1:
            raise NotImplementedError(
                "Only single clock designs supported for cocotb template testbench gen!"
            )
        clock_name, mhz = list(clock_name_to_mhz.items())[0]
        ns = 1.0
        if mhz:
            ns = 1000.0 / mhz

        # Testbench just does 10 clocks and done
        py_text = f'''
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def my_first_test(dut):
    """Try accessing the design."""
    for cycle in range(10):
        dut.{clock_name}.value = 0
        await Timer({ns}, units="ns")
        dut.{clock_name}.value = 1
        await Timer({ns}, units="ns")
'''
        py_filepath = COCOTB_OUT_DIR + "/" + py_basename + ".py"
        f = open(py_filepath, "w")
        f.write(py_text)
        f.close()

    # Run make in directory with makefile to do simulation
    print("Running make in:", makefile_dir, "...", flush=True)
    bash_cmd = f"make"
    log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=makefile_dir)
    print(log_text, flush=True)
    sys.exit(0)
