#!/usr/bin/env python3
"""The synthesis API: what the compiler asks a synthesis tool to do, and what
it expects back.

See docs/SYN_DESIGN.md. This module owns:

- tool selection (`PART_SET_TOOL` -> the `SYN_TOOL` backend module) and the
  backend contract (`SYN_AND_REPORT_TIMING*`, the file-list/TCL and clock
  constraint helpers every backend calls);
- the kinds of runs: per-function delay measurement (`MEASURE_DELAYS`,
  `ADD_PATH_DELAY_TO_LOOKUP`), one instance (`RUN_INST_SYN_AND_UPDATE_CACHE`),
  the full multi-MAIN design, and the final bitstream;
- the reports it expects: parsed timing paths (`SET_MEASURED_DELAY_FROM_REPORT`,
  `GET_MAIN_INSTS_FROM_PATH_REPORT`), measured area, and pre-synthesis area /
  register estimates;
- the on-disk path-delay and area caches, output directories, final files.

Using these runs to reach a timing goal is SWEEP.py; how pipelines are
represented is AUTO_PIPELINE.py; multi-cycle path constraints are
AUTO_MULTI_CYCLE.py.
"""

import datetime
import inspect
import json
import math
import os
import re
import sys
from multiprocessing.pool import ThreadPool
from timeit import default_timer as timer

import CC_TOOLS
import C_TO_LOGIC
import DEVICE_MODELS
import DIAMOND
import EFINITY
import GOWIN
import OPEN_TOOLS
import PYRTL
import QUARTUS
import RAW_VHDL
import SW_LIB
import VHDL
import VIVADO
import pypeline
from utilities import REPO_ABS_DIR

START_TIME = timer()

OUTPUT_DIR_NAME = "pipelinec_output"
SYN_OUTPUT_DIRECTORY = None  # Auto created with pid and filename or from user
TOP_LEVEL_MODULE = None  # Holds the name of the top level module
SYN_TOOL = None  # Attempts to figure out from part number
# Tri-state override for the mux path-delay cache key (see
# GET_CACHED_LOGIC_FILE_KEY): None = automatic per SYN_TOOL, True/False force
# width-keyed or collapsed for every tool. Set by --mux_delay_by_width /
# --no_mux_delay_by_width.
MUX_DELAY_KEY_BY_WIDTH = None
# How many synthesis runs may be in flight at once. None = read
# config/num_processes.cfg; set by pipelinec's -j/--jobs. Each in-flight run is
# a whole vendor tool process, so this is really a memory knob: Efinity's
# efx_pnr peaks near 3.7GB building a Titanium routing graph, and four of those
# at once will exhaust a 16GB machine (the OOM killer then takes whatever has
# the worst oom_score, not necessarily the build).
NUM_PROCESSES = None
_NUM_PROCESSES_CFG = None
CONVERT_FINAL_TOP_VERILOG = False  # Flag for final top level converison to verilog
WRITE_AXIS_XO_FILE = False
PIN_CONSTRAINTS_FILE = None  # Pin constraints file to use

# Welcome to the land of magic numbers
#   "But I think its much worse than you feared" Modest Mouse - I'm Still Here

DELAY_UNIT_MULT = 10.0  # Timing is reported in nanoseconds. Multiplier to convert that time into integer units (nanosecs, tenths, hundreds of nanosecs)
INF_MHZ = 1000  # Impossible timing goal
# Pre-pipelining path delay collection mode:
#  "leaf" = only synthesize raw HDL leaf funcs and topmost untagged stateful
#           modules (atomic spans); hierarchical funcs on the pipelining path
#           get delay estimated from their zero clock pipeline map (see
#           FUNC_PATH_DELAY_IS_ESTIMABLE and docs/SYN_DESIGN.md).
#  "full" = old behavior, synthesize every level of hierarchy individually
#           including MAINs (--full_hier_syn cmd line flag).
#  "prim" = opposite of "full": only true primitive leaves (no submodules)
#           are ever synthesized. Every hierarchical module, including
#           MAINs and stateful atomic spans, is estimated from submodule
#           delays (--no_hier_syn cmd line flag). Gives up the automatic
#           estimate-was-inaccurate fallback to real synthesis.
HIER_SYN_MODE = "leaf"
# Experimental planner geometry: use a timing backend's measured
# combinational component as the relative leaf weight, then normalize it at
# the measured frontier before placement. This stays internal and defaults
# off until controlled A/B evidence promotes it; the synthesis/STA budget
# continues to use Logic.delay regardless.
USE_COMBINATIONAL_PLANNER_WEIGHTS = os.environ.get(
    "PIPELINEC_INTERNAL_COMBINATIONAL_PLANNER_WEIGHTS", "0"
).lower() in ("1", "true", "yes", "on")
COMBINATIONAL_PLANNER_MODEL_VERSION = 1


def GET_PLANNER_DELAY_CACHE_SUFFIX():
    if not USE_COMBINATIONAL_PLANNER_WEIGHTS:
        return ""
    return f"__comb_planner_v{COMBINATIONAL_PLANNER_MODEL_VERSION}"


def GET_PLANNER_DELAY(logic):
    """Relative planner weight in the same integer units as ``logic.delay``.

    The experimental value is the measured combinational component. Callers
    must normalize a frontier's relative weights back to its existing
    measured total before placement; this helper intentionally does not alter
    the global slice-count/timing budget.
    """

    if (
        USE_COMBINATIONAL_PLANNER_WEIGHTS
        and getattr(logic, "planner_delay", None) is not None
    ):
        return logic.planner_delay
    return logic.delay


def GET_NUM_PROCESSES():
    """Parallel synthesis runs allowed. -j/--jobs wins, else
    config/num_processes.cfg, else 4."""
    global _NUM_PROCESSES_CFG
    if NUM_PROCESSES is not None:
        return max(1, int(NUM_PROCESSES))
    if _NUM_PROCESSES_CFG is None:
        try:
            with open(
                C_TO_LOGIC.EXE_ABS_DIR() + "/../config/num_processes.cfg", "r"
            ) as f:
                _NUM_PROCESSES_CFG = max(1, int(f.readline()))
        except (OSError, ValueError):
            _NUM_PROCESSES_CFG = 4
    return _NUM_PROCESSES_CFG


# Every selectable synthesis backend, by the name used on the command line
# (--syn_tool) and in source (SYN_TOOL("...")). These names are also what a
# build log's "Running: .../<name>_....log" lines say, and what the test
# suite's per-tool categories are named after (common.SYN_TOOLS).
TOOL_MODULES = {
    "vivado": VIVADO,
    "quartus": QUARTUS,
    "diamond": DIAMOND,
    "gowin": GOWIN,
    "efinity": EFINITY,
    "open_tools": OPEN_TOOLS,
    "cc_tools": CC_TOOLS,
    "pyrtl": PYRTL,
    "device_models": DEVICE_MODELS,
}
TOOL_NAMES = tuple(TOOL_MODULES.keys())


def TOOL_NAME(tool):
    """The --syn_tool spelling of a backend module, or None."""
    for name, module in TOOL_MODULES.items():
        if module is tool:
            return name
    return None


def GET_TOOL_MODULE(tool_name):
    """Backend module for a --syn_tool/SYN_TOOL() name. Raises on a typo."""
    try:
        return TOOL_MODULES[tool_name]
    except KeyError:
        raise Exception(
            f"Unknown synthesis tool '{tool_name}'! Expected one of: "
            + ", ".join(TOOL_NAMES)
        )


def PART_TO_TOOL(part_str):
    """The backend a part string selects, or None if nothing matches.

    Pure: no install checks, no writes to the SYN_TOOL global. A part of None
    means "no part given" and selects PYRTL, the part-less estimator.
    """
    if part_str is None:
        return PYRTL
    if part_str.lower().startswith("xc"):
        return VIVADO
    elif (
        part_str.lower().startswith("ep")
        or part_str.lower().startswith("10c")
        or part_str.lower().startswith("5c")
    ):
        return QUARTUS
    elif part_str.lower().startswith("lfe5u") or part_str.lower().startswith("ice"):
        # Diamond fails to create proj for UMG5G part?
        if "um5g" in part_str.lower():
            return OPEN_TOOLS
        # Default to open tools for non ice40 (nextpnr not support ooc mode yet)
        elif "ice40" not in part_str.lower():
            return OPEN_TOOLS
        else:
            # ice40 is the one part family two backends can serve: Diamond when
            # it is installed, open tools otherwise. PART_TO_TOOL reports the
            # install-dependent preference; TOOL_MATCHES_PART treats both as
            # consistent so an explicit --syn_tool never depends on which
            # machine it runs on.
            if os.path.exists(DIAMOND.DIAMOND_PATH):
                return DIAMOND
            return OPEN_TOOLS
    elif part_str.upper().startswith("T8") or part_str.upper().startswith("TI"):
        return EFINITY
    elif part_str.upper().startswith("GW"):
        return GOWIN
    elif part_str.upper().startswith("CCGM"):
        return CC_TOOLS
    elif part_str.lower().startswith("sky130"):
        return DEVICE_MODELS
    return None


def _PART_IS_ICE40(part_str):
    return part_str is not None and "ice40" in part_str.lower()


def TOOL_MATCHES_PART(tool, part_str):
    """Is an explicitly named tool consistent with an explicitly given part?

    Exact match, except families with more than one supported backend:
    ice40 may use DIAMOND or OPEN_TOOLS, and Xilinx 7-series may use VIVADO
    or the open Yosys/nextpnr-xilinx flow in OPEN_TOOLS. PART_TO_TOOL keeps
    the historical/default choice; an explicit --syn_tool may select the
    alternate backend without making the part/tool pair contradictory.
    """
    if tool is PART_TO_TOOL(part_str):
        return True
    if _PART_IS_ICE40(part_str) and tool in (DIAMOND, OPEN_TOOLS):
        return True
    if OPEN_TOOLS.IS_XC7_PART(part_str) and tool in (VIVADO, OPEN_TOOLS):
        return True
    return False


def CHECK_TOOL_INSTALLED(tool, part_str=None, allow_fail=False):
    """Report/verify that a selected backend is actually installed.

    Returns True when usable. With allow_fail the caller gets False instead of
    an exception, which is how pipelinec falls back to --comb --no_synth.
    """
    if tool is None:
        return False

    def _found(label, path):
        print(label + ":", path, flush=True)
        return True

    def _missing(msg):
        if not allow_fail:
            raise Exception(msg)
        return False

    if tool is VIVADO:
        if os.path.exists(VIVADO.VIVADO_PATH):
            return _found("Vivado", VIVADO.VIVADO_PATH)
        return _missing("Vivado install not found!")
    elif tool is QUARTUS:
        if os.path.exists(QUARTUS.QUARTUS_PATH):
            return _found("Quartus", QUARTUS.QUARTUS_PATH)
        return _missing("Quartus install not found!")
    elif tool is DIAMOND:
        if os.path.exists(DIAMOND.DIAMOND_PATH):
            return _found("Diamond", DIAMOND.DIAMOND_PATH)
        return _missing("Diamond install not found!")
    elif tool is EFINITY:
        if os.path.exists(EFINITY.EFINITY_PATH):
            return _found("Efinity", EFINITY.EFINITY_PATH)
        return _missing("Efinity install not found!")
    elif tool is GOWIN:
        if os.path.exists(GOWIN.GOWIN_PATH):
            return _found("Gowin", GOWIN.GOWIN_PATH)
        return _missing("Gowin install not found!")
    elif tool is CC_TOOLS:
        # TODO dont base on cc-toolchain directory?
        if os.path.exists(CC_TOOLS.CC_TOOLS_PATH):
            return _found("CologneChip Tools", CC_TOOLS.CC_TOOLS_PATH)
        return _missing("CologneChip toolchain install not found!")
    elif tool is OPEN_TOOLS:
        if OPEN_TOOLS.IS_XC7_PART(part_str):
            missing = []
            if OPEN_TOOLS.YOSYS_BIN_PATH is None:
                missing.append("yosys")
            if OPEN_TOOLS.GHDL_PREFIX is None:
                missing.append("ghdl")
            nextpnr = OPEN_TOOLS.GET_XC7_TOOL_PATH(OPEN_TOOLS.XC7_NEXTPNR_EXE)
            if nextpnr is None:
                missing.append("nextpnr-xilinx")
            chipdb = OPEN_TOOLS.GET_XC7_CHIPDB_PATH(part_str)
            if chipdb is None:
                missing.append(
                    "nextpnr-xilinx chipdb " + OPEN_TOOLS.XC7_CHIPDB_NAME(part_str)
                )
            if missing:
                return _missing(
                    "OpenXC7 install incomplete for "
                    + part_str
                    + ": missing "
                    + ", ".join(missing)
                    + ". Put the OpenXC7 tools on PATH and set OPENXC7_CHIPDB, "
                    "or use OPENXC7 for a self-contained tool root."
                )
            return _found("Open tools (OpenXC7)", nextpnr)
        if OPEN_TOOLS.YOSYS_BIN_PATH is not None:
            return _found("Open tools (yosys)", OPEN_TOOLS.YOSYS_BIN_PATH)
        return _missing("Open tools (yosys/nextpnr/ghdl) install not found!")
    elif tool is PYRTL:
        if PYRTL.IS_INSTALLED():
            return True
        return _missing(
            "PyRTL not installed -- need the pyrtl and pyparsing python modules!"
        )
    elif tool is DEVICE_MODELS:
        if DEVICE_MODELS.IS_INSTALLED():
            return _found(
                "DEVICE_MODELS (sky130 liberty STA)", DEVICE_MODELS.SELECTED_LIBRARY
            )
        return _missing(
            "sky130 liberty STA not available -- need yosys+ghdl "
            "(OPEN_TOOLS) and a volare sky130 PDK install "
            "(see DEVICE_MODELS.LIBERTY_RAW_LIB_PATH / "
            "PIPELINEC_SKY130_LIB_PATH)!"
        )
    return _missing(f"Do not know how to check install of {tool.__name__}!")


def _RECONCILE(axis, cli_value, cli_flag, src_value, src_call):
    """One value from two sources that must not disagree."""
    if cli_value is not None and src_value is not None and cli_value != src_value:
        raise Exception(
            f"Conflicting {axis}: {cli_flag} says '{cli_value}' but the source's "
            f"{src_call} says '{src_value}'. Set only one, or set both the same."
        )
    return cli_value if cli_value is not None else src_value


