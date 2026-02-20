#!/usr/bin/env python

import copy
import difflib
import glob
import hashlib
import math
import os
import pickle
import subprocess
import sys

import C_TO_LOGIC
import MODELSIM
import SW_LIB
import SYN
import VHDL
from utilities import GET_TOOL_PATH

TOOL_EXE = "vivado"
# Default to path if there
ENV_TOOL_PATH = GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
    VIVADO_PATH = ENV_TOOL_PATH
    VIVADO_DIR = os.path.abspath(os.path.dirname(VIVADO_PATH) + "/../")
else:
    # Environment variable maybe?
    ENV_VIVADO_DIR = os.environ.get("XILINX_VIVADO")
    if ENV_VIVADO_DIR:
        VIVADO_DIR = ENV_VIVADO_DIR
    else:
        # then fallback to hardcoded
        VIVADO_DIR = "/media/1TB/Programs/Linux/Xilinx/Vivado/2019.2"
    VIVADO_PATH = VIVADO_DIR + "/bin/vivado"
VIVADO_VERSION = None

FIXED_PKG_PATH = VIVADO_DIR + "/scripts/rt/data/fixed_pkg_2008.vhd"

# Do full place and route for timing results
# for "all" modules or just the "top" module
DO_PNR = None  # None|"all"|"top"


