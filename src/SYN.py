#!/usr/bin/env python3

import sys
import os
import subprocess
import math
import copy
import pickle
import glob
import hashlib
import getpass
from multiprocessing.pool import ThreadPool
from multiprocessing import Lock

def GET_TOOL_PATH(tool_exe_name):
  from shutil import which
  w = which(tool_exe_name)
  if w is not None:
    return str(w)
  return None

import C_TO_LOGIC
import VHDL
import SW_LIB
import MODELSIM
import VIVADO
import QUARTUS
import DIAMOND
import OPEN_TOOLS
import EFINITY

OUTPUT_DIR_NAME = "pipelinec_output"
SYN_OUTPUT_DIRECTORY = None # Auto created with pid and filename or from user
SYN_TOOL = None # Attempts to figure out from part number
DO_SYN_FAIL_SIM = False # Start simulation if synthesis fails

# Welcome to the land of magic numbers
#   "But I think its much worse than you feared" Modest Mouse - I'm Still Here
MAX_N_WORSE_RESULTS = 6
MAX_ALLOWED_LATENCY_MULT = 15
HIER_SWEEP_MULT_MIN = 0.5
HIER_SWEEP_MULT_INC = 0.001 # Intentionally very small, sweep tries to make largest possible steps
COARSE_SWEEP_MULT_INC = 0.01
BEST_GUESS_MUL_MAX = 25.0 # Between 20-30 is max
COARSE_SWEEP_MULT_MAX = 2.0
INF_MHZ = 1000 # Impossible timing goal
INF_HIER_MULT = 999999.9 # Needed?
MAX_CLK_INC_RATIO = 1.25 # Multiplier for how any extra clocks can be added ex. 1.25 means 25% more stages max
SLICE_EPSILON_MULTIPLIER = 5 # 6.684491979 max/best? # Constant used to determine when slices are equal. Higher=finer grain slicing, lower=similar slices are said to be equal
SLICE_STEPS_BETWEEN_REGS = 3 # Multiplier for how narrow to start off the search for better timing. Higher=More narrow start, Experimentally 2 isn't enough, slices shift <0 , > 1 easily....what?
DELAY_UNIT_MULT = 10.0 # Timing is reported in nanoseconds. Multiplier to convert that time into integer units (nanosecs, tenths, hundreds of nanosecs)


def PART_SET_TOOL(part_str, allow_fail=False):
  global SYN_TOOL
  if SYN_TOOL is None:
    # Try to guess synthesis tool based on part number
    # Hacky for now...
    if part_str is None:
      if allow_fail:
        return
      else:
        print("Need to set FPGA part somewhere in the code to continue with synthesis tool support!")
        print('Ex. #pragma PART "LFE5U-85F-6BG381C"')
        sys.exit(0)
      
    if part_str.lower().startswith("xc"):
      SYN_TOOL = VIVADO
    elif part_str.lower().startswith("ep") or part_str.lower().startswith("10c") or part_str.lower().startswith("5c"):
      SYN_TOOL = QUARTUS
    elif part_str.lower().startswith("lfe5u") or part_str.lower().startswith("ice"):
      # Diamond fails to create proj for UMG5G part?
      if "um5g" in part_str.lower():
        SYN_TOOL = OPEN_TOOLS
      else:
        SYN_TOOL = DIAMOND #OPEN_TOOLS # Can replace with SYN_TOOL = DIAMOND
    elif part_str.upper().startswith("T8") or part_str.upper().startswith("TI"):
      SYN_TOOL = EFINITY
    else:
      if not allow_fail:
        print("No known synthesis tool for FPGA part:",part_str, flush=True)
        sys.exit(-1)
    
    if SYN_TOOL is not None:
      print("Using",SYN_TOOL.__name__, "synthesizing for part:",part_str)




# These are the parameters that describe how multiple pipelines are timed
class MultiMainTimingParams:
  def __init__(self):
    # Pipeline params
    self.TimingParamsLookupTable = dict()
    # TODO some kind of params for clock crossing
    
  def GET_HASH_EXT(self, parser_state):
    # Just hash all the slices #TODO fix to just mains
    top_level_str = ""
    for main_func in sorted(parser_state.main_mhz.keys()):
      timing_params = self.TimingParamsLookupTable[main_func]
      hash_ext_i = timing_params.GET_HASH_EXT(self.TimingParamsLookupTable, parser_state)
      top_level_str += hash_ext_i
    s = top_level_str
    hash_ext = "_" + ((hashlib.md5(s.encode("utf-8")).hexdigest())[0:4]) #4 chars enough?
    return hash_ext

# These are the parameters that describe how a pipeline should be formed
class TimingParams:
  def __init__(self,inst_name, logic):
    self.logic = logic
    self.inst_name = inst_name
    
    # Have the current params (slices) been fixed,
    # Default to fixed if known cant be sliced
    self.params_are_fixed = not logic.CAN_BE_SLICED()
    # Params, private _ since cached
    self._slices = [] # Unless raw vhdl (no submodules), these are only ~approximate slices
    # ??Maybe add flag for these fixed slices provide latency, dont rebuild? unecessary?
    self._has_input_regs = False
    self._has_output_regs = False
        
    # Sometimes slices are between submodules,
    # This can specify where a stage is artificially started by not allowing submodules to be instantiated even if driven in an early state
    # UNUSED FOR NOW
    #self.submodule_to_start_stage = dict()
    #self.submodule_to_end_stage = dict()
    
    # Cached stuff
    self.calcd_total_latency = None
    self.hash_ext = None
    #self.timing_report_stage_range = None
    
  def DEEPCOPY(self):
    rv = copy.copy(self)
    rv._slices = self._slices[:] # COPY
    # Logic ok to be same obj
    # All others immut right now
    return rv
    
  def INVALIDATE_CACHE(self):
    self.calcd_total_latency = None
    self.hash_ext = None
    #self.timing_report_stage_range = None
    
  # I was dumb and used get latency all over
  # mAKE CACHED VERSION
  def GET_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):    
    if self.calcd_total_latency is None:
      self.calcd_total_latency = self.CALC_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
    return self.calcd_total_latency
        
  # Haha why uppercase everywhere ...
  def CALC_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
    # C built in has multiple shared latencies based on where used
    if len(self.logic.submodule_instances) <= 0:
      # Just pipeline slices
      pipeline_latency = len(self._slices)
    else:
      # If cant be sliced then latency must be zero right?
      if not self.logic.CAN_BE_SLICED():
        if self._has_input_regs or self._has_output_regs:
          print("Bad io regs on non sliceable!")
          sys.exit(-1)
        return 0
        
      if TimingParamsLookupTable is None:
        print("Need TimingParamsLookupTable for non raw hdl latency",self.logic.func_name)
        print(0/0)
        sys.exit(-1)
        
      pipeline_map = GET_PIPELINE_MAP(self.inst_name, self.logic, parser_state, TimingParamsLookupTable)
      pipeline_latency = pipeline_map.num_stages - 1
    
    # Adjut latency for io regs
    latency = pipeline_latency
    if self._has_input_regs:
      latency += 1
    if self._has_output_regs:
      latency += 1

    return latency
    
  def RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(self, inst_name, Logic, TimingParamsLookupTable, parser_state):
    # All modules include IO reg flags
    timing_params = TimingParamsLookupTable[inst_name]
    rv = (timing_params._has_input_regs, timing_params._has_output_regs,)
    # Only lowest level raw VHDL modules with no submodules include slices
    if len(Logic.submodule_instances) > 0:
      # Not raw hdl, slices dont guarentee describe pipeline structure
      for submodule in sorted(Logic.submodule_instances): # MUST BE SORTED FOR CONSISTENT ORDER!
        sub_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule
        if sub_inst not in parser_state.LogicInstLookupTable:
          print("Missing inst_name:",sub_inst)
          print("has instances:")
          for inst_i,logic_i in parser_state.LogicInstLookupTable.items():
            print(inst_i)
          print(0/0,flush=True)
          sys.exit(-1)
        sub_logic = parser_state.LogicInstLookupTable[sub_inst]
        rv += (self.RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(sub_inst, sub_logic, TimingParamsLookupTable, parser_state),)
    else:
      # Raw HDL
      rv += (tuple(timing_params._slices),)
      
    return rv
    
  # Hash ext only reflect raw hdl slices (better would be raw hdl bits per stage)
  def BUILD_HASH_EXT(self, inst_name, Logic, TimingParamsLookupTable, parser_state):
    #print("BUILD_HASH_EXT",Logic.func_name, flush=True)
    io_regs_and_slices_tup = self.RECURSIVE_GET_IO_REGS_AND_NO_SUBMODULE_SLICES(inst_name, Logic, TimingParamsLookupTable, parser_state)
    s = str(io_regs_and_slices_tup)
    full_hash = (hashlib.md5(s.encode("utf-8")).hexdigest())
    hash_ext = "_" + (full_hash[0:8]) #4 chars enough, no you dummy, lets hope 8 is
    #print(f"inst {inst_name} {full_hash} {hash_ext}")
    return hash_ext
      
  def GET_HASH_EXT(self, TimingParamsLookupTable, parser_state):
    if self.hash_ext is None:
      self.hash_ext = self.BUILD_HASH_EXT(self.inst_name, self.logic, TimingParamsLookupTable, parser_state)
    
    return self.hash_ext
    
  def ADD_SLICE(self, slice_point):     
    if self._slices is None:
      self._slices = []
    if slice_point > 1.0:
      print("Slice > 1.0?",slice_point)
      sys.exit(-1)
      slice_point = 1.0
    if slice_point < 0.0:
      print("Slice < 0.0?",slice_point)
      print(0/0)
      sys.exit(-1)
      slice_point = 0.0

    if not(slice_point in self._slices):
      self._slices.append(slice_point)
      self._slices = sorted(self._slices)
      self.INVALIDATE_CACHE()
    else:
      raise Exception(f"Slice {slice_point} exists already cant add? slices pre add: {self._slices}")
      
    
    if self.calcd_total_latency is not None:
      print("WTF adding a slice and has latency cache?",self.calcd_total_latency)
      print(0/0)
      sys.exit(-1)
      
  def SET_SLICES(self, value):
    if value != self._slices:
      self._slices = value[:]
      self.INVALIDATE_CACHE()
      
  def SET_HAS_IN_REGS(self, value):
    if value != self._has_input_regs:
      self._has_input_regs = value
      self.INVALIDATE_CACHE()
  
  def SET_HAS_OUT_REGS(self, value):
    if value != self._has_output_regs:
      self._has_output_regs = value
      self.INVALIDATE_CACHE()
  
  '''
  # Returns if add was success
  def ADD_SUBMODULE_END_STAGE(self, end_submodule, end_stage):
    if end_submodule not in self.submodule_to_end_stage:
      self.submodule_to_end_stage[end_submodule] = end_stage
      self.INVALIDATE_CACHE() 
    else:
      if end_stage != self.submodule_to_end_stage[end_submodule]:
        # not allowed like that?
        return False
        #print 0/0
        #sys.exit(-1)
        
    return True
    
  # Returns if add was success
  def ADD_SUBMODULE_START_STAGE(self, start_submodule, start_stage):
    if start_submodule not in self.submodule_to_start_stage:
      self.submodule_to_start_stage[start_submodule] = start_stage
      self.INVALIDATE_CACHE() 
    else:
      if start_stage != self.submodule_to_start_stage[start_submodule]:
        # not allowed like that?
        return False
        #print 0/0
        #sys.exit(-1)
        
    return True
  '''
    
  def GET_SUBMODULE_LATENCY(self, submodule_inst_name, parser_state, TimingParamsLookupTable):
    submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
    return submodule_timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)


def DEL_ALL_CACHES():
  # Clear all caches after parsing is done
  global _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache
  #global _GET_ZERO_CLK_TIMING_PARAMS_LOOKUP_cache
  
  _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache         = dict()
  #_GET_ZERO_CLK_TIMING_PARAMS_LOOKUP_cache    = dict()
  #_GET_ZERO_CLK_PIPELINE_MAP_cache = dict()


    
_GET_ZERO_CLK_HASH_EXT_LOOKUP_cache = dict()
_GET_ZERO_CLK_TIMING_PARAMS_LOOKUP_cache = dict()
def GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state):
  # Cached?
  #print("GET_ZERO_CLK_TIMING_PARAMS_LOOKUP")
  cache_key = str(sorted(set(parser_state.LogicInstLookupTable.keys())))
  if cache_key in _GET_ZERO_CLK_TIMING_PARAMS_LOOKUP_cache:
    cached_lookup = _GET_ZERO_CLK_TIMING_PARAMS_LOOKUP_cache[cache_key]
    rv = dict()
    for inst_i,params_i in cached_lookup.items():
      rv[inst_i] = params_i.DEEPCOPY()
    return rv
  
  # Create empty lookup
  ZeroClockTimingParamsLookupTable = dict()
  for logic_inst_name in parser_state.LogicInstLookupTable: 
    logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
    timing_params_i = TimingParams(logic_inst_name, logic_i)
    ZeroClockTimingParamsLookupTable[logic_inst_name] = timing_params_i
  
  # Calc cached params so they are in cache
  
  # Set latency as known
  for logic_inst_name in parser_state.LogicInstLookupTable:
    timing_params_i = ZeroClockTimingParamsLookupTable[logic_inst_name]
    # Known latency is 0 here - fake calculating it
    timing_params_i.calcd_total_latency = 0
  
  # Latency knonwn so following hash ext calcs dont need to calc pipeline map for latency
  for logic_inst_name in parser_state.LogicInstLookupTable: 
    logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
    timing_params_i = ZeroClockTimingParamsLookupTable[logic_inst_name]
    #timing_params_i.GET_TOTAL_LATENCY(parser_state, ZeroClockTimingParamsLookupTable) 
    if logic_i.func_name in _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache:
      timing_params_i.hash_ext = _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache[logic_i.func_name]
    else:
      _GET_ZERO_CLK_HASH_EXT_LOOKUP_cache[logic_i.func_name] = timing_params_i.GET_HASH_EXT(ZeroClockTimingParamsLookupTable, parser_state)
  
  _GET_ZERO_CLK_TIMING_PARAMS_LOOKUP_cache[cache_key] = ZeroClockTimingParamsLookupTable
  return ZeroClockTimingParamsLookupTable

_GET_ZERO_CLK_PIPELINE_MAP_cache = dict()
def GET_ZERO_CLK_PIPELINE_MAP(inst_name, Logic, parser_state, write_files=True):
  key = Logic.func_name
  
  # Try cache
  try:
    rv = _GET_ZERO_CLK_PIPELINE_MAP_cache[key]
    #print "_GET_ZERO_CLK_PIPELINE_MAP_cache",key
    
    # Sanity?
    if rv.logic != Logic:
      print("Zero clock cache no mactho")
      sys.exit(-1)
    
    return rv
  except:
    pass
    
  has_delay = True
  # Only need to check submodules, not self
  for sub_inst in Logic.submodule_instances:
    func_name = Logic.submodule_instances[sub_inst]
    sub_func_logic = parser_state.FuncLogicLookupTable[func_name]
    if sub_func_logic.delay is None:
      print(sub_func_logic.func_name)
      has_delay = False
      break
  if not has_delay:
    print("Can't get zero clock pipeline map without delay?") 
    print(0/0)
    sys.exit(-1)
  
  
  # Populate table as all 0 clk
  ZeroClockLogicInst2TimingParams = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state)
  
  # Get params for this logic
  #print "Logic.func_name",Logic.func_name

  # Get pipeline map
  zero_clk_pipeline_map = GET_PIPELINE_MAP(inst_name, Logic, parser_state, ZeroClockLogicInst2TimingParams)
  
  # Only cache if has delay
  # zero_clk_pipeline_map.logic.delay is not None and  Dont need to check self, only submodules
  if zero_clk_pipeline_map.zero_clk_max_delay is not None:
    _GET_ZERO_CLK_PIPELINE_MAP_cache[key] = zero_clk_pipeline_map
  else:
    # Sanity?
    if has_delay:
      print("has delay for subs but did not calc in zero clk map?",zero_clk_pipeline_map.logic.func_name)
      sys.exit(-1)
  
  return zero_clk_pipeline_map

# This started off as just code writing VHDL
# Then the logic of how the VHDL was written was highjacked for latency calculation
# Then latency calculations were highjacked for logic delay calculations
class PipelineMap:
  def __init__(self, logic):
    self.logic = logic
    # Any logic will have
    self.per_stage_texts = dict() # VHDL texts dict[stage_num]=[per,submodule,level,texts]
    self.stage_ordered_submodule_list = dict()
    self.num_stages = 1 # Comb logic
    
    # DELAY STUFF ONLY MAKES SENSE TO TALK ABOUT WHEN:
    # - 0 CLKS
    # - >0 delay submodules
    #  ITS NOT CLEAR HOW SLICES ACTUALLY DISTRIBUTE DELAY
    #  Ex. 1 ns split 2 equal clks? 
    #    0.3 | 0.3 | 0.3  ?
    #    0   |  1  |  0   ?   Some raw VHDL is like this
    # Also once you are doing fractional stuff you might as well be doing delay ns
    # Doing slicing for multiple clocks shouldnt require multi clk pipeline maps anyway right?
    # HELP ME
    self.zero_clk_per_delay_submodules_map = dict() # dict[delay_offset] => [submodules,at,offset]
    self.zero_clk_submodule_start_offset = dict() # dict[submodule_inst] = start_offset  # In delay units
    self.zero_clk_submodule_end_offset = dict() # dict[submodule_inst] => end_offset # In delay units
    self.zero_clk_max_delay = None
    
  def __str__(self):
    rv = "Pipeline Map:\n"
    for delay in sorted(self.zero_clk_per_delay_submodules_map.keys()):
      submodules_insts = self.zero_clk_per_delay_submodules_map[delay]
      submodule_func_names = []
      for submodules_inst in submodules_insts:
        submodule_func_names.append(submodules_inst)

      rv += str(delay) + ": " + str(sorted(submodule_func_names)) + "\n"
    rv = rv.strip("\n")
    return rv
    
