#!/usr/bin/env python3

import copy
import datetime
import glob
import hashlib
import math
import os
import pickle
import sys
from distutils.dir_util import copy_tree
from multiprocessing.pool import ThreadPool
from pathlib import Path
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
from utilities import REPO_ABS_DIR

START_TIME = timer()

OUTPUT_DIR_NAME = "pipelinec_output"
SYN_OUTPUT_DIRECTORY = None  # Auto created with pid and filename or from user
TOP_LEVEL_MODULE = None  # Holds the name of the top level module
SYN_TOOL = None  # Attempts to figure out from part number
CONVERT_FINAL_TOP_VERILOG = False  # Flag for final top level converison to verilog
DO_SYN_FAIL_SIM = False  # Start simulation if synthesis fails
WRITE_AXIS_XO_FILE = False

# Welcome to the land of magic numbers
#   "But I think its much worse than you feared" Modest Mouse - I'm Still Here

# Artix 7 100t full RT:
# Coarse sweep BEST IS sliced 494 clocks, get 490 clock pipeline at 153MHz
# Coarse (not sweep) gets to 504 slice, 500 clk, 10 clks off fine for now...
# With BEST_GUESS_MUL_MAX = 10.0, COARSE_SWEEP_MULT_MAX = 1.5, not skipping higher fmax to compensate
# RT pixel_logic
# HIER_SWEEP_MULT_MIN   latency   # top runs
# 0.125                 470       32
# 0.25                  470       24
# 0.5                   419       7
# 0.75                  421       13
# 1.0                   423       31
# 1.0625                413       31
# 1.125                 370       5
# 1.25                  370       5
# 1.5                   370       5
# 1.75                  370       5
# 1.875                 371       4
# 1.9375                350       4
# 1.96875               350       4
# 1.984375              585       9
# 2.0                   585       9
# 2.25                  493       8
# 2.5                   509       7
# === After Recent updates
# 2.0?                  536       5
# 1.9375                343       8
# 1.5                   368       8
# 1.087                 368
# 1.0                   417       15
# 0.5                   ~417      ~45 reaches 1.0x start after ~33runs
# 0.0                   ~417      ~65 reaches 1.0x after ~55 runs

# ECP5 Full RT:
# Coarse sweep gets to: 75 clocks
# Coarse (not sweep) gets to 81 clocks
# HIER_SWEEP_MULT_MIN   latency         # top runs
# 2.0                   80+clks never finished ~24hrs hash=5c32
# 1.9375                ^same
# 1.5                   83+clks never finished ~12 hours hash=a39f
# 1.0                   63+clks never finished ~12 hrs hash=e748
# 0.5                   45+clks never finished ~12 hr hash=22ef
# 0.25                  60+clks never finished 12+hours hash=5237
# 0.181                 79+clks never finished 12+hours hash=222f
# 0.125                 ^same
# 0.09375               ^same
# 0.078125              \/same
# 0.06780026720106881
# 0.0625                66              4   ^ ends up at slighty higher after failing coarse
# 0.046875              ^same
# 0.03125               \/same
# 0.0                   70              2   # wow

# Tool increases HIER_SWEEP_MULT_MIN if it has trouble
# i.e. tries to pipeline smaller/less logic modules, easier task
# Starting off too large is bad - no way to recover

# Target pipelining at minimum at modules of period = target/MULT
#   0.0 -> start w/ largest/top level modules first
#   0.5 -> 2 times the target period (not meeting timing),
#   2.0 -> 1/2 the target period (easily meets timing)
HIER_SWEEP_MULT_MIN = None  # Cmd line arg sets
HIER_SWEEP_MULT_INC = 0.001  # Intentionally very small, sweep already tries to make largest possible steps
MAX_N_WORSE_RESULTS_MULT = 16  # Multiplier for how many times failing to improve before moving on? divided by total latnecy
BEST_GUESS_MUL_MAX = 5.0  # Multiplier limit on top down register insertion coarsly during middle out sweep
MAX_ALLOWED_LATENCY_MULT = 5.0  # Multiplier limit for individual module coarse register insertion coarsely, similar same as BEST_GUESS_MUL_MAX?
COARSE_SWEEP_MULT_INC = 0.1  # Multiplier increment for how many times fmax to try for compensating not meeting timing
COARSE_SWEEP_MULT_MAX = 1.0  # ==1.0 disables trying to pipeline to fake higher fmax, Max multiplier for internal fmax
MAX_CLK_INC_RATIO = 1.25  # Multiplier for how any extra clocks can be added ex. 1.25 means 25% more stages max
DELAY_UNIT_MULT = 10.0  # Timing is reported in nanoseconds. Multiplier to convert that time into integer units (nanosecs, tenths, hundreds of nanosecs)
INF_MHZ = 1000  # Impossible timing goal
INF_HIER_MULT = 999999.9  # Needed?
SLICE_EPSILON_MULTIPLIER = 5  # 6.684491979 max/best? # Constant used to determine when slices are equal. Higher=finer grain slicing, lower=similar slices are said to be equal
SLICE_STEPS_BETWEEN_REGS = 3  # Multiplier for how narrow to start off the search for better timing. Higher=More narrow start, Experimentally 2 isn't enough, slices shift <0 , > 1 easily....what?


def PART_SET_TOOL(part_str, allow_fail=False):
    global SYN_TOOL
    if SYN_TOOL is None:
        # Try to guess synthesis tool based on part number
        # Hacky for now...
        if part_str is None:
            if allow_fail:
                return
            else:
                # Try to default to part-less estimates from pyrtl?
                if PYRTL.IS_INSTALLED():
                    SYN_TOOL = PYRTL
                    print("Defaulting to pyrtl based timing estimates...")
                else:
                    print(
                        "Need to set FPGA part somewhere in the code to continue with synthesis tool support!"
                    )
                    print('Ex. #pragma PART "LFE5U-85F-6BG381C"')
                    sys.exit(0)
        else:
            if part_str.lower().startswith("xc"):
                SYN_TOOL = VIVADO
                if os.path.exists(VIVADO.VIVADO_PATH):
                    print("Vivado:", VIVADO.VIVADO_PATH, flush=True)
                else:
                    if not allow_fail:
                        raise Exception("Vivado install not found!")
            elif (
                part_str.lower().startswith("ep")
                or part_str.lower().startswith("10c")
                or part_str.lower().startswith("5c")
            ):
                SYN_TOOL = QUARTUS
                if os.path.exists(QUARTUS.QUARTUS_PATH):
                    print("Quartus:", QUARTUS.QUARTUS_PATH, flush=True)
                else:
                    if not allow_fail:
                        raise Exception("Quartus install not found!")
            elif part_str.lower().startswith("lfe5u") or part_str.lower().startswith(
                "ice"
            ):
                # Diamond fails to create proj for UMG5G part?
                if "um5g" in part_str.lower():
                    SYN_TOOL = OPEN_TOOLS
                # Default to open tools for non ice40 (nextpnr not support ooc mode yet)
                elif "ice40" not in part_str.lower():
                    SYN_TOOL = OPEN_TOOLS
                else:
                    if os.path.exists(DIAMOND.DIAMOND_PATH):
                        SYN_TOOL = DIAMOND
                        print("Diamond:", DIAMOND.DIAMOND_PATH, flush=True)
                    else:
                        if not allow_fail:
                            raise Exception("Diamond install not found!")
                        # But also fall back to open tools for ice40 if no Diamond
                        SYN_TOOL = OPEN_TOOLS
            elif part_str.upper().startswith("T8") or part_str.upper().startswith("TI"):
                SYN_TOOL = EFINITY
                if os.path.exists(EFINITY.EFINITY_PATH):
                    print("Efinity:", EFINITY.EFINITY_PATH, flush=True)
                else:
                    if not allow_fail:
                        raise Exception("Efinity install not found!")
            elif part_str.upper().startswith("GW"):
                SYN_TOOL = GOWIN
                if os.path.exists(GOWIN.GOWIN_PATH):
                    print("Gowin:", GOWIN.GOWIN_PATH, flush=True)
                else:
                    if not allow_fail:
                        raise Exception("Gowin install not found!")
            elif part_str.upper().startswith("CCGM"):
                SYN_TOOL = CC_TOOLS
                # TODO dont base on cc-toolchain directory?
                if os.path.exists(CC_TOOLS.CC_TOOLS_PATH):
                    print("CologneChip Tools:", CC_TOOLS.CC_TOOLS_PATH, flush=True)
                else:
                    if not allow_fail:
                        raise Exception("CologneChip toolchain install not found!")
            else:
                if not allow_fail:
                    print(
                        "No known synthesis tool for FPGA part:", part_str, flush=True
                    )
                    sys.exit(-1)

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
    elif (SYN_TOOL is DIAMOND) or (SYN_TOOL is PYRTL):
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
def WRITE_CLK_CONSTRAINTS_FILE(parser_state, inst_name=None):
    # Use specified mhz is multimain top
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

    f.close()
    return out_filepath


# These are the parameters that describe how multiple pipelines are timed
class MultiMainTimingParams:
    def __init__(self):
        # Pipeline params
        self.TimingParamsLookupTable = {}
        # TODO some kind of params for clock crossing

    def GET_HASH_EXT(self, parser_state):
        # Just hash all the slices #TODO fix to just mains
        top_level_str = ""
        for main_func in sorted(parser_state.main_mhz.keys()):
            timing_params = self.TimingParamsLookupTable[main_func]
            hash_ext_i = timing_params.GET_HASH_EXT(
                self.TimingParamsLookupTable, parser_state
            )
            top_level_str += hash_ext_i
        s = top_level_str
        hash_ext = (
            "_" + ((hashlib.md5(s.encode("utf-8")).hexdigest())[0:4])
        )  # 4 chars enough?
        return hash_ext


# These are the parameters that describe how a pipeline should be formed
class TimingParams:
    def __init__(self, inst_name, logic):
        self.logic = logic
        self.inst_name = inst_name

        # Have the current params (slices) been fixed,
        # Default to fixed if known cant be sliced
        self.params_are_fixed = False
        # Params, private _ since cached
        self._slices = []  # Unless raw vhdl (no submodules), these are only ~approximate slices
        # ??Maybe add flag for these fixed slices provide latency, dont rebuild? unecessary?
        self._has_input_regs = False
        self._has_output_regs = False

        # Sometimes slices are between submodules,
        # This can specify where a stage is artificially started by not allowing submodules to be instantiated even if driven in an early state
        # UNUSED FOR NOW
        # self.submodule_to_start_stage = {}
        # self.submodule_to_end_stage = {}

        # Cached stuff
        self.calcd_total_latency = None
        self.hash_ext = None
        # self.timing_report_stage_range = None

    def DEEPCOPY(self):
        rv = copy.copy(self)
        rv._slices = self._slices[:]  # COPY
        # Logic ok to be same obj
        # All others immut right now
        return rv

    def INVALIDATE_CACHE(self):
        self.calcd_total_latency = None
        self.hash_ext = None
        # self.timing_report_stage_range = None

    # I was dumb and used get latency all over
    # mAKE CACHED VERSION
    def GET_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
        if self.calcd_total_latency is None:
            self.calcd_total_latency = self.CALC_TOTAL_LATENCY(
                parser_state, TimingParamsLookupTable
            )
        return self.calcd_total_latency

    def GET_PIPELINE_LOGIC_ADDED_LATENCY(self, parser_state, TimingParamsLookupTable):
        total_latency = self.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
        # Remove latency added by user
        if self.logic.func_name in parser_state.func_fixed_latency:
            fixed_latency = parser_state.func_fixed_latency[self.logic.func_name]
            if total_latency < fixed_latency:
                raise Exception(
                    f"{total_latency} latency function {self.logic.func_name} has fixed latency less? {fixed_latency}?"
                )
            total_latency = total_latency - fixed_latency
        pipeline_added_latency = total_latency
        if self._has_input_regs:
            if pipeline_added_latency == 0:
                raise Exception(
                    f"Zero latency function {self.logic.func_name} has input regs?"
                )
            pipeline_added_latency -= 1
        if self._has_output_regs:
            if pipeline_added_latency == 0:
                raise Exception(
                    "Zero latency function {self.logic.func_name} has output regs?"
                )
            pipeline_added_latency -= 1
        return pipeline_added_latency

    # Haha why uppercase everywhere ...
    def CALC_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
        # Use hard coded pipelined latency
        if self.logic.func_name in parser_state.func_fixed_latency:
            fixed_latency = parser_state.func_fixed_latency[self.logic.func_name]
            pipeline_latency = fixed_latency
        # C built in has multiple shared latencies based on where used
        elif len(self.logic.submodule_instances) <= 0:
            # Just pipeline slices
            pipeline_latency = len(self._slices)
        else:
            # If cant be sliced then latency must be zero right?
            if not self.logic.CAN_BE_SLICED(parser_state):
                if self._has_input_regs or self._has_output_regs:
                    raise Exception(
                        f"{self.logic.func_name} cannot have IO regs but has been given them!?"
                    )
                    # print("Bad io regs on non sliceable!")
                    # sys.exit(-1)
                return 0

            if TimingParamsLookupTable is None:
                print(
                    "Need TimingParamsLookupTable for non raw hdl latency",
                    self.logic.func_name,
                )
                print(0 / 0)
                sys.exit(-1)

            pipeline_map = GET_PIPELINE_MAP(
                self.inst_name, self.logic, parser_state, TimingParamsLookupTable
            )
            pipeline_latency = pipeline_map.num_stages - 1

        # Adjut latency for io regs
        latency = pipeline_latency
        if self._has_input_regs:
            latency += 1
        if self._has_output_regs:
            latency += 1

        return latency

    def RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(
        self, inst_name, Logic, TimingParamsLookupTable, parser_state
    ):
        # All modules include IO reg flags
        timing_params = TimingParamsLookupTable[inst_name]
        rv = (
            timing_params._has_input_regs,
            timing_params._has_output_regs,
        )
        # Only lowest level raw VHDL modules with no submodules include slices
        if len(Logic.submodule_instances) > 0:
            # Not raw hdl, slices dont guarentee describe pipeline structure
            for submodule in sorted(
                Logic.submodule_instances
            ):  # MUST BE SORTED FOR CONSISTENT ORDER!
                sub_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule
                if sub_inst not in parser_state.LogicInstLookupTable:
                    print("Missing inst_name:", sub_inst)
                    print("has instances:")
                    for inst_i, logic_i in parser_state.LogicInstLookupTable.items():
                        print(inst_i)
                    print(0 / 0, flush=True)
                    sys.exit(-1)
                sub_logic = parser_state.LogicInstLookupTable[sub_inst]
                rv += (
                    self.RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(
                        sub_inst, sub_logic, TimingParamsLookupTable, parser_state
                    ),
                )
        else:
            # Raw HDL
            rv += (tuple(timing_params._slices),)

        return rv

    # Hash ext only reflect raw hdl slices (better would be raw hdl bits per stage)
    def BUILD_HASH_EXT(self, inst_name, Logic, TimingParamsLookupTable, parser_state):
        # print("BUILD_HASH_EXT",Logic.func_name, flush=True)
        io_regs_and_slices_tup = self.RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(
            inst_name, Logic, TimingParamsLookupTable, parser_state
        )
        s = str(io_regs_and_slices_tup)
        full_hash = hashlib.md5(s.encode("utf-8")).hexdigest()
        hash_ext = (
            "_" + (full_hash[0:8])
        )  # 4 chars enough, no you dummy, lets hope 8 is
        # print(f"inst {inst_name} {full_hash} {hash_ext}")
        return hash_ext

    def GET_HASH_EXT(self, TimingParamsLookupTable, parser_state):
        if self.hash_ext is None:
            self.hash_ext = self.BUILD_HASH_EXT(
                self.inst_name, self.logic, TimingParamsLookupTable, parser_state
            )

        return self.hash_ext

    def ADD_SLICE(self, slice_point):
        if self._slices is None:
            self._slices = []
        if slice_point > 1.0:
            print("Slice > 1.0?", slice_point)
            sys.exit(-1)
            slice_point = 1.0
        if slice_point < 0.0:
            print("Slice < 0.0?", slice_point)
            print(0 / 0)
            sys.exit(-1)
            slice_point = 0.0

        if slice_point not in self._slices:
            self._slices.append(slice_point)
            self._slices = sorted(self._slices)
            self.INVALIDATE_CACHE()
        else:
            raise Exception(
                f"Slice {slice_point} exists already cant add? slices pre add: {self._slices}"
            )

        if self.calcd_total_latency is not None:
            print("WTF adding a slice and has latency cache?", self.calcd_total_latency)
            print(0 / 0)
            sys.exit(-1)

    def SET_SLICES(self, value):
        if value != self._slices:
            self._slices = value[:]
            self.INVALIDATE_CACHE()

    def SET_HAS_IN_REGS(self, value):
        if value != self._has_input_regs:
            self._has_input_regs = value
            self.INVALIDATE_CACHE()

    def SET_HAS_OUT_REGS(self, value):
        if value != self._has_output_regs:
            self._has_output_regs = value
            self.INVALIDATE_CACHE()

    def GET_SUBMODULE_LATENCY(
        self, submodule_inst_name, parser_state, TimingParamsLookupTable
    ):
        submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
        return submodule_timing_params.GET_TOTAL_LATENCY(
            parser_state, TimingParamsLookupTable
        )


def DEL_ALL_CACHES():
    # Clear all caches after parsing is done
    global _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache
    # global _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache

    _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache = {}
    # _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache    = {}
    # _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache = {}


_GET_ZERO_CLK_HASH_EXT_LOOKUP_cache = {}
_GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache = {}


def GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state):
    # Cached?
    # print("GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP")
    cache_key = str(sorted(set(parser_state.LogicInstLookupTable.keys())))
    if cache_key in _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache:
        cached_lookup = _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache[cache_key]
        rv = {}
        for inst_i, params_i in cached_lookup.items():
            rv[inst_i] = params_i.DEEPCOPY()
        return rv

    # Create empty lookup
    ZeroAddedClocksTimingParamsLookupTable = {}
    for logic_inst_name in parser_state.LogicInstLookupTable:
        logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
        timing_params_i = TimingParams(logic_inst_name, logic_i)
        ZeroAddedClocksTimingParamsLookupTable[logic_inst_name] = timing_params_i

    # Calc cached params so they are in cache
    bad_fixed_latency_when_cant_slice_func_names = set()
    for logic_inst_name in parser_state.LogicInstLookupTable:
        logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
        timing_params_i = ZeroAddedClocksTimingParamsLookupTable[logic_inst_name]
        total_latency = timing_params_i.GET_TOTAL_LATENCY(
            parser_state, ZeroAddedClocksTimingParamsLookupTable
        )
        # Sanity check functions that can't be sliced arent showing up with slices/latency in them
        pipeline_added_latency = timing_params_i.GET_PIPELINE_LOGIC_ADDED_LATENCY(
            parser_state, ZeroAddedClocksTimingParamsLookupTable
        )
        if logic_i.func_name not in bad_fixed_latency_when_cant_slice_func_names:
            if (pipeline_added_latency > 0) and not logic_i.BODY_CAN_BE_SLICED(
                parser_state
            ):
                print(
                    "Error: Zero latency static stateful function",
                    logic_i.func_name,
                    "actually describes a pipeline of non-zero latency/depth. (",
                    pipeline_added_latency + 1,
                    "stages total)",
                )
                bad_fixed_latency_when_cant_slice_func_names.add(logic_i.func_name)
        # Write cache
        if logic_i.func_name in _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache:
            timing_params_i.hash_ext = _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache[
                logic_i.func_name
            ]
        else:
            _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache[logic_i.func_name] = (
                timing_params_i.GET_HASH_EXT(
                    ZeroAddedClocksTimingParamsLookupTable, parser_state
                )
            )
    if len(bad_fixed_latency_when_cant_slice_func_names) > 0:
        print(
            """Modify one or more of the above functions:
Remove FUNC_LATENCY pragmas specifying fixed pipeline latencies.
OR
Remove stateful static local variables to allow pipelining."""
        )
        raise Exception("Resolve the above unexpected added pipeline latency errors.")

    _GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP_cache[cache_key] = (
        ZeroAddedClocksTimingParamsLookupTable
    )
    return ZeroAddedClocksTimingParamsLookupTable


_GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache = {}


def GET_ZERO_ADDED_CLKS_PIPELINE_MAP(inst_name, Logic, parser_state, write_files=True):
    key = Logic.func_name

    # Try cache
    try:
        rv = _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache[key]
        # print "_GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache",key

        # Sanity?
        if rv.logic != Logic:
            print("Zero clock cache no mactho")
            sys.exit(-1)

        return rv
    except:
        pass

    has_delay = True
    # Only need to check submodules, not self
    for sub_inst in Logic.submodule_instances:
        func_name = Logic.submodule_instances[sub_inst]
        sub_func_logic = parser_state.FuncLogicLookupTable[func_name]
        if sub_func_logic.delay is None:
            print(Logic.func_name, "/", sub_func_logic.func_name)
            has_delay = False
            break
    if not has_delay:
        raise Exception("Can't get zero clock pipeline map without delay?")

    # Populate table as all 0 added clks
    ZeroAddedClocksLogicInst2TimingParams = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(
        parser_state
    )

    # Get params for this logic
    # print "Logic.func_name",Logic.func_name

    # Get pipeline map
    zero_added_clks_pipeline_map = GET_PIPELINE_MAP(
        inst_name, Logic, parser_state, ZeroAddedClocksLogicInst2TimingParams
    )

    # Only cache if has delay
    # zero_added_clks_pipeline_map.logic.delay is not None and  Dont need to check self, only submodules
    if zero_added_clks_pipeline_map.zero_clk_max_delay is not None:
        _GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache[key] = zero_added_clks_pipeline_map
    else:
        # Sanity?
        if has_delay:
            # Seems to early catch designs optimizing away
            raise Exception(
                f"It looks like the function {zero_added_clks_pipeline_map.logic.func_name} reduces to constants/wires in an unexpected way? Missing '#pragma FUNC_WIRES {zero_added_clks_pipeline_map.logic.func_name}' ? "
            )

    return zero_added_clks_pipeline_map


class SubmoduleLevelInfo:
    def __init__(self, level_num):
        self.level_num = level_num

        # Starts with wires driving other wires
        self.driver_driven_wire_pairs = []
        # Ends with submodule logic connections
        self.submodule_insts = []

    def IS_EMPTY(self):
        return (
            len(self.driver_driven_wire_pairs) == 0 and len(self.submodule_insts) == 0
        )


class StageInfo:
    def __init__(self, stage_num):
        self.stage_num = stage_num

        # Submodule output wires first
        self.submodule_output_ports = []
        # Then sequence of per submodule level information
        self.submodule_level_infos = []


# This started off as just code writing VHDL
# Then the logic of how the VHDL was written was highjacked for latency calculation
# Then latency calculations were highjacked for logic delay calculations
class PipelineMap:
    def __init__(self, logic):
        self.logic = logic
        # Any logic will have
        self.num_stages = 1  # Comb logic
        # New per stage info class
        self.stage_infos = []

        # Wires and submodules of const network like another pipeline stage outside pipeline
        self.const_network_stage_info = None  # StageInfo
        # Helper list of wires part of const network just used during prop processes
        self.const_network_wire_to_upstream_vars = {}

        # Read only global wires (might be volatile or not)
        self.read_only_global_network_stage_info = None
        self.read_only_global_network_wire_to_upstream_vars = {}

        # DELAY STUFF ONLY MAKES SENSE TO TALK ABOUT WHEN:
        # - 0 CLKS
        # - >0 delay submodules
        #  ITS NOT CLEAR HOW SLICES ACTUALLY DISTRIBUTE DELAY
        #  Ex. 1 ns split 2 equal clks?
        #    0.3 | 0.3 | 0.3  ?
        #    0   |  1  |  0   ?   Some raw VHDL is like this
        # Also once you are doing fractional stuff you might as well be doing delay ns
        # Doing slicing for multiple clocks shouldnt require multi clk pipeline maps anyway right?
        # HELP ME
        self.zero_clk_per_delay_submodules_map = {}  # dict[delay_offset] => [submodules,at,offset]
        self.zero_clk_submodule_start_offset = {}  # dict[submodule_inst] = start_offset  # In delay units
        self.zero_clk_submodule_end_offset = {}  # dict[submodule_inst] => end_offset # In delay units
        self.zero_clk_max_delay = None

    def __str__(self):
        rv = "Pipeline Map:\n"
        for delay in sorted(self.zero_clk_per_delay_submodules_map.keys()):
            submodules_insts = self.zero_clk_per_delay_submodules_map[delay]
            submodule_func_names = []
            for submodules_inst in submodules_insts:
                submodule_func_names.append(submodules_inst)

            rv += str(delay) + ": " + str(sorted(submodule_func_names)) + "\n"
        rv = rv.strip("\n")
        return rv

    def write_png(self, out_dir, parser_state):
        try:
            import graphviz
        except:
            return
        s = graphviz.Digraph(
            self.logic.func_name,
            filename="pipeline_map.gv",
            node_attr={"shape": "record"},
        )

        # Dont bother if more than 128 nodes...
        if len(self.logic.submodule_instances) > 128:
            return

        s.graph_attr["rankdir"] = "LR"  # Left to right ordering
        # s.graph_attr['splines']="ortho" # Right angle lines...doesnt look right?

        # SIZE IO + REGS NODES to be largest font
        # Get average bit width (height of node)
        smallest_font_pt = 14.0

        def get_avg_bit_width(sub_inst, logic, parser_state):
            sub_func_name = logic.submodule_instances[sub_inst]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            # See registers estiamte .log
            input_ffs = 0
            for input_port in sub_logic.inputs:
                input_type = sub_logic.wire_to_c_type[input_port]
                input_bits = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(
                    input_type, parser_state
                )
                input_ffs += input_bits
            output_ffs = 0
            for output_port in sub_logic.outputs:
                output_type = sub_logic.wire_to_c_type[output_port]
                output_bits = VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM(
                    output_type, parser_state
                )
                output_ffs += output_bits
            return (input_ffs + output_ffs) / 2.0

        # Bit width(height) scaling
        MIN_AVG_BIT_WIDTH = 999999
        MAX_AVG_BIT_WIDTH = 0
        for sub_inst, sub_func_name in self.logic.submodule_instances.items():
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            if sub_logic.delay is not None and sub_logic.delay > 0:  # Skip zero delay
                avg_bit_width = get_avg_bit_width(sub_inst, self.logic, parser_state)
                if avg_bit_width < MIN_AVG_BIT_WIDTH:
                    MIN_AVG_BIT_WIDTH = avg_bit_width
                if avg_bit_width > MAX_AVG_BIT_WIDTH:
                    MAX_AVG_BIT_WIDTH = avg_bit_width

        # Delay (width) scaling
        MIN_NON_ZERO_DELAY = 999999
        MAX_DELAY = 0
        for sub_inst, sub_func_name in self.logic.submodule_instances.items():
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            if sub_logic.delay is not None and sub_logic.delay > 0:  # Skip zero delay
                if sub_logic.delay < MIN_NON_ZERO_DELAY:
                    MIN_NON_ZERO_DELAY = sub_logic.delay
                if sub_logic.delay > MAX_DELAY:
                    MAX_DELAY = sub_logic.delay

        by_eye_scale = 4.0  # By-eye const adjust...
        max_font_pt = smallest_font_pt + (
            (MAX_DELAY / MIN_NON_ZERO_DELAY) * by_eye_scale
        )
        for wire in self.logic.wires:
            # Constants(Node)
            if C_TO_LOGIC.WIRE_IS_CONSTANT(wire):
                # TODO resolve to const str and manually add location on next line
                val_str = C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE(
                    wire, self.logic, parser_state
                )
                s.node(wire, r"{ " + val_str + " | {<const> CONST}}")

            # Inputs(Node)
            if wire in self.logic.inputs:
                s.node(
                    wire,
                    r"{ " + wire + " | {<in> IN}}",
                    **{"fontsize": str(max_font_pt)},
                )

            # Clock enable(Node)
            if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(self.logic, parser_state):
                s.node(
                    C_TO_LOGIC.CLOCK_ENABLE_NAME,
                    r"{ " + C_TO_LOGIC.CLOCK_ENABLE_NAME + " | {<in> IN}}",
                    **{"fontsize": str(max_font_pt)},
                )

            # Outputs(Node)
            if wire in self.logic.outputs:
                s.node(
                    wire,
                    r"{ {<out> OUT} | " + wire + " }",
                    **{"fontsize": str(max_font_pt)},
                )

            # State regs
            if wire in self.logic.state_regs:
                # s.node(wire, r'{ <in> NEXT | '+wire+' | <out> NOW }')
                s.node(
                    wire + "_in",
                    r"{ {<in> NEXT} | " + wire + " }",
                    **{"fontsize": str(max_font_pt)},
                )
                s.node(
                    wire + "_out",
                    r"{ " + wire + " | {<out> NOW} }",
                    **{"fontsize": str(max_font_pt)},
                )

        # Submodules/Nodes with ports
        for sub_inst, sub_func_name in self.logic.submodule_instances.items():
            # Need to lookup input ports, and output ports
            # Location
            # And total width of inputs/outputs for height
            # width is based on delay of func logic
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            inputs_text = ""
            for input_port in sub_logic.inputs:
                inputs_text += f"<{input_port}> {input_port}" + " |"
            if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                inputs_text += (
                    f"<{C_TO_LOGIC.CLOCK_ENABLE_NAME}> {C_TO_LOGIC.CLOCK_ENABLE_NAME}"
                    + " |"
                )
            inputs_text = inputs_text.strip("|")
            outputs_text = ""
            for output_port in sub_logic.outputs:
                outputs_text += f"<{output_port}> {output_port}" + " |"
            outputs_text = outputs_text.strip("|")
            func_name_text = sub_func_name
            c_ast_node_coord = self.logic.submodule_instance_to_c_ast_node[
                sub_inst
            ].coord
            location_text = (  # str(os.path.basename(c_ast_node_coord.file)) + r'\n' +
                "line "
                + str(c_ast_node_coord.line)
                + " "
                + "col. "
                + str(c_ast_node_coord.column)
            )
            avg_bit_width = get_avg_bit_width(sub_inst, self.logic, parser_state)
            width = 1
            height = 1
            font_pt = smallest_font_pt
            if sub_logic.delay is not None and sub_logic.delay > 0:
                width = float(sub_logic.delay) / MIN_NON_ZERO_DELAY
                font_pt += width * by_eye_scale
                width *= by_eye_scale
                height = float(avg_bit_width) / MIN_AVG_BIT_WIDTH
                height /= by_eye_scale
            ns = float(sub_logic.delay) / DELAY_UNIT_MULT
            shape_text = f"{ns:.1f}ns x ~{avg_bit_width}bits"
            s.node(
                sub_inst,
                r"{{"
                + inputs_text
                + r"} | "
                + func_name_text
                + r"\n"
                + location_text
                + r"\n"
                + shape_text
                + r"| {"
                + outputs_text
                + r"}}",
                **{
                    "width": str(width),
                    "height": str(height),
                    "fontsize": str(font_pt),
                },
            )

        # Connections/Edges
        for driving_wire, driven_wires in self.logic.wire_drives.items():

            def wire_to_gv_text(wire, dir):
                # Constants(Node)
                if C_TO_LOGIC.WIRE_IS_CONSTANT(wire):
                    return wire + ":" + "const"

                # Inputs(Node)
                if wire in self.logic.inputs:
                    return wire + ":" + "in"

                # Clock enable(Node)
                if wire == C_TO_LOGIC.CLOCK_ENABLE_NAME:
                    return wire

                # Outputs(Node)
                if wire in self.logic.outputs:
                    return wire + ":" + "out"

                # State regs
                if wire in self.logic.state_regs:
                    return wire + "_" + dir + ":" + dir

                # Submodule
                if C_TO_LOGIC.SUBMODULE_MARKER in wire:
                    return wire.replace(C_TO_LOGIC.SUBMODULE_MARKER, ":")

                return None
                # raise Exception(f"GV text for wire? {wire}")

            for driven_wire in driven_wires:
                drive_text = wire_to_gv_text(driving_wire, "out")
                if drive_text is None:
                    continue
                # Follow wire-wire connections to submodules
                # Quickly hacked together...
                next_driven_wires = []
                if driven_wire in self.logic.wire_drives:
                    next_driven_wires = self.logic.wire_drives[driven_wire]
                driven_text = wire_to_gv_text(driven_wire, "in")
                if driven_text is not None:
                    s.edges([(drive_text, driven_text)])
                while driven_text is None and len(next_driven_wires) > 0:
                    new_next_driven_wires = []
                    for next_driven_wire in next_driven_wires:
                        driven_text = wire_to_gv_text(next_driven_wire, "in")
                        if driven_text is None:
                            if next_driven_wire in self.logic.wire_drives:
                                new_next_driven_wires += self.logic.wire_drives[
                                    next_driven_wire
                                ]
                        else:
                            s.edges([(drive_text, driven_text)])
                    next_driven_wires = new_next_driven_wires[:]

        s.format = "png"
        try:
            s.render(directory=out_dir)
        except Exception as e:
            print(f"graphviz render exception: {e}")
        return


"""
___          ___     __   __   ___  __       . ___ 
 |  |  |\/| |__     |  \ /  \ |__  /__` |\ | '  |  
 |  |  |  | |___    |__/ \__/ |___ .__/ | \|    |  
                                                   
 ___        __  ___              ___       ___     
|__  \_/ | /__`  |     | |\ |     |  |__| |__      
|___ / \ | .__/  |     | | \|     |  |  | |___     
                                                   
 __        __   ___        ___      ___            
|__)  /\  /__` |__   |\/| |__  |\ |  |             
|__) /~~\ .__/ |___  |  | |___ | \|  |             
"""