def RESOLVE_PART_AND_TOOL(
    cli_part=None, cli_tool=None, src_part=None, src_tool=None, allow_fail=False
):
    """Settle the part and the synthesis tool from all four possible sources.

    Part comes from --part or PART(...), tool from --syn_tool or SYN_TOOL(...).
    Same-axis disagreements are errors, and so is naming a tool that the part
    does not select -- the two are one decision spelled two ways, never an
    override. Naming a tool with no part falls back to that tool's
    DEFAULT_PART.

    Returns (part_str, tool_module); tool_module is None when nothing is
    installed and allow_fail is set. Sets the SYN_TOOL global.
    """
    global SYN_TOOL
    part = _RECONCILE("FPGA part", cli_part, "--part", src_part, 'PART("...")')
    tool_name = _RECONCILE(
        "synthesis tool", cli_tool, "--syn_tool", src_tool, 'SYN_TOOL("...")'
    )

    if tool_name is not None:
        tool = GET_TOOL_MODULE(tool_name)
        if part is None:
            # Tool named on its own: it supplies the part it is normally used with.
            part = tool.DEFAULT_PART
            if part is not None:
                print(
                    f"Using {tool_name} default part:", part, flush=True
                )
        elif not TOOL_MATCHES_PART(tool, part):
            implied = PART_TO_TOOL(part)
            implied_name = TOOL_NAME(implied) if implied else "no known tool"
            raise Exception(
                f"Part '{part}' selects {implied_name}, but the synthesis tool "
                f"was set to '{tool_name}'. A part and a tool cannot contradict: "
                f"either drop the tool and let the part choose it, or pass a part "
                f"{tool_name} supports (ex. --part {tool.DEFAULT_PART})."
            )
    else:
        tool = PART_TO_TOOL(part)
        if tool is None:
            if not allow_fail:
                print("No known synthesis tool for FPGA part:", part, flush=True)
                sys.exit(-1)
            return part, None

    if part is None and tool is not PYRTL:
        # Only PYRTL models something that isn't a part.
        if not allow_fail:
            raise Exception(
                f"{TOOL_NAME(tool)} needs an FPGA part -- set --part or PART(...)."
            )
        return part, None

    if not CHECK_TOOL_INSTALLED(tool, part, allow_fail=allow_fail):
        return part, None

    SYN_TOOL = tool
    print("Using", SYN_TOOL.__name__, "synthesizing for part:", part)
    return part, tool


def PART_SET_TOOL(part_str, allow_fail=False):
    """Set the SYN_TOOL global from a part string, if not already set.

    Thin back-compat wrapper over PART_TO_TOOL + CHECK_TOOL_INSTALLED, kept
    for the many call sites that only have a part in hand. A SYN_TOOL already
    chosen (by --syn_tool/SYN_TOOL(), via RESOLVE_PART_AND_TOOL) always wins.
    """
    global SYN_TOOL
    if SYN_TOOL is not None:
        return
    if part_str is None:
        if PYRTL.IS_INSTALLED():
            SYN_TOOL = PYRTL
            print("Defaulting to pyrtl based timing estimates...")
        else:
            if allow_fail:
                return
            print(
                "Need to set FPGA part somewhere in the code to continue with synthesis tool support!"
            )
            print('Ex. #pragma PART "LFE5U-85F-6BG381C"')
            sys.exit(0)
    else:
        tool = PART_TO_TOOL(part_str)
        if tool is None:
            if not allow_fail:
                print("No known synthesis tool for FPGA part:", part_str, flush=True)
                sys.exit(-1)
            return
        if not CHECK_TOOL_INSTALLED(tool, part_str, allow_fail=allow_fail):
            return
        SYN_TOOL = tool

    if SYN_TOOL is not None:
        print("Using", SYN_TOOL.__name__, "synthesizing for part:", part_str)


def TOOL_DOES_PNR():
    # Does tool do full PNR or just syn?
    if SYN_TOOL is VIVADO:
        return VIVADO.DO_PNR == "all"
    elif SYN_TOOL is GOWIN:
        return GOWIN.DO_PNR == "all"
    # Uses PNR
    elif (
        (SYN_TOOL is QUARTUS)
        or (SYN_TOOL is OPEN_TOOLS)
        or (SYN_TOOL is EFINITY)
        or (SYN_TOOL is CC_TOOLS)
    ):
        return True
    # Uses synthesis estimates
    elif (SYN_TOOL is DIAMOND) or (SYN_TOOL is PYRTL) or (SYN_TOOL is DEVICE_MODELS):
        return False
    else:
        raise Exception("Need to know if tool flow does PnR!")


def GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
    parser_state, inst_name=None, allow_no_syn_tool=False
):
    ext = None
    if SYN_TOOL is VIVADO:
        ext = ".xdc"
    elif SYN_TOOL is QUARTUS:
        ext = ".sdc"
    elif SYN_TOOL is DIAMOND and DIAMOND.DIAMOND_TOOL == "lse":
        ext = ".ldc"
    elif SYN_TOOL is DIAMOND and DIAMOND.DIAMOND_TOOL == "synplify":
        ext = ".sdc"
    elif SYN_TOOL is OPEN_TOOLS:
        ext = ".py"
    elif SYN_TOOL is EFINITY:
        ext = ".sdc"
    elif SYN_TOOL is GOWIN:
        ext = ".sdc"
    elif SYN_TOOL is PYRTL:
        ext = ".sdc"
    elif SYN_TOOL is DEVICE_MODELS:
        ext = ".sdc"
    elif SYN_TOOL is CC_TOOLS:
        ext = ".ccf"  # Only for temp clock pins, no timing contraints?
    else:
        if not allow_no_syn_tool:
            # Sufjan Stevens - Video Game
            raise Exception(
                f"Add constraints file ext for syn tool {SYN_TOOL.__name__}"
            )
        ext = ""

    clock_name_to_mhz = {}
    if inst_name:
        # Default instances get max fmax
        clock_name_to_mhz["clk"] = INF_MHZ
        """
    # Unless happens to be main with fixed freq
    if inst_name in parser_state.main_mhz:
      clock_mhz = GET_TARGET_MHZ(inst_name, parser_state, allow_no_syn_tool)
      clock_name_to_mhz["clk"] = clock_mhz
    """
        out_filename = "clock" + ext
        Logic = parser_state.LogicInstLookupTable[inst_name]
        output_dir = GET_OUTPUT_DIRECTORY(Logic)
        out_filepath = output_dir + "/" + out_filename
    else:
        out_filename = "clocks" + ext
        out_filepath = SYN_OUTPUT_DIRECTORY + "/" + out_filename
        for main_func in parser_state.main_mhz:
            clock_mhz = GET_TARGET_MHZ(main_func, parser_state, allow_no_syn_tool)
            clk_ext_str = VHDL.CLK_EXT_STR(main_func, parser_state)
            clk_name = "clk_" + clk_ext_str
            clock_name_to_mhz[clk_name] = clock_mhz

    return clock_name_to_mhz, out_filepath


def GET_ALL_USER_CLOCKS(parser_state):
    all_user_clks = set()
    for clk_wire, mhz in parser_state.clk_mhz.items():
        clk_group = None
        if clk_wire in parser_state.clk_group:
            clk_group = parser_state.clk_group[clk_wire]
        clk_name = "clk_" + VHDL.CLK_MHZ_GROUP_TEXT(mhz, clk_group)
        all_user_clks.add(clk_name)
    return all_user_clks


# return path
def WRITE_CLK_CONSTRAINTS_FILE(multimain_timing_params, parser_state, inst_name=None):
    # Use specified mhz is multimain top
    import AUTO_MULTI_CYCLE

    clock_name_to_mhz, out_filepath = GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
        parser_state, inst_name
    )
    f = open(out_filepath, "w")

    if SYN_TOOL is OPEN_TOOLS:
        # All clock assumed async in nextpnr constraints
        for clock_name in clock_name_to_mhz:
            clock_mhz = clock_name_to_mhz[clock_name]
            if clock_mhz is None:
                print(
                    f"WARNING: No frequency associated with clock {clock_name}. Missing MAIN_MHZ pragma? Setting to maximum rate = {INF_MHZ}MHz so timing report can be generated..."
                )
                clock_mhz = INF_MHZ
            f.write('ctx.addClock("' + clock_name + '", ' + str(clock_mhz) + ")\n")
    elif SYN_TOOL is CC_TOOLS:
        f.write("#TODO")
    else:
        # Collect all user generated clocks
        all_user_clks = GET_ALL_USER_CLOCKS(parser_state)

        # Standard sdc like constraints
        for clock_name in clock_name_to_mhz:
            clock_mhz = clock_name_to_mhz[clock_name]
            if clock_mhz is None:
                print(
                    f"WARNING: No frequency associated with clock {clock_name}. Missing MAIN_MHZ pragma? Setting to maximum rate = {INF_MHZ}MHz so timing report can be generated..."
                )
                clock_mhz = INF_MHZ
            ns = 1000.0 / clock_mhz
            # Quartus has some maximum acceptable clock period < 8333333 ns
            if SYN_TOOL is QUARTUS:
                MAX_NS = 80000
                if ns > MAX_NS:
                    print("Clipping clock", clock_name, "period to", MAX_NS, "ns...")
                    ns = MAX_NS
            # Default cmd is get_ports unless need internal user clk net name
            get_thing_cmd = "get_ports"
            if clock_name in all_user_clks:
                get_thing_cmd = "get_nets"
            f.write(
                f"create_clock -add -name {clock_name} -period {ns} -waveform {{0 {ns/2.0}}} [{get_thing_cmd} {{{clock_name}}}]\n"
            )

        # All clock assumed async? Doesnt matter for internal syn
        # Rely on generated/board provided constraints for real hardware
        if len(clock_name_to_mhz) > 1:
            if SYN_TOOL is VIVADO:
                f.write(
                    "set_clock_groups -name async_clks_group -asynchronous -group [get_clocks *] -group [get_clocks *]\n"
                )
            elif SYN_TOOL is QUARTUS:
                # Ignored set_clock_groups at clocks.sdc(3): The clock clk_100p0 was found in more than one -group argument.
                # Uh do the hard way?
                clk_sets = set()
                for clock_name1 in clock_name_to_mhz:
                    for clock_name2 in clock_name_to_mhz:
                        if clock_name1 != clock_name2:
                            clk_set = frozenset([clock_name1, clock_name2])
                            if clk_set not in clk_sets:
                                f.write(
                                    "set_clock_groups -asynchronous -group [get_clocks "
                                    + clock_name1
                                    + "] -group [get_clocks "
                                    + clock_name2
                                    + "]"
                                )
                                clk_sets.add(clk_set)
            elif SYN_TOOL is DIAMOND:
                # f.write("set_clock_groups -name async_clks_group -asynchronous -group [get_clocks *] -group [get_clocks *]")
                # ^ is wrong, makes 200mhx system clock?
                pass  # rely on clock cross path detection error in timing report
            else:
                raise Exception(
                    f"How does tool {SYN_TOOL.__name__} deal with async clocks?"
                )

    # Multi cycle path constraints:
    # TODO should mcps be in separate file? - how will user consume like vhdl_files.txt or read_vhdl.tcl?
    # Loop over funcs, records instances of those with MCP constraints
    insts = []
    for func_logic in parser_state.FuncLogicLookupTable.values():
        if len(func_logic.mcp_tuples) > 0:
            func_insts = parser_state.FuncToInstances[func_logic.func_name]
            for func_inst in func_insts:
                if (
                    (inst_name is None)
                    or (inst_name == func_inst)
                    or func_inst.startswith(inst_name + C_TO_LOGIC.SUBMODULE_MARKER)
                ):
                    insts.append(func_inst)
    for inst in insts:
        # Top level has different name if individual module with inst_name or multi main top
        if inst_name is None:
            main_func = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
                inst, parser_state
            )
            main_logic = parser_state.LogicInstLookupTable[main_func]
            top_path = VHDL.GET_ENTITY_NAME(
                main_func,
                main_logic,
                multimain_timing_params.TimingParamsLookupTable,
                parser_state,
            )
            top_inst = main_func
        else:
            func_logic = parser_state.LogicInstLookupTable[inst_name]
            top_path = VHDL.GET_ENTITY_NAME(
                inst_name,
                func_logic,
                multimain_timing_params.TimingParamsLookupTable,
                parser_state,
            )
            top_inst = inst_name
        constraints = AUTO_MULTI_CYCLE.GET_MCP_PATH_CONSTRAINTS(
            inst, top_inst, top_path, multimain_timing_params, parser_state
        )
        for constraint in constraints:
            f.write(constraint + "\n")

    f.close()
    return out_filepath


def DEL_ALL_CACHES():
    # Clear all caches after parsing is done
    global _FUNC_SUBTREE_HAS_STATE_cache
    global _FUNC_TO_INSTANTIATING_FUNCS_cache
    global _FUNC_IS_TOPMOST_COMB_cache
    import AUTO_PIPELINE

    import AUTO_FSM

    _FUNC_SUBTREE_HAS_STATE_cache = {}
    _FUNC_TO_INSTANTIATING_FUNCS_cache = None
    _FUNC_IS_TOPMOST_COMB_cache = {}
    AUTO_PIPELINE.DEL_PIPELINE_CACHES()
    AUTO_FSM.DEL_AUTO_FSM_SUBTREE_CACHE()


    # _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache    = {}


# Target mhz is internal name for whatever mhz we are using in this run
# Real pnr MAIN_MHZ or syn only MAIN_SYN_MHZ
def GET_TARGET_MHZ(main_func, parser_state, allow_no_syn_tool=False):
    if SYN_TOOL is None:
        if not allow_no_syn_tool:
            raise Exception("Need syn tool!")
        # Default to main mhz
        return parser_state.main_mhz[main_func]

    # Does tool do full PNR or just syn?
    if TOOL_DOES_PNR():
        # Uses PNR MAIN_MHZ
        return parser_state.main_mhz[main_func]
    else:
        # Uses synthesis estimates
        return parser_state.main_syn_mhz[main_func]


def WRITE_BLACK_BOX_FILES(parser_state, multimain_timing_params, is_final_top):
    for func_name in parser_state.func_marked_blackbox:
        if func_name in parser_state.FuncToInstances:
            blackbox_func_logic = parser_state.FuncLogicLookupTable[func_name]
            for inst_name in parser_state.FuncToInstances[func_name]:
                bb_out_dir = GET_OUTPUT_DIRECTORY(blackbox_func_logic)
                VHDL.WRITE_LOGIC_ENTITY(
                    inst_name,
                    blackbox_func_logic,
                    bb_out_dir,
                    parser_state,
                    multimain_timing_params.TimingParamsLookupTable,
                    is_final_top,
                )


def CHECK_VHDL_FILES_CONSISTENCY(vhdl_files_texts):
    """Assert the final VHDL file list is referentially consistent: every
    `entity work.X` instantiated inside a listed file is defined by some file
    in the list. VHDL identifiers are case-insensitive, so compare casefolded.
    Raises with the offending (file, unit) pairs -- this is how stale/mixed
    entity references (an old file under a still-matching name whose child
    entities have since been renamed) surface as a build error rather than a
    downstream GHDL/Vivado analysis failure."""
    file_paths = vhdl_files_texts.split()
    defined_units = set()
    file_to_refs = {}
    entity_def_re = re.compile(r"^\s*entity\s+(\w+)\s+is", re.IGNORECASE | re.MULTILINE)
    entity_ref_re = re.compile(r"entity\s+work\.(\w+)", re.IGNORECASE)
    for file_path in file_paths:
        try:
            with open(file_path, "r") as vhd_f:
                text = vhd_f.read()
        except OSError:
            raise Exception(f"vhdl_files.txt references a missing file: {file_path}")
        for m in entity_def_re.finditer(text):
            defined_units.add(m.group(1).casefold())
        refs = {m.group(1).casefold() for m in entity_ref_re.finditer(text)}
        if refs:
            file_to_refs[file_path] = refs
    missing = []
    for file_path, refs in file_to_refs.items():
        for ref in sorted(refs - defined_units):
            missing.append((file_path, ref))
    if missing:
        for file_path, ref in missing:
            print(
                f"VHDL file list inconsistency: {file_path} instantiates "
                f"'entity work.{ref}' but no listed file defines it"
            )
        raise Exception(
            "Final VHDL file list is not self-consistent (stale/mixed entity "
            "references above) -- refusing to hand it to simulation/synthesis."
        )