# This code is so dumb that I dont want to touch it
# Forgive me
# im such a bitch
#                   .---..---.                                                                                
#               .--.|   ||   |                                                                                
#        _     _|__||   ||   |                                                                                
#  /\    \\   //.--.|   ||   |                                                                                
#  `\\  //\\ // |  ||   ||   |                                                                                
#    \`//  \'/  |  ||   ||   |                                                                                
#     \|   |/   |  ||   ||   |                                                                                
#      '        |  ||   ||   |                                                                                
#               |__||   ||   |                                                                                
#                   '---''---'                                                                                
#                                                                                                             
#                                                                                                                                                                                                                     
#               .---.                                                                                         
# .--.          |   |.--..----.     .----.   __.....__                                                        
# |__|          |   ||__| \    \   /    /.-''         '.                                                      
# .--.          |   |.--.  '   '. /'   //     .-''"'-.  `.                                                    
# |  |          |   ||  |  |    |'    //     /________\   \                                                   
# |  |          |   ||  |  |    ||    ||                  |                                                   
# |  |          |   ||  |  '.   `'   .'\    .-------------'                                                   
# |  |          |   ||  |   \        /  \    '-.____...---.                                                   
# |__|          |   ||__|    \      /    `.             .'                                                    
#               '---'         '----'       `''-...... -'                                                      
#                                                                                                                                                                                                                     
#               .-'''-.                                                                         .-''''-..     
#              '   _    \                                                                     .' .'''.   `.   
#            /   /` '.   \               __.....__   .----.     .----.   __.....__           /    \   \    `. 
#      _.._ .   |     \  '           .-''         '.  \    \   /    /.-''         '.         \    '   |     | 
#    .' .._||   '      |  '.-,.--.  /     .-''"'-.  `. '   '. /'   //     .-''"'-.  `. .-,.--.`--'   /     /  
#    | '    \    \     / / |  .-. |/     /________\   \|    |'    //     /________\   \|  .-. |    .'  ,-''   
#  __| |__   `.   ` ..' /  | |  | ||                  ||    ||    ||                  || |  | |    |  /       
# |__   __|     '-...-'`   | |  | |\    .-------------''.   `'   .'\    .-------------'| |  | |    | '        
#    | |                   | |  '-  \    '-.____...---. \        /  \    '-.____...---.| |  '-     '-'        
#    | |                   | |       `.             .'   \      /    `.             .' | |        .--.        
#    | |                   | |         `''-...... -'      '----'       `''-...... -'   | |       /    \       
#    | |                   |_|                                                         |_|       \    /       
#    |_|
# 
def GET_PIPELINE_MAP(inst_name, logic, parser_state, TimingParamsLookupTable):  
  # RAW HDL doesnt need this
  if len(logic.submodule_instances) <= 0 and logic.is_c_built_in: #logic.func_name not in parser_state.main_mhz:
    print("DONT USE GET_PIPELINE_MAP ON RAW HDL LOGIC!")
    print(0/0)
    sys.exit(-1)
    
  # FORGIVE ME - never
  print_debug = False #inst_name=="posix_aws_fpga_dma" #False
  bad_inf_loop = False
  LogicInstLookupTable = parser_state.LogicInstLookupTable
  timing_params = TimingParamsLookupTable[inst_name]
  rv = PipelineMap(logic)
  #print("Get pipeline map inst_name",inst_name,flush=True)
  # Shouldnt need debug for zero clock? You wish you sad lazy person
  #print_debug = print_debug and (est_total_latency>0)
  if print_debug:
    print("==============================Getting pipeline map=======================================")
    print("GET_PIPELINE_MAP:")
    print("inst_name",inst_name)
    print("logic.func_name",logic.func_name)
    #print "logic.submodule_instances:",logic.submodule_instances
  
  # Delay stuff was hacked into here and only works for combinatorial logic
  est_total_latency = None
  is_zero_clk = False
  # Cant estimate latency but can know if is zero clocks - only one way to do that
  is_zero_clk = True
  for local_sub_inst in logic.submodule_instances:
    sub_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + local_sub_inst
    if sub_inst not in TimingParamsLookupTable:
      print("Missing timing params for instance:",sub_inst)
      print("has instances:")
      for inst_i,params_i in TimingParamsLookupTable.items():
        print(inst_i)
      print(0/0,flush=True)
      sys.exit(-1)
    submodule_timing_params = TimingParamsLookupTable[sub_inst]
    submodule_latency = submodule_timing_params.GET_TOTAL_LATENCY(parser_state,TimingParamsLookupTable)
    if submodule_latency > 0:
      is_zero_clk = False
      break
  has_delay = True
  # Only need to check submodules, not self
  for sub_inst in logic.submodule_instances:
    func_name = logic.submodule_instances[sub_inst]
    sub_func_logic = parser_state.FuncLogicLookupTable[func_name]
    if sub_func_logic.delay is None:
      has_delay = False
      break
  is_zero_clk_has_delay = is_zero_clk and has_delay

  if print_debug:
    print("timing_params._slices",timing_params._slices)
    print("is_zero_clk_has_delay",is_zero_clk_has_delay)
    
  # Keep track of submodules whos inputs are fully driven
  fully_driven_submodule_inst_2_logic = dict()
  # And keep track of which submodules remain
  # as to not keep looping over all submodules (sloo)
  not_fully_driven_submodules = set(logic.submodule_instances.keys())
    
  # Upon writing a submodule do not 
  # add output wire (and driven by output wires) to wires_driven_so_far
  # Intead delay them for N clocks as counted by the clock loop
  #   "Let's pretend we don't exist. Lets pretend we're in Antarctica" - Of Montreal
  wire_to_remaining_clks_before_driven = dict()
  # All wires start with invalid latency as to not write them too soon
  for wire in logic.wires:
    wire_to_remaining_clks_before_driven[wire] = -1
  
  # To keep track of 'execution order' do this stupid thing:
  # Keep a list of wires that are have been driven so far
  # Search this list to filter which submodules are in each level
  # Replaced wires_driven_so_far
  wires_driven_by_so_far = dict() # driven wire -> driving wire
  def RECORD_DRIVEN_BY(driving_wire, driven_wire_or_wires):
    if type(driven_wire_or_wires) == list:
      driven_wires = driven_wire_or_wires
    elif type(driven_wire_or_wires) == set:
      driven_wires = list(driven_wire_or_wires)
    else:
      driven_wires = [driven_wire_or_wires]
    for driven_wire in driven_wires:
      wires_driven_by_so_far[driven_wire] = driving_wire
      # Also set clks? Seems right?
      wire_to_remaining_clks_before_driven[driven_wire] = 0
  
  # Some wires are driven to start with
  RECORD_DRIVEN_BY(None, logic.inputs)
  RECORD_DRIVEN_BY(None, C_TO_LOGIC.CLOCK_ENABLE_NAME)
  RECORD_DRIVEN_BY(None, set(logic.state_regs.keys()))
  RECORD_DRIVEN_BY(None, logic.feedback_vars)
  # Also "CONST" wires representing constants like '2' are already driven
  for wire in logic.wires:
    #print "wire=",wire
    if C_TO_LOGIC.WIRE_IS_CONSTANT(wire):
      #print "CONST->",wire
      RECORD_DRIVEN_BY(None, wire)
      
  # Keep track of delay offset when wire is driven
  # ONLY MAKES SENSE FOR 0 CLK RIGHT NOW
  delay_offset_when_driven = dict()
  for wire_driven_so_far in list(wires_driven_by_so_far.keys()):
    delay_offset_when_driven[wire_driven_so_far] = 0 # Is per stage value but we know is start of stage 0 
  
  # Start with wires that have drivers
  last_wires_starting_level = None
  wires_starting_level=list(wires_driven_by_so_far.keys())[:] 
  next_wires_to_follow=[]

  # Bound on latency for sanity
  if est_total_latency is not None:
    max_possible_latency = est_total_latency
    max_possible_latency_with_extra = max_possible_latency + 2
  stage_num = 0
  
  # Pipeline is done when
  def PIPELINE_DONE():
    # ALl outputs driven
    for output in logic.outputs:
      if (output not in wires_driven_by_so_far) or (wires_driven_by_so_far[output]==None):
        if print_debug:
          print("Pipeline not done output.",output)
        return False
      if print_debug:
        print("Output driven ", output, "<=",wires_driven_by_so_far[output])
    # Feedback wires
    for feedback_var in logic.feedback_vars:
      if (feedback_var not in wires_driven_by_so_far) or (wires_driven_by_so_far[feedback_var]==None):
        if print_debug:
          print("Pipeline not done feedback var.",feedback_var)
        return False
      if print_debug:
        print("Feedback var driven ", feedback_var, "<=",wires_driven_by_so_far[feedback_var])  
    # ALl globals driven
    for state_reg in logic.state_regs:
      if logic.state_regs[state_reg].is_volatile == False:
        global_wire = state_reg
        if (global_wire not in wires_driven_by_so_far) or (wires_driven_by_so_far[global_wire]==None):
          if print_debug:
            print("Pipeline not done global.",global_wire)
          return False
        if print_debug:
          print("Global driven ", global_wire, "<=",wires_driven_by_so_far[global_wire])
    # ALl voltatile globals driven
    # Some volatiles are read only - ex. valid indicator bit
    # And thus are never driven
    # Allow a volatile global wire not to be driven if logic says it is undriven 
    for state_reg in logic.state_regs:
      if logic.state_regs[state_reg].is_volatile:
        volatile_global_wire = state_reg
        if volatile_global_wire in logic.wire_driven_by:
          # Has a driving wire so must be driven for func to be done
          if (volatile_global_wire not in wires_driven_by_so_far) or (wires_driven_by_so_far[volatile_global_wire]==None):
            if print_debug:
              print("Pipeline not done volatile global.",volatile_global_wire)
            return False
        if print_debug:
          print("Volatile driven ", volatile_global_wire, "<=",wires_driven_by_so_far[volatile_global_wire])
    
    # All other wires driven?
    for wire in logic.wires:
      if wire not in wires_driven_by_so_far and not logic.WIRE_ALLOW_NO_DRIVEN_BY(wire,parser_state.FuncLogicLookupTable): # None is OK? since only use for globals and inputs and such?
        if print_debug:
          print("Pipeline not done wire.",wire)
        return False
      if print_debug:
        driven_by = None
        if wire in wires_driven_by_so_far:
          driven_by = wires_driven_by_so_far[wire]
        print("Wire driven ", wire, "<=",driven_by)
        
    return True
  
  # WHILE LOOP FOR MULTI STAGE/CLK
  while not PIPELINE_DONE():      
    # Print stuff and set debug if obviously wrong
    if stage_num >= 5000:
      print("Pipeline too long? Past hard coded limit probably...")
      print("inst_name", inst_name)
      bad_inf_loop = True
      print_debug = True
      #print(0/0)
      #sys.exit(-1)
    if est_total_latency is not None:
      if (stage_num >= max_possible_latency_with_extra):
        print("Something is wrong here, infinite loop probably...")
        print("inst_name", inst_name)
        #print 0/0
        sys.exit(-1)
      elif (stage_num >= max_possible_latency+1):
        bad_inf_loop = True
        print_debug = True
    if print_debug:
      print("STAGE NUM =", stage_num)

    rv.per_stage_texts[stage_num] = []
    submodule_level = 0
    # DO WHILE LOOP FOR PER COMB LOGIC SUBMODULE LEVELS
    while True: # DO
      submodule_level_text = ""
            
      if print_debug:
        print("SUBMODULE LEVEL",submodule_level)
      
      #########################################################################################
      # THIS WHILE LOOP FOLLOWS WIRES TO SUBMODULES
      # (BEWARE!: NO SUBMODULES MAY BE FULLY DRIVEN DUE TO MULTI CLK LATENCY)
      # First follow wires to submodules
      #print "wires_driven_by_so_far",wires_driven_by_so_far
      #print "wires_starting_level",wires_starting_level
      wires_to_follow=wires_starting_level[:]           
      while len(wires_to_follow)>0:
        # Sort wires to follow for easy debug of duplicates
        wires_to_follow = sorted(wires_to_follow)
        for driving_wire in wires_to_follow:
          if bad_inf_loop:
            print("driving_wire",driving_wire)
          
          # Record driving wire as being driven?
          if driving_wire not in wires_driven_by_so_far:
            # What drives the driving wire?
            # Dont know driving wire?
            driver_of_driver = None
            if driving_wire in logic.wire_driven_by:
              driver_of_driver = logic.wire_driven_by[driving_wire]
            RECORD_DRIVEN_BY(driver_of_driver, driving_wire)

          # Loop over what this wire drives
          if driving_wire in logic.wire_drives:
            driven_wires = logic.wire_drives[driving_wire]
            if bad_inf_loop:
              print("driven_wires",driven_wires)
              
            # Sort for easy debug
            driven_wires = sorted(driven_wires)
            for driven_wire in driven_wires:
              if bad_inf_loop:
                print("handling driven wire", driven_wire)
                
              if not(driven_wire in logic.wire_driven_by):
                # In
                print("!!!!!!!!!!!! DANGLING LOGIC???????",driven_wire, "is not driven!?")
                continue
                            
              # Add driven wire to wires driven so far
              # Record driving this wire, at this logic level offset
              if (driven_wire in wires_driven_by_so_far) and (wires_driven_by_so_far[driven_wire] is not None):
                # Already handled this wire
                continue
              RECORD_DRIVEN_BY(driving_wire, driven_wire)
                
              # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
              if is_zero_clk_has_delay:
                delay_offset_when_driven[driven_wire] = delay_offset_when_driven[driving_wire]
              #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~   
              
              # Follow the driven wire unless its a submodule input port
              # Submodules input ports is handled at hierarchy cross later - do nothing later
              if not C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(driven_wire, logic):
                # Record reaching another wire
                next_wires_to_follow.append(driven_wire)
              
              
              # Dont write text connecting VHDL input ports
              # (connected directly in func call params)
              if C_TO_LOGIC.WIRE_IS_VHDL_EXPR_SUBMODULE_INPUT_PORT(driven_wire, logic, parser_state):
                continue
              if C_TO_LOGIC.WIRE_IS_VHDL_FUNC_SUBMODULE_INPUT_PORT(driven_wire, logic, parser_state):
                continue
              
              ### WRITE VHDL TEXT
              # If the driving wire is a submodule output AND LATENCY>0 then RHS uses register style 
              # as way to ensure correct multi clock behavior 
              RHS = VHDL.GET_RHS(driving_wire, inst_name, logic, parser_state, TimingParamsLookupTable, rv.stage_ordered_submodule_list, stage_num)
              # Submodule or not LHS is write pipe wire
              LHS = VHDL.GET_LHS(driven_wire, logic, parser_state)
              #print "logic.func_name",logic.func_name
              #print "driving_wire, driven_wire",driving_wire, driven_wire
              # Need VHDL conversions for this type assignment?
              TYPE_RESOLVED_RHS = VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS(RHS, logic, driving_wire, driven_wire, parser_state)
              
              # Typical wires using := assignment, but feedback wires need <=
              ass_op = ":="
              if driven_wire in logic.feedback_vars:
                ass_op = "<="
              submodule_level_text += " " + " " + " " + LHS + " " + ass_op + " " + TYPE_RESOLVED_RHS + ";" + "\n" # + " -- " + driven_wire + " <= " + driving_wire + 
                
                
        wires_to_follow=next_wires_to_follow[:]
        next_wires_to_follow=[]
      
      
      #########################################################################################
      
      
      
      # \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/ GET FULLY DRIVEN SUBMODULES TO POPULATE SUBMODULE LEVEL \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/ 
      # Have followed this levels wires to submodules
      # We only want to consider the submodules whose inputs have all 
      # been driven by now in clock cycle to keep execution order
      #   ALSO:
      #     Slicing between submodules is done via artificially delaying when submodules are instantiated/connected into later stages
      fully_driven_submodule_inst_this_level_2_logic = dict()
      # Get submodule logics
      # Loop over each sumodule and check if all inputs are driven
      not_fully_driven_submodules_iter = set(not_fully_driven_submodules)
      for submodule_inst in not_fully_driven_submodules_iter:
        submodule_inst_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
        # Skip submodules weve done already
        already_fully_driven = submodule_inst in fully_driven_submodule_inst_2_logic
        # Also skip if not the correct stage for this submodule 
        incorrect_stage_for_submodule = False
        '''
        NOT DOING THIS FOR NOW
        if submodule_inst in timing_params.submodule_to_start_stage:
          incorrect_stage_for_submodule = stage_num != timing_params.submodule_to_start_stage[submodule_inst]
        '''
        
        #if print_debug:
        # print ""
        # print "########"
        # print "SUBMODULE INST",submodule_inst, "FULLY DRIVEN?:",already_fully_driven
        
        if not already_fully_driven and not incorrect_stage_for_submodule:
          submodule_logic = parser_state.LogicInstLookupTable[submodule_inst_name]
          
          # Check submodule signals that need to be driven before submodule can be used
          # CLOCK ENABLE + INPUTS
          submodule_has_all_inputs_driven = True
          submodule_input_port_driving_wires = []
          # Check clock enable
          if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(submodule_logic, parser_state):
            #print "logic.func_name", logic.func_name
            ce_wire = submodule_inst+ C_TO_LOGIC.SUBMODULE_MARKER + C_TO_LOGIC.CLOCK_ENABLE_NAME
            ce_driving_wire = logic.wire_driven_by[ce_wire]
            submodule_input_port_driving_wires.append(ce_driving_wire)
            if ce_driving_wire not in wires_driven_by_so_far:
              submodule_has_all_inputs_driven = False
          # Check each input
          if submodule_has_all_inputs_driven:
            for input_port_name in submodule_logic.inputs:
              driving_wire = C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(logic, submodule_inst,input_port_name)
              submodule_input_port_driving_wires.append(driving_wire)
              if driving_wire not in wires_driven_by_so_far:
                submodule_has_all_inputs_driven = False
                if bad_inf_loop:
                  print("!! " + submodule_inst + " input wire " + input_port_name + " not driven yet")
                  #print " is driven by", driving_wire
                  #print "  <<<<<<<<<<<<< ", driving_wire , "is not (fully?) driven?"
                  #print " <<<<<<<<<<<<< YOU ARE PROBABALY NOT DRIVING ALL LOCAL VARIABLES COMPLETELY(STRUCTS) >>>>>>>>>>>> "
                  #C_TO_LOGIC.PRINT_DRIVER_WIRE_TRACE(driving_wire, logic, wires_driven_by_so_far)
                break
          
          # If all inputs are driven
          if submodule_has_all_inputs_driven: 
            fully_driven_submodule_inst_2_logic[submodule_inst]=submodule_logic
            fully_driven_submodule_inst_this_level_2_logic[submodule_inst] = submodule_logic
            not_fully_driven_submodules.remove(submodule_inst)
            if bad_inf_loop:
              print("submodule",submodule_inst, "HAS ALL INPUTS DRIVEN")


            # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            if is_zero_clk_has_delay:
              # Record delay offset as max of driving wires
              # Do zero_clk_submodule_start_offset INPUT OFFSET as max of input wires
              # Start with 0 since submodule can have no inputs and this no input port delay offset
              input_port_delay_offsets = [0]
              for submodule_input_port_driving_wire in submodule_input_port_driving_wires:
                delay_offset = delay_offset_when_driven[submodule_input_port_driving_wire]
                input_port_delay_offsets.append(delay_offset)
              max_input_port_delay_offset = max(input_port_delay_offsets)
              
              # All submodules should be driven at some offset right?
              #print "wires_driven_by_so_far",wires_driven_by_so_far
              #print "delay_offset_when_driven",delay_offset_when_driven
              rv.zero_clk_submodule_start_offset[submodule_inst] = max_input_port_delay_offset
              
              
              # Do  delay starting at the input offset
              # This delay_offset_when_driven value wont be used 
              # until the stage when the output wire is read
              # So needs delay expected in last stage
              submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
              submodule_delay = parser_state.LogicInstLookupTable[submodule_inst_name].delay
              if submodule_delay is None:
                print("What cant do this without delay!",inst_name,submodule_inst_name)
                sys.exit(-1)
              submodule_latency = submodule_timing_params.GET_TOTAL_LATENCY(parser_state,TimingParamsLookupTable)
              
              
              # Sanity?
              if submodule_latency > 0:
                print("What non zero latency for pipeline map? FIX MEhow? Probably dont fix now since fractional delay dont/cant make sense yet?")
                #HOW TO ALLOCATE delay?
                print(0/0)
                sys.exit(-1)
              # End offset is start offset plus delay
              # Ex. 0 delay in offset 0 
              # Starts and ends in offset 0
              # Ex. 1 delay unit in offset 0 
              # ALSO STARTS AND ENDS IN STAGE 0
              if submodule_delay > 0:
                abs_delay_end_offset = submodule_delay + rv.zero_clk_submodule_start_offset[submodule_inst] - 1
              else:
                abs_delay_end_offset = rv.zero_clk_submodule_start_offset[submodule_inst] 
              rv.zero_clk_submodule_end_offset[submodule_inst] = abs_delay_end_offset
                
              # Do PARALLEL submodules map with start and end offsets from each stage
              # Dont do for 0 delay submodules, ok fine
              if submodule_delay > 0:
                start_offset = rv.zero_clk_submodule_start_offset[submodule_inst]
                end_offset = rv.zero_clk_submodule_end_offset[submodule_inst]
                for abs_delay in range(start_offset,end_offset+1):
                  if abs_delay < 0:
                    print("<0 delay offset?")
                    print(start_offset,end_offset)
                    print(delay_offset_when_driven)
                    sys.exit(-1)
                  # Submodule isnts
                  if not(abs_delay in rv.zero_clk_per_delay_submodules_map):
                    rv.zero_clk_per_delay_submodules_map[abs_delay] = []
                  if not(submodule_inst in rv.zero_clk_per_delay_submodules_map[abs_delay]):
                    rv.zero_clk_per_delay_submodules_map[abs_delay].append(submodule_inst)
                    
            # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            
            
          else:
            # Otherwise save for later
            if bad_inf_loop:
              print("submodule",submodule_inst, "does not have all inputs driven yet")
            
        else:
          #if not already_fully_driven and not incorrect_stage_for_submodule:
          if print_debug:
            if not already_fully_driven:
              print("submodule",submodule_inst)
              print("already_fully_driven",already_fully_driven)
              #if submodule_inst in timing_params.submodule_to_start_stage:
              # print "incorrect_stage_for_submodule",incorrect_stage_for_submodule," = ",stage_num, "stage_num != ", timing_params.submodule_to_start_stage[submodule_inst]
          
      #print "got input driven submodules, wires_driven_by_so_far",wires_driven_by_so_far
      if bad_inf_loop:
        print("fully_driven_submodule_inst_this_level_2_logic",fully_driven_submodule_inst_this_level_2_logic)
      #/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\
      
      # Im dumb
      submodule_level_iteration_has_submodules = len(fully_driven_submodule_inst_this_level_2_logic) > 0
          
      ############################# GET OUTPUT WIRES FROM SUBMODULE LEVEL #############################################
      # Get list of output wires for this all the submodules in this level
      # by writing submodule connections / entity connections
      submodule_level_output_wires = []
      for submodule_inst in fully_driven_submodule_inst_this_level_2_logic:
        submodule_inst_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
        submodule_logic = parser_state.LogicInstLookupTable[submodule_inst_name]
        
        # Record this submodule in this stage
        if stage_num not in rv.stage_ordered_submodule_list:
          rv.stage_ordered_submodule_list[stage_num] = []
        if submodule_inst not in rv.stage_ordered_submodule_list[stage_num]:
          rv.stage_ordered_submodule_list[stage_num].append(submodule_inst)
          
        # Get latency
        submodule_latency_from_container_logic = timing_params.GET_SUBMODULE_LATENCY(submodule_inst_name, parser_state, TimingParamsLookupTable)
        
        # Use submodule logic to write vhdl
        # REGULAR ENTITY CONNECITON
        submodule_level_text += " " + " " + " -- " + C_TO_LOGIC.LEAF_NAME(submodule_inst, True) + " LATENCY=" + str(submodule_latency_from_container_logic) +  "\n"
        entity_connection_text = VHDL.GET_ENTITY_CONNECTION_TEXT(submodule_logic,submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic, rv.stage_ordered_submodule_list, stage_num)     
        submodule_level_text += entity_connection_text + "\n"

        # Add output wires of this submodule to wires driven so far after latency
        for output_port in submodule_logic.outputs:
          # Construct the name of this wire in the original logic
          submodule_output_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + output_port
          if bad_inf_loop:
            print("following output",submodule_output_wire)
          # Add this output port wire on the submodule after the latency of the submodule
          if bad_inf_loop:
            print("submodule_output_wire",submodule_output_wire)
          wire_to_remaining_clks_before_driven[submodule_output_wire] = submodule_latency_from_container_logic
          
          # Sanity?
          submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
          submodule_latency = submodule_timing_params.GET_TOTAL_LATENCY(parser_state,TimingParamsLookupTable)
          if submodule_latency != submodule_latency_from_container_logic:
            print("submodule_latency != submodule_latency_from_container_logic")
            sys.exit(-1)
            
          # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
          # Set delay_offset_when_driven for this output wire
          if is_zero_clk_has_delay:
            # Assume zero latency fix me
            if submodule_latency != 0:
              print("non zero submodule latency? fix me")
              sys.exit(-1)
            # Set delay offset for this wire
            submodule_delay = parser_state.LogicInstLookupTable[submodule_inst_name].delay
            abs_delay_offset = rv.zero_clk_submodule_end_offset[submodule_inst]
            delay_offset_when_driven[submodule_output_wire] = abs_delay_offset
            # ONly +1 if delay > 0
            if submodule_delay > 0:
              delay_offset_when_driven[submodule_output_wire] += 1 # "+1" Was seeing stacked parallel submodules where they dont exist
          # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
      ####################################################################################################################
    
  
      # END
      # SUBMODULE
      # LEVEL
      # ITERATION
      
      # This ends one submodule level iteration
      # Record text from this iteration
      submodule_level_prepend_text = "  " + " " + "-- SUBMODULE LEVEL " + str(submodule_level) + "\n"
      if submodule_level_text != "":
        # Init dict entries
        if stage_num not in rv.per_stage_texts:
          # Init stage to have empty list of submodule stage texts
          rv.per_stage_texts[stage_num] = []
        # Init submodule level to be empty text then have prepend
        if submodule_level > len(rv.per_stage_texts[stage_num])-1:
          rv.per_stage_texts[stage_num].append("")
          rv.per_stage_texts[stage_num][submodule_level] = submodule_level_prepend_text
        # Append text to dict entry
        rv.per_stage_texts[stage_num][submodule_level] += submodule_level_text
        if print_debug:
          print(submodule_level_text)
          
      # Sometimes submodule levels iterations dont have submodules as we iterate driving wires / for multiple clks
      # Only update counters if was real submodule level with submodules
      if submodule_level_iteration_has_submodules:        
        # Update counters
        submodule_level = submodule_level + 1
      #else:
      # print "NOT submodule_level_iteration_has_submodules, and that is weird?"
      # sys.exit(-1)
      
      # Wires starting next level IS wires whose latency has elapsed just now
      wires_starting_level=[]
      # Also are added to wires driven so far
      # (done per submodule level iteration since ALSO DOES 0 CLK SUBMODULE OUTPUTS)
      for wire in wire_to_remaining_clks_before_driven:
        if wire_to_remaining_clks_before_driven[wire]==0:
          if wire not in wires_driven_by_so_far:
            if bad_inf_loop:
              print("wire remaining clks done, is driven now",wire)
            
            driving_wire = None
            if wire in logic.wire_driven_by:
              driving_wire = logic.wire_driven_by[wire]
            RECORD_DRIVEN_BY(driving_wire, wire)
            wires_starting_level.append(wire)

      # WHILE CHECK for when to stop try for submodule levels in this stage
      if not( len(wires_starting_level)>0 ):
        # Break out of this loop trying to do submodule level iterations for this stage
        break;
      else:
        # Record these last wires starting level and loop again
        # This is dumb and probably doesnt work?
        if last_wires_starting_level == wires_starting_level:
          print("Same wires starting level?")
          print(wires_starting_level)
          #if print_debug:
          sys.exit(-1)
          #print_debug = True
          #sys.exit(-1)
        else:       
          last_wires_starting_level = wires_starting_level[:]
      
    # PER CLOCK
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    if is_zero_clk_has_delay:
      # Get max delay
      if len(list(rv.zero_clk_per_delay_submodules_map.keys())) == 0:
        rv.zero_clk_max_delay = 0
      else:
        rv.zero_clk_max_delay = max(rv.zero_clk_per_delay_submodules_map.keys()) +1 # +1 since 0 indexed
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # PER CLOCK decrement latencies
    stage_num = stage_num +1
    for wire in wire_to_remaining_clks_before_driven:
      #if wire_to_remaining_clks_before_driven[wire] >= 0:
      wire_to_remaining_clks_before_driven[wire]=wire_to_remaining_clks_before_driven[wire]-1
      
    # Output might be driven
    
    # For 0 clk global funcs, and no global funcs 
    # the output is always driven in the last stage / stage zero
    # But for volatile globals the return value might be driven before
    # all of the other logic driving the volatiles is done
    num_volatiles = 0
    for state_reg in logic.state_regs:
      if logic.state_regs[state_reg].is_volatile:
        num_volatiles += 1
    if num_volatiles == 0:
      if est_total_latency is not None:
        # Sanity check that output is driven in last stage
        my_total_latency = stage_num - 1
        if PIPELINE_DONE() and (my_total_latency != est_total_latency):
          print("Seems like pipeline is done before or after last stage?") 
          print("inst_name",inst_name, timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state))
          print("est_total_latency",est_total_latency, "calculated total_latency",my_total_latency)
          print("timing_params._slices",timing_params._slices)
          #print "timing_params.submodule_to_start_stage",timing_params.submodule_to_start_stage 
          print(0/0)
          sys.exit(-1)
          print_debug = True
  
  #*************************** End of while loops *****************************************************#
  
  
  
  # Save number of stages using stage number counter
  rv.num_stages = stage_num
  my_total_latency = rv.num_stages - 1
    
  # Sanity check against estimate
  if est_total_latency is not None:
    if est_total_latency != my_total_latency:
      print("BUG IN PIPELINE MAP!")
      print("inst_name",inst_name, timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state))
      print("est_total_latency",est_total_latency, "calculated total_latency",my_total_latency)
      print("timing_params._slices5",timing_params._slices)
      #print "timing_params.submodule_to_start_stage",timing_params.submodule_to_start_stage
      sys.exit(-1)
    
  return rv
  
