import sys
import os

import SYN
import VHDL
import C_TO_LOGIC

TOOL_EXE = "efx_run.py"
# Default to env if there
ENV_TOOL_PATH = SYN.GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
  EFINITY_EFX_RUN_PATH = ENV_TOOL_PATH
  EFINITY_PATH = os.path.abspath(os.path.dirname(EFINITY_EFX_RUN_PATH) + "/../bin")
else:
  EFINITY_PATH = "/media/1TB/Programs/Linux/efinity/2021.1/bin"

def PART_TO_FAMILY_TIMING_MODEL(part_str):
  if part_str.upper().startswith("T8"):
    return "Trion","C2"
  elif part_str.upper().startswith("TI"):
    return "Titanium","C4"
  else:
    raise Exception(f"What family is part '{part_str}'from? Edit EFINITY.py.")

# Convert Efinix style 'node' paths to something Xilinx like with '/'
def NODE_TO_ELEM(node_str):  
  node_str = node_str.split("~")[0]
  node_str = node_str.replace("|","/")
  '''
  elem_str = node_str
  if ":" in node_str:
    # inst name is right tok, func name is left tok
    hier_toks = node_str.split("/")
    new_hier_toks = []
    for hier_tok in hier_toks:
      toks = hier_tok.split(":")
      new_hier_toks.append(toks[len(toks)-1])
    elem_str = "/".join(new_hier_toks)
  '''
  return node_str
    
class ParsedTimingReport:
  def __init__(self, syn_output):
    #print(syn_output)
    # Clocks reported once at end
    clock_to_act_tar_mhz = dict()
    tok1 = "Max frequency for clock"
    in_constraints = False
    in_freqs = False
    prev_line = ""
    for line in syn_output.split("\n"):
      if "Maximum possible analyzed clocks frequency" in line:
        in_constraints = False
      if "Geomean max period:" in line:
        in_freqs = False
      if in_constraints:
        toks = list(filter(None, line.split(" ")))
        if len(toks) == 6:
          clk_name = toks[0]
          target_mhz = float(toks[2])
          if clk_name not in clock_to_act_tar_mhz:
            clock_to_act_tar_mhz[clk_name] = [None,None]
          clock_to_act_tar_mhz[clk_name][1] = target_mhz
      if in_freqs:
        toks = list(filter(None, line.split(" ")))
        if len(toks) >= 3:
          clk_name = toks[0]
          actual_mhz = float(toks[2])
          if clk_name not in clock_to_act_tar_mhz:
            clock_to_act_tar_mhz[clk_name] = [None,None]
          clock_to_act_tar_mhz[clk_name][0] = actual_mhz
      
      if "Clock Name      Period (ns)   Frequency (MHz)   Waveform   Source Clock Name" in line:
        in_constraints = True
      if "Clock Name      Period (ns)   Frequency (MHz)   Edge" in line:
        in_freqs = True
      prev_line = line[:]      
      
    #for clk_name in clock_to_act_tar_mhz:
    #  actual_mhz, target_mhz = clock_to_act_tar_mhz[clk_name]
    #  print(clk_name, actual_mhz, target_mhz)
    #sys.exit(-1)
    
    # Get max delay paths
    self.path_reports = dict()
    min_split = "Path Details for Min Critical Paths (begin)"
    max_delay_paths = syn_output.split(min_split)[0]
    path_split = "++++ Path"
    path_texts = max_delay_paths.split(path_split)[1:]
    for path_text in path_texts:
        path_report = PathReport(path_text)
        # Set things only parsed once not per report
        path_report.path_delay_ns = 1000.0 / clock_to_act_tar_mhz[path_report.path_group][0]
        path_report.source_ns_per_clock = 1000.0 / clock_to_act_tar_mhz[path_report.path_group][1]
        self.path_reports[path_report.path_group] = path_report
        
    if len(self.path_reports) == 0:
      raise Exception(f"Bad synthesis log?:\n{syn_output}")
   