# So for ~now the answer is yes, forever
def GET_PIPELINE_MAP(inst_name, logic, parser_state, TimingParamsLookupTable):
    # FORGIVE ME (for this hacked custom graph breadth first thing w/ delays + multiple stages) - never
    LogicInstLookupTable = parser_state.LogicInstLookupTable
    timing_params = TimingParamsLookupTable[inst_name]
    rv = PipelineMap(logic)

    # Non submodule modules like dont need this
    # Dont check just dont call this func in that case?
    if (
        VHDL.LOGIC_IS_RAW_HDL(logic, parser_state)
        or logic.is_vhdl_func
        or logic.is_vhdl_expr
        or logic.is_vhdl_text_module
        or logic.func_name in parser_state.func_marked_blackbox
        or C_TO_LOGIC.FUNC_IS_PRIMITIVE(logic.func_name, parser_state)
    ):
        return rv

    print_debug = False
    bad_inf_loop = False
    if print_debug:
        print(
            "==============================Getting pipeline map======================================="
        )
        print("GET_PIPELINE_MAP:")
        print("inst_name", inst_name)
        print("logic.func_name", logic.func_name)
        # print "logic.submodule_instances:",logic.submodule_instances

    # Delay stuff was hacked into here and only works for combinatorial logic
    est_total_latency = None
    has_delay = True
    # Only need to check submodules, not self
    for sub_inst in logic.submodule_instances:
        func_name = logic.submodule_instances[sub_inst]
        sub_func_logic = parser_state.FuncLogicLookupTable[func_name]
        if sub_func_logic.delay is None:
            if print_debug:
                print("Submodule", sub_inst, "has None delay")
            has_delay = False
            break

    if print_debug:
        print("timing_params._slices", timing_params._slices)
        print("has_delay", has_delay)

    # Keep track of submodules whos inputs are fully driven
    fully_driven_submodule_inst_2_logic = {}
    # And keep track of which submodules remain
    # as to not keep looping over all submodules (sloo)
    not_fully_driven_submodules = set(logic.submodule_instances.keys())

    # Upon writing a submodule do not
    # add output wire (and driven by output wires) to wires_driven_so_far
    # Intead delay them for N clocks as counted by the clock loop
    #   "Let's pretend we don't exist. Lets pretend we're in Antarctica" - Of Montreal
    wire_to_remaining_clks_before_driven = {}
    # All wires start with invalid latency as to not write them too soon
    for wire in logic.wires:
        wire_to_remaining_clks_before_driven[wire] = -1

    # Bound on latency for sanity - this isnt used is it?
    if est_total_latency is not None:
        max_possible_latency = est_total_latency
        max_possible_latency_with_extra = max_possible_latency + 2

    # To keep track of 'execution order' do this stupid thing:
    # Keep a list of wires that are have been driven so far
    # Search this list to filter which submodules are in each level
    # Replaced wires_driven_so_far
    wires_driven_by_so_far = {}  # driven wire -> driving wire

    def RECORD_DRIVEN_BY(driving_wire, driven_wire_or_wires):
        if type(driven_wire_or_wires) is list:
            driven_wires = driven_wire_or_wires
        elif type(driven_wire_or_wires) is set:
            driven_wires = list(driven_wire_or_wires)
        else:
            driven_wires = [driven_wire_or_wires]
        for driven_wire in driven_wires:
            wires_driven_by_so_far[driven_wire] = driving_wire
            # Also set clks? Seems right?
            wire_to_remaining_clks_before_driven[driven_wire] = 0

    # Some wires are driven to start with
    RECORD_DRIVEN_BY(None, logic.inputs)
    RECORD_DRIVEN_BY(None, C_TO_LOGIC.CLOCK_ENABLE_NAME)
    RECORD_DRIVEN_BY(None, set(logic.state_regs.keys()))
    RECORD_DRIVEN_BY(None, logic.feedback_vars)

    # Keep track of delay offset when wire is driven
    # ONLY MAKES SENSE FOR 0 CLK RIGHT NOW
    delay_offset_when_driven = {}
    for wire_driven_so_far in list(wires_driven_by_so_far.keys()):
        delay_offset_when_driven[wire_driven_so_far] = (
            0  # Is per stage value but we know is start of stage 0
        )

    # Start with wires that have drivers
    last_wires_starting_level = None
    wires_starting_level = list(wires_driven_by_so_far.keys())[:]
    next_wires_to_follow = []

    # Special handling of wires not directly in pipeline:

    # Propagate network across wires until reaching submodule inputs
    # Append wire driver pairs to submodule_level_info
    # Return submodules reached by wire
    def propagate_wire(
        wire_to_follow,
        upstream_vars,
        submodule_level_info,
        network_wire_to_upstream_vars,
    ):
        if wire_to_follow not in network_wire_to_upstream_vars:
            network_wire_to_upstream_vars[wire_to_follow] = set()
        network_wire_to_upstream_vars[wire_to_follow] |= upstream_vars
        submodules_reached = set()
        # Submodule input port finishes level
        is_submodule_input = False
        if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(wire_to_follow, logic):
            sub_toks = wire_to_follow.split(C_TO_LOGIC.SUBMODULE_MARKER)
            submodule_inst = sub_toks[0]
            sub_func_name = logic.submodule_instances[submodule_inst]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            sub_port_name = sub_toks[1]
            if sub_port_name in sub_logic.inputs:
                is_submodule_input = True
            if sub_port_name in sub_logic.outputs:
                RECORD_DRIVEN_BY(None, wire_to_follow)
        if is_submodule_input:
            sub_toks = wire_to_follow.split(C_TO_LOGIC.SUBMODULE_MARKER)
            submodule_inst = sub_toks[0]
            submodules_reached.add(submodule_inst)
        else:
            # Otherwise keep following connected wires
            driven_wires = []
            if wire_to_follow in logic.wire_drives:
                driven_wires = logic.wire_drives[wire_to_follow]
            for driven_wire in driven_wires:
                RECORD_DRIVEN_BY(wire_to_follow, driven_wire)
                submodule_level_info.driver_driven_wire_pairs.append(
                    (wire_to_follow, driven_wire)
                )
                submodules_reached |= propagate_wire(
                    driven_wire,
                    upstream_vars,
                    submodule_level_info,
                    network_wire_to_upstream_vars,
                )
        return submodules_reached

    # Single submodule level of network propagation
    # Fucky since essentially can start with upstream root wires or following modules...
    # Return updated stage_info with new submodule level and return all_in_network_sub_insts_reached
    def propagate_submodule_level(
        things_to_follow,
        things_are_upstream_vars_not_submodules,
        submodule_level_num,
        stage_info,
        network_wire_to_upstream_vars,
    ):
        submodule_level_info = SubmoduleLevelInfo(submodule_level_num)
        # Upstreams vars for these wires depend on if starting off with wires or following submodules
        wire_to_upstream_vars = {}
        if things_are_upstream_vars_not_submodules:
            wires_to_follow = things_to_follow
            for wire_to_follow in wires_to_follow:
                # Follow wires marking as mark of network to submodules
                upstream_vars = set([wire_to_follow])
                wire_to_upstream_vars[wire_to_follow] = upstream_vars
        else:
            submodules_to_follow_outputs = things_to_follow
            # Follow submodule outputs adding to wires_to_follow
            wires_to_follow = set()
            for sub_inst_reached in submodules_to_follow_outputs:
                sub_func_name = logic.submodule_instances[sub_inst_reached]
                sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
                # Known that this func has all inputs fully driven by network in prev sub level
                # And module can be instantiated in separate network
                prev_submodule_level_info = stage_info.submodule_level_infos[-1]
                prev_submodule_level_info.submodule_insts.append(sub_inst_reached)
                fully_driven_submodule_inst_2_logic[sub_inst_reached] = sub_logic
                not_fully_driven_submodules.remove(sub_inst_reached)
                # Set upstream vars for this output wire to be
                # everything that occurs across inputs
                input_upstream_vars = set()
                if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                    input_wire = (
                        sub_inst_reached
                        + C_TO_LOGIC.SUBMODULE_MARKER
                        + C_TO_LOGIC.CLOCK_ENABLE_NAME
                    )
                    if input_wire in network_wire_to_upstream_vars:
                        input_upstream_vars |= network_wire_to_upstream_vars[input_wire]
                for input_port in sub_logic.inputs:
                    input_wire = (
                        sub_inst_reached + C_TO_LOGIC.SUBMODULE_MARKER + input_port
                    )
                    input_upstream_vars |= network_wire_to_upstream_vars[input_wire]
                for output_port in sub_logic.outputs:
                    output_wire = (
                        sub_inst_reached + C_TO_LOGIC.SUBMODULE_MARKER + output_port
                    )
                    wires_to_follow.add(output_wire)
                    wire_to_upstream_vars[output_wire] = input_upstream_vars
        # Follow each wire with associated upstream vars to more submodules
        all_in_network_sub_insts_reached = set()
        for wire_to_follow in wires_to_follow:
            upstream_vars = wire_to_upstream_vars[wire_to_follow]
            sub_insts_reached = propagate_wire(
                wire_to_follow,
                upstream_vars,
                submodule_level_info,
                network_wire_to_upstream_vars,
            )
            # Are all submodule inputs part of network?
            for sub_inst_reached in sub_insts_reached:
                if sub_inst_reached in all_in_network_sub_insts_reached:
                    continue
                sub_func_name = logic.submodule_instances[sub_inst_reached]
                sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
                all_inputs_in_network = True
                for input_port in sub_logic.inputs:
                    input_wire = (
                        sub_inst_reached + C_TO_LOGIC.SUBMODULE_MARKER + input_port
                    )
                    if input_wire not in network_wire_to_upstream_vars.keys():
                        all_inputs_in_network = False
                        break
                if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                    input_wire = (
                        sub_inst_reached
                        + C_TO_LOGIC.SUBMODULE_MARKER
                        + C_TO_LOGIC.CLOCK_ENABLE_NAME
                    )
                    if input_wire not in network_wire_to_upstream_vars.keys():
                        all_inputs_in_network = False
                if all_inputs_in_network:
                    all_in_network_sub_insts_reached.add(sub_inst_reached)
        # Update and return where ended up
        stage_info.submodule_level_infos.append(submodule_level_info)
        return all_in_network_sub_insts_reached

    # Constant network propagation starts at user constant literals like '2'
    things_to_follow = set()
    for wire in logic.wires:
        if C_TO_LOGIC.WIRE_IS_CONSTANT(wire):
            RECORD_DRIVEN_BY(None, wire)
            things_to_follow.add(wire)
    if len(things_to_follow) > 0:
        rv.const_network_stage_info = StageInfo(0)
    submodule_level = 0
    while len(things_to_follow) > 0:
        things_are_upstream_vars_not_submodules = submodule_level == 0
        all_in_network_sub_insts_reached = propagate_submodule_level(
            things_to_follow,
            things_are_upstream_vars_not_submodules,
            submodule_level,
            rv.const_network_stage_info,
            rv.const_network_wire_to_upstream_vars,
        )
        submodule_level += 1
        # Conditionally set submodule outputs as next wires to follow
        things_to_follow = set()
        for sub_inst_reached in all_in_network_sub_insts_reached:
            sub_func_name = logic.submodule_instances[sub_inst_reached]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            # Is this logic something constants propagate over?
            # Any pure function without state should work
            # Use clock/enable? check?
            if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(sub_logic, parser_state):
                continue
            things_to_follow.add(sub_inst_reached)

    # Do read_only_global_wires (non volatile) network prop
    # Starts from read only wires
    things_to_follow = set(logic.read_only_global_wires.keys())
    RECORD_DRIVEN_BY(None, set(logic.read_only_global_wires.keys()))
    if len(things_to_follow) > 0:
        rv.read_only_global_network_stage_info = StageInfo(0)
        # And also includes constant network but does not include its upstream vars/wires - just that is in network
        for const_network_wire in rv.const_network_wire_to_upstream_vars:
            if (
                const_network_wire
                not in rv.read_only_global_network_wire_to_upstream_vars
            ):
                rv.read_only_global_network_wire_to_upstream_vars[
                    const_network_wire
                ] = set()
    submodule_level = 0
    while len(things_to_follow) > 0:
        things_are_upstream_vars_not_submodules = submodule_level == 0
        all_in_network_sub_insts_reached = propagate_submodule_level(
            things_to_follow,
            things_are_upstream_vars_not_submodules,
            submodule_level,
            rv.read_only_global_network_stage_info,
            rv.read_only_global_network_wire_to_upstream_vars,
        )
        submodule_level += 1
        # Conditionally set submodule outputs as next wires to follow
        things_to_follow = set()
        for sub_inst_reached in all_in_network_sub_insts_reached:
            sub_func_name = logic.submodule_instances[sub_inst_reached]
            sub_logic = parser_state.FuncLogicLookupTable[sub_func_name]
            # Is this logic something non vol read only globals propagate over?
            if not LOGIC_IS_ZERO_DELAY(sub_logic, parser_state, True):
                continue
            things_to_follow.add(sub_inst_reached)

    # Pipeline is done when
    def PIPELINE_DONE():
        # ALl outputs driven
        for output in logic.outputs:
            if (output not in wires_driven_by_so_far) or (
                wires_driven_by_so_far[output] is None
            ):
                if print_debug:
                    print("Pipeline not done output.", output)
                return False
            if print_debug:
                print("Output driven ", output, "<=", wires_driven_by_so_far[output])
        # Feedback wires
        for feedback_var in logic.feedback_vars:
            if (feedback_var not in wires_driven_by_so_far) or (
                wires_driven_by_so_far[feedback_var] is None
            ):
                if print_debug:
                    print("Pipeline not done feedback var.", feedback_var)
                return False
            if print_debug:
                print(
                    "Feedback var driven ",
                    feedback_var,
                    "<=",
                    wires_driven_by_so_far[feedback_var],
                )
        # ALl globals driven
        for state_reg in logic.state_regs:
            if logic.state_regs[state_reg].is_volatile == False:
                global_wire = state_reg
                if (global_wire not in wires_driven_by_so_far) or (
                    wires_driven_by_so_far[global_wire] is None
                ):
                    if print_debug:
                        print("Pipeline not done global.", global_wire)
                    return False
                if print_debug:
                    print(
                        "Global driven ",
                        global_wire,
                        "<=",
                        wires_driven_by_so_far[global_wire],
                    )
        # All write only global var wires
        for global_wire in logic.write_only_global_wires:
            if (global_wire not in wires_driven_by_so_far) or (
                wires_driven_by_so_far[global_wire] is None
            ):
                if print_debug:
                    print("Pipeline not done write only global.", global_wire)
                return False
            if print_debug:
                print(
                    "Write only global driven ",
                    global_wire,
                    "<=",
                    wires_driven_by_so_far[global_wire],
                )
        # ALl voltatile globals driven
        # Some volatiles are read only - ex. valid indicator bit
        # And thus are never driven
        # Allow a volatile global wire not to be driven if logic says it is undriven
        for state_reg in logic.state_regs:
            if logic.state_regs[state_reg].is_volatile:
                volatile_global_wire = state_reg
                if volatile_global_wire in logic.wire_driven_by:
                    # Has a driving wire so must be driven for func to be done
                    if (volatile_global_wire not in wires_driven_by_so_far) or (
                        wires_driven_by_so_far[volatile_global_wire] is None
                    ):
                        if print_debug:
                            print(
                                "Pipeline not done volatile global.",
                                volatile_global_wire,
                            )
                        return False
                if print_debug:
                    print(
                        "Volatile driven ",
                        volatile_global_wire,
                        "<=",
                        wires_driven_by_so_far[volatile_global_wire],
                    )

        # All other wires driven?
        for wire in logic.wires:
            if wire not in wires_driven_by_so_far and not logic.WIRE_ALLOW_NO_DRIVEN_BY(
                wire, parser_state.FuncLogicLookupTable
            ):
                if print_debug:
                    print("Pipeline not done wire.", wire)
                return False
            if print_debug:
                driven_by = None
                if wire in wires_driven_by_so_far:
                    driven_by = wires_driven_by_so_far[wire]
                print("Wire driven ", wire, "<=", driven_by)
        if print_debug:
            print("Pipeline stages done...")
        return True

    # WHILE LOOP FOR MULTI STAGE/CLK
    stage_num = 0
    stage_info = StageInfo(stage_num)
    rv.stage_infos.append(stage_info)
    # Above constant and global wire prop
    # means might be done pipeline before even a single iteration
    # of below while loop that increments stage_num, and then stage_num-1 is used for stage count
    if PIPELINE_DONE():
        stage_num = 1
    while not PIPELINE_DONE():
        # Print stuff and set debug if obviously wrong
        if stage_num >= 5000:
            print("Pipeline too long? Past hard coded limit probably...")
            print("inst_name", inst_name)
            bad_inf_loop = True
            print_debug = True
            # print(0/0)
            # sys.exit(-1)
        if est_total_latency is not None:
            if stage_num >= max_possible_latency_with_extra:
                print("Something is wrong here, infinite loop probably...")
                print("inst_name", inst_name)
                # print 0/0
                sys.exit(-1)
            elif stage_num >= max_possible_latency + 1:
                bad_inf_loop = True
                print_debug = True
        if print_debug:
            print("STAGE NUM =", stage_num)

        submodule_level = 0
        # DO WHILE LOOP FOR PER COMB LOGIC SUBMODULE LEVELS
        while True:  # DO
            submodule_level_info = SubmoduleLevelInfo(submodule_level)
            # submodule_level_text = ""

            if print_debug:
                print("SUBMODULE LEVEL", submodule_level)

            #########################################################################################
            # THIS WHILE LOOP FOLLOWS WIRES TO SUBMODULES
            # (BEWARE!: NO SUBMODULES MAY BE FULLY DRIVEN DUE TO MULTI CLK LATENCY)
            # First follow wires to submodules
            # print "wires_driven_by_so_far",wires_driven_by_so_far
            # print "wires_starting_level",wires_starting_level
            wires_to_follow = wires_starting_level[:]
            while len(wires_to_follow) > 0:
                # Sort wires to follow for easy debug of duplicates
                wires_to_follow = sorted(wires_to_follow)
                for driving_wire in wires_to_follow:
                    if bad_inf_loop:
                        print("driving_wire", driving_wire)

                    # Record driving wire as being driven?
                    if driving_wire not in wires_driven_by_so_far:
                        # What drives the driving wire?
                        # Dont know driving wire?
                        driver_of_driver = None
                        if driving_wire in logic.wire_driven_by:
                            driver_of_driver = logic.wire_driven_by[driving_wire]
                        RECORD_DRIVEN_BY(driver_of_driver, driving_wire)

                    # If driving wire is submodule output
                    # Then connect module wire to write pipe
                    if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(
                        driving_wire, logic
                    ):  # is output checked next
                        sub_out_toks = driving_wire.split(C_TO_LOGIC.SUBMODULE_MARKER)
                        submodule_inst = sub_out_toks[0]
                        output_port = sub_out_toks[1]
                        submodule_inst_name = (
                            inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                        )
                        submodule_logic = parser_state.LogicInstLookupTable[
                            submodule_inst_name
                        ]
                        # Make sure is output
                        if output_port in submodule_logic.outputs:
                            # Zero latency special case already in write pipe
                            submodule_latency_from_container_logic = (
                                timing_params.GET_SUBMODULE_LATENCY(
                                    submodule_inst_name,
                                    parser_state,
                                    TimingParamsLookupTable,
                                )
                            )
                            if submodule_latency_from_container_logic > 0:
                                stage_info.submodule_output_ports.append(driving_wire)

                    # Loop over what this wire drives
                    if driving_wire in logic.wire_drives:
                        driven_wires = logic.wire_drives[driving_wire]
                        # Sort for easy debug
                        driven_wires = sorted(driven_wires)
                        if bad_inf_loop:
                            print("driven_wires", driven_wires)

                        # Handle each driven wire
                        for driven_wire in driven_wires:
                            if bad_inf_loop:
                                print("handling driven wire", driven_wire)

                            if driven_wire not in logic.wire_driven_by:
                                # In
                                print(
                                    "!!!!!!!!!!!! DANGLING LOGIC???????",
                                    driven_wire,
                                    "is not driven!?",
                                )
                                continue

                            # Add driven wire to wires driven so far
                            # Record driving this wire, at this logic level offset
                            if (driven_wire in wires_driven_by_so_far) and (
                                wires_driven_by_so_far[driven_wire] is not None
                            ):
                                # Already handled this wire
                                continue
                            RECORD_DRIVEN_BY(driving_wire, driven_wire)

                            # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                            if has_delay:
                                delay_offset_when_driven[driven_wire] = (
                                    delay_offset_when_driven[driving_wire]
                                )
                            # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

                            # Follow the driven wire unless its a submodule input port
                            # Submodules input ports is handled at hierarchy cross later - do nothing later
                            if not C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(
                                driven_wire, logic
                            ):
                                # Record reaching another wire
                                next_wires_to_follow.append(driven_wire)

                            # Driving of vol wires is delayed to last stage and done manually in other vhdl
                            # do not record the final driving of vol wires
                            if (
                                driven_wire in logic.state_regs
                                and logic.state_regs[driven_wire].is_volatile
                            ):
                                continue

                            # Record wire pair for rendering in vhdl
                            submodule_level_info.driver_driven_wire_pairs.append(
                                (driving_wire, driven_wire)
                            )

                wires_to_follow = next_wires_to_follow[:]
                next_wires_to_follow = []

            #########################################################################################

            # \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/ GET FULLY DRIVEN SUBMODULES TO POPULATE SUBMODULE LEVEL \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/
            # Have followed this levels wires to submodules
            # We only want to consider the submodules whose inputs have all
            # been driven by now in clock cycle to keep execution order
            #   ALSO:
            #     Slicing between submodules is done via artificially delaying when submodules are instantiated/connected into later stages
            fully_driven_submodule_inst_this_level_2_logic = {}
            # Get submodule logics
            # Loop over each sumodule and check if all inputs are driven
            not_fully_driven_submodules_iter = set(not_fully_driven_submodules)
            for submodule_inst in not_fully_driven_submodules_iter:
                submodule_inst_name = (
                    inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                )
                # Skip submodules weve done already
                already_fully_driven = (
                    submodule_inst in fully_driven_submodule_inst_2_logic
                )
                # Also skip if not the correct stage for this submodule
                incorrect_stage_for_submodule = False

                # if print_debug:
                # print ""
                # print "########"
                # print "SUBMODULE INST",submodule_inst, "FULLY DRIVEN?:",already_fully_driven

                if not already_fully_driven and not incorrect_stage_for_submodule:
                    submodule_logic = parser_state.LogicInstLookupTable[
                        submodule_inst_name
                    ]

                    # Check submodule signals that need to be driven before submodule can be used
                    # CLOCK ENABLE + INPUTS
                    submodule_has_all_inputs_driven = True
                    submodule_input_port_driving_wires = []
                    # Check clock enable
                    if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(
                        submodule_logic, parser_state
                    ):
                        # print "logic.func_name", logic.func_name
                        ce_wire = (
                            submodule_inst
                            + C_TO_LOGIC.SUBMODULE_MARKER
                            + C_TO_LOGIC.CLOCK_ENABLE_NAME
                        )
                        ce_driving_wire = logic.wire_driven_by[ce_wire]
                        submodule_input_port_driving_wires.append(ce_driving_wire)
                        if ce_driving_wire not in wires_driven_by_so_far:
                            submodule_has_all_inputs_driven = False
                    # Check each input
                    if submodule_has_all_inputs_driven:
                        for input_port_name in submodule_logic.inputs:
                            driving_wire = (
                                C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(
                                    logic, submodule_inst, input_port_name
                                )
                            )
                            submodule_input_port_driving_wires.append(driving_wire)
                            if driving_wire not in wires_driven_by_so_far:
                                submodule_has_all_inputs_driven = False
                                if bad_inf_loop:
                                    print(
                                        "!! "
                                        + submodule_inst
                                        + " input wire "
                                        + input_port_name
                                        + " not driven yet"
                                    )
                                    print(" ^ is driven by", driving_wire)
                                    # print "  <<<<<<<<<<<<< ", driving_wire , "is not (fully?) driven?"
                                    # print " <<<<<<<<<<<<< YOU ARE PROBABALY NOT DRIVING ALL LOCAL VARIABLES COMPLETELY(STRUCTS) >>>>>>>>>>>> "
                                    # C_TO_LOGIC.PRINT_DRIVER_WIRE_TRACE(driving_wire, logic, wires_driven_by_so_far)
                                break

                    # If all inputs are driven
                    if submodule_has_all_inputs_driven:
                        fully_driven_submodule_inst_2_logic[submodule_inst] = (
                            submodule_logic
                        )
                        fully_driven_submodule_inst_this_level_2_logic[
                            submodule_inst
                        ] = submodule_logic
                        not_fully_driven_submodules.remove(submodule_inst)
                        if bad_inf_loop:
                            print("submodule", submodule_inst, "HAS ALL INPUTS DRIVEN")

                        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                        if has_delay:
                            # Record delay offset as max of driving wires
                            # Do zero_clk_submodule_start_offset INPUT OFFSET as max of input wires
                            # Start with 0 since submodule can have no inputs and this no input port delay offset
                            input_port_delay_offsets = [0]
                            for (
                                submodule_input_port_driving_wire
                            ) in submodule_input_port_driving_wires:
                                # Some inputs might be constant, dont contribute to delay offset
                                # Some inputs might also be global read wires, similar no delay
                                if (
                                    submodule_input_port_driving_wire
                                    not in rv.const_network_wire_to_upstream_vars
                                    and submodule_input_port_driving_wire
                                    not in rv.read_only_global_network_wire_to_upstream_vars
                                ):
                                    delay_offset = delay_offset_when_driven[
                                        submodule_input_port_driving_wire
                                    ]
                                    input_port_delay_offsets.append(delay_offset)
                            max_input_port_delay_offset = max(input_port_delay_offsets)

                            # All submodules should be driven at some offset right?
                            # print "wires_driven_by_so_far",wires_driven_by_so_far
                            # print "delay_offset_when_driven",delay_offset_when_driven
                            rv.zero_clk_submodule_start_offset[submodule_inst] = (
                                max_input_port_delay_offset
                            )

                            # Do  delay starting at the input offset
                            # This delay_offset_when_driven value wont be used
                            # until the stage when the output wire is read
                            # So needs delay expected in last stage
                            submodule_timing_params = TimingParamsLookupTable[
                                submodule_inst_name
                            ]
                            submodule_delay = parser_state.LogicInstLookupTable[
                                submodule_inst_name
                            ].delay
                            # End offset is start offset plus delay
                            # Ex. 0 delay in offset 0
                            # Starts and ends in offset 0
                            # Ex. 1 delay unit in offset 0
                            # ALSO STARTS AND ENDS IN STAGE 0
                            if submodule_delay > 0:
                                abs_delay_end_offset = (
                                    submodule_delay
                                    + rv.zero_clk_submodule_start_offset[submodule_inst]
                                    - 1
                                )
                            else:
                                abs_delay_end_offset = (
                                    rv.zero_clk_submodule_start_offset[submodule_inst]
                                )
                            rv.zero_clk_submodule_end_offset[submodule_inst] = (
                                abs_delay_end_offset
                            )

                            # Do PARALLEL submodules map with start and end offsets from each stage
                            # Dont do for 0 delay submodules, ok fine
                            if submodule_delay > 0:
                                start_offset = rv.zero_clk_submodule_start_offset[
                                    submodule_inst
                                ]
                                end_offset = rv.zero_clk_submodule_end_offset[
                                    submodule_inst
                                ]
                                for abs_delay in range(start_offset, end_offset + 1):
                                    if abs_delay < 0:
                                        print("<0 delay offset?")
                                        print(start_offset, end_offset)
                                        print(delay_offset_when_driven)
                                        sys.exit(-1)
                                    # Submodule isnts
                                    if (
                                        abs_delay
                                        not in rv.zero_clk_per_delay_submodules_map
                                    ):
                                        rv.zero_clk_per_delay_submodules_map[
                                            abs_delay
                                        ] = []
                                    if (
                                        submodule_inst
                                        not in rv.zero_clk_per_delay_submodules_map[
                                            abs_delay
                                        ]
                                    ):
                                        rv.zero_clk_per_delay_submodules_map[
                                            abs_delay
                                        ].append(submodule_inst)

                        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

                    else:
                        # Otherwise save for later
                        if bad_inf_loop:
                            print(
                                "submodule",
                                submodule_inst,
                                "does not have all inputs driven yet",
                            )

                else:
                    # if not already_fully_driven and not incorrect_stage_for_submodule:
                    if print_debug:
                        if not already_fully_driven:
                            print("submodule", submodule_inst)
                            print("already_fully_driven", already_fully_driven)
                            # if submodule_inst in timing_params.submodule_to_start_stage:
                            # print "incorrect_stage_for_submodule",incorrect_stage_for_submodule," = ",stage_num, "stage_num != ", timing_params.submodule_to_start_stage[submodule_inst]

            # print "got input driven submodules, wires_driven_by_so_far",wires_driven_by_so_far
            if bad_inf_loop:
                print(
                    "fully_driven_submodule_inst_this_level_2_logic",
                    fully_driven_submodule_inst_this_level_2_logic,
                )
            # /\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\

            # Im dumb
            submodule_level_iteration_has_submodules = (
                len(fully_driven_submodule_inst_this_level_2_logic) > 0
            )

            ################## INSTANTIATIONS + OUTPUT WIRES FROM SUBMODULE LEVEL ###################################
            # Get list of output wires for this all the submodules in this level
            # by writing submodule connections / entity connections
            for submodule_inst in fully_driven_submodule_inst_this_level_2_logic:
                submodule_inst_name = (
                    inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                )
                submodule_logic = parser_state.LogicInstLookupTable[submodule_inst_name]

                # Use submodule logic to write vhdl
                submodule_level_info.submodule_insts.append(submodule_inst)

                # Get latency
                submodule_latency_from_container_logic = (
                    timing_params.GET_SUBMODULE_LATENCY(
                        submodule_inst_name, parser_state, TimingParamsLookupTable
                    )
                )
                # Add output wires of this submodule to wires driven so far after latency
                for output_port in submodule_logic.outputs:
                    # Construct the name of this wire in the original logic
                    submodule_output_wire = (
                        submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + output_port
                    )
                    if bad_inf_loop:
                        print("following output", submodule_output_wire)
                    # Add this output port wire on the submodule after the latency of the submodule
                    if bad_inf_loop:
                        print("submodule_output_wire", submodule_output_wire)
                    wire_to_remaining_clks_before_driven[submodule_output_wire] = (
                        submodule_latency_from_container_logic
                    )

                    # Sanity?
                    submodule_timing_params = TimingParamsLookupTable[
                        submodule_inst_name
                    ]
                    submodule_latency = submodule_timing_params.GET_TOTAL_LATENCY(
                        parser_state, TimingParamsLookupTable
                    )
                    if submodule_latency != submodule_latency_from_container_logic:
                        print(
                            "submodule_latency != submodule_latency_from_container_logic"
                        )
                        sys.exit(-1)

                    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                    # Set delay_offset_when_driven for this output wire
                    if has_delay:
                        # Set delay offset for this wire
                        submodule_delay = parser_state.LogicInstLookupTable[
                            submodule_inst_name
                        ].delay
                        abs_delay_offset = rv.zero_clk_submodule_end_offset[
                            submodule_inst
                        ]
                        delay_offset_when_driven[submodule_output_wire] = (
                            abs_delay_offset
                        )
                        # ONly +1 if delay > 0
                        if submodule_delay > 0:
                            delay_offset_when_driven[submodule_output_wire] += (
                                1  # "+1" Was seeing stacked parallel submodules where they dont exist
                            )
                    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            ####################################################################################################################

            # END
            # SUBMODULE
            # LEVEL
            # ITERATION

            # This ends one submodule level iteration
            # Record text from this iteration
            submodule_level_prepend_text = (
                "  " + " " + "-- SUBMODULE LEVEL " + str(submodule_level) + "\n"
            )
            if not submodule_level_info.IS_EMPTY():
                stage_info.submodule_level_infos.append(submodule_level_info)

            # Sometimes submodule levels iterations dont have submodules as we iterate driving wires / for multiple clks
            # Only update counters if was real submodule level with submodules
            if submodule_level_iteration_has_submodules:
                # Update counters
                submodule_level = submodule_level + 1
            # else:
            # print "NOT submodule_level_iteration_has_submodules, and that is weird?"
            # sys.exit(-1)

            # Wires starting next level IS wires whose latency has elapsed just now
            wires_starting_level = []
            # Also are added to wires driven so far
            # (done per submodule level iteration since ALSO DOES 0 CLK SUBMODULE OUTPUTS)
            for wire in wire_to_remaining_clks_before_driven:
                if wire_to_remaining_clks_before_driven[wire] == 0:
                    if wire not in wires_driven_by_so_far:
                        if bad_inf_loop:
                            print("wire remaining clks done, is driven now", wire)

                        driving_wire = None
                        if wire in logic.wire_driven_by:
                            driving_wire = logic.wire_driven_by[wire]
                        RECORD_DRIVEN_BY(driving_wire, wire)
                        wires_starting_level.append(wire)

            # WHILE CHECK for when to stop try for submodule levels in this stage
            if not (len(wires_starting_level) > 0):
                # Break out of this loop trying to do submodule level iterations for this stage
                break
            else:
                # Record these last wires starting level and loop again
                # This is dumb and probably doesnt work?
                if last_wires_starting_level == wires_starting_level:
                    print("Same wires starting level?")
                    print(wires_starting_level)
                    # if print_debug:
                    sys.exit(-1)
                    # print_debug = True
                    # sys.exit(-1)
                else:
                    last_wires_starting_level = wires_starting_level[:]

        # PER CLOCK
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        if has_delay:
            # Get max delay
            if len(list(rv.zero_clk_per_delay_submodules_map.keys())) == 0:
                if print_debug:
                    print("No submodules with delay")
                rv.zero_clk_max_delay = 0
            else:
                rv.zero_clk_max_delay = (
                    max(rv.zero_clk_per_delay_submodules_map.keys()) + 1
                )  # +1 since 0 indexed
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

        # PER CLOCK decrement latencies
        if print_debug:
            print("Current stage info...", len(rv.stage_infos))
        stage_num = stage_num + 1
        stage_info = StageInfo(stage_num)
        rv.stage_infos.append(stage_info)
        for wire in wire_to_remaining_clks_before_driven:
            # if wire_to_remaining_clks_before_driven[wire] >= 0:
            wire_to_remaining_clks_before_driven[wire] = (
                wire_to_remaining_clks_before_driven[wire] - 1
            )

        # Output might be driven

        # For 0 clk global funcs, and no global funcs
        # the output is always driven in the last stage / stage zero
        # But for volatile globals the return value might be driven before
        # all of the other logic driving the volatiles is done
        num_volatiles = 0
        for state_reg in logic.state_regs:
            if logic.state_regs[state_reg].is_volatile:
                num_volatiles += 1
        if num_volatiles == 0:
            if est_total_latency is not None:
                # Sanity check that output is driven in last stage
                my_total_latency = stage_num - 1
                if PIPELINE_DONE() and (my_total_latency != est_total_latency):
                    print("Seems like pipeline is done before or after last stage?")
                    print(
                        "inst_name",
                        inst_name,
                        timing_params.GET_HASH_EXT(
                            TimingParamsLookupTable, parser_state
                        ),
                    )
                    print(
                        "est_total_latency",
                        est_total_latency,
                        "calculated total_latency",
                        my_total_latency,
                    )
                    print("timing_params._slices", timing_params._slices)
                    # print "timing_params.submodule_to_start_stage",timing_params.submodule_to_start_stage
                    print(0 / 0)
                    sys.exit(-1)
                    print_debug = True

    # *************************** End of while loops *****************************************************#

    # Save number of stages using stage number counter
    rv.num_stages = stage_num
    my_total_latency = rv.num_stages - 1

    # Sanity check against estimate
    if est_total_latency is not None:
        if est_total_latency != my_total_latency:
            print("BUG IN PIPELINE MAP!")
            print(
                "inst_name",
                inst_name,
                timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state),
            )
            print(
                "est_total_latency",
                est_total_latency,
                "calculated total_latency",
                my_total_latency,
            )
            print("timing_params._slices5", timing_params._slices)
            # print "timing_params.submodule_to_start_stage",timing_params.submodule_to_start_stage
            sys.exit(-1)

    if print_debug:
        print("Stage infos count:", len(rv.stage_infos))

    return rv