# Returns updated TimingParamsLookupTable
# Index of bad slice if sliced through globals, scoo # Passing Afternoon - Iron & Wine
# THIS MUST BE CALLED IN LOOP OF INCREASING SLICES FROM LEFT=>RIGHT
def SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(inst_name, logic, new_slice_pos, parser_state, TimingParamsLookupTable, skip_boundary_slice, write_files=True, rounding_so_fuck_it=False):
  print_debug = False
  
  # Get timing params for this logic
  timing_params = TimingParamsLookupTable[inst_name]
  if timing_params.params_are_fixed:
    print("Trying to add slice to fixed params?", inst_name)
    sys.exit(-1)
  # Add slice
  timing_params.ADD_SLICE(new_slice_pos)
  slice_index = timing_params._slices.index(new_slice_pos)
  slice_ends_stage = slice_index
  slice_starts_stage = slice_ends_stage + 1
  prev_slice_pos = None
  if len(timing_params._slices) > 1:
    prev_slice_pos = timing_params._slices[slice_index-1]
    
  '''
  # Sanity check if not adding last slice then must be skipping boundary right?
  if slice_index != len(timing_params._slices)-1 and not skip_boundary_slice:
    print "Wtf added old/to left slice",new_slice_pos,"while not skipping boundary?",timing_params._slices
    print 0/0
    sys.exit(-1)
  '''
  
  # Write into timing params dict, almost certainly unecessary
  TimingParamsLookupTable[inst_name] = timing_params
  
  # Check if can slice
  if not logic.CAN_BE_SLICED():
    # Can't slice globals, return index of bad slice
    if print_debug:
      print("Can't slice")
    return slice_index
  
  if print_debug:
    print("SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES", inst_name, new_slice_pos, "write_files",write_files)
  
  # Raw HDL doesnt need further slicing, bottom of hierarchy
  if len(logic.submodule_instances) > 0:
    #print "logic.submodule_instances",logic.submodule_instances
    # Get the zero clock pipeline map for this logic
    zero_clk_pipeline_map = GET_ZERO_CLK_PIPELINE_MAP(inst_name, logic, parser_state)
    total_delay = zero_clk_pipeline_map.zero_clk_max_delay
    if total_delay is None:
      print("No delay for module?",logic.func_name)
      sys.exit(-1)
    epsilon = SLICE_EPSILON(total_delay)
    
    # Sanity?
    if logic.func_name != zero_clk_pipeline_map.logic.func_name:
      print("Zero clk inst name:",zero_clk_pipeline_map.logic.func_name)
      print("Wtf using pipeline map from other func?")
      sys.exit(-1)
    
    # Get the offset as float
    delay_offset_float = new_slice_pos * total_delay
    delay_offset = math.floor(delay_offset_float)
    # Clamp to max?
    max_delay = max(zero_clk_pipeline_map.zero_clk_per_delay_submodules_map.keys())
    if delay_offset > max_delay:
      delay_offset = max_delay
    delay_offset_decimal = delay_offset_float - delay_offset
    
    # Slice can be through modules or on the boundary between modules
    # The boundary between modules is important for moving slices right up against global logic?
    
    # Get submodules at this offset
    submodule_insts = zero_clk_pipeline_map.zero_clk_per_delay_submodules_map[delay_offset]
    # Get submodules in previous and next delay units
    prev_submodule_insts = []
    if delay_offset - 1 in zero_clk_pipeline_map.zero_clk_per_delay_submodules_map:
      prev_submodule_insts = zero_clk_pipeline_map.zero_clk_per_delay_submodules_map[delay_offset - 1]
    next_submodule_insts = []
    if delay_offset + 1 in zero_clk_pipeline_map.zero_clk_per_delay_submodules_map:
      next_submodule_insts = zero_clk_pipeline_map.zero_clk_per_delay_submodules_map[delay_offset + 1]
    
    # Slice each submodule at offset
    # Record if submodules need to be artifically delayed to start in a later stage
    for submodule_inst in submodule_insts:      
      # Slice through submodule
      submodule_inst_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
      submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
      # Only continue slicing down if not fixed slices already (trying to slice deeper and make fixed slices)
      if not submodule_timing_params.params_are_fixed:
        # Slice through submodule
        # Only slice when >= 1 delay unit?
        submodule_func_name = logic.submodule_instances[submodule_inst]
        submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
        containing_logic = logic
        
        start_offset = zero_clk_pipeline_map.zero_clk_submodule_start_offset[submodule_inst]
        local_offset = delay_offset - start_offset
        local_offset_w_decimal = local_offset + delay_offset_decimal
        
        #print "start_offset",start_offset
        #print "local_offset",local_offset
        #print "local_offset_w_decimal",local_offset_w_decimal
        
        # Convert to percent to add slice
        submodule_total_delay = submodule_logic.delay
        slice_pos = float(local_offset_w_decimal) / float(submodule_total_delay)      
        if print_debug:
          print(" Slicing:", submodule_inst)
          print("   @", slice_pos)
            
        # Slice into that submodule
        skip_boundary_slice = False
        TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(submodule_inst_name, submodule_logic, slice_pos, parser_state, TimingParamsLookupTable, skip_boundary_slice, write_files)  
        
        # Might be bad slice
        if type(TimingParamsLookupTable) is int:
          # Slice into submodule was bad
          if print_debug:
            print("Adding slice",slice_pos)
            print("To", submodule_inst)
            print("Submodule Slice index", TimingParamsLookupTable)
            print("Container slice index", slice_index)
            print("Was bad")
          # Return the slice in the container that was bad
          return slice_index
  
  if write_files: 
    # Final write package
    # Write VHDL file for submodule
    # Re write submodule package with updated timing params
    timing_params = TimingParamsLookupTable[inst_name]
    syn_out_dir = GET_OUTPUT_DIRECTORY(logic)
    if not os.path.exists(syn_out_dir):
      os.makedirs(syn_out_dir)    
    VHDL.WRITE_LOGIC_ENTITY(inst_name, logic, syn_out_dir, parser_state, TimingParamsLookupTable)
  
  return TimingParamsLookupTable
  
