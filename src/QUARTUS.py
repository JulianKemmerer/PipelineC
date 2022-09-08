import os
import sys

import C_TO_LOGIC
import SYN
import VHDL
from utilities import GET_TOOL_PATH, REPO_ABS_DIR

TOOL_EXE = "quartus_sh"
# Default to env if there
ENV_TOOL_PATH = GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
    QUARTUS_SH_PATH = ENV_TOOL_PATH
    QUARTUS_PATH = os.path.abspath(os.path.dirname(QUARTUS_SH_PATH))
else:
    QUARTUS_PATH = "/media/1TB/Programs/Linux/intelFPGA_lite/20.1/quartus/bin"

# Need to know family in addition to part number?
# Dumb
# SAINT MOTEL - "Daydream/Wetdream/Nightmare"
def PART_TO_FAMILY(part_str):
    if part_str.upper().startswith("EP2A"):  # GX45CU17I3":
        return "Arria II GX"
    elif part_str.upper().startswith("EP4C"):  # E22F17C6":
        return "Cyclone IV E"
    elif part_str.upper().startswith("10C"):  # 120ZF780I8G":
        return "Cyclone 10 LP"
    elif part_str.upper().startswith("5C"):  # GXFC9E7F35C8":
        return "Cyclone"
    elif part_str.upper().startswith("10M"):  # 50SCE144I7G":
        return "MAX 10"
    else:
        print("What family is part'", part_str, "from? Edit QUARTUS.py.", flush=True)
        sys.exit(-1)


def FUNC_IS_PRIMITIVE(func_name):
    if func_name.startswith("LPM_MULT"):
        return True
    return False


def GET_PRIMITIVE_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
    # TODO easy to support any width from prim name alone
    name = "LPM_MULT"
    if not Logic.func_name.startswith(name):
        print("TODO other prims!")
        sys.exit(-1)

    toks = Logic.func_name.split(name)
    lxr_str = toks[1]
    l_width, r_width = lxr_str.split("X")
    # Assume LPM_MULT18X18
    needs_clk = VHDL.LOGIC_NEEDS_CLOCK(
        inst_name, Logic, parser_state, TimingParamsLookupTable
    )
    timing_params = TimingParamsLookupTable[inst_name]

    LPM_WIDTHA = int(l_width)
    LPM_WIDTHB = int(r_width)
    LPM_WIDTHP = LPM_WIDTHA + LPM_WIDTHB
    LPM_REPRESENTATION = "UNSIGNED"
    LPM_PIPELINE = len(timing_params._slices)
    INPUT_A_IS_CONSTANT = "NO"
    INPUT_B_IS_CONSTANT = "NO"
    USE_EAB = "NO"

    if timing_params._has_input_regs or timing_params._has_output_regs:
        raise Exception("TODO: Cyclone prim IO regs!")

    text = f"""
  
--LIBRARY lpm;
--USE lpm.lpm_components.all;
component LPM_MULT
generic ( 
  LPM_WIDTHA : natural;
  LPM_WIDTHB : natural;
  LPM_WIDTHS : natural := 1;
  LPM_WIDTHP : natural;
  LPM_REPRESENTATION : string := "UNSIGNED";
  LPM_PIPELINE : natural := 0;
  --LPM_TYPE: string := L_MULT;
  LPM_HINT : string := "UNUSED"
);
port ( 
  DATAA : in std_logic_vector(LPM_WIDTHA-1 downto 0);
  DATAB : in std_logic_vector(LPM_WIDTHB-1 downto 0);
  ACLR : in std_logic := '0';
  CLOCK : in std_logic := '0';
  CLKEN : in std_logic := '1';
  SUM : in std_logic_vector(LPM_WIDTHS-1 downto 0) := (OTHERS => '0');
  RESULT : out std_logic_vector(LPM_WIDTHP-1 downto 0)
);

end component;

begin
  
  LPM_MULT_inst : LPM_MULT
  generic map (
   LPM_WIDTHA => {LPM_WIDTHA},
   LPM_WIDTHB => {LPM_WIDTHB},
   LPM_WIDTHP => {LPM_WIDTHP},
   LPM_REPRESENTATION => "{LPM_REPRESENTATION}",
   LPM_PIPELINE => {LPM_PIPELINE}
  )
  port map(
"""
    if needs_clk:
        text += "CLOCK => clk,\n"
    text += f"""
  DATAA => std_logic_vector(a),
  DATAB => std_logic_vector(b),
  unsigned(RESULT) => return_output
  );
"""

    return text


