import os
import sys

import C_TO_LOGIC
import SYN
import VHDL

TOOL_EXE = "diamondc"
# Default to env if there
ENV_TOOL_PATH = C_TO_LOGIC.GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
    DIAMOND_PATH = ENV_TOOL_PATH
else:
    DIAMOND_PATH = "/usr/local/diamond/3.11_x64/bin/lin64/diamondc"
DIAMOND_TOOL = "synplify"  # lse|synplify
# * If changing tool then need to delete FPGA part path_delay_cache dirs to be re synthesized
# * Might need this to make synplify work on Debian based systems:
#     https://electronics.stackexchange.com/questions/327527/lattice-icecube2-error-synplify-pro-321

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
    top_entity_name = VHDL.GET_TOP_ENTITY_NAME(
        parser_state, multimain_timing_params, inst_name
    )

    # Single inst
    if inst_name:
        Logic = parser_state.LogicInstLookupTable[inst_name]

        # First create syn/imp directory for this logic
        output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)
    else:
        # Multimain
        # First create directory for this logic
        output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + "top"

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    if DIAMOND_TOOL == "lse":
        log_path = output_directory + "/impl1/" + top_entity_name + "_impl1_lse.twr"
    if DIAMOND_TOOL == "synplify":
        log_path = output_directory + "/impl1/" + top_entity_name + "_impl1.srr"

    # Use same configs based on to speed up run time?
    log_to_read = log_path

    # If log file exists dont run syn
    if os.path.exists(log_to_read) and use_existing_log_file:
        # print "SKIPPED:", syn_imp_bash_cmd
        print("Reading log", log_to_read)
        f = open(log_path, "r", errors="replace")
        log_text = f.read()
        f.close()
    else:

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

        # Which vhdl files?
        vhdl_files_texts, top_entity_name = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(
            multimain_timing_params, parser_state, inst_name
        )

        # tcl
        tcl_file = top_entity_name + ".tcl"
        tcl_path = output_directory + "/" + tcl_file
        f = open(tcl_path, "w")
        f.write(
            '''
prj_project new -name "'''
            + top_entity_name
            + """" -impl "impl1" -dev """
            + parser_state.part
            + ''' -synthesis "'''
            + DIAMOND_TOOL
            + """"
prj_strgy set_value -strategy Strategy1 syn_pipelining_retiming=None
"""
        )
        # All the generated vhdl files
        f.write("prj_src add ")
        for vhdl_file_text in vhdl_files_texts.split(" "):  # hacky
            vhdl_file_text = vhdl_file_text.strip()
            if vhdl_file_text != "":
                f.write(vhdl_file_text + " ")
        f.write("\n")
        # Clock file
        f.write("prj_src add " + constraints_filepath + "\n")
        ## Do the prn
        # f.write("prj_run PAR -impl impl1\n")
        if DIAMOND_TOOL == "lse":
            # Nah, need to settle for syn est for now
            f.write("prj_run Synthesis -impl impl1 -task Lattice_Synthesis\n")
        if DIAMOND_TOOL == "synplify":
            # LSE sucks apparently? - no hard feelings
            f.write("prj_run Synthesis -impl impl1 -task Synplify_Synthesis\n")
        f.close()

        # Execute the command
        syn_imp_bash_cmd = DIAMOND_PATH + " " + tcl_path
        print("Running:", log_path, flush=True)
        C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)

        f = open(log_path, "r", errors="replace")
        log_text = f.read()
        f.close()
        # print("log:",log_text)
        # sys.exit(0)

    return ParsedTimingReport(log_text)