def WRITE_FINAL_FILES(multimain_timing_params, parser_state):
    import AUTO_PIPELINE

    import AUTO_COMB_OPT

    AUTO_COMB_OPT.DUMP_GENERATED_SOURCE(parser_state, SYN_OUTPUT_DIRECTORY)
    if multimain_timing_params is None:
        ZeroAddedClocksTimingParamsLookupTable = (
            AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
        )
        multimain_timing_params = AUTO_PIPELINE.MultiMainTimingParams()
        multimain_timing_params.TimingParamsLookupTable = (
            ZeroAddedClocksTimingParamsLookupTable
        )

    # The final files/list must be computed 100% against the CURRENT
    # parser_state: invalidate every cached hash/latency string in the final
    # table first (subsumes the previous ancestors-only invalidation --
    # ancestor treatment alone still folded children's stale cached strings,
    # and any cache carried across an AUTO_PIPELINE pass-2 re-elaboration may
    # embed since-renamed child func names). One full lazy recompute at end
    # of build.
    for final_timing_params in multimain_timing_params.TimingParamsLookupTable.values():
        final_timing_params.INVALIDATE_CACHE()

    is_final_top = True
    VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top)

    # Ensure every entity the final file list will reference exists on disk
    # under its freshly-computed (content-aware) name: pass ALL insts as
    # eligible; already-written entities are skipped by name dedup +
    # skip-if-exists inside (sound now that entity hashes cover descendant
    # func names, so same filename => same rendered content).
    AUTO_PIPELINE.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(
        multimain_timing_params.TimingParamsLookupTable,
        parser_state,
        set(multimain_timing_params.TimingParamsLookupTable.keys()),
    )

    # Black boxes are different in final files
    WRITE_BLACK_BOX_FILES(parser_state, multimain_timing_params, is_final_top)

    # Do generic dump of vhdl files
    # Which vhdl files?
    vhdl_files_texts, top_entity_name = GET_VHDL_FILES_TCL_TEXT_AND_TOP(
        multimain_timing_params, parser_state, inst_name=None, is_final_top=is_final_top
    )
    out_filename = "vhdl_files.txt"
    out_filepath = SYN_OUTPUT_DIRECTORY + "/" + out_filename
    out_text = vhdl_files_texts
    f = open(out_filepath, "w")
    f.write(out_text)
    f.close()

    # Referential consistency: every entity instantiated inside a listed file
    # must be defined by a file in the list. Catches any stale/mixed entity
    # references (e.g. a file written by an earlier elaboration pass whose
    # children have since been renamed) at build time with a clear message,
    # instead of failing later inside GHDL/Vivado analysis.
    CHECK_VHDL_FILES_CONSISTENCY(vhdl_files_texts)

    # TODO better GUI / tcl scripts support for other tools
    # ^ incorporate into GET_VHDL_FILES_TCL_TEXT_AND_TOP instead of hacky below?
    if SYN_TOOL is VIVADO:
        # Write read_vhdl.tcl
        tcl = VIVADO.GET_SYN_IMP_AND_REPORT_TIMING_TCL(
            multimain_timing_params,
            parser_state,
            inst_name=None,
            is_final_top=is_final_top,
        )
        rv_lines = []
        for line in tcl.split("\n"):
            # Hacky AF Built To Spill - Kicked It In The Sun
            if (
                line.startswith("read_vhdl")
                or line.startswith("add_files")
                or line.startswith("set_property")
            ):
                line = line.replace(SYN_OUTPUT_DIRECTORY, "$thisDir")
                line = line.replace(VIVADO.VIVADO_DIR, "$vivadoDir")
                line = line.replace("{", "[subst {").replace("}", "}]")
                rv_lines.append(line)
        rv = ""
        rv += f"set vivadoDir {VIVADO.VIVADO_DIR}\n"
        rv += "set thisFile [ dict get [ info frame 0 ] file ] \n"
        rv += "set thisDir [file dirname $thisFile] \n"
        for line in rv_lines:
            rv += line + "\n"

        # Write file
        out_filename = "read_vhdl.tcl"
        out_filepath = SYN_OUTPUT_DIRECTORY + "/" + out_filename
        out_text = rv
    elif SYN_TOOL is QUARTUS:
        # Make a .qip file in the output dir
        # Pull set vhdl file assignment lines from file (gets ieee stuff too)
        # I dont think its too hacky right? lolz Baby When I Close My Eyes  -Sweet Spirit
        constraints_filepath = ""  # fine for this
        tcl = QUARTUS.GET_SH_TCL(
            top_entity_name, vhdl_files_texts, constraints_filepath, parser_state
        )
        rv_lines = []
        for line in tcl.split("\n"):
            if "-name VHDL_FILE" in line:
                # Ok getting hack hack
                if SYN_OUTPUT_DIRECTORY in line:
                    line = (
                        line.replace(
                            SYN_OUTPUT_DIRECTORY + "/",
                            '[file join $::quartus(qip_path) "',
                        )
                        + '"]'
                    )
                rv_lines.append(line)
        rv = ""
        for line in rv_lines:
            rv += line + "\n"

        # Write file
        out_filename = "pipelinec_top.qip"
        out_filepath = SYN_OUTPUT_DIRECTORY + "/" + out_filename
        out_text = rv

    print("Output VHDL files:", out_filepath)
    f = open(out_filepath, "w")
    f.write(out_text)
    f.close()

    # Optional Vivado .xo file, only needs IO info to be ready, not final read_vhdl.tcl yet
    if WRITE_AXIS_XO_FILE:
        VIVADO.WRITE_AXIS_XO(parser_state)

    # Tack on a conversion to verilog if requested
    if CONVERT_FINAL_TOP_VERILOG:
        OPEN_TOOLS.RENDER_FINAL_TOP_VERILOG(multimain_timing_params, parser_state)


# Wow this is hack AF
def GET_MAIN_INSTS_FROM_PATH_REPORT(path_report, parser_state, TimingParamsLookupTable):
    main_insts = set()
    if path_report.start_reg_name is None:
        return main_insts
    if path_report.end_reg_name is None:
        return main_insts
    all_main_insts = list(reversed(sorted(list(parser_state.main_mhz.keys()), key=len)))
    # Try to go off of just start and end registers being in single top level main
    start_reg_main = None
    end_reg_main = None
    for main_inst in all_main_insts:
        main_logic = parser_state.LogicInstLookupTable[main_inst]
        main_vhdl_entity_name = VHDL.GET_ENTITY_NAME(
            main_inst,
            main_logic,
            TimingParamsLookupTable,
            parser_state,
        )
        # OPEN_TOOLs reports in lower case
        if path_report.start_reg_name.lower().startswith(main_vhdl_entity_name.lower()):
            start_reg_main = main_inst
        if path_report.end_reg_name.lower().startswith(main_vhdl_entity_name.lower()):
            end_reg_main = main_inst
        if start_reg_main == end_reg_main and start_reg_main is not None:
            main_insts.add(start_reg_main)

    # If nothing was found try hacky netlist resource check?
    # if len(main_insts) == 0:
    # Include start and end regs in search
    all_netlist_resources = set(path_report.netlist_resources)
    all_netlist_resources.add(path_report.start_reg_name)
    all_netlist_resources.add(path_report.end_reg_name)
    for netlist_resource in all_netlist_resources:
        # toks = netlist_resource.split("/")
        # if toks[0] in parser_state.main_mhz:
        #  main_inst_funcs.add(toks[0])
        # If in the top level - no '/'? then look for main funcs like a dummy
        # if "/" not in netlist_resource:
        # Main funcs sorted by len for best match
        match_main = None
        # print("netlist_resource",netlist_resource)
        for main_inst in all_main_insts:
            main_logic = parser_state.LogicInstLookupTable[main_inst]
            main_vhdl_entity_name = VHDL.GET_ENTITY_NAME(
                main_inst,
                main_logic,
                TimingParamsLookupTable,
                parser_state,
            )
            # print(main_vhdl_entity_name,"?")
            # OPEN_TOOLs reports in lower case
            if netlist_resource.lower().startswith(main_vhdl_entity_name.lower()):
                match_main = main_inst
                break
        if match_main:
            main_insts.add(match_main)

    # If nothing was found try hacky clock cross check?
    # if len(main_insts) == 0:
    # print("No mains form path reportS?")
    start_inst = path_report.start_reg_name.split("/")[0]
    end_inst = path_report.end_reg_name.split("/")[0]
    # print(start_inst,end_inst)
    if (start_inst in parser_state.clk_cross_var_info) and (
        end_inst in parser_state.clk_cross_var_info
    ):
        start_info = parser_state.clk_cross_var_info[start_inst]
        end_info = parser_state.clk_cross_var_info[end_inst]
        # Start read and end write must be same main
        start_write_mains, start_read_mains = start_info.write_read_main_funcs
        end_write_mains, end_read_mains = end_info.write_read_main_funcs
        # print(start_read_main,end_write_main)
        in_both_mains = start_read_mains & end_write_mains
        if len(in_both_mains) > 0:
            main_insts |= in_both_mains

    return main_insts


def GET_REGISTERS_ESTIMATE_TEXT_AND_FFS(
    logic, inst_name, parser_state, TimingParamsLookupTable, ff_est_cache
):
    import AUTO_PIPELINE

    timing_params = TimingParamsLookupTable[inst_name]
    hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)

    cache_key = (logic.func_name, hash_ext)
    if cache_key in ff_est_cache:
        cache_text, cache_ffs = ff_est_cache[cache_key]
        return cache_text, cache_ffs

    total_ffs = 0
    text = f"Function: {C_TO_LOGIC.LEAF_NAME(inst_name)} ({logic.func_name})\n"

    input_ffs = 0
    inputs_text = ""
    for input_port in logic.inputs:
        input_type = logic.wire_to_c_type[input_port]
        inputs_text += input_type + " " + input_port + ","
        input_bits = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(input_type, parser_state)
        input_ffs += input_bits
    inputs_text += "\n"
    if timing_params._has_input_regs:
        text += f"  {input_ffs} Input FFs: " + inputs_text
        total_ffs += input_ffs

    output_ffs = 0
    outputs_text = ""
    for output_port in logic.outputs:
        output_type = logic.wire_to_c_type[output_port]
        outputs_text += output_type + " " + output_port + ","
        output_bits = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(output_type, parser_state)
        output_ffs += output_bits
    outputs_text += "\n"
    if timing_params._has_output_regs:
        text += f"  {output_ffs} Output FFs: " + outputs_text
        total_ffs += output_ffs

    if len(logic.state_regs) > 0:
        state_reg_ffs = 0
        state_regs_text = ""
        for state_reg_name in logic.state_regs:
            var_info = logic.state_regs[state_reg_name]
            state_reg_type = var_info.type_name
            state_regs_text += state_reg_type + " " + state_reg_name + ","
            state_reg_bits = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(
                state_reg_type, parser_state
            )
            state_reg_ffs += state_reg_bits
        state_regs_text += "\n"
        text += f"  {state_reg_ffs} State Register FFs: " + state_regs_text
        total_ffs += state_reg_ffs

    latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
    if latency > 0:
        if VHDL.LOGIC_IS_RAW_HDL(logic, parser_state) or C_TO_LOGIC.FUNC_IS_PRIMITIVE(
            logic.func_name, parser_state
        ):
            # Raw vhdl estimate func of N bits input -> M bits output as using
            # (N+M)/2 bits per pipeline stage
            avg_regs = int((input_ffs + output_ffs) / 2)
            # raw_hdl_ffs = avg_regs * (latency)
            # text += f"  {avg_regs} average width * {latency} pipeline register stages = ~ {raw_hdl_ffs} FFs\n"
            raw_hdl_ffs = avg_regs
            text += f"  ~ {avg_regs} average bit width = ~ {raw_hdl_ffs} FFs\n"
            total_ffs += raw_hdl_ffs
        else:
            # use range size from PiplineHDLParams to get regs for each wire
            # do per stage - how many regs from wires in each stage
            pipeline_map = AUTO_PIPELINE.GET_PIPELINE_MAP(
                inst_name, logic, parser_state, TimingParamsLookupTable
            )
            pipeline_hdl_params = AUTO_PIPELINE.PiplineHDLParams(
                inst_name, logic, parser_state, TimingParamsLookupTable, pipeline_map
            )
            pipeline_ffs = 0
            pipeline_text = ""
            for stage in range(0, latency):  # Last stage never has regs, dont print
                stage_ffs = 0
                stage_wires_text = ""
                for wire in pipeline_hdl_params.wires_to_decl:
                    (
                        wire_start_stage,
                        wire_end_stage,
                    ) = pipeline_hdl_params.wire_to_reg_stage_start_end[wire]
                    if wire_start_stage is None or wire_end_stage is None:
                        continue
                    if stage in range(wire_start_stage, wire_end_stage + 1):
                        wire_type = logic.wire_to_c_type[wire]
                        wire_ffs = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(
                            wire_type, parser_state
                        )
                        stage_ffs += wire_ffs
                        stage_wires_text += f"{wire_type}({wire_ffs} bits) {wire}, "
                stage_text = (
                    "    "
                    + f"{stage_ffs} FFs for stage {stage}: "
                    + stage_wires_text
                    + "\n"
                )
                pipeline_text += stage_text
                pipeline_ffs += stage_ffs
            text += f"  {pipeline_ffs} FFs for {latency+1} auto-pipeline stages:\n"
            text += pipeline_text
            total_ffs += pipeline_ffs

    sub_mod_reg_ffs = 0
    sub_mod_regs_text = ""
    for sub_inst in logic.submodule_instances:
        sub_func_name = logic.submodule_instances[sub_inst]
        sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
        sub_full_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + sub_inst
        sub_inst_text, sub_inst_ffs = GET_REGISTERS_ESTIMATE_TEXT_AND_FFS(
            sub_logic,
            sub_full_inst,
            parser_state,
            TimingParamsLookupTable,
            ff_est_cache,
        )
        sub_inst_text = sub_inst_text.strip("\n")
        if sub_inst_ffs > 0:
            for sub_inst_text_line in sub_inst_text.split("\n"):
                sub_mod_regs_text += "    " + sub_inst_text_line + "\n"
            # sub_mod_regs_text = sub_mod_regs_text.strip("\n")
        sub_mod_reg_ffs += sub_inst_ffs
    # sub_mod_regs_text += "\n"
    if sub_mod_reg_ffs > 0:
        text += f"  {sub_mod_reg_ffs} total submodule FFs: \n"
        text += sub_mod_regs_text
        total_ffs += sub_mod_reg_ffs

    text = f"{total_ffs} FFs " + text

    ff_est_cache[cache_key] = (text, total_ffs)
    return text, total_ffs


