#!/usr/bin/env python

import copy
import difflib
import glob
import hashlib
import json
from pathlib import Path
import math
import os
import pickle
import re
import subprocess
import sys
import time

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
VIVADO_VERSION_ID = None
# Part used when this tool is selected without a part (--syn_tool/SYN_TOOL()
# with no --part/PART()). See SYN.RESOLVE_PART_AND_TOOL.
DEFAULT_PART = "xc7a35ticsg324-1l"


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
        self.utilization = PARSE_UTILIZATION(syn_output)
        self.extra_paths, self.coverage = PARSE_EXTRA_PATHS(syn_output)
        report_times = re.findall(r"^PYPELINEC_REPORT_MS (\d+)$", syn_output, re.M)
        self.optional_report_ms = int(report_times[-1]) if report_times else None
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

        if len(self.path_reports) == 0 and self.utilization["status"] != "over_capacity":
            print("Bad synthesis log?:", syn_output)
            raise Exception(f"Bad synthesis log?:{syn_output}")


def PARSE_UTILIZATION(text):
    """Capacity evidence: over_capacity / within_reported_limits / unknown.

    Keeps requested overflow (Synth 8-3323) even when final mapping spills
    back under capacity.
    """
    warnings = []
    for resource, used, available in re.findall(
        r"Resources of type (\S+) have been overutilized\. Used = ([\d,]+), Available = ([\d,]+)",
        text,
    ):
        row = {
            "resource": resource,
            "used": int(used.replace(",", "")),
            "available": int(available.replace(",", "")),
        }
        if row not in warnings:
            warnings.append(row)
    resources = {}
    # Columns by header name: Vivado 2019.2 prints
    # Site Type | Used | Fixed | Available | Util%; newer releases add
    # Prohibited. Rows are read only under a "Site Type" header.
    columns = None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [s.strip() for s in line.strip().strip("|").split("|")]
        if cells and cells[0] == "Site Type":
            columns = {name: i for i, name in enumerate(cells)}
            if "Used" not in columns or "Available" not in columns:
                columns = None
            continue
        if columns is None or len(cells) != len(columns):
            continue
        used, available = cells[columns["Used"]], cells[columns["Available"]]
        if not (re.fullmatch(r"[\d,]+", used) and re.fullmatch(r"[\d,]+", available)):
            continue
        name = cells[0].rstrip("*").strip()
        row = {
            "used": int(used.replace(",", "")),
            "available": int(available.replace(",", "")),
        }
        resources[name] = row
    over = warnings + [
        dict(resource=k, **v)
        for k, v in resources.items()
        if v["used"] > v["available"]
    ]
    return {
        "status": "over_capacity"
        if over
        else "within_reported_limits"
        if resources
        else "unknown",
        "resources": resources,
        "overutilization": warnings,
    }


class ParsedUtilizationReport:
    """Diagnostic-only resource counts from the report_utilization output
    already present in every Vivado synthesis log (never LUT/FF/DSP parsed
    anywhere else in this codebase -- see docs/operator_qor_report.md). Used
    by src/tests/pypeline_tests/op_qor_bench.py to explain surprising timing
    results (e.g. a soft adder that looks fast because synthesis optimized
    an operator away); never used to decide a QoR winner -- that is timing
    (ParsedTimingReport.path_delay_ns) only."""

    def __init__(self, syn_output):
        self.slice_luts = None
        self.slice_registers = None
        self.carry4 = None
        lines = syn_output.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("| Slice LUTs"):
                toks = [t.strip() for t in stripped.strip("|").split("|")]
                if len(toks) >= 2 and toks[1].isdigit():
                    self.slice_luts = int(toks[1])
            elif stripped.startswith("| Slice Registers"):
                toks = [t.strip() for t in stripped.strip("|").split("|")]
                if len(toks) >= 2 and toks[1].isdigit():
                    self.slice_registers = int(toks[1])
            elif stripped.startswith("| CARRY4"):
                toks = [t.strip() for t in stripped.strip("|").split("|")]
                if len(toks) >= 2 and toks[1].isdigit():
                    self.carry4 = int(toks[1])