# Returns updated TimingParamsLookupTable
# Index of bad slice if sliced through globals, scoo # Passing Afternoon - Iron & Wine
# THIS MUST BE CALLED IN LOOP OF INCREASING SLICES FROM LEFT=>RIGHT
def SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(
    inst_name,
    logic,
    new_slice_pos,
    parser_state,
    TimingParamsLookupTable,
    skip_boundary_slice,
    write_files=True,
    rounding_so_fuck_it=False,
):
    print_debug = False

    # Get timing params for this logic
    timing_params = TimingParamsLookupTable[inst_name]
    if timing_params.params_are_fixed:
        print("Trying to add slice to fixed params?", inst_name)
        sys.exit(-1)

    # If body cant be sliced then can only add IO regs
    if not logic.BODY_CAN_BE_SLICED(parser_state) and logic.CAN_BE_SLICED(parser_state):
        if new_slice_pos > 0.5:
            # Output reg
            timing_params.SET_HAS_OUT_REGS(True)
            if print_debug:
                print(inst_name, "output reg")
        else:
            # Input reg
            timing_params.SET_HAS_IN_REGS(True)
            if print_debug:
                print(inst_name, "input reg")
        TimingParamsLookupTable[inst_name] = timing_params
    elif logic.BODY_CAN_BE_SLICED(parser_state):
        # Add slice to body
        timing_params.ADD_SLICE(new_slice_pos)
        slice_index = timing_params._slices.index(new_slice_pos)
        slice_ends_stage = slice_index
        slice_starts_stage = slice_ends_stage + 1
        prev_slice_pos = None
        if len(timing_params._slices) > 1:
            prev_slice_pos = timing_params._slices[slice_index - 1]

        """
    # Sanity check if not adding last slice then must be skipping boundary right?
    if slice_index != len(timing_params._slices)-1 and not skip_boundary_slice:
        print "Wtf added old/to left slice",new_slice_pos,"while not skipping boundary?",timing_params._slices
        print 0/0
        sys.exit(-1)
    """

        # Write into timing params dict, almost certainly unecessary
        TimingParamsLookupTable[inst_name] = timing_params

        ## Already checked getting here
        ## Check if can slice
        # if not logic.CAN_BE_SLICED(parser_state):
        #    # Can't slice globals, return index of bad slice
        #    if print_debug:
        #        print("Can't slice")
        #    return slice_index

        if print_debug:
            print(
                "SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES",
                inst_name,
                new_slice_pos,
                "write_files",
                write_files,
            )

        # Raw HDL doesnt need further slicing, bottom of hierarchy
        if len(logic.submodule_instances) > 0:
            # print "logic.submodule_instances",logic.submodule_instances
            # Get the zero clock pipeline map for this logic
            zero_added_clks_pipeline_map = GET_ZERO_ADDED_CLKS_PIPELINE_MAP(
                inst_name, logic, parser_state
            )
            total_delay = zero_added_clks_pipeline_map.zero_clk_max_delay
            if total_delay is None:
                print("No delay for module?", logic.func_name)
                sys.exit(-1)
            epsilon = SLICE_EPSILON(total_delay)

            # Sanity?
            if logic.func_name != zero_added_clks_pipeline_map.logic.func_name:
                print(
                    "Zero clk inst name:", zero_added_clks_pipeline_map.logic.func_name
                )
                print("Wtf using pipeline map from other func?")
                sys.exit(-1)

            # Get the offset as float
            delay_offset_float = new_slice_pos * total_delay
            delay_offset = math.floor(delay_offset_float)
            # Clamp to max?
            max_delay = max(
                zero_added_clks_pipeline_map.zero_clk_per_delay_submodules_map.keys()
            )
            if delay_offset > max_delay:
                delay_offset = max_delay
            delay_offset_decimal = delay_offset_float - delay_offset

            # Slice can be through modules or on the boundary between modules
            # The boundary between modules is important for moving slices right up against global logic?

            # Get submodules at this offset
            submodule_insts = (
                zero_added_clks_pipeline_map.zero_clk_per_delay_submodules_map[
                    delay_offset
                ]
            )
            # Get submodules in previous and next delay units
            prev_submodule_insts = []
            if (
                delay_offset - 1
                in zero_added_clks_pipeline_map.zero_clk_per_delay_submodules_map
            ):
                prev_submodule_insts = (
                    zero_added_clks_pipeline_map.zero_clk_per_delay_submodules_map[
                        delay_offset - 1
                    ]
                )
            next_submodule_insts = []
            if (
                delay_offset + 1
                in zero_added_clks_pipeline_map.zero_clk_per_delay_submodules_map
            ):
                next_submodule_insts = (
                    zero_added_clks_pipeline_map.zero_clk_per_delay_submodules_map[
                        delay_offset + 1
                    ]
                )

            # Slice each submodule at offset
            # Record if submodules need to be artifically delayed to start in a later stage
            for submodule_inst in submodule_insts:
                # Slice through submodule
                submodule_inst_name = (
                    inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                )
                submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
                # Only continue slicing down if not fixed slices already (trying to slice deeper and make fixed slices)
                if not submodule_timing_params.params_are_fixed:
                    # Slice through submodule
                    # Only slice when >= 1 delay unit?
                    submodule_func_name = logic.submodule_instances[submodule_inst]
                    submodule_logic = parser_state.FuncLogicLookupTable[
                        submodule_func_name
                    ]
                    containing_logic = logic

                    start_offset = (
                        zero_added_clks_pipeline_map.zero_clk_submodule_start_offset[
                            submodule_inst
                        ]
                    )
                    local_offset = delay_offset - start_offset
                    local_offset_w_decimal = local_offset + delay_offset_decimal

                    # print "start_offset",start_offset
                    # print "local_offset",local_offset
                    # print "local_offset_w_decimal",local_offset_w_decimal

                    # Convert to percent to add slice
                    submodule_total_delay = submodule_logic.delay
                    slice_pos = float(local_offset_w_decimal) / float(
                        submodule_total_delay
                    )
                    if print_debug:
                        print(" Slicing:", submodule_inst)
                        print("   @", slice_pos)

                    # Slice into that submodule
                    skip_boundary_slice = False
                    TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(
                        submodule_inst_name,
                        submodule_logic,
                        slice_pos,
                        parser_state,
                        TimingParamsLookupTable,
                        skip_boundary_slice,
                        write_files,
                    )

                    # Might be bad slice
                    if type(TimingParamsLookupTable) is int:
                        # Slice into submodule was bad
                        if print_debug:
                            print("Adding slice", slice_pos)
                            print("To", submodule_inst)
                            print("Submodule Slice index", TimingParamsLookupTable)
                            print("Container slice index", slice_index)
                            print("Was bad")
                        # Return the slice in the container that was bad
                        return slice_index

    if write_files:
        # Final write package
        # Write VHDL file for submodule
        # Re write submodule package with updated timing params
        timing_params = TimingParamsLookupTable[inst_name]
        syn_out_dir = GET_OUTPUT_DIRECTORY(logic)
        if not os.path.exists(syn_out_dir):
            os.makedirs(syn_out_dir)
        VHDL.WRITE_LOGIC_ENTITY(
            inst_name, logic, syn_out_dir, parser_state, TimingParamsLookupTable
        )

    return TimingParamsLookupTable


# Does not change fixed params
def RECURSIVE_SET_NON_FIXED_TO_ZERO_CLK_TIMING_PARAMS(
    inst_name, parser_state, TimingParamsLookupTable, override_fixed=False
):
    # Get timing params for this logic
    timing_params = TimingParamsLookupTable[inst_name]
    if not timing_params.params_are_fixed or override_fixed:
        # Set to be zero clk
        timing_params.SET_SLICES([])
        # Maybe unfix
        if override_fixed:
            # Reset value
            timing_params.params_are_fixed = not timing_params.logic.CAN_BE_SLICED(
                parser_state
            )
        # Repeat down through submodules since not fixed
        logic = parser_state.LogicInstLookupTable[inst_name]
        for local_sub_inst in logic.submodule_instances:
            sub_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + local_sub_inst
            TimingParamsLookupTable = RECURSIVE_SET_NON_FIXED_TO_ZERO_CLK_TIMING_PARAMS(
                sub_inst, parser_state, TimingParamsLookupTable, override_fixed
            )

    TimingParamsLookupTable[inst_name] = timing_params

    return TimingParamsLookupTable


# Returns index of bad slices or working TimingParamsLookupTable
def ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
    inst_name,
    logic,
    current_slices,
    parser_state,
    TimingParamsLookupTable,
    write_files=True,
    rounding_so_fuck_it=False,
):
    # Do slice to main logic for each slice
    for current_slice_i in current_slices:
        # print "  current_slice_i:",current_slice_i
        skip_boundary_slice = False
        write_files_in_loop = False
        TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(
            inst_name,
            logic,
            current_slice_i,
            parser_state,
            TimingParamsLookupTable,
            skip_boundary_slice,
            write_files_in_loop,
            rounding_so_fuck_it,
        )
        # Might be bad slice
        if type(TimingParamsLookupTable) is int:
            return TimingParamsLookupTable

    if write_files:
        # Do one final dumb loop over all timing params that arent zero clocks?
        # because write_files_in_loop = False above
        for inst_name_to_wr in TimingParamsLookupTable:
            wr_logic = parser_state.LogicInstLookupTable[inst_name_to_wr]
            wr_timing_params = TimingParamsLookupTable[inst_name_to_wr]
            if (
                wr_timing_params.GET_TOTAL_LATENCY(
                    parser_state, TimingParamsLookupTable
                )
                > 0
            ):
                wr_syn_out_dir = GET_OUTPUT_DIRECTORY(wr_logic)
                if not os.path.exists(wr_syn_out_dir):
                    os.makedirs(wr_syn_out_dir)
                VHDL.WRITE_LOGIC_ENTITY(
                    inst_name_to_wr,
                    wr_logic,
                    wr_syn_out_dir,
                    parser_state,
                    TimingParamsLookupTable,
                )

    return TimingParamsLookupTable


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


