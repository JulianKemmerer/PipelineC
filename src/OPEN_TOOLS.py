import sys
import os

import SYN
import VHDL
import C_TO_LOGIC

# Tool names
YOSYS_EXE = "yosys"
NEXT_PNR_EXE = "nextpnr-ecp5"
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
  GHDL_PLUGIN_BUILT_IN = True
else:
  YOSYS_EXE_PATH = C_TO_LOGIC.GET_TOOL_PATH(YOSYS_EXE)
  if YOSYS_EXE_PATH is not None:
    YOSYS_BIN_PATH = os.path.abspath(os.path.dirname(YOSYS_EXE_PATH))

  GHDL_EXE_PATH = C_TO_LOGIC.GET_TOOL_PATH(GHDL_EXE)
  if GHDL_EXE_PATH is not None:
    GHDL_BIN_PATH = os.path.abspath(os.path.dirname(GHDL_EXE_PATH))
    GHDL_PREFIX = os.path.abspath(os.path.dirname(GHDL_EXE_PATH)+"/../lib/ghdl")
  GHDL_PLUGIN_BUILT_IN = False

  NEXTPNR_EXE_PATH = C_TO_LOGIC.GET_TOOL_PATH(NEXT_PNR_EXE)
  if NEXTPNR_EXE_PATH is not None:
    NEXTPNR_BIN_PATH = os.path.abspath(os.path.dirname(NEXTPNR_EXE_PATH))
    
# Flag to skip pnr
YOSYS_JSON_ONLY = False

# Derive cmd line options from part
def PART_TO_CMD_LINE_OPTS(part_str):
  opts = ""
  if part_str.lower().startswith("lfe5u"):
    #Ex. LFE5UM5G-85F-8BG756C
    toks = part_str.split("-")
    part = toks[0]
    size = toks[1]
    pkg = toks[2]
    '''
    --12k                             set device type to LFE5U-12F
    --25k                             set device type to LFE5U-25F
    --45k                             set device type to LFE5U-45F
    --85k                             set device type to LFE5U-85F
    --um-25k                          set device type to LFE5UM-25F
    --um-45k                          set device type to LFE5UM-45F
    --um-85k                          set device type to LFE5UM-85F
    --um5g-25k                        set device type to LFE5UM5G-25F
    --um5g-45k                        set device type to LFE5UM5G-45F
    --um5g-85k                        set device type to LFE5UM5G-85F
    --package arg                     select device package (defaults to 
                                      CABGA381)
    --speed arg                       select device speedgrade (6, 7 or 8)
    '''
    opts = ""
    opts += "--"
    if part == "LFE5UM":
      opts += "um-"
    elif part == "LFE5UM5G":
      opts += "um5g-"
    
    size_num = size.strip("F")
    opts += size_num + "k "
    
    speed_num = pkg[0]
    opts += "--speed " + speed_num + " "
    opts += "--out-of-context"
    
  elif part_str.lower().startswith("ice"):
    # Ex. ICE40UP5K-SG48
    toks = part_str.split("-")
    part = toks[0]
    pkg = toks[1]
    '''
    --lp384                           set device type to iCE40LP384
    --lp1k                            set device type to iCE40LP1K
    --lp4k                            set device type to iCE40LP4K
    --lp8k                            set device type to iCE40LP8K
    --hx1k                            set device type to iCE40HX1K
    --hx4k                            set device type to iCE40HX4K
    --hx8k                            set device type to iCE40HX8K
    --up3k                            set device type to iCE40UP3K
    --up5k                            set device type to iCE40UP5K
    --u1k                             set device type to iCE5LP1K
    --u2k                             set device type to iCE5LP2K
    --u4k                             set device type to iCE5LP4K
    '''
    if part_str.upper().startswith("ICE40LP384"):   
      opts += "--lp384"
    elif part_str.upper().startswith("ICE40LP1K"):  
      opts += "--lp1k"
    elif part_str.upper().startswith("ICE40LP4K"):  
      opts += "--lp4k"
    elif part_str.upper().startswith("ICE40LP8K"):  
      opts += "--lp8k"
    elif part_str.upper().startswith("ICE40HX1K"):  
      opts += "--hx1k"
    elif part_str.upper().startswith("ICE40HX4K"):  
      opts += "--hx4k"
    elif part_str.upper().startswith("ICE40HX8K"):  
      opts += "--hx8k"
    elif part_str.upper().startswith("ICE40UP3K"):  
      opts += "--up3k"
    elif part_str.upper().startswith("ICE40UP5K"):  
      opts += "--up5k"
    elif part_str.upper().startswith("ICE5LP1K"):   
      opts += "--u1k"
    elif part_str.upper().startswith("ICE5LP2K"):   
      opts += "--u2k"
    elif part_str.upper().startswith("ICE5LP4K"):   
      opts += "--u4k"
      
    opts += " --pcf-allow-unconstrained"
  
  return opts
    