class ParsedTimingReport:
    def __init__(self, syn_output):
        # Split into timing report and not
        split_marker = "Max Delay Paths\n--------------------------------------------------------------------------------------"
        split_marker_toks = syn_output.split(split_marker)
        single_timing_report = split_marker_toks[0]

        self.orig_text = syn_output
        self.reg_merged_with = {}  # dict[new_sig] = [orig,sigs]
        self.has_loops = True
        self.has_latch_loops = True

        # Parsing:
        syn_output_lines = single_timing_report.split("\n")
        prev_line = ""
        for syn_output_line in syn_output_lines:
            # LOOPS!
            if "There are 0 combinational loops in the design." in syn_output_line:
                self.has_loops = False
            if "There are 0 combinational latch loops in the design" in syn_output_line:
                self.has_latch_loops = False
            if "[Synth 8-295] found timing loop." in syn_output_line:
                # print single_timing_report
                print(syn_output_line)
                # print "FOUND TIMING LOOPS!"
                # print
                # Do debug?
                # latency=0
                # do_debug=True
                # print "ASSUMING LATENCY=",latency
                # MODELSIM.DO_OPTIONAL_DEBUG(do_debug, latency)
                # sys.exit(-1)
            if "inferred exception to break timing loop" in syn_output_line:
                print(syn_output_line)

            # Constant outputs?

            # Unconnected ports are maybe problem?
            if ("design " in syn_output_line) and (
                " has unconnected port " in syn_output_line
            ):
                if syn_output_line.endswith("unconnected port clk"):
                    # Clock NOT OK to disconnect
                    print("WARNING: Disconnected clock!?", syn_output_line)
                    # sys.exit(-1)
                # else:
                #  print syn_output_line

            # No driver?
            if ("Net " in syn_output_line) and (
                " does not have driver" in syn_output_line
            ):
                print(syn_output_line)

            # REG MERGING
            # INFO: [Synth 8-4471] merging register
            # Build dict of per bit renames
            tok1 = "INFO: [Synth 8-4471] merging register"
            if tok1 in syn_output_line:
                # Get left and right names
                """
                INFO: [Synth 8-4471] merging register 'main_registers_r_reg[submodules][BIN_OP_GT_main_c_12_registers][self][0][same_sign]' into 'main_registers_r_reg[submodules][BIN_OP_GT_main_c_8_registers][self][0][same_sign]' [/media/1TB/Dropbox/HaramNailuj/ZYBO/idea/single_timing_report/main/main_4CLK.vhd:25]
                INFO: [Synth 8-4471] merging register 'main_registers_r_reg[submodules][BIN_OP_GT_main_c_12_registers][self][1][left][31:0]' into 'main_registers_r_reg[submodules][BIN_OP_GT_main_c_8_registers][self][1][left][31:0]' [/media/1TB/Dropbox/HaramNailuj/ZYBO/idea/single_timing_report/main/main_4CLK.vhd:25]
                """
                # Split left and right on "into"
                line_toks = syn_output_line.split("' into '")
                left_text = line_toks[0]
                right_text = line_toks[1]
                left_reg_text = left_text.split("'")[1]
                right_reg_text = right_text.split("'")[0]
                # Do regs have a bit width or signal name?
                left_has_bit_width = ":" in left_reg_text
                right_has_bit_width = ":" in right_reg_text

                # Break a part brackets
                left_reg_toks = left_reg_text.split("[")
                right_reg_toks = right_reg_text.split("[")

                # Get left and right signal names per bit (if applicable)
                left_names = []
                if left_has_bit_width:
                    # What is bit width

                    # print left_reg_toks
                    width_str = left_reg_toks[len(left_reg_toks) - 1].strip("]")
                    width_toks = width_str.split(":")
                    left_index = int(width_toks[0])
                    right_index = int(width_toks[1])
                    start_index = min(left_index, right_index)
                    end_index = max(left_index, right_index)
                    # What is signal base name?
                    # print "width_str",width_str
                    left_name_no_bitwidth = left_reg_text.replace(
                        "[" + width_str + "]", ""
                    )
                    # print left_reg_text
                    # print "left_name_no_bitwidth",left_name_no_bitwidth
                    # Add to left names list
                    for i in range(start_index, end_index + 1):
                        left_name_with_bit = left_name_no_bitwidth + "[" + str(i) + "]"
                        left_names.append(left_name_with_bit)
                else:
                    # No bit width on signal
                    left_names.append(left_reg_text)

                right_names = []
                if right_has_bit_width:
                    # What is bit width
                    # print right_reg_text
                    # print right_reg_toks
                    width_str = right_reg_toks[len(right_reg_toks) - 1].strip("]")
                    width_toks = width_str.split(":")
                    left_index = int(width_toks[0])
                    right_index = int(width_toks[1])
                    start_index = min(left_index, right_index)
                    end_index = max(left_index, right_index)
                    # What is signal base name?
                    right_name_no_bitwidth = right_reg_text.replace(
                        "[" + width_str + "]", ""
                    )
                    # Add to right names list
                    for i in range(start_index, end_index + 1):
                        right_name_with_bit = (
                            right_name_no_bitwidth + "[" + str(i) + "]"
                        )
                        right_names.append(right_name_with_bit)
                else:
                    # No bit width on signal
                    right_names.append(right_reg_text)

                # print left_names[0:2]
                # print right_names[0:2]

                # Need same count
                if len(left_names) != len(right_names):
                    print("Reg merge len(left_names) != len(right_names) ??")
                    print("left_names", left_names)
                    print("right_names", right_names)
                    raise Exception("Reg: same count error")

                for i in range(0, len(left_names)):
                    if right_names[i] not in self.reg_merged_with:
                        self.reg_merged_with[right_names[i]] = []
                    self.reg_merged_with[right_names[i]].append(left_names[i])

            # SAVE PREV LINE
            prev_line = syn_output_line

        # LOOPS
        if self.has_loops or self.has_latch_loops:
            # print single_timing_report
            # print syn_output_line
            print("TIMING LOOPS!")

        # Parse multiple path reports
        self.path_reports = {}
        path_report_texts = split_marker_toks[1:]
        for path_report_text in path_report_texts:
            if "(required time - arrival time)" in path_report_text:
                path_report = PathReport(path_report_text)
                self.path_reports[path_report.path_group] = path_report

        if len(self.path_reports) == 0:
            print("Bad synthesis log?:", syn_output)
            raise Exception(f"Bad synthesis log?:{syn_output}")


