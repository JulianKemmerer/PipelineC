import os
import xml.etree.ElementTree as ET

import C_TO_LOGIC
import SYN
import VHDL
from utilities import GET_TOOL_PATH

TOOL_EXE = "gw_sh"
# Default to env if there
ENV_TOOL_PATH = GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
    GOWIN_PATH = ENV_TOOL_PATH
else:
    GOWIN_PATH = "/usr/local/share/gowin/IDE/bin/gw_sh"


class ParsedHTMLTimingReport:
    def __init__(self, syn_output):
        self.path_reports = {}
        # fixing GowinSynthesis timing output html one error at a time,
        # and massaging it to be readable by python's default XML parser.
        syn_output = syn_output.replace("<br>", "<br/>").replace("</br>", "<br/>") # fixing html5 auto-closing tags (including badly-formed ones)
        syn_output = syn_output.replace("&nbsp;", " ").replace("&nbsp", " ") # fixing space entities (including badly-formed ones)
        syn_output = syn_output.replace("<1%", "&lt;1%") # WTH gowin?
        syn_out_root = ET.fromstring(syn_output).find('body').find('div')[1]
        current_path_nodes = None
        path_nodes = []
        # split the main report node based on the <h3> items in it
        for path_report_node in syn_out_root:
            if path_report_node.tag == 'h3':
                if current_path_nodes:
                    path_nodes += [current_path_nodes]
                current_path_nodes = []
                #print(f"h3: {path_report_node.text}")
            elif current_path_nodes != None:
                current_path_nodes += [path_report_node]
                #print(f"path node: {path_report_node.tag}")
        path_nodes += [current_path_nodes]
        for path_node_items in path_nodes:
            path_report = PathHTMLReport(path_node_items)
            self.path_reports[path_report.path_group] = path_report
        #print(path_nodes)
        #raise Exception(f"Parsed HTML Root: {syn_out_root.tag} {syn_out_root.attrib}")
        if len(self.path_reports) == 0:
            raise Exception(f"Bad synthesis log?:\n{syn_output}")
    

class PathHTMLReport:
    def __init__(self, path_node_items):
        self.path_delay_ns = None # nanoseconds
        self.slack_ns = None
        self.source_ns_per_clock = None
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None
        looking_for = ""
        for node in path_node_items:
            if node.tag == "b":
                looking_for = node.text # will be "Path Summary:", "Data Arrival Path:", etc
            elif node.tag == "table":
                match looking_for:
                    case "Path Summary:":
                        self.slack_ns = float(node[0][1].text)
                        self.source_ns_per_clock = float(node[2][1].text)
                        self.start_reg_name = node[3][1].text
                        self.end_reg_name = node[4][1].text
                        self.path_group = node[5][1].text
                        self.path_delay_ns = self.source_ns_per_clock - self.slack_ns
                    case "Data Arrival Path:":
                        for row in node:
                            if row[5].tag != 'th':
                                self.netlist_resources.add(row[5].text)
                    

class ParsedTimingReport:
    def __init__(self, syn_output):
        self.path_reports = {}
        PATH_REPORT_BEGIN = '''3.3.1 Setup Analysis Report'''
        PATH_REPORT_END = '''3.3.2 Hold Analysis Report'''
        syn_report = syn_output.split(PATH_REPORT_BEGIN)[-1].split(PATH_REPORT_END)[0]
        PATH_SPLIT = "\t\t\t\t\t\tPath"
        maybe_path_texts = syn_report.split(PATH_SPLIT)
        for path_text in maybe_path_texts:
            if "Data Arrival Path:" in path_text:
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
                self.source_ns_per_clock = float(toks[1].strip())
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
                self.path_group = toks[1].strip()
                #print("path_group",self.path_group)

            # Netlist resources
            toks = [x for x in line.split(" ") if x]
            if len(toks) == 0:
                in_netlist_resources = False
            if in_netlist_resources:
                #print(toks)
                if len(toks) == 7:
                    s = toks[-1]
                    #print("resource",s)
                    self.netlist_resources.add(s)
            tok1 = "active clock edge time"
            if tok1 in line:
                in_netlist_resources = True