def WRITE_REGISTERS_ESTIMATE_FILE(
    parser_state, multimain_timing_params_or_TimingParamsLookupTable, inst_name=None
):
    if inst_name is None:
        # Multi main
        multimain_timing_params = multimain_timing_params_or_TimingParamsLookupTable
        TimingParamsLookupTable = multimain_timing_params.TimingParamsLookupTable
        hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
        output_dir = SYN_OUTPUT_DIRECTORY + "/" + TOP_LEVEL_MODULE
        output_file = output_dir + "/" + TOP_LEVEL_MODULE + hash_ext + "_registers.log"
    else:
        # Specific inst
        TimingParamsLookupTable = multimain_timing_params_or_TimingParamsLookupTable
        logic = parser_state.LogicInstLookupTable[inst_name]
        # Prim pipelines dont have reg estimates
        if C_TO_LOGIC.FUNC_IS_PRIMITIVE(logic.func_name, parser_state):
            return
        output_dir = GET_OUTPUT_DIRECTORY(logic)
        timing_params = TimingParamsLookupTable[inst_name]
        hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
        latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
        output_file = (
            output_dir
            + "/"
            + f"{logic.func_name}_{latency}CLK"
            + hash_ext
            + "_registers.log"
        )

    # Start cache of info for recursive process
    ff_est_cache = {}

    # For each main func write text
    text = ""
    for main_func in parser_state.main_mhz:
        main_logic = parser_state.LogicInstLookupTable[main_func]
        main_func_text, main_func_ffs = GET_REGISTERS_ESTIMATE_TEXT_AND_FFS(
            main_logic, main_func, parser_state, TimingParamsLookupTable, ff_est_cache
        )
        text += main_func_text
        text += "\n"

    print(f"Estimated register usage: {output_file}")
    f = open(output_file, "w")
    f.write(text)
    f.close()


def GET_ESTIMATED_COMBINATIONAL_AREA(logic, parser_state, area_memo=None):
    """Sum of cached leaf areas (SYN.GET_CACHED_LEAF_AREA) across logic's
    full instance hierarchy, one term per call site -- the combinational
    counterpart to GET_REGISTERS_ESTIMATE_TEXT_AND_FFS's sequential walk.
    Every non-shared call site becomes its own hardware instance, so a leaf
    used N times contributes N times its area, exactly like the FF walk
    counts every instance's own registers.

    Returns (area, unit, missing_leaf_func_names). A leaf with no cached
    area contributes 0.0 and its func_name to the missing set rather than
    triggering synthesis here -- see ADD_PATH_DELAY_TO_LOOKUP's forced
    remeasure clause for where cache/area actually gets filled in. The
    exception is a leaf LOGIC_IS_ZERO_DELAY already excludes from synthesis
    entirely (bit-manip/concat/const-ref wiring, black boxes, ...): it
    correctly has no cache/area entry because nothing ever measured it, so
    it contributes 0.0 without being counted as missing.

    Genuinely combinational as of AREA_MODEL_VERSION 2: GET_CACHED_LEAF_AREA
    reads combinational_cell_area, not total_cell_area, so a leaf's own
    dont_touch STA harness registers (VHDL.WRITE_LOGIC_TOP) are excluded. A
    v1 cache mixed them in, which is why ESTIMATE_DESIGN_AREA used to
    double-count sequential area between this term and its own FF term.
    """
    area_memo = {} if area_memo is None else area_memo
    hit = area_memo.get(logic.func_name)
    if hit is not None:
        return hit
    unit = DEVICE_MODELS.AREA_UNIT if SYN_TOOL is DEVICE_MODELS else None
    area_memo[logic.func_name] = (0.0, unit, frozenset())  # cycle guard
    if not logic.submodule_instances:
        if LOGIC_IS_ZERO_DELAY(logic, parser_state, allow_none_delay=True):
            result = (0.0, unit, frozenset())
        else:
            cached = GET_CACHED_LEAF_AREA(logic, parser_state)
            if cached is None:
                result = (0.0, unit, frozenset({logic.func_name}))
            else:
                value, cached_unit = cached
                result = (value, cached_unit, frozenset())
    else:
        total = 0.0
        missing = set()
        for sub_func_name in logic.submodule_instances.values():
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            sub_area, sub_unit, sub_missing = GET_ESTIMATED_COMBINATIONAL_AREA(
                sub_logic, parser_state, area_memo
            )
            total += sub_area
            missing |= sub_missing
            unit = sub_unit or unit
        result = (total, unit, frozenset(missing))
    area_memo[logic.func_name] = result
    return result


def ESTIMATE_DESIGN_AREA(
    parser_state, multimain_timing_params_or_TimingParamsLookupTable, inst_name=None
):
    """Whole-design area estimate: cached leaf areas summed across the
    instance hierarchy (combinational) plus PipelineC's own already-computed
    FF count times one flip-flop's real cell area (sequential). Pure
    computation, no synthesis triggered -- see GET_ESTIMATED_COMBINATIONAL_AREA.
    Same dual multimain/single-inst calling convention as
    GET_REGISTERS_ESTIMATE_TEXT_AND_FFS/WRITE_REGISTERS_ESTIMATE_FILE.
    """
    if inst_name is None:
        multimain_timing_params = multimain_timing_params_or_TimingParamsLookupTable
        TimingParamsLookupTable = multimain_timing_params.TimingParamsLookupTable
        mains = [
            (parser_state.LogicInstLookupTable[main_func], main_func)
            for main_func in parser_state.main_mhz
        ]
    else:
        TimingParamsLookupTable = multimain_timing_params_or_TimingParamsLookupTable
        mains = [(parser_state.LogicInstLookupTable[inst_name], inst_name)]

    unit = None
    dff_area = 0.0
    if SYN_TOOL is DEVICE_MODELS:
        dff_area, unit = DEVICE_MODELS.GET_SEQUENTIAL_CELL_AREA()

    area_memo = {}
    ff_est_cache = {}
    combinational_area = 0.0
    total_ffs = 0
    missing_leaf_funcs = set()
    for logic, full_inst_name in mains:
        comb_area, comb_unit, missing = GET_ESTIMATED_COMBINATIONAL_AREA(
            logic, parser_state, area_memo
        )
        combinational_area += comb_area
        missing_leaf_funcs |= missing
        unit = comb_unit or unit
        _text, main_ffs = GET_REGISTERS_ESTIMATE_TEXT_AND_FFS(
            logic, full_inst_name, parser_state, TimingParamsLookupTable, ff_est_cache
        )
        total_ffs += main_ffs

    sequential_area = total_ffs * dff_area
    return {
        "total_area": combinational_area + sequential_area,
        "combinational_area": combinational_area,
        "sequential_area": sequential_area,
        "n_ffs": total_ffs,
        "area_unit": unit,
        "missing_leaf_area_funcs": sorted(missing_leaf_funcs),
    }


def WRITE_AREA_ESTIMATE_FILE(
    parser_state, multimain_timing_params_or_TimingParamsLookupTable, inst_name=None
):
    """Print + JSON sidecar for ESTIMATE_DESIGN_AREA, written beside the
    matching _registers.log (see WRITE_REGISTERS_ESTIMATE_FILE, same output
    path convention with _area.json in place of _registers.log). No-op for
    any SYN_TOOL other than DEVICE_MODELS -- area is a sky130-only estimate
    today, and every non-DEVICE_MODELS tool's leaf area cache is empty by
    construction (SYN.GET_AREA_CACHE_DIR returns None for them).
    """
    if SYN_TOOL is not DEVICE_MODELS:
        return
    if inst_name is None:
        multimain_timing_params = multimain_timing_params_or_TimingParamsLookupTable
        hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
        output_dir = SYN_OUTPUT_DIRECTORY + "/" + TOP_LEVEL_MODULE
        output_file = output_dir + "/" + TOP_LEVEL_MODULE + hash_ext + "_area.json"
    else:
        TimingParamsLookupTable = multimain_timing_params_or_TimingParamsLookupTable
        logic = parser_state.LogicInstLookupTable[inst_name]
        if C_TO_LOGIC.FUNC_IS_PRIMITIVE(logic.func_name, parser_state):
            return
        output_dir = GET_OUTPUT_DIRECTORY(logic)
        timing_params = TimingParamsLookupTable[inst_name]
        hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
        latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
        output_file = (
            output_dir
            + "/"
            + f"{logic.func_name}_{latency}CLK"
            + hash_ext
            + "_area.json"
        )

    result = ESTIMATE_DESIGN_AREA(
        parser_state, multimain_timing_params_or_TimingParamsLookupTable, inst_name
    )
    unit = result["area_unit"] or DEVICE_MODELS.AREA_UNIT
    missing_note = (
        f", {len(result['missing_leaf_area_funcs'])} leaf area(s) not yet cached"
        if result["missing_leaf_area_funcs"]
        else ""
    )
    print(
        f"Estimated area: {result['total_area']:.1f} {unit} "
        f"(comb {result['combinational_area']:.1f} + regs {result['sequential_area']:.1f}, "
        f"{result['n_ffs']} FFs){missing_note} [estimate, pre-PnR]"
    )
    with open(output_file, "w") as f:
        json.dump(dict(result, schema_version=1), f, indent=2, sort_keys=True)
        f.write("\n")


def PRINT_MEASURED_AREA_IF_AVAILABLE(timing_report, estimated_total_area=None):
    """After a real whole-design confirmation synthesis (only DEVICE_MODELS
    ever populates this -- see DEVICE_MODELS._run_synth_and_sta, which
    measures area as a free byproduct of the same mapped netlist it already
    STAs), print the exact measured area once. One number for the whole
    design regardless of how many clock groups were reported, since they all
    come from the same single mapped netlist.
    """
    for path_report in timing_report.path_reports.values():
        area = getattr(path_report, "total_cell_area", None)
        unit = getattr(path_report, "area_unit", None)
        if area is None or unit is None:
            return
        delta_note = ""
        if estimated_total_area:
            delta_pct = (estimated_total_area - area) / area * 100.0
            delta_note = f" (estimate {delta_pct:+.2f}%)"
        print(f"Measured area: {area:.1f} {unit}{delta_note}", flush=True)
        return


def GENERATE_FINAL_BITSTREAM(parser_state, multimain_timing_params):
    print("================== Generating Bitstream ==================", flush=True)
    generate_bitstream = getattr(SYN_TOOL, "GENERATE_BITSTREAM", None)
    if generate_bitstream is not None:
        return generate_bitstream(parser_state, multimain_timing_params)
    # Backends without an explicit bitstream hook keep the historical path.
    return SYN_TOOL.SYN_AND_REPORT_TIMING(
        None,
        None,
        parser_state,
        multimain_timing_params.TimingParamsLookupTable,
        is_final_top=True,
    )


# Not because it is easy, but because we thought it would be easy

# Do I like Joe Walsh?


def RUN_INST_SYN_AND_UPDATE_CACHE(
    inst_name, logic, inst_sweep_state, parser_state, TimingParamsLookupTable
):
    import AUTO_PIPELINE

    # Run syn on multi main top
    timing_params = TimingParamsLookupTable[inst_name]
    latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
    print(
        "Synthesizing",
        logic.func_name,
        ":",
        latency,
        "clocks total latency...",
        len(timing_params._slices),
        "slices...",
        flush=True,
    )
    print(f"Elapsed time: {str(datetime.timedelta(seconds=(timer() - START_TIME)))}...")
    inst_sweep_state.timing_report = SYN_TOOL.SYN_AND_REPORT_TIMING(
        inst_name, logic, parser_state, TimingParamsLookupTable
    )

    # Write pipeline delay cache
    AUTO_PIPELINE.UPDATE_PIPELINE_MIN_PERIOD_CACHE(
        inst_sweep_state.timing_report,
        TimingParamsLookupTable,
        parser_state,
        inst_name,
    )


def FUNC_SRC_LOC_STR(parser_state, func_name):
    """' [file.py:line]' for a function's true source location, or '' when
    none is known (built-ins, raw-HDL, etc.) -- for appending to stdout/
    [sweep] messages that name a function, so a reader isn't left grepping a
    second, much larger log file for a line number. Logic.ast_meta already
    carries this; nothing printed it before now."""
    logic = parser_state.FuncLogicLookupTable.get(func_name)
    ast_meta = getattr(logic, "ast_meta", None)
    if ast_meta is None:
        return ""
    return f" [{os.path.basename(ast_meta.src_file)}:{ast_meta.line}]"


def GET_OUTPUT_DIRECTORY(Logic):
    if Logic.is_c_built_in or Logic.ast_meta is None:
        output_directory = (
            SYN_OUTPUT_DIRECTORY + "/" + "built_in" + "/" + Logic.func_name
        )
    elif SW_LIB.IS_BIT_MANIP(Logic):
        output_directory = (
            SYN_OUTPUT_DIRECTORY
            + "/"
            + SW_LIB.BIT_MANIP_HEADER_FILE
            + "/"
            + Logic.func_name
        )
    elif SW_LIB.IS_MEM(Logic):
        output_directory = (
            SYN_OUTPUT_DIRECTORY + "/" + SW_LIB.MEM_HEADER_FILE + "/" + Logic.func_name
        )
    elif SW_LIB.IS_BIT_MATH(Logic):
        output_directory = (
            SYN_OUTPUT_DIRECTORY
            + "/"
            + SW_LIB.BIT_MATH_HEADER_FILE
            + "/"
            + Logic.func_name
        )
    else:
        # Use source file if not built in?
        # print("Logic.func_name", Logic.func_name)
        src_file = Logic.ast_meta.src_file
        # # hacky catch files from same dir as script?
        # ex src file = /media/1TB/Dropbox/PipelineC/git/PipelineC/src/../axis.h
        repo_dir = REPO_ABS_DIR()
        if src_file.startswith(repo_dir + "/"):
            # hacky
            src_file = src_file.replace(repo_dir + "/src/../", "")
            src_file = src_file.replace(repo_dir + "/", "")
            output_directory = (
                SYN_OUTPUT_DIRECTORY + "/" + src_file + "/" + Logic.func_name
            )
        # hacky catch generated files from output dir already?
        elif src_file.startswith(SYN_OUTPUT_DIRECTORY + "/"):
            output_directory = os.path.dirname(src_file)
        else:
            # Otherwise normal
            # output_directory = SYN_OUTPUT_DIRECTORY + "/" + src_file + "/" + Logic.func_name
            # print("output_directory",output_directory,repo_dir)
            # Func uniquely identifies logic so just use that?
            output_directory = SYN_OUTPUT_DIRECTORY + "/" + Logic.func_name

    if output_directory.endswith("/" + Logic.func_name):
        output_directory = output_directory[
            : -len(Logic.func_name)
        ] + VHDL.EMITTED_NAME(Logic.func_name, Logic)
    return output_directory


def LOGIC_IS_ZERO_DELAY(logic, parser_state, allow_none_delay=False):
    if logic.func_name in parser_state.func_marked_wires:
        return True
    # Black boxes have no known delay to the tool
    elif logic.func_name in parser_state.func_marked_blackbox:
        return True
    elif SW_LIB.IS_BIT_MANIP(logic):
        return True
    elif logic.is_clock_crossing:
        return True  # For now? How to handle paths through clock cross logic?
    elif logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
        return True
    elif logic.func_name.startswith(
        C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SL_NAME
    ) or logic.func_name.startswith(
        C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SR_NAME
    ):
        return True
    elif logic.vhdl_module_text is not None:
        return False  # No idea what user has in there
    elif logic.is_vhdl_func or logic.is_vhdl_expr:
        return True
    elif (
        logic.func_name in getattr(parser_state, "func_fixed_latency", {})
        and not logic.is_c_built_in
        and not logic.submodule_instances
    ):
        # A user pipeline consisting only of wire assignments and registers
        # has no combinational operators to time. In particular PYRTL's
        # zero-FF-overhead timing model cannot divide by this zero path delay.
        return True
    elif logic.is_c_built_in and C_TO_LOGIC.IS_SIM_CTRL_FUNC_NAME(logic.func_name):
        # printf/sim_print, sim_assert, and sim_finish submodules are all void,
        # simulation-console-facing builtins with no real output to measure a delay
        # to -- without this, sim_assert_.../sim_finish_... fall through to the
        # `else` branch below and get fed to real synthesis for pre-pipelining path
        # delay measurement, which produces an all-zero utilization report (nothing
        # to synthesize) that VIVADO.py's ParsedTimingReport then rejects as a "Bad
        # synthesis log?" instead of the zero-delay short-circuit sim_print already got.
        return True
    elif (SYN_TOOL is GOWIN) and logic.func_name.startswith(
        f"{C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX}_{C_TO_LOGIC.UNARY_OP_NOT_NAME}_"
    ):
        # for some reason, GowinSynthesis (GOWIN EDA version 1.9.9.01)
        # fails to generate timing reports for this particular setup, so we skip it
        return True
    else:
        # Maybe all submodules are zero delay?
        if len(logic.submodule_instances) > 0:
            for submodule_inst in logic.submodule_instances:
                submodule_func_name = logic.submodule_instances[submodule_inst]
                submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
                if submodule_logic.delay is None:
                    if allow_none_delay:
                        return False
                    else:
                        raise Exception("Wtf none to check delay?")
                if submodule_logic.delay > 0:
                    return False
            return True

    return False