def WRITE_FINAL_FILES(multimain_timing_params, parser_state):
    is_final_top = True
    VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top)

    # Black boxes are different in final files
    WRITE_BLACK_BOX_FILES(parser_state, multimain_timing_params, is_final_top)

    # Copy pipelinec vhdl directory to output so users can export output directory alone
    copy_tree(
        f"{C_TO_LOGIC.REPO_ABS_DIR()}/src/vhdl", SYN_OUTPUT_DIRECTORY + "/built_in"
    )

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


# Sweep state for a single pipeline inst of logic (a main inst typically?)
class InstSweepState:
    def __init__(self):
        self.met_timing = False
        self.timing_report = None  # Current timing report with multiple paths
        self.mhz_to_latency = {}  # BEST dict[mhz] = latency
        self.latency_to_mhz = {}  # BEST dict[latency] = mhz
        self.last_mhz = None
        self.last_latency = None

        # Coarse grain sweep
        self.coarse_latency = None
        self.slice_step = 0.0  # Coarse grain
        self.initial_guess_latency = None
        self.last_non_passing_latency = None
        self.last_latency_increase = None
        self.worse_or_same_tries_count = 0

        # These only make sense after re writing fine sweep?
        # State about which stage being adjusted?
        # self.seen_slices=dict() # dict[main func] = list of above lists
        # self.latency_to_best_slices = {}
        # self.latency_to_best_delay = {}
        # self.stage_range = [0] # The current worst path stage estimate from the timing report
        # self.working_stage_range = [0] # Temporary stage range to guide adjustments to slices
        # self.stages_adjusted_this_latency = {0 : 0} # stage -> num times adjusted

        # Middle out sweep uses synthesis runs of smaller modules
        # How far down the hierarchy?
        self.hier_sweep_mult = None  # Try coarse sweep from top level 0.0 and move down
        # Increment by find the next level down of not yet sliced modules
        self.smallest_not_sliced_hier_mult = INF_HIER_MULT
        # Sweep use of the coarse sweep at middle levels to produce modules that meet more than the timing requirement
        self.coarse_sweep_mult = 1.0  # Saw as bad as 15 percent loss just from adding io regs slices #1.05 min? # 1.0 doesnt make sense need margin since logic will be with logic/routing delay etc
        # Otherwise from top level coarsely - like original coarse sweep
        # keep trying harder with best guess slices
        self.best_guess_sweep_mult = 1.0

    def reset_recorded_best(self):
        self.mhz_to_latency = {}
        self.latency_to_mhz = {}
        self.worse_or_same_tries_count = 0


# SweepState for the entire multimain top
class SweepState:
    def __init__(self):
        # Multimain sweep state
        self.met_timing = False
        self.multimain_timing_params = None  # Current timing params
        self.timing_report = None  # Current timing report with multiple paths
        self.fine_grain_sweep = False
        self.curr_main_inst = None

        # Per instance sweep state
        self.inst_sweep_state = {}  # dict[main_inst_name] = InstSweepState


def GET_MOST_RECENT_OR_DEFAULT_SWEEP_STATE(parser_state, multimain_timing_params):
    # Try to use cache
    cached_sweep_state = GET_MOST_RECENT_CACHED_SWEEP_STATE()
    sweep_state = None
    if cached_sweep_state is not None:
        print("Using cached most recent sweep state...", flush=True)
        sweep_state = cached_sweep_state
    else:
        print("Starting with blank sweep state...", flush=True)
        sweep_state = SweepState()
        # Set defaults
        sweep_state.multimain_timing_params = multimain_timing_params
        # print("...determining slicing tolerance information for each main function...", flush=True)
        for main_inst_name in parser_state.main_mhz:
            func_logic = parser_state.LogicInstLookupTable[main_inst_name]
            sweep_state.inst_sweep_state[main_inst_name] = InstSweepState()
            # Any instance will do
            inst_name = main_inst_name
            # Only need slicing if has delay?
            delay = parser_state.LogicInstLookupTable[main_inst_name].delay
            # Init hier sweep mult to be top level
            func_path_delay_ns = float(func_logic.delay) / DELAY_UNIT_MULT
            target_mhz = GET_TARGET_MHZ(main_inst_name, parser_state)
            if target_mhz is not None:
                target_path_delay_ns = 1000.0 / target_mhz
                sweep_state.inst_sweep_state[main_inst_name].hier_sweep_mult = 0.0
                if delay > 0.0 and func_logic.CAN_BE_SLICED(parser_state):
                    sweep_state.inst_sweep_state[
                        main_inst_name
                    ].slice_ep = SLICE_EPSILON(delay)
                    # Dont bother making from the top level if need more than 50 slices? # MAGIC?
                    hier_sweep_mult = max(
                        HIER_SWEEP_MULT_MIN,
                        (target_path_delay_ns / func_path_delay_ns)
                        - HIER_SWEEP_MULT_INC,
                    )  # HIER_SWEEP_MULT_INC since fp rounding stuff?
                    sweep_state.inst_sweep_state[
                        main_inst_name
                    ].hier_sweep_mult = hier_sweep_mult
                    # print(func_logic.func_name,"hierarchy sweep mult:",sweep_state.inst_sweep_state[main_inst_name].hier_sweep_mult)

    return sweep_state


def GET_MOST_RECENT_CACHED_SWEEP_STATE():
    output_directory = SYN_OUTPUT_DIRECTORY + "/" + TOP_LEVEL_MODULE
    # Search for most recently modified
    sweep_files = [
        file for file in glob.glob(os.path.join(output_directory, "*.sweep"))
    ]
    if len(sweep_files) > 0:
        # print "sweep_files",sweep_files
        sweep_files.sort(key=os.path.getmtime)
        print(sweep_files[-1])  # most recent file
        most_recent_sweep_file = sweep_files[-1]

        with open(most_recent_sweep_file, "rb") as input:
            sweep_state = pickle.load(input)
            return sweep_state
    else:
        return None


def WRITE_SWEEP_STATE_CACHE_FILE(sweep_state, parser_state):
    # TimingParamsLookupTable = state.TimingParamsLookupTable
    output_directory = SYN_OUTPUT_DIRECTORY + "/" + TOP_LEVEL_MODULE
    # ONly write one sweep per clk for space sake?
    hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
    filename = TOP_LEVEL_MODULE + hash_ext + ".sweep"
    filepath = output_directory + "/" + filename

    # Write dir first if needed
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Write file
    with open(filepath, "wb") as output:
        pickle.dump(state, output, pickle.HIGHEST_PROTOCOL)


def SHIFT_SLICE(slices, index, direction, amount, min_dist):
    if amount == 0:
        return slices

    curr_slice = slices[index]

    # New slices dont incldue the current one until adjsuted
    new_slices = slices[:]
    new_slices.remove(curr_slice)
    new_slice = None
    if direction == "r":
        new_slice = curr_slice + amount

    elif direction == "l":
        new_slice = curr_slice - amount

    else:
        print("WHATATSTDTSTTTS")
        sys.exit(-1)

    if new_slice >= 1.0:
        new_slice = 1.0 - min_dist
    if new_slice < 0.0:
        new_slice = min_dist

    # if new slice is within min_dist of another slice back off change
    for slice_i in new_slices:
        if SLICE_POS_EQ(slice_i, new_slice, min_dist):
            if direction == "r":
                new_slice = slice_i - min_dist  # slightly to left of matching slice

            elif direction == "l":
                new_slice = slice_i + min_dist  # slightly to right of matching slice

            else:
                print("WHATATSTD$$$$TSTTTS")
                sys.exit(-1)
            break

    new_slices.append(new_slice)
    new_slices = sorted(new_slices)

    return new_slices


def GET_BEST_GUESS_IDEAL_SLICES(latency):
    # Build ideal slices at this latency
    chunks = latency + 1
    slice_per_chunk = 1.0 / chunks
    slice_total = 0
    ideal_slices = []
    for i in range(0, latency):
        slice_total += slice_per_chunk
        ideal_slices.append(slice_total)

    return ideal_slices


def REDUCE_SLICE_STEP(slice_step, total_latency, epsilon):
    n = 0
    while True:
        maybe_new_slice_step = 1.0 / (
            (SLICE_STEPS_BETWEEN_REGS + 1 + n) * (total_latency + 1)
        )
        if maybe_new_slice_step < epsilon / 2.0:  # Allow half as small>>>???
            maybe_new_slice_step = epsilon / 2.0
            return maybe_new_slice_step

        if maybe_new_slice_step < slice_step:
            return maybe_new_slice_step

        n = n + 1


def SLICE_DISTANCE_MIN(delay):
    return 1.0 / float(delay)


def SLICE_EPSILON(delay):
    num_div = SLICE_EPSILON_MULTIPLIER * delay

    # Fp compare epsilon is this divider
    EPSILON = 1.0 / float(num_div)
    return EPSILON


def SLICE_POS_EQ(a, b, epsilon):
    return abs(a - b) < epsilon


def SLICES_EQ(slices_a, slices_b, epsilon):
    # Eq if all values are eq
    if len(slices_a) != len(slices_b):
        return False
    all_eq = True
    for i in range(0, len(slices_a)):
        a = slices_a[i]
        b = slices_b[i]
        if not SLICE_POS_EQ(a, b, epsilon):
            all_eq = False
            break

    return all_eq


# Wow this is hack AF
def GET_MAIN_INSTS_FROM_PATH_REPORT(path_report, parser_state, TimingParamsLookupTable):
    if path_report.start_reg_name is None:
        raise Exception("No start reg name in timing report!")
    if path_report.end_reg_name is None:
        raise Exception("No end reg name in timing report!")
    main_insts = set()
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
            pipeline_map = GET_PIPELINE_MAP(
                inst_name, logic, parser_state, TimingParamsLookupTable
            )
            pipeline_hdl_params = VHDL.PiplineHDLParams(
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
            text += f"  {pipeline_ffs} FFs for {latency+1} autopipeline stages:\n"
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


# Todo just coarse for now until someone other than me care to squeeze performance?
# Course then fine - knowhaimsayin
def DO_THROUGHPUT_SWEEP(
    parser_state,
    coarse_only=False,
    starting_guess_latency=None,
    do_incremental_guesses=True,
    comb_only=False,
    stop_at_latency=None,
):
    # Make sure syn tool is set
    PART_SET_TOOL(parser_state.part)
    global SYN_TOOL

    for main_func in parser_state.main_mhz:
        main_logic = parser_state.FuncLogicLookupTable[main_func]
        if main_logic.delay is not None and main_logic.delay > 0:
            mhz = GET_TARGET_MHZ(main_func, parser_state, allow_no_syn_tool=True)
            print("Function:", main_func, "Target MHz:", mhz, flush=True)

    # Populate timing lookup table as all 0 clk
    print("Starting with no added pipelining...", flush=True)
    ZeroAddedClocksTimingParamsLookupTable = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(
        parser_state
    )
    multimain_timing_params = MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = (
        ZeroAddedClocksTimingParamsLookupTable
    )

    # Write clock cross entities
    VHDL.WRITE_CLK_CROSS_ENTITIES(parser_state, multimain_timing_params)

    # Write multi-main top
    VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params)

    # Re-write black box modules that are no longer in final state starting throughput sweep
    WRITE_BLACK_BOX_FILES(parser_state, multimain_timing_params, False)

    # Can only do comb. logic with yosys json for now
    if OPEN_TOOLS.YOSYS_JSON_ONLY:
        print(
            "Running Yosys on top level without added pipelining. logic. TODO: Complete feedback for pipeline params..."
        )
        comb_only = True
        SYN_TOOL = OPEN_TOOLS

    # If comb. logic only
    if comb_only:
        print("Running synthesis on top level without added pipelining...", flush=True)
        for main_func in parser_state.main_mhz:
            main_func_timing_params = multimain_timing_params.TimingParamsLookupTable[
                main_func
            ]
            main_func_latency = main_func_timing_params.GET_TOTAL_LATENCY(
                parser_state, multimain_timing_params.TimingParamsLookupTable
            )
            if main_func_latency > 0:
                print(
                    main_func,
                    ":",
                    main_func_latency,
                    "clocks latency total...",
                    flush=True,
                )
        # Comb logic only AND coarse?
        if coarse_only:
            print("Using --coarse and --comb doesnt make sense? TODO fix?")
            sys.exit(-1)
        else:
            # Regular multi main top comb logic
            timing_report = SYN_TOOL.SYN_AND_REPORT_TIMING_MULTIMAIN(
                parser_state, multimain_timing_params
            )

        # Print a little timing info to characterize comb logic
        clk_to_mhz, constraints_filepath = GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
            parser_state
        )
        for reported_clock_group, path_report in timing_report.path_reports.items():
            passfail = ""
            mhz = 1000.0 / path_report.path_delay_ns
            if reported_clock_group in clk_to_mhz:
                target_mhz = clk_to_mhz[reported_clock_group]
                if target_mhz is not None:
                    if mhz >= target_mhz:
                        passfail = "PASS "
                    else:
                        passfail = "FAIL "
            print(
                f"{passfail}Clock {reported_clock_group} FMAX: {mhz:.3f} MHz ({path_report.path_delay_ns:.3f} ns)",
                flush=True,
            )

        return multimain_timing_params

    # Default sweep state is zero clocks
    sweep_state = GET_MOST_RECENT_OR_DEFAULT_SWEEP_STATE(
        parser_state, multimain_timing_params
    )

    # Switch to coase if single main with no target mhz
    if len(parser_state.main_mhz) == 1:
        main_func = list(parser_state.main_mhz.keys())[0]
        target_mhz = GET_TARGET_MHZ(main_func, parser_state)
        if target_mhz is None:
            print(
                "Switching to coarse sweep since only main function has no specified frequency..."
            )
            coarse_only = True

    # if coarse only
    if coarse_only:
        print("Doing coarse sweep only...", flush=True)
        if len(parser_state.main_mhz) > 1:
            # Try to guess at main func, find funcs with delay and can be sliced
            possible_mains = []
            for main_func in parser_state.main_mhz:
                main_logic = parser_state.FuncLogicLookupTable[main_func]
                if main_logic.delay != 0 and main_logic.BODY_CAN_BE_SLICED(
                    parser_state
                ):
                    possible_mains.append(main_func)
            if len(possible_mains) == 1:
                main_func = possible_mains[0]
                print("Assuming coarse sweep is for main function:", main_func)
            elif len(possible_mains) == 0:
                raise Exception("No main functions are elligible for pipelining.")
            else:
                raise Exception(
                    f"Cannot do use a single coarse sweep with multiple pipelined main functions. Possible main functions: {possible_mains}"
                )
                sys.exit(-1)
        else:
            main_func = list(parser_state.main_mhz.keys())[0]
        target_mhz = GET_TARGET_MHZ(main_func, parser_state)
        if target_mhz is None:
            print("Main function:", main_func, "does not have a set target frequency.")
            target_mhz = INF_MHZ
            if starting_guess_latency is None:
                print(
                    "Starting a coarse sweep incrementally from zero added latency logic.",
                    flush=True,
                )
                starting_guess_latency = 0
                do_incremental_guesses = False
        max_allowed_latency_mult = None
        stop_at_n_worse_result = None
        inst_sweep_state = InstSweepState()
        (
            inst_sweep_state,
            working_slices,
            multimain_timing_params.TimingParamsLookupTable,
        ) = DO_COARSE_THROUGHPUT_SWEEP(
            main_func,
            target_mhz,
            inst_sweep_state,
            parser_state,
            starting_guess_latency,
            do_incremental_guesses,
            max_allowed_latency_mult,
            stop_at_n_worse_result,
            stop_at_latency,
        )

        # Do update of top vhdl (not final though)
        is_final_top = False
        VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top)

        return multimain_timing_params

    # Real middle out sweep which includes coarse sweep
    print("Starting middle out sweep...", flush=True)
    sweep_state = DO_MIDDLE_OUT_THROUGHPUT_SWEEP(parser_state, sweep_state)

    # Maybe skip fine grain
    # if not skip_fine_sweep:
    # # Then fine grain
    # return DO_FINE_THROUGHPUT_SWEEP(parser_state, sweep_state)
    # else:
    return sweep_state.multimain_timing_params


# Not because it is easy, but because we thought it would be easy

# Do I like Joe Walsh?


