import os
import sys

import C_TO_LOGIC
import SYN
import VHDL
from utilities import GET_TOOL_PATH

# Tool names
YOSYS_EXE = "yosys"
NEXT_PNR_EXE = "nextpnr-gowin"
GHDL_EXE = "ghdl"

# Hard coded/default exe paths for simplest oss-cad-suite based install
# https://github.com/YosysHQ/oss-cad-suite-build/releases/
# Download, extract, set path here
OSS_CAD_SUITE_PATH = "/media/1TB/Programs/Linux/oss-cad-suite"
YOSYS_BIN_PATH = None
GHDL_BIN_PATH = None
NEXTPNR_BIN_PATH = None
GHDL_PREFIX = None

if os.path.exists(OSS_CAD_SUITE_PATH):
    YOSYS_BIN_PATH = OSS_CAD_SUITE_PATH + "/bin"
    GHDL_BIN_PATH = OSS_CAD_SUITE_PATH + "/bin"
    NEXTPNR_BIN_PATH = OSS_CAD_SUITE_PATH + "/bin"
    GHDL_PREFIX = OSS_CAD_SUITE_PATH + "/lib/ghdl"
    GHDL_PLUGIN_BUILT_IN = False
else:
    YOSYS_EXE_PATH = GET_TOOL_PATH(YOSYS_EXE)
    if YOSYS_EXE_PATH is not None:
        YOSYS_BIN_PATH = os.path.abspath(os.path.dirname(YOSYS_EXE_PATH))

    GHDL_EXE_PATH = GET_TOOL_PATH(GHDL_EXE)
    if GHDL_EXE_PATH is not None:
        GHDL_BIN_PATH = os.path.abspath(os.path.dirname(GHDL_EXE_PATH))
        GHDL_PREFIX = os.path.abspath(os.path.dirname(GHDL_EXE_PATH) + "/../lib/ghdl")
    GHDL_PLUGIN_BUILT_IN = False

    NEXTPNR_EXE_PATH = GET_TOOL_PATH(NEXT_PNR_EXE)
    if NEXTPNR_EXE_PATH is not None:
        NEXTPNR_BIN_PATH = os.path.abspath(os.path.dirname(NEXTPNR_EXE_PATH))

# Flag to skip pnr
YOSYS_JSON_ONLY = False

# Derive cmd line options from part
def PART_TO_CMD_LINE_OPTS(part_str):
    opts = ""
    opts += "--device "
    opts += part_str.upper()
    return opts


# Convert nextpnr style paths with . /
def NODE_TO_ELEM(node_str):
    # Struct dot is "\."  ?
    node_str = node_str.replace("\\.", "|")
    # Regualr modules is .
    node_str = node_str.replace(".", "/")
    # Fix structs
    node_str = node_str.replace("|", ".")
    # print("node_str",node_str)
    return node_str


class ParsedTimingReport:
    def __init__(self, syn_output):
        # Clocks reported once at end
        clock_to_act_tar_mhz = {}
        tok1 = "Max frequency for clock"
        for line in syn_output.split("\n"):
            if tok1 in line:
                clk_str = line.split(tok1)[1]
                clk_name = clk_str.split(":")[0].strip().strip("'")
                freqs_str = clk_str.split(":")[1]
                # print("clk_str",clk_str)
                # print("freqs_str",freqs_str)
                actual_mhz = float(freqs_str.split("MHz")[0])
                target_mhz = float(freqs_str.split("at ")[1].replace(" MHz)", ""))
                # print(clk_name, actual_mhz, target_mhz)
                clock_to_act_tar_mhz[clk_name] = (actual_mhz, target_mhz)

        self.path_reports = {}
        PATH_SPLIT = "Info: Critical path report for "
        maybe_path_texts = syn_output.split(PATH_SPLIT)
        for path_text in maybe_path_texts:
            if (
                "ns logic" in path_text and "(posedge -> posedge)" in path_text
            ):  # no async paths
                path_report = PathReport(path_text)
                # Set things only parsed once not per report
                path_report.path_delay_ns = (
                    1000.0 / clock_to_act_tar_mhz[path_report.path_group][0]
                )
                # Lolz really slow clocks come back as zero
                # nextpnr reports with two decimals 0.00 MHz
                tar_mhz = clock_to_act_tar_mhz[path_report.path_group][1]
                if tar_mhz < 0.01:
                    tar_mhz = 0.01
                path_report.source_ns_per_clock = 1000.0 / tar_mhz
                # Save in dict
                self.path_reports[path_report.path_group] = path_report

        if len(self.path_reports) == 0:
            print("Bad synthesis log?:", syn_output)
            sys.exit(-1)


