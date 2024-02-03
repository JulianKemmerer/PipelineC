import os

import C_TO_LOGIC
import SYN
import VHDL
from utilities import GET_TOOL_PATH

TOOL_EXE = "gw_sh"
# Default to env if there
ENV_TOOL_PATH = GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
    GOWIN_PATH = os.path.abspath(os.path.dirname(ENV_TOOL_PATH))
else:
    GOWIN_PATH = "/todo/install/gowin/tools"

class ParsedTimingReport:
    def __init__(self, syn_output):
        # Split report into individual paths
        path_tok = "						Path"
        # Only look at first path for now
        path_texts = syn_output.split(path_tok)[1:2]
        # Parse each path
        self.path_reports = {}
        for path_text in path_texts:
            path_report = PathReport(path_text)
            self.path_reports[path_report.path_group] = path_report
        if len(self.path_reports) == 0:
            raise Exception(f"Bad synthesis log?:\n{syn_output}")


class PathReport:
    def __init__(self, path_report_text):
        #print("path_report_text",path_report_text) 
        self.path_delay_ns = None  # nanoseconds
        self.slack_ns = None
        self.source_ns_per_clock = None
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None

        prev_line = None
        in_netlist_resources = False
        for line in path_report_text.split("\n"):
            # SLACK
            tok1 = "Slack             : "
            if tok1 in line:
                toks = line.split(tok1)
                self.slack_ns = float(toks[1].strip())
                #print("Slack",self.slack_ns)

            # CLOCK NAME / PATH GROUP?
            tok1 = "Data Required Time: "
            if tok1 in line:
                toks = line.split(tok1)
                tok = toks[1].strip()
                self.source_ns_per_clock = float(tok)
                self.path_delay_ns = self.source_ns_per_clock - self.slack_ns
                #print("source_ns_per_clock",self.source_ns_per_clock)
                #print("path_delay_ns",self.path_delay_ns)

            # Start reg
            tok1 = "From              : "
            if tok1 in line:
                toks = line.split(tok1)
                self.start_reg_name = toks[1].strip()
                #print("start_reg_name",self.start_reg_name)

            # End reg
            tok1 = "To                : "
            if tok1 in line:
                toks = line.split(tok1)
                self.end_reg_name = toks[1].strip()
                #print("end_reg_name",self.end_reg_name)

            # CLOCK NAME / PATH GROUP?
            tok1 = "Launch Clk        : "
            if tok1 in line:
                toks = line.split(":")
                tok = toks[1].strip()
                self.path_group = tok
                #print("path_group",self.path_group)

            # Netlist resources
            toks = list(filter(None, line.split(" ")))
            if len(toks)==0:
                in_netlist_resources = False
            if in_netlist_resources:
                #print(toks)
                if len(toks) == 7:
                    s = toks[6]
                    #print("resource",s)
                    self.netlist_resources.add(s)
            tok1 = "active clock edge time"
            if tok1 in line:
                in_netlist_resources = True


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
    log_file_name = top_entity_name + ".tr"
    # Single inst
    if inst_name:
        Logic = parser_state.LogicInstLookupTable[inst_name]

        # Timing params for this logic
        timing_params = multimain_timing_params.TimingParamsLookupTable[inst_name]

        # First create syn/imp directory for this logic
        output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)

        # Set log path
        #if hash_ext is None:
        #    hash_ext = timing_params.GET_HASH_EXT(
        #        multimain_timing_params.TimingParamsLookupTable, parser_state
        #    )
    else:
        # Multimain
        # First create directory for this logic
        output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
        # Set log path
        # Hash for multi main is just hash of main pipes
        #hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    log_path = output_directory + "/" + "impl/pnr/" + log_file_name
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

    # Constraints
    # Write clock xdc and include it
    constraints_filepath = SYN.WRITE_CLK_CONSTRAINTS_FILE(parser_state, inst_name)
    clk_to_mhz, constraints_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(
        parser_state, inst_name
    )

    # Generate tcl file TODO use real generated vhdl files
    tcl_txt = ""
    tcl_txt += f'''
set_device -name {parser_state.part}
'''
    # All the generated vhdl files
    for vhdl_file_text in vhdl_files_texts.split(" "):  # hacky
        vhdl_file_text = vhdl_file_text.strip()
        if vhdl_file_text != "":
            tcl_txt += (
                """add_file -type vhdl """
                + vhdl_file_text
                + "\n")
    tcl_txt += f'''
add_file -type sdc {constraints_filepath}
set_option -output_base_name pipelinec
set_option -top_module {top_entity_name}
set_option -vhdl_std vhd2008
set_option -gen_text_timing_rpt 1
run all
'''
    tcl_file = top_entity_name + ".tcl"
    tcl_path = output_directory + "/" + tcl_file
    f = open(tcl_path, "w")
    f.write(tcl_txt)
    f.close()

    # Run the build script
    print("Running Gowin:", tcl_path, flush=True)
    syn_imp_bash_cmd = (
        GOWIN_PATH + "/" + TOOL_EXE + " " + tcl_path
    )
    C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
    
    # Read and parse log
    f = open(log_path, "r")
    log_text = f.read()
    f.close()
    return ParsedTimingReport(log_text)