class PathReport:
  def __init__(self, path_report_text):
    #print("path_report_text",path_report_text)
    self.path_delay_ns = None # nanoseconds
    self.slack_ns = None
    self.source_ns_per_clock = None  # From latch edge time
    self.path_group = None # Clock name?
    self.netlist_resources = set() # Set of strings
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
        #print("start_reg_name",self.start_reg_name)
        
      # End reg
      tok1 = "Path End      : "
      if tok1 in line:
        toks = line.split(tok1)
        self.end_reg_name = NODE_TO_ELEM(toks[1].strip())
        #print("end_reg_name",self.end_reg_name)
        
      # CLOCK NAME / PATH GROUP?
      tok1 = "Launch Clock  : "
      if tok1 in line:
        toks = line.split(tok1)
        tok = toks[1].split("(")[0].strip()
        self.path_group = tok
        #print("path_group",self.path_group)
        
      # SLACK
      tok1 = "Slack         : "
      if tok1 in line:
        toks = line.split(tok1)
        toks = toks[1].split("(")
        self.slack_ns = float(toks[0].strip())
        #print("Slack",self.slack_ns)
            
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
          #print("resource",resource)
          self.netlist_resources.add(resource)
      tok1 = "Data Path"  
      if line.startswith(tok1):
        in_netlist_resources = True       

      # SAVE LAST LINE
      prev_line = line
    

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
  # Which vhdl files?
  vhdl_files_texts,top_entity_name = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(multimain_timing_params, parser_state, inst_name)
  # EFINITY FORCES LOG FILE
  log_file_name = top_entity_name + ".timing.rpt"
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
    #if total_latency is None:
    #  total_latency = timing_params.GET_TOTAL_LATENCY(parser_state, multimain_timing_params.TimingParamsLookupTable)
    #entity_file_ext = "_" +  str(total_latency) + "CLK" + hash_ext
    #log_file_name = "efinity" + entity_file_ext + ".log"
    
  else:
    # Multimain
    # First create directory for this logic
    output_directory = SYN.SYN_OUTPUT_DIRECTORY + "/" + "top"
    # Set log path
    # Hash for multi main is just hash of main pipes
    hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
    #log_file_name = "efinity" + hash_ext + ".log"
  
  
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
    return ParsedTimingReport(log_text)
  
  # Not from log:
  
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
  
  # Generate project xml file
  # Based on opening the GUI and seeing what it wrote for a minimal project?
  family,timing_model = PART_TO_FAMILY_TIMING_MODEL(parser_state.part)
  xml_text = ""
  xml_text += '''<?xml version="1.0" encoding="UTF-8"?>
<efx:project name="''' + top_entity_name + '''" description="" location="'''+output_directory+'''" sw_version="2021.1.165" config_result_in_sync="true" design_ood="new" place_ood="sync" route_ood="new" xmlns:efx="http://www.efinixinc.com/enf_proj" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.efinixinc.com/enf_proj enf_proj.xsd">
    <efx:device_info>
        <efx:family name="'''+family+'''"/>
        <efx:device name="'''+parser_state.part+'''"/>
        <efx:timing_model name="'''+timing_model+'''"/>
    </efx:device_info>
    <efx:design_info def_veri_version="verilog_2k" def_vhdl_version="vhdl_2008">
        <efx:top_module name="''' + top_entity_name + '''"/>
'''

  for vhdl_file in vhdl_files_texts.split(" "):
    if vhdl_file != "":
      xml_text +='''        <efx:design_file name="'''+vhdl_file+'''" version="default" library="default"/>
''' 
  xml_text += '''
        <efx:top_vhdl_arch name=""/>
    </efx:design_info>
    <efx:constraint_info>
        <efx:sdc_file name="''' + constraints_filepath + '''"/>
        <efx:inter_file name=""/>
    </efx:constraint_info>
    <efx:sim_info/>
    <efx:misc_info/>
    <efx:ip_info/>
    <efx:synthesis tool_name="efx_map">
        <efx:param name="work_dir" value="work_syn" value_type="e_string"/>
        <efx:param name="write_efx_verilog" value="on" value_type="e_bool"/>
        <efx:param name="mode" value="speed" value_type="e_option"/>
        <efx:param name="max_ram" value="-1" value_type="e_integer"/>
        <efx:param name="max_mult" value="-1" value_type="e_integer"/>
        <efx:param name="infer-clk-enable" value="3" value_type="e_option"/>
        <efx:param name="infer-sync-set-reset" value="1" value_type="e_option"/>
        <efx:param name="fanout-limit" value="0" value_type="e_integer"/>
        <efx:param name="seq_opt" value="0" value_type="e_option"/>
        <efx:param name="bram_output_regs_packing" value="1" value_type="e_option"/>
        <efx:param name="retiming" value="1" value_type="e_option"/>
        <efx:param name="blast_const_operand_adders" value="1" value_type="e_option"/>
        <efx:param name="mult_input_regs_packing" value="1" value_type="e_option"/>
        <efx:param name="mult_output_regs_packing" value="1" value_type="e_option"/>
    </efx:synthesis>
    <efx:place_and_route tool_name="efx_pnr">
        <efx:param name="work_dir" value="work_pnr" value_type="e_string"/>
        <efx:param name="verbose" value="off" value_type="e_bool"/>
        <efx:param name="load_delaym" value="on" value_type="e_bool"/>
        <efx:param name="optimization_level" value="NULL" value_type="e_option"/>
        <efx:param name="qp_options=anneal_random_seed=" value="1" value_type="e_integer"/>
        <efx:param name="seed" value="1" value_type="e_integer"/>
    </efx:place_and_route>
    <efx:bitstream_generation tool_name="efx_pgm">
        <efx:param name="mode" value="active" value_type="e_string"/>
        <efx:param name="width" value="1" value_type="e_string"/>
        <efx:param name="cold_boot" value="off" value_type="e_bool"/>
        <efx:param name="cascade" value="off" value_type="e_option"/>
        <efx:param name="enable_roms" value="on" value_type="e_option"/>
        <efx:param name="spi_low_power_mode" value="on" value_type="e_bool"/>
        <efx:param name="io_weak_pullup" value="on" value_type="e_bool"/>
        <efx:param name="oscillator_clock_divider" value="DIV8" value_type="e_option"/>
        <efx:param name="enable_crc_check" value="on" value_type="e_bool"/>
    </efx:bitstream_generation>
    <efx:debugger>
        <efx:param name="work_dir" value="work_dbg" value_type="e_string"/>
        <efx:param name="auto_instantiation" value="off" value_type="e_bool"/>
        <efx:param name="profile" value="NONE" value_type="e_string"/>
    </efx:debugger>
</efx:project>
'''
  xml_file = top_entity_name + ".xml"
  xml_path = output_directory + "/" + xml_file
  f=open(xml_path,'w')
  f.write(xml_text)
  f.close()
  
  # Generate build scripts that sources setup and runs local python3 instance
  sh_text = ""
  # &> ''' + log_path + '''
  # &> ''' + log_path + ''';
  # #!/bin/bash
  sh_text += '''
#!/bin/sh
source ''' + EFINITY_PATH + '''/setup.sh 
efx_run.py ''' + xml_path + ''' --flow map --output_dir ''' + output_directory + '''
efx_run.py ''' + xml_path + ''' --flow pnr --output_dir ''' + output_directory + '''
'''
  sh_file = top_entity_name + ".sh"
  sh_path = output_directory + "/" + sh_file
  f=open(sh_path,'w')
  f.write(sh_text)
  f.close()
  
  # Run the build script to generate the project file
  print("Running Efinity:", sh_path, flush=True)
  syn_imp_bash_cmd =  "bash " + sh_file #+ ''' &> ''' + log_path  #"chmod +x " + "./" + sh_file + " && " + "./"
  C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
  f = open(log_path, "r")
  log_text = f.read()
  f.close()
  #print("log:",log_text)
  #sys.exit(0)
    
  return ParsedTimingReport(log_text)
  
  # PYTHON API FOR STUFF? \/ 
  
  # Generate python script that generates project file
  # Based on https://github.com/Efinix-Inc/xyloni/blob/master/bsp/build.py
  py_text = ""
  py_text += '''
#!/usr/bin/env python3

# Get access to useful python package
import os
import sys
import pprint

# Tell python where to get Interface Designer's API package
pt_home = os.environ['EFXPT_HOME']
sys.path.append(pt_home + "/bin")

from api_service.design import DesignAPI  # Get access to design database API
from api_service.device import DeviceAPI  # Get access to device database API
import api_service.excp.design_excp as APIExcp  # Get access to API exception

is_verbose = False
design = DesignAPI(is_verbose)
device = DeviceAPI(is_verbose)

# Create empty design
device_name = "T8F81"  # Matches Device name from Efinity's Project Editor
project_name = "''' + top_entity_name + '''"
output_dir = "''' + output_directory + '''"

try:
    design.create(project_name, device_name, output_dir)
except APIExcp.PTAPIException as excp:
    print("Fail to create design : {} Msg={}".format(excp.get_msg_level(), excp.get_msg()))
    sys.exit(1)
    
'''

  for vhdl_file in vhdl_files_texts.split(" "):
    py_text +='''design.load("''' + vhdl_file + '''")
'''

  py_text += '''
# Check design, generate constraints and reports
try:
    design.generate(enable_bitstream=True)
except APIExcp.PTDsgCheckException as excp:
    print("Design check fails : {} Msg={}".format(excp.get_msg_level(), excp.get_msg()))
    sys.exit(1)
except APIExcp.PTDsgGenConstException as excp:
    print("Fail to generate constraint : {} Msg={}".format(excp.get_msg_level(), excp.get_msg()))
    sys.exit(1)
except APIExcp.PTDsgGenReportException as excp:
    print("Fail to generate report : {} Msg={}".format(excp.get_msg_level(), excp.get_msg()))
    sys.exit(1)

# Save the configured periphery design
design.save()
'''

  # Write build script to output
  py_file = top_entity_name + ".py"
  py_path = output_directory + "/" + py_file
  f=open(py_path,'w')
  f.write(py_text)
  f.close()
  
  # Generate build scripts that sources setup and runs local python3 instance
  sh_text = ""
  sh_text += '''
source ''' + EFINITY_PATH + '''/setup.sh &> ''' + log_path + ''';
python3 ''' + py_path + ''' &> ''' + log_path + ''';
exit
'''
  sh_file = top_entity_name + ".sh"
  sh_path = output_directory + "/" + sh_file
  f=open(sh_path,'w')
  f.write(sh_text)
  f.close()
  
  # Run the build script to generate the project file
  print("Running Efinity:", sh_path, flush=True)
  syn_imp_bash_cmd = "bash " + sh_file  #+ ''' &> ''' + log_path
  C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd, cwd=output_directory)
  f = open(log_path, "r")
  log_text = f.read()
  f.close()
  #print("log:",log_text)
  #sys.exit(0)
    
  return ParsedTimingReport(log_text)
  
