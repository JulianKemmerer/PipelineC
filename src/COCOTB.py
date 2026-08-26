import os
import subprocess
import sys

import C_TO_LOGIC
import pypeline_sim
import SIM
import SYN
import VHDL
from utilities import GET_TOOL_PATH


def GET_MAKEFILE_TEXT(sim_make_args, vhdl_files_txt_path, toplevel, py_basename):
    """Generate the cocotb Makefile text.

    VHDL_SOURCES is set from a GHDL "@file" response file (plain
    whitespace-split, so vhdl_files.txt -- already one space-separated line
    of absolute paths -- works unmodified) rather than inlining every path
    via $(shell cat ...). Needed because cocotb's Makefile.ghdl "analyse"
    target is one backslash-continued logical recipe line, which make hands
    to the shell as a single argv string; Linux caps any one argv string at
    MAX_ARG_STRLEN (PAGE_SIZE * 32 = 131072 bytes) independent of the much
    larger overall ARG_MAX, and a large design's full VHDL file list can
    exceed that on its own ("Argument list too long").

    The "@..." token names no real file, so make would otherwise refuse it
    as an unbuildable prerequisite ("No rule to make target") -- declaring it
    .PHONY (a phony target is never "missing") fixes that; analyse is already
    .PHONY itself, so nothing is lost. Real dependency tracking moves to
    CUSTOM_COMPILE_DEPS, which cocotb's Makefile.inc also wires into analyse.

    Only correct for GHDL (the only supported cocotb SIM here, enforced by
    DO_SIM's NotImplementedError for anything else) -- "@file" is a GHDL
    response-file feature, not a generic make/shell one.
    """
    return f"""
{sim_make_args}
TOPLEVEL_LANG ?= vhdl

#VERILOG_SOURCES += $(PWD)/my_design.sv
# use VHDL_SOURCES for VHDL files
PIPELINEC_VHDL_FILES_TXT = {vhdl_files_txt_path}
VHDL_SOURCES += @$(PIPELINEC_VHDL_FILES_TXT)
.PHONY: @$(PIPELINEC_VHDL_FILES_TXT)
CUSTOM_COMPILE_DEPS += $(PIPELINEC_VHDL_FILES_TXT)

# TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = {toplevel}

# MODULE is the basename of the Python test file
MODULE = {py_basename}

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
      """


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
        # --run all relies on sim_finish()'s std.env.finish to terminate GHDL
        # out from under cocotb's still-running coroutine -- cocotb has no way
        # to distinguish that from a real crash, so it always scores the test
        # a SimFailure (see CHECK_COCOTB_RESULTS's docstring for the verified
        # log evidence). expect_error=SimFailure tells cocotb's own regression
        # manager this specific outcome is the expected, successful one
        # (cocotb/regression.py's _score_test: SimFailure matching
        # expect_error -> "errored as expected" -> PASS; any OTHER exception,
        # e.g. the --run-all safety-cap RuntimeError below, still -> FAIL).
        # Finite --run N never triggers this path (the loop simply completes),
        # so it keeps the plain, unmodified @cocotb.test().
        test_decorator_args = "expect_error=SimFailure" if run_all else ""
        py_text = f'''
import cocotb
from cocotb.result import SimFailure
from cocotb.triggers import Timer

from pipelinec_cocotb import * # Generated

@cocotb.test({test_decorator_args})
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
        makefile_text = GET_MAKEFILE_TEXT(
            sim_make_args,
            SYN.SYN_OUTPUT_DIRECTORY + "/vhdl_files.txt",
            SYN.TOP_LEVEL_MODULE,
            py_basename,
        )
        f = open(makefile_path, "w")
        f.write(makefile_text)
        f.close()

    # Run make in directory with makefile to do simulation. Use subprocess
    # directly (not C_TO_LOGIC.GET_SHELL_CMD_OUTPUT, which raises a raw
    # Exception on any nonzero exit and only returns stdout) -- a firing
    # sim_assert makes GHDL itself exit nonzero, and DO_SIM needs to turn
    # that into the same kind of verdict as every other failure mode, not an
    # unhandled traceback.
    print("Running make in:", makefile_dir, "...", flush=True)
    proc = subprocess.run(
        "make", shell=True, cwd=makefile_dir, capture_output=True, text=True
    )
    # stdout only, not stdout+stderr merged: pypeline_sim_debug.py's cycle
    # diff parses this exact stream for interleaved "Clock: N" /
    # "[SIM DEBUG PRINT: ...]" lines, in order -- merging stderr in would
    # reorder them and break every native_vs_vhdl_sim test.
    print(proc.stdout, flush=True)
    if proc.returncode != 0:
        print(proc.stderr, flush=True)
        raise Exception(
            f"make failed (exit {proc.returncode}) in {makefile_dir} -- see output above."
        )
    CHECK_COCOTB_RESULTS(makefile_dir, proc.stdout)
    # Print an unambiguous verdict last -- cocotb's own scheduler still logs
    # its generic "Simulator shutdown prematurely" ERROR line for every
    # sim_finish()-terminated run even when CHECK_COCOTB_RESULTS scored it a
    # clean PASS (that text comes from cocotb's low-level _sim_event handler,
    # not its scoring path), which otherwise reads as a failure to a human
    # skimming the log.
    print(
        "================== cocotb Simulation Result ==============================",
        flush=True,
    )
    print("PASS: cocotb reported no test failures.", flush=True)
    sys.exit(0)


def CHECK_COCOTB_RESULTS(makefile_dir, log_text):
    """cocotb's console "TESTS=N PASS=N FAIL=N" summary used to be misleading
    on its face for every --run all design: sim_finish() stops the
    simulation via VHDL's std.env.finish, which terminates GHDL out from
    under cocotb's still-awaiting coroutine.
    cocotb has no way to distinguish that from a real crash, so its
    regression manager used to always score it a SimFailure ("Simulator
    shutdown prematurely") -- confirmed empirically against a design that
    unambiguously passed (self_check_autofsm_test, native vs. VHDL cycle
    diff matched): its own log ended "TESTS=1 PASS=0 FAIL=1".

    The generated testbench (see the `expect_error=SimFailure` decorator
    argument above) now tells cocotb's regression manager that exact
    SimFailure outcome is the EXPECTED, successful one for --run all, so a
    clean sim_finish() stop is scored PASS and any other exception (a real
    crash, or the --run-all safety-cap RuntimeError) is still scored FAIL.
    That makes cocotb's own COCOTB_RESULTS_FILE (results.xml, cocotb's
    structured JUnit-style report -- see cocotb's Makefile.inc) the
    authoritative verdict, with no text-based carve-out needed here.

    results.xml's location is COCOTB_RESULTS_FILE relative to `make`'s cwd
    (makefile_dir here), which can differ from COCOTB_OUT_DIR when a user
    passes --makefile.
    """
    import xml.etree.ElementTree as ET

    results_path = os.path.join(makefile_dir, "results.xml")
    if not os.path.isfile(results_path):
        # Only reachable via a relocating --makefile; results.xml is
        # otherwise guaranteed to exist by cocotb's own check_for_results_file.
        print(
            f"WARNING: {results_path} not found -- falling back to a log-text "
            f"check instead of cocotb's structured results.",
            flush=True,
        )
        if "TESTS=" not in log_text or " FAIL=0 " not in log_text:
            raise Exception(
                "cocotb's 'TESTS=N PASS=N FAIL=N' summary line is missing or "
                "reports a failure -- see the simulation log above."
            )
        return

    tree = ET.parse(results_path)
    failures = []
    for testcase in tree.getroot().iter("testcase"):
        if testcase.find("failure") is not None:
            name = testcase.get("name", "<unnamed>")
            msg = testcase.find("failure").get("message", "no message")
            failures.append(f"{name}: {msg}")
    if failures:
        raise Exception(
            "cocotb reported real test failure(s): "
            + "; ".join(failures)
            + " -- see the simulation log above."
        )