# Based on available devices and checked against device_list.csv inside Gowin tools v1.9.9
# might not be entirely comprehensive, but one can apply sensible defaults based on this
# (won't copy data from that list as it would not fit the license)
GOWIN_PART_PACKAGES_GRADES_VERSIONS = {
    "GW1N": [
        [["LV1S", "LV1"], # device variants
         ["CS30", "QN32", "QN48", "LQ100"], # packages
         ["C6/I5", "C5/I4"], # grades
         ["NA"]], # versions
        [["LV1P5", "UV1P5"], # device variants
         ["LQ100X", "LQ100", "QN48X"], # packages
         ["C7/I6", "C6/I5"], # grades
         ["NA", "B", "C"]], # versions
        [["LV2", "UV2"], # device variants
         ["LQ100X", "LQ144X", "LQ100", "LQ144",
          "CS42H", "CS42", "CS100H", "CS100",
          "MG121X", "MG121", "MG132X", "MG132H", "MG132", "MG49",
          "QN32X", "QN32", "QN48E", "QN48H", "QN48", "QN32X", "QN32" ], # packages
         ["C7/I6", "C6/I5"], # grades
         ["NA", "B", "C"]], # versions
        [["LV4", "UV4"], # device variants
         ["QN32", "QN48", "QN88",
          "CS72",
          "LQ100", "LQ144",
          "MG132X", "MG160",
          "PG256M", "PG256"], # packages
         ["C7/I6", "C6/I5", "C5/I4", "A4"], # grades
         ["NA", "B", "D"]], # versions
        [["LV9", "UV9"], # device variants
         ["CM64", "CS81M",
          "QN48", "QN60", "QN88",
          "LQ100", "LQ144", "LQ176",
          "MG160", "MG196",
          "PG256", "PG332",
          "UG169", "UG256", "UG332"], # packages
          ["C6/I5", "C5/I4", "ES"], # grades
          ["NA", "B", "C"]] # versions
    ],
    "GW1NZ": [
        [["LV1", "ZV1"], # device variants
         ["FN24", "FN32", "FN32F", "CS16", "CG25", "QN48"], # packages
         ["C6/I5", "C5/I4", "I3", "I2", "ES", "A3"], # grades
         ["NA", "C"]], # versions
        [["LV2", "ZV2"], # device variants
         ["CS100H", "QN48", "CS42"], # packages
         ["C6/I5", "C5/I4", "I3", "I2"], # grades
         ["NA", "B", "C"]] # versions
    ],
    "GW1NR": [
        [["LV1"], # device variants
         ["FN32G", "EQ144G",
          "QN32X", "QN48G", "QN48X",
          "LQ100G"], # packages
         ["C6/I5", "C5/I4","ES"], # grades
         ["NA"]], # versions
        [["LV2", "UV2"], # device variants
         ["MG49P", "MG49PG", "MG49G"], # packages
         ["C7/I6", "C6/I5"], # grades
         ["NA", "B", "C"]], # versions
        [["LV4", "UV4"], # device variants
         ["QN88P", "QN88", "MG81P"], # packages
         ["C7/I6", "C6/I5", "C5/I4", "ES"], # grades
         ["NA", "B", "C"]], # versions
        [["LV9", "UV9"], # device variants
         ["QN88P", "QN88",
          "LQ144P", "MG100P"], # packages
         ["C7/I6", "C6/I5", "C5/I4", "ES"], # grades
         ["NA", "C"]] # versions
    ],
    "GW1NS": [
        [["LV4C"], # device variants
         ["QN32", "QN48", "CS49", "MG64"], # packages
         ["C7/I6", "C6/I5", "C5/I4", "ES"], # grades
         ["NA"]] # versions
    ],
    "GW1NSR": [
        [["LV4C"], # device variants
         ["QN48G", "QN48P", "MG64P"], # packages
         ["C7/I6", "C6/I5", "C5/I4"], # grades
         ["NA"]] # versions
    ],
    "GW1NSER": [
        [["LV4C"], # device variants
         ["QN48G", "QN48P"], # packages
         ["C7/I6", "C6/I5", "C5/I4"], # grades
         ["NA"]] # versions
    ],
    "GW1NRF": [
        [["LV4", "UV4"], # device variants
         ["QN48E", "QN48"], # packages
         ["C6/I5", "C5/I4"], # grades
         ["NA"]] # versions
    ],
    "GW2A": [
        [["LV18"], # device variants
         ["PG256CF", "PG256SF", "PG256S", "PG256C", "PG256E", "PG256",
          "PG484C", "PG484",
          "MG195", "EQ144", "UG484", "UG324",
          "QN88"], # packages
         ["C9/I8", "C8/I7", "C7/I6", "A6", "ES"], # grades
         ["NA", "C"]], # versions
        [["LV55"], # device variants
         ["PG484S", "PG484", "PG1156",
          "UG324D", "UG324F", "UG324", "UG484S", "UG676"], # packages
         ["C9/I8", "C8/I7", "C7/I6", "ES"], # grades
         ["NA", "C"]] # versions
    ],
    "GW2AR": [
        [["LV18"], # device variants
         ["QN88PF", "QN88P", "QN88",
          "EQ144P", "EQ144", "EQ176"], # packages
         ["C9/I8", "C8/I7", "C7/I6", "ES"], # grades
         ["NA", "C"]] # versions
    ],
    "GW2ANR": [
        [["LV18"], # device variants
         ["QN88"], # packages
         ["C9/I8", "C8/I7", "C7/I6", "ES"], # grades
         ["C"]] # versions
    ],
    "GW2AN": [
        [["LV9", "EV9"], # device variants
         ["PG256",
          "UG324", "UG400", "UG484"], # packages
         ["C7/I6"], # grades
         ["NA"]], # versions
        [["LV18", "EV18"], # device variants
         ["PG256", "PG484",
          "UG256", "UG324", "UG332", "UG400", "UG484", "UG676"], # packages
         ["C7/I6"], # grades
         ["NA"]], # versions
        [["LV55"], # device variants
         ["UG676"], # packages
         ["C9/I8", "C8/I7", "C7/I6"], # grades
         ["C"]] # versions
    ],
    "GW5A": [
        [["LV138"], # device variants
         ["UG324A"], # packages
         ["C2/I1", "C1/I0", "ES"],
         ["B"]], # versions
        [["LV25", "EV25"], # device variants
         ["MG121N", "MG196S",
          "UG225S", "UG256C", "UG324",
          "PG256S", "PG256C", "PG256",
          "LQ100", "LQ144"], # packages
         ["C2/I1", "C1/I0", "ES", "A0"], # grades
         ["A"]] # versions
    ],
    "GW5AR": [
        [["LV25"], # device variants
         ["UG256P"], # packages
         ["C2/I1", "C1/I0", "ES"], # grades
         ["A"]] # versions
    ],
    "GW5AS": [
        [["LV138"], # device variants
         ["UG324A"], # packages
         ["C2/I1", "C1/I0", "ES"], # grades
         ["B"]], # versions
        [["EV25"], # device variants
         ["UG256"], # packages
         ["C2/I1", "C1/I0", "ES"], # grades
         ["A"]] # versions
    ],
    "GW5AST": [
        [["LV138F", "LV138"], # device variants
         ["PG484A", "PG676A"], # packages
         ["C2/I1", "C1/I0", "ES"], # grades
         ["B"]] # versions
    ],
    "GW5AT": [[["LV75"], ["UG484"], ["ES"], ["B"]]]
}