# Convert Intel style 'node' paths with | and : into 'element' ones with just |
# And while here convert to use / instead of | like Xilinx too
def NODE_TO_ELEM(node_str):
    node_str = node_str.replace("|", "/")
    elem_str = node_str
    if ":" in node_str:
        # inst name is right tok, func name is left tok
        hier_toks = node_str.split("/")
        new_hier_toks = []
        for hier_tok in hier_toks:
            toks = hier_tok.split(":")
            new_hier_toks.append(toks[len(toks) - 1])
        elem_str = "/".join(new_hier_toks)

    return elem_str


class ParsedTimingReport:
    def __init__(self, syn_output):
        self.path_reports = dict()
        PATH_SPLIT = "): Path #"
        maybe_path_texts = syn_output.split(PATH_SPLIT)
        path_texts = []
        for path_text in maybe_path_texts:
            if "From Node" in path_text:
                path_report = PathReport(path_text)
                self.path_reports[path_report.path_group] = path_report

        if len(self.path_reports) == 0:
            print("Bad synthesis log?:", syn_output)
            sys.exit(-1)


class PathReport:
    def __init__(self, path_report_text):
        self.path_delay_ns = None  # nanoseconds
        self.slack_ns = None
        self.source_ns_per_clock = None  # From latch edge time
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None

        prev_line = None
        in_netlist_resources = False
        for line in path_report_text.split("\n"):

            # SLACK
            tok1 = "Setup slack is"
            if tok1 in line:
                toks = line.split(tok1)
                toks = toks[1].split("(")
                self.slack_ns = float(toks[0].strip())
                # print("Slack",self.slack_ns)

            # CLOCK PERIOD
            tok1 = "latch edge time"
            if tok1 in line:
                toks = list(filter(None, line.split(" ")))
                self.source_ns_per_clock = float(toks[2])

            # CLOCK NAME / PATH GROUP?
            tok1 = "Launch Clock :"
            if tok1 in line:
                toks = line.split(tok1)
                self.path_group = toks[1].strip()
                # print("path_group",self.path_group)

            tok1 = "Latch Clock  :"
            if tok1 in line:
                toks = line.split(tok1)
                latch_clock = toks[1].strip()
                if self.path_group != latch_clock:
                    print("Multiple clocks in path report?")
                    print(path_report_text)
                    sys.exit(-1)
                # print("path_group",self.path_group)

            # Netlist resources
            tok1 = ": Data Required Path:"
            if tok1 in line:
                in_netlist_resources = False
            if in_netlist_resources:
                if "clock network delay" in line:
                    continue
                toks = list(filter(None, line.split(" ")))
                s = toks[len(toks) - 1]
                resource = NODE_TO_ELEM(s)
                # print("resource",resource)
                self.netlist_resources.add(resource)
            tok1 = "0.000      0.000           launch edge time"
            if tok1 in line:
                in_netlist_resources = True

            # Start reg
            tok1 = ": From Node    :"
            if tok1 in line:
                toks = line.split(tok1)
                self.start_reg_name = NODE_TO_ELEM(toks[len(toks) - 1].strip())
                # Remove everything after last "/"
                # if "/" in self.start_reg_name:
                #  toks = self.start_reg_name.split("/")
                #  self.start_reg_name = "/".join(toks[0:len(toks)-1])
                # print("self.start_reg_name",self.start_reg_name)

            # End reg
            tok1 = ": To Node      :"
            if tok1 in line:
                toks = line.split(tok1)
                self.end_reg_name = NODE_TO_ELEM(toks[len(toks) - 1].strip())

                # Remove everything after last "/"
                # if "/" in self.end_reg_name:
                #  toks = self.end_reg_name.split("/")
                #  self.end_reg_name = "/".join(toks[0:len(toks)-1])
                # print("self.end_reg_name",self.end_reg_name)

            # SAVE LAST LINE
            prev_line = line

        # Calc path delay
        self.path_delay_ns = self.source_ns_per_clock - self.slack_ns
        # print("path_delay_ns",self.path_delay_ns)


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
        log_file_name = "quartus" + entity_file_ext + ".log"
    else:
        # Multimain
        # First create directory for this logic
        output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + "top"

        # Set log path
        # Hash for multi main is just hash of main pipes
        hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
        log_file_name = "quartus" + hash_ext + ".log"

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

        sh_file = top_entity_name + ".sh"
        sh_tcl_file = top_entity_name + ".sh.tcl"
        sta_tcl_file = top_entity_name + ".sta.tcl"
        sh_path = output_directory + "/" + sh_file
        sh_tcl_path = output_directory + "/" + sh_tcl_file
        sta_tcl_path = output_directory + "/" + sta_tcl_file
        f = open(sh_path, "w")
        f.write(
            """
#!/bin/sh
"""
            + QUARTUS_PATH
            + """/quartus_sh -t """
            + sh_tcl_file
            + """ >> """
            + log_file_name
            + """ 2>&1
"""
            + QUARTUS_PATH
            + """/quartus_sta -t """
            + sta_tcl_file
            + """ >> """
            + log_file_name
            + """ 2>&1
exit 0
"""
        )
        f.close()

        # sh.tcl
        f = open(sh_tcl_path, "w")
        sh_tcl_text = GET_SH_TCL(
            top_entity_name, vhdl_files_texts, constraints_filepath, parser_state
        )
        f.write(sh_tcl_text)
        f.close()

        # sta.tcl
        f = open(sta_tcl_path, "w")
        f.write(
            """
# Static timing analysis
project_open """
            + top_entity_name
            + """
create_timing_netlist
read_sdc """
            + constraints_filepath
            + """
# Report timing for each clock
"""
        )
        for clk_name in clk_to_mhz:
            f.write(
                """report_timing -npaths 1 -from_clock """
                + clk_name
                + """
"""
            )
        f.write(
            """
project_close
"""
        )
        f.close()

        # Execute the command
        syn_imp_bash_cmd = "bash " + sh_file
        print("Running Quartus:", sh_path, flush=True)
        C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
        f = open(log_path, "r")
        log_text = f.read()
        f.close()
        # print("log:",log_text)
        # sys.exit(0)

    return ParsedTimingReport(log_text)