class PathReport:
    def __init__(self, single_timing_report):
        # SINGLE TIMING REPORT STUFF  (single path report)
        self.logic_levels = 0
        self.slack_ns = None
        self.source_ns_per_clock = 0.0
        self.start_reg_name = None
        self.end_reg_name = None
        self.path_delay_ns = None
        self.logic_delay = None
        self.path_group = None
        self.netlist_resources = set()  # Set of strings

        # Parsing state
        in_netlist_resources = False

        # Parsing:
        syn_output_lines = single_timing_report.split("\n")
        prev_line = ""
        for syn_output_line in syn_output_lines:
            # LOGIC LEVELS
            tok1 = "Logic Levels:           "
            if tok1 in syn_output_line:
                self.logic_levels = int(
                    syn_output_line.replace(tok1, "").split("(")[0].strip()
                )

            # SLACK_NS
            tok1 = "Slack ("
            tok2 = "  (required time - arrival time)"
            if (tok1 in syn_output_line) and (tok2 in syn_output_line):
                slack_w_unit = (
                    syn_output_line.replace(tok1, "")
                    .replace(tok2, "")
                    .split(":")[1]
                    .strip()
                )
                slack_ns_str = slack_w_unit.strip("ns")
                self.slack_ns = float(slack_ns_str)

            # CLOCK PERIOD
            tok1 = "Source:                 "
            # tok2="                            (rising edge-triggered"
            tok2 = "{rise@0.000ns fall@"
            tok3 = "period="
            if (tok1 in prev_line) and (tok2 in syn_output_line):
                # print("Start reg?",prev_line)
                toks = syn_output_line.split(tok3)
                per_and_trash = toks[len(toks) - 1]
                period = per_and_trash.strip("ns})")
                self.source_ns_per_clock = float(period)
                # START REG
                self.start_reg_name = prev_line.replace(tok1, "").strip()
                # Remove everything after last "/"
                toks = self.start_reg_name.split("/")
                self.start_reg_name = "/".join(toks[0 : len(toks) - 1])
                # print("self.start_reg_name",self.start_reg_name)

            # END REG
            tok1 = "Destination:            "
            if (tok1 in prev_line) and (tok2 in syn_output_line):
                self.end_reg_name = prev_line.replace(tok1, "").strip()
                # Remove everything after last "/"
                toks = self.end_reg_name.split("/")
                self.end_reg_name = "/".join(toks[0 : len(toks) - 1])

            # Path group
            tok1 = "Path Group:"
            if tok1 in syn_output_line:
                self.path_group = syn_output_line.replace(tok1, "").strip()

            # Data path delay in report is not the total delay in the path
            tok1 = "  Requirement:            "
            if tok1 in syn_output_line:
                self.requirement_ns = float(
                    syn_output_line.replace(tok1, "").split(" ")[0].replace("ns", "")
                )
            tok1 = "Data Path Delay:        "
            if tok1 in syn_output_line:
                # self.path_delay_ns = self.source_ns_per_clock - self.slack_ns
                self.path_delay_ns = self.requirement_ns - self.slack_ns
                mcp_ratio = self.requirement_ns / self.source_ns_per_clock
                self.path_delay_ns /= mcp_ratio

            # LOGIC DELAY
            tok1 = "Data Path Delay:        "
            if tok1 in syn_output_line:
                self.logic_delay = float(
                    syn_output_line.split("  (logic ")[1].split("ns (")[0]
                )

            # Netlist resources
            tok1 = "    Location             Delay type                Incr(ns)  Path(ns)    "
            #   Set
            if tok1 in prev_line:
                in_netlist_resources = True
            if in_netlist_resources:
                # Parse resource
                start_offset = len(tok1)
                if len(syn_output_line) > start_offset:
                    resource_str = syn_output_line[start_offset:].strip()
                    if len(resource_str) > 0:
                        if "/" in resource_str:
                            # print "Resource: '",resource_str,"'"
                            self.netlist_resources.add(resource_str)
                # Reset
                tok1 = "                         slack"
                if tok1 in syn_output_line:
                    in_netlist_resources = False

            # SAVE PREV LINE
            prev_line = syn_output_line

        # Catch problems
        if self.slack_ns is None:
            raise Exception(f"Timing report error?\n{single_timing_report}")