# Convert nextpnr style paths with . /
def NODE_TO_ELEM(node_str):  
  # Struct dot is "\."  ?
  node_str = node_str.replace("\\.","|")
  # Regualr modules is .
  node_str = node_str.replace(".","/")
  # Fix structs
  node_str = node_str.replace("|",".")
  #print("node_str",node_str)
  return node_str

class ParsedTimingReport:
  def __init__(self, syn_output):
    # Clocks reported once at end
    clock_to_act_tar_mhz = dict()
    tok1 = "Max frequency for clock"
    for line in syn_output.split("\n"):
      if tok1 in line:
        clk_str = line.split(tok1)[1]
        clk_name = clk_str.split(":")[0].strip().strip("'")
        freqs_str = clk_str.split(":")[1]
        #print("clk_str",clk_str)
        #print("freqs_str",freqs_str)
        actual_mhz = float(freqs_str.split("MHz")[0])
        target_mhz = float(freqs_str.split("at ")[1].replace(" MHz)",""))
        #print(clk_name, actual_mhz, target_mhz)
        clock_to_act_tar_mhz[clk_name] = (actual_mhz, target_mhz)
    
    self.path_reports = dict()   
    PATH_SPLIT = "Info: Critical path report for "
    maybe_path_texts = syn_output.split(PATH_SPLIT)
    path_texts = []
    for path_text in maybe_path_texts:
      if "ns logic" in path_text and "(posedge -> posedge)" in path_text: # no async paths
        path_report = PathReport(path_text)
        # Set things only parsed once not per report
        path_report.path_delay_ns = 1000.0 / clock_to_act_tar_mhz[path_report.path_group][0]
        path_report.source_ns_per_clock = 1000.0 / clock_to_act_tar_mhz[path_report.path_group][1]
        # Save in dict
        self.path_reports[path_report.path_group] = path_report
        
    if len(self.path_reports) == 0:
      print("Bad synthesis log?:",syn_output)
      sys.exit(-1)
   
class PathReport:
  def __init__(self, path_report_text):
    #print(path_report_text)    
    self.path_delay_ns = None # nanoseconds
    #self.slack_ns = None
    self.source_ns_per_clock = None  # From latch edge time
    self.path_group = None # Clock name?
    self.netlist_resources = set() # Set of strings
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
        #print("mhz",mhz)
        #print("ns",ns)
        
      # Clock name  /path group
      tok1 = "(posedge -> posedge)"
      if tok1 in line:
        self.path_group = line.split("'")[1] #.strip().strip("'")
        #print("self.path_group",self.path_group)
        
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
        
      # SAVE LAST LINE
      prev_line = line
      
      
    #print("self.netlist_resources",self.netlist_resources)
    #print("self.start_reg_name",self.start_reg_name)
    #print("self.end_reg_name",self.end_reg_name)
    #sys.exit(0)

# Returns parsed timing report
def SYN_AND_REPORT_TIMING(inst_name, Logic, parser_state, TimingParamsLookupTable, total_latency=None, hash_ext = None, use_existing_log_file = True):
  multimain_timing_params = SYN.MultiMainTimingParams()
  multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable
  return SYN_AND_REPORT_TIMING_NEW(parser_state, multimain_timing_params, inst_name, total_latency, hash_ext, use_existing_log_file)
  
# Returns parsed timing report
def SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params):
  return SYN_AND_REPORT_TIMING_NEW(parser_state,  multimain_timing_params)
  
