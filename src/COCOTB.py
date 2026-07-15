import os
import sys

import C_TO_LOGIC
import pypeline_sim
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

        # Testbench just does N clocks and done -- or, for --run all, an unbounded
        # loop relying on sim_finish()'s std.env.finish to end the GHDL simulation
        # itself (confirmed empirically: std.env.finish terminates the whole GHDL
        # process immediately, regardless of what the cocotb-side loop has left to
        # do, so a large/unbounded Python-side loop bound is harmless -- it's simply
        # never fully iterated). A safety cap still applies so a design that never
        # calls sim_finish() fails loudly instead of hanging the GHDL process
        # indefinitely (VHDL sim is much slower per-cycle than native sim, so this
        # cap is intentionally smaller than pypeline_sim.py's native --run all cap).
        run_all = args.run == pypeline_sim.RUN_ALL
        run_all_safety_cap = 1_000_000
        if run_all:
            remaining_cycles_expr = f"range({run_all_safety_cap})"
        else:
            remaining_cycles_expr = f"range({args.run - 1})"
        # Only reached if the loop above completed all its iterations without
        # sim_finish()'s std.env.finish having already terminated the GHDL process --
        # for --run all that means sim_finish() was never called, a design bug.
        run_all_cap_check = (
            f"""
    raise RuntimeError(
        "--run all exceeded {run_all_safety_cap} cycles without sim_finish() ever "
        "being called -- likely a design bug, not a slow-but-working simulation."
    )"""
            if run_all
            else ""
        )
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
    #
    # Drive the clock to '0' before its first rising edge (with no wait/print of
    # its own) so VHDL's rising_edge() -- which requires clk'last_value = '0',
    # not just any transition into '1' -- actually fires on this first pulse.
    # Without this, clk's initial value is 'U' (undefined), so the U->1
    # transition below does NOT satisfy rising_edge(), silently skipping every
    # clocked process for what this script labels "Clock: 0": registers only
    # take their first real clock edge one full loop iteration later, at what
    # gets printed as "Clock: 1" -- a one-cycle-late log label vs. native sim.
    dut.{clock_name}.value = 0
    # Settle the '0' with a real (if tiny) time advance -- a delta-only
    # NextTimeStep() was not enough to get GHDL/VPI to commit the '0' before
    # the '1' assignment below; an actual Timer wait is.
    await Timer(0.001, units="ns")
    cycle = 0
    print("Clock: ", cycle, flush=True)
    DUMP_PIPELINEC_DEBUG(dut)
    dut.{clock_name}.value = 1
    await Timer({(ns/2):.3f}, units="ns")
    print("^End Clock: ", cycle, flush=True)
    for i in {remaining_cycles_expr}:
        dut.{clock_name}.value = 0
        await Timer({(ns/2):.3f}, units="ns")
        print("")
        print("Clock: ", i+1, flush=True)
        DUMP_PIPELINEC_DEBUG(dut)
        dut.{clock_name}.value = 1
        await Timer({(ns/2):.3f}, units="ns")
{run_all_cap_check}
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
    CHECK_COCOTB_LOG_PASS_FAIL(log_text, args)
    sys.exit(0)


def CHECK_COCOTB_LOG_PASS_FAIL(log_text, args):
    """cocotb's own regression-manager PASS/FAIL summary is not reflected in `make`'s
    process returncode for every failure mode: a real VHDL assertion failure (from
    sim_assert) makes GHDL itself error out, which does propagate as a non-zero `make`
    exit -- but a Python-level exception raised inside the generated cocotb test body
    (e.g. --run all's safety-cap RuntimeError) does not, since GHDL considers the
    simulation to have completed normally right up until that Python exception fires.
    So `make` returning 0 is not sufficient evidence of success; check cocotb's own
    "TESTS=N PASS=N FAIL=N" summary line explicitly.

    A FAIL is expected and OK exactly when it's `--run all` and the failure is GHDL's
    own "Simulator shutdown prematurely" scheduler message (cocotb's generic framing
    for "the simulator ended before I expected it to") -- that's what a clean,
    intentional sim_finish()/std.env.finish() stop looks like, confirmed empirically:
    GHDL prints "simulation finished @<t>ns" and terminates immediately, which cocotb
    (having no way to know the stop was intentional) reports as this same premature-
    shutdown FAIL text. Any other FAIL (including a Python traceback from a genuine bug
    like the safety cap firing, or any other in-test exception) is a real failure.
    """
    import re

    m = re.search(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)", log_text)
    if m is None:
        raise Exception(
            "Could not find cocotb's 'TESTS=N PASS=N FAIL=N' summary line in the "
            "simulation log -- cannot confirm the cocotb test actually passed."
        )
    num_tests, num_pass, num_fail = (int(g) for g in m.groups())
    if num_fail == 0 and num_pass == num_tests:
        return  # genuine clean pass
    run_all = getattr(args, "run", None) == pypeline_sim.RUN_ALL
    if (
        run_all
        and "Simulator shutdown prematurely" in log_text
        and "my_first_test failed" not in log_text
    ):
        # Expected: sim_finish()/std.env.finish() stopped the simulation cleanly.
        return
    raise Exception(
        f"cocotb reported real test failures (TESTS={num_tests} PASS={num_pass} "
        f"FAIL={num_fail}) -- see the simulation log above."
    )