# Does not change fixed params
def RECURSIVE_SET_NON_FIXED_TO_ZERO_CLK_TIMING_PARAMS(inst_name, parser_state, TimingParamsLookupTable, override_fixed=False):
  # Get timing params for this logic
  timing_params = TimingParamsLookupTable[inst_name]
  if not timing_params.params_are_fixed or override_fixed:
    # Set to be zero clk
    timing_params.SET_SLICES([])
    # Maybe unfix
    if override_fixed:
      # Reset value
      timing_params.params_are_fixed = not timing_params.logic.CAN_BE_SLICED()
    # Repeat down through submodules since not fixed
    logic = parser_state.LogicInstLookupTable[inst_name]
    for local_sub_inst in logic.submodule_instances:
      sub_inst = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + local_sub_inst
      TimingParamsLookupTable = RECURSIVE_SET_NON_FIXED_TO_ZERO_CLK_TIMING_PARAMS(sub_inst, parser_state, TimingParamsLookupTable, override_fixed)
    
  TimingParamsLookupTable[inst_name] = timing_params
      
  return TimingParamsLookupTable
  
# Returns index of bad slices or working TimingParamsLookupTable
def ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(inst_name, logic, current_slices, parser_state, TimingParamsLookupTable, write_files=True, rounding_so_fuck_it=False):
  # Do slice to main logic for each slice
  for current_slice_i in current_slices:
    #print "  current_slice_i:",current_slice_i
    skip_boundary_slice = False
    write_files_in_loop = False
    TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(inst_name, logic, current_slice_i, parser_state, TimingParamsLookupTable, skip_boundary_slice, write_files_in_loop,rounding_so_fuck_it)
    # Might be bad slice
    if type(TimingParamsLookupTable) is int:
      return TimingParamsLookupTable
  
  if write_files:
    # Do one final dumb loop over all timing params that arent zero clocks?
    # because write_files_in_loop = False above
    for inst_name_to_wr in TimingParamsLookupTable:
      wr_logic = parser_state.LogicInstLookupTable[inst_name_to_wr]
      wr_timing_params = TimingParamsLookupTable[inst_name_to_wr]
      if wr_timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable) > 0:
        wr_syn_out_dir = GET_OUTPUT_DIRECTORY(wr_logic)
        if not os.path.exists(wr_syn_out_dir):
          os.makedirs(wr_syn_out_dir)    
        VHDL.WRITE_LOGIC_ENTITY(inst_name_to_wr, wr_logic, wr_syn_out_dir, parser_state, TimingParamsLookupTable)
  
  return TimingParamsLookupTable
        
def GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(parser_state, inst_name=None):
  ext = None
  if SYN_TOOL is VIVADO:
    ext = ".xdc"
  elif SYN_TOOL is QUARTUS:
    ext = ".sdc"
  elif SYN_TOOL is DIAMOND and DIAMOND.DIAMOND_TOOL=="lse":
    ext = ".ldc"
  elif (SYN_TOOL is DIAMOND and DIAMOND.DIAMOND_TOOL=="synplify"):
    ext = ".sdc"
  elif SYN_TOOL is OPEN_TOOLS:
    ext = ".py"
  elif SYN_TOOL is EFINITY:
    ext = ".sdc"
  else:
    # Sufjan Stevens - Video Game
    raise Exception(f"Add constraints file ext for syn tool {SYN_TOOL.__name__}")
    #sys.exit(-1)
    
  clock_name_to_mhz = dict()
  if inst_name:
    clock_name_to_mhz["clk"] = INF_MHZ
    out_filename = "clock" + ext
    Logic = parser_state.LogicInstLookupTable[inst_name]
    output_dir = GET_OUTPUT_DIRECTORY(Logic)
    out_filepath = output_dir+"/"+out_filename
  else:
    out_filename = "clocks" + ext
    out_filepath = SYN_OUTPUT_DIRECTORY+"/"+out_filename
    for main_func in parser_state.main_mhz:
      clock_mhz = GET_TARGET_MHZ(main_func, parser_state)
      clk_ext_str = VHDL.CLK_EXT_STR(main_func, parser_state)
      clk_name = "clk_" + clk_ext_str
      clock_name_to_mhz[clk_name] = clock_mhz
    
  return clock_name_to_mhz,out_filepath
      
# return path 
def WRITE_CLK_CONSTRAINTS_FILE(parser_state, inst_name=None):
  
  # Use specified mhz is multimain top
  clock_name_to_mhz,out_filepath = GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH(parser_state, inst_name)  
  f=open(out_filepath,"w")
  
  if SYN_TOOL is OPEN_TOOLS:
    # All clock assumed async in nextpnr constraints
    for clock_name in clock_name_to_mhz:
      clock_mhz = clock_name_to_mhz[clock_name]
      f.write('ctx.addClock("' + clock_name + '", ' + str(clock_mhz) + ')\n');
  else:
    # Standard sdc like constraints
    for clock_name in clock_name_to_mhz:
      clock_mhz = clock_name_to_mhz[clock_name]
      if clock_mhz is None:
        raise Exception(f"No frequency associated with clock {clock_name}! (Missing MAIN_MHZ?)")
      ns = (1000.0 / clock_mhz)
      f.write("create_clock -add -name " + clock_name + " -period " + str(ns) + " -waveform {0 " + str(ns/2.0) + "} [get_ports " + clock_name + "]\n");
      
    # All clock assumed async? Doesnt matter for internal syn
    # Rely on generated/board provided constraints for real hardware
    if len(clock_name_to_mhz) > 1:
      if SYN_TOOL is VIVADO:
        f.write("set_clock_groups -name async_clks_group -asynchronous -group [get_clocks *] -group [get_clocks *]\n")
      elif SYN_TOOL is QUARTUS:
        # Ignored set_clock_groups at clocks.sdc(3): The clock clk_100p0 was found in more than one -group argument.
        # Uh do the hard way?
        clk_sets = set()
        for clock_name1 in clock_name_to_mhz:
          for clock_name2 in clock_name_to_mhz:
            if clock_name1 != clock_name2:
              clk_set = frozenset([clock_name1,clock_name2])
              if clk_set not in clk_sets:
                f.write("set_clock_groups -asynchronous -group [get_clocks " + clock_name1 + "] -group [get_clocks " + clock_name2 + "]")
                clk_sets.add(clk_set)
      elif SYN_TOOL is DIAMOND:
        #f.write("set_clock_groups -name async_clks_group -asynchronous -group [get_clocks *] -group [get_clocks *]")
        # ^ is wrong, makes 200mhx system clock?
        pass # rely on clock cross path detection error in timing report
      else:
        print("What syn too for async clocks?")
        sys.exit(-1)
  
  
  f.close()
  return out_filepath
  
# Target mhz is internal name for whatever mhz we are using in this run
# Real pnr MAIN_MHZ or syn only MAIN_SYN_MHZ
def GET_TARGET_MHZ(main_func, parser_state):
  # Does tool do full PNR or just syn?
  if SYN_TOOL is VIVADO:
    if VIVADO.DO_PNR is not None:
      return parser_state.main_mhz[main_func]
    else:
      return parser_state.main_syn_mhz[main_func]
  # Uses PNR MAIN_MHZ
  elif (SYN_TOOL is QUARTUS) or (SYN_TOOL is OPEN_TOOLS) or (SYN_TOOL is EFINITY):
    return parser_state.main_mhz[main_func]
  # Uses synthesis estimates
  elif (SYN_TOOL is DIAMOND):
    return parser_state.main_syn_mhz[main_func]
  else:
    raise Exception("Need syn tool!")
    
def WRITE_FINAL_FILES(multimain_timing_params, parser_state):
  is_final_top = True
  VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top)
  
  # Black boxes are different in final files
  for func_name in parser_state.func_marked_blackbox:
    if func_name in parser_state.FuncToInstances:
      blackbox_func_logic = parser_state.FuncLogicLookupTable[func_name]
      for inst_name in parser_state.FuncToInstances[func_name]:
        bb_out_dir = GET_OUTPUT_DIRECTORY(blackbox_func_logic)
        VHDL.WRITE_LOGIC_ENTITY(inst_name, blackbox_func_logic, bb_out_dir, parser_state, multimain_timing_params.TimingParamsLookupTable, is_final_top)
  
  # read_vhdl.tcl only for Vivado for now
  if SYN_TOOL is VIVADO:
    # TODO better GUI / tcl scripts support for other tools
    # Write read_vhdl.tcl
    tcl = VIVADO.GET_SYN_IMP_AND_REPORT_TIMING_TCL(multimain_timing_params, parser_state)
    rv_lines = []
    for line in tcl.split('\n'):
      # Hacky AF Built To Spill - Kicked It In The Sun
      if line.startswith("read_vhdl") or line.startswith("add_files") or line.startswith("set_property"):
        rv_lines.append(line)
    
    rv = ""
    for line in rv_lines:
      rv += line + "\n"
    
    # One more read_vhdl line for the final entity  with constant name
    top_file_path = SYN_OUTPUT_DIRECTORY + "/top/top.vhd"
    rv += "read_vhdl -library work {" + top_file_path + "}\n"
      
    # Write file
    out_filename = "read_vhdl.tcl"
    out_filepath = SYN_OUTPUT_DIRECTORY+"/"+out_filename
    out_text = rv
  else:
    # Do generic dump of vhdl files
    # Which vhdl files?
    vhdl_files_texts,top_entity_name = GET_VHDL_FILES_TCL_TEXT_AND_TOP(multimain_timing_params, parser_state)
    # One more rvhdl line for the final entity  with constant name
    top_file_path = SYN_OUTPUT_DIRECTORY + "/top/top.vhd"
    vhdl_files_texts += " " + top_file_path
    out_filename = "vhdl_files.txt"
    out_filepath = SYN_OUTPUT_DIRECTORY+"/"+out_filename
    out_text = vhdl_files_texts
    
  print("Output VHDL files:", out_filepath)
  f=open(out_filepath,"w")
  f.write(out_text)
  f.close()
    

def DO_SYN_FROM_TIMING_PARAMS(multimain_timing_params, parser_state):
  # Then run syn
  timing_report = SYN_TOOL.SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params)
  if len(timing_report.path_reports) == 0:
    print(timing_report.orig_text)
    print("Using a bad syn log file?")
    sys.exit(-1)
    
  return timing_report
  
# Sweep state for a single pipeline inst of logic (a main inst typically?)
class InstSweepState:
  def __init__(self):
    self.met_timing = False
    self.timing_report = None # Current timing report with multiple paths
    self.mhz_to_latency = dict() # dict[mhz] = latency
    self.latency_to_mhz = dict() # dict[latency] = mhz

    # Coarse grain sweep 
    self.coarse_latency = None
    self.slice_step = 0.0 # Coarse grain
    self.initial_guess_latency = None
    self.last_non_passing_latency = None
    self.last_latency_increase = None
    self.worse_or_same_tries_count = 0
    
    # These only make sense after re writing fine sweep?
    # State about which stage being adjusted?
    #self.seen_slices=dict() # dict[main func] = list of above lists
    #self.latency_to_best_slices = dict() 
    #self.latency_to_best_delay = dict()
    #self.stage_range = [0] # The current worst path stage estimate from the timing report
    #self.working_stage_range = [0] # Temporary stage range to guide adjustments to slices
    #self.stages_adjusted_this_latency = {0 : 0} # stage -> num times adjusted
    
    # Middle out sweep uses synthesis runs of smaller modules
    # How far down the hierarchy?
    self.hier_sweep_mult = None # Try coarse sweep from top level 0.0 and move down
    # Increment by find the next level down of not yet sliced modules
    self.smallest_not_sliced_hier_mult = INF_HIER_MULT
    # Sweep use of the coarse sweep at middle levels to produce modules that meet more than the timing requirement
    self.coarse_sweep_mult = 1.0 # Saw as bad as 15 percent loss just from adding io regs slices #1.05 min? # 1.0 doesnt make sense need margin since logic will be with logic/routing delay etc 
    # Otherwise from top level coarsely - like original coarse sweep
    # keep trying harder with best guess slices
    self.best_guess_sweep_mult = 1.0
    

# SweepState for the entire multimain top
class SweepState:
  def __init__(self):
    # Multimain sweep state
    self.met_timing = False
    self.multimain_timing_params = None # Current timing params
    self.timing_report = None # Current timing report with multiple paths
    self.fine_grain_sweep = False
    self.curr_main_inst = None

    
    # Per instance sweep state
    self.inst_sweep_state = dict() # dict[main_inst_name] = InstSweepState
    
    
def GET_MOST_RECENT_OR_DEFAULT_SWEEP_STATE(parser_state, multimain_timing_params):
  # Try to use cache
  cached_sweep_state = GET_MOST_RECENT_CACHED_SWEEP_STATE()
  sweep_state = None
  if not(cached_sweep_state is None):
    print("Using cached most recent sweep state...", flush=True)
    sweep_state = cached_sweep_state
  else:
    print("Starting with blank sweep state...", flush=True)
    sweep_state = SweepState()
    # Set defaults
    sweep_state.multimain_timing_params = multimain_timing_params
    #print("...determining slicing tolerance information for each main function...", flush=True)
    for main_inst_name in parser_state.main_mhz:
      func_logic = parser_state.LogicInstLookupTable[main_inst_name]
      sweep_state.inst_sweep_state[main_inst_name] = InstSweepState()
      # Any instance will do 
      inst_name = main_inst_name
      # Only need slicing if has delay?
      delay = parser_state.LogicInstLookupTable[main_inst_name].delay
      # Init hier sweep mult to be top level
      func_path_delay_ns = float(func_logic.delay) / DELAY_UNIT_MULT
      target_mhz = GET_TARGET_MHZ(main_inst_name, parser_state)
      if target_mhz is not None:
        target_path_delay_ns = 1000.0 / target_mhz
        sweep_state.inst_sweep_state[main_inst_name].hier_sweep_mult = 0.0
        if delay > 0.0 and func_logic.CAN_BE_SLICED():
          sweep_state.inst_sweep_state[main_inst_name].slice_ep = SLICE_EPSILON(delay)
          # Dont bother making from the top level if need more than 50 slices? # MAGIC?
          hier_sweep_mult = max(HIER_SWEEP_MULT_MIN, (target_path_delay_ns/func_path_delay_ns) - HIER_SWEEP_MULT_INC) # HIER_SWEEP_MULT_INC since fp rounding stuff?
          sweep_state.inst_sweep_state[main_inst_name].hier_sweep_mult = hier_sweep_mult
          #print(func_logic.func_name,"hierarchy sweep mult:",sweep_state.inst_sweep_state[main_inst_name].hier_sweep_mult)
        
  return sweep_state
  
def GET_MOST_RECENT_CACHED_SWEEP_STATE():
  output_directory = SYN_OUTPUT_DIRECTORY + "/" + "top"
  # Search for most recently modified
  sweep_files = [file for file in glob.glob(os.path.join(output_directory, '*.sweep'))]
  if len(sweep_files) > 0 :
    #print "sweep_files",sweep_files
    sweep_files.sort(key=os.path.getmtime)
    print(sweep_files[-1]) # most recent file
    most_recent_sweep_file = sweep_files[-1]
    
    with open(most_recent_sweep_file, 'rb') as input:
      sweep_state = pickle.load(input)
      return sweep_state
  else:
    return None
  
  
    