# inst_name=None means multimain
def GET_SYN_IMP_AND_REPORT_TIMING_TCL(
    multimain_timing_params, parser_state, inst_name=None, is_final_top=False
):
    rv = ""

    # Add in VHDL 2008 fixed/float support for pre 2022.2
    # (currently the only reason why we need to know vivado version...)
    global VIVADO_VERSION
    if VIVADO_VERSION is None and os.path.exists(VIVADO_PATH):
        ver_output = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(VIVADO_PATH + " -version")
        VIVADO_VERSION = ver_output.split("\n")[0].split(" ")[1].strip("v")
    if VIVADO_VERSION:
        if float(VIVADO_VERSION) < 2022.2:
            rv += "add_files -norecurse " + FIXED_PKG_PATH + "\n"
            rv += (
                "set_property library ieee_proposed [get_files "
                + FIXED_PKG_PATH
                + "]\n"
            )

    # Bah tcl doesnt like brackets in file names
    # Becuase dumb

    # Single read vhdl line
    files_txt, top_entity_name = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(
        multimain_timing_params, parser_state, inst_name, is_final_top
    )
    rv += "read_vhdl -vhdl2008 -library work {" + files_txt + "}\n"

    # Write clock xdc and include it
    clk_xdc_filepath = SYN.WRITE_CLK_CONSTRAINTS_FILE(
        multimain_timing_params, parser_state, inst_name
    )
    # Single xdc with single clock for now
    rv += "read_xdc {" + clk_xdc_filepath + "}\n"

    ################
    # MSG Config
    #
    # ERROR WARNING: [Synth 8-312] ignoring unsynthesizable construct: non-synthesizable procedure call
    rv += "set_msg_config -id {Synth 8-312} -new_severity ERROR" + "\n"
    # ERROR WARNING: [Synth 8-614] signal is read in the process but is not in the sensitivity list
    rv += "set_msg_config -id {Synth 8-614} -new_severity ERROR" + "\n"
    # ERROR WARNING: [Synth 8-2489] overwriting existing secondary unit arch
    rv += "set_msg_config -id {Synth 8-2489} -new_severity ERROR" + "\n"
    # ERROR WARNING: [Vivado 12-584] No ports matched
    rv += "set_msg_config -id {Vivado 12-584} -new_severity ERROR" + "\n"
    # ERROR WARNING: [Vivado 12-507] No nets matched
    rv += "set_msg_config -id {Vivado 12-507} -new_severity ERROR" + "\n"
    # ERROR CRITICAL WARNING: [Vivado 12-4739] set_multicycle_path:No valid object(s)
    rv += "set_msg_config -id {Vivado 12-4739} -new_severity ERROR" + "\n"
    # ERROR WARNING: [Vivado 12-180] No cells matched
    rv += "set_msg_config -id {Vivado 12-180} -new_severity ERROR" + "\n"
    # ERROR CRITICAL WARNING: [Common 17-55] 'set_property' expects at least one object.
    rv += "set_msg_config -id {Common 17-55} -new_severity ERROR" + "\n"

    # CRITICAL WARNING WARNING: [Synth 8-326] inferred exception to break timing loop:
    rv += 'set_msg_config -id {Synth 8-326} -new_severity "CRITICAL WARNING"' + "\n"

    # Set high limit for these msgs
    # [Synth 8-4471] merging register
    rv += "set_msg_config -id {Synth 8-4471} -limit 10000" + "\n"
    # [Synth 8-3332] Sequential element removed
    rv += "set_msg_config -id {Synth 8-3332} -limit 10000" + "\n"
    # [Synth 8-3331] design has unconnected port
    rv += "set_msg_config -id {Synth 8-3331} -limit 10000" + "\n"
    # [Synth 8-5546] ROM won't be mapped to RAM because it is too sparse
    rv += "set_msg_config -id {Synth 8-5546} -limit 10000" + "\n"
    # [Synth 8-3848] Net in module/entity does not have driver.
    rv += "set_msg_config -id {Synth 8-3848} -limit 10000" + "\n"
    # [Synth 8-223] decloning instance
    rv += "set_msg_config -id {Synth 8-223} -limit 10000" + "\n"

    # Multi threading help? max is 8?
    rv += "set_param general.maxThreads 8" + "\n"

    # SYN OPTIONS
    retiming = ""
    use_retiming = False
    if use_retiming:
        retiming = " -retiming"

    flatten_hierarchy_none = ""
    use_flatten_hierarchy_none = False
    if use_flatten_hierarchy_none:
        flatten_hierarchy_none = " -flatten_hierarchy none"

    # SYNTHESIS@@@@@@@@@@@@@@!@!@@@!@
    rv += (
        "synth_design -mode out_of_context -top "
        + top_entity_name
        + " -part "
        + parser_state.part
        + flatten_hierarchy_none
        + retiming
        + "\n"
    )
    doing_pnr = DO_PNR == "all" or (DO_PNR == "top" and inst_name is None)
    if not doing_pnr:
        rv += "report_utilization\n"
    # Output dir
    if inst_name is None:
        output_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
    else:
        output_dir = SYN.GET_OUTPUT_DIRECTORY(
            parser_state.LogicInstLookupTable[inst_name]
        )

    # Synthesis Timing report maybe to file
    rv += "report_timing_summary -setup"
    # Put syn log in separate file if doing pnr
    if doing_pnr:
        rv += " -file " + output_dir + "/" + top_entity_name + ".syn.timing.log"
    rv += "\n"

    # Place and route
    if doing_pnr:
        rv += "place_design\n"
        rv += "route_design\n"
        rv += "report_utilization\n"
        rv += "report_timing_summary -setup\n"

    # Write checkpoint for top - not individual inst runs
    if inst_name is None:
        rv += "write_checkpoint " + output_dir + "/" + top_entity_name + ".dcp\n"

    return rv