class PathReport:
    def __init__(self, single_timing_report):
        # SINGLE TIMING REPORT STUFF  (single path report)
        self.logic_levels = 0
        self.slack_ns = None
        self.source_ns_per_clock = 0.0
        self.start_reg_name = None
        self.end_reg_name = None
        self.start_pin_name = None
        self.end_pin_name = None
        self.start_cell_type = None
        self.end_cell_type = None
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
                self.start_pin_name = toks[-1]
                cell_type = re.search(r"cell (\S+) clocked by", syn_output_line)
                self.start_cell_type = cell_type.group(1) if cell_type else None
                self.start_reg_name = "/".join(toks[0 : len(toks) - 1])
                # print("self.start_reg_name",self.start_reg_name)

            # END REG
            tok1 = "Destination:            "
            if (tok1 in prev_line) and (tok2 in syn_output_line):
                self.end_reg_name = prev_line.replace(tok1, "").strip()
                # Remove everything after last "/"
                toks = self.end_reg_name.split("/")
                self.end_pin_name = toks[-1]
                cell_type = re.search(r"cell (\S+) clocked by", syn_output_line)
                self.end_cell_type = cell_type.group(1) if cell_type else None
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
    global VIVADO_VERSION, VIVADO_VERSION_ID
    if VIVADO_VERSION is None and os.path.exists(VIVADO_PATH):
        ver_output = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(VIVADO_PATH + " -version")
        VIVADO_VERSION_ID = ver_output.strip()
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

    rv += EXTRA_PATHS_TCL(multimain_timing_params, parser_state, inst_name)

    # Write checkpoint for top - not individual inst runs
    if inst_name is None:
        rv += "write_checkpoint " + output_dir + "/" + top_entity_name + ".dcp\n"

    rv += 'puts "PYPELINEC_SYNTHESIS_COMPLETE"\n'
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
    import AUTO_PIPELINE

    # Make fake multimain params
    multimain_timing_params = AUTO_PIPELINE.MultiMainTimingParams()
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


def INPUT_MANIFEST(tcl, part, tool_version, output_root):
    """Synthesis input identity: HDL/XDC bytes, part, tool version and the
    normalized Tcl recipe, independent of output-directory spelling. See
    docs/SYN_DESIGN.md#6-caches."""
    inputs = []
    normalized = tcl
    groups = re.findall(r"read_vhdl[^\n]*?\{([^}]+)\}", tcl)
    paths = [p for group in groups for p in group.split()]
    paths += re.findall(r"read_xdc\s+\{([^}]+)\}", tcl)
    paths += [
        s.strip().strip("{}")
        for s in re.findall(r"^add_files -norecurse (.+)$", tcl, re.M)
    ]
    xdc = {}
    # Longest first, so a path that prefixes another is never mis-replaced.
    for filename in sorted(set(paths), key=lambda f: (-len(f), f)):
        content_hash = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
        kind = (
            "xdc" if filename in re.findall(r"read_xdc\s+\{([^}]+)\}", tcl) else "hdl"
        )
        inputs.append(
            {"name": Path(filename).name, "kind": kind, "sha256": content_hash}
        )
        normalized = normalized.replace(filename, "@input/" + kind + "/" + content_hash)
        if kind == "xdc":
            xdc[Path(filename).name] = content_hash
    normalized = normalized.replace(str(output_root), "@output")
    manifest = {
        "schema_version": 1,
        "part": part,
        "tool_version": tool_version,
        "inputs": sorted(inputs, key=lambda v: (v["kind"], v["name"], v["sha256"])),
        "xdc_hash": SYN.JSON_DIGEST(xdc),
        "recipe_hash": hashlib.sha256(normalized.encode()).hexdigest(),
    }
    manifest["signature"] = SYN.JSON_DIGEST(manifest)
    return manifest