class ParsedTimingReport:
    def __init__(self, syn_output):
        if DIAMOND_TOOL == "lse":
            self.init_lse(syn_output)
        if DIAMOND_TOOL == "synplify":
            self.init_synplify(syn_output)

    def init_lse(self, syn_output):
        # Skip hold
        tok = "Lattice TRACE Report - Hold"
        syn_output = syn_output.split(tok)[0]
        self.path_reports = dict()
        PATH_SPLIT = "Logical Details:"
        maybe_path_texts = syn_output.split(PATH_SPLIT)
        for path_text in maybe_path_texts:
            if "Source:" in path_text:
                path_report = PathReport(path_text)

                # Only save the worst delay per path group
                do_add = False
                if path_report.path_group in self.path_reports:
                    if (
                        path_report.path_delay_ns
                        > self.path_reports[path_report.path_group].path_delay_ns
                    ):
                        do_add = True
                else:
                    do_add = True
                if do_add:
                    self.path_reports[path_report.path_group] = path_report

        if len(self.path_reports) == 0:
            print("Bad synthesis log?:", syn_output)
            sys.exit(-1)

    def init_synplify(self, syn_output):
        self.path_reports = dict()
        PATH_SPLIT = "Path information for path number"
        maybe_path_texts = syn_output.split(PATH_SPLIT)
        for path_text in maybe_path_texts:
            if "Number of logic level(s):" in path_text:
                path_report = PathReport(path_text)

                # Only save the worst delay per path group
                do_add = False
                if path_report.path_group in self.path_reports:
                    if (
                        path_report.path_delay_ns
                        > self.path_reports[path_report.path_group].path_delay_ns
                    ):
                        do_add = True
                else:
                    do_add = True
                if do_add:
                    self.path_reports[path_report.path_group] = path_report

        if len(self.path_reports) == 0:
            print("Bad synthesis log?:", syn_output)
            sys.exit(-1)


# Convert paths with . and \. into like Xilinx
def NODE_TO_ELEM(node_str):
    # Struct dot is "\."  ?
    node_str = node_str.replace("\\.", "|")
    # Regualr modules is .
    node_str = node_str.replace(".", "/")
    # Fix structs
    node_str = node_str.replace("|", ".")
    # print("node_str",node_str)
    return node_str