def WRITE_SWEEP_STATE_CACHE_FILE(sweep_state, parser_state):
  #TimingParamsLookupTable = state.TimingParamsLookupTable
  output_directory = SYN_OUTPUT_DIRECTORY + "/" + "top"
  # ONly write one sweep per clk for space sake?
  hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
  filename = "top" + hash_ext + ".sweep"
  filepath = output_directory + "/" + filename
  
  # Write dir first if needed
  if not os.path.exists(output_directory):
    os.makedirs(output_directory)
    
  # Write file
  with open(filepath, 'wb') as output:
    pickle.dump(state, output, pickle.HIGHEST_PROTOCOL)

def SHIFT_SLICE(slices, index, direction, amount,min_dist):
  if amount == 0:
    return slices
  
  curr_slice = slices[index]
  
  # New slices dont incldue the current one until adjsuted
  new_slices = slices[:]
  new_slices.remove(curr_slice)
  new_slice = None
  if direction == 'r':
    new_slice = curr_slice + amount
            
  elif direction == 'l':
    new_slice = curr_slice - amount
    
  else:
    print("WHATATSTDTSTTTS")
    sys.exit(-1)
    
    
  if new_slice >= 1.0:
    new_slice = 1.0 - min_dist
  if new_slice < 0.0:
    new_slice = min_dist  
    
    
  # if new slice is within min_dist of another slice back off change
  for slice_i in new_slices:
    if SLICE_POS_EQ(slice_i, new_slice, min_dist):      
      if direction == 'r':
        new_slice = slice_i - min_dist # slightly to left of matching slice 
                
      elif direction == 'l':
        new_slice = slice_i + min_dist # slightly to right of matching slice
        
      else:
        print("WHATATSTD$$$$TSTTTS")
        sys.exit(-1)
      break
  
  
  new_slices.append(new_slice)
  new_slices = sorted(new_slices)
  
  return new_slices
    

  
def GET_BEST_GUESS_IDEAL_SLICES(latency):
  # Build ideal slices at this latency
  chunks = latency+1
  slice_per_chunk = 1.0/chunks
  slice_total = 0
  ideal_slices = []
  for i in range(0,latency):
    slice_total += slice_per_chunk
    ideal_slices.append(slice_total)
    
  return ideal_slices
    

def REDUCE_SLICE_STEP(slice_step, total_latency, epsilon):
  n=0
  while True:
    maybe_new_slice_step = 1.0/((SLICE_STEPS_BETWEEN_REGS+1+n)*(total_latency+1))
    if maybe_new_slice_step < epsilon/2.0: # Allow half as small>>>???
      maybe_new_slice_step = epsilon/2.0
      return maybe_new_slice_step
      
    if maybe_new_slice_step < slice_step:
      return maybe_new_slice_step
    
    n = n + 1     

def SLICE_DISTANCE_MIN(delay):
  return 1.0 / float(delay)



def SLICE_EPSILON(delay):
  num_div = SLICE_EPSILON_MULTIPLIER * delay
  
  # Fp compare epsilon is this divider
  EPSILON = 1.0 / float(num_div)
  return EPSILON
  
def SLICE_POS_EQ(a,b,epsilon):
  return abs(a-b) < epsilon

def SLICES_EQ(slices_a, slices_b, epsilon):
  # Eq if all values are eq
  if len(slices_a) != len(slices_b):
    return False
  all_eq = True
  for i in range(0,len(slices_a)):
    a = slices_a[i]
    b = slices_b[i]
    if not SLICE_POS_EQ(a,b,epsilon):
      all_eq = False
      break
  
  return all_eq

def GET_MAIN_INSTS_FROM_PATH_REPORT(path_report, parser_state, multimain_timing_params):
  main_insts = set()
  all_main_insts = list(reversed(sorted(list(parser_state.main_mhz.keys()), key=len)))
  #print("all_main_insts",all_main_insts)
  # Include start and end regs in search 
  all_netlist_resources = set(path_report.netlist_resources)
  all_netlist_resources.add(path_report.start_reg_name)
  all_netlist_resources.add(path_report.end_reg_name)
  for netlist_resource in all_netlist_resources:
    #toks = netlist_resource.split("/")
    #if toks[0] in parser_state.main_mhz:
    #  main_inst_funcs.add(toks[0])
    # If in the top level - no '/'? then look for main funcs like a dummy
    #if "/" not in netlist_resource:
    # Main funcs sorted by len for best match
    match_main = None
    #print("netlist_resource",netlist_resource)
    for main_inst in all_main_insts:
      main_logic = parser_state.LogicInstLookupTable[main_inst]
      main_vhdl_entity_name = VHDL.GET_ENTITY_NAME(main_inst, main_logic, multimain_timing_params.TimingParamsLookupTable, parser_state)
      if netlist_resource.startswith(main_vhdl_entity_name):
        match_main = main_inst
        break
      # OPEN_TOOLs reports in lower case
      if netlist_resource.lower().startswith(main_vhdl_entity_name.lower()):
        match_main = main_inst
        break
        
    if match_main:
      main_insts.add(match_main)
  
  # If nothing was found try hacky clock cross check?
  if len(main_insts)==0:
    start_inst = path_report.start_reg_name.split("/")[0]
    end_inst = path_report.end_reg_name.split("/")[0]
    #print(start_inst,end_inst)
    if (start_inst in parser_state.clk_cross_var_info) and (end_inst in parser_state.clk_cross_var_info):
      start_info = parser_state.clk_cross_var_info[start_inst]
      end_info = parser_state.clk_cross_var_info[end_inst]
      # Start read and end write must be same main
      start_write_mains, start_read_mains = start_info.write_read_main_funcs
      end_write_mains, end_read_mains = end_info.write_read_main_funcs
      #print(start_read_main,end_write_main)
      in_both_mains = start_read_mains & end_write_main
      if len(in_both_mains) > 0:
        main_insts |= in_both_mains
        
  return main_insts

# Todo just coarse for now until someone other than me care to squeeze performance?
# Course then fine - knowhaimsayin
def DO_THROUGHPUT_SWEEP(parser_state, coarse_only=False, starting_guess_latency=None, do_incremental_guesses=True):
  for main_func in parser_state.main_mhz:
    if main_func not in parser_state.main_mhz:
      print("Main Function:",main_func,"does not have a set target frequency. Cannot do pipelining throughput sweep!", flush=True)
      print("Define frequency with 'MAIN_MHZ' or clock group with 'MAIN_GROUP' pragmas...")
      sys.exit(-1)
    else:
      mhz = GET_TARGET_MHZ(main_func, parser_state)
      print("Function:",main_func,"Target MHz:", mhz, flush=True)
  
  # Populate timing lookup table as all 0 clk
  print("Setting all instances to comb. logic to start...", flush=True)
  ZeroClockTimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state)
  multimain_timing_params = MultiMainTimingParams()
  multimain_timing_params.TimingParamsLookupTable = ZeroClockTimingParamsLookupTable
  
  # Write clock cross entities
  VHDL.WRITE_CLK_CROSS_ENTITIES(parser_state, multimain_timing_params)
    
  # Write multi-main top
  VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params)
  
  # Default sweep state is zero clocks
  sweep_state = GET_MOST_RECENT_OR_DEFAULT_SWEEP_STATE(parser_state, multimain_timing_params)
  
  # if coarse only
  if coarse_only:
    print("Doing coarse sweep only...", flush=True)
    if len(parser_state.main_mhz) > 1:
      raise Exception("Cannot do use a single coarse sweep with multiple main functions.")
      sys.exit(-1)
    main_func = list(parser_state.main_mhz.keys())[0]
    if GET_TARGET_MHZ(main_func, parser_state) is None:
      print("Main Function:",main_func,"does not have a set target frequency.")
      print("Starting a coarse sweep incrementally from zero latency comb. logic.", flush=True)
      starting_guess_latency = 0
      do_incremental_guesses = False
      parser_state.main_mhz[main_func] = INF_MHZ
    inst_sweep_state = InstSweepState()
    inst_sweep_state, working_slices, multimain_timing_params.TimingParamsLookupTable = DO_COARSE_THROUGHPUT_SWEEP(
      list(parser_state.main_mhz.keys())[0], list(parser_state.main_mhz.values())[0],
      inst_sweep_state, parser_state,
      starting_guess_latency, do_incremental_guesses)
    return multimain_timing_params
  
  # Real middle out sweep which includes coarse sweep
  print("Starting middle out sweep...", flush=True)
  sweep_state = DO_MIDDLE_OUT_THROUGHPUT_SWEEP(parser_state, sweep_state)
  
  # Maybe skip fine grain
  #if not skip_fine_sweep:
  # # Then fine grain
  # return DO_FINE_THROUGHPUT_SWEEP(parser_state, sweep_state)
  #else:
  return sweep_state.multimain_timing_params
  
# Not because it is easy, but because we thought it would be easy

# Do I like Joe Walsh?