def _WITHOUT_OPTIONAL_SECTIONS(text):
    """Drop output between the optional-report markers (errors there are
    caught in Tcl and only make optional evidence unavailable)."""
    return re.sub(
        r"^PYPELINEC_OPTIONAL_BEGIN\s*$.*?^PYPELINEC_OPTIONAL_END\s*$",
        "",
        text,
        flags=re.M | re.S,
    )


def REQUIRE_COMPLETE_LOG(text, path):
    required = _WITHOUT_OPTIONAL_SECTIONS(text)
    if re.search(r"^ERROR:", required, re.M) or not re.search(
        r"^PYPELINEC_SYNTHESIS_COMPLETE\s*$", required, re.M
    ):
        # Place and route typically fails outright on an over-capacity design:
        # say so, instead of only "errored" (synthesis warnings are still in the log).
        overflow = PARSE_UTILIZATION(text)["overutilization"]
        capacity = (
            " DOES NOT FIT: requested "
            + ", ".join(f"{r['resource']} {r['used']}/{r['available']}" for r in overflow)
            + "."
            if overflow
            else ""
        )
        raise RuntimeError(
            "Synthesis log is errored or incomplete: "
            + str(path)
            + "."
            + capacity
            + " Preserved; inspect and move this exact log aside before retrying. No automatic rerun."
        )


def _RUN_IDENTIFIED(
    parser_state,
    params,
    output_directory,
    stem,
    inst_name=None,
    is_final_top=False,
    use_existing_log_file=True,
):
    started = time.monotonic()
    tcl = GET_SYN_IMP_AND_REPORT_TIMING_TCL(
        params, parser_state, inst_name, is_final_top
    )
    manifest = INPUT_MANIFEST(
        tcl,
        parser_state.part,
        VIVADO_VERSION_ID or VIVADO_VERSION,
        SYN.SYN_OUTPUT_DIRECTORY,
    )
    suffix = manifest["signature"][:16]
    base = Path(output_directory) / (stem + "_" + suffix)
    log_path = str(base) + ".log"
    tcl_path = str(base) + ".tcl"
    # Checkpoints and journals belong to the same observation as its log.
    tcl = re.sub(
        r"^write_checkpoint .*?$",
        "write_checkpoint {" + str(base) + ".dcp}",
        tcl,
        flags=re.M,
    )
    hit = os.path.exists(log_path)
    if hit:
        # Never overwrite a failed/partial log, including explicit force callers.
        log_text = Path(log_path).read_text()
        REQUIRE_COMPLETE_LOG(log_text, log_path)
        if not use_existing_log_file:
            raise RuntimeError(
                "Existing synthesis artifact preserved: "
                + log_path
                + "; move it aside explicitly before requesting a rerun"
            )
        print("Reading log", log_path, flush=True)
    else:
        Path(tcl_path).write_text(tcl)
        Path(str(base) + ".inputs.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
        print("Running:", log_path, flush=True)
        result = subprocess.run(
            [
                VIVADO_PATH,
                "-log",
                log_path,
                "-source",
                tcl_path,
                "-journal",
                str(base) + ".jou",
                "-mode",
                "batch",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_text = (
            Path(log_path).read_text() if Path(log_path).exists() else result.stdout
        )
        REQUIRE_COMPLETE_LOG(log_text, log_path)
        if result.returncode:
            raise RuntimeError(
                "Vivado exited " + str(result.returncode) + ": " + log_path
            )
    report = ParsedTimingReport(log_text)
    report.log_path = log_path
    report.input_signature = manifest["signature"]
    report.cache_hit = hit
    report.elapsed_seconds = time.monotonic() - started
    return report


def SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params):
    import AUTO_MULTI_CYCLE

    output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
    os.makedirs(output_directory, exist_ok=True)
    VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params)
    report = _RUN_IDENTIFIED(
        parser_state,
        multimain_timing_params,
        output_directory,
        "vivado" + multimain_timing_params.GET_HASH_EXT(parser_state),
    )
    import SWEEP

    over = report.utilization["status"] == "over_capacity"
    if not (SWEEP.STOP_ON_OVER_CAPACITY and over):
        try:
            AUTO_MULTI_CYCLE.CHECK_MCP_TIMING_REPORT(
                report, parser_state, multimain_timing_params
            )
        except ValueError as error:
            if not over:
                raise
            # Default (no fit stop): say why the netlist may be unusable
            # before the MCP coverage error ends the build.
            overflow = ", ".join(
                f"{r['resource']} {r['used']}/{r['available']}"
                for r in report.utilization["overutilization"]
            ) or "final utilization table"
            raise ValueError(
                f"{error} NOTE: this netlist is over device capacity ({overflow}); "
                "over-capacity mapping can change or remove MCP endpoints. "
                "Consider --stop_on_over_capacity."
            ) from error
    return report


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
    import AUTO_MULTI_CYCLE
    import AUTO_PIPELINE

    tp = TimingParamsLookupTable[inst_name]
    output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)
    os.makedirs(output_directory, exist_ok=True)
    if hash_ext is None:
        hash_ext = tp.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
    if total_latency is None:
        total_latency = tp.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
    VHDL.WRITE_LOGIC_ENTITY(
        inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable
    )
    VHDL.WRITE_LOGIC_TOP(
        inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable
    )
    params = AUTO_PIPELINE.MultiMainTimingParams()
    params.TimingParamsLookupTable = TimingParamsLookupTable
    report = _RUN_IDENTIFIED(
        parser_state,
        params,
        output_directory,
        "vivado_" + str(total_latency) + "CLK" + hash_ext,
        inst_name,
        is_final_top,
        use_existing_log_file,
    )
    AUTO_MULTI_CYCLE.CHECK_MCP_TIMING_REPORT(report, parser_state, params, inst_name)
    # Only endpoint-qualified reports may seed automatic cycle counts later.
    AUTO_MULTI_CYCLE.REMEMBER_ISOLATED_REPORTS(report, parser_state, params, inst_name)
    return report


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