def LOGIC_SINGLE_SUBMODULE_DELAY(logic, parser_state):
    if len(logic.submodule_instances) != 1:
        return None
    if logic.vhdl_module_text is not None:
        return None

    submodule_inst = list(logic.submodule_instances.keys())[0]
    submodule_func_name = logic.submodule_instances[submodule_inst]
    submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
    if submodule_logic.delay is None:
        print("Wtf none to check delay???????")
        sys.exit(-1)

    return submodule_logic.delay


# Pypeline's shipped operator-overload library (include/pypeline/operators/)
# is library code, not user code, for cache/delay purposes -- like
# floating_point.py/fixed_point.py, its entities are reused verbatim across
# any design at a given (op, widths) and should be measured once and cached,
# the same as a built-in BIN_OP_* leaf. Without this, IS_USER_CODE's default
# "not is_c_built_in" rule makes every soft-op entity ineligible for the
# cache (see docs/operator_qor_report.md finding C): its delay is instead
# *estimated* bottom-up from submodule delays every build, which is measurably
# less accurate than a real measured/cached number and can mis-plan the
# auto-pipeline slice budget.
_operators_library_dir_cache = None


def _GET_OPERATORS_LIBRARY_DIR():
    # Lazy + cached: computed at first use, not import time. C_TO_LOGIC.EXE_ABS_DIR
    # is unavailable while this module is still being imported (SW_LIB -> SYN
    # happens partway through C_TO_LOGIC's own top-level imports).
    global _operators_library_dir_cache
    if _operators_library_dir_cache is None:
        _operators_library_dir_cache = os.path.abspath(
            C_TO_LOGIC.EXE_ABS_DIR() + "/../include/pypeline/operators"
        )
    return _operators_library_dir_cache


def _IS_PYPELINE_OPERATOR_LIBRARY_CODE(logic, parser_state):
    entity_callables = getattr(parser_state, "pypeline_entity_callables", None)
    if not entity_callables:
        return False
    live_callable = entity_callables.get(logic.func_name)
    if live_callable is None:
        return False
    try:
        src_file = inspect.getsourcefile(live_callable)
    except TypeError:
        return False
    if src_file is None:
        return False
    return os.path.abspath(src_file).startswith(_GET_OPERATORS_LIBRARY_DIR() + os.sep)


def IS_USER_CODE(logic, parser_state):
    # Check logic.is_built_in
    # or autogenerated code
    # or Pypeline's own shipped operator-overload library

    if _IS_PYPELINE_OPERATOR_LIBRARY_CODE(logic, parser_state):
        return False

    user_code = not logic.is_c_built_in and not SW_LIB.IS_AUTO_GENERATED(logic)

    # GAH NEED TO CHECK input and output TYPES
    # AND ALL INNNER WIRES TOO!
    all_types = []
    for input_port in logic.inputs:
        all_types.append(logic.wire_to_c_type[input_port])
    for wire in logic.wires:
        all_types.append(logic.wire_to_c_type[wire])
    for output_port in logic.outputs:
        all_types.append(logic.wire_to_c_type[output_port])
    all_types = list(set(all_types))

    # Becomes user code if using struct or array of structs
    # For now???? fuck me
    for c_type in all_types:
        is_user = C_TO_LOGIC.C_TYPE_IS_USER_TYPE(c_type, parser_state)
        if is_user:
            user_code = True
            break
    # print "?? USER? logic.func_name:",logic.func_name, user_code

    return user_code


def GET_CACHE_ROOT_DIR():
    """Root of the committed measurement cache tree: cache/delay, cache/area.

    One env override for the whole tree -- the subtrees are siblings under it
    (see GET_PATH_DELAY_CACHE_DIR / GET_AREA_CACHE_DIR), never independently
    relocatable, so a build can never read delay from one tree and area from
    another.
    """
    return os.environ.get(
        "PYPELINEC_CACHE_DIR", C_TO_LOGIC.EXE_ABS_DIR() + "/../cache/"
    )


# Windows forbids these in a path component. `:` is the live case: Gowin parts
# are spelled PART:DEVICE_VERSION (GOWIN.py splits on it) and a committed
# cache/delay/gowin/<part> dir named that way broke every Windows checkout
# (PR #298). `/` would silently nest directories (a Gowin tool grade like C8/I7).
_UNSAFE_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


def PART_CACHE_DIR_NAME(part):
    """The part as one filesystem-safe path component (cache dirs only).

    The part string itself keeps its spelling everywhere else -- tools parse
    it (GOWIN.py splits PART:DEVICE_VERSION on the colon) -- only the directory
    it is cached under is sanitized.
    """
    return _UNSAFE_PATH_CHARS_RE.sub("_", part)


def GET_PATH_DELAY_CACHE_DIR(parser_state, dir_name="delay"):
    cache_dir = os.path.join(GET_CACHE_ROOT_DIR(), dir_name)
    PATH_DELAY_CACHE_DIR = os.path.join(cache_dir, str(SYN_TOOL.__name__).lower())
    if SYN_TOOL is PYRTL:
        PATH_DELAY_CACHE_DIR += (
            "_" + str(PYRTL.TECH_IN_NM) + "nm" + "_" + str(PYRTL.FF_OVERHEAD) + "ff"
        )
    if SYN_TOOL is DEVICE_MODELS:
        PATH_DELAY_CACHE_DIR += (
            "_" + DEVICE_MODELS.SELECTED_LIBRARY
            + "_" + DEVICE_MODELS.SELECTED_CORNER
            + "_v" + str(DEVICE_MODELS.MODEL_VERSION)
            + DEVICE_MODELS.GET_SYNTHESIS_RECIPE_CACHE_SUFFIX()
        )
    PATH_DELAY_CACHE_DIR += GET_PLANNER_DELAY_CACHE_SUFFIX()
    # `part` disambiguates cache entries when the same SYN_TOOL/library/
    # corner combo could still map to different physical parts (ex. PyRTL's
    # tech node doesn't imply an FPGA part number). For DEVICE_MODELS the
    # part carries no information the library+corner above doesn't already
    # encode -- the part string is only ever a *selector* that routes to this
    # tool (PART_SET_TOOL matches any "sky130"-prefixed string), and the
    # library/corner actually used comes from SELECTED_LIBRARY/SELECTED_CORNER
    # regardless of how it was spelled. Appending it too would fragment one
    # logical cache across a directory per spelling: PART("sky130") and
    # PART("sky130_fd_sc_hvl") select the identical tool+library+corner but
    # would look in ".../sky130/syn" and ".../syn" respectively, so a
    # committed cache populated under one spelling silently misses under the
    # other (real bug: PART("sky130") re-synthesized every already-cached
    # leaf).
    part_already_encoded = SYN_TOOL is DEVICE_MODELS
    if parser_state.part is not None and not part_already_encoded:
        PATH_DELAY_CACHE_DIR += "/" + PART_CACHE_DIR_NAME(parser_state.part)
    if TOOL_DOES_PNR():
        PATH_DELAY_CACHE_DIR += "/pnr"
    else:
        PATH_DELAY_CACHE_DIR += "/syn"
    return PATH_DELAY_CACHE_DIR


def GET_AREA_CACHE_DIR(parser_state, dir_name="area"):
    """Leaf area cache directory, mirroring GET_PATH_DELAY_CACHE_DIR above.

    Returns None for any SYN_TOOL that has no area source -- only
    DEVICE_MODELS measures area today, unlike the delay cache which every
    tool populates. Callers must check for None.

    Keyed by DEVICE_MODELS.AREA_MODEL_VERSION, deliberately NOT
    DEVICE_MODELS.MODEL_VERSION: leaf area depends only on which cells the
    synthesis recipe maps to (a flat histogram sum, see
    DEVICE_MODELS.MEASURE_NETLIST_AREA), not on run_sta()'s own STA physics.
    A future STA-only MODEL_VERSION bump must not discard an
    otherwise-still-valid committed cache/area, and vice versa.
    """
    if SYN_TOOL is not DEVICE_MODELS:
        return None
    cache_dir = os.path.join(GET_CACHE_ROOT_DIR(), dir_name)
    AREA_CACHE_DIR = os.path.join(cache_dir, str(SYN_TOOL.__name__).lower())
    AREA_CACHE_DIR += (
        "_" + DEVICE_MODELS.SELECTED_LIBRARY
        + "_" + DEVICE_MODELS.SELECTED_CORNER
        + "_a" + str(DEVICE_MODELS.AREA_MODEL_VERSION)
        + DEVICE_MODELS.GET_SYNTHESIS_RECIPE_CACHE_SUFFIX()
    )
    AREA_CACHE_DIR += "/syn"
    return AREA_CACHE_DIR


def LOGIC_IS_BUILT_IN_MUX(logic):
    return logic.is_c_built_in and logic.func_name.startswith(
        C_TO_LOGIC.MUX_LOGIC_NAME
    )


def LOGIC_PATH_DELAY_IS_CACHEABLE(logic, parser_state):
    """Measured built-in MUXes are reusable even when their packed data
    type is user-defined.  Other user-code entities retain the existing
    no-disk-cache policy."""
    return LOGIC_IS_BUILT_IN_MUX(logic) or not IS_USER_CODE(logic, parser_state)


def CLAIM_MUX_PATH_DELAY_SYNTH_OWNER(
    logic, parser_state, cache_key_to_owner
):
    """Claim one cold synthesis owner for a canonical packed-MUX key.

    Returns ``(None, None)`` for non-MUX logic.  Equivalent typed MUXes get
    the first claimant's function name so ADD_PATH_DELAY_TO_LOOKUP can share
    its AsyncResult without launching a duplicate synthesis.
    """
    if not LOGIC_IS_BUILT_IN_MUX(logic):
        return None, None
    cache_key = GET_CACHED_LOGIC_FILE_KEY(logic, parser_state)
    owner = cache_key_to_owner.setdefault(cache_key, logic.func_name)
    return cache_key, owner


def _mux_cache_key_is_width_collapsed():
    """True when a MUX's cache key collapses every width onto the bare "mux"
    string. True for PYRTL (measured: 1.640ns at every width 1..64, with the
    cache deleted -- not a caching artifact) and every tool that predates
    MUX_DELAY_KEY_BY_WIDTH, false for DEVICE_MODELS -- a real per-cell model
    is not necessarily flat, since a wider mux's select really does drive
    more sinks inside its own entity. --mux_delay_by_width/
    --no_mux_delay_by_width force either, for any tool, for A/B measurement.
    """
    by_width = MUX_DELAY_KEY_BY_WIDTH
    if by_width is None:
        by_width = SYN_TOOL is DEVICE_MODELS
    return not by_width


def GET_MUX_CACHE_KEY(width):
    """The cache key one width's 2:1 mux bank is stored under -- the same
    string GET_CACHED_LOGIC_FILE_KEY resolves a MUX Logic object to, from
    just the width, for a caller pricing a mux bank with no Logic object in
    hand. AUTO_FSM's operand multiplexers are that caller: ESTIMATE_SCHEDULE_
    AREA prices one from (ctype, fold count) during scheduling, before any
    MUX entity is ever built. Reconstructing this convention independently
    (rather than calling through to it) is exactly how a caller would go
    silently wrong under --no_mux_delay_by_width, where every width collapses
    onto the bare "mux" key."""
    if _mux_cache_key_is_width_collapsed():
        return "mux"
    return f"{C_TO_LOGIC.MUX_LOGIC_NAME}_uint{width}_t"


def GET_CACHED_LOGIC_FILE_KEY(logic, parser_state):
    # Default sanity
    key = logic.func_name

    if LOGIC_IS_BUILT_IN_MUX(logic):
        if _mux_cache_key_is_width_collapsed():
            key = "mux"
        else:
            # A 2:1 MUX over any N-bit packed type is physically the same
            # bank as MUX_uintN_t. Canonicalizing signed, float, enum, array,
            # and struct names lets every representation share the existing
            # integer cache.
            width = RAW_VHDL.GET_MUX_DATA_WIDTH(logic, parser_state)
            key = GET_MUX_CACHE_KEY(width)
    else:
        # MEM has var name - weird yo
        if SW_LIB.IS_MEM(logic):
            key = SW_LIB.GET_MEM_NAME(logic)

        func_name_includes_types = SW_LIB.FUNC_NAME_INCLUDES_TYPES(logic)
        if not func_name_includes_types:
            for input_port in logic.inputs:
                c_type = logic.wire_to_c_type[input_port]
                key += "_" + c_type
    # Hard safety cap: this key becomes a filename with a suffix appended
    # (".delay", ".timing.json"), so an unbounded number of input ports (each
    # contributing its own, possibly already-near-cap, c_type name above)
    # must never be allowed to exceed the filesystem's 255-byte filename
    # limit. 235 leaves generous headroom under 255 for the longest suffix.
    key = pypeline.collapse_overflow_name(key, logic.func_name, 235)
    return key


def GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state):
    key = GET_CACHED_LOGIC_FILE_KEY(logic, parser_state)
    file_path = GET_PATH_DELAY_CACHE_DIR(parser_state) + "/" + key + ".delay"
    return file_path


def GET_CACHED_PATH_DELAY_COMPONENTS_FILE_PATH(logic, parser_state):
    key = GET_CACHED_LOGIC_FILE_KEY(logic, parser_state)
    return GET_PATH_DELAY_CACHE_DIR(parser_state) + "/" + key + ".timing.json"


def GET_CACHED_PATH_DELAY(logic, parser_state):
    if not logic.is_c_built_in and C_TO_LOGIC.FUNC_IS_OP_OVERLOAD(logic.func_name):
        return None

    # Look in cache dir
    file_path = GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state)
    if os.path.exists(file_path):
        # print "Reading Cached Delay File:", file_path
        return float(open(file_path, "r").readlines()[0])

    return None