class PathReport:
    def __init__(self, path_report_text):
        # print(path_report_text)
        self.path_delay_ns = None  # nanoseconds
        # self.slack_ns = None
        self.source_ns_per_clock = None  # From latch edge time
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None

        prev_line = None
        in_netlist_resources = False
        is_first_net = True
        last_net_name = None
        for line in path_report_text.split("\n"):

            # Path delay ns
            tok1 = "Max frequency for clock"
            if tok1 in line:
                toks = line.split(tok1)
                toks = toks[1].split(":")
                toks = toks[1].split("MHz")
                mhz = float(toks[0])
                ns = 1000.0 / mhz
                self.path_delay_ns = ns
                # print("mhz",mhz)
                # print("ns",ns)

            # Clock name  /path group
            tok1 = "(posedge -> posedge)"
            if tok1 in line:
                self.path_group = line.split("'")[1]  # .strip().strip("'")
                # print("self.path_group",self.path_group)

            # Netlist resources + start and end
            if in_netlist_resources:
                tok1 = "  Net "
                if tok1 in line:
                    net_str = line.split(tok1)[1].strip()
                    net = net_str.split(" ")[0]
                    net_name = NODE_TO_ELEM(net)
                    self.netlist_resources.add(net_name)
                    if is_first_net:
                        self.start_reg_name = net_name
                        is_first_net = False
                    last_net_name = net_name
            if "ns logic," in line and "ns routing" in line:
                in_netlist_resources = False
                self.end_reg_name = last_net_name
            tok1 = "Info: curr total"
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
    # Single inst
    if inst_name:
        Logic = parser_state.LogicInstLookupTable[inst_name]

        # Timing params for this logic
        timing_params = multimain_timing_params.TimingParamsLookupTable[inst_name]

        # First create syn/imp directory for this logic
        output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)

        # Set log path
        if hash_ext is None:
            hash_ext = timing_params.GET_HASH_EXT(
                multimain_timing_params.TimingParamsLookupTable, parser_state
            )
        if total_latency is None:
            total_latency = timing_params.GET_TOTAL_LATENCY(
                parser_state, multimain_timing_params.TimingParamsLookupTable
            )
        entity_file_ext = "_" + str(total_latency) + "CLK" + hash_ext
        log_file_name = "open_tools_gowin" + entity_file_ext + ".log"
    else:
        # Multimain
        # First create directory for this logic
        output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE

        # Set log path
        # Hash for multi main is just hash of main pipes
        hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
        log_file_name = "open_tools_gowin" + hash_ext + ".log"

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    log_path = output_directory + "/" + log_file_name

    # Use same configs based on to speed up run time?
    log_to_read = log_path

    # If log file exists dont run syn
    if os.path.exists(log_to_read) and use_existing_log_file:
        # print "SKIPPED:", syn_imp_bash_cmd
        print("Reading log", log_to_read)
        f = open(log_path, "r")
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

        if GHDL_PREFIX is None:
            raise Exception("ghdl not installed?")
        if YOSYS_BIN_PATH is None:
            raise Exception("yosys not installed?")
        if NEXTPNR_BIN_PATH is None:
            raise Exception("nextpnr not installed?")

        # A single shell script build .sh
        m_ghdl = ""
        if not GHDL_PLUGIN_BUILT_IN:
            m_ghdl = "-m ghdl "
        optional_router2 = "" # Always default router for now...
        #optional_router2 = "--router router2"
        #if inst_name:
        #    # Dont use router two for small single instances
        #    # Only use router two for multi main top level no inst_name
        #    optional_router2 = ""
        sh_file = top_entity_name + ".sh"
        sh_path = output_directory + "/" + sh_file
        f = open(sh_path, "w")
        # -v --debug
        if not YOSYS_JSON_ONLY:
            # Which exe?
            if parser_state.part.lower().startswith("ice"):
                exe_ext = "ice40"
            else:
                exe_ext = "ecp5"
            f.write(
                """
#!/usr/bin/env bash
export GHDL_PREFIX="""
                + GHDL_PREFIX
                + f"""
# Elab+Syn (json is output) $MODULE -g 
{YOSYS_BIN_PATH}/yosys {m_ghdl} -p 'ghdl --std=08 -frelaxed """
                + vhdl_files_texts
                + """ -e """
                + top_entity_name
                + """; synth_"""
                + exe_ext
                + """ -abc9 -nowidelut """
                + """ -top """
                + top_entity_name
                + """ -json """
                + top_entity_name
                + """.json; write_edif -top """
                + top_entity_name + """  """ 
                + top_entity_name + """.edf' &>> """
                + log_file_name
                + f"""
# P&R
{NEXTPNR_BIN_PATH}/nextpnr-"""
                + exe_ext
                + " "
                + PART_TO_CMD_LINE_OPTS(parser_state.part)
                + " --json "
                + top_entity_name
                + ".json --pre-pack "
                + constraints_filepath
                + " --timing-allow-fail "
                + " --seed 1 "
                + optional_router2
                + " &>> "
                + log_file_name
                + """
"""
            )
        else:
            # YOSYS_JSON_ONLY
            f.write(
                """
# Only output yosys json
#!/usr/bin/env bash
export GHDL_PREFIX="""
                + GHDL_PREFIX
                + f"""
# Elab+Syn (json is output) $MODULE -g 
{YOSYS_BIN_PATH}/yosys {m_ghdl} -p 'ghdl --std=08 -frelaxed """
                + vhdl_files_texts
                + """ -e """
                + top_entity_name
                + """; synth -top """
                + top_entity_name
                + """; write_json """
                + top_entity_name
                + """.json' &>> """
                + log_file_name
                + f"""
"""
            )
        f.close()

        # Execute the command
        syn_imp_bash_cmd = "bash " + sh_file
        print("Running:", log_path, flush=True)
        C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
        f = open(log_path, "r")
        log_text = f.read()
        f.close()

        # If just outputting json have to stop now?
        if YOSYS_JSON_ONLY:
            print("Stopping after json output in:", output_directory)
            sys.exit(0)

    return ParsedTimingReport(log_text)