# MULTIMAIN OR SINGLE INSTANCE
# Returns parsed timing report
def SYN_AND_REPORT_TIMING_NEW(parser_state,  multimain_timing_params, inst_name = None, total_latency = None, hash_ext = None, use_existing_log_file = True):
  # Single inst
  if inst_name:
    Logic = parser_state.LogicInstLookupTable[inst_name]
    
    # Timing params for this logic
    timing_params = multimain_timing_params.TimingParamsLookupTable[inst_name]
  
    # First create syn/imp directory for this logic
    output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)  
    
    # Set log path
    if hash_ext is None:
      hash_ext = timing_params.GET_HASH_EXT(multimain_timing_params.TimingParamsLookupTable, parser_state)
    if total_latency is None:
      total_latency = timing_params.GET_TOTAL_LATENCY(parser_state, multimain_timing_params.TimingParamsLookupTable)
    entity_file_ext = "_" +  str(total_latency) + "CLK" + hash_ext
    log_file_name = "open_tools" + entity_file_ext + ".log"
  else:
    # Multimain
    # First create directory for this logic
    output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + "top"
    
    # Set log path
    # Hash for multi main is just hash of main pipes
    hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
    log_file_name = "open_tools" + hash_ext + ".log"
  
  
  if not os.path.exists(output_directory):
    os.makedirs(output_directory)
    
  log_path = output_directory + "/" + log_file_name
      
  # Use same configs based on to speed up run time?
  log_to_read = log_path
  
  # If log file exists dont run syn
  if os.path.exists(log_to_read) and use_existing_log_file:
    #print "SKIPPED:", syn_imp_bash_cmd
    print("Reading log", log_to_read)
    f = open(log_path, "r")
    log_text = f.read()
    f.close()
  else:
    
    # Write top level vhdl for this module/multimain
    if inst_name:
      VHDL.WRITE_LOGIC_ENTITY(inst_name, Logic, output_directory, parser_state, multimain_timing_params.TimingParamsLookupTable)
      VHDL.WRITE_LOGIC_TOP(inst_name, Logic, output_directory, parser_state, multimain_timing_params.TimingParamsLookupTable)
    else:
      VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params)
    
    # Generate files for this SYN
    
    # Constraints
    # Write clock xdc and include it
    constraints_filepath = SYN.WRITE_CLK_CONSTRAINTS_FILE(parser_state, inst_name)
    clk_to_mhz,constraints_filepath = SYN.GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(parser_state, inst_name)
    
    # Which vhdl files?
    vhdl_files_texts,top_entity_name = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(multimain_timing_params, parser_state, inst_name)
    
      
    if GHDL_PREFIX is None:
      raise Exception("ghdl not installed?")
    if YOSYS_BIN_PATH is None:
      raise Exception("yosys not installed?")
    if NEXTPNR_BIN_PATH is None:
      raise Exception("nextpnr not installed?")
    
    # A single shell script build .sh
    sh_file = top_entity_name + ".sh"
    sh_path = output_directory + "/" + sh_file
    f=open(sh_path,'w')
    # -v --debug
    
    if not YOSYS_JSON_ONLY:
      # Which exe?
      if parser_state.part.lower().startswith("ice"):
        exe_ext = "ice40"
      else:
        exe_ext = "ecp5"
      f.write('''
#!/usr/bin/env bash
export GHDL_PREFIX=''' + GHDL_PREFIX + f'''
# Elab+Syn (json is output)
{YOSYS_BIN_PATH}/yosys $MODULE -p 'ghdl --std=08 ''' + vhdl_files_texts + ''' -e ''' + top_entity_name + '''; synth_''' + exe_ext + ''' -top ''' + top_entity_name + ''' -json ''' + top_entity_name + '''.json' &>> ''' + log_file_name + f'''
# P&R
{NEXTPNR_BIN_PATH}/nextpnr-''' + exe_ext + ''' ''' + PART_TO_CMD_LINE_OPTS(parser_state.part) + ''' --json ''' + top_entity_name + '''.json --pre-pack ''' + constraints_filepath + ''' --timing-allow-fail &>> ''' + log_file_name + '''
''')
    else:
      # YOSYS_JSON_ONLY
      f.write('''
# Only output yosys json
#!/usr/bin/env bash
export GHDL_PREFIX=''' + GHDL_PREFIX + f'''
# Elab+Syn (json is output)
{YOSYS_BIN_PATH}/yosys $MODULE -p 'ghdl --std=08 ''' + vhdl_files_texts + ''' -e ''' + top_entity_name + '''; synth -top ''' + top_entity_name + '''; write_json ''' + top_entity_name + '''.json' &>> ''' + log_file_name + f'''
''')
    f.close()

    # Execute the command
    syn_imp_bash_cmd = "bash " + sh_file 
    print("Running:", sh_path, flush=True)
    C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
    f = open(log_path, "r")
    log_text = f.read()
    f.close()
    
    # If just outputting json have to stop now?
    if YOSYS_JSON_ONLY:
      print("Stopping after json output in:",output_directory)
      sys.exit(0)
    
  return ParsedTimingReport(log_text)
  