def GET_CACHED_PATH_DELAY_COMPONENTS(logic, parser_state, expected_delay_ns=None):
    """Read an optional V1 leaf timing-component cache sidecar.

    Old ``.delay`` caches intentionally have no sidecar and cleanly return
    None. When the experimental combinational planner model is selected its
    cache identity is distinct, so such a miss triggers one real measurement
    rather than silently mixing total-delay and combinational geometries.
    """

    if not logic.is_c_built_in and C_TO_LOGIC.FUNC_IS_OP_OVERLOAD(logic.func_name):
        return None
    path = GET_CACHED_PATH_DELAY_COMPONENTS_FILE_PATH(logic, parser_state)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            value = json.load(f)
        if value.get("schema_version") != 1:
            return None
        component_names = (
            "launch_clock_to_q_ns",
            "combinational_delay_ns",
            "setup_ns",
        )
        components = {
            name: float(value[name])
            for name in component_names
        }
        cached_total = float(value["path_delay_ns"])
        if expected_delay_ns is not None and not math.isclose(
            cached_total,
            expected_delay_ns,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            return None
        components["path_delay_ns"] = cached_total
        return components
    except (KeyError, OSError, TypeError, ValueError):
        return None


def _PATH_REPORT_DELAY_COMPONENTS(path_report):
    names = (
        "launch_clock_to_q_ns",
        "combinational_delay_ns",
        "setup_ns",
    )
    values = [getattr(path_report, name, None) for name in names]
    if any(value is None for value in values):
        return None
    components = {name: float(value) for name, value in zip(names, values)}
    components["path_delay_ns"] = float(path_report.path_delay_ns)
    component_sum = sum(components[name] for name in names)
    # DEVICE_MODELS text logs are rounded to 6 decimal places. Reject a
    # genuinely inconsistent decomposition but tolerate that serialization.
    if not math.isclose(
        component_sum,
        components["path_delay_ns"],
        rel_tol=1e-6,
        abs_tol=5e-6,
    ):
        return None
    return components


def _SET_LOGIC_DELAY_COMPONENTS(logic, components):
    logic.delay_components = dict(components) if components is not None else None
    logic.planner_delay = None
    if components is None:
        return
    combinational_ns = components["combinational_delay_ns"]
    planner_delay = int(combinational_ns * DELAY_UNIT_MULT)
    if combinational_ns > 0.0 and planner_delay == 0:
        planner_delay = 1
    logic.planner_delay = planner_delay


def _WRITE_CACHED_PATH_DELAY_COMPONENTS(logic, parser_state, components):
    if components is None:
        return
    path = GET_CACHED_PATH_DELAY_COMPONENTS_FILE_PATH(logic, parser_state)
    value = dict(components)
    value["schema_version"] = 1
    value["planner_weight"] = "combinational_delay_ns"
    with open(path, "w") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")


def GET_CACHED_LEAF_AREA_FILE_PATH(logic, parser_state):
    """Same relative path as this leaf's .delay file (shared cache key), in
    the separately-versioned cache/area tree. None when the active
    SYN_TOOL has no area source (GET_AREA_CACHE_DIR)."""
    cache_dir = GET_AREA_CACHE_DIR(parser_state)
    if cache_dir is None:
        return None
    key = GET_CACHED_LOGIC_FILE_KEY(logic, parser_state)
    return GET_CACHED_LEAF_AREA_FILE_PATH_BY_KEY(key, parser_state)


def GET_CACHED_LEAF_AREA_FILE_PATH_BY_KEY(key, parser_state):
    """Same cache path GET_CACHED_LEAF_AREA_FILE_PATH builds from a Logic
    object, from an already-known cache key directly -- for a shape priced
    with no Logic in hand. AUTO_FSM's operand multiplexers are the case this
    exists for: ESTIMATE_SCHEDULE_AREA prices one from (ctype, fold count)
    alone during scheduling, before any MUX entity is ever built, but its
    cache key (GET_MUX_CACHE_KEY(width), the same canonicalization
    GET_CACHED_LOGIC_FILE_KEY uses for a real MUX Logic) is knowable without
    one. None when the active SYN_TOOL has no area source
    (GET_AREA_CACHE_DIR)."""
    cache_dir = GET_AREA_CACHE_DIR(parser_state)
    if cache_dir is None:
        return None
    return cache_dir + "/" + key + ".area"


def _READ_CACHED_AREA_FILE(file_path):
    """(value, unit) parsed from one .area file, or None on a missing or
    malformed file, or a unit that disagrees with the active model's own
    unit (DEVICE_MODELS.AREA_UNIT) -- the whole point of writing the unit
    into the file is to make that mismatch loud instead of silently mixed."""
    if file_path is None or not os.path.exists(file_path):
        return None
    text = open(file_path).read().strip()
    try:
        value_str, unit = text.rsplit(" ", 1)
        value = float(value_str)
    except ValueError:
        return None
    if SYN_TOOL is DEVICE_MODELS and unit != DEVICE_MODELS.AREA_UNIT:
        return None
    return value, unit


def GET_CACHED_LEAF_AREA(logic, parser_state):
    """Read one leaf's cached area as (value, unit), or None on a cache
    miss: no area source, no file on disk, or malformed contents. See
    _READ_CACHED_AREA_FILE for the unit-mismatch handling."""
    if not logic.is_c_built_in and C_TO_LOGIC.FUNC_IS_OP_OVERLOAD(logic.func_name):
        return None
    return _READ_CACHED_AREA_FILE(
        GET_CACHED_LEAF_AREA_FILE_PATH(logic, parser_state)
    )


def GET_CACHED_LEAF_AREA_BY_KEY(key, parser_state):
    """GET_CACHED_LEAF_AREA's cache read, keyed directly rather than via a
    Logic object -- see GET_CACHED_LEAF_AREA_FILE_PATH_BY_KEY."""
    return _READ_CACHED_AREA_FILE(
        GET_CACHED_LEAF_AREA_FILE_PATH_BY_KEY(key, parser_state)
    )


def WRITE_CACHED_LEAF_AREA(logic, parser_state, value, unit):
    file_path = GET_CACHED_LEAF_AREA_FILE_PATH(logic, parser_state)
    if file_path is None:
        return
    cache_dir = os.path.dirname(file_path)
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    with open(file_path, "w") as f:
        f.write(f"{value} {unit}\n")


def _FUNC_NEEDS_SUBMODULE_DELAYS(func_name, parser_state):
    # Whose subtree delays must be resolved? Funcs with a sliceable path to
    # raw HDL (pipelining candidates) and funcs whose own delay is derived
    # from submodules (estimated - notably stateful Reg/Feedback containers,
    # which are never synthesized per-module, see FUNC_PATH_DELAY_IS_ESTIMABLE)
    import AUTO_PIPELINE

    if AUTO_PIPELINE.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(func_name, parser_state):
        return True
    logic = parser_state.FuncLogicLookupTable[func_name]
    return HIER_SYN_MODE != "full" and FUNC_PATH_DELAY_IS_ESTIMABLE(
        logic, parser_state
    )


def RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(func_names, parser_state):
    funcs_to_synth = []
    for func_name in func_names:
        if _FUNC_NEEDS_SUBMODULE_DELAYS(func_name, parser_state):
            func_logic = parser_state.FuncLogicLookupTable[func_name]
            # Recurse into submodules whose subtree delays are needed
            for sub_inst in func_logic.submodule_instances:
                sub_func_name = func_logic.submodule_instances[sub_inst]
                if _FUNC_NEEDS_SUBMODULE_DELAYS(sub_func_name, parser_state):
                    sub_funcs_to_synth = RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(
                        [sub_func_name], parser_state
                    )
                    for sub_func_to_synth in sub_funcs_to_synth:
                        if sub_func_to_synth not in funcs_to_synth:
                            funcs_to_synth.append(sub_func_to_synth)
            # Include self and all submodules for synth
            for sub_inst in func_logic.submodule_instances:
                sub_func_name = func_logic.submodule_instances[sub_inst]
                if sub_func_name not in funcs_to_synth:
                    funcs_to_synth.append(sub_func_name)
            if func_name not in funcs_to_synth:
                funcs_to_synth.append(func_name)
        # Old (full) mode: always synthesize main funcs too (their delay
        # seeded coarse sweep guesses). Leaf mode does not force this:
        # sliceable mains are cut subtree roots measured on demand by the
        # sweep's budget anchor, and a stateful main's whole-design zero clk
        # critical path (including regions about to be pipelined) feeds no
        # decision - synthesizing it wastes a near-whole-design run and its
        # number reads as a bogus "Design likely limited to X MHz" report
        if func_name in parser_state.main_mhz.keys() and HIER_SYN_MODE == "full":
            if func_name not in funcs_to_synth:
                funcs_to_synth.append(func_name)
    return funcs_to_synth


_FUNC_TO_INSTANTIATING_FUNCS_cache = None


def _GET_FUNC_TO_INSTANTIATING_FUNCS(parser_state):
    # Reverse map: func name -> set of func names that instantiate it
    global _FUNC_TO_INSTANTIATING_FUNCS_cache
    if _FUNC_TO_INSTANTIATING_FUNCS_cache is None:
        rv = {}
        for func_name, logic in parser_state.FuncLogicLookupTable.items():
            for sub_func_name in logic.submodule_instances.values():
                if sub_func_name not in rv:
                    rv[sub_func_name] = set()
                rv[sub_func_name].add(func_name)
        _FUNC_TO_INSTANTIATING_FUNCS_cache = rv
    return _FUNC_TO_INSTANTIATING_FUNCS_cache


_FUNC_IS_TOPMOST_COMB_cache = {}


def FUNC_IS_TOPMOST_COMB(func_name, parser_state):
    # The "measurement frontier": the largest fully-combinational subtrees.
    # A func with no Reg/Feedback anywhere below it, instantiated by a func
    # that DOES have state in its subtree (or being a main itself). Only for
    # such modules does a per-module synthesis run measure the input to
    # output through-delay (nothing internal to hide a path in) - so these
    # are the modules that get real synthesis to calibrate the estimated
    # delays of everything above them.
    if func_name in _FUNC_IS_TOPMOST_COMB_cache:
        return _FUNC_IS_TOPMOST_COMB_cache[func_name]
    logic = parser_state.FuncLogicLookupTable[func_name]
    rv = False
    if (
        len(logic.submodule_instances) > 0
        and logic.vhdl_module_text is None
        and func_name not in parser_state.func_marked_blackbox
        and not FUNC_SUBTREE_HAS_STATE(func_name, parser_state)
    ):
        if func_name in parser_state.main_mhz:
            rv = True
        else:
            parents = _GET_FUNC_TO_INSTANTIATING_FUNCS(parser_state).get(
                func_name, set()
            )
            rv = any(FUNC_SUBTREE_HAS_STATE(p, parser_state) for p in parents)
    _FUNC_IS_TOPMOST_COMB_cache[func_name] = rv
    return rv


_FUNC_SUBTREE_HAS_STATE_cache = {}


def FUNC_SUBTREE_HAS_STATE(func_name, parser_state):
    # Does this func or ANY submodule below it hold Reg/Feedback state?
    # (recursive: only a fully combinational subtree guarantees that a
    # per-module synthesis run measures input-to-output through delay -
    # any state inside, at any depth, means the reported critical path may
    # be an internal register-involved path instead)
    if func_name in _FUNC_SUBTREE_HAS_STATE_cache:
        return _FUNC_SUBTREE_HAS_STATE_cache[func_name]
    logic = parser_state.FuncLogicLookupTable[func_name]
    rv = logic.uses_nonvolatile_state_regs or len(logic.feedback_vars) > 0
    if not rv:
        for sub_func_name in logic.submodule_instances.values():
            if sub_func_name in parser_state.FuncLogicLookupTable:
                if FUNC_SUBTREE_HAS_STATE(sub_func_name, parser_state):
                    rv = True
                    break
    _FUNC_SUBTREE_HAS_STATE_cache[func_name] = rv
    return rv


def FUNC_PATH_DELAY_IS_ESTIMABLE(logic, parser_state):
    # Can this func's path delay be derived from its submodule delays
    # (zero clock pipeline map) instead of a real synthesis run?
    import AUTO_PIPELINE

    import AUTO_FSM

    if len(logic.submodule_instances) == 0:
        return False
    if logic.vhdl_module_text is not None:
        return False
    if logic.func_name in parser_state.func_marked_blackbox:
        return False
    # Explicitly forced to be estimated rather than synthesized. Used by
    # AUTO_FSM for the combinational passthrough it wraps a tagged function in
    # on the bootstrap pass: that wrapper looks exactly like a measurement
    # frontier (fully combinational, inside a stateful caller) and would
    # therefore get one whole-blob synthesis run -- of precisely the giant
    # parallel logic the user asked NOT to build, which for something like a
    # float64 polynomial does not finish in reasonable time. Nothing needs that
    # number: the scheduler works from the individual operations' delays
    # underneath, which are measured and cached as usual.
    if logic.func_name in getattr(parser_state, "func_force_estimated", ()):
        return True
    # Modules with Reg/Feedback state anywhere in their subtree: a
    # per-module synthesis run reports the module's internal critical path
    # (often register to register, possibly deep inside a nested FSM) - a
    # different quantity than the input to output through-delay that
    # dataflow slicing geometry needs. Only a fully combinational subtree
    # guarantees measured == through delay. So:
    # - stateful modules ON the estimate chain (an AUTO_PIPELINE tag
    #   somewhere below - slicing descends through them, ex. a dataflow
    #   core containing tagged stream pipelines) are ESTIMATED from their
    #   submodule delays, never synthesized;
    # - stateful modules NOT on the chain are atomic spans: slicing never
    #   enters them and only their span width is needed, so they get ONE
    #   whole-module synthesis at this topmost point and NOTHING inside
    #   them is synthesized or estimated (their interior delays feed no
    #   decision).
    if FUNC_SUBTREE_HAS_STATE(logic.func_name, parser_state):
        # "prim" mode: never synthesize any hierarchical module, stateful
        # or not -- estimate everything above true primitive leaves.
        if HIER_SYN_MODE == "prim":
            return True
        return AUTO_PIPELINE.FUNC_SUBTREE_HAS_AUTO_PIPELINE(
            logic.func_name, parser_state
        ) or AUTO_FSM.FUNC_SUBTREE_HAS_AUTO_FSM(logic.func_name, parser_state)
    # Fully combinational subtree from here down
    if FUNC_IS_TOPMOST_COMB(logic.func_name, parser_state):
        # The measurement frontier: this func gets ONE real synthesis run -
        # its measured input-to-output through delay calibrates the
        # estimated delays of everything above it (the "budget anchor" that
        # keeps first plans at the fewest-stages guess). Interior comb funcs
        # below stay estimated; the landscape rescales their relative
        # geometry into this measured total.
        # "prim" mode skips even this: no hierarchical module is ever
        # synthesized, including the measurement frontier.
        return HIER_SYN_MODE == "prim"
    if not AUTO_PIPELINE.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
        logic.func_name, parser_state
    ):
        return False
    return True


