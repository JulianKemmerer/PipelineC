import os

import C_TO_LOGIC
import OPEN_TOOLS
import SYN
import VHDL


def IS_INSTALLED():
    try:
        C_TO_LOGIC.GET_SHELL_CMD_OUTPUT('python3 -c "import pyrtl"')
    except:
        return False
    try:
        C_TO_LOGIC.GET_SHELL_CMD_OUTPUT('python3 -c "import pyparsing"')
    except:
        return False
    return True


class ParsedTimingReport:
    def __init__(self, syn_output):
        self.path_reports = dict()
        path_report = PathReport(syn_output)
        self.path_reports[path_report.path_group] = path_report


class PathReport:
    def __init__(self, path_report_text):
        self.path_delay_ns = None  # nanoseconds
        # self.slack_ns = None
        self.source_ns_per_clock = None  # From latch edge time
        self.path_group = None  # Clock name?
        self.netlist_resources = set()  # Set of strings
        self.start_reg_name = None
        self.end_reg_name = None

        for line in path_report_text.split("\n"):

            # Path delay ns
            tok1 = "Fmax (MHz):"
            if tok1 in line:
                toks = line.split(tok1)
                pyrtl_fmax = float(toks[1].strip())
                self.path_delay_ns = 1000.0 / pyrtl_fmax


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
        log_file_name = "pyrtl" + entity_file_ext + ".log"
    else:
        # Multimain
        # First create directory for this logic
        output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + SYN.TOP_LEVEL_MODULE

        # Set log path
        # Hash for multi main is just hash of main pipes
        hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
        log_file_name = "pyrtl" + hash_ext + ".log"

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

        if OPEN_TOOLS.YOSYS_BIN_PATH is None:
            raise Exception("yosys not installed?")

        """
    max_freq(tech_in_nm=130, ffoverhead=None)[source]
    Estimates the max frequency of a block in MHz.

    Parameters
    tech_in_nm – the size of the circuit technology to be estimated (for example, 65 is 65nm and 250 is 0.25um)

    ffoverhead – setup and ff propagation delay in picoseconds

    Returns
    a number representing an estimate of the max frequency in Mhz

    If a timing_map has already been generated by timing_analysis, 
    it will be used to generate the estimate (and gate_delay_funcs will be ignored). 
    Regardless, all params are optional and have reasonable default values. 
    Estimation is based on Dennard Scaling assumption and does not include wiring effect
    as a result the estimates may be optimistic (especially below 65nm).
    """

        # Write python file that does pyrtl stuff
        py_text = f"""
import pyrtl
pyrtl.reset_working_block()
print("Opening .blif...", flush=True)
f=open("{top_entity_name + ".blif"}")
blif = f.read()
pyrtl.input_from_blif(blif)
#print("Optimizing...", flush=True)
#pyrtl.optimize(skip_sanity_check=True)
print("Removing unlistened nets...", flush=True)
block = pyrtl.working_block(None)
pyrtl.passes._remove_unlistened_nets(block)
print("Computing timing analysis...", flush=True)
timing = pyrtl.TimingAnalysis()
#print("Max length:")
#timing.print_max_length()
print("Critical path:")
critical_path_info = timing.critical_path(cp_limit=1)
#print(critical_path_info)
print("Fmax (MHz):", timing.max_freq(), flush=True)
"""
        py_file = top_entity_name + ".py"
        py_path = output_directory + "/" + py_file
        f = open(py_path, "w")
        f.write(py_text)
        f.close()

        # A single shell script build .sh
        sh_file = top_entity_name + ".sh"
        sh_path = output_directory + "/" + sh_file
        f = open(sh_path, "w")
        # -v --debug

        # Uses yosys blif output
        # Write a shell script to execute
        m_ghdl = ""
        if not OPEN_TOOLS.GHDL_PLUGIN_BUILT_IN:
            m_ghdl = "-m ghdl "

        f.write(
            """
# Only output yosys json
#!/usr/bin/env bash
export GHDL_PREFIX="""
            + OPEN_TOOLS.GHDL_PREFIX
            + f"""
# Elab+Syn (blif is output) $MODULE
{OPEN_TOOLS.YOSYS_BIN_PATH}/yosys {m_ghdl} -p 'ghdl --std=08 """
            + vhdl_files_texts
            + """ -e """
            + top_entity_name
            + """; synth -top """
            + top_entity_name
            + """; write_blif """
            + top_entity_name
            + """.blif' &>> """
            + log_file_name
            + f"""
# pyrtl
echo "Beginning PyRTL analysis..." &>> {log_file_name}
python3 {py_file} &>> {log_file_name}
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

    return ParsedTimingReport(log_text)