def EXTRA_PATHS_TCL(params, parser_state, top_inst=None):
    """Bounded optional evidence. Query filters do not change timing constraints."""
    import AUTO_MULTI_CYCLE

    # Everything below is optional evidence. It runs inside markers and a Tcl
    # catch: a failure here must never error the synthesis log (which would
    # block reuse and retries), only make this evidence unavailable. See
    # REQUIRE_COMPLETE_LOG / PARSE_EXTRA_PATHS.
    text = r"""
puts "PYPELINEC_OPTIONAL_BEGIN"
if {[catch {
set pypeline_extra_started [clock milliseconds]
proc pypeline_paths {scope paths limit} {
    puts [join [list PYPELINEC_COVERAGE $scope [llength $paths] $limit] "\t"]
    foreach p $paths {
        set src [get_property STARTPOINT_PIN $p]
        set dst [get_property ENDPOINT_PIN $p]
        set clock [get_clocks -quiet [get_property STARTPOINT_CLOCK $p]]
        if {[llength $clock] != 1} {continue}
        set period [get_property PERIOD $clock]
        set sc [get_cells -quiet -of_objects [get_pins -quiet $src]]
        set dc [get_cells -quiet -of_objects [get_pins -quiet $dst]]
        set st ""; set dt ""
        if {[llength $sc] == 1} {set st [get_property REF_NAME $sc]}
        if {[llength $dc] == 1} {set dt [get_property REF_NAME $dc]}
        puts [join [list PYPELINEC_PATH $scope [get_property GROUP $p] \
            [get_property SLACK $p] [get_property REQUIREMENT $p] \
            [get_property DATAPATH_DELAY $p] [get_property LOGIC_LEVELS $p] \
            $period $src $dst $st $dt] "\t"]
    }
}
"""
    tpl = params.TimingParamsLookupTable
    roots = [top_inst] if top_inst is not None else sorted(parser_state.main_mhz)
    for root in roots:
        entity = VHDL.GET_ENTITY_NAME(
            root, parser_state.LogicInstLookupTable[root], tpl, parser_state
        )
        if top_inst is None:
            text += f"set pypeline_cells [get_cells -quiet -hier -filter {{NAME =~ {entity}/* && IS_SEQUENTIAL}}]\n"
            text += f"if {{[llength $pypeline_cells]}} {{pypeline_paths {{main:{root}}} [get_timing_paths -quiet -to $pypeline_cells -max_paths 1] 1}}\n"
        for inst in sorted(parser_state.LogicInstLookupTable):
            if inst != root and not inst.startswith(root + C_TO_LOGIC.SUBMODULE_MARKER):
                continue
            for tup, start, end, auto in AUTO_MULTI_CYCLE.GET_MCP_CELL_PATHS(
                inst, root, entity, parser_state
            ):
                # Each physical pair is separately queried, including replicated groups.
                scope = "mcp:" + inst + ":" + tup[1] + ":" + tup[2]
                # The same /C -> /D pins the set_multicycle_path exception uses:
                # a cell-to-cell worst path may end on CE/R, which that
                # exception (and MCP evidence) does not cover.
                text += f"set pypeline_launch [get_pins -quiet {{{start}/C}}]\nset pypeline_capture [get_pins -quiet {{{end}/D}}]\n"
                text += f"if {{[llength $pypeline_launch] && [llength $pypeline_capture]}} {{pypeline_paths {{{scope}}} [get_timing_paths -quiet -from $pypeline_launch -to $pypeline_capture -max_paths 1] 1}}\n"
    if top_inst is None:
        text += "pypeline_paths failing [get_timing_paths -quiet -max_paths 4096 -nworst 1 -slack_lesser_than 0] 4096\n"
    text += 'puts "PYPELINEC_REPORT_MS [expr {[clock milliseconds] - $pypeline_extra_started}]"\n'
    text += '} pypeline_optional_error]} {puts [join [list PYPELINEC_OPTIONAL_ERROR $pypeline_optional_error] "\\t"]}\n'
    text += 'puts "PYPELINEC_OPTIONAL_END"\n'
    return text