# Inside out timing params
# Kinda like "make all adds N cycles" as in original thinking
# But starts from first module where any slice approaches timing goal
# Middle out coarseness?
# Modules can be locked/fixed in place and not sliced from above less accurately
def DO_MIDDLE_OUT_THROUGHPUT_SWEEP(parser_state, sweep_state):
    debug = False

    # Cache the multiple coarse runs
    coarse_slices_cache = {}
    printed_slices_cache = set()  # hacky indicator of if printed slicing of func yet

    def cache_key_func(logic, target_mhz):
        key = (logic.func_name, target_mhz)
        return key

    def hier_sweep_mult_func(target_path_delay_ns, func_path_delay_ns):
        return (target_path_delay_ns / func_path_delay_ns) + HIER_SWEEP_MULT_INC

    # Outer loop for this sweep
    sweep_state.met_timing = False
    while not sweep_state.met_timing:
        # Repeatedly walk up the hierarchy trying to slice
        # can fail because cant meet timing on some submodule at this timing goal
        got_timing_params_from_walking_tree = False
        keep_try_for_timing_params = True
        while keep_try_for_timing_params:
            got_timing_params_from_walking_tree = True
            keep_try_for_timing_params = False
            printed_slices_cache = (
                set()
            )  # Print each time trying to walk tree for slicing
            print("Starting from timing params without added pipelining...", flush=True)
            # Reset to empty start for this tree walk
            sweep_state.multimain_timing_params.TimingParamsLookupTable = (
                GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
            )
            for main_inst in parser_state.main_mhz:
                sweep_state.inst_sweep_state[
                    main_inst
                ].smallest_not_sliced_hier_mult = INF_HIER_MULT

            # @#NEED TO REDO search for modules at this hierarchy/delay level starting from top and moving down
            # @Starting from small can run into breaking optimizations that occur at higher levels
            print("Collecting modules to pipeline...", flush=True)
            lowest_level_insts_to_pipeline = set()
            for main_inst in parser_state.main_mhz:
                main_func_logic = parser_state.LogicInstLookupTable[main_inst]
                if main_func_logic.CAN_BE_SLICED(parser_state):
                    lowest_level_insts_to_pipeline.add(main_inst)
            # Do this not recursive down the multi main hier tree walk
            # Looking for lowest level submodule large enough to pipeline lowest_level_insts_to_pipeline is lowest_level_insts_to_pipeline
            collecting_modules_to_pipeline = True
            while collecting_modules_to_pipeline:
                collecting_modules_to_pipeline = False
                for func_inst in list(
                    lowest_level_insts_to_pipeline
                ):  # Copy for modification dur iter
                    # Is this function large enough to pipeline?
                    func_logic = parser_state.LogicInstLookupTable[func_inst]
                    func_path_delay_ns = float(func_logic.delay) / DELAY_UNIT_MULT
                    main_func = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
                        func_inst, parser_state
                    )
                    # Cached coarse sweep?
                    target_mhz = GET_TARGET_MHZ(main_func, parser_state)
                    if target_mhz is None:
                        raise Exception(
                            f"Main function {main_func} does not have a specified operating frequency. Missing MAIN_MHZ pragma?"
                        )
                    target_path_delay_ns = 1000.0 / target_mhz
                    coarse_target_mhz = (
                        target_mhz
                        * sweep_state.inst_sweep_state[main_func].coarse_sweep_mult
                    )

                    if (
                        sweep_state.inst_sweep_state[main_func].hier_sweep_mult
                        * func_path_delay_ns
                    ) <= target_path_delay_ns:
                        # Does NOT need pipelining
                        lowest_level_insts_to_pipeline.discard(func_inst)
                        collecting_modules_to_pipeline = True
                        if func_path_delay_ns > 0.0:
                            hsm_i = hier_sweep_mult_func(
                                target_path_delay_ns, func_path_delay_ns
                            )
                            if (
                                hsm_i
                                < sweep_state.inst_sweep_state[
                                    main_func
                                ].smallest_not_sliced_hier_mult
                            ):
                                sweep_state.inst_sweep_state[
                                    main_func
                                ].smallest_not_sliced_hier_mult = hsm_i
                    elif func_logic.CAN_BE_SLICED(parser_state):
                        # Might need pipelining here if no submodules are also large enough pipeline
                        # Invalidate timing param caches similar to how slicing down does
                        func_inst_timing_params = (
                            sweep_state.multimain_timing_params.TimingParamsLookupTable[
                                func_inst
                            ]
                        )
                        func_inst_timing_params.INVALIDATE_CACHE()
                        for local_sub_inst in func_logic.submodule_instances:
                            sub_inst_name = (
                                func_inst + C_TO_LOGIC.SUBMODULE_MARKER + local_sub_inst
                            )
                            sub_logic = parser_state.LogicInstLookupTable[sub_inst_name]
                            if sub_logic.delay is not None:
                                sub_func_path_delay_ns = (
                                    float(sub_logic.delay) / DELAY_UNIT_MULT
                                )
                                if (
                                    sweep_state.inst_sweep_state[
                                        main_func
                                    ].hier_sweep_mult
                                    * sub_func_path_delay_ns
                                ) > target_path_delay_ns:
                                    # Submodule DOES need pipelining
                                    if sub_logic.CAN_BE_SLICED(parser_state):
                                        lowest_level_insts_to_pipeline.add(
                                            sub_inst_name
                                        )
                                    # This current inst is not lowest level sub needing pipelining
                                    lowest_level_insts_to_pipeline.discard(func_inst)
                                    collecting_modules_to_pipeline = True
                                else:
                                    # Submodule does not neet pipelining, record for hier mult step
                                    if sub_func_path_delay_ns > 0.0:
                                        hsm_i = hier_sweep_mult_func(
                                            target_path_delay_ns, sub_func_path_delay_ns
                                        )
                                        if (
                                            hsm_i
                                            < sweep_state.inst_sweep_state[
                                                main_func
                                            ].smallest_not_sliced_hier_mult
                                        ):
                                            sweep_state.inst_sweep_state[
                                                main_func
                                            ].smallest_not_sliced_hier_mult = hsm_i

            # Sanity
            for func_inst in lowest_level_insts_to_pipeline:
                containr_inst = C_TO_LOGIC.GET_CONTAINER_INST(func_inst)
                if containr_inst in lowest_level_insts_to_pipeline:
                    print(
                        containr_inst,
                        "and submodule",
                        func_inst,
                        "both to be pipelined?",
                    )
                    sys.exit(-1)

            # Got correct lowest_level_insts_to_pipeline
            # Do loop doing pipelining
            print("Pipelining modules...", flush=True)
            pipelining_worked = True
            for func_inst in sorted(
                list(lowest_level_insts_to_pipeline)
            ):  # Sorted for same order of execution
                func_logic = parser_state.LogicInstLookupTable[func_inst]
                func_path_delay_ns = float(func_logic.delay) / DELAY_UNIT_MULT
                main_func = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
                    func_inst, parser_state
                )
                # Cached coarse sweep?
                target_mhz = GET_TARGET_MHZ(main_func, parser_state)
                target_path_delay_ns = 1000.0 / target_mhz
                coarse_target_mhz = (
                    target_mhz
                    * sweep_state.inst_sweep_state[main_func].coarse_sweep_mult
                )
                cache_key = cache_key_func(func_logic, coarse_target_mhz)

                # How to pipeline?
                # Just IO regs? no slicing
                if (
                    (
                        func_path_delay_ns
                        * sweep_state.inst_sweep_state[main_func].coarse_sweep_mult
                    )
                    / target_path_delay_ns
                    <= 1.0
                ):  # func_path_delay_ns < target_path_delay_ns:
                    # Do single clock with io regs "coarse grain"
                    slices = []  # [0.0, 1.0]
                    needs_in_regs = True
                    needs_out_regs = True
                    if func_logic.func_name in parser_state.func_marked_no_add_io_regs:
                        needs_in_regs = False
                        needs_out_regs = False
                    if cache_key not in printed_slices_cache:
                        print(
                            "Slicing (w/ IO regs if possible):",
                            func_logic.func_name,
                            ", mult =",
                            sweep_state.inst_sweep_state[main_func].coarse_sweep_mult,
                            slices,
                            flush=True,
                        )

                # Cached result?
                elif cache_key in coarse_slices_cache:
                    # Try cache of coarse grain before trying for real
                    slices = coarse_slices_cache[cache_key]
                    needs_in_regs = True
                    needs_out_regs = True
                    if func_logic.func_name in parser_state.func_marked_no_add_io_regs:
                        needs_in_regs = False
                        needs_out_regs = False
                    if cache_key not in printed_slices_cache:
                        print(
                            "Cached coarse grain slicing (w/ IO regs if possible):",
                            func_logic.func_name,
                            ", target MHz =",
                            coarse_target_mhz,
                            slices,
                            flush=True,
                        )

                # Manual coarse pipelining
                else:
                    # Have state for this module?
                    if func_inst not in sweep_state.inst_sweep_state:
                        sweep_state.inst_sweep_state[func_inst] = InstSweepState()
                    func_inst_timing_params = (
                        sweep_state.multimain_timing_params.TimingParamsLookupTable[
                            func_inst
                        ]
                    )
                    if cache_key not in printed_slices_cache:
                        print(
                            "Coarse grain sweep slicing",
                            func_logic.func_name,
                            ", target MHz =",
                            coarse_target_mhz,
                            flush=True,
                        )
                    # Need way to stop coarse sweep if sweeping at this level of hierarchy wont work
                    # Number of tries should be more for smaller modules with more uneven slicing landscape
                    # Most tries is like 6?
                    # Which should used for modules where inital guess says ~1clk slicing
                    coarse_sweep_initial_clks = (
                        int(
                            math.ceil(
                                (
                                    func_path_delay_ns
                                    * sweep_state.inst_sweep_state[
                                        main_func
                                    ].coarse_sweep_mult
                                )
                                / target_path_delay_ns
                            )
                        )
                        - 1
                    )
                    allowed_worse_results = int(
                        MAX_N_WORSE_RESULTS_MULT / coarse_sweep_initial_clks
                    )
                    if allowed_worse_results == 0:
                        allowed_worse_results = 1
                    print(
                        "Allowed worse results in coarse sweep:", allowed_worse_results
                    )
                    # Why not do middle out again? All the way down? Because complicated?weird do later
                    (
                        sweep_state.inst_sweep_state[func_inst],
                        working_slices,
                        inst_TimingParamsLookupTable,
                    ) = DO_COARSE_THROUGHPUT_SWEEP(
                        func_inst,
                        coarse_target_mhz,
                        sweep_state.inst_sweep_state[func_inst],
                        parser_state,
                        starting_guess_latency=None,
                        do_incremental_guesses=True,
                        max_allowed_latency_mult=MAX_ALLOWED_LATENCY_MULT,
                        stop_at_n_worse_result=allowed_worse_results,
                    )
                    if not sweep_state.inst_sweep_state[func_inst].met_timing:
                        # Fail here, increment sweep mut and try_to_slice logic will slice lower module next time
                        # Done in this loop, try again
                        got_timing_params_from_walking_tree = False
                        print(
                            func_logic.func_name,
                            "failed to meet timing, trying to pipeline smaller modules...",
                        )
                        # If at smallest module then done trying to get params too
                        if (
                            sweep_state.inst_sweep_state[
                                main_func
                            ].smallest_not_sliced_hier_mult
                            != INF_HIER_MULT
                        ):
                            keep_try_for_timing_params = True
                            # Increase mult to start at next delay unit down
                            # WTF float stuff end up with slice getting repeatedly set just close enough not to slice next level down ?
                            if (
                                sweep_state.inst_sweep_state[
                                    main_func
                                ].smallest_not_sliced_hier_mult
                                == sweep_state.inst_sweep_state[
                                    main_func
                                ].hier_sweep_mult
                            ):
                                sweep_state.inst_sweep_state[
                                    main_func
                                ].hier_sweep_mult += HIER_SWEEP_MULT_INC
                                print(
                                    main_func,
                                    "nudging hierarchy sweep multiplier:",
                                    sweep_state.inst_sweep_state[
                                        main_func
                                    ].hier_sweep_mult,
                                )
                            else:
                                # Normal case
                                sweep_state.inst_sweep_state[
                                    main_func
                                ].hier_sweep_mult = sweep_state.inst_sweep_state[
                                    main_func
                                ].smallest_not_sliced_hier_mult
                                print(
                                    main_func,
                                    "hierarchy sweep multiplier:",
                                    sweep_state.inst_sweep_state[
                                        main_func
                                    ].hier_sweep_mult,
                                )
                            sweep_state.inst_sweep_state[
                                main_func
                            ].best_guess_sweep_mult = 1.0
                            sweep_state.inst_sweep_state[
                                main_inst
                            ].coarse_sweep_mult = 1.0
                        else:
                            # Unless no more modules left?
                            print("No smaller submodules to pipeline...")
                            keep_try_for_timing_params = False
                        break
                    # Assummed met timing if here
                    # Add IO regs for timing
                    slices = working_slices[:]
                    needs_in_regs = True
                    needs_out_regs = True
                    if func_logic.func_name in parser_state.func_marked_no_add_io_regs:
                        needs_in_regs = False
                        needs_out_regs = False
                    if cache_key not in printed_slices_cache:
                        print(
                            "Coarse gain confirmed slicing (w/ IO regs if possible):",
                            func_logic.func_name,
                            ", target MHz =",
                            coarse_target_mhz,
                            slices,
                            flush=True,
                        )
                    coarse_slices_cache[cache_key] = slices[:]

                # Apply pipelining slices
                # Do add slices with the current slices
                write_files = False
                sweep_state.multimain_timing_params.TimingParamsLookupTable = (
                    ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
                        func_inst,
                        func_logic,
                        slices,
                        parser_state,
                        sweep_state.multimain_timing_params.TimingParamsLookupTable,
                        write_files,
                    )
                )
                # Set this module to use io regs or not
                func_inst_timing_params = (
                    sweep_state.multimain_timing_params.TimingParamsLookupTable[
                        func_inst
                    ]
                )
                func_inst_timing_params.SET_HAS_IN_REGS(needs_in_regs)
                func_inst_timing_params.SET_HAS_OUT_REGS(needs_out_regs)
                # Lock these slices in place?
                # Not be sliced through from the top down in the future
                func_inst_timing_params.params_are_fixed = True
                sweep_state.multimain_timing_params.TimingParamsLookupTable[
                    func_inst
                ] = func_inst_timing_params

                # sET PRINT Cche - yup
                if cache_key not in printed_slices_cache:
                    printed_slices_cache.add(cache_key)

            # Above determination of slices may have failed
            if not got_timing_params_from_walking_tree:
                continue

            # Done pipelining lowest level modules
            # Apply best guess slicing from main top level if wasnt fixed by above loop
            # (could change to do best guess at first place moving up in hier without fixed params?)
            for main_inst in parser_state.main_mhz:
                main_inst_timing_params = (
                    sweep_state.multimain_timing_params.TimingParamsLookupTable[
                        main_inst
                    ]
                )
                if main_inst_timing_params.params_are_fixed:
                    continue
                main_func_logic = parser_state.LogicInstLookupTable[main_inst]
                main_func_path_delay_ns = float(main_func_logic.delay) / DELAY_UNIT_MULT
                target_mhz = GET_TARGET_MHZ(main_inst, parser_state)
                target_path_delay_ns = 1000.0 / target_mhz
                clks = (
                    int(
                        math.ceil(
                            (
                                main_func_path_delay_ns
                                * sweep_state.inst_sweep_state[
                                    main_inst
                                ].best_guess_sweep_mult
                            )
                            / target_path_delay_ns
                        )
                    )
                    - 1
                )
                if clks <= 0:
                    continue
                slices = GET_BEST_GUESS_IDEAL_SLICES(clks)
                print(
                    "Best guess slicing:",
                    main_func_logic.func_name,
                    main_func_path_delay_ns,
                    "(ns) in to target",
                    target_path_delay_ns,
                    "(ns)",
                    ", mult =",
                    sweep_state.inst_sweep_state[main_inst].best_guess_sweep_mult,
                    "~=",
                    len(slices),
                    "clks",
                    flush=True,
                )
                write_files = False
                sweep_state.multimain_timing_params.TimingParamsLookupTable = (
                    ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
                        main_inst,
                        main_func_logic,
                        slices,
                        parser_state,
                        sweep_state.multimain_timing_params.TimingParamsLookupTable,
                        write_files,
                    )
                )
                # Set this module to use io regs or not
                main_inst_timing_params = (
                    sweep_state.multimain_timing_params.TimingParamsLookupTable[
                        main_inst
                    ]
                )
                main_inst_timing_params.SET_HAS_IN_REGS(False)
                main_inst_timing_params.SET_HAS_OUT_REGS(False)
                # Lock these slices in place?
                # Not be sliced through from the top down in the future
                main_inst_timing_params.params_are_fixed = (
                    False  # Best guess can be overwritten
                )
                sweep_state.multimain_timing_params.TimingParamsLookupTable[
                    main_inst
                ] = main_inst_timing_params

        # }END WHILE LOOP REPEATEDLY walking tree for params

        # Quit if cant slice submodules to meet timing / no params from walking tree
        if not got_timing_params_from_walking_tree:
            print(
                "Failed to make even smallest submodules meet timing? Impossible timing goals?"
            )
            sys.exit(-1)

        # Do one final dumb loop over all timing params that arent zero clocks?
        # because write_files_in_loop = False above
        print("Updating output files...", flush=True)
        entities_written = set()
        for (
            inst_name_to_wr
        ) in sweep_state.multimain_timing_params.TimingParamsLookupTable:
            wr_logic = parser_state.LogicInstLookupTable[inst_name_to_wr]
            wr_timing_params = (
                sweep_state.multimain_timing_params.TimingParamsLookupTable[
                    inst_name_to_wr
                ]
            )
            if (
                wr_timing_params.GET_TOTAL_LATENCY(
                    parser_state,
                    sweep_state.multimain_timing_params.TimingParamsLookupTable,
                )
                > 0
            ):
                entity_name = VHDL.GET_ENTITY_NAME(
                    inst_name_to_wr,
                    wr_logic,
                    sweep_state.multimain_timing_params.TimingParamsLookupTable,
                    parser_state,
                )
                if entity_name not in entities_written:
                    entities_written.add(entity_name)
                    wr_syn_out_dir = GET_OUTPUT_DIRECTORY(wr_logic)
                    if not os.path.exists(wr_syn_out_dir):
                        os.makedirs(wr_syn_out_dir)
                    wr_filename = wr_syn_out_dir + "/" + entity_name + ".vhd"
                    if not os.path.exists(wr_filename):
                        VHDL.WRITE_LOGIC_ENTITY(
                            inst_name_to_wr,
                            wr_logic,
                            wr_syn_out_dir,
                            parser_state,
                            sweep_state.multimain_timing_params.TimingParamsLookupTable,
                        )
        # Write estimate of FF usage
        WRITE_REGISTERS_ESTIMATE_FILE(parser_state, sweep_state.multimain_timing_params)

        # Print info on main funcs being synthesized in top
        print("Running syn w timing params...", flush=True)
        print(
            f"Elapsed time: {str(datetime.timedelta(seconds=(timer() - START_TIME)))}..."
        )
        for main_func in parser_state.main_mhz:
            main_func_logic = parser_state.FuncLogicLookupTable[main_func]
            main_func_timing_params = (
                sweep_state.multimain_timing_params.TimingParamsLookupTable[main_func]
            )
            main_func_latency = main_func_timing_params.GET_TOTAL_LATENCY(
                parser_state,
                sweep_state.multimain_timing_params.TimingParamsLookupTable,
            )
            if main_func_latency > 0:
                print(
                    main_func,
                    ":",
                    main_func_latency,
                    "clocks latency total...",
                    flush=True,
                )

        # Run syn on multi main top
        sweep_state.timing_report = SYN_TOOL.SYN_AND_REPORT_TIMING_MULTIMAIN(
            parser_state, sweep_state.multimain_timing_params
        )
        if len(sweep_state.timing_report.path_reports) == 0:
            print(sweep_state.timing_report.orig_text)
            print("Using a bad syn log file?")
            sys.exit(-1)

        # Write pipeline delay cache
        UPDATE_PIPELINE_MIN_PERIOD_CACHE(
            sweep_state.timing_report,
            sweep_state.multimain_timing_params.TimingParamsLookupTable,
            parser_state,
        )

        # Did it meet timing? Make adjusments as checking
        made_adj = False
        has_paths = len(sweep_state.timing_report.path_reports) > 0
        sweep_state.met_timing = has_paths
        for reported_clock_group in sweep_state.timing_report.path_reports:
            path_report = sweep_state.timing_report.path_reports[reported_clock_group]
            # print("Path report:")
            # print(path_report.start_reg_name)
            # print(path_report.end_reg_name)
            # print(path_report.netlist_resources)
            curr_mhz = 1000.0 / path_report.path_delay_ns
            # Oh boy old log files can still be used if target freq changes right?
            # Do a little hackery to get actual target freq right now, not from log
            # Could be a clock crossing too right?
            if len(parser_state.main_mhz) == 1:  # hacky work around for pyrtl really...
                main_insts = set([list(parser_state.main_mhz.keys())[0]])
            else:
                main_insts = GET_MAIN_INSTS_FROM_PATH_REPORT(
                    path_report,
                    parser_state,
                    sweep_state.multimain_timing_params.TimingParamsLookupTable,
                )
            if len(main_insts) <= 0:
                print(
                    "Path group:",
                    reported_clock_group,
                    "is likely only limited by built in FIFO implementations...",
                )
            # Check timing, make adjustments and print info for each main in the timing report
            for main_inst in main_insts:
                # Met timing?
                main_func_logic = parser_state.LogicInstLookupTable[main_inst]
                main_func_timing_params = (
                    sweep_state.multimain_timing_params.TimingParamsLookupTable[
                        main_inst
                    ]
                )
                latency = main_func_timing_params.GET_TOTAL_LATENCY(
                    parser_state,
                    sweep_state.multimain_timing_params.TimingParamsLookupTable,
                )
                target_mhz = GET_TARGET_MHZ(main_inst, parser_state)
                target_path_delay_ns = 1000.0 / target_mhz
                clk_group = parser_state.main_clk_group[main_inst]
                main_met_timing = curr_mhz >= target_mhz
                if not main_met_timing:
                    sweep_state.met_timing = False

                # Print and log
                print(
                    "{} Clock Goal: {:.2f} (MHz) Current: {:.2f} (MHz)({:.2f} ns) {} clks".format(
                        main_func_logic.func_name,
                        target_mhz,
                        curr_mhz,
                        path_report.path_delay_ns,
                        latency,
                    ),
                    flush=True,
                )
                best_mhz_so_far = 0.0
                if len(sweep_state.inst_sweep_state[main_inst].mhz_to_latency) > 0:
                    best_mhz_so_far = max(
                        sweep_state.inst_sweep_state[main_inst].mhz_to_latency.keys()
                    )
                best_mhz_this_latency = 0.0
                if latency in sweep_state.inst_sweep_state[main_inst].latency_to_mhz:
                    best_mhz_this_latency = sweep_state.inst_sweep_state[
                        main_inst
                    ].latency_to_mhz[latency]
                better_mhz = curr_mhz > best_mhz_so_far
                better_latency = curr_mhz > best_mhz_this_latency
                # Log result
                got_same_mhz_again = (
                    curr_mhz == sweep_state.inst_sweep_state[main_inst].last_mhz
                ) and (latency != sweep_state.inst_sweep_state[main_inst].last_latency)
                sweep_state.inst_sweep_state[main_inst].last_mhz = curr_mhz
                sweep_state.inst_sweep_state[main_inst].last_latency = latency
                if better_mhz or better_latency:
                    sweep_state.inst_sweep_state[main_inst].mhz_to_latency[curr_mhz] = (
                        latency
                    )
                    sweep_state.inst_sweep_state[main_inst].latency_to_mhz[latency] = (
                        curr_mhz
                    )

                # Make adjustment if can be sliced
                if not main_met_timing:
                    print_path = False
                    if main_func_logic.BODY_CAN_BE_SLICED(parser_state):
                        # How would best guess mult increase?
                        # Given current latency for pipeline and stage delay what new total comb logic delay does this imply?
                        max_path_delay_ns = 1000.0 / curr_mhz
                        total_delay = max_path_delay_ns * (latency + 1)
                        # How many slices for that delay to meet timing
                        fake_one_clk_mhz = 1000.0 / total_delay
                        new_clks = target_mhz / fake_one_clk_mhz
                        latency_mult = new_clks / (latency + 1)
                        new_best_guess_sweep_mult = (
                            sweep_state.inst_sweep_state[
                                main_inst
                            ].best_guess_sweep_mult
                            * latency_mult
                        )

                        # TODO: Very much need to organize this

                        # Getting exactly same MHz is bad sign, that didnt pipeline current modules right
                        if got_same_mhz_again:
                            print(
                                "Got identical timing result, trying to pipeline smaller modules instead..."
                            )
                            # Dont compensate with higher fmax, start with original coarse grain compensation on smaller modules
                            # WTF float stuff end up with slice getting repeatedly set just close enough not to slice next level down ?
                            if (
                                sweep_state.inst_sweep_state[
                                    main_func
                                ].smallest_not_sliced_hier_mult
                                == sweep_state.inst_sweep_state[
                                    main_func
                                ].hier_sweep_mult
                            ):
                                sweep_state.inst_sweep_state[
                                    main_func
                                ].hier_sweep_mult += HIER_SWEEP_MULT_INC
                                print(
                                    "Nudging hierarchy sweep multiplier:",
                                    sweep_state.inst_sweep_state[
                                        main_func
                                    ].hier_sweep_mult,
                                )
                            else:
                                sweep_state.inst_sweep_state[
                                    main_inst
                                ].hier_sweep_mult = sweep_state.inst_sweep_state[
                                    main_inst
                                ].smallest_not_sliced_hier_mult
                                print(
                                    "Hierarchy sweep multiplier:",
                                    sweep_state.inst_sweep_state[
                                        main_inst
                                    ].hier_sweep_mult,
                                )
                            sweep_state.inst_sweep_state[
                                main_inst
                            ].best_guess_sweep_mult = 1.0
                            sweep_state.inst_sweep_state[
                                main_inst
                            ].coarse_sweep_mult = 1.0
                            made_adj = True
                        elif (
                            new_best_guess_sweep_mult > BEST_GUESS_MUL_MAX
                        ):  # 15 like? main_max_allowed_latency_mult  2.0 magic?
                            # Fail here, increment sweep mut and try_to_slice logic will slice lower module next time
                            print(
                                "Middle sweep at this hierarchy level failed to meet timing...",
                                "Next best guess multiplier was",
                                new_best_guess_sweep_mult,
                            )
                            if (
                                sweep_state.inst_sweep_state[
                                    main_inst
                                ].coarse_sweep_mult
                                + COARSE_SWEEP_MULT_INC
                            ) <= COARSE_SWEEP_MULT_MAX:
                                print(
                                    "Trying to pipeline current modules to higher fmax to compensate..."
                                )
                                sweep_state.inst_sweep_state[
                                    main_inst
                                ].best_guess_sweep_mult = 1.0
                                sweep_state.inst_sweep_state[
                                    main_inst
                                ].coarse_sweep_mult += COARSE_SWEEP_MULT_INC
                                print(
                                    "Coarse synthesis sweep multiplier:",
                                    sweep_state.inst_sweep_state[
                                        main_inst
                                    ].coarse_sweep_mult,
                                )
                                made_adj = True
                                # New timing goal resets recorded best for all recorded insts
                                for inst_i in sweep_state.inst_sweep_state:
                                    inst_sweep_state_i = sweep_state.inst_sweep_state[
                                        inst_i
                                    ]
                                    inst_sweep_state_i.reset_recorded_best()
                            elif (
                                sweep_state.inst_sweep_state[
                                    main_inst
                                ].smallest_not_sliced_hier_mult
                                != INF_HIER_MULT
                            ):
                                print("Trying to pipeline smaller modules instead...")
                                # Dont compensate with higher fmax, start with original coarse grain compensation on smaller modules
                                # WTF float stuff end up with slice getting repeatedly set just close enough not to slice next level down ?
                                if (
                                    sweep_state.inst_sweep_state[
                                        main_func
                                    ].smallest_not_sliced_hier_mult
                                    == sweep_state.inst_sweep_state[
                                        main_func
                                    ].hier_sweep_mult
                                ):
                                    sweep_state.inst_sweep_state[
                                        main_func
                                    ].hier_sweep_mult += HIER_SWEEP_MULT_INC
                                    print(
                                        "Nudging hierarchy sweep multiplier:",
                                        sweep_state.inst_sweep_state[
                                            main_func
                                        ].hier_sweep_mult,
                                    )
                                else:
                                    sweep_state.inst_sweep_state[
                                        main_inst
                                    ].hier_sweep_mult = sweep_state.inst_sweep_state[
                                        main_inst
                                    ].smallest_not_sliced_hier_mult
                                    print(
                                        "Hierarchy sweep multiplier:",
                                        sweep_state.inst_sweep_state[
                                            main_inst
                                        ].hier_sweep_mult,
                                    )
                                sweep_state.inst_sweep_state[
                                    main_inst
                                ].best_guess_sweep_mult = 1.0
                                sweep_state.inst_sweep_state[
                                    main_inst
                                ].coarse_sweep_mult = 1.0
                                made_adj = True
                            else:
                                print_path = True
                        else:
                            # sweep_state.inst_sweep_state[main_inst].best_guess_sweep_mult *= best_guess_sweep_mult_inc
                            sweep_state.inst_sweep_state[
                                main_inst
                            ].best_guess_sweep_mult = new_best_guess_sweep_mult
                            print(
                                "Best guess sweep multiplier:",
                                sweep_state.inst_sweep_state[
                                    main_inst
                                ].best_guess_sweep_mult,
                            )
                            made_adj = True
                    else:
                        print_path = True

                    if print_path:
                        print("Cannot pipeline path to meet timing:")
                        print("START: ", path_report.start_reg_name, "=>")
                        print(" ~", path_report.path_delay_ns, "ns of logic+routing ~")
                        print("END: =>", path_report.end_reg_name, flush=True)

        if sweep_state.met_timing:
            print("Met timing...")
            return sweep_state

        if not made_adj:
            print("Giving up...")
            sys.exit(-1)