# Inside out timing params
# Kinda like "make all adds N cycles" as in original thinking
# But starts from first module where any slice approaches timing goal
# Middle out coarseness?
# Modules can be locked/fixed in place and not sliced from above less accurately
def DO_MIDDLE_OUT_THROUGHPUT_SWEEP(parser_state, sweep_state):
  debug = False
  
  # Cache the multiple coarse runs
  coarse_slices_cache = dict()
  printed_slices_cache = set() # hacky indicator of if printed slicing of func yet
  def cache_key_func(logic, target_mhz):
    key=(logic.func_name,target_mhz)
    return key
    
  def hier_sweep_mult_func(target_path_delay_ns, func_path_delay_ns):
    return (target_path_delay_ns/func_path_delay_ns) + HIER_SWEEP_MULT_INC
  
  # Outer loop for this sweep
  sweep_state.met_timing = False
  while not sweep_state.met_timing:
    # Repeatedly walk up the hierarchy trying to slice
    # can fail because cant meet timing on some submodule at this timing goal
    got_timing_params_from_walking_tree = False
    keep_try_for_timing_params = True
    while keep_try_for_timing_params:
      got_timing_params_from_walking_tree = True
      keep_try_for_timing_params = False
      printed_slices_cache = set() # Print each time trying to walk tree for slicing
      print("Starting from zero clk timing params...", flush=True)
      # Reset to empty start for this tree walk
      sweep_state.multimain_timing_params.TimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state)
      for main_inst in parser_state.main_mhz:
        sweep_state.inst_sweep_state[main_inst].smallest_not_sliced_hier_mult = INF_HIER_MULT
      
      #@#NEED TO REDO search for modules at this hierarchy/delay level starting from top and moving down
      #@Starting from small can run into breaking optimizations that occur at higher levels
      print("Collecting modules to pipeline...", flush=True)
      lowest_level_insts_to_pipeline = set()
      for main_inst in parser_state.main_mhz:
        main_func_logic = parser_state.LogicInstLookupTable[main_inst]
        if main_func_logic.CAN_BE_SLICED():
          lowest_level_insts_to_pipeline.add(main_inst)
      # Do this not recursive down the multi main hier tree walk
      # Looking for lowest level submodule large enough to pipeline lowest_level_insts_to_pipeline is lowest_level_insts_to_pipeline       
      collecting_modules_to_pipeline = True
      while collecting_modules_to_pipeline:
        collecting_modules_to_pipeline = False
        for func_inst in list(lowest_level_insts_to_pipeline): # Copy for modification dur iter
          # Is this function large enough to pipeline?
          func_logic = parser_state.LogicInstLookupTable[func_inst]
          func_path_delay_ns = float(func_logic.delay) / DELAY_UNIT_MULT
          main_func = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(func_inst, parser_state)
          # Cached coarse sweep?
          target_mhz = GET_TARGET_MHZ(main_func, parser_state)
          target_path_delay_ns = 1000.0 / target_mhz
          coarse_target_mhz = target_mhz * sweep_state.inst_sweep_state[main_func].coarse_sweep_mult
          
          if (sweep_state.inst_sweep_state[main_func].hier_sweep_mult*func_path_delay_ns) <= target_path_delay_ns:
            # Does NOT need pipelining
            lowest_level_insts_to_pipeline.discard(func_inst)
            collecting_modules_to_pipeline = True
            if func_path_delay_ns > 0.0:
              hsm_i = hier_sweep_mult_func(target_path_delay_ns,func_path_delay_ns)
              if hsm_i < sweep_state.inst_sweep_state[main_func].smallest_not_sliced_hier_mult:
                sweep_state.inst_sweep_state[main_func].smallest_not_sliced_hier_mult = hsm_i
          elif func_logic.CAN_BE_SLICED():
            # Might need pipelining here if no submodules are also large enough pipeline
            # Invalidate timing param caches similar to how slicing down does
            func_inst_timing_params = sweep_state.multimain_timing_params.TimingParamsLookupTable[func_inst]
            func_inst_timing_params.INVALIDATE_CACHE()
            for local_sub_inst in func_logic.submodule_instances:
              sub_inst_name = func_inst + C_TO_LOGIC.SUBMODULE_MARKER + local_sub_inst 
              sub_logic = parser_state.LogicInstLookupTable[sub_inst_name]
              if sub_logic.delay is not None:
                sub_func_path_delay_ns = float(sub_logic.delay) / DELAY_UNIT_MULT
                if (sweep_state.inst_sweep_state[main_func].hier_sweep_mult*sub_func_path_delay_ns) > target_path_delay_ns:
                  # Submodule DOES need pipelining
                  if sub_logic.CAN_BE_SLICED():
                    lowest_level_insts_to_pipeline.add(sub_inst_name)
                  # This current inst is not lowest level sub needing pipelining
                  lowest_level_insts_to_pipeline.discard(func_inst)
                  collecting_modules_to_pipeline = True
                else:
                  # Submodule does not neet pipelining, record for hier mult step
                  if sub_func_path_delay_ns > 0.0:
                    hsm_i = hier_sweep_mult_func(target_path_delay_ns,sub_func_path_delay_ns)
                    if hsm_i < sweep_state.inst_sweep_state[main_func].smallest_not_sliced_hier_mult:
                      sweep_state.inst_sweep_state[main_func].smallest_not_sliced_hier_mult = hsm_i

      # Sanity
      for func_inst in lowest_level_insts_to_pipeline:
        containr_inst = C_TO_LOGIC.GET_CONTAINER_INST(func_inst)
        if containr_inst in lowest_level_insts_to_pipeline:
          print(containr_inst, "and submodule", func_inst,"both to be pipelined?")
          sys.exit(-1)
            
      # Got correct lowest_level_insts_to_pipeline
      # Do loop doing pipelining
      print("Pipelining modules...", flush=True)
      pipelining_worked = True
      for func_inst in lowest_level_insts_to_pipeline:
        func_logic = parser_state.LogicInstLookupTable[func_inst]
        func_path_delay_ns = float(func_logic.delay) / DELAY_UNIT_MULT
        main_func = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(func_inst, parser_state)
        # Cached coarse sweep?
        target_mhz = GET_TARGET_MHZ(main_func, parser_state)
        target_path_delay_ns = 1000.0 / target_mhz
        coarse_target_mhz = target_mhz * sweep_state.inst_sweep_state[main_func].coarse_sweep_mult
        cache_key = cache_key_func(func_logic, coarse_target_mhz)
        
        # How to pipeline?
        # Just IO regs? no slicing
        if (func_path_delay_ns*sweep_state.inst_sweep_state[main_func].coarse_sweep_mult) / target_path_delay_ns <= 1.0: #func_path_delay_ns < target_path_delay_ns:
          # Do single clock with io regs "coarse grain" 
          slices = [] #[0.0, 1.0]
          needs_in_regs = True
          needs_out_regs = True
          if cache_key not in printed_slices_cache:
            print("Slicing w/ IO regs:",func_logic.func_name,", mult =", sweep_state.inst_sweep_state[main_func].coarse_sweep_mult, slices, flush=True)
        
        # Cached result?
        elif cache_key in coarse_slices_cache:
          # Try cache of coarse grain before trying for real
          slices = coarse_slices_cache[cache_key]
          needs_in_regs = True
          needs_out_regs = True
          if cache_key not in printed_slices_cache:
            print("Cached coarse grain slicing:",func_logic.func_name,", target MHz =", coarse_target_mhz, slices, flush=True)
        
        # Manual coarse pipelining
        else:
          # Have state for this module?
          if func_inst not in sweep_state.inst_sweep_state:
            sweep_state.inst_sweep_state[func_inst] = InstSweepState()          
          func_inst_timing_params = sweep_state.multimain_timing_params.TimingParamsLookupTable[func_inst]
          if cache_key not in printed_slices_cache:
            print("Coarse grain sweep slicing",func_logic.func_name,", target MHz =",coarse_target_mhz, flush=True)
          # Need way to stop coarse sweep if sweeping at this level of hierarchy wont work
          # Number of tries should be more for smaller modules with more uneven slicing landscape
          # Most tries is like 6?
          # Which should used for modules where inital guess says ~1clk slicing
          coarse_sweep_initial_clks = int(math.ceil((func_path_delay_ns*sweep_state.inst_sweep_state[main_func].coarse_sweep_mult) / target_path_delay_ns)) - 1
          allowed_worse_results = int(MAX_N_WORSE_RESULTS/coarse_sweep_initial_clks)
          if allowed_worse_results == 0:
            allowed_worse_results = 1
          print("Allowed worse results in coarse sweep:",allowed_worse_results)
          # Why not do middle out again? All the way down? Because complicated?weird do later
          sweep_state.inst_sweep_state[func_inst], working_slices, inst_TimingParamsLookupTable = DO_COARSE_THROUGHPUT_SWEEP(func_inst, coarse_target_mhz,
            sweep_state.inst_sweep_state[func_inst], parser_state, starting_guess_latency=None, do_incremental_guesses=True, 
            max_allowed_latency_mult=MAX_ALLOWED_LATENCY_MULT, stop_at_n_worse_result=allowed_worse_results)
          if not sweep_state.inst_sweep_state[func_inst].met_timing:
            # Fail here, increment sweep mut and try_to_slice logic will slice lower module next time
            # Done in this loop, try again
            got_timing_params_from_walking_tree = False
            print(func_logic.func_name, "failed to meet timing, trying to pipeline smaller modules...")
            # If at smallest module then done trying to get params too
            if sweep_state.inst_sweep_state[main_func].smallest_not_sliced_hier_mult != INF_HIER_MULT:
              keep_try_for_timing_params = True
              # Increase mult to start at next delay unit down
              # WTF float stuff end up with slice getting repeatedly set just close enough not to slice next level down ?
              if sweep_state.inst_sweep_state[main_func].smallest_not_sliced_hier_mult == sweep_state.inst_sweep_state[main_func].hier_sweep_mult:
                sweep_state.inst_sweep_state[main_func].hier_sweep_mult += HIER_SWEEP_MULT_INC
                print(main_func,"nudging hierarchy sweep multiplier:",sweep_state.inst_sweep_state[main_func].hier_sweep_mult)
              else:
                # Normal case
                sweep_state.inst_sweep_state[main_func].hier_sweep_mult = sweep_state.inst_sweep_state[main_func].smallest_not_sliced_hier_mult
                print(main_func,"hierarchy sweep multiplier:",sweep_state.inst_sweep_state[main_func].hier_sweep_mult)
              sweep_state.inst_sweep_state[main_func].best_guess_sweep_mult = 1.0
              sweep_state.inst_sweep_state[main_inst].coarse_sweep_mult = 1.0
            else:
              # Unless no more modules left?
              print("No smaller submodules to pipeline...")
              keep_try_for_timing_params = False
            break
          # Assummed met timing if here
          # Add IO regs to timing
          slices = working_slices[:]
          needs_in_regs = True
          needs_out_regs = True
          if cache_key not in printed_slices_cache:
            print("Coarse gain confirmed slicing (w/ IO regs):",func_logic.func_name,", target MHz =", coarse_target_mhz, slices, flush=True)
          coarse_slices_cache[cache_key] = slices[:]
          
        # Apply pipelining slices
        # Do add slices with the current slices
        write_files = False
        sweep_state.multimain_timing_params.TimingParamsLookupTable = (
          ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
            func_inst, func_logic, slices, parser_state, 
            sweep_state.multimain_timing_params.TimingParamsLookupTable, write_files) )
        # Set this module to use io regs or not
        func_inst_timing_params = sweep_state.multimain_timing_params.TimingParamsLookupTable[func_inst]
        func_inst_timing_params.SET_HAS_IN_REGS(needs_in_regs)
        func_inst_timing_params.SET_HAS_OUT_REGS(needs_out_regs)
        # Lock these slices in place?
        # Not be sliced through from the top down in the future
        func_inst_timing_params.params_are_fixed = True
        sweep_state.multimain_timing_params.TimingParamsLookupTable[func_inst] = func_inst_timing_params        
        
        # sET PRINT Cche - yup
        if cache_key not in printed_slices_cache:
          printed_slices_cache.add(cache_key)
      
      # Above determination of slices may have failed
      if not got_timing_params_from_walking_tree:
        continue
        
      # Done pipelining lowest level modules
      # Apply best guess slicing from main top level if wasnt fixed by above loop
      # (could change to do best guess at first place moving up in hier without fixed params?)
      for main_inst in parser_state.main_mhz:
        main_inst_timing_params = sweep_state.multimain_timing_params.TimingParamsLookupTable[main_inst]
        if main_inst_timing_params.params_are_fixed:
          continue
        main_func_logic = parser_state.LogicInstLookupTable[main_inst]
        main_func_path_delay_ns = float(main_func_logic.delay) / DELAY_UNIT_MULT
        target_mhz = GET_TARGET_MHZ(main_func, parser_state)
        target_path_delay_ns = 1000.0 / target_mhz
        clks = int(math.ceil((main_func_path_delay_ns*sweep_state.inst_sweep_state[main_inst].best_guess_sweep_mult) / target_path_delay_ns)) - 1
        if clks <= 0:
          continue 
        slices = GET_BEST_GUESS_IDEAL_SLICES(clks)
        print("Best guess slicing:",main_func_logic.func_name,", mult =", sweep_state.inst_sweep_state[main_func].best_guess_sweep_mult, slices, flush=True)
        write_files = False
        sweep_state.multimain_timing_params.TimingParamsLookupTable = (
          ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
            main_inst, main_func_logic, slices, parser_state, 
            sweep_state.multimain_timing_params.TimingParamsLookupTable, write_files) )
        # Set this module to use io regs or not
        main_inst_timing_params = sweep_state.multimain_timing_params.TimingParamsLookupTable[main_inst]
        main_inst_timing_params.SET_HAS_IN_REGS(False)
        main_inst_timing_params.SET_HAS_OUT_REGS(False)
        # Lock these slices in place?
        # Not be sliced through from the top down in the future
        main_inst_timing_params.params_are_fixed = False # Best guess can be overwritten
        sweep_state.multimain_timing_params.TimingParamsLookupTable[main_inst] = main_inst_timing_params
        
    #}END WHILE LOOP REPEATEDLY walking tree for params
    
    # Quit if cant slice submodules to meet timing / no params from walking tree
    if not got_timing_params_from_walking_tree:
      print("Failed to make even smallest submodules meet timing? Impossible timing goals?")
      sys.exit(-1)
      
    # Do one final dumb loop over all timing params that arent zero clocks?
    # because write_files_in_loop = False above
    print("Updating output files...",flush=True)
    entities_written = set()
    for inst_name_to_wr in sweep_state.multimain_timing_params.TimingParamsLookupTable:
      wr_logic = parser_state.LogicInstLookupTable[inst_name_to_wr]
      wr_timing_params = sweep_state.multimain_timing_params.TimingParamsLookupTable[inst_name_to_wr]
      if wr_timing_params.GET_TOTAL_LATENCY(parser_state, sweep_state.multimain_timing_params.TimingParamsLookupTable) > 0:
        entity_name = VHDL.GET_ENTITY_NAME(inst_name_to_wr, wr_logic, sweep_state.multimain_timing_params.TimingParamsLookupTable, parser_state)
        if entity_name not in entities_written:
          entities_written.add(entity_name)
          wr_syn_out_dir = GET_OUTPUT_DIRECTORY(wr_logic)
          if not os.path.exists(wr_syn_out_dir):
            os.makedirs(wr_syn_out_dir)
          wr_filename = wr_syn_out_dir + "/" + entity_name + ".vhd"
          if not os.path.exists(wr_filename):
            VHDL.WRITE_LOGIC_ENTITY(inst_name_to_wr, wr_logic, wr_syn_out_dir, parser_state, sweep_state.multimain_timing_params.TimingParamsLookupTable)
      
    # Run syn on multi main top
    print("Running syn w timing params...",flush=True)
    for main_func in parser_state.main_mhz:
      main_func_logic = parser_state.FuncLogicLookupTable[main_func]
      main_func_timing_params = sweep_state.multimain_timing_params.TimingParamsLookupTable[main_func]
      print(main_func,":",main_func_timing_params.GET_TOTAL_LATENCY(parser_state,sweep_state.multimain_timing_params.TimingParamsLookupTable),"clocks latency...", flush=True)
    sweep_state.timing_report = DO_SYN_FROM_TIMING_PARAMS(sweep_state.multimain_timing_params, parser_state)
    
    # Did it meet timing? Make adjusments as checking
    made_adj = False
    has_paths = len(sweep_state.timing_report.path_reports) > 0
    sweep_state.met_timing = has_paths
    for reported_clock_group in sweep_state.timing_report.path_reports:
      path_report = sweep_state.timing_report.path_reports[reported_clock_group]
      curr_mhz = 1000.0 / path_report.path_delay_ns
      # Oh boy old log files can still be used if target freq changes right?
      # Do a little hackery to get actual target freq right now, not from log
      # Could be a clock crossing too right?
      main_insts = GET_MAIN_INSTS_FROM_PATH_REPORT(path_report, parser_state, sweep_state.multimain_timing_params)
      if len(main_insts) <= 0:
        print("No main functions in timing report for path group:",reported_clock_group)
        print(path_report.start_reg_name)
        print(path_report.end_reg_name)
        print(path_report.netlist_resources)
        for main_inst in parser_state.main_mhz:
          main_logic = parser_state.LogicInstLookupTable[main_inst]
          main_vhdl_entity_name = VHDL.GET_ENTITY_NAME(main_inst, main_logic, sweep_state.multimain_timing_params.TimingParamsLookupTable, parser_state)
          print(main_vhdl_entity_name)
        sys.exit(-1)
      # Check timing, make adjustments and print info for each main in the timing report
      for main_inst in main_insts:
        # Met timing?
        main_func_logic = parser_state.LogicInstLookupTable[main_inst]
        main_func_timing_params = sweep_state.multimain_timing_params.TimingParamsLookupTable[main_inst]
        latency = main_func_timing_params.GET_TOTAL_LATENCY(parser_state,sweep_state.multimain_timing_params.TimingParamsLookupTable)
        target_mhz = GET_TARGET_MHZ(main_inst, parser_state)
        target_path_delay_ns = 1000.0 / target_mhz
        clk_group = parser_state.main_clk_group[main_inst]
        main_met_timing = curr_mhz >= target_mhz
        if not main_met_timing:
          sweep_state.met_timing = False
          
        # Print and log
        print("{} Clock Goal: {:.2f} (MHz) Current: {:.2f} (MHz)({:.2f} ns) {} clks".format(
          main_func_logic.func_name, target_mhz, curr_mhz, path_report.path_delay_ns, latency), flush=True)
        best_mhz_so_far = 0.0
        if len(sweep_state.inst_sweep_state[main_inst].mhz_to_latency) > 0:
          best_mhz_so_far = max(sweep_state.inst_sweep_state[main_inst].mhz_to_latency.keys())
        best_mhz_this_latency = 0.0
        if latency in sweep_state.inst_sweep_state[main_inst].latency_to_mhz:
          best_mhz_this_latency = sweep_state.inst_sweep_state[main_inst].latency_to_mhz[latency]
        better_mhz = curr_mhz > best_mhz_so_far
        better_latency = curr_mhz > best_mhz_this_latency
        # Log result
        if better_mhz or better_latency:
          sweep_state.inst_sweep_state[main_inst].mhz_to_latency[curr_mhz] = latency
          sweep_state.inst_sweep_state[main_inst].latency_to_mhz[latency] = curr_mhz

        # Make adjustment if can be sliced
        if not main_met_timing:
          print_path = False
          if main_func_logic.CAN_BE_SLICED():
            best_guess_sweep_mult_inc = 1.2 # 20% default
            if not better_mhz:
              best_guess_sweep_mult_inc = 2.0 # Big double jump
            if (sweep_state.inst_sweep_state[main_inst].best_guess_sweep_mult*best_guess_sweep_mult_inc) > BEST_GUESS_MUL_MAX: #15 like? main_max_allowed_latency_mult  2.0 magic?
              # Fail here, increment sweep mut and try_to_slice logic will slice lower module next time
              print("Middle sweep at this hierarchy level failed to meet timing, trying to pipeline current modules to higher fmax to compensate...") 
              if (sweep_state.inst_sweep_state[main_inst].coarse_sweep_mult+COARSE_SWEEP_MULT_INC) <= COARSE_SWEEP_MULT_MAX: #1.5: # MAGIC?
                  sweep_state.inst_sweep_state[main_inst].best_guess_sweep_mult = 1.0
                  sweep_state.inst_sweep_state[main_inst].coarse_sweep_mult += COARSE_SWEEP_MULT_INC
                  print("Coarse synthesis sweep multiplier:",sweep_state.inst_sweep_state[main_inst].coarse_sweep_mult)
                  made_adj = True
              elif sweep_state.inst_sweep_state[main_inst].smallest_not_sliced_hier_mult!=INF_HIER_MULT:
                print("Trying to pipeline smaller modules instead...")
                # Dont compensate with higher fmax, start with original coarse grain compensation on smaller modules
                # WTF float stuff end up with slice getting repeatedly set just close enough not to slice next level down ?
                if sweep_state.inst_sweep_state[main_func].smallest_not_sliced_hier_mult == sweep_state.inst_sweep_state[main_func].hier_sweep_mult:
                  sweep_state.inst_sweep_state[main_func].hier_sweep_mult += HIER_SWEEP_MULT_INC
                  print("Nudging hierarchy sweep multiplier:",sweep_state.inst_sweep_state[main_func].hier_sweep_mult)
                else:
                  sweep_state.inst_sweep_state[main_inst].hier_sweep_mult = sweep_state.inst_sweep_state[main_inst].smallest_not_sliced_hier_mult
                  print("Hierarchy sweep multiplier:",sweep_state.inst_sweep_state[main_inst].hier_sweep_mult)
                sweep_state.inst_sweep_state[main_inst].best_guess_sweep_mult = 1.0
                sweep_state.inst_sweep_state[main_inst].coarse_sweep_mult = 1.0
                made_adj = True
              else:
                print_path = True
            else:
              sweep_state.inst_sweep_state[main_inst].best_guess_sweep_mult *= best_guess_sweep_mult_inc
              print("Best guess sweep multiplier:",sweep_state.inst_sweep_state[main_inst].best_guess_sweep_mult)
              made_adj = True
          else:
            print_path = True
          
          if print_path:
            print("Cannot pipeline path to meet timing:")
            print("START: ", path_report.start_reg_name,"=>")
            print(" ~", path_report.path_delay_ns, "ns of logic+routing ~")
            print("END: =>",path_report.end_reg_name, flush=True)
          
    if sweep_state.met_timing:
      print("Met timing...")
      return sweep_state
      
    if not made_adj:
      print("Giving up...")
      sys.exit(-1)

        