# return path to tcl file
def WRITE_SYN_IMP_AND_REPORT_TIMING_TCL_FILE_MULTIMAIN(
    multimain_timing_params, parser_state
):
    syn_imp_and_report_timing_tcl = GET_SYN_IMP_AND_REPORT_TIMING_TCL(
        multimain_timing_params, parser_state
    )
    hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
    out_filename = SYN.TOP_LEVEL_MODULE + hash_ext + ".tcl"
    out_filepath = (
        SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE + "/" + out_filename
    )
    f = open(out_filepath, "w")
    f.write(syn_imp_and_report_timing_tcl)
    f.close()
    return out_filepath


# return path to tcl file
def WRITE_SYN_IMP_AND_REPORT_TIMING_TCL_FILE(
    inst_name, Logic, output_directory, TimingParamsLookupTable, parser_state
):
    # Make fake multimain params
    multimain_timing_params = SYN.MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable
    syn_imp_and_report_timing_tcl = GET_SYN_IMP_AND_REPORT_TIMING_TCL(
        multimain_timing_params, parser_state, inst_name
    )
    timing_params = TimingParamsLookupTable[inst_name]
    hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
    out_filename = (
        Logic.func_name
        + "_"
        + str(timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable))
        + "CLK"
        + hash_ext
        + ".syn.tcl"
    )
    out_filepath = output_directory + "/" + out_filename
    f = open(out_filepath, "w")
    f.write(syn_imp_and_report_timing_tcl)
    f.close()
    return out_filepath


