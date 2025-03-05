import os
import sys

import C_TO_LOGIC
import SIM
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

        # Write helper file to go with template testbench
        py_text = ""
        sim_gen_info = SIM.GET_SIM_GEN_INFO(parser_state, multimain_timing_params)
        # Only support one clock for now (otherwise do multiple parallel clock gens)
        if len(sim_gen_info.clock_name_to_mhz) != 1:
            raise NotImplementedError(
                "Only single clock designs supported for cocotb template testbench gen!"
            )
        clock_name, mhz = list(sim_gen_info.clock_name_to_mhz.items())[0]
        ns = 1.0
        if mhz:
            ns = 1000.0 / mhz
        # Debug ports
        # Inputs
        for (
            debug_name,
            debug_vhdl_name,
        ) in sim_gen_info.debug_input_to_vhdl_name.items():
            py_text += f"""
def {debug_name}(dut, val_input=None):
  if val_input:
    dut.{debug_vhdl_name} = val_input
  else:
    return dut.{debug_vhdl_name}
          """
        # Outputs
        for (
            debug_name,
            debug_vhdl_name,
        ) in sim_gen_info.debug_output_to_vhdl_name.items():
            py_text += f"""
def {debug_name}(dut):
  return dut.{debug_vhdl_name}
          """
        # Dump all debug inputs and outputs
        py_text += """
def DUMP_PIPELINEC_DEBUG(dut):\n"""
        if (
            len(sim_gen_info.debug_input_to_vhdl_name)
            + len(sim_gen_info.debug_output_to_vhdl_name)
            > 0
        ):
            for (
                debug_name,
                debug_vhdl_name,
            ) in sim_gen_info.debug_input_to_vhdl_name.items():
                py_text += f'  print("{debug_name} =", {debug_name}(dut), flush=True)\n'
            for (
                debug_name,
                debug_vhdl_name,
            ) in sim_gen_info.debug_output_to_vhdl_name.items():
                py_text += f'  print("{debug_name} =", {debug_name}(dut), flush=True)\n'
        else:
            py_text += " pass\n"
        py_text += "\n"
        # Main func latencies
        for main_func, latency in sim_gen_info.main_func_to_latency.items():
            py_text += f"{main_func}_LATENCY = {latency}\n"

        py_filepath = COCOTB_OUT_DIR + "/pipelinec_cocotb.py"
        f = open(py_filepath, "w")
        f.write(py_text)
        f.close()

        # Testbench just does 10 clocks and done
        py_basename = "test_" + SYN.TOP_LEVEL_MODULE
        py_text = f'''
import cocotb
from cocotb.triggers import Timer

from pipelinec_cocotb import * # Generated

@cocotb.test()
async def my_first_test(dut):
    """Try accessing the design."""
    # Do first cycle print a little different
    # to work around 'metavalue detected' warnings from ieee libs
    cycle = 0
    print("Clock: ", cycle, flush=True)
    DUMP_PIPELINEC_DEBUG(dut)
    dut.{clock_name}.value = 1
    await Timer({(ns/2):.3f}, units="ns")
    print("^End Clock: ", cycle, flush=True)
    for i in range({args.run-1}):
        dut.{clock_name}.value = 0
        await Timer({(ns/2):.3f}, units="ns")
        print("")
        print("Clock: ", i+1, flush=True)
        DUMP_PIPELINEC_DEBUG(dut)
        dut.{clock_name}.value = 1
        await Timer({(ns/2):.3f}, units="ns")
'''
        py_filepath = COCOTB_OUT_DIR + "/" + py_basename + ".py"
        f = open(py_filepath, "w")
        f.write(py_text)
        f.close()

        # What sim tool?
        sim_make_args = ""
        if args.ghdl:
            sim_make_args += "SIM ?= ghdl\n"
            sim_make_args += "EXTRA_ARGS += --std=08\n"
            sim_make_args += f"SIM_ARGS += --vcd={SYN.TOP_LEVEL_MODULE}.vcd --ieee-asserts=disable-at-0\n"
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

    # Run make in directory with makefile to do simulation
    print("Running make in:", makefile_dir, "...", flush=True)
    bash_cmd = "make"
    log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=makefile_dir)
    print(log_text, flush=True)
    sys.exit(0)