# Returns main_inst_to_slices = dict() since "coarse" means timing defined by top level slices
# Of Montreal - The Party's Crashing Us
# Starting guess really only saves 1 extra syn run for dup multimain top
def DO_COARSE_THROUGHPUT_SWEEP(inst_name, target_mhz,
    inst_sweep_state, parser_state,
    starting_guess_latency=None, do_incremental_guesses=True, 
    max_allowed_latency_mult=None,
    stop_at_n_worse_result=None):
  working_slices = None
  logic = parser_state.LogicInstLookupTable[inst_name]
  # Reasonable starting guess and coarse throughput strategy is dividing each main up to meet target
  # Dont even bother running multimain top as combinatorial logic
  inst_sweep_state.coarse_latency = 0
  inst_sweep_state.initial_guess_latency = 0
  if starting_guess_latency is None:
    target_path_delay_ns = 1000.0 / target_mhz
    path_delay_ns = float(logic.delay) / DELAY_UNIT_MULT
    if path_delay_ns > 0.0:
      #curr_mhz = 1000.0 / path_delay_ns
      # How many multiples are we away from the goal
      mult = path_delay_ns / target_path_delay_ns
      if mult > 1.0:
        # Divide up into that many clocks as a starting guess
        # If doesnt have global wires
        if logic.CAN_BE_SLICED():
          clks = int(math.ceil(mult)) - 1
          inst_sweep_state.coarse_latency = clks
          inst_sweep_state.initial_guess_latency = clks
  else:
    if logic.CAN_BE_SLICED():
      inst_sweep_state.coarse_latency = starting_guess_latency
      inst_sweep_state.initial_guess_latency = starting_guess_latency
      
  # Do loop of:
  #   Reset top to 0 clk
  #   Slice each main evenly based on latency
  #   Syn multimain top
  #   Course adjust func latency
  # until mhz goals met
  while True:
    # Reset to zero clock
    print("Starting from comb. logic...",flush=True)
    # TODO dont need full copy of all other inst being zero clock too
    TimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state)
    
    # Do slicing
    # Set the slices in timing params and then rebuild
    done = False
    logic = parser_state.LogicInstLookupTable[inst_name]
    # Make even slices      
    best_guess_slices = GET_BEST_GUESS_IDEAL_SLICES(inst_sweep_state.coarse_latency)
    print(logic.func_name,": sliced coarsely ~=", inst_sweep_state.coarse_latency, "clocks latency...", flush=True)
    # Do slicing and dont write vhdl this way since slow
    write_files = False
    
    # Sanity
    if len(TimingParamsLookupTable[inst_name]._slices) !=0:
      print("Not starting with comb logic for main? sliced already?",TimingParamsLookupTable[inst_name]._slices)
      sys.exit(-1)        
    
    # Apply slices to main funcs 
    TimingParamsLookupTable = ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(inst_name, logic, best_guess_slices, parser_state, TimingParamsLookupTable, write_files)
    # TimingParamsLookupTable == None 
    # means these slices go through global code
    if type(TimingParamsLookupTable) is not dict:
      print("Slicing through globals still an issue?")
      sys.exit(-1)
      #print("Can't syn when slicing through globals!")
      #return None, None, None, None  
      
    # SANITY
    if TimingParamsLookupTable[inst_name]._slices != best_guess_slices:
      print("Tried to slice as ",best_guess_slices, "but got",TimingParamsLookupTable[inst_name]._slices)
      sys.exit(-1)
    
    
    # Fast one time loop writing only files that have non default,>0 latency
    print("Updating output files...",flush=True)
    entities_written = set()
    for inst_name_to_wr in TimingParamsLookupTable:
      wr_logic = parser_state.LogicInstLookupTable[inst_name_to_wr]
      wr_timing_params = TimingParamsLookupTable[inst_name_to_wr]
      if wr_timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable) > 0:
        entity_name = VHDL.GET_ENTITY_NAME(inst_name_to_wr, wr_logic, TimingParamsLookupTable, parser_state)
        if entity_name not in entities_written:
          entities_written.add(entity_name)
          wr_syn_out_dir = GET_OUTPUT_DIRECTORY(wr_logic)
          if not os.path.exists(wr_syn_out_dir):
            os.makedirs(wr_syn_out_dir)
          wr_filename = wr_syn_out_dir + "/" + entity_name + ".vhd"
          if not os.path.exists(wr_filename):
            VHDL.WRITE_LOGIC_ENTITY(inst_name_to_wr, wr_logic, wr_syn_out_dir, parser_state, TimingParamsLookupTable)
          
    
    # Run syn on multi main top
    print("Running syn w slices...",flush=True)
    inst_sweep_state.timing_report = SYN_TOOL.SYN_AND_REPORT_TIMING(inst_name, logic, parser_state, TimingParamsLookupTable)
    
    # Did it meet timing? Make adjusments as checking
    made_adj = False
    has_paths = len(inst_sweep_state.timing_report.path_reports) > 0
    inst_sweep_state.met_timing = has_paths
    for reported_clock_group in inst_sweep_state.timing_report.path_reports:
      path_report = inst_sweep_state.timing_report.path_reports[reported_clock_group]
      curr_mhz = 1000.0 / path_report.path_delay_ns
      # Oh boy old log files can still be used if target freq changes right?
      # Do a little hackery to get actual target freq right now, not from log
      # Could be a clock crossing too right?
      
      # Met timing?
      func_logic = parser_state.LogicInstLookupTable[inst_name]
      timing_params = TimingParamsLookupTable[inst_name]
      latency = timing_params.GET_TOTAL_LATENCY(parser_state,TimingParamsLookupTable)
      met_timing = curr_mhz >= target_mhz
      if not met_timing:
        inst_sweep_state.met_timing = False
        
      # Print, log, maybe give up
      print("{} Clock Goal: {:.2f} (MHz) Current: {:.2f} (MHz)({:.2f} ns) {} clks".format(
        func_logic.func_name, target_mhz, curr_mhz, path_report.path_delay_ns, latency), flush=True)
      best_mhz_so_far = 0.0
      if len(inst_sweep_state.mhz_to_latency) > 0:
        best_mhz_so_far = max(inst_sweep_state.mhz_to_latency.keys())
      better_mhz = curr_mhz >= best_mhz_so_far
      if better_mhz:
        # Log result
        inst_sweep_state.mhz_to_latency[curr_mhz] = latency
        inst_sweep_state.latency_to_mhz[latency] = curr_mhz
        # Log return val best result fmax
        best_guess_slices = GET_BEST_GUESS_IDEAL_SLICES(inst_sweep_state.coarse_latency)
        working_slices = best_guess_slices
        # Reset count of bad tries
        inst_sweep_state.worse_or_same_tries_count = 0
      else:
        # Same or worse timing result
        inst_sweep_state.worse_or_same_tries_count += 1
        print(f"Same or worse timing result... (best={best_mhz_so_far})", flush=True)
        if stop_at_n_worse_result is not None:
          if inst_sweep_state.worse_or_same_tries_count >= stop_at_n_worse_result:
            print(logic.func_name,"giving up after",inst_sweep_state.worse_or_same_tries_count,"bad tries...")
            continue
      
      # Make adjustment if can be sliced
      if not met_timing and func_logic.CAN_BE_SLICED():
        # DO incremental guesses based on time report results
        if do_incremental_guesses:
          max_path_delay = path_report.path_delay_ns
          # Given current latency for pipeline and stage delay what new total comb logic delay does this imply?
          total_delay = max_path_delay * (inst_sweep_state.coarse_latency + 1)
          # How many slices for that delay to meet timing
          fake_one_clk_mhz = 1000.0 / total_delay
          mult = target_mhz / fake_one_clk_mhz
          if mult > 1.0:
            # Divide up into that many clocks
            clks = int(mult) - 1
            print("Timing report suggests",clks,"clocks...")
            # Reached max check again before setting main_inst_to_coarse_latency
            if max_allowed_latency_mult is not None:
              if inst_sweep_state.initial_guess_latency == 0:
                limit = max_allowed_latency_mult
              else:
                limit = inst_sweep_state.initial_guess_latency*max_allowed_latency_mult
              if clks >= limit:
                print(logic.func_name,"reached maximum allowed latency, no more adjustments...")
                continue
            
            '''
            # If very far off, or at very low local min, suggested step can be too large
            inc_ratio = clks / inst_sweep_state.coarse_latency
            if inc_ratio > MAX_CLK_INC_RATIO:
              clks = int(MAX_CLK_INC_RATIO*inst_sweep_state.coarse_latency)
              print("Clipped for smaller jump up to",clks,"clocks...")
            '''
            # If very close to goal suggestion might be same clocks (or less?), still increment
            if clks <= inst_sweep_state.coarse_latency:
              clks = inst_sweep_state.coarse_latency + 1 
            # Calc diff in latency change
            clk_inc = clks - inst_sweep_state.coarse_latency
            # Should be getting smaller
            if inst_sweep_state.last_latency_increase is not None and clk_inc >= inst_sweep_state.last_latency_increase:
              # Clip to last inc size - 1, minus one to always be narrowing down
              clk_inc = inst_sweep_state.last_latency_increase - 1
              if clk_inc <= 0:
                clk_inc = 1
              clks = inst_sweep_state.coarse_latency + clk_inc
              print("Clipped for decreasing jump size to",clks,"clocks...")
            
            # Record
            inst_sweep_state.last_non_passing_latency = inst_sweep_state.coarse_latency
            inst_sweep_state.coarse_latency = clks
            inst_sweep_state.last_latency_increase = clk_inc
            made_adj = True
        else:
          # No guess, dumb increment by 1
          # Record, save non passing latency
          inst_sweep_state.last_non_passing_latency = inst_sweep_state.coarse_latency
          inst_sweep_state.coarse_latency += 1
          inst_sweep_state.last_latency_increase = 1
          made_adj = True
          
    # Passed timing?
    if inst_sweep_state.met_timing:
      return inst_sweep_state, working_slices, TimingParamsLookupTable
    # Stuck?
    if not made_adj:
      print("Unable to make further adjustments. Failed coarse grain attempt meet timing for this module.")
      return inst_sweep_state, working_slices, TimingParamsLookupTable 
  
  return inst_sweep_state, working_slices, TimingParamsLookupTable

def GET_SLICE_PER_STAGE(current_slices):
  # Get list of how many slice per stage
  slice_per_stage = []
  slice_total = 0.0
  for slice_pos in current_slices:
    slice_size = slice_pos - slice_total
    slice_per_stage.append(slice_size)
    slice_total = slice_total + slice_size
  # Add end stage
  slice_size = 1.0 - current_slices[len(current_slices)-1]
  slice_per_stage.append(slice_size)
  
  return slice_per_stage
  
def BUILD_SLICES(slice_per_stage):
  rv = []
  slice_total = 0.0
  for slice_size in slice_per_stage:
    new_slice = slice_size + slice_total
    rv.append(new_slice)
    slice_total = slice_total + slice_size  
  # Remove end slice?
  rv = rv[0:len(rv)-1]
  return rv
  
# Return slices
def EXPAND_STAGES_VIA_ADJ_COUNT(missing_stages, current_slices, slice_step, state, min_dist): 
  print("<<<<<<<<<<< EXPANDING", missing_stages, "VIA_ADJ_COUNT:",current_slices)
  slice_per_stage = GET_SLICE_PER_STAGE(current_slices)
  # Each missing stage is expanded by slice_step/num missing stages
  # Div by num missing stages since might not be able to shrink enough slices 
  # to account for every missing stage getting slice step removed
  expansion = slice_step / len(missing_stages)
  total_expansion = 0.0
  for missing_stage in missing_stages:
    slice_per_stage[missing_stage] = slice_per_stage[missing_stage] + expansion
    total_expansion = total_expansion + expansion
  
  remaining_expansion = total_expansion
  # Split remaining expansion among other stages
  # First check how many stages will be shrank
  stages_to_shrink = []
  for stage in range(0, len(current_slices)+1):
    if not(stage in missing_stages) and (slice_per_stage[stage] - expansion > min_dist):
      stages_to_shrink.append(stage)
  if len(stages_to_shrink) > 0:
    shrink_per_stage = total_expansion / float(len(stages_to_shrink))
    for stage in stages_to_shrink:
      print("Shrinking stage",stage, "curr size:", slice_per_stage[stage])
      slice_per_stage[stage] -= shrink_per_stage  
    
    # reconstruct new slcies
    rv = BUILD_SLICES(slice_per_stage)
    
    #print "RV",rv
    #sys.exit(-1)
    
    return rv
  else:
    # Can't shrink anything more
    return current_slices

  


def ESTIMATE_MAX_THROUGHPUT(mhz_range, mhz_to_latency):
  '''
  High Clock  High Latency  High Period Low Clock Low Latency Low Period  "Required parallel
  Low clock"  "Serialization
  Latency (1 or each clock?) (ns)"
  160 5 6.25  100   10  1.6 16.25
  240 10            
  100 2           
  260 10            
  40  0           
  220 10            
  140 5           
  80  1           
  200 10            
  20  0           
  300 43            
  120 5           
  180 8           
  60  1           
  280 32            
  '''
  min_mhz = min(mhz_range)
  max_mhz = max(mhz_range)
  max_div = int(math.ceil(max_mhz/min_mhz))
  
  text = ""
  text += "clk_mhz" + " " +"high_clk_latency_ns" + "  " + "div_clk_mhz" + " " + "div_clock_latency_ns" + "  " + "n_parallel" + "  " + "deser_delay" + " " + "ser_delay" + " " + "total_latency" + "\n"
  
  # For each clock we have calculate the integer divided clocks
  for clk_mhz in mhz_to_latency:
    # Orig latency
    clk_period_ns = (1.0/clk_mhz)*1000
    high_clk_latency_ns = mhz_to_latency[clk_mhz] * clk_period_ns
    # Find interger divided clocks we have entries for
    for div_i in range(2,max_div+1):
      div_clk_mhz =  clk_mhz / div_i
      if div_clk_mhz in mhz_to_latency:
        # Have div clock entry
        n_parallel = div_i
        div_clk_period_ns = (1.0/div_clk_mhz)*1000
        # Deserialize
        deser_delay = clk_period_ns + div_clk_period_ns # one of each clock?
        # Latency is one of the low clock
        div_clock_latency_clks = mhz_to_latency[div_clk_mhz]
        div_clock_latency_ns = div_clock_latency_clks * div_clk_period_ns
        # Serialize
        ser_delay = clk_period_ns + div_clk_period_ns # one of each clock?
        # total latency
        total_latency  = deser_delay + div_clock_latency_ns + ser_delay
        
        text += str(clk_mhz) + "  " + str(high_clk_latency_ns) + "  " + str(div_clk_mhz) + "  " + str(div_clock_latency_ns) + " " + str(n_parallel) + " " + str(deser_delay) + "  " + str(ser_delay) + "  " + str(total_latency) + "\n"
    
  
  f = open(SYN_OUTPUT_DIRECTORY + "/" + "estimated_max_throughput.log","w")
  f.write(text)
  f.close()

def GET_OUTPUT_DIRECTORY(Logic):
  if Logic.is_c_built_in:
    output_directory = SYN_OUTPUT_DIRECTORY + "/" + "built_in" + "/" + Logic.func_name
  elif SW_LIB.IS_BIT_MANIP(Logic):
    output_directory = SYN_OUTPUT_DIRECTORY + "/" + SW_LIB.BIT_MANIP_HEADER_FILE + "/" + Logic.func_name
  elif SW_LIB.IS_MEM(Logic):
    output_directory = SYN_OUTPUT_DIRECTORY + "/" + SW_LIB.MEM_HEADER_FILE + "/" + Logic.func_name
  elif SW_LIB.IS_BIT_MATH(Logic):
    output_directory = SYN_OUTPUT_DIRECTORY + "/" + SW_LIB.BIT_MATH_HEADER_FILE + "/" + Logic.func_name
  else:
    # Use source file if not built in?
    src_file = str(Logic.c_ast_node.coord.file)
    # # hacky catch files from same dir as script?
    # ex src file = /media/1TB/Dropbox/PipelineC/git/PipelineC/src/../axis.h
    repo_dir = C_TO_LOGIC.REPO_ABS_DIR()
    if src_file.startswith(repo_dir):
      # hacky
      src_file = src_file.replace(repo_dir + "/src/../","")
      src_file = src_file.replace(repo_dir + "/","")      
      output_directory = SYN_OUTPUT_DIRECTORY + "/" + src_file + "/" + Logic.func_name
    # hacky catch generated files from output dir already?
    elif src_file.startswith(SYN_OUTPUT_DIRECTORY+"/"):
      output_directory = os.path.dirname(src_file)
    else:
      # Otherwise normal
      #output_directory = SYN_OUTPUT_DIRECTORY + "/" + src_file + "/" + Logic.func_name
      #print("output_directory",output_directory,repo_dir)
      # Func uniquely identifies logic so just use that?
      output_directory = SYN_OUTPUT_DIRECTORY + "/" + Logic.func_name
    
  return output_directory
  
def LOGIC_IS_ZERO_DELAY(logic, parser_state):
  if logic.func_name in parser_state.func_marked_wires:
    return True
  # Black boxes have no known delay to the tool
  elif logic.func_name in parser_state.func_marked_blackbox:
    return True    
  elif SW_LIB.IS_BIT_MANIP(logic):
    return True
  elif logic.is_clock_crossing:
    return True # For now? How to handle paths through clock cross logic?
  elif logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
    return True
  elif logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SL_NAME) or logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SR_NAME):
    return True
  elif logic.is_vhdl_text_module:
    return False # No idea what user has in there
  elif logic.is_vhdl_func or logic.is_vhdl_expr:
    return True
  elif logic.func_name.startswith(C_TO_LOGIC.PRINTF_FUNC_NAME):
    return True
  else:
    # Maybe all submodules are zero delay?
    if len(logic.submodule_instances) > 0:
      for submodule_inst in logic.submodule_instances:
        submodule_func_name = logic.submodule_instances[submodule_inst]
        submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
        if submodule_logic.delay is None:
          print("Wtf none to check delay?")
          sys.exit(-1)
        if submodule_logic.delay > 0:
          return False
      return True
    
  return False
  
def LOGIC_SINGLE_SUBMODULE_DELAY(logic, parser_state):
  if len(logic.submodule_instances) != 1:
    return None
  if logic.is_vhdl_text_module:
    return None
    
  submodule_inst = list(logic.submodule_instances.keys())[0]
  submodule_func_name = logic.submodule_instances[submodule_inst]
  submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
  if submodule_logic.delay is None:
    print("Wtf none to check delay???????")
    sys.exit(-1)
     
  return submodule_logic.delay

def IS_USER_CODE(logic, parser_state):
  # Check logic.is_built_in
  # or autogenerated code 
  
  user_code = (not logic.is_c_built_in and not SW_LIB.IS_AUTO_GENERATED(logic))
  
  # GAH NEED TO CHECK input and output TYPES
  # AND ALL INNNER WIRES TOO!
  all_types = []
  for input_port in logic.inputs:
    all_types.append(logic.wire_to_c_type[input_port])
  for wire in logic.wires: 
    all_types.append(logic.wire_to_c_type[wire])
  for output_port in logic.outputs:
    all_types.append(logic.wire_to_c_type[output_port])
  all_types = list(set(all_types))
  
  # Becomes user code if using struct or array of structs
  # For now???? fuck me
  for c_type in all_types:
    is_user = C_TO_LOGIC.C_TYPE_IS_USER_TYPE(c_type,parser_state)
    if is_user:
      user_code = True
      break
  #print "?? USER? logic.func_name:",logic.func_name, user_code
  
  return user_code
    
def GET_PATH_DELAY_CACHE_DIR(logic, parser_state):
  PATH_DELAY_CACHE_DIR= C_TO_LOGIC.EXE_ABS_DIR() + "/../path_delay_cache/" + str(SYN_TOOL.__name__).lower() + "/" + parser_state.part
  return PATH_DELAY_CACHE_DIR

def GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state):
  # Default sanity
  key = logic.func_name
  
  # Mux is same delay no matter type
  if logic.is_c_built_in and logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME):
    key = "mux"
  else:
    # MEM has var name - weird yo
    if SW_LIB.IS_MEM(logic):
      key = SW_LIB.GET_MEM_NAME(logic)
    
    func_name_includes_types = SW_LIB.FUNC_NAME_INCLUDES_TYPES(logic)
    if not func_name_includes_types:
      for input_port in logic.inputs:
        c_type = logic.wire_to_c_type[input_port]
        key += "_" + c_type
  
  if parser_state.part is None:
    print("Did not set FPGA part!")
    print('Ex. #pragma PART "xc7a35ticsg324-1l"')
    sys.exit(-1)
  
  file_path = GET_PATH_DELAY_CACHE_DIR(logic, parser_state) + "/" + key + ".delay"
  
  return file_path
  
def GET_CACHED_PATH_DELAY(logic, parser_state): 
  # Look in cache dir
  file_path = GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state)
  if os.path.exists(file_path):
    #print "Reading Cached Delay File:", file_path
    return float(open(file_path,"r").readlines()[0])
    
  return None 
  