def FUNC_IS_PRIMITIVE(func_name):
  if func_name == "ECP5_MUL18X18":
    return True
  return False
  
def GET_PRIMITIVE_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
  if Logic.func_name != "ECP5_MUL18X18":
    print("TODO other prims!")
    sys.exit(-1)
  # Assume ECP5_MUL18X18
  needs_clk = VHDL.LOGIC_NEEDS_CLOCK(inst_name, Logic, parser_state, TimingParamsLookupTable)
  timing_params = TimingParamsLookupTable[inst_name]
  
  # Simple mapping of any slicing?
  in_reg = "NONE"
  pipe_reg = "NONE"
  out_reg = "NONE"
  # TODO UPDATE TO USE timing_params._has regs flags
  # 0 slices = comb
  if len(timing_params._slices) == 0:
    pass
  # 1 slice > 50% is output, < means input
  elif len(timing_params._slices) == 1:
    if timing_params._slices[0] > 0.5:
      out_reg = "CLK0"
    else:
      in_reg = "CLK0"
  # 2 slice is in and out
  elif len(timing_params._slices) == 2:
    out_reg = "CLK0"
    in_reg = "CLK0"
  # 3 slice is in,pipline,out regs
  elif len(timing_params._slices) == 3:
    out_reg = "CLK0"
    in_reg = "CLK0"
    pipe_reg = "CLK0"
  else:
    # 4+=? auto switch to comb logic version?
    print("Cannot pipeline ECP5_MUL18X18 further than 3 clocks!")
    print(inst_name)
    sys.exit(-1)  
  
  text = '''
  
  component MULT18X18D is
  generic (
    REG_INPUTA_CLK : string := "NONE";
    REG_INPUTA_CE : string := "CE0";
    REG_INPUTA_RST : string := "RST0";
    --
    REG_INPUTB_CLK : string := "NONE";
    REG_INPUTB_CE : string := "CE0";
    REG_INPUTB_RST : string := "RST0";
    --
    REG_INPUTC_CLK : string := "NONE";
    --reg_inputc_ce : string := "CE0";
    --reg_inputc_rst : string := "RST0";
    --
    REG_PIPELINE_CLK : string := "NONE";
    REG_PIPELINE_CE : string := "CE0";
    REG_PIPELINE_RST : string := "RST0";
    --
    REG_OUTPUT_CLK : string := "NONE";
    --reg_output_ce : string := "CE0";
    --reg_output_rst : string := "RST0";
    --
    CLK0_DIV : string := "ENABLED";
    CLK1_DIV : string := "ENABLED";
    CLK2_DIV : string := "ENABLED";
    CLK3_DIV : string := "ENABLED";
    --
    --highspeed_clk : string := "NONE";
    GSR : string := "ENABLED";
    --Cas_match_reg : string := "FALSE";
    SOURCEB_MODE : string := "B_SHIFT";
    --mult_bypass : string := "DISABLED";
    RESETMODE : string := "SYNC"  );
  port (
    A17 :   in  std_logic;
    A16 :   in  std_logic;
    A15 :   in  std_logic;
    A14 :   in  std_logic;
    A13 :   in  std_logic;
    A12 :   in  std_logic;
    A11 :   in  std_logic;
    A10 :   in  std_logic;
    A9 :   in  std_logic;
    A8 :   in  std_logic;
    A7 :   in  std_logic;
    A6 :   in  std_logic;
    A5 :   in  std_logic;
    A4 :   in  std_logic;
    A3 :   in  std_logic;
    A2 :   in  std_logic;
    A1 :   in  std_logic;
    A0 :   in  std_logic;
    B17 :   in  std_logic;
    B16 :   in  std_logic;
    B15 :   in  std_logic;
    B14 :   in  std_logic;
    B13 :   in  std_logic;
    B12 :   in  std_logic;
    B11 :   in  std_logic;
    B10 :   in  std_logic;
    B9 :   in  std_logic;
    B8 :   in  std_logic;
    B7 :   in  std_logic;
    B6 :   in  std_logic;
    B5 :   in  std_logic;
    B4 :   in  std_logic;
    B3 :   in  std_logic;
    B2 :   in  std_logic;
    B1 :   in  std_logic;
    B0 :   in  std_logic;
    C17 :   in  std_logic;
    C16 :   in  std_logic;
    C15 :   in  std_logic;
    C14 :   in  std_logic;
    C13 :   in  std_logic;
    C12 :   in  std_logic;
    C11 :   in  std_logic;
    C10 :   in  std_logic;
    C9 :   in  std_logic;
    C8 :   in  std_logic;
    C7 :   in  std_logic;
    C6 :   in  std_logic;
    C5 :   in  std_logic;
    C4 :   in  std_logic;
    C3 :   in  std_logic;
    C2 :   in  std_logic;
    C1 :   in  std_logic;
    C0 :   in  std_logic;
    SIGNEDA :   in  std_logic;
    SIGNEDB :   in  std_logic;
    SOURCEA :   in  std_logic;
    SOURCEB :   in  std_logic;
    CLK3 :   in  std_logic;
    CLK2 :   in  std_logic;
    CLK1 :   in  std_logic;
    CLK0 :   in  std_logic;
    CE3 :   in  std_logic;
    CE2 :   in  std_logic;
    CE1 :   in  std_logic;
    CE0 :   in  std_logic;
    RST3 :   in  std_logic;
    RST2 :   in  std_logic;
    RST1 :   in  std_logic;
    RST0 :   in  std_logic;
    -- SRIA17 :   in  std_logic;
    -- SRIA16 :   in  std_logic;
    -- SRIA15 :   in  std_logic;
    -- SRIA14 :   in  std_logic;
    -- SRIA13 :   in  std_logic;
    -- SRIA12 :   in  std_logic;
    -- SRIA11 :   in  std_logic;
    -- SRIA10 :   in  std_logic;
    -- SRIA9 :   in  std_logic;
    -- SRIA8 :   in  std_logic;
    -- SRIA7 :   in  std_logic;
    -- SRIA6 :   in  std_logic;
    -- SRIA5 :   in  std_logic;
    -- SRIA4 :   in  std_logic;
    -- SRIA3 :   in  std_logic;
    -- SRIA2 :   in  std_logic;
    -- SRIA1 :   in  std_logic;
    -- SRIA0 :   in  std_logic;
    -- SRIB17 :   in  std_logic;
    -- SRIB16 :   in  std_logic;
    -- SRIB15 :   in  std_logic;
    -- SRIB14 :   in  std_logic;
    -- SRIB13 :   in  std_logic;
    -- SRIB12 :   in  std_logic;
    -- SRIB11 :   in  std_logic;
    -- SRIB10 :   in  std_logic;
    -- SRIB9 :   in  std_logic;
    -- SRIB8 :   in  std_logic;
    -- SRIB7 :   in  std_logic;
    -- SRIB6 :   in  std_logic;
    -- SRIB5 :   in  std_logic;
    -- SRIB4 :   in  std_logic;
    -- SRIB3 :   in  std_logic;
    -- SRIB2 :   in  std_logic;
    -- SRIB1 :   in  std_logic;
    -- SRIB0 :   in  std_logic;
    SROA17 :   out  std_logic;
    SROA16 :   out  std_logic;
    SROA15 :   out  std_logic;
    SROA14 :   out  std_logic;
    SROA13 :   out  std_logic;
    SROA12 :   out  std_logic;
    SROA11 :   out  std_logic;
    SROA10 :   out  std_logic;
    SROA9 :   out  std_logic;
    SROA8 :   out  std_logic;
    SROA7 :   out  std_logic;
    SROA6 :   out  std_logic;
    SROA5 :   out  std_logic;
    SROA4 :   out  std_logic;
    SROA3 :   out  std_logic;
    SROA2 :   out  std_logic;
    SROA1 :   out  std_logic;
    SROA0 :   out  std_logic;
    SROB17 :   out  std_logic;
    SROB16 :   out  std_logic;
    SROB15 :   out  std_logic;
    SROB14 :   out  std_logic;
    SROB13 :   out  std_logic;
    SROB12 :   out  std_logic;
    SROB11 :   out  std_logic;
    SROB10 :   out  std_logic;
    SROB9 :   out  std_logic;
    SROB8 :   out  std_logic;
    SROB7 :   out  std_logic;
    SROB6 :   out  std_logic;
    SROB5 :   out  std_logic;
    SROB4 :   out  std_logic;
    SROB3 :   out  std_logic;
    SROB2 :   out  std_logic;
    SROB1 :   out  std_logic;
    SROB0 :   out  std_logic;
    ROA17 :   out  std_logic;
    ROA16 :   out  std_logic;
    ROA15 :   out  std_logic;
    ROA14 :   out  std_logic;
    ROA13 :   out  std_logic;
    ROA12 :   out  std_logic;
    ROA11 :   out  std_logic;
    ROA10 :   out  std_logic;
    ROA9 :   out  std_logic;
    ROA8 :   out  std_logic;
    ROA7 :   out  std_logic;
    ROA6 :   out  std_logic;
    ROA5 :   out  std_logic;
    ROA4 :   out  std_logic;
    ROA3 :   out  std_logic;
    ROA2 :   out  std_logic;
    ROA1 :   out  std_logic;
    ROA0 :   out  std_logic;
    ROB17 :   out  std_logic;
    ROB16 :   out  std_logic;
    ROB15 :   out  std_logic;
    ROB14 :   out  std_logic;
    ROB13 :   out  std_logic;
    ROB12 :   out  std_logic;
    ROB11 :   out  std_logic;
    ROB10 :   out  std_logic;
    ROB9 :   out  std_logic;
    ROB8 :   out  std_logic;
    ROB7 :   out  std_logic;
    ROB6 :   out  std_logic;
    ROB5 :   out  std_logic;
    ROB4 :   out  std_logic;
    ROB3 :   out  std_logic;
    ROB2 :   out  std_logic;
    ROB1 :   out  std_logic;
    ROB0 :   out  std_logic;
    ROC17 :   out  std_logic;
    ROC16 :   out  std_logic;
    ROC15 :   out  std_logic;
    ROC14 :   out  std_logic;
    ROC13 :   out  std_logic;
    ROC12 :   out  std_logic;
    ROC11 :   out  std_logic;
    ROC10 :   out  std_logic;
    ROC9 :   out  std_logic;
    ROC8 :   out  std_logic;
    ROC7 :   out  std_logic;
    ROC6 :   out  std_logic;
    ROC5 :   out  std_logic;
    ROC4 :   out  std_logic;
    ROC3 :   out  std_logic;
    ROC2 :   out  std_logic;
    ROC1 :   out  std_logic;
    ROC0 :   out  std_logic;
    P35 :   out  std_logic;
    P34 :   out  std_logic;
    P33 :   out  std_logic;
    P32 :   out  std_logic;
    P31 :   out  std_logic;
    P30 :   out  std_logic;
    P29 :   out  std_logic;
    P28 :   out  std_logic;
    P27 :   out  std_logic;
    P26 :   out  std_logic;
    P25 :   out  std_logic;
    P24 :   out  std_logic;
    P23 :   out  std_logic;
    P22 :   out  std_logic;
    P21 :   out  std_logic;
    P20 :   out  std_logic;
    P19 :   out  std_logic;
    P18 :   out  std_logic;
    P17 :   out  std_logic;
    P16 :   out  std_logic;
    P15 :   out  std_logic;
    P14 :   out  std_logic;
    P13 :   out  std_logic;
    P12 :   out  std_logic;
    P11 :   out  std_logic;
    P10 :   out  std_logic;
    P9 :   out  std_logic;
    P8 :   out  std_logic;
    P7 :   out  std_logic;
    P6 :   out  std_logic;
    P5 :   out  std_logic;
    P4 :   out  std_logic;
    P3 :   out  std_logic;
    P2 :   out  std_logic;
    P1 :   out  std_logic;
    P0 :   out  std_logic;
    SIGNEDP :   out  std_logic  
    );
end component; 
  
  begin
  
  mult18x18d_inst : MULT18X18D
  generic map (
    REG_INPUTA_CLK => "''' + in_reg + '''",
    REG_INPUTA_CE => "CE0",
    REG_INPUTA_RST => "RST0",
    --
    REG_INPUTB_CLK => "''' + in_reg + '''",
    REG_INPUTB_CE => "CE0",
    REG_INPUTB_RST => "RST0",
    --
    REG_INPUTC_CLK => "NONE",
    --reg_inputc_ce => "CE0",
    --reg_inputc_rst => "RST0",
    --
    REG_PIPELINE_CLK => "''' + pipe_reg + '''",
    REG_PIPELINE_CE => "CE0",
    REG_PIPELINE_RST => "RST0",
    --
    REG_OUTPUT_CLK => "''' + out_reg + '''",
    --reg_output_ce => "CE0",
    --reg_output_rst => "RST0",
    --
    CLK0_DIV => "DISABLED",
    CLK1_DIV => "DISABLED",
    CLK2_DIV => "DISABLED",
    CLK3_DIV => "DISABLED",
    --
    --highspeed_clk => "NONE",
    GSR => "DISABLED",
    --Cas_match_reg => "FALSE",
    --SOURCEB_MODE => "B_SHIFT",
    --mult_bypass => "DISABLED",
    RESETMODE => "ASYNC"  
  )
  port map(
    A17 => a(17),
    A16 => a(16),
    A15 => a(15),
    A14 => a(14),
    A13 => a(13),
    A12 => a(12),
    A11 => a(11),
    A10 => a(10),
    A9 => a(9),
    A8 => a(8),
    A7 => a(7),
    A6 => a(6),
    A5 => a(5),
    A4 => a(4),
    A3 => a(3),
    A2 => a(2),
    A1 => a(1),
    A0 => a(0),
    B17 => b(17),
    B16 => b(16),
    B15 => b(15),
    B14 => b(14),
    B13 => b(13),
    B12 => b(12),
    B11 => b(11),
    B10 => b(10),
    B9 => b(9),
    B8 => b(8),
    B7 => b(7),
    B6 => b(6),
    B5 => b(5),
    B4 => b(4),
    B3 => b(3),
    B2 => b(2),
    B1 => b(1),
    B0 => b(0),
    C17 => '0',
    C16 => '0',
    C15 => '0',
    C14 => '0',
    C13 => '0',
    C12 => '0',
    C11 => '0',
    C10 => '0',
    C9 => '0',
    C8 => '0',
    C7 => '0',
    C6 => '0',
    C5 => '0',
    C4 => '0',
    C3 => '0',
    C2 => '0',
    C1 => '0',
    C0 => '0',
    SIGNEDA => '0',
    SIGNEDB => '0',
    SOURCEA => '0',
    SOURCEB => '0',
    CLK3 => '0',
    CLK2 => '0',
    CLK1 => '0',
    '''
  if needs_clk:
    text += '''
    CLK0 => clk,
    '''
  else:
    text += '''
    CLK0 => '0',
    '''
  text += '''
    CE3 => '1',
    CE2 => '1',
    CE1 => '1',
    CE0 => '1',
    RST3 => '0',
    RST2 => '0',
    RST1 => '0',
    RST0 => '0',
    -- SRIA17 => '0',
    -- SRIA16 => '0',
    -- SRIA15 => '0',
    -- SRIA14 => '0',
    -- SRIA13 => '0',
    -- SRIA12 => '0',
    -- SRIA11 => '0',
    -- SRIA10 => '0',
    -- SRIA9 => '0',
    -- SRIA8 => '0',
    -- SRIA7 => '0',
    -- SRIA6 => '0',
    -- SRIA5 => '0',
    -- SRIA4 => '0',
    -- SRIA3 => '0',
    -- SRIA2 => '0',
    -- SRIA1 => '0',
    -- SRIA0 => '0',
    -- SRIB17 => '0',
    -- SRIB16 => '0',
    -- SRIB15 => '0',
    -- SRIB14 => '0',
    -- SRIB13 => '0',
    -- SRIB12 => '0',
    -- SRIB11 => '0',
    -- SRIB10 => '0',
    -- SRIB9 => '0',
    -- SRIB8 => '0',
    -- SRIB7 => '0',
    -- SRIB6 => '0',
    -- SRIB5 => '0',
    -- SRIB4 => '0',
    -- SRIB3 => '0',
    -- SRIB2 => '0',
    -- SRIB1 => '0',
    -- SRIB0 => '0',
    SROA17 => open,
    SROA16 => open,
    SROA15 => open,
    SROA14 => open,
    SROA13 => open,
    SROA12 => open,
    SROA11 => open,
    SROA10 => open,
    SROA9 => open,
    SROA8 => open,
    SROA7 => open,
    SROA6 => open,
    SROA5 => open,
    SROA4 => open,
    SROA3 => open,
    SROA2 => open,
    SROA1 => open,
    SROA0 => open,
    SROB17 => open,
    SROB16 => open,
    SROB15 => open,
    SROB14 => open,
    SROB13 => open,
    SROB12 => open,
    SROB11 => open,
    SROB10 => open,
    SROB9 => open,
    SROB8 => open,
    SROB7 => open,
    SROB6 => open,
    SROB5 => open,
    SROB4 => open,
    SROB3 => open,
    SROB2 => open,
    SROB1 => open,
    SROB0 => open,
    ROA17 => open,
    ROA16 => open,
    ROA15 => open,
    ROA14 => open,
    ROA13 => open,
    ROA12 => open,
    ROA11 => open,
    ROA10 => open,
    ROA9 => open,
    ROA8 => open,
    ROA7 => open,
    ROA6 => open,
    ROA5 => open,
    ROA4 => open,
    ROA3 => open,
    ROA2 => open,
    ROA1 => open,
    ROA0 => open,
    ROB17 => open,
    ROB16 => open,
    ROB15 => open,
    ROB14 => open,
    ROB13 => open,
    ROB12 => open,
    ROB11 => open,
    ROB10 => open,
    ROB9 => open,
    ROB8 => open,
    ROB7 => open,
    ROB6 => open,
    ROB5 => open,
    ROB4 => open,
    ROB3 => open,
    ROB2 => open,
    ROB1 => open,
    ROB0 => open,
    ROC17 => open,
    ROC16 => open,
    ROC15 => open,
    ROC14 => open,
    ROC13 => open,
    ROC12 => open,
    ROC11 => open,
    ROC10 => open,
    ROC9 => open,
    ROC8 => open,
    ROC7 => open,
    ROC6 => open,
    ROC5 => open,
    ROC4 => open,
    ROC3 => open,
    ROC2 => open,
    ROC1 => open,
    ROC0 => open,
    P35 => return_output(35),
    P34 => return_output(34),
    P33 => return_output(33),
    P32 => return_output(32),
    P31 => return_output(31),
    P30 => return_output(30),
    P29 => return_output(29),
    P28 => return_output(28),
    P27 => return_output(27),
    P26 => return_output(26),
    P25 => return_output(25),
    P24 => return_output(24),
    P23 => return_output(23),
    P22 => return_output(22),
    P21 => return_output(21),
    P20 => return_output(20),
    P19 => return_output(19),
    P18 => return_output(18),
    P17 => return_output(17),
    P16 => return_output(16),
    P15 => return_output(15),
    P14 => return_output(14),
    P13 => return_output(13),
    P12 => return_output(12),
    P11 => return_output(11),
    P10 => return_output(10),
    P9 => return_output(9),
    P8 => return_output(8),
    P7 => return_output(7),
    P6 => return_output(6),
    P5 => return_output(5),
    P4 => return_output(4),
    P3 => return_output(3),
    P2 => return_output(2),
    P1 => return_output(1),
    P0 => return_output(0),
    SIGNEDP => open
  );
'''
  
  return text
  
  