# Returns main_inst_to_slices = {} since "coarse" means timing defined by top level slices
# Of Montreal - The Party's Crashing Us
# Starting guess really only saves 1 extra syn run for dup multimain top
def DO_COARSE_THROUGHPUT_SWEEP(
    inst_name,
    target_mhz,
    inst_sweep_state,
    parser_state,
    starting_guess_latency=None,
    do_incremental_guesses=True,
    max_allowed_latency_mult=None,
    stop_at_n_worse_result=None,
    stop_at_latency=None,
):
    working_slices = None
    logic = parser_state.LogicInstLookupTable[inst_name]
    # Reasonable starting guess and coarse throughput strategy is dividing each main up to meet target
    # Dont even bother running multimain top as combinatorial logic
    inst_sweep_state.coarse_latency = 0
    inst_sweep_state.initial_guess_latency = 0
    if starting_guess_latency is None:
        target_path_delay_ns = 1000.0 / target_mhz
        path_delay_ns = float(logic.delay) / DELAY_UNIT_MULT
        if path_delay_ns > 0.0:
            # curr_mhz = 1000.0 / path_delay_ns
            # How many multiples are we away from the goal
            mult = path_delay_ns / target_path_delay_ns
            if mult > 1.0:
                # Divide up into that many clocks as a starting guess
                # If doesnt have global wires
                if logic.BODY_CAN_BE_SLICED(parser_state):
                    clks = int(math.ceil(mult)) - 1
                    inst_sweep_state.coarse_latency = clks
                    inst_sweep_state.initial_guess_latency = clks
    else:
        if logic.BODY_CAN_BE_SLICED(parser_state):
            inst_sweep_state.coarse_latency = starting_guess_latency
            inst_sweep_state.initial_guess_latency = starting_guess_latency

    # Do loop of:
    #   Reset top to 0 clk
    #   Slice each main evenly based on latency
    #   Syn multimain top
    #   Course adjust func latency
    # until mhz goals met
    while True:
        # Reset to zero clock
        print("Building timing params starting without added pipelining...", flush=True)
        # TODO dont need full copy of all other inst being zero clock too
        TimingParamsLookupTable = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)

        # Do slicing
        # Set the slices in timing params and then rebuild
        done = False
        logic = parser_state.LogicInstLookupTable[inst_name]
        # Make even slices
        best_guess_slices = GET_BEST_GUESS_IDEAL_SLICES(inst_sweep_state.coarse_latency)
        print(
            logic.func_name,
            ": sliced coarsely ~=",
            inst_sweep_state.coarse_latency,
            "clocks latency added...",
            flush=True,
        )
        # Do slicing and dont write vhdl this way since slow
        write_files = False

        # Sanity
        if len(TimingParamsLookupTable[inst_name]._slices) != 0:
            print(
                "Not starting with comb logic for main? sliced already?",
                TimingParamsLookupTable[inst_name]._slices,
            )
            sys.exit(-1)

        # Apply slices to main funcs
        TimingParamsLookupTable = (
            ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
                inst_name,
                logic,
                best_guess_slices,
                parser_state,
                TimingParamsLookupTable,
                write_files,
            )
        )
        # TimingParamsLookupTable == None
        # means these slices go through global code
        if type(TimingParamsLookupTable) is not dict:
            print("Slicing through globals still an issue?")
            sys.exit(-1)
            # print("Can't syn when slicing through globals!")
            # return None, None, None, None

        # Fast one time loop writing only files that have non default,>0 latency
        print("Updating output files...", flush=True)
        entities_written = set()
        for inst_name_to_wr in TimingParamsLookupTable:
            wr_logic = parser_state.LogicInstLookupTable[inst_name_to_wr]
            wr_timing_params = TimingParamsLookupTable[inst_name_to_wr]
            if (
                wr_timing_params.GET_TOTAL_LATENCY(
                    parser_state, TimingParamsLookupTable
                )
                > 0
            ):
                entity_name = VHDL.GET_ENTITY_NAME(
                    inst_name_to_wr, wr_logic, TimingParamsLookupTable, parser_state
                )
                if entity_name not in entities_written:
                    entities_written.add(entity_name)
                    wr_syn_out_dir = GET_OUTPUT_DIRECTORY(wr_logic)
                    if not os.path.exists(wr_syn_out_dir):
                        os.makedirs(wr_syn_out_dir)
                    wr_filename = wr_syn_out_dir + "/" + entity_name + ".vhd"
                    if not os.path.exists(wr_filename):
                        VHDL.WRITE_LOGIC_ENTITY(
                            inst_name_to_wr,
                            wr_logic,
                            wr_syn_out_dir,
                            parser_state,
                            TimingParamsLookupTable,
                        )
        # Write estimate of FF usage
        WRITE_REGISTERS_ESTIMATE_FILE(parser_state, TimingParamsLookupTable, inst_name)

        # Run syn on multi main top
        latency = TimingParamsLookupTable[inst_name].GET_TOTAL_LATENCY(
            parser_state, TimingParamsLookupTable
        )
        print(
            "Synthesizing",
            logic.func_name,
            ":",
            latency,
            "clocks total latency...",
            flush=True,
        )
        print(
            f"Elapsed time: {str(datetime.timedelta(seconds=(timer() - START_TIME)))}..."
        )
        inst_sweep_state.timing_report = SYN_TOOL.SYN_AND_REPORT_TIMING(
            inst_name, logic, parser_state, TimingParamsLookupTable
        )

        # Write pipeline delay cache
        UPDATE_PIPELINE_MIN_PERIOD_CACHE(
            inst_sweep_state.timing_report,
            TimingParamsLookupTable,
            parser_state,
            inst_name,
        )

        # Did it meet timing? Make adjusments as checking
        made_adj = False
        has_paths = len(inst_sweep_state.timing_report.path_reports) > 0
        inst_sweep_state.met_timing = has_paths
        for reported_clock_group in inst_sweep_state.timing_report.path_reports:
            path_report = inst_sweep_state.timing_report.path_reports[
                reported_clock_group
            ]
            curr_mhz = 1000.0 / path_report.path_delay_ns
            # Oh boy old log files can still be used if target freq changes right?
            # Do a little hackery to get actual target freq right now, not from log
            # Could be a clock crossing too right?

            # Met timing?
            func_logic = parser_state.LogicInstLookupTable[inst_name]
            timing_params = TimingParamsLookupTable[inst_name]
            latency = timing_params.GET_TOTAL_LATENCY(
                parser_state, TimingParamsLookupTable
            )
            met_timing = curr_mhz >= target_mhz
            if not met_timing:
                inst_sweep_state.met_timing = False

            # Print, log, maybe give up
            print(
                "{} Clock Goal: {:.2f} (MHz) Current: {:.2f} (MHz)({:.2f} ns) {} clks".format(
                    func_logic.func_name,
                    target_mhz,
                    curr_mhz,
                    path_report.path_delay_ns,
                    latency,
                ),
                flush=True,
            )
            best_mhz_so_far = 0.0
            if len(inst_sweep_state.mhz_to_latency) > 0:
                best_mhz_so_far = max(inst_sweep_state.mhz_to_latency.keys())
            better_mhz = curr_mhz >= best_mhz_so_far
            if better_mhz:
                # Log result
                inst_sweep_state.mhz_to_latency[curr_mhz] = latency
                inst_sweep_state.latency_to_mhz[latency] = curr_mhz
                # Log return val best result fmax
                best_guess_slices = GET_BEST_GUESS_IDEAL_SLICES(
                    inst_sweep_state.coarse_latency
                )
                working_slices = best_guess_slices
                # Reset count of bad tries
                inst_sweep_state.worse_or_same_tries_count = 0
            else:
                # Same or worse timing result
                inst_sweep_state.worse_or_same_tries_count += 1
                print(
                    f"Same or worse timing result... (best={best_mhz_so_far})",
                    flush=True,
                )
                if stop_at_n_worse_result is not None:
                    if (
                        inst_sweep_state.worse_or_same_tries_count
                        >= stop_at_n_worse_result
                    ):
                        print(
                            logic.func_name,
                            "giving up after",
                            inst_sweep_state.worse_or_same_tries_count,
                            "bad tries...",
                        )
                        continue

            # Intentionally stopping?
            if (
                stop_at_latency is not None
                and inst_sweep_state.coarse_latency >= stop_at_latency
            ):
                print("Stopping at", stop_at_latency, "clocks latency added...")
                continue

            # Make adjustment if can be sliced
            if not met_timing and func_logic.CAN_BE_SLICED(parser_state):
                # DO incremental guesses based on time report results
                if do_incremental_guesses:
                    max_path_delay = path_report.path_delay_ns
                    # Given current latency for pipeline and stage delay what new total comb logic delay does this imply?
                    total_delay = max_path_delay * (inst_sweep_state.coarse_latency + 1)
                    # How many slices for that delay to meet timing
                    fake_one_clk_mhz = 1000.0 / total_delay
                    mult = target_mhz / fake_one_clk_mhz
                    if mult > 1.0:
                        # Divide up into that many clocks
                        clks = int(mult) - 1
                        print("Timing report suggests", clks, "clocks...")
                        # Reached max check again before setting main_inst_to_coarse_latency
                        if max_allowed_latency_mult is not None:
                            if inst_sweep_state.initial_guess_latency == 0:
                                limit = max_allowed_latency_mult
                            else:
                                limit = (
                                    inst_sweep_state.initial_guess_latency
                                    * max_allowed_latency_mult
                                )
                            if clks >= limit:
                                print(
                                    logic.func_name,
                                    "reached maximum allowed latency, no more adjustments...",
                                    "multiplier =",
                                    max_allowed_latency_mult,
                                )
                                continue

                        """
            # If very far off, or at very low local min, suggested step can be too large
            inc_ratio = clks / inst_sweep_state.coarse_latency
            if inc_ratio > MAX_CLK_INC_RATIO:
              clks = int(MAX_CLK_INC_RATIO*inst_sweep_state.coarse_latency)
              print("Clipped for smaller jump up to",clks,"clocks...")
            """
                        # If very close to goal suggestion might be same clocks (or less?), still increment
                        if clks <= inst_sweep_state.coarse_latency:
                            clks = inst_sweep_state.coarse_latency + 1
                        # Calc diff in latency change
                        clk_inc = clks - inst_sweep_state.coarse_latency
                        # Should be getting smaller
                        if (
                            inst_sweep_state.last_latency_increase is not None
                            and clk_inc >= inst_sweep_state.last_latency_increase
                        ):
                            # Clip to last inc size - 1, minus one to always be narrowing down
                            # Extra div by 2 helps?
                            clk_inc = int(
                                inst_sweep_state.last_latency_increase / 2
                            )  # - 1
                            if clk_inc <= 0:
                                clk_inc = 1
                            clks = inst_sweep_state.coarse_latency + clk_inc
                            print(
                                "Clipped for decreasing jump size to", clks, "clocks..."
                            )

                        # Record
                        inst_sweep_state.last_non_passing_latency = (
                            inst_sweep_state.coarse_latency
                        )
                        inst_sweep_state.coarse_latency = clks
                        inst_sweep_state.last_latency_increase = clk_inc
                        made_adj = True
                else:
                    # No guess, dumb increment by 1
                    # Record, save non passing latency
                    inst_sweep_state.last_non_passing_latency = (
                        inst_sweep_state.coarse_latency
                    )
                    inst_sweep_state.coarse_latency += 1
                    inst_sweep_state.last_latency_increase = 1
                    made_adj = True

        # Intentionally stopping?
        if (
            stop_at_latency is not None
            and inst_sweep_state.coarse_latency >= stop_at_latency
        ):
            return inst_sweep_state, working_slices, TimingParamsLookupTable
        # Passed timing?
        if inst_sweep_state.met_timing:
            return inst_sweep_state, working_slices, TimingParamsLookupTable
        # Stuck?
        if not made_adj:
            print(
                "Unable to make further adjustments. Failed coarse grain attempt meet timing for this module."
            )
            return inst_sweep_state, working_slices, TimingParamsLookupTable

    return inst_sweep_state, working_slices, TimingParamsLookupTable


def GET_SLICE_PER_STAGE(current_slices):
    # Get list of how many slice per stage
    slice_per_stage = []
    slice_total = 0.0
    for slice_pos in current_slices:
        slice_size = slice_pos - slice_total
        slice_per_stage.append(slice_size)
        slice_total = slice_total + slice_size
    # Add end stage
    slice_size = 1.0 - current_slices[len(current_slices) - 1]
    slice_per_stage.append(slice_size)

    return slice_per_stage


def BUILD_SLICES(slice_per_stage):
    rv = []
    slice_total = 0.0
    for slice_size in slice_per_stage:
        new_slice = slice_size + slice_total
        rv.append(new_slice)
        slice_total = slice_total + slice_size
    # Remove end slice?
    rv = rv[0 : len(rv) - 1]
    return rv