def ADD_PATH_DELAY_TO_LOOKUP(parser_state):
  # Make sure synthesis tool is set
  PART_SET_TOOL(parser_state.part)
  
  #print("WHY SLO?")
  #sys.exit(-1)
  
  print("Synthesizing as combinatorial logic to get total logic delay...", flush=True)
  print("", flush=True)
  TimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state)
  multimain_timing_params = MultiMainTimingParams()
  multimain_timing_params.TimingParamsLookupTable = TimingParamsLookupTable
  
  # Record stats on functions with globals - TODO per main func?
  min_mhz = 999999999
  min_mhz_func_name = None
  
  #bAAAAAAAAAAAhhhhhhh need to recursively do this 
  # Do depth first 
  # haha no do it the dumb easy way
  func_names_done_so_far = []
  func_names_done_so_far.append(C_TO_LOGIC.VHDL_FUNC_NAME) # Hacky?
  all_funcs_done = False
  while not all_funcs_done:
    all_funcs_done = True

    # Determine funcs that need syn and can be syn'd in parallel
    parallel_func_names = []
    still_finding_parallel_funcs = True
    while still_finding_parallel_funcs:
      still_finding_parallel_funcs = False
      for logic_func_name in parser_state.FuncLogicLookupTable:
        # If already done then skip
        if logic_func_name in func_names_done_so_far:
          continue
        # Skip vhdl funcs as they will be syn'd as container logic
        if logic_func_name == C_TO_LOGIC.VHDL_FUNC_NAME:
          continue
        # Get logic
        logic = parser_state.FuncLogicLookupTable[logic_func_name]
        # Any inst will do, skip func if was never used as instance
        inst_name = None
        if logic_func_name in parser_state.FuncToInstances:
          inst_name = list(parser_state.FuncToInstances[logic_func_name])[0]
        if inst_name is None:
          #print("Warning?: No logic instance for function:", logic.func_name, "never used?")
          continue
        # All dependencies met?
        all_dep_met = True
        for submodule_inst in logic.submodule_instances:
          submodule_func_name = logic.submodule_instances[submodule_inst]
          if submodule_func_name not in func_names_done_so_far:
            #print logic_func_name, "submodule_func_name not in func_names_done_so_far",submodule_func_name
            all_dep_met = False
            break 
        # If all dependencies met then maybe add to list do syn yet
        if all_dep_met:
          # Try to get cached path delay
          cached_path_delay = GET_CACHED_PATH_DELAY(logic, parser_state)
          if cached_path_delay is not None:
            logic.delay = int(cached_path_delay * DELAY_UNIT_MULT)
            print("Function:",logic.func_name, "Cached path delay(ns):", cached_path_delay)
            if cached_path_delay > 0.0 and logic.delay==0:
              print("Have timing path of",cached_path_delay,"ns")
              print("...but recorded zero delay. Increase delay multiplier!")
              sys.exit(-1)
          # Then check for known delays
          elif LOGIC_IS_ZERO_DELAY(logic, parser_state):
            logic.delay = 0
          elif LOGIC_SINGLE_SUBMODULE_DELAY(logic, parser_state) is not None:
            logic.delay = LOGIC_SINGLE_SUBMODULE_DELAY(logic, parser_state)
            print("Function:", logic.func_name, "assumed same delay as it's single submodule...")
          
          # Save delay value or prepare for syn to determine
          if logic.delay is None:
            # Run real syn in parallel
            if logic_func_name not in parallel_func_names:
              parallel_func_names.append(logic_func_name)
              still_finding_parallel_funcs = True
          else:
            # Save value
            # Save logic with delay into lookup
            parser_state.FuncLogicLookupTable[logic_func_name] = logic
            # Done
            func_names_done_so_far.append(logic_func_name)
        else:
          # Not all funcs are done
          all_funcs_done = False
    
    # Print what is being synthesized first
    for logic_func_name in parallel_func_names:
      # Get logic
      logic = parser_state.FuncLogicLookupTable[logic_func_name]
      # Any inst will do
      inst_name = None
      if logic.func_name in parser_state.FuncToInstances:
        inst_name = list(parser_state.FuncToInstances[logic.func_name])[0]
      if inst_name is None:
        #print "Warning?: No logic instance for function:", logic.func_name, "never used?"
        continue
      print("Synthesizing function:",logic.func_name, flush=True)
      if len(logic.submodule_instances) > 0 and not logic.is_vhdl_text_module:  # TODO make pipeline map return empty instead of check?
        zero_clk_pipeline_map = GET_ZERO_CLK_PIPELINE_MAP(inst_name, logic, parser_state) # use inst_logic since timing params are by inst
        zero_clk_pipeline_map_str = str(zero_clk_pipeline_map)
        out_dir = GET_OUTPUT_DIRECTORY(logic)
        if not os.path.exists(out_dir):
          os.makedirs(out_dir) 
        out_path = out_dir + "/pipeline_map.log"
        f=open(out_path,'w')
        f.write(zero_clk_pipeline_map_str)
        f.close()      
      
    # Start parallel syn for parallel_func_names
    # Parallelized
    NUM_PROCESSES = int(open(C_TO_LOGIC.EXE_ABS_DIR() + "/../num_processes.cfg",'r').readline())
    my_thread_pool = ThreadPool(processes=NUM_PROCESSES)
    func_name_to_async_result = dict()
    for logic_func_name in parallel_func_names:
      # Get logic
      logic = parser_state.FuncLogicLookupTable[logic_func_name]
      # Any inst will do
      inst_name = None
      if logic_func_name in parser_state.FuncToInstances:
        inst_name = list(parser_state.FuncToInstances[logic_func_name])[0]
      if inst_name is None:
        #print "Warning?: No logic instance for function:", logic.func_name, "never used?"
        continue
      if logic != parser_state.LogicInstLookupTable[inst_name]:
        print("Mismatching logic!?", logic.func_name)
        sys.exit(-1)
      # Run Syn
      total_latency=0
      #parsed_timing_report = SYN_TOOL.SYN_AND_REPORT_TIMING(inst_name, logic, parser_state, TimingParamsLookupTable, total_latency)
      #sys.exit(-1)
      my_async_result = my_thread_pool.apply_async(SYN_TOOL.SYN_AND_REPORT_TIMING, (inst_name, logic, parser_state, TimingParamsLookupTable, total_latency))
      func_name_to_async_result[logic_func_name] = my_async_result
      
    # Finish parallel syn
    for logic_func_name in parallel_func_names:
      # Get logic
      logic = parser_state.FuncLogicLookupTable[logic_func_name]
      # Get result
      my_async_result = func_name_to_async_result[logic_func_name]
      print("...Waiting on synthesis for:", logic_func_name, flush=True)
      parsed_timing_report =  my_async_result.get()
      # Sanity should be one path reported
      if len(parsed_timing_report.path_reports) > 1:
        print("Too many paths reported!",logic.func_name,parsed_timing_report.orig_text)
        sys.exit(-1)
      if len(parsed_timing_report.path_reports) == 0:
        print("No timing paths reported!",logic.func_name,parsed_timing_report.orig_text)
        sys.exit(-1)
      path_report = list(parsed_timing_report.path_reports.values())[0]
      if path_report.path_delay_ns is None:
        print("Cannot parse synthesized path report for path delay ",logic.func_name)
        print(parsed_timing_report.orig_text)
        #if DO_SYN_FAIL_SIM:
        #  MODELSIM.DO_OPTIONAL_DEBUG(do_debug=True)
        sys.exit(-1)
      mhz = 1000.0 / path_report.path_delay_ns
      logic.delay = int(path_report.path_delay_ns * DELAY_UNIT_MULT)
      # Sanity check multiplier is working
      if path_report.path_delay_ns > 0.0 and logic.delay==0:
        print("Have timing path of",path_report.path_delay_ns,"ns")
        print("...but recorded zero delay. Increase delay multiplier!")
        sys.exit(-1)      
      # Make adjustment for 0 LLs to have 0 delay
      if (SYN_TOOL is VIVADO) and path_report.logic_levels == 0:
        logic.delay = 0        
        
      # Syn results are delay and clock 
      print(logic_func_name, "Path delay (ns):", path_report.path_delay_ns, "=",mhz, "MHz")
      print("")
      # Record worst non slicable logic
      if not logic.CAN_BE_SLICED():
        if mhz < min_mhz:
          min_mhz_func_name = logic.func_name
          min_mhz = mhz
          
      # Cache delay syn result if not user code
      if not IS_USER_CODE(logic, parser_state):
        filepath = GET_CACHED_PATH_DELAY_FILE_PATH(logic, parser_state)
        PATH_DELAY_CACHE_DIR = GET_PATH_DELAY_CACHE_DIR(logic, parser_state)
        if not os.path.exists(PATH_DELAY_CACHE_DIR):
          os.makedirs(PATH_DELAY_CACHE_DIR)         
        f=open(filepath,"w")
        f.write(str(path_report.path_delay_ns))
        f.close()       
      
      # Save logic with delay into lookup
      parser_state.FuncLogicLookupTable[logic_func_name] = logic
      
      # Done
      func_names_done_so_far.append(logic_func_name)
  
  # Record worst global
  #if min_mhz_func_name is not None:
  # print "Design limited to ~", min_mhz, "MHz due to function:", min_mhz_func_name
  # parser_state.global_mhz_limit = min_mhz
    
  return parser_state

  
  
# Generalizing is a bad thing to do
# Abstracting is something more


def WRITE_ALL_ZERO_CLK_VHDL(parser_state, ZeroClkTimingParamsLookupTable): 
  # All instances are zero clock so just pick any instance
  for func_name in parser_state.FuncLogicLookupTable:
    if func_name in parser_state.FuncToInstances:
      inst_name = list(parser_state.FuncToInstances[func_name])[0]
      logic = parser_state.FuncLogicLookupTable[func_name]
      # ONly write non vhdl 
      if logic.is_vhdl_func or logic.is_vhdl_expr or (logic.func_name == C_TO_LOGIC.VHDL_FUNC_NAME):
        continue
      # Dont write clock cross funcs
      if logic.is_clock_crossing:
        continue
      # Dont write FSM funcs
      if logic.is_fsm_clk_func:
        continue      
      print("Writing func",func_name,"...", flush=True)
      syn_out_dir = GET_OUTPUT_DIRECTORY(logic)
      if not os.path.exists(syn_out_dir):
        os.makedirs(syn_out_dir)
      VHDL.WRITE_LOGIC_ENTITY(inst_name, logic, syn_out_dir, parser_state, ZeroClkTimingParamsLookupTable)
      
  # Include a zero clock multi main top too
  print("Writing multi main top level files...", flush=True)
  multimain_timing_params = MultiMainTimingParams()
  multimain_timing_params.TimingParamsLookupTable = ZeroClkTimingParamsLookupTable;
  is_final_top = False
  VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top)
  # And clock cross entities
  VHDL.WRITE_CLK_CROSS_ENTITIES(parser_state, multimain_timing_params)
  
# returns vhdl_files_txt,top_entity_name
def GET_VHDL_FILES_TCL_TEXT_AND_TOP(multimain_timing_params, parser_state, inst_name=None):
  # Read in vhdl files with a single (faster than multiple) read_vhdl
  files_txt = ""
  
  # C defined structs
  files_txt += SYN_OUTPUT_DIRECTORY + "/" + "c_structs_pkg" + VHDL.VHDL_PKG_EXT + " "
  
  # Clocking crossing if needed

  if not inst_name and len(parser_state.clk_cross_var_info) > 0:
    # Multimain needs clk cross entities
    # Clock crossing entities
    files_txt += SYN_OUTPUT_DIRECTORY + "/" + "clk_cross_entities" + VHDL.VHDL_FILE_EXT + " " 
      
  needs_clk_cross_t = len(parser_state.clk_cross_var_info) > 0 and not inst_name # is multimain
  if inst_name:
    # Does inst need clk cross?
    Logic = parser_state.LogicInstLookupTable[inst_name]
    needs_clk_cross_to_module = VHDL.LOGIC_NEEDS_CLK_CROSS_TO_MODULE(Logic, parser_state)#, multimain_timing_params.TimingParamsLookupTable)
    needs_module_to_clk_cross = VHDL.LOGIC_NEEDS_MODULE_TO_CLK_CROSS(Logic, parser_state)#, multimain_timing_params.TimingParamsLookupTable)
    needs_clk_cross_t = needs_clk_cross_to_module or needs_module_to_clk_cross
  if needs_clk_cross_t:
    # Clock crossing record
    files_txt += SYN_OUTPUT_DIRECTORY + "/" + "clk_cross_t_pkg" + VHDL.VHDL_PKG_EXT + " "
    
  
  # Top not shared
  top_entity_name = VHDL.GET_TOP_ENTITY_NAME(parser_state, multimain_timing_params, inst_name)
  if inst_name:
    Logic = parser_state.LogicInstLookupTable[inst_name]
    output_directory = GET_OUTPUT_DIRECTORY(Logic)
    files_txt += output_directory + "/" + top_entity_name + VHDL.VHDL_FILE_EXT + " "
  else:
    # Entity and file name
    filename = top_entity_name + VHDL.VHDL_FILE_EXT
    files_txt += SYN_OUTPUT_DIRECTORY + "/top/" +  filename + " "
    
    
  # Write all entities starting at this inst/multi main
  inst_names = set()
  if inst_name:
    inst_names = set([inst_name])
  else:
    inst_names = set(parser_state.main_mhz.keys())
  
  entities_so_far = set() 
  while len(inst_names) > 0:
    next_inst_names = set()
    for inst_name_i in inst_names:
      logic_i = parser_state.LogicInstLookupTable[inst_name_i]
      # Write file text
      # ONly write non vhdl
      if logic_i.is_vhdl_func or logic_i.is_vhdl_expr or logic_i.func_name == C_TO_LOGIC.VHDL_FUNC_NAME:
        continue
      # Dont write clock cross
      if logic_i.is_clock_crossing:
        continue
      entity_filename = VHDL.GET_ENTITY_NAME(inst_name_i, logic_i,multimain_timing_params.TimingParamsLookupTable, parser_state) + ".vhd" 
      if entity_filename not in entities_so_far:
        entities_so_far.add(entity_filename)
        # Include entity file for this functions slice variant
        syn_output_directory = GET_OUTPUT_DIRECTORY(logic_i)
        files_txt += syn_output_directory + "/" + entity_filename + " "

      # Add submodules as next inst_names
      for submodule_inst in logic_i.submodule_instances:
        full_submodule_inst_name = inst_name_i + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
        next_inst_names.add(full_submodule_inst_name)
          
    # Use next insts as current
    inst_names = set(next_inst_names)
  
  return files_txt,top_entity_name


def GET_ABS_SUBMODULE_STAGE_WHEN_USED(submodule_inst_name, inst_name, logic, parser_state, TimingParamsLookupTable):
  # Start at containing logic
  absolute_stage = 0
  curr_submodule_inst_name = submodule_inst_name

  # Stop once at top level
  # DO
  while curr_submodule_inst_name != inst_name:
    curr_container_inst_name = C_TO_LOGIC.GET_CONTAINER_INST(curr_submodule_inst_name)
    curr_container_logic = parser_state.LogicInstLookupTable[curr_container_inst_name]
    containing_timing_params = TimingParamsLookupTable[curr_container_inst_name]
    curr_submodule_inst = curr_submodule_inst_name.replace(curr_container_inst_name+C_TO_LOGIC.SUBMODULE_MARKER,"")
    local_stage_when_used = GET_LOCAL_SUBMODULE_STAGE_WHEN_USED(curr_submodule_inst, curr_container_inst_name, curr_container_logic, parser_state, TimingParamsLookupTable)
    absolute_stage += local_stage_when_used
    
    # Update vars for next iter
    curr_submodule_inst_name = curr_container_inst_name
    
  return absolute_stage
    

def GET_LOCAL_SUBMODULE_STAGE_WHEN_USED(submodule_inst, container_inst_name, container_logic, parser_state, TimingParamsLookupTable): 
  timing_params = TimingParamsLookupTable[container_inst_name]  
  
  pipeline_map = GET_PIPELINE_MAP(container_inst_name, container_logic, parser_state, TimingParamsLookupTable)
  per_stage_time_order = pipeline_map.stage_ordered_submodule_list
  #per_stage_time_order = VHDL.GET_PER_STAGE_LOCAL_TIME_ORDER_SUBMODULE_INSTANCE_NAMES(container_logic, parser_state, TimingParamsLookupTable)
  
  # Find earliest occurance of this submodule inst in per stage order
  earliest_stage = TimingParamsLookupTable[container_inst_name].GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  earliest_match = None
  for stage in per_stage_time_order:
    for c_built_in_inst in per_stage_time_order[stage]:
      if submodule_inst in c_built_in_inst:
        if stage <= earliest_stage:
          earliest_match = c_built_in_inst
          earliest_stage = stage
  
  if earliest_match is None:
    print("What stage when submodule used?", submodule_inst)
    print("per_stage_time_order",per_stage_time_order)
    sys.exit(-1)
    
  return earliest_stage

def GET_ABS_SUBMODULE_STAGE_WHEN_COMPLETE(submodule_inst_name, inst_name, logic, LogicInstLookupTable, TimingParamsLookupTable):
  # Add latency to when sued
  used = GET_ABS_SUBMODULE_STAGE_WHEN_USED(submodule_inst_name, inst_name, logic, parser_state, TimingParamsLookupTable)
  
  return used + TimingParamsLookupTable[submodule_inst_name].GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)