# Returns parsed timing report
def SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params):
    # First create directory for this logic
    output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Set log path
    # Hash for multi main is just hash of main pipes
    hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
    log_path = output_directory + "/vivado" + hash_ext + ".log"

    # If log file exists dont run syn
    if os.path.exists(log_path):
        print("Reading log", log_path)
        f = open(log_path, "r")
        log_text = f.read()
        f.close()
    else:
        # O@O@()(@)Q@$*@($_!@$(@_$(
        # Here stands a moument to "[Synth 8-312] ignoring unsynthesizable construct: non-synthesizable procedure call"
        # meaning "procedure is named the same as the entity"
        VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params)

        # Write a syn tcl into there
        syn_imp_tcl_filepath = WRITE_SYN_IMP_AND_REPORT_TIMING_TCL_FILE_MULTIMAIN(
            multimain_timing_params, parser_state
        )

        # Execute vivado sourcing the tcl
        syn_imp_bash_cmd = (
            VIVADO_PATH + " "
            "-log "
            + log_path
            + " "
            + '-source "'
            + syn_imp_tcl_filepath
            + '" '
            + "-journal "
            + output_directory
            + "/vivado.jou"
            + " "
            + "-mode batch"
        )  # Quotes since I want to keep brackets in inst names

        print("Running:", log_path, flush=True)
        log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd)

    return ParsedTimingReport(log_text)


# Returns parsed timing report
def SYN_AND_REPORT_TIMING(
    inst_name,
    Logic,
    parser_state,
    TimingParamsLookupTable,
    total_latency=None,
    hash_ext=None,
    use_existing_log_file=True,
    is_final_top=False,
):
    # Timing params for this logic
    timing_params = TimingParamsLookupTable[inst_name]

    # First create syn/imp directory for this logic
    output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Set log path
    if hash_ext is None:
        hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
    if total_latency is None:
        total_latency = timing_params.GET_TOTAL_LATENCY(
            parser_state, TimingParamsLookupTable
        )
    log_path = (
        output_directory
        + "/vivado"
        + "_"
        + str(total_latency)
        + "CLK"
        + hash_ext
        + ".log"
    )
    # vivado -mode batch -source <your_Tcl_script>

    # Use same configs based on to speed up run time?
    log_to_read = log_path

    # If log file exists dont run syn
    if os.path.exists(log_to_read) and use_existing_log_file:
        # print "SKIPPED:", syn_imp_bash_cmd
        print("Reading log", log_to_read, flush=True)
        f = open(log_path, "r")
        log_text = f.read()
        f.close()
    else:
        # O@O@()(@)Q@$*@($_!@$(@_$(
        # Here stands a moument to "[Synth 8-312] ignoring unsynthesizable construct: non-synthesizable procedure call"
        # meaning "procedure is named the same as the entity"
        # VHDL.GENERATE_PACKAGE_FILE(Logic, parser_state, TimingParamsLookupTable, timing_params, output_directory)
        VHDL.WRITE_LOGIC_ENTITY(
            inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable
        )
        VHDL.WRITE_LOGIC_TOP(
            inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable
        )

        # Write xdc describing clock rate

        # Write a syn tcl into there
        syn_imp_tcl_filepath = WRITE_SYN_IMP_AND_REPORT_TIMING_TCL_FILE(
            inst_name, Logic, output_directory, TimingParamsLookupTable, parser_state
        )

        # Execute vivado sourcing the tcl
        syn_imp_bash_cmd = (
            VIVADO_PATH + " "
            "-log "
            + log_path
            + " "
            + '-source "'
            + syn_imp_tcl_filepath
            + '" '
            + "-journal "  # Quotes since I want to keep brackets in inst names
            + output_directory
            + "/vivado.jou"
            + " "
            + "-mode batch"
        )

        print("Running:", log_path, flush=True)
        log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd)

    return ParsedTimingReport(log_text)