def PARSE_EXTRA_PATHS(text):
    from types import SimpleNamespace

    paths, coverage = [], {}
    for line in text.splitlines():
        cols = line.split("\t")
        if cols[0] == "PYPELINEC_COVERAGE" and len(cols) == 4:
            scope, count, limit = cols[1], int(cols[2]), int(cols[3])
            coverage[scope] = dict(
                count=count,
                limit=limit,
                truncated=scope == "failing" and count >= limit,
                complete=scope == "failing" and count < limit,
            )
        elif cols[0] == "PYPELINEC_OPTIONAL_ERROR":
            # The optional queries failed inside their Tcl catch: no evidence.
            coverage["optional_error"] = dict(
                count=0, limit=0, truncated=False, complete=False,
                error="\t".join(cols[1:]),
            )
        elif cols[0] == "PYPELINEC_PATH" and len(cols) == 12:
            (
                _,
                scope,
                group,
                slack,
                requirement,
                data,
                levels,
                period,
                src,
                dst,
                st,
                dt,
            ) = cols
            slack, requirement, data, period = map(
                float, (slack, requirement, data, period)
            )
            if requirement <= 0 or period <= 0 or requirement - slack <= 0:
                continue  # unsupported/non-setup timing is not evidence of a pass
            start, _, spin = src.rpartition("/")
            end, _, epin = dst.rpartition("/")
            paths.append(
                SimpleNamespace(
                    scope=scope,
                    path_group=group,
                    slack_ns=slack,
                    requirement_ns=requirement,
                    data_path_ns=data,
                    logic_levels=int(levels),
                    source_ns_per_clock=period,
                    path_delay_ns=(requirement - slack) / (requirement / period),
                    start_reg_name=start or src,
                    end_reg_name=end or dst,
                    start_pin_name=spin,
                    end_pin_name=epin,
                    start_cell_type=st,
                    end_cell_type=dt,
                    netlist_resources=set(),
                    logic_delay=data,
                )
            )
    for scope, row in coverage.items():
        row["parsed_count"] = sum(path.scope == scope for path in paths)
        row["complete"] = row["complete"] and row["parsed_count"] == row["count"]
    return paths, coverage
