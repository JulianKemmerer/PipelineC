import sys
import os

import SYN
import VHDL
import C_TO_LOGIC

FPGA_TOOLCHAIN_PATH = "/media/1TB/Programs/Linux/fpga-toolchain"
YOSYS_BIN_PATH   = FPGA_TOOLCHAIN_PATH + "/bin"
NEXTPNR_BIN_PATH = FPGA_TOOLCHAIN_PATH + "/bin"
GHDL_PREFIX      = FPGA_TOOLCHAIN_PATH + "/lib/ghdl"

# Derive cmd line options from part
def PART_TO_CMD_LINE_OPTS(part_str):
  #Ex. LFE5UM5G-85F-8BG756C
  toks = part_str.split("-")
  part = toks[0]
  size = toks[1]
  pkg = toks[2]
  
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
    PATH_SPLIT = "Critical path report for clock"
    maybe_path_texts = syn_output.split(PATH_SPLIT)
    path_texts = []
    for path_text in maybe_path_texts:
      if "ns logic" in path_text:
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
        self.path_group = line.split(tok1)[0].strip().strip("'")
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
def SYN_AND_REPORT_TIMING(inst_name, Logic, parser_state, TimingParamsLookupTable, total_latency, hash_ext = None, use_existing_log_file = True):
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
  
    #print "SYN: FUNC_NAME:", C_TO_LOGIC.LEAF_NAME(Logic.func_name)
    # First create syn/imp directory for this logic
    output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)  
    
    # Set log path
    if hash_ext is None:
      hash_ext = timing_params.GET_HASH_EXT(multimain_timing_params.TimingParamsLookupTable, parser_state)
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
    
    # A single shell script build .sh
    sh_file = top_entity_name + ".sh"
    sh_path = output_directory + "/" + sh_file
    f=open(sh_path,'w')
    f.write('''
#!/usr/bin/env bash
export PATH="''' + YOSYS_BIN_PATH + ''':$PATH"
export PATH="''' + NEXTPNR_BIN_PATH + ''':$PATH"
export GHDL_PREFIX=''' + GHDL_PREFIX + '''
# Elab+Syn (json is output)
yosys $MODULE -p 'ghdl ''' + vhdl_files_texts + ''' -e ''' + top_entity_name + '''; synth_ecp5 -top ''' + top_entity_name + ''' -json ''' + top_entity_name + '''.json' &>> ''' + log_file_name + '''
# P&R
nextpnr-ecp5 ''' + PART_TO_CMD_LINE_OPTS(parser_state.part) + ''' --json ''' + top_entity_name + '''.json --out-of-context --pre-pack ''' + constraints_filepath + ''' --timing-allow-fail &>> ''' + log_file_name + '''
# P&R
    ''')
    f.close()

    # Execute the command
    syn_imp_bash_cmd = "bash " + sh_file 
    print("Running:", sh_path, flush=True)
    C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
    f = open(log_path, "r")
    log_text = f.read()
    f.close()
    #print("log:",log_text)
    #sys.exit(0)
    
  return ParsedTimingReport(log_text)
  