class PathReport:
    def __init__(self, path_report_text):
        if DIAMOND_TOOL == "lse":
            self.init_lse(path_report_text)
        if DIAMOND_TOOL == "synplify":
            self.init_synplify(path_report_text)

    def init_synplify(self, path_report_text):
        # print("path_report_text",path_report_text)
        self.path_delay_ns = None
        self.source_ns_per_clock = None  # From latch edge time
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None
        self.slack_ns = None

        prev_line = None
        in_netlist_resources = False
        for line in path_report_text.split("\n"):
            # CLOCK PERIOD
            tok1 = "Requested Period:"
            if tok1 in line:
                toks = list(filter(None, line.split(" ")))
                self.source_ns_per_clock = float(toks[2].strip())
                # print("Period",self.source_ns_per_clock)

            # SLACK
            tok1 = "= Slack"
            if tok1 in line:
                toks = list(filter(None, line.split(" ")))
                tok = toks[4].replace("ns", "").strip()
                self.slack_ns = float(tok)
                # print("slack_ns",self.slack_ns)

            # Start reg
            if self.start_reg_name is None:
                tok1 = "Starting point:"
                if tok1 in line:
                    toks = list(filter(None, line.split(" ")))
                    self.start_reg_name = toks[2]
                    # hacky remove last after _ if not _reg?
                    toks = self.start_reg_name.split("_")
                    if toks[len(toks) - 1] != "reg":
                        self.start_reg_name = "_".join(toks[0 : len(toks) - 1])
                    # print("start_reg_name",self.start_reg_name)

            # End reg
            if self.end_reg_name is None:
                tok1 = "Ending point:"
                if tok1 in line:
                    toks = list(filter(None, line.split(" ")))
                    self.end_reg_name = toks[2]
                    # hacky remove last after _ if not _reg?
                    toks = self.end_reg_name.split("_")
                    if toks[len(toks) - 1] != "reg":
                        self.end_reg_name = "_".join(toks[0 : len(toks) - 1])
                    # print("end_reg_name",self.end_reg_name)

            # CLOCK NAME / PATH GROUP?
            tok1 = "The start point is clocked by"
            if tok1 in line:
                toks = list(filter(None, line.split(" ")))
                tok = toks[6].strip()
                self.path_group = tok
                # print("path_group",self.path_group)
            tok1 = "The end   point is clocked by"
            if tok1 in line:
                toks = list(filter(None, line.split(" ")))
                tok = toks[6].strip()
                if self.path_group != tok:
                    # Gah 'System' clk wtf?
                    # Janelle Monáe - Screwed
                    if self.path_group == "System" and tok != "System":
                        self.path_group = tok
                    elif self.path_group != "System" and tok == "System":
                        # Keep good path group
                        pass
                    else:
                        print("Multiple clocks in path report?")
                        print(path_report_text)
                        sys.exit(-1)

            # Netlist resources
            tok1 = "=============================================================================================================================================================="
            if tok1 in line:
                in_netlist_resources = False
            if in_netlist_resources:
                toks = list(filter(None, line.split(" ")))
                resource = NODE_TO_ELEM(toks[0])
                self.netlist_resources.add(resource)
            tok1 = "--------------------------------------------------------------------------------------------------------------------------------------------------------------"
            if tok1 in line:
                in_netlist_resources = True

            # SAVE LAST LINE
            prev_line = line

        self.path_delay_ns = self.source_ns_per_clock - self.slack_ns
        # print("path_delay_ns",self.path_delay_ns)

    def init_lse(self, path_report_text):
        # print("path_report_text",path_report_text)

        print("TODO multiple clock domains for LSE!!")
        self.path_delay_ns = None
        self.source_ns_per_clock = None  # From latch edge time
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None

        prev_line = None
        for line in path_report_text.split("\n"):

            # DELAY
            tok1 = "Delay:"
            if tok1 in line:
                toks = list(filter(None, line.split(" ")))
                tok = toks[1].replace("ns", "").strip()
                self.path_delay_ns = float(tok)
                # print("path_delay_ns",self.path_delay_ns)

            # CLOCK PERIOD
            tok1 = "delay constraint less"
            if tok1 in line:
                toks = list(filter(None, line.split(" ")))
                self.source_ns_per_clock = float(toks[0].replace("ns", "").strip())
                # print("Period",self.source_ns_per_clock)

            # CLOCK NAME / PATH GROUP?
            self.path_group = "clk"
            """
      tok1 = "Launch Clock :"
      if tok1 in line:
        toks = line.split(tok1)
        self.path_group = toks[1].strip()
        #print("path_group",self.path_group)
      """

            """
      tok1 = "Latch Clock  :"
      if tok1 in line:
        toks = line.split(tok1)
        latch_clock = toks[1].strip()
        if self.path_group != latch_clock:
          print("Multiple clocks in path report?")
          print(path_report_text)
          sys.exit(-1)       
        #print("path_group",self.path_group)
      """

            # Netlist resources
            """
      tok1 = ": Data Required Path:"  
      if tok1 in line:
        in_netlist_resources = False
      if in_netlist_resources:
        if "clock network delay" in line:
          continue
        toks = list(filter(None, line.split(" ")))
        s = toks[len(toks)-1]
        resource = NODE_TO_ELEM(s)
        #print("resource",resource)
        self.netlist_resources.add(resource)
      tok1 = "0.000      0.000           launch edge time"
      if tok1 in line:
        in_netlist_resources = True       
      """

            # Start reg
            if self.start_reg_name is None:
                tok1 = "Source:"
                if tok1 in line:
                    toks = list(filter(None, line.split(" ")))
                    self.start_reg_name = toks[3]
                    # hacky remove last after _ if not _reg?
                    toks = self.start_reg_name.split("_")
                    if toks[len(toks) - 1] != "reg":
                        self.start_reg_name = "_".join(toks[0 : len(toks) - 1])
                    # print("start_reg_name",self.start_reg_name)

            # End reg
            if self.end_reg_name is None:
                tok1 = "Destination:"
                if tok1 in line:
                    # HAAAAHAACCKKY? Somestimes is data in sometimes is just D?
                    line = line.replace("Data in", "Data_in")
                    toks = list(filter(None, line.split(" ")))
                    self.end_reg_name = toks[3]
                    # hacky remove last after _ if not _reg?
                    toks = self.end_reg_name.split("_")
                    if toks[len(toks) - 1] != "reg":
                        self.end_reg_name = "_".join(toks[0 : len(toks) - 1])
                    # print("end_reg_name",self.end_reg_name)