def RENDER_FINAL_TOP_VERILOG(multimain_timing_params, parser_state):
    output_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE
    out_file = f"{output_dir}/{SYN.TOP_LEVEL_MODULE}.v"
    print("Rendering final top level Verilog...")
    # Identify tool versions
    if not os.path.exists(f"{GHDL_BIN_PATH}/ghdl"):
        raise Exception("ghdl executable not found!")
    if not os.path.exists(f"{YOSYS_BIN_PATH}/yosys"):
        raise Exception("yosys executable not found!")

    # Write a shell script to execute
    m_ghdl = ""
    if not GHDL_PLUGIN_BUILT_IN:
        m_ghdl = "-m ghdl "

    # GHDL --out=verilog produces duplicate wires
    # https://github.com/ghdl/ghdl/issues/2491
    '''{GHDL_BIN_PATH}/ghdl synth --std=08 -frelaxed --out=verilog `cat ../vhdl_files.txt` -e {SYN.TOP_LEVEL_MODULE} > {SYN.TOP_LEVEL_MODULE}.v'''
    sh_text = f"""
{GHDL_BIN_PATH}/ghdl -i --std=08 -frelaxed `cat ../vhdl_files.txt` && \
{GHDL_BIN_PATH}/ghdl -m --std=08 -frelaxed {SYN.TOP_LEVEL_MODULE} && \
{YOSYS_BIN_PATH}/yosys -g {m_ghdl} -p "ghdl --std=08 -frelaxed {SYN.TOP_LEVEL_MODULE}; proc; opt; fsm; opt; memory; opt; write_verilog {SYN.TOP_LEVEL_MODULE}.v"
"""
    
    sh_path = output_dir + "/" + "convert_to_verilog.sh"
    f = open(sh_path, "w")
    f.write(sh_text)
    f.close()

    # Run command
    bash_cmd = f"bash {sh_path}"
    # print(bash_cmd, flush=True)
    log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=output_dir)
    #print(log_text)
    print(f"Top level Verilog file: {out_file}")


def FUNC_IS_PRIMITIVE(func_name):
    # TODO: primitives
    #if func_name.startswith("ECP5_MUL"):
    #    return True
    return False


def GET_PRIMITIVE_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
    raise Exception("TODO prims!")