def GET_SH_TCL(top_entity_name, vhdl_files_texts, constraints_filepath, parser_state):
    text = (
        """
load_package flow

# Thanks internet
proc make_all_pins_virtual {} {

 execute_module -tool map

 set name_ids [get_names -filter * -node_type pin]

 foreach_in_collection name_id $name_ids {
    set pin_name [get_name_info -info full_path $name_id]
    post_message "Making VIRTUAL_PIN assignment to $pin_name"
    set_instance_assignment -to $pin_name -name VIRTUAL_PIN ON
 }
 export_assignments
}

# Create the project
project_new """
        + top_entity_name
        + ''' -overwrite
# Set top level info
set_global_assignment -name FAMILY "'''
        + PART_TO_FAMILY(parser_state.part)
        + """"
set_global_assignment -name DEVICE """
        + parser_state.part
        + """
set_global_assignment -name TOP_LEVEL_ENTITY """
        + top_entity_name
        + """
set_global_assignment -name SDC_FILE """
        + constraints_filepath
        + """
# All the generated vhdl includes
"""
    )

    # All the generated vhdl files
    for vhdl_file_text in vhdl_files_texts.split(" "):  # hacky
        vhdl_file_text = vhdl_file_text.strip()
        if vhdl_file_text != "":
            text += (
                """set_global_assignment -name VHDL_FILE """
                + vhdl_file_text
                + """
"""
            )

    # IEEE proposed since quartus lite doesnt include vhdl 2008
    text += f"set_global_assignment -name VHDL_FILE {REPO_ABS_DIR()}/ieee/ieee_proposed.fixed_float_types.vhdl -library ieee_proposed\n"
    text += f"set_global_assignment -name VHDL_FILE {REPO_ABS_DIR()}/ieee/ieee_proposed.fixed_pkg.vhdl -library ieee_proposed\n"
    text += f"set_global_assignment -name VHDL_FILE {REPO_ABS_DIR()}/ieee/ieee_proposed.float_pkg.vhdl -library ieee_proposed\n"

    # Do compile
    text += """
# compile the project
make_all_pins_virtual
execute_flow -compile
project_close    
"""
    return text