def SET_MEASURED_DELAY_FROM_REPORT(logic, parsed_timing_report, parser_state):
    # Parse a single path report from a per-func synthesis run and record
    # the measured delay on the logic object (+ disk cache for non-user code).
    # Sanity should be one path reported
    import AUTO_PIPELINE

    if len(parsed_timing_report.path_reports) > 1:
        print(
            "Too many paths reported!",
            logic.func_name,
            parsed_timing_report.orig_text,
        )
        sys.exit(-1)
    if len(parsed_timing_report.path_reports) == 0:
        print(
            "No timing paths reported!",
            logic.func_name,
            parsed_timing_report.orig_text,
        )
        sys.exit(-1)
    path_report = list(parsed_timing_report.path_reports.values())[0]
    if path_report.path_delay_ns is None:
        print(
            "Cannot parse synthesized path report for path delay ",
            logic.func_name,
        )
        print(parsed_timing_report.orig_text)
        sys.exit(-1)
    logic.delay = int(path_report.path_delay_ns * DELAY_UNIT_MULT)
    logic.delay_is_estimated = False
    delay_components = _PATH_REPORT_DELAY_COMPONENTS(path_report)
    _SET_LOGIC_DELAY_COMPONENTS(logic, delay_components)
    if logic.delay > 0 and AUTO_PIPELINE.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
        logic.func_name, parser_state
    ):
        print(
            f"{logic.func_name} Path delay (maybe to be pipelined): {path_report.path_delay_ns:.3f} ns"
        )
    # Sanity check multiplier is working
    if path_report.path_delay_ns > 0.0 and logic.delay == 0:
        print(
            "WARNING: Found",
            logic.func_name,
            "delay path of",
            path_report.path_delay_ns,
            "ns",
            "which is to small to represent. Increase delay multiplier?",
        )
        logic.delay = 1  # Set to smallest non zero for now?
    # Make adjustment for 0 LLs to have 0 delay
    if (SYN_TOOL is VIVADO) and path_report.logic_levels == 0:
        logic.delay = 0
    # Cache delay syn result if not user code, or if this is a built-in MUX
    # whose user type has a canonical packed-width cache identity.
    # (never cache estimated delays - cache holds measured values only)
    if LOGIC_PATH_DELAY_IS_CACHEABLE(logic, parser_state):
        filepath = GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state)
        PATH_DELAY_CACHE_DIR = GET_PATH_DELAY_CACHE_DIR(parser_state)
        if not os.path.exists(PATH_DELAY_CACHE_DIR):
            os.makedirs(PATH_DELAY_CACHE_DIR)
        f = open(filepath, "w")
        f.write(str(path_report.path_delay_ns))
        f.close()
        _WRITE_CACHED_PATH_DELAY_COMPONENTS(
            logic, parser_state, delay_components
        )
        # Cache leaf area alongside delay when the active tool measured one
        # -- only DEVICE_MODELS does (GET_AREA_CACHE_DIR is None for every
        # other SYN_TOOL, and their PathReport classes carry no area
        # attributes, so this is a no-op there via getattr's default).
        #
        # combinational_cell_area, deliberately NOT total_cell_area: an
        # isolated leaf is wrapped in dont_touch input/output registers
        # (VHDL.WRITE_LOGIC_TOP) purely to give it a register-to-register path
        # for STA, and total_cell_area includes them. For a narrow leaf that
        # harness dominates -- e.g. BIN_OP_AND_uint16_t_uint16_t's old
        # (AREA_MODEL_VERSION 1) total_cell_area of 2563.1232 um2 was 91%
        # harness flip-flop, 11.7x its real combinational area (218.8032
        # um2). combinational_cell_area (MEASURE_NETLIST_AREA already splits
        # it by each cell's own is_sequential flag) excludes them.
        area_value = getattr(path_report, "combinational_cell_area", None)
        area_unit = getattr(path_report, "area_unit", None)
        if area_value is not None and area_unit is not None:
            WRITE_CACHED_LEAF_AREA(logic, parser_state, area_value, area_unit)


def ESTIMATE_HIER_PATH_DELAYS(funcs_to_estimate, parser_state, quiet=False):
    # Derive hierarchical func delays from their zero clock pipeline maps
    # (critical topological path through already-known submodule delays).
    # funcs_to_estimate must be bottom up ordered (children before parents)
    # so each map only consumes already-resolved delays.
    import AUTO_PIPELINE

    for logic_func_name in funcs_to_estimate:
        logic = parser_state.FuncLogicLookupTable[logic_func_name]
        if logic_func_name not in parser_state.FuncToInstances:
            continue
        inst_name = list(parser_state.FuncToInstances[logic_func_name])[0]
        zero_added_clks_pipeline_map = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_PIPELINE_MAP(
            inst_name, logic, parser_state
        )
        logic.delay = zero_added_clks_pipeline_map.zero_clk_max_delay
        logic.delay_is_estimated = True
        logic.delay_components = None
        logic.planner_delay = None
        if not quiet:
            print(
                f"Function: {logic.func_name} estimated path delay: {logic.delay / DELAY_UNIT_MULT:.3f} ns (derived from submodules)"
            )
        parser_state.FuncLogicLookupTable[logic_func_name] = logic


def MEASURE_DELAYS(func_names, parser_state):
    # Fallback from estimated to measured delays: really synthesize the given
    # funcs (estimates only guide slice placement - when they prove inaccurate,
    # ex. because of optimizations that only happen in synthesis, the only way
    # to get the true delay is to synthesize, not estimate harder).
    # Afterwards re-estimates any still-estimated ancestor funcs with the new
    # measured child delays and invalidates stale pipeline map caches.
    # Funcs with Reg/Feedback anywhere below are skipped - NO exceptions:
    # their synthesized number is an internal critical path, not the
    # through-delay geometry needs (see FUNC_PATH_DELAY_IS_ESTIMABLE);
    # callers fall back to the estimated delay.
    import AUTO_PIPELINE

    funcs_to_measure = []
    for func_name in func_names:
        logic = parser_state.FuncLogicLookupTable[func_name]
        if len(logic.submodule_instances) > 0 and (
            HIER_SYN_MODE == "prim"
            or FUNC_SUBTREE_HAS_STATE(func_name, parser_state)
        ):
            # "prim" mode: no hierarchical module is ever (re-)synthesized,
            # only true primitive leaves -- callers fall back to the estimate.
            continue
        if logic.delay is None or logic.delay_is_estimated:
            if func_name in parser_state.FuncToInstances:
                funcs_to_measure.append(func_name)
    if len(funcs_to_measure) == 0:
        return
    print(
        "Replacing estimated delays with measured synthesis results for:",
        ", ".join(funcs_to_measure),
        flush=True,
    )
    TimingParamsLookupTable = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
    my_thread_pool = ThreadPool(processes=GET_NUM_PROCESSES())
    func_name_to_async_result = {}
    for func_name in funcs_to_measure:
        logic = parser_state.FuncLogicLookupTable[func_name]
        inst_name = list(parser_state.FuncToInstances[func_name])[0]
        print(
            "Synthesizing function:",
            func_name + FUNC_SRC_LOC_STR(parser_state, func_name),
            flush=True,
        )
        func_name_to_async_result[func_name] = my_thread_pool.apply_async(
            SYN_TOOL.SYN_AND_REPORT_TIMING,
            (inst_name, logic, parser_state, TimingParamsLookupTable),
        )
    for func_name, my_async_result in func_name_to_async_result.items():
        logic = parser_state.FuncLogicLookupTable[func_name]
        parsed_timing_report = my_async_result.get()
        SET_MEASURED_DELAY_FROM_REPORT(logic, parsed_timing_report, parser_state)
        print(
            f"Function: {logic.func_name} measured path delay: {logic.delay / DELAY_UNIT_MULT:.3f} ns"
        )
        parser_state.FuncLogicLookupTable[func_name] = logic
    # Pipeline maps built from the old estimated delays are stale now
    AUTO_PIPELINE._GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache.clear()
    # Re-estimate remaining estimated funcs bottom up with updated child delays
    all_funcs_ordered = RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(
        parser_state.main_mhz.keys(), parser_state
    )
    still_estimated = [
        f
        for f in all_funcs_ordered
        if parser_state.FuncLogicLookupTable[f].delay_is_estimated
    ]
    ESTIMATE_HIER_PATH_DELAYS(still_estimated, parser_state, quiet=True)


def ADD_PATH_DELAY_TO_LOOKUP(parser_state, root_func_names=None):
    # root_func_names: measure only the subtrees of these funcs instead of the
    # whole design's mains (+ AUTO_FSM muxes) -- used by builds that never sweep
    # but must still place fixed AUTO_PIPELINE latency= registers
    # (BUILD_FIXED_AUTO_PIPELINE_TIMING_PARAMS).
    # Make sure synthesis tool is set
    import AUTO_PIPELINE

    import AUTO_FSM

    PART_SET_TOOL(parser_state.part)

    print("Synthesizing before pipelining to get path delays...", flush=True)
    print("", flush=True)
    TimingParamsLookupTable = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
    multimain_timing_params = AUTO_PIPELINE.MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable

    # Re-write black box modules that are no longer in final state starting throughput sweep
    WRITE_BLACK_BOX_FILES(parser_state, multimain_timing_params, False)

    # Get the functions that need to be synthed for path delay
    if root_func_names is not None:
        funcs_to_synth = []
        for func_name in RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(
            root_func_names, parser_state
        ) + list(root_func_names):
            if func_name not in funcs_to_synth:
                funcs_to_synth.append(func_name)
        _auto_fsm_muxes = []
    else:
        funcs_to_synth = RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(
            parser_state.main_mhz.keys(), parser_state
        )
        # ...plus AUTO_FSM's operand multiplexers, which the walk above cannot
        # reach (see _AUTO_FSM_MUX_ENTITIES). Their own subtrees first, so the
        # list stays bottom-up ordered.
        _auto_fsm_muxes = sorted(AUTO_FSM._AUTO_FSM_MUX_ENTITIES(parser_state))
    if _auto_fsm_muxes:
        for extra in RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(
            _auto_fsm_muxes, parser_state
        ) + _auto_fsm_muxes:
            if extra not in funcs_to_synth:
                funcs_to_synth.append(extra)

    # Record stats on functions with globals
    main_to_min_mhz = {}
    main_to_min_mhz_func_name = {}

    # Run multiple syn runs in parallel
    my_thread_pool = ThreadPool(processes=GET_NUM_PROCESSES())
    func_name_to_async_result = {}
    func_name_to_async_owner = {}
    mux_cache_key_to_async_owner = {}
    func_names_done_so_far = set()
    # Hierarchical funcs deferred for delay estimation from submodule delays
    # instead of a real syn run (leaf-only syn mode). funcs_to_synth is bottom
    # up ordered (children before parents) so appending preserves that order.
    funcs_to_estimate = []

    # Start synth runs
    for logic_func_name in funcs_to_synth:
        # print("func to synth",logic_func_name)
        # Get logic
        logic = parser_state.FuncLogicLookupTable[logic_func_name]
        # Any inst will do, skip func if was never used as instance
        inst_name = None
        if logic_func_name in parser_state.FuncToInstances:
            inst_name = list(parser_state.FuncToInstances[logic_func_name])[0]

        # Try to model the path delay
        modeled_path_delay = None
        if DEVICE_MODELS.part_supported(parser_state.part):
            op_and_widths = DEVICE_MODELS.func_name_to_op_and_widths(logic.func_name)
            if op_and_widths is not None:
                op, widths = op_and_widths
                modeled_path_delay = DEVICE_MODELS.estimate_int_timing(op, widths)
        # Try to get cached path delay
        cached_path_delay = GET_CACHED_PATH_DELAY(logic, parser_state)
        cached_delay_components = None
        if cached_path_delay is not None:
            cached_delay_components = GET_CACHED_PATH_DELAY_COMPONENTS(
                logic, parser_state, cached_path_delay
            )
            if (
                USE_COMBINATIONAL_PLANNER_WEIGHTS
                and SYN_TOOL is DEVICE_MODELS
                and cached_delay_components is None
            ):
                # The experimental planner cache identity requires timing
                # components. A lone legacy/partial .delay file cannot supply
                # its geometry, so measure once and populate the sidecar.
                cached_path_delay = None
            if (
                SYN_TOOL is DEVICE_MODELS
                and cached_path_delay is not None
                and LOGIC_PATH_DELAY_IS_CACHEABLE(logic, parser_state)
                and GET_CACHED_LEAF_AREA(logic, parser_state) is None
            ):
                # Leaf area is a free byproduct of the exact same synthesis
                # run that produces delay (DEVICE_MODELS._run_synth_and_sta
                # measures both from one mapped netlist), but a warm delay
                # cache short-circuits before that run ever happens. Force
                # one real synthesis so a cold cache/area entry gets filled
                # exactly the way a cold cache/delay entry would --
                # mirrors the combinational-planner-weights clause just
                # above, which does the same thing for a missing sidecar.
                cached_path_delay = None
        # Prefer cache over model
        if cached_path_delay is not None:
            logic.delay = int(cached_path_delay * DELAY_UNIT_MULT)
            _SET_LOGIC_DELAY_COMPONENTS(logic, cached_delay_components)
            print(
                f"Function: {logic.func_name} cached path delay: {cached_path_delay:.3f} ns"
            )
            if cached_path_delay > 0.0 and logic.delay == 0:
                print(
                    "WARNING: Found cached",
                    logic_func_name,
                    "delay path of",
                    cached_path_delay,
                    "ns",
                    "which is to small to represent. Increase delay multiplier?",
                )
                logic.delay = 1  # Set to smallest non zero for now?
        elif modeled_path_delay is not None:
            logic.delay = int(modeled_path_delay * DELAY_UNIT_MULT)
            _SET_LOGIC_DELAY_COMPONENTS(logic, None)
            print(
                f"Function: {logic.func_name} modeled path delay: {modeled_path_delay:.3f} ns"
            )
        # Then check for known delays
        elif LOGIC_IS_ZERO_DELAY(logic, parser_state, allow_none_delay=True):
            logic.delay = 0
            _SET_LOGIC_DELAY_COMPONENTS(logic, None)

        # Prepare for syn to determine
        if logic.delay is None:
            if HIER_SYN_MODE != "full" and FUNC_PATH_DELAY_IS_ESTIMABLE(
                logic, parser_state
            ):
                # Hierarchical func on the pipelining path: derive delay from
                # submodule delays after leaf syn results are in (see below).
                # Estimates are guidance for slice placement only - full design
                # synthesis during the throughput sweep remains the ground truth,
                # and MEASURE_DELAYS() is the fallback when estimates are off.
                funcs_to_estimate.append(logic_func_name)
            else:
                cache_key, owner = CLAIM_MUX_PATH_DELAY_SYNTH_OWNER(
                    logic, parser_state, mux_cache_key_to_async_owner
                )
                if owner is not None and owner != logic_func_name:
                    func_name_to_async_result[logic_func_name] = (
                        func_name_to_async_result[owner]
                    )
                    func_name_to_async_owner[logic_func_name] = owner
                    print(
                        f"Sharing MUX path-delay synthesis for {logic.func_name} "
                        f"with {owner} (cache key {cache_key})",
                        flush=True,
                    )
                else:
                    # Run real syn in parallel
                    print(
                        "Synthesizing function:",
                        logic.func_name + FUNC_SRC_LOC_STR(parser_state, logic.func_name),
                        flush=True,
                    )
                    # Start Syn
                    my_async_result = my_thread_pool.apply_async(
                        SYN_TOOL.SYN_AND_REPORT_TIMING,
                        (inst_name, logic, parser_state, TimingParamsLookupTable),
                    )
                    func_name_to_async_result[logic_func_name] = my_async_result
                    func_name_to_async_owner[logic_func_name] = logic_func_name
        else:
            func_names_done_so_far.add(logic_func_name)

    # Finish parallel syns
    for logic_func_name in funcs_to_synth:
        # Get logic
        logic = parser_state.FuncLogicLookupTable[logic_func_name]
        func_names_done_so_far.add(logic_func_name)
        if logic_func_name in func_name_to_async_result:
            # Get result
            my_async_result = func_name_to_async_result[logic_func_name]
            print(
                f"Function {len(func_names_done_so_far)}/{len(funcs_to_synth)}, elapsed time {str(datetime.timedelta(seconds=(timer() - START_TIME)))}..."
            )
            owner = func_name_to_async_owner[logic_func_name]
            print("...Waiting on synthesis for:", owner, flush=True)
            # TODO better than simple loop doing .get() on each and waiting some
            parsed_timing_report = my_async_result.get()
            SET_MEASURED_DELAY_FROM_REPORT(logic, parsed_timing_report, parser_state)

        # Syn results are delay and clock
        # Try to communicate if is a problem path that cant be auto-pipelined
        # (delay is None here for funcs deferred to estimation below - they are
        #  all on the pipelining path so would not be reported here anyway)
        if (
            logic.delay is not None
            and logic.delay > 0
            and not AUTO_PIPELINE.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
                logic.func_name, parser_state
            )
        ):
            path_delay_ns = logic.delay / DELAY_UNIT_MULT
            mhz = 1000.0 / path_delay_ns
            print(
                f"{logic_func_name} FMAX: {mhz:.3f} MHz ({path_delay_ns:.3f} ns path delay)"
            )
            # Record worst non slicable logic
            insts = list(parser_state.FuncToInstances[logic_func_name])
            for inst in insts:
                main_inst = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
                    inst, parser_state
                )
                if main_inst not in main_to_min_mhz:
                    main_to_min_mhz[main_inst] = 9999
                if mhz < main_to_min_mhz[main_inst]:
                    main_to_min_mhz_func_name[main_inst] = logic.func_name
                    main_to_min_mhz[main_inst] = mhz

        # Save logic with delay into lookup (should not be needed)
        parser_state.FuncLogicLookupTable[logic_func_name] = logic

    # Estimate hierarchical func delays from submodule delays (leaf-only mode).
    # All real syn results are in at this point; bottom up order resolves
    # estimated children before estimated parents.
    ESTIMATE_HIER_PATH_DELAYS(funcs_to_estimate, parser_state)

    # Write out final pictures requiring all delays in hierarchy to be computed above
    for logic_func_name in funcs_to_synth:
        logic = parser_state.FuncLogicLookupTable[logic_func_name]
        if logic.delay is None:
            print("None delay for func to synth?", logic_func_name)
        # What if do want pipeline map for something that will never be pipelined? --synth_all?
        if not AUTO_PIPELINE.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL(
            logic.func_name, parser_state
        ):
            continue
        if len(logic.submodule_instances) <= 0:
            continue
        if logic.vhdl_module_text is not None:
            continue
        if logic.delay <= 0:
            continue
        # Any inst will do, skip func if was never used as instance
        if logic_func_name not in parser_state.FuncToInstances:
            continue
        inst_name = list(parser_state.FuncToInstances[logic_func_name])[0]
        # TODO make pipeline map return empty instead of check?
        zero_added_clks_pipeline_map = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_PIPELINE_MAP(
            inst_name, logic, parser_state
        )  # use inst_logic since timing params are by inst
        zero_clk_pipeline_map_str = str(zero_added_clks_pipeline_map)
        out_dir = GET_OUTPUT_DIRECTORY(logic)
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        out_path = out_dir + "/pipeline_map.log"
        f = open(out_path, "w")
        f.write(zero_clk_pipeline_map_str)
        f.close()
        # Large fine-grained designs can have thousands of functions; opt-in
        # QoR probes may skip diagnostic graph rendering without changing HDL.
        if os.environ.get("PIPELINEC_INTERNAL_SKIP_PIPELINE_MAP_PNG") != "1":
            zero_added_clks_pipeline_map.write_png(out_dir, parser_state)

    # Report worst timing modules
    for main_inst in main_to_min_mhz if root_func_names is None else ():
        min_mhz = main_to_min_mhz[main_inst]
        mhz = parser_state.main_mhz[main_inst]
        if mhz is not None and mhz > min_mhz:
            min_mhz_func_name = main_to_min_mhz_func_name[main_inst]
            print(
                f"Design likely limited to ~{min_mhz:.3f} MHz due to function: "
                f"{min_mhz_func_name}{FUNC_SRC_LOC_STR(parser_state, min_mhz_func_name)}"
            )
    WRITE_MODULE_INSTANCES_REPORT_BY_DELAY_USAGE(parser_state)

    return parser_state