def PART_GRADE_TO_TOOL_GRADE(part_grade, grades):
    if len(part_grade) == 2 or len(part_grade) == 5:
        for grade in grades:
            if grade.find(part_grade) != -1:
                return grade
    raise Exception(f"Cannot derive part grade from part subsection: {part_grade}")


def PART_TO_DEVICE_VERSIONS(part_str):
    """
    Returns the allowed device version strings - which are expected
    by gw_sh, otherwise it won't synthesize for that part number.
    """
    split_part = part_str.upper().split("-")
    if split_part[0] in GOWIN_PART_PACKAGES_GRADES_VERSIONS:
        subparts = GOWIN_PART_PACKAGES_GRADES_VERSIONS[split_part[0]]
        for [prefixes, packages, grades, versions] in subparts:
            for package_prefix in prefixes:
                if split_part[1].startswith(package_prefix):
                    l = len(package_prefix)
                    for package in packages:
                        if split_part[1].startswith(package, l):
                            l += len(package)
                            grade = PART_GRADE_TO_TOOL_GRADE(split_part[1][l:], grades)
                            return f"{split_part[0]}-{split_part[1][:l]}{grade}", versions
    raise Exception(f"Cannot derive device versions from part string {part_str} - please check GOWIN.py if part exists")

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

    # Single instance
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
    log_path = f"{output_directory}/impl/gwsynthesis/{top_entity_name}_syn.rpt.html"
    #log_path = f"{output_directory}/impl/pnr/{top_entity_name}.tr"
    # Use same configs based on to speed up run time?
    log_to_read = log_path

    # If log file exists dont run syn
    if os.path.exists(log_to_read) and use_existing_log_file:
        # print "SKIPPED:", syn_imp_bash_cmd
        print("Reading log", log_to_read)
        with open(log_to_read, "r") as f:
            log_text = f.read()
            return ParsedTimingReport(log_text)
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

    # Which VHDL files?
    vhdl_files_texts, top_entity_name = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(
        multimain_timing_params, parser_state, inst_name
    )

    # Generate TCL file
    tcl_file = top_entity_name + ".tcl"
    tcl_path = output_directory + "/" + tcl_file

    # parse part name to direct the synthesis 
    part_name = parser_state.part
    tool_part_name, device_versions = PART_TO_DEVICE_VERSIONS(part_name)

    with open(tcl_path, "w") as f:
        if len(device_versions) > 1:
            f.write(f"set_device --device_version {device_versions[-1]} {tool_part_name}\n")
        else:
            f.write(f"set_device {tool_part_name}\n")
        for vhdl_file_text in vhdl_files_texts.split(" "):
            vhdl_file_text = vhdl_file_text.strip()
            if vhdl_file_text != "":
                f.write(f"add_file -type vhdl {vhdl_file_text}\n")
        f.write(
            f'''
add_file -type sdc {constraints_filepath}
set_option -output_base_name {top_entity_name}
set_option -top_module {top_entity_name}
set_option -vhdl_std vhd2008
set_option -gen_text_timing_rpt 1
run syn
''')
    syn_imp_bash_cmd = f"{GOWIN_PATH} {tcl_path}"
    print("Running:", log_path, flush=True)
    C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)

    # Read and parse log
    with open(log_path, "r", errors="replace") as f:
        log_text = f.read()
    return ParsedHTMLTimingReport(log_text)

def FUNC_IS_PRIMITIVE(func_name):
    return func_name in [
        
    ]

def GET_PRIMITIVE_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
    pass