# Return slices
def EXPAND_STAGES_VIA_ADJ_COUNT(
    missing_stages, current_slices, slice_step, state, min_dist
):
    print("<<<<<<<<<<< EXPANDING", missing_stages, "VIA_ADJ_COUNT:", current_slices)
    slice_per_stage = GET_SLICE_PER_STAGE(current_slices)
    # Each missing stage is expanded by slice_step/num missing stages
    # Div by num missing stages since might not be able to shrink enough slices
    # to account for every missing stage getting slice step removed
    expansion = slice_step / len(missing_stages)
    total_expansion = 0.0
    for missing_stage in missing_stages:
        slice_per_stage[missing_stage] = slice_per_stage[missing_stage] + expansion
        total_expansion = total_expansion + expansion

    remaining_expansion = total_expansion
    # Split remaining expansion among other stages
    # First check how many stages will be shrank
    stages_to_shrink = []
    for stage in range(0, len(current_slices) + 1):
        if stage not in missing_stages and (
            slice_per_stage[stage] - expansion > min_dist
        ):
            stages_to_shrink.append(stage)
    if len(stages_to_shrink) > 0:
        shrink_per_stage = total_expansion / float(len(stages_to_shrink))
        for stage in stages_to_shrink:
            print("Shrinking stage", stage, "curr size:", slice_per_stage[stage])
            slice_per_stage[stage] -= shrink_per_stage

        # reconstruct new slcies
        rv = BUILD_SLICES(slice_per_stage)

        # print "RV",rv
        # sys.exit(-1)

        return rv
    else:
        # Can't shrink anything more
        return current_slices


def ESTIMATE_MAX_THROUGHPUT(mhz_range, mhz_to_latency):
    """
    High Clock  High Latency  High Period Low Clock Low Latency Low Period  "Required parallel
    Low clock"  "Serialization
    Latency (1 or each clock?) (ns)"
    160 5 6.25  100   10  1.6 16.25
    240 10
    100 2
    260 10
    40  0
    220 10
    140 5
    80  1
    200 10
    20  0
    300 43
    120 5
    180 8
    60  1
    280 32
    """
    min_mhz = min(mhz_range)
    max_mhz = max(mhz_range)
    max_div = int(math.ceil(max_mhz / min_mhz))

    text = ""
    text += (
        "clk_mhz"
        + " "
        + "high_clk_latency_ns"
        + "  "
        + "div_clk_mhz"
        + " "
        + "div_clock_latency_ns"
        + "  "
        + "n_parallel"
        + "  "
        + "deser_delay"
        + " "
        + "ser_delay"
        + " "
        + "total_latency"
        + "\n"
    )

    # For each clock we have calculate the integer divided clocks
    for clk_mhz in mhz_to_latency:
        # Orig latency
        clk_period_ns = (1.0 / clk_mhz) * 1000
        high_clk_latency_ns = mhz_to_latency[clk_mhz] * clk_period_ns
        # Find interger divided clocks we have entries for
        for div_i in range(2, max_div + 1):
            div_clk_mhz = clk_mhz / div_i
            if div_clk_mhz in mhz_to_latency:
                # Have div clock entry
                n_parallel = div_i
                div_clk_period_ns = (1.0 / div_clk_mhz) * 1000
                # Deserialize
                deser_delay = clk_period_ns + div_clk_period_ns  # one of each clock?
                # Latency is one of the low clock
                div_clock_latency_clks = mhz_to_latency[div_clk_mhz]
                div_clock_latency_ns = div_clock_latency_clks * div_clk_period_ns
                # Serialize
                ser_delay = clk_period_ns + div_clk_period_ns  # one of each clock?
                # total latency
                total_latency = deser_delay + div_clock_latency_ns + ser_delay

                text += (
                    str(clk_mhz)
                    + "  "
                    + str(high_clk_latency_ns)
                    + "  "
                    + str(div_clk_mhz)
                    + "  "
                    + str(div_clock_latency_ns)
                    + " "
                    + str(n_parallel)
                    + " "
                    + str(deser_delay)
                    + "  "
                    + str(ser_delay)
                    + "  "
                    + str(total_latency)
                    + "\n"
                )

    f = open(SYN_OUTPUT_DIRECTORY + "/" + "estimated_max_throughput.log", "w")
    f.write(text)
    f.close()


def GET_OUTPUT_DIRECTORY(Logic):
    if Logic.is_c_built_in:
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
        src_file = str(Logic.c_ast_node.coord.file)
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
    elif logic.is_vhdl_text_module:
        return False  # No idea what user has in there
    elif logic.is_vhdl_func or logic.is_vhdl_expr:
        return True
    elif logic.func_name.startswith(C_TO_LOGIC.PRINTF_FUNC_NAME):
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
    if logic.is_vhdl_text_module:
        return None

    submodule_inst = list(logic.submodule_instances.keys())[0]
    submodule_func_name = logic.submodule_instances[submodule_inst]
    submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
    if submodule_logic.delay is None:
        print("Wtf none to check delay???????")
        sys.exit(-1)

    return submodule_logic.delay


def IS_USER_CODE(logic, parser_state):
    # Check logic.is_built_in
    # or autogenerated code

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


def GET_PATH_DELAY_CACHE_DIR(parser_state, dir_name="path_delay_cache"):
    PATH_DELAY_CACHE_DIR = (
        C_TO_LOGIC.EXE_ABS_DIR() + f"/../{dir_name}/" + str(SYN_TOOL.__name__).lower()
    )
    if SYN_TOOL is PYRTL:
        PATH_DELAY_CACHE_DIR += (
            "_" + str(PYRTL.TECH_IN_NM) + "nm" + "_" + str(PYRTL.FF_OVERHEAD) + "ff"
        )
    if parser_state.part is not None:
        PATH_DELAY_CACHE_DIR += "/" + parser_state.part
    if TOOL_DOES_PNR():
        PATH_DELAY_CACHE_DIR += "/pnr"
    else:
        PATH_DELAY_CACHE_DIR += "/syn"
    return PATH_DELAY_CACHE_DIR


def GET_CACHED_LOGIC_FILE_KEY(logic, parser_state):
    # Default sanity
    key = logic.func_name

    # Mux is same delay no matter type
    if logic.is_c_built_in and logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME):
        key = "mux"
    else:
        # MEM has var name - weird yo
        if SW_LIB.IS_MEM(logic):
            key = SW_LIB.GET_MEM_NAME(logic)

        func_name_includes_types = SW_LIB.FUNC_NAME_INCLUDES_TYPES(logic)
        if not func_name_includes_types:
            for input_port in logic.inputs:
                c_type = logic.wire_to_c_type[input_port]
                key += "_" + c_type
    return key


def GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state):
    key = GET_CACHED_LOGIC_FILE_KEY(logic, parser_state)
    file_path = GET_PATH_DELAY_CACHE_DIR(parser_state) + "/" + key + ".delay"
    return file_path


def GET_CACHED_PATH_DELAY(logic, parser_state):
    if not logic.is_c_built_in and C_TO_LOGIC.FUNC_IS_OP_OVERLOAD(logic.func_name):
        return None

    # Look in cache dir
    file_path = GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state)
    if os.path.exists(file_path):
        # print "Reading Cached Delay File:", file_path
        return float(open(file_path, "r").readlines()[0])

    return None


def RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(start_insts, parser_state, funcs_to_synth=[]):
    # Recurse through submodules
    for start_inst in start_insts:
        func_logic = parser_state.LogicInstLookupTable[start_inst]
        for sub_inst in func_logic.submodule_instances:
            sub_inst_name = start_inst + C_TO_LOGIC.SUBMODULE_MARKER + sub_inst
            sub_logic = parser_state.LogicInstLookupTable[sub_inst_name]
            if func_logic.BODY_CAN_BE_SLICED(parser_state):
                if sub_logic.BODY_CAN_BE_SLICED(parser_state):
                    funcs_to_synth = RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(
                        [sub_inst_name], parser_state, funcs_to_synth
                    )
                if sub_logic.func_name not in funcs_to_synth:
                    funcs_to_synth.append(sub_logic.func_name)
    # Include start inst if MAIN
    for start_inst in start_insts:
        func_logic = parser_state.LogicInstLookupTable[start_inst]
        if func_logic.func_name in funcs_to_synth:
            continue
        if start_inst in parser_state.main_mhz:
            funcs_to_synth.append(func_logic.func_name)
    return funcs_to_synth


def ADD_PATH_DELAY_TO_LOOKUP(parser_state):
    # Make sure synthesis tool is set
    PART_SET_TOOL(parser_state.part)

    print("Synthesizing before pipelining to get path delays...", flush=True)
    print("", flush=True)
    TimingParamsLookupTable = GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
    multimain_timing_params = MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable

    # Re-write black box modules that are no longer in final state starting throughput sweep
    WRITE_BLACK_BOX_FILES(parser_state, multimain_timing_params, False)

    # Get the functions that need to be synthed for path delay
    funcs_to_synth = RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(
        parser_state.main_mhz.keys(), parser_state
    )

    # Record stats on functions with globals
    main_to_min_mhz = {}
    main_to_min_mhz_func_name = {}

    # Run multiple syn runs in parallel
    NUM_PROCESSES = int(
        open(C_TO_LOGIC.EXE_ABS_DIR() + "/../config/num_processes.cfg", "r").readline()
    )
    my_thread_pool = ThreadPool(processes=NUM_PROCESSES)
    func_name_to_async_result = {}
    func_names_done_so_far = set()

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
        # Prefer cache over model
        if cached_path_delay is not None:
            logic.delay = int(cached_path_delay * DELAY_UNIT_MULT)
            print(
                f"Function: {logic.func_name} cached path delay: {cached_path_delay:.3f} ns"
            )
            if cached_path_delay > 0.0 and logic.delay == 0:
                print("Have timing path of", cached_path_delay, "ns")
                print("...but recorded zero delay. Increase delay multiplier!")
                sys.exit(-1)
        elif modeled_path_delay is not None:
            logic.delay = int(modeled_path_delay * DELAY_UNIT_MULT)
            print(
                f"Function: {logic.func_name} modeled path delay: {modeled_path_delay:.3f} ns"
            )
        # Then check for known delays
        elif LOGIC_IS_ZERO_DELAY(logic, parser_state, allow_none_delay=True):
            logic.delay = 0

        # Prepare for syn to determine
        if logic.delay is None:
            # Run real syn in parallel
            print("Synthesizing function:", logic.func_name, flush=True)
            # Start Syn
            my_async_result = my_thread_pool.apply_async(
                SYN_TOOL.SYN_AND_REPORT_TIMING,
                (inst_name, logic, parser_state, TimingParamsLookupTable),
            )
            func_name_to_async_result[logic_func_name] = my_async_result
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
            print("...Waiting on synthesis for:", logic_func_name, flush=True)
            # TODO better than simple loop doing .get() on each and waiting some
            parsed_timing_report = my_async_result.get()
            # Sanity should be one path reported
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
                # if DO_SYN_FAIL_SIM:
                #  MODELSIM.DO_OPTIONAL_DEBUG(do_debug=True)
                sys.exit(-1)
            mhz = 1000.0 / path_report.path_delay_ns
            logic.delay = int(path_report.path_delay_ns * DELAY_UNIT_MULT)
            if logic.delay > 0 and logic.BODY_CAN_BE_SLICED(parser_state):
                print(
                    f"{logic_func_name} Path delay (maybe to be pipelined): {path_report.path_delay_ns:.3f} ns"
                )
            # Sanity check multiplier is working
            if path_report.path_delay_ns > 0.0 and logic.delay == 0:
                print("Have timing path of", path_report.path_delay_ns, "ns")
                print("...but recorded zero delay. Increase delay multiplier!")
                sys.exit(-1)
            # Make adjustment for 0 LLs to have 0 delay
            if (SYN_TOOL is VIVADO) and path_report.logic_levels == 0:
                logic.delay = 0
            # Cache delay syn result if not user code
            if not IS_USER_CODE(logic, parser_state):
                filepath = GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state)
                PATH_DELAY_CACHE_DIR = GET_PATH_DELAY_CACHE_DIR(parser_state)
                if not os.path.exists(PATH_DELAY_CACHE_DIR):
                    os.makedirs(PATH_DELAY_CACHE_DIR)
                f = open(filepath, "w")
                f.write(str(path_report.path_delay_ns))
                f.close()

        # Syn results are delay and clock
        # Try to communicate if is a problem path that cant be autopipelined
        if logic.delay > 0 and not logic.BODY_CAN_BE_SLICED(parser_state):
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

    # Write out final pictures requiring all delays in hierarchy to be computed above
    for logic_func_name in funcs_to_synth:
        logic = parser_state.FuncLogicLookupTable[logic_func_name]
        if logic.delay is None:
            print("None delay for func to synth?", logic_func_name)
        # What if do want pipeline map for something that will never be pipelined? --synth_all?
        if not logic.BODY_CAN_BE_SLICED(parser_state):
            continue
        if len(logic.submodule_instances) <= 0:
            continue
        if logic.is_vhdl_text_module:
            continue
        if logic.delay <= 0:
            continue
        # Any inst will do, skip func if was never used as instance
        if logic_func_name not in parser_state.FuncToInstances:
            continue
        inst_name = list(parser_state.FuncToInstances[logic_func_name])[0]
        # TODO make pipeline map return empty instead of check?
        zero_added_clks_pipeline_map = GET_ZERO_ADDED_CLKS_PIPELINE_MAP(
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
        # Picture too?
        zero_added_clks_pipeline_map.write_png(out_dir, parser_state)

    # Report worst timing modules
    for main_inst in main_to_min_mhz:
        min_mhz = main_to_min_mhz[main_inst]
        mhz = parser_state.main_mhz[main_inst]
        if mhz is not None and mhz > min_mhz:
            min_mhz_func_name = main_to_min_mhz_func_name[main_inst]
            print(
                f"Design likely limited to ~{min_mhz:.3f} MHz due to function: {min_mhz_func_name}"
            )
    WRITE_MODULE_INSTANCES_REPORT_BY_DELAY_USAGE(parser_state)

    return parser_state


def UPDATE_PIPELINE_MIN_PERIOD_CACHE(
    timing_report, TimingParamsLookupTable, parser_state, inst_name=None
):
    # Make dir if needed
    cache_dir = GET_PATH_DELAY_CACHE_DIR(parser_state, "pipeline_min_period_cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    # pipeline 'number' record in filename is size of largest slice 0..1.0
    # Find all pipelined cachable func instances
    cacheable_pipelined_instances = set()
    for func_inst, timing_params in TimingParamsLookupTable.items():
        func_logic = parser_state.LogicInstLookupTable[func_inst]
        # Cacheable non user code?
        if IS_USER_CODE(func_logic, parser_state):
            continue
        # Pipelined?
        if len(timing_params._slices) <= 0:
            continue
        # Func is inside the func inst being talked about?
        if inst_name:
            if func_inst.startswith(inst_name):
                cacheable_pipelined_instances.add(func_inst)
        else:
            cacheable_pipelined_instances.add(func_inst)

    # Organize timing report into main func -> period ns
    # Includes logic for inst name coarse or multi main top
    main_to_period = {}
    if len(parser_state.main_mhz) == 1:  # TODO --coarse like finding of main needed?
        the_main_inst = list(parser_state.main_mhz.keys())[0]
        if len(timing_report.path_reports) > 1:
            raise Exception("Should only be one path group in timing report!")
        main_to_period[the_main_inst] = list(timing_report.path_reports.values())[
            0
        ].path_delay_ns
    elif inst_name:
        the_main_inst = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
            inst_name, parser_state
        )
        if len(timing_report.path_reports) > 1:
            raise Exception("Should only be one path group in timing report!")
        main_to_period[the_main_inst] = list(timing_report.path_reports.values())[
            0
        ].path_delay_ns
    else:
        for reported_clock_group in timing_report.path_reports:
            path_report = timing_report.path_reports[reported_clock_group]
            some_main_insts = GET_MAIN_INSTS_FROM_PATH_REPORT(
                path_report, parser_state, TimingParamsLookupTable
            )
            for main_inst in some_main_insts:
                main_to_period[main_inst] = path_report.path_delay_ns

    # For each pipelined instance try to update cache with
    # period from its main func
    for func_inst in cacheable_pipelined_instances:
        timing_params = TimingParamsLookupTable[func_inst]
        func_logic = parser_state.LogicInstLookupTable[func_inst]
        main_inst = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(
            func_inst, parser_state
        )
        # Sometimes, especally when finally meeting timing,
        # the timing report might not have a critical path through
        # a cacheable pipelined instance
        # Could assume met timing, but for now just skip...
        if main_inst not in main_to_period:
            continue
        period_ns = main_to_period[main_inst]
        # Try to update cache
        # What is slicing, specifically largest slice?
        slice_sizes = RAW_VHDL.SLICES_TO_SIZE_LIST(timing_params._slices)
        max_slice_size = max(slice_sizes)
        func_key = GET_CACHED_LOGIC_FILE_KEY(func_logic, parser_state)
        # Does the file exist?
        out_filepath = cache_dir + "/" + func_key + f"_{max_slice_size:.2f}.delay"
        if not os.path.exists(out_filepath):
            f = open(out_filepath, "w")
            f.write(str(period_ns))
            f.close()
        # Enforce monotonic smaller slicing always increases fmax in cache
        func_cache_files = Path(cache_dir).glob(f"{func_key}*")
        for func_cache_filepath in func_cache_files:
            func_cache_file = os.path.basename(str(func_cache_filepath))
            cached_slice_size = float(
                func_cache_file.replace(".delay", "").split("_")[-1]
            )
            # those with smaller slices than current
            if cached_slice_size < max_slice_size:
                # Should have better timing
                f = open(func_cache_filepath, "r")
                cached_period_ns = float(f.read())
                f.close()
                # Update if not...
                if period_ns < cached_period_ns:
                    f = open(func_cache_filepath, "w")
                    f.write(str(period_ns))
                    f.close()
            # Those with larger slices should not be fast
            elif cached_slice_size > max_slice_size:
                # Should not have better timing
                f = open(func_cache_filepath, "r")
                cached_period_ns = float(f.read())
                f.close()
                # Update as needed
                if cached_period_ns < period_ns:
                    f = open(out_filepath, "w")
                    f.write(str(cached_period_ns))
                    f.close()


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


# Generalizing is a bad thing to do
# Abstracting is something more


def WRITE_ALL_ZERO_CLK_VHDL(parser_state, ZeroClkTimingParamsLookupTable):
    # All instances are zero clock so just pick any instance
    for func_name in parser_state.FuncLogicLookupTable:
        if func_name in parser_state.FuncToInstances:
            inst_name = list(parser_state.FuncToInstances[func_name])[0]
            logic = parser_state.FuncLogicLookupTable[func_name]
            # ONly write non vhdl
            if (
                logic.is_vhdl_func
                or logic.is_vhdl_expr
                or (logic.func_name == C_TO_LOGIC.VHDL_FUNC_NAME)
            ):
                continue
            # Dont write clock cross funcs
            if logic.is_clock_crossing:
                continue
            # Dont write FSM funcs
            if logic.is_fsm_clk_func:
                continue
            # print("Writing function:", func_name, "...", flush=True)
            syn_out_dir = GET_OUTPUT_DIRECTORY(logic)
            if not os.path.exists(syn_out_dir):
                os.makedirs(syn_out_dir, exist_ok=True)
            VHDL.WRITE_LOGIC_ENTITY(
                inst_name,
                logic,
                syn_out_dir,
                parser_state,
                ZeroClkTimingParamsLookupTable,
            )

    # Include a zero clock multi main top too
    print("Writing multi main top level files...", flush=True)
    multimain_timing_params = MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = ZeroClkTimingParamsLookupTable
    is_final_top = False
    VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top)
    # And clock cross entities
    VHDL.WRITE_CLK_CROSS_ENTITIES(parser_state, multimain_timing_params)


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
        for inst_name_i in inst_names:
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
            for submodule_inst in logic_i.submodule_instances:
                full_submodule_inst_name = (
                    inst_name_i + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
                )
                next_inst_names.add(full_submodule_inst_name)

        # Use next insts as current
        inst_names = set(next_inst_names)

    return files_txt, top_entity_name
