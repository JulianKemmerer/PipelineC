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
        print("TODO parse GOWIN output into path reports")
        # Split output into path texts
        self.path_reports = {}
        # path_report = PathReport(path_text) etc
        if len(self.path_reports) == 0:
            raise Exception(f"Bad synthesis log?:\n{syn_output}")


class PathReport:
    def __init__(self, path_report_text):
        # print("path_report_text",path_report_text)
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
            # Start reg
            tok1 = "Path Begin    : "
            if tok1 in line:
                toks = line.split(tok1)
                self.start_reg_name = NODE_TO_ELEM(toks[1].strip())
                # print("start_reg_name",self.start_reg_name)

            # End reg
            tok1 = "Path End      : "
            if tok1 in line:
                toks = line.split(tok1)
                self.end_reg_name = NODE_TO_ELEM(toks[1].strip())
                # print("end_reg_name",self.end_reg_name)

            # CLOCK NAME / PATH GROUP?
            tok1 = "Launch Clock  : "
            if tok1 in line:
                toks = line.split(tok1)
                tok = toks[1].split("(")[0].strip()
                self.path_group = tok
                # print("path_group",self.path_group)

            # SLACK
            tok1 = "Slack         : "
            if tok1 in line:
                toks = line.split(tok1)
                toks = toks[1].split("(")
                self.slack_ns = float(toks[0].strip())
                # print("Slack",self.slack_ns)

            # Netlist resources
            tok1 = "Capture Clock Path"
            if line.startswith(tok1):
                in_netlist_resources = False
            if in_netlist_resources:
                toks = list(filter(None, line.split(" ")))
                # pin name  model name    delay (ns)   cumulative delay (ns)    pins on net   location
                if len(toks) == 6:
                    s = toks[0]
                    resource = NODE_TO_ELEM(s)
                    # print("resource",resource)
                    self.netlist_resources.add(resource)
            tok1 = "Data Path"
            if line.startswith(tok1):
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

    

    # Run the build script to generate the project file
    print("Running Gowin:", tcl_path, flush=True)
    syn_imp_bash_cmd = (
        TOOL_EXE + " " + tcl_path
    )
    # TODO run script, for now fake log
    #C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
    #f = open(log_path, "r")
    #log_text = f.read()
    #f.close()
    log_text = """
2.2 Clock Summary
  Clock Name   Type   Period   Frequency   Rise     Fall    Source   Master   Objects  
 ============ ====== ======== =========== ======= ======== ======== ======== ========= 
  Clk          Base   37.037   27.000MHz   0.000   18.518                     Clk      

2.3 Max Frequency Summary
  NO.   Clock Name   Constraint    Actual Fmax    Level   Entity  
 ===== ============ ============= ============== ======= ======== 
  1     Clk          27.000(MHz)   322.094(MHz)   4       TOP     

2.4 Total Negative Slack Summary
  Clock Name   Analysis Type   EndPoints TNS   Number of EndPoints  
 ============ =============== =============== ===================== 
  Clk          setup           0.000           0                    
  Clk          hold            0.000           0                    


3. Timing Details
3.1 Path Slacks Table
3.1.1 Setup Paths Table
<Report Command>:report_timing -setup -max_paths 25 -max_common_paths 1
  Path Number   Path Slack      From Node          To Node       From Clock   To Clock   Relation   Clock Skew   Data Delay  
 ============= ============ ================= ================= ============ ========== ========== ============ ============ 
  1             33.932       Counter_6_s0/Q    Counter_15_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        3.070       
  2             34.175       Counter_6_s0/Q    Counter_19_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.827       
  3             34.175       Counter_6_s0/Q    Counter_13_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.827       
  4             34.175       Counter_6_s0/Q    Counter_18_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.827       
  5             34.188       Counter_6_s0/Q    Counter_17_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.814       
  6             34.221       Counter_2_s0/Q    Counter_6_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        2.781       
  7             34.320       Counter_2_s0/Q    Counter_10_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.682       
  8             34.320       Counter_2_s0/Q    Counter_11_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.682       
  9             34.359       Counter_6_s0/Q    Counter_14_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.643       
  10            34.366       Counter_6_s0/Q    Counter_16_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.636       
  11            34.494       Counter_2_s0/Q    Counter_12_s0/D   Clk:[R]      Clk:[R]    37.037     0.000        2.508       
  12            34.517       Counter_2_s0/Q    Counter_7_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        2.485       
  13            34.522       Counter_2_s0/Q    Counter_9_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        2.480       
  14            35.047       Counter_2_s0/Q    Counter_4_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        1.955       
  15            35.047       Counter_2_s0/Q    Counter_8_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        1.955       
  16            35.167       Counter_2_s0/Q    Counter_5_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        1.835       
  17            35.405       Leds_l_0_s1/Q     Leds_l_5_s0/D     Clk:[R]      Clk:[R]    37.037     0.000        1.597       
  18            35.440       Leds_l_0_s1/Q     Leds_l_4_s0/D     Clk:[R]      Clk:[R]    37.037     0.000        1.562       
  19            35.475       Leds_l_0_s1/Q     Leds_l_3_s0/D     Clk:[R]      Clk:[R]    37.037     0.000        1.527       
  20            35.503       Counter_1_s0/Q    Counter_3_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        1.499       
  21            35.510       Leds_l_0_s1/Q     Leds_l_2_s0/D     Clk:[R]      Clk:[R]    37.037     0.000        1.492       
  22            35.756       Counter_19_s0/Q   Counter_2_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        1.246       
  23            35.774       Counter_19_s0/Q   Leds_l_0_s1/D     Clk:[R]      Clk:[R]    37.037     0.000        1.228       
  24            35.775       Counter_19_s0/Q   Counter_0_s0/D    Clk:[R]      Clk:[R]    37.037     0.000        1.227       
  25            35.892       Counter_19_s0/Q   Leds_l_1_s0/CE    Clk:[R]      Clk:[R]    37.037     0.000        1.110       

3.1.2 Hold Paths Table
<Report Command>:report_timing -hold -max_paths 25 -max_common_paths 1
  Path Number   Path Slack      From Node          To Node       From Clock   To Clock   Relation   Clock Skew   Data Delay  
 ============= ============ ================= ================= ============ ========== ========== ============ ============ 
  1             0.425        Leds_l_2_s0/Q     Leds_l_2_s0/D     Clk:[R]      Clk:[R]    0.000      0.000        0.436       
  2             0.425        Counter_2_s0/Q    Counter_2_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.436       
  3             0.425        Counter_3_s0/Q    Counter_3_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.436       
  4             0.425        Counter_4_s0/Q    Counter_4_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.436       
  5             0.425        Counter_10_s0/Q   Counter_10_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.436       
  6             0.425        Counter_11_s0/Q   Counter_11_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.436       
  7             0.425        Counter_17_s0/Q   Counter_17_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.436       
  8             0.427        Leds_l_0_s1/Q     Leds_l_0_s1/D     Clk:[R]      Clk:[R]    0.000      0.000        0.438       
  9             0.427        Counter_8_s0/Q    Counter_8_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.438       
  10            0.427        Counter_12_s0/Q   Counter_12_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.438       
  11            0.427        Counter_13_s0/Q   Counter_13_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.438       
  12            0.542        Leds_l_3_s0/Q     Leds_l_3_s0/D     Clk:[R]      Clk:[R]    0.000      0.000        0.553       
  13            0.542        Leds_l_4_s0/Q     Leds_l_4_s0/D     Clk:[R]      Clk:[R]    0.000      0.000        0.553       
  14            0.547        Counter_18_s0/Q   Counter_19_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.558       
  15            0.547        Leds_l_5_s0/Q     Leds_l_5_s0/D     Clk:[R]      Clk:[R]    0.000      0.000        0.558       
  16            0.556        Counter_13_s0/Q   Counter_14_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.567       
  17            0.557        Leds_l_1_s0/Q     Leds_l_1_s0/D     Clk:[R]      Clk:[R]    0.000      0.000        0.568       
  18            0.557        Counter_0_s0/Q    Counter_0_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.568       
  19            0.557        Counter_5_s0/Q    Counter_5_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.568       
  20            0.557        Counter_6_s0/Q    Counter_6_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.568       
  21            0.557        Counter_7_s0/Q    Counter_7_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.568       
  22            0.557        Counter_9_s0/Q    Counter_9_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.568       
  23            0.557        Counter_18_s0/Q   Counter_18_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.568       
  24            0.559        Counter_1_s0/Q    Counter_1_s0/D    Clk:[R]      Clk:[R]    0.000      0.000        0.570       
  25            0.559        Counter_15_s0/Q   Counter_15_s0/D   Clk:[R]      Clk:[R]    0.000      0.000        0.570       

3.1.3 Recovery Paths Table
<Report Command>:report_timing -recovery -max_paths 25 -max_common_paths 1
Nothing to report!
3.1.4 Removal Paths Table
<Report Command>:report_timing -removal -max_paths 25 -max_common_paths 1
Nothing to report!
3.2 Minimum Pulse Width Table
Report Command:report_min_pulse_width -nworst 10 -detail
  Number   Slack    Actual Width   Required Width        Type         Clock      Objects     
 ======== ======== ============== ================ ================= ======= =============== 
  1        17.430   18.430         1.000            Low Pulse Width   Clk     Counter_18_s0  
  2        17.430   18.430         1.000            Low Pulse Width   Clk     Counter_16_s0  
  3        17.430   18.430         1.000            Low Pulse Width   Clk     Counter_12_s0  
  4        17.430   18.430         1.000            Low Pulse Width   Clk     Counter_4_s0   
  5        17.430   18.430         1.000            Low Pulse Width   Clk     Counter_5_s0   
  6        17.430   18.430         1.000            Low Pulse Width   Clk     Counter_13_s0  
  7        17.430   18.430         1.000            Low Pulse Width   Clk     Counter_6_s0   
  8        17.430   18.430         1.000            Low Pulse Width   Clk     Leds_l_0_s1    
  9        17.430   18.430         1.000            Low Pulse Width   Clk     Counter_7_s0   
  10       17.430   18.430         1.000            Low Pulse Width   Clk     Counter_19_s0  

3.3 Timing Report By Analysis Type
3.3.1 Setup Analysis Report
Report Command:report_timing -setup -max_paths 25 -max_common_paths 1
						Path1						
Path Summary:
Slack             : 33.932
Data Arrival Time : 3.996
Data Required Time: 37.928
From              : Counter_6_s0
To                : Counter_15_s0
Launch Clk        : Clk:[R]
Latch Clk         : Clk:[R]

Data Arrival Path:
   AT     DELAY   TYPE   RF   FANOUT       LOC                 NODE           
 ======= ======= ====== ==== ======== ============== ======================== 
  0.000   0.000                                       active clock edge time  
  0.000   0.000                                       Clk                     
  0.000   0.000   tCL    RR   1        IOL29[A]       Clk_ibuf/I              
  0.683   0.683   tINS   RR   26       IOL29[A]       Clk_ibuf/O              
  0.926   0.243   tNET   RR   1        R26C29[0][B]   Counter_6_s0/CLK        
  1.158   0.232   tC2Q   RF   3        R26C29[0][B]   Counter_6_s0/Q          
  1.579   0.421   tNET   FF   1        R27C30[2][A]   n43_s5/I2               
  2.032   0.453   tINS   FF   4        R27C30[2][A]   n43_s5/F                
  2.447   0.415   tNET   FF   1        R27C28[2][B]   n43_s4/I3               
  3.002   0.555   tINS   FF   5        R27C28[2][B]   n43_s4/F                
  3.447   0.445   tNET   FF   1        R26C27[0][B]   n47_s2/I1               
  3.996   0.549   tINS   FR   1        R26C27[0][B]   n47_s2/F                
  3.996   0.000   tNET   RR   1        R26C27[0][B]   Counter_15_s0/D         

Data Required Path:
    AT     DELAY    TYPE   RF   FANOUT       LOC                 NODE           
 ======== ======== ====== ==== ======== ============== ======================== 
  37.037   37.037                                       active clock edge time  
  37.037   0.000                                        Clk                     
  37.037   0.000    tCL    RR   1        IOL29[A]       Clk_ibuf/I              
  37.719   0.683    tINS   RR   26       IOL29[A]       Clk_ibuf/O              
  37.963   0.243    tNET   RR   1        R26C27[0][B]   Counter_15_s0/CLK       
  37.928   -0.035   tSu         1        R26C27[0][B]   Counter_15_s0           

Path Statistics:
Clock Skew: 0.000
Setup Relationship: 37.037
Logic Level: 4
Arrival Clock Path delay: (cell: 0.683 73.717%, 
                     route: 0.243 26.283%)
Arrival Data Path Delay: (cell: 1.557 50.722%, 
                    route: 1.281 41.720%, 
                    tC2Q: 0.232 7.558%)
Required Clock Path Delay: (cell: 0.683 73.717%, 
                     route: 0.243 26.283%)

						Path2						
Path Summary:
Slack             : 34.175
Data Arrival Time : 3.753
Data Required Time: 37.928
From              : Counter_6_s0
To                : Counter_19_s0
Launch Clk        : Clk:[R]
Latch Clk         : Clk:[R]

Data Arrival Path:
   AT     DELAY   TYPE   RF   FANOUT       LOC                 NODE           
 ======= ======= ====== ==== ======== ============== ======================== 
  0.000   0.000                                       active clock edge time  
  0.000   0.000                                       Clk                     
  0.000   0.000   tCL    RR   1        IOL29[A]       Clk_ibuf/I              
  0.683   0.683   tINS   RR   26       IOL29[A]       Clk_ibuf/O              
  0.926   0.243   tNET   RR   1        R26C29[0][B]   Counter_6_s0/CLK        
  1.158   0.232   tC2Q   RF   3        R26C29[0][B]   Counter_6_s0/Q          
  1.579   0.421   tNET   FF   1        R27C30[2][A]   n43_s5/I2               
  2.032   0.453   tINS   FF   4        R27C30[2][A]   n43_s5/F                
  2.447   0.415   tNET   FF   1        R27C28[2][B]   n43_s4/I3               
  3.002   0.555   tINS   FF   5        R27C28[2][B]   n43_s4/F                
  3.204   0.202   tNET   FF   1        R27C27[1][B]   n43_s2/I3               
  3.753   0.549   tINS   FR   1        R27C27[1][B]   n43_s2/F                
  3.753   0.000   tNET   RR   1        R27C27[1][B]   Counter_19_s0/D         

Data Required Path:
    AT     DELAY    TYPE   RF   FANOUT       LOC                 NODE           
 ======== ======== ====== ==== ======== ============== ======================== 
  37.037   37.037                                       active clock edge time  
  37.037   0.000                                        Clk                     
  37.037   0.000    tCL    RR   1        IOL29[A]       Clk_ibuf/I              
  37.719   0.683    tINS   RR   26       IOL29[A]       Clk_ibuf/O              
  37.963   0.243    tNET   RR   1        R27C27[1][B]   Counter_19_s0/CLK       
  37.928   -0.035   tSu         1        R27C27[1][B]   Counter_19_s0           

Path Statistics:
Clock Skew: 0.000
Setup Relationship: 37.037
Logic Level: 4
Arrival Clock Path delay: (cell: 0.683 73.717%, 
                     route: 0.243 26.283%)
Arrival Data Path Delay: (cell: 1.557 55.077%, 
                    route: 1.038 36.716%, 
                    tC2Q: 0.232 8.207%)
Required Clock Path Delay: (cell: 0.683 73.717%, 
                     route: 0.243 26.283%)
"""

    return ParsedTimingReport(log_text)