def WRITE_AXIS_XO(parser_state):
    project_name = SYN.TOP_LEVEL_MODULE + "_project"
    ip_name = SYN.TOP_LEVEL_MODULE + "_ip"

    # Clocks
    clock_name_to_mhz, out_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
        parser_state, None, True
    )
    if len(clock_name_to_mhz) != 1:
        print(
            "Wrong number of clocks in design, can't write .xo packaging .tcl!",
            clock_name_to_mhz.keys(),
        )
        return
    clk_name = list(clock_name_to_mhz.keys())[0]

    # Scan MAIN IO for data,valid,ready
    # input_stream slave
    in_datas = set()
    in_valids = set()
    out_readys = set()
    # output_stream master
    out_datas = set()
    out_valids = set()
    in_readys = set()

    def sort_io_port(port_name, dir):
        if "data" in port_name:
            if dir == "in":
                in_datas.add(port_name)
            else:
                out_datas.add(port_name)
        if "valid" in port_name:
            if dir == "in":
                in_valids.add(port_name)
            else:
                out_valids.add(port_name)
        if "ready" in port_name:
            if dir == "in":
                in_readys.add(port_name)
            else:
                out_readys.add(port_name)

    for main_func in parser_state.main_mhz:
        main_func_logic = parser_state.LogicInstLookupTable[main_func]
        # Inputs
        for input_port in main_func_logic.inputs:
            port_name = main_func + "_" + input_port
            sort_io_port(port_name, "in")
        # Outputs
        for output_port in main_func_logic.outputs:
            port_name = main_func + "_" + output_port
            sort_io_port(port_name, "out")

    # Can only sort out one axis port for now
    axis_names_correct = True
    if len(in_datas) != 1:
        print("Wrong number of input AXIS data signals:", in_datas)
        axis_names_correct = False
    axis_data_in_name = list(in_datas)[0]
    if len(in_valids) != 1:
        print("Wrong number of input AXIS valid signals:", in_valids)
        axis_names_correct = False
    axis_valid_in_name = list(in_valids)[0]
    if len(out_readys) != 1:
        print("Wrong number of output AXIS ready signals:", out_readys)
        axis_names_correct = False
    axis_ready_out_name = list(out_readys)[0]
    #
    if len(out_datas) != 1:
        print("Wrong number of output AXIS data signals:", out_datas)
        axis_names_correct = False
    axis_data_out_name = list(out_datas)[0]
    if len(out_valids) != 1:
        print("Wrong number of output AXIS valid signals:", out_valids)
        axis_names_correct = False
    axis_valid_out_name = list(out_valids)[0]
    if len(in_readys) != 1:
        print("Wrong number of input AXIS ready signals:", in_readys)
        axis_names_correct = False
    axis_ready_in_name = list(in_readys)[0]
    if not axis_names_correct:
        print("Can't write AXIS .xo packaging .tcl!")
        return

    # Thanks Bartus!
    text = ""
    text += (
        """
set script_path [ file dirname [ file normalize [ info script ] ] ]
set script_path $script_path/..
set PIPELINEC_PROJ_DIR """
        + SYN.SYN_OUTPUT_DIRECTORY
        + """

"""
        + f"""
create_project {project_name} $script_path/{project_name} -part {parser_state.part} -force """
        + """
source ${PIPELINEC_PROJ_DIR}/read_vhdl.tcl
set_property file_type VHDL [get_files  ${PIPELINEC_PROJ_DIR}/"""
        + SYN.TOP_LEVEL_MODULE
        + "/"
        + SYN.TOP_LEVEL_MODULE
        + """.vhd]

update_compile_order -fileset sources_1 """
        + f"""
create_bd_design "{ip_name}"
create_bd_cell -type module -reference {SYN.TOP_LEVEL_MODULE} {SYN.TOP_LEVEL_MODULE}_0
make_bd_pins_external  [get_bd_cells {SYN.TOP_LEVEL_MODULE}_0]
make_bd_intf_pins_external  [get_bd_cells {SYN.TOP_LEVEL_MODULE}_0]
save_bd_design
validate_bd_design"""
        + f"""

make_wrapper -files [get_files $script_path/{project_name}/{project_name}.srcs/sources_1/bd/{ip_name}/{ip_name}.bd] -top
add_files -norecurse $script_path/{project_name}/{project_name}.gen/sources_1/bd/{ip_name}/hdl/{ip_name}_wrapper.v
set_property top {ip_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project -root_dir $script_path/ip_repo -vendor user.org -library user -taxonomy /UserIP -module {ip_name} -import_files + """
        + """
update_compile_order -fileset sources_1
set_property ipi_drc {ignore_freq_hz false} [ipx::find_open_core user.org:user:"""
        + ip_name
        + """:1.0]
set_property sdx_kernel true [ipx::find_open_core user.org:user:"""
        + ip_name
        + """:1.0]
set_property sdx_kernel_type rtl [ipx::find_open_core user.org:user:"""
        + ip_name
        + """:1.0]
set_property vitis_drc {ctrl_protocol ap_ctrl_none} [ipx::find_open_core user.org:user:"""
        + ip_name
        + """:1.0]
set_property ipi_drc {ignore_freq_hz true} [ipx::find_open_core user.org:user:"""
        + ip_name
        + """:1.0]"""
        + """

#source sources/utils.tcl
proc map_clock {axi_clk} {"""
        + f"""
    ipx::infer_bus_interface $axi_clk xilinx.com:signal:clock_rtl:1.0 [ipx::find_open_core user.org:user:{ip_name}:1.0]
    ipx::add_bus_parameter FREQ_TOLERANCE_HZ [ipx::get_bus_interfaces $axi_clk -of_objects [ipx::current_core]]
    set_property value -1 [ipx::get_bus_parameters FREQ_TOLERANCE_HZ -of_objects [ipx::get_bus_interfaces $axi_clk -of_objects [ipx::current_core]]]
"""
        + """}
proc map_axi_stream {data valid ready axi_clock port_name axi_type} {"""
        + f"""
    ipx::add_bus_interface $port_name [ipx::find_open_core user.org:user:{ip_name}:1.0]
    set_property abstraction_type_vlnv xilinx.com:interface:axis_rtl:1.0 [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]
    set_property interface_mode $axi_type [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]
    set_property bus_type_vlnv xilinx.com:interface:axis:1.0 [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]
    ipx::add_port_map TDATA [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]
    set_property physical_name $data [ipx::get_port_maps TDATA -of_objects [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]]
    ipx::add_port_map TVALID [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]
    set_property physical_name $valid [ipx::get_port_maps TVALID -of_objects [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]]
    ipx::add_port_map TREADY [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]
    set_property physical_name $ready [ipx::get_port_maps TREADY -of_objects [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:{ip_name}:1.0]]]
    ipx::associate_bus_interfaces -busif $port_name -clock $axi_clock [ipx::find_open_core user.org:user:{ip_name}:1.0]"""
        + """
}"""
        + f"""

map_clock {clk_name}_0
map_axi_stream {axis_data_in_name}_0 {axis_valid_in_name}_0 {axis_ready_out_name}_0 {clk_name}_0 input_stream slave
map_axi_stream {axis_data_out_name}_0 {axis_valid_out_name}_0 {axis_ready_in_name}_0 {clk_name}_0 output_stream master

set_property core_revision 1 [ipx::find_open_core user.org:user:{ip_name}:1.0]
ipx::create_xgui_files [ipx::find_open_core user.org:user:{ip_name}:1.0]
ipx::update_checksums [ipx::find_open_core user.org:user:{ip_name}:1.0]
ipx::check_integrity -kernel -xrt [ipx::find_open_core user.org:user:{ip_name}:1.0]
ipx::save_core [ipx::find_open_core user.org:user:{ip_name}:1.0]
package_xo  -xo_path $script_path/xo/{ip_name}.xo -kernel_name {ip_name} -ip_directory $script_path/ip_repo -ctrl_protocol ap_ctrl_none -force
update_ip_catalog
ipx::check_integrity -quiet -kernel -xrt [ipx::find_open_core user.org:user:{ip_name}:1.0]
ipx::archive_core $script_path/ip_repo/user.org_user_{ip_name}_1.0.zip [ipx::find_open_core user.org:user:{ip_name}:1.0]    
    """
    )

    out_filename = "package_axis_xo.tcl"
    out_filepath = SYN.SYN_OUTPUT_DIRECTORY + "/" + out_filename
    print("AXIS .xo packaging TCL Script:", out_filepath)
    f = open(out_filepath, "w")
    f.write(text)
    f.close()