def WRITE_MODULE_INSTANCES_REPORT_BY_DELAY_USAGE(parser_state):
    # print(
    #    "Updating modules instances log to list longest delay, most used modules only..."
    # )
    top_n_delay_usage = 10

    # Calc delay*n uses
    func_to_delay_usage = {}
    for func_name in parser_state.FuncToInstances:
        func_logic = parser_state.FuncLogicLookupTable[func_name]
        if func_logic.delay is None:
            continue
        func_path_delay_ns = float(func_logic.delay) / DELAY_UNIT_MULT
        n_instances = len(parser_state.FuncToInstances[func_name])
        delay_usage = func_path_delay_ns * n_instances
        func_to_delay_usage[func_name] = delay_usage

    # Print top N funcs
    text = ""
    for n in range(0, top_n_delay_usage):
        if len(func_to_delay_usage) <= 0:
            break
        max_delay_usage = max(func_to_delay_usage.values())
        for func_name in sorted(func_to_delay_usage):
            func_logic = parser_state.FuncLogicLookupTable[func_name]
            func_path_delay_ns = float(func_logic.delay) / DELAY_UNIT_MULT
            instances = sorted(parser_state.FuncToInstances[func_name])
            n_instances = len(instances)
            delay_usage = func_path_delay_ns * n_instances
            if delay_usage >= max_delay_usage:
                func_to_delay_usage.pop(func_name, None)
                text += f"{func_name} {n_instances} instances:\n"
                for instance in instances:
                    text += instance.replace(C_TO_LOGIC.SUBMODULE_MARKER, "/") + "\n"
                text += "\n"

    out_file = SYN_OUTPUT_DIRECTORY + "/module_instances.log"
    f = open(out_file, "w")
    f.write(text)
    f.close()

    WRITE_NAME_INDEX_LOG(parser_state)


def WRITE_NAME_INDEX_LOG(parser_state):
    """Index logical/emitted names, complete source descriptions and call sites.

    Includes nested type origins, generated source files, timing variants and
    per-scope wire/hierarchy mappings. Also called for --no_synth. Pypeline
    side-tables are optional; classic C builds retain their source/timing index.
    """
    name_full = getattr(parser_state, "pypeline_name_full", {})
    type_canonical = getattr(parser_state, "pypeline_type_canonical", {})
    hash_ext_info = getattr(parser_state, "pypeline_hash_ext_info", {})
    names = getattr(parser_state, "pypeline_emission_names", None)

    lines = ["ENTITIES"]
    for func_name in sorted(parser_state.FuncToInstances.keys()):
        logic = parser_state.FuncLogicLookupTable.get(func_name)
        if logic is None:
            continue
        loc = None
        ast_meta = getattr(logic, "ast_meta", None)
        if ast_meta is not None:
            loc = f"{ast_meta.src_file}:{ast_meta.line}"
            if ast_meta.col is not None:
                loc += f":{ast_meta.col}"
        full = name_full.get(func_name)
        if loc is None and full is None:
            continue  # nothing decodable to report (e.g. a plain built-in)
        lines.append(f"  {func_name}")
        if names is not None:
            lines.append(f"    vhdl:   {names.identifier(func_name)}")
        if loc is not None:
            lines.append(f"    source: {loc}")
        if full is not None:
            lines.append(f"    full:   {full}")
        lines.append(f"    insts:  {len(parser_state.FuncToInstances[func_name])}")

    lines.append("")
    lines.append("TYPES")
    for type_name in sorted(type_canonical.keys()):
        lines.append(f"  {type_name}")
        lines.append(f"    full:   {type_canonical[type_name]}")

    if names is not None:
        lines.extend(["", "SOURCE DESCRIPTIONS"])
        seen_descriptions = set()

        def describe(info, indent="    "):
            key = (info.identity, info.source, info.line, info.kind)
            lines.append(f"{indent}{info.kind}: {info.render()}")
            lines.append(
                f"{indent}source: {info.source}:{info.line} ({info.module}.{info.qualname})"
            )
            if key in seen_descriptions:
                return
            seen_descriptions.add(key)
            lines.append(f"{indent}identity: {info.identity}")
            for label, child in info.params + info.fields:
                if hasattr(child, "render"):
                    lines.append(f"{indent}{label}:")
                    describe(child, indent + "  ")

        for raw, infos in sorted(names.descriptions.items()):
            lines.append(f"  {names.identifier(raw)}")
            lines.append(f"    logical: {raw}")
            for info in sorted(infos, key=lambda n: (n.source, n.line, n.qualname)):
                describe(info)

        lines.extend(["", "INSTANCES AND WIRES"])
        for func_name in sorted(parser_state.FuncToInstances):
            logic = parser_state.FuncLogicLookupTable[func_name]
            lines.append(f"  scope: {names.identifier(func_name)}")
            for inst in sorted(parser_state.FuncToInstances[func_name]):
                path = "/".join(
                    VHDL.WIRE_TO_VHDL_NAME(t, parser_state)
                    for t in inst.split(C_TO_LOGIC.SUBMODULE_MARKER)
                )
                lines.append(f"    hierarchy: {path}")
            for inst, child in sorted(logic.submodule_instances.items()):
                lines.append(
                    f"    instance: {VHDL.WIRE_TO_VHDL_NAME(inst, parser_state)} -> {names.identifier(child)}"
                )
                for origin in sorted(
                    logic.submodule_instance_to_source_origins.get(inst, ())
                ):
                    source, line, col, end_line, end_col = origin
                    lines.append(
                        f"      source: {source}:{line}:{col}-{end_line}:{end_col}"
                    )
            for wire in sorted(logic.wires):
                lines.append(f"    wire: {VHDL.WIRE_TO_VHDL_NAME(wire, parser_state)}")
                lines.append(f"      logical: {wire}")
                lines.append(f"      type: {logic.wire_to_c_type.get(wire, '?')}")

        lines.extend(["", "EMITTED IDENTIFIERS"])
        for emitted, (raw, full) in sorted(names.full.items()):
            lines.append(f"  {emitted}")
            lines.append(f"    logical: {raw}")
            lines.append(f"    full: {full}")

    lines.append("")
    lines.append("GENERATED SOURCES")
    try:
        gen_dir = SYN_OUTPUT_DIRECTORY + "/pypeline_generated_source"
        written = pypeline.dump_generated_sources(gen_dir)
        for gen_path in sorted(written):
            lines.append(f"  {gen_path}")
    except Exception as e:
        lines.append(f"  (failed to dump generated sources: {e})")

    lines.append("")
    lines.append("PIPELINE VARIANTS")
    for hash_ext in sorted(hash_ext_info.keys()):
        owner, detail = hash_ext_info[hash_ext]
        lines.append(f"  {hash_ext} -> {owner}, {detail}")

    out_file = SYN_OUTPUT_DIRECTORY + "/name_index.log"
    with open(out_file, "w") as f:
        f.write("\n".join(lines) + "\n")


# Generalizing is a bad thing to do
# Abstracting is something more


# Should this branch to call syn tool specific includes of like ieee files?
# returns vhdl_files_txt,top_entity_name
def GET_VHDL_FILES_TCL_TEXT_AND_TOP(
    multimain_timing_params, parser_state, inst_name=None, is_final_top=False
):
    # Read in vhdl files with a single (faster than multiple) read_vhdl
    files_txt = ""

    # Built in src/vhdl #TODO just auto add every file in dir
    files_txt += SYN_OUTPUT_DIRECTORY + "/" + "built_in/pipelinec_fifo_fwft.vhd" + " "
    files_txt += (
        SYN_OUTPUT_DIRECTORY + "/" + "built_in/pipelinec_async_fifo_fwft.vhd" + " "
    )

    # C defined structs
    files_txt += SYN_OUTPUT_DIRECTORY + "/" + "c_structs_pkg" + VHDL.VHDL_PKG_EXT + " "

    # Clocking crossing if needed

    if not inst_name and len(parser_state.clk_cross_var_info) > 0:
        # Multimain needs clk cross entities
        # Clock crossing entities
        files_txt += (
            SYN_OUTPUT_DIRECTORY + "/" + "clk_cross_entities" + VHDL.VHDL_FILE_EXT + " "
        )

    needs_global_t = (
        VHDL.NEEDS_GLOBAL_WIRES_VHDL_PACKAGE(parser_state) and not inst_name
    )  # is multimain
    if inst_name:
        # Does inst need clk cross?
        Logic = parser_state.LogicInstLookupTable[inst_name]
        needs_global_to_module = VHDL.LOGIC_NEEDS_GLOBAL_TO_MODULE(
            Logic, parser_state
        )  # , multimain_timing_params.TimingParamsLookupTable)
        needs_module_to_global = VHDL.LOGIC_NEEDS_MODULE_TO_GLOBAL(
            Logic, parser_state
        )  # , multimain_timing_params.TimingParamsLookupTable)
        needs_global_t = needs_global_to_module or needs_module_to_global
    if needs_global_t:
        # Clock crossing record
        files_txt += (
            SYN_OUTPUT_DIRECTORY + "/" + "global_wires_pkg" + VHDL.VHDL_PKG_EXT + " "
        )

    # Top not shared
    top_entity_name = VHDL.GET_TOP_ENTITY_NAME(
        parser_state, multimain_timing_params, inst_name, is_final_top
    )
    if inst_name:
        Logic = parser_state.LogicInstLookupTable[inst_name]
        output_directory = GET_OUTPUT_DIRECTORY(Logic)
        files_txt += output_directory + "/" + top_entity_name + VHDL.VHDL_FILE_EXT + " "
    else:
        # Entity and file name
        filename = top_entity_name + VHDL.VHDL_FILE_EXT
        files_txt += (
            SYN_OUTPUT_DIRECTORY + "/" + TOP_LEVEL_MODULE + "/" + filename + " "
        )

    # Write all entities starting at this inst/multi main
    inst_names = set()
    if inst_name:
        inst_names = set([inst_name])
    else:
        inst_names = set(parser_state.main_mhz.keys())

    entities_so_far = set()
    while len(inst_names) > 0:
        next_inst_names = set()
        # Sets are useful for frontier deduplication, but their iteration
        # order is process-randomized. Keep the ordered VHDL input list
        # deterministic: it participates in synthesis cache identity and two
        # byte-identical designs must not re-map merely because siblings were
        # discovered in a different hash order.
        for inst_name_i in sorted(inst_names):
            logic_i = parser_state.LogicInstLookupTable[inst_name_i]
            # Write file text
            # ONly write non vhdl
            if (
                logic_i.is_vhdl_func
                or logic_i.is_vhdl_expr
                or logic_i.func_name == C_TO_LOGIC.VHDL_FUNC_NAME
            ):
                continue
            # Dont write clock cross
            if logic_i.is_clock_crossing:
                continue
            entity_filename = (
                VHDL.GET_ENTITY_NAME(
                    inst_name_i,
                    logic_i,
                    multimain_timing_params.TimingParamsLookupTable,
                    parser_state,
                )
                + ".vhd"
            )
            if entity_filename not in entities_so_far:
                entities_so_far.add(entity_filename)
                # Include entity file for this functions slice variant
                syn_output_directory = GET_OUTPUT_DIRECTORY(logic_i)
                files_txt += syn_output_directory + "/" + entity_filename + " "

            # Add submodules as next inst_names
            for submodule_inst in sorted(logic_i.submodule_instances):
                full_submodule_inst_name = (
                    inst_name_i + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                )
                next_inst_names.add(full_submodule_inst_name)

        # Use next insts as current
        inst_names = set(next_inst_names)

    return files_txt, top_entity_name
