import os
import shutil
import sys

import C_TO_LOGIC
import SYN
import VHDL
from utilities import GET_TOOL_PATH

# Tool path constants
TOOL_EXE = "p_r"
# Default to env if there
ENV_TOOL_PATH = GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
    CC_TOOLS_PR_PATH = ENV_TOOL_PATH
    CC_TOOLS_PATH = os.path.abspath(os.path.dirname(CC_TOOLS_PR_PATH) + "../../")
else:
    CC_TOOLS_PATH = "/media/1TB/Programs/Linux/cc-toolchain-linux_01.09.2024"


class ParsedTimingReport:
    def __init__(self, syn_output):
        path_report = PathReport(syn_output)
        self.path_reports = dict()
        self.path_reports[path_report.path_group] = path_report
        if len(self.path_reports) == 0:
            raise Exception(f"Bad synthesis log?:\n{syn_output}")


class PathReport:
    def __init__(self, path_report_text):
        self.path_delay_ns = None  # nanoseconds
        # Fake clock info since no clock constrainted existed?
        self.path_group = "clk"
        self.slack_ns = None
        self.source_ns_per_clock = None  # From latch edge time
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None
        for line in path_report_text.split("\n"):
            tok = "Maximum Clock Frequency"
            if tok in line:
                #print(line)
                fmax_mhz = float(line.split(":")[1].strip().split(" ")[0])
                #print("fmax_mhz",fmax_mhz)
                self.path_delay_ns = 1000.0 / fmax_mhz


# Returns parsed timing report
def SYN_AND_REPORT_TIMING(
    inst_name,
    Logic,
    parser_state,
    TimingParamsLookupTable,
    total_latency=None,
    hash_ext=None,
    use_existing_log_file=True,
):
    multimain_timing_params = SYN.MultiMainTimingParams()
    multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable
    return SYN_AND_REPORT_TIMING_NEW(
        parser_state,
        multimain_timing_params,
        inst_name,
        total_latency,
        hash_ext,
        use_existing_log_file,
    )


# Returns parsed timing report
def SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params):
    return SYN_AND_REPORT_TIMING_NEW(parser_state, multimain_timing_params)


# MULTIMAIN OR SINGLE INSTANCE
# Returns parsed timing report
def SYN_AND_REPORT_TIMING_NEW(
    parser_state,
    multimain_timing_params,
    inst_name=None,
    total_latency=None,
    hash_ext=None,
    use_existing_log_file=True,
):
    # Which vhdl files?
    vhdl_files_texts, top_entity_name = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(
        multimain_timing_params, parser_state, inst_name
    )
    log_file_name = top_entity_name + ".log"
    # Single inst
    if inst_name:
        Logic = parser_state.LogicInstLookupTable[inst_name]
        # First create syn/imp directory for this logic
        output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)
    else:
        # Multimain
        # First create directory for this logic
        output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    log_path = output_directory + "/" + log_file_name
    syn_log_path = output_directory + "/syn_" + log_file_name # Need separate logs?
    # Use same configs based on to speed up run time?
    log_to_read = log_path

    # If log file exists dont run syn
    if os.path.exists(log_to_read) and use_existing_log_file:
        # print "SKIPPED:", syn_imp_bash_cmd
        print("Reading log", log_to_read)
        f = open(log_path, "r")
        log_text = f.read()
        f.close()
        return ParsedTimingReport(log_text)
    # Not from log:

    # Write top level vhdl for this module/multimain
    if inst_name:
        VHDL.WRITE_LOGIC_ENTITY(
            inst_name,
            Logic,
            output_directory,
            parser_state,
            multimain_timing_params.TimingParamsLookupTable,
        )
        VHDL.WRITE_LOGIC_TOP(
            inst_name,
            Logic,
            output_directory,
            parser_state,
            multimain_timing_params.TimingParamsLookupTable,
        )
    else:
        VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params)

    # Generate files for this SYN

    # Write clock constraint and include it
    constraints_filepath = SYN.WRITE_CLK_CONSTRAINTS_FILE(parser_state, inst_name)
    clk_to_mhz, constraints_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
        parser_state, inst_name
    )

    # Generate build scripts
    # TODO dont base on cc-toolchain directory?
    CC_TOOLS_YOSYS = CC_TOOLS_PATH + "/bin/yosys/yosys"
    CC_TOOLS_PR = CC_TOOLS_PATH + "/bin/p_r/p_r"
    CC_TOOLS_PR_FLAGS = f"-ccf {constraints_filepath}" #-cCP?
    temp_local_out_dir = CC_TOOLS_PATH + "/workspace/pipelinec_temp_"+top_entity_name
    shutil.rmtree(temp_local_out_dir, ignore_errors=True)
    os.makedirs(temp_local_out_dir)
    os.makedirs(f"{output_directory}/net")
    sh_text = ""
    sh_text += f"""
#!/bin/bash
{CC_TOOLS_YOSYS} -ql {syn_log_path} -p 'ghdl --std=08 --warn-no-binding -C --ieee=synopsys {vhdl_files_texts} -e {top_entity_name}; synth_gatemate -top {top_entity_name} -nomx8 -vlog {output_directory}/net/{top_entity_name}_synth.v' &> /dev/null
{CC_TOOLS_PR} -i {output_directory}/net/{top_entity_name}_synth.v -o {top_entity_name} {CC_TOOLS_PR_FLAGS} &> {log_path}
"""
    sh_file = top_entity_name + ".sh"
    sh_path = output_directory + "/" + sh_file
    f = open(sh_path, "w")
    f.write(sh_text)
    f.close()

    # Run the build script 
    print("Running CC_TOOLS:", sh_path, flush=True)
    syn_imp_bash_cmd = (
        "bash " + sh_path
    )
    C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=temp_local_out_dir)
    f = open(log_path, "r")
    log_text = f.read()
    f.close()
    shutil.rmtree(temp_local_out_dir, ignore_errors=True)
    return ParsedTimingReport(log_text)
