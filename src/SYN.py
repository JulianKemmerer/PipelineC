#!/usr/bin/env python

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

import C_TO_LOGIC
import VHDL
import SW_LIB
import MODELSIM
import VIVADO
import QUARTUS
import DIAMOND
import OPEN_TOOLS

SYN_TOOL = None # Attempts to figure out from part number
SYN_OUTPUT_DIRECTORY="/home/" + getpass.getuser() + "/pipelinec_syn_output"
DO_SYN_FAIL_SIM = False # Start simulation if synthesis fails

# Welcome to the land of magic numbers
#   "But I think its much worse than you feared" Modest Mouse - I'm Still Here
INF_MHZ = 1000 # Impossible timing goal
SLICE_MOVEMENT_MULT = 2 # 3 is max/best? Multiplier for how explorative to be in moving slices for better timing
MAX_STAGE_ADJUSTMENT = 2 # Uhh 2 should probably be fine? Maybe fixed bug 20 seems whack? 20 is max, best? Each stage of the pipeline will be adjusted at most this many times when searching for best timing
SLICE_EPSILON_MULTIPLIER = 5 # 6.684491979 max/best? # Constant used to determine when slices are equal. Higher=finer grain slicing, lower=similar slices are said to be equal
SLICE_STEPS_BETWEEN_REGS = 3 # Multiplier for how narrow to start off the search for better timing. Higher=More narrow start, Experimentally 2 isn't enough, slices shift <0 , > 1 easily....what?
DELAY_UNIT_MULT = 10.0 # Timing is reported in nanoseconds. Multiplier to convert that time into integer units (nanosecs, tenths, hundreds of nanosecs)



def PART_SET_TOOL(part_str):
  global SYN_TOOL
  if SYN_TOOL is None:
    # Try to guess synthesis tool based on part number
    # Hacky for now...
    if part_str is None:
      print("Need to set part!")
      print('#pragma PART "EP2AGX45CU17I3"')
      sys.exit(-1)
    elif part_str.startswith("xc"):
      SYN_TOOL = VIVADO
    elif part_str.startswith("EP2") or part_str.startswith("10C"):
      SYN_TOOL = QUARTUS
    elif part_str.startswith("LFE5"):
      SYN_TOOL = OPEN_TOOLS  # TODO replace with DIAMOND option
    else:
      SYN_TOOL = DIAMOND
    print("Using",SYN_TOOL.__name__, "synthesizing for part:",part_str)


# These are the parameters that describe how multiple pipelines are timed
class MultiMainTimingParams:
  def __init__(self):
    # Pipeline params
    self.TimingParamsLookupTable = dict()
    # TODO some kind of params for clock crossing

  def REBUILD_FROM_MAINS(self, parser_state):
    # Apply current slices from main funcs 
    # Start from zero clock
    new_TimingParamsLookupTable = dict()
    new_TimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state.LogicInstLookupTable)
    # Then build from mains
    for main_func in parser_state.main_mhz:
      main_func_logic = parser_state.FuncLogicLookupTable[main_func]
      main_func_slices = self.TimingParamsLookupTable[main_func].slices
      new_TimingParamsLookupTable = ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(main_func, main_func_logic, main_func_slices, parser_state, new_TimingParamsLookupTable)
      # TimingParamsLookupTable == None 
      # means these slices go through global code
      if type(new_TimingParamsLookupTable) is not dict:
        print("Can't syn when slicing through globals!")
        return None, None, None, None
    # Use the new params
    self.TimingParamsLookupTable = new_TimingParamsLookupTable
        
  def REBUILD_FROM_MAIN_SLICES(self, slices, main_func, parser_state, do_latency_check=True):
    # Overwrite this main funcs timing params with slices
    self.TimingParamsLookupTable[main_func] = TimingParams(main_func, parser_state.FuncLogicLookupTable[main_func])
    for slice_i in slices:
      self.TimingParamsLookupTable[main_func].ADD_SLICE(slice_i)

    # And rebuild
    self.REBUILD_FROM_MAINS(parser_state)
    
    # Do sanity pipeline map latency based check
    if do_latency_check:
      timing_params = self.TimingParamsLookupTable[main_func]
      total_latency = timing_params.GET_TOTAL_LATENCY(parser_state, self.TimingParamsLookupTable)
      #print "Latency (clocks):",total_latency
      if len(timing_params.slices) != total_latency:
        print("Calculated total latency based on timing params does not match latency from number of slices?")
        print(" current_slices:",slices)
        print(" total_latency",total_latency)
        sys.exit(-1)
  
  def GET_HASH_EXT(self, parser_state):
    # Just hash all the slices #TODO fix to just mains
    top_level_str = ""
    for main_func in sorted(parser_state.main_mhz.keys()):
      timing_params = self.TimingParamsLookupTable[main_func]
      top_level_str += str(timing_params.slices)
    s = top_level_str
    hash_ext = "_" + ((hashlib.md5(s.encode("utf-8")).hexdigest())[0:4]) #4 chars enough?
    return hash_ext

# These are the parameters that describe how a pipeline should be formed
class TimingParams:
  def __init__(self,inst_name, logic):
    self.logic = logic
    self.inst_name = inst_name
    # Slices reach down into submodules and cause them to be > 0 latency
    self.slices = []
    # Sometimes slices are between submodules,
    # This can specify where a stage is artificially started by not allowing submodules to be instantiated even if driven in an early state
    # UNUSED FOR NOW
    #self.submodule_to_start_stage = dict()
    #self.submodule_to_end_stage = dict()
    
    # Cached stuff
    self.calcd_total_latency = None
    self.hash_ext = None
    self.timing_report_stage_range = None
    
    
  def INVALIDATE_CACHE(self):
    self.calcd_total_latency = None
    self.hash_ext = None
    self.timing_report_stage_range = None
    self.cache_slices = None
    
  # I was dumb and used get latency all over
  # mAKE CACHED VERSION
  def GET_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
    # All modules latency is determined by slices right now
    # TODO slices between submodules
    return len(self.slices)
    '''
    # C built in has multiple shared latencies based on where used
    if len(self.logic.submodule_instances) <= 0:
      return len(self.slices)   
    
    if self.calcd_total_latency is None:
      self.calcd_total_latency = self.CALC_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
      
    return self.calcd_total_latency
    
  # Haha why uppercase everywhere ...
  def CALC_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
    # C built in has multiple shared latencies based on where used
    if len(self.logic.submodule_instances) <= 0:
      return len(self.slices)
    
    if TimingParamsLookupTable is None:
      print "Need TimingParamsLookupTable for non raw hdl latency"
      print 0/0
      sys.exit(-1)
      
    pipeline_map = GET_PIPELINE_MAP(self.inst_name, self.logic, parser_state, TimingParamsLookupTable)
    latency = pipeline_map.num_stages - 1
    
    if latency != len(self.slices):
      print "Oh bad latency",latency ,self.slices
      sys.exit(-1)
    
    return latency
  '''
    
  def GET_HASH_EXT(self, TimingParamsLookupTable, parser_state):
    if self.hash_ext is None:
      self.hash_ext = BUILD_HASH_EXT(self.inst_name, self.logic, TimingParamsLookupTable, parser_state)
    
    return self.hash_ext
    
  def ADD_SLICE(self, slice_point):     
    if slice_point > 1.0:
      print("Slice > 1.0?",slice_point)
      sys.exit(-1)
      slice_point = 1.0
    if slice_point < 0.0:
      print("Slice < 0.0?",slice_point)
      print(0/0)
      sys.exit(-1)
      slice_point = 0.0

    if not(slice_point in self.slices):
      self.slices.append(slice_point)
    self.slices = sorted(self.slices)
    self.INVALIDATE_CACHE()
    
    if self.calcd_total_latency is not None:
      print("WTF adding a slice and has latency cache?",self.calcd_total_latency)
      print(0/0)
      sys.exit(-1)
    
  def SET_RAW_HDL_SLICE(self, slice_index, slice_point):
    self.slices[slice_index]=slice_point
    self.slices = sorted(self.slices)
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
    
    

def GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(LogicInstLookupTable): 
  ZeroClockTimingParamsLookupTable = dict()
  for logic_inst_name in LogicInstLookupTable: 
    logic_i = LogicInstLookupTable[logic_inst_name]
    timing_params_i = TimingParams(logic_inst_name, logic_i)
    ZeroClockTimingParamsLookupTable[logic_inst_name] = timing_params_i
  return ZeroClockTimingParamsLookupTable
      

_GET_ZERO_CLK_PIPELINE_MAP_cache = dict()
def GET_ZERO_CLK_PIPELINE_MAP(inst_name, Logic, parser_state, write_files=True):
  key = Logic.func_name
  
  # Try cache
  try:
    rv = _GET_ZERO_CLK_PIPELINE_MAP_cache[key]
    #print "_GET_ZERO_CLK_PIPELINE_MAP_cache",key
    
    # Sanity?
    if rv.logic.func_name != Logic.func_name:
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
  ZeroClockLogicInst2TimingParams = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state.LogicInstLookupTable)
  
  # Get params for this logic
  #print "Logic.func_name",Logic.func_name

  # Get pipeline map
  zero_clk_pipeline_map = GET_PIPELINE_MAP(inst_name, Logic, parser_state, ZeroClockLogicInst2TimingParams)
  
  # Only cache if has delay
  if zero_clk_pipeline_map.logic.delay is not None: 
    _GET_ZERO_CLK_PIPELINE_MAP_cache[key] = zero_clk_pipeline_map
  
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
  if len(logic.submodule_instances) <= 0 and logic.func_name not in parser_state.main_mhz:
    print("DONT USE GET_PIPELINE_MAP ON RAW HDL LOGIC!")
    print(0/0)
    sys.exit(-1)
    
  # FORGIVE ME - never
  print_debug = False #inst_name=="posix_aws_fpga_dma" #False
  bad_inf_loop = False
    
  LogicInstLookupTable = parser_state.LogicInstLookupTable
  timing_params = TimingParamsLookupTable[inst_name]
  est_total_latency = len(timing_params.slices)
  rv = PipelineMap(logic)
  
  # Shouldnt need debug for zero clock? You wish you sad lazy person
  #print_debug = print_debug and (est_total_latency>0)
  
  if print_debug:
    print("==============================Getting pipeline map=======================================")
    print("GET_PIPELINE_MAP:")
    print("inst_name",inst_name)
    print("logic.func_name",logic.func_name)
    #print "logic.submodule_instances:",logic.submodule_instances
  
  # Delay stuff was hacked into here and only works for combinatorial logic
  is_zero_clk = est_total_latency == 0
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
    print("timing_params.slices",timing_params.slices)
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
  max_possible_latency = len(timing_params.slices)
  max_possible_latency_with_extra = len(timing_params.slices) + 2
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
        print("Wire driven ", wire, "<=",wires_driven_by_so_far[wire])
        
    return True
  
  # WHILE LOOP FOR MULTI STAGE/CLK
  while not PIPELINE_DONE():      
    # Print stuff and set debug if obviously wrong
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
                print("What cant do this without delay!")
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
      submodule_level_prepend_text = "  " + " " + " " + "-- SUBMODULE LEVEL " + str(submodule_level) + "\n"
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
      # Sanity check that output is driven in last stage
      my_total_latency = stage_num - 1
      if PIPELINE_DONE() and (my_total_latency!= est_total_latency):
        print("Seems like pipeline is done before or after last stage?") 
        print("inst_name",inst_name, timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state))
        print("est_total_latency",est_total_latency, "calculated total_latency",my_total_latency)
        print("timing_params.slices",timing_params.slices)
        #print "timing_params.submodule_to_start_stage",timing_params.submodule_to_start_stage 
        print(0/0)
        sys.exit(-1)
        print_debug = True
  
  #*************************** End of while loops *****************************************************#
  
  
  
  # Save number of stages using stage number counter
  rv.num_stages = stage_num
  my_total_latency = rv.num_stages - 1
    
  # Sanity check against estimate
  if est_total_latency != my_total_latency:
    print("BUG IN PIPELINE MAP!")
    print("inst_name",inst_name, timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state))
    print("est_total_latency",est_total_latency, "calculated total_latency",my_total_latency)
    print("timing_params.slices5",timing_params.slices)
    #print "timing_params.submodule_to_start_stage",timing_params.submodule_to_start_stage
    sys.exit(-1)
    
    
  return rv
  
def BUILD_HASH_EXT(inst_name, Logic, TimingParamsLookupTable, parser_state):
  # All modules get sliced, not just raw hdl
  # Might even be through submodule markers so would never slice all the way down to raw HDL
  top_level_str = "" # Should be ok to just use slices alone? # Logic.func_name + "_"
  timing_params = TimingParamsLookupTable[inst_name]
  top_level_str += str(timing_params.slices)
  # Top level slices ALONE should uniquely identify a pipeline configuration
  # Dont need to go down into submodules
  s = top_level_str
      
  hash_ext = "_" + ((hashlib.md5(s.encode("utf-8")).hexdigest())[0:4]) #4 chars enough?
    
  return hash_ext
  
# Returns updated TimingParamsLookupTable
# Index of bad slice if sliced through globals, scoo # Passing Afternoon - Iron & Wine
# THIS MUST BE CALLED IN LOOP OF INCREASING SLICES FROM LEFT=>RIGHT
def SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(inst_name, logic, new_slice_pos, parser_state, TimingParamsLookupTable, skip_boundary_slice, write_files=True, rounding_so_fuck_it=False): 
  
  print_debug = False
  
  # Get timing params for this logic
  timing_params = TimingParamsLookupTable[inst_name]
  # Add slice
  timing_params.ADD_SLICE(new_slice_pos)
  slice_index = timing_params.slices.index(new_slice_pos)
  slice_ends_stage = slice_index
  slice_starts_stage = slice_ends_stage + 1
  prev_slice_pos = None
  if len(timing_params.slices) > 1:
    prev_slice_pos = timing_params.slices[slice_index-1]
    
  '''
  # Sanity check if not adding last slice then must be skipping boundary right?
  if slice_index != len(timing_params.slices)-1 and not skip_boundary_slice:
    print "Wtf added old/to left slice",new_slice_pos,"while not skipping boundary?",timing_params.slices
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
  
  # Double check slice
  est_total_latency = len(timing_params.slices)
  
  if print_debug:
    print("SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES", inst_name, new_slice_pos, "write_files",write_files)
  

  # Shouldnt need debug for zero clock?
  print_debug = print_debug and (est_total_latency>0)
  
  # Raw HDL doesnt need further slicing, bottom of hierarchy
  if len(logic.submodule_instances) > 0:
    #print "logic.submodule_instances",logic.submodule_instances
    # Get the zero clock pipeline map for this logic
    zero_clk_pipeline_map = GET_ZERO_CLK_PIPELINE_MAP(inst_name, logic, parser_state)
    total_delay = zero_clk_pipeline_map.zero_clk_max_delay
    epsilon = SLICE_EPSILON(total_delay)
    
    # Sanity?
    if logic.func_name != zero_clk_pipeline_map.logic.func_name:
      print("Zero clk inst name:",zero_clk_pipeline_map.logic.func_name)
      print("Wtf using pipeline map from other func?")
      sys.exit(-1)
    
    # Get the offset as float
    delay_offset_float = new_slice_pos * total_delay
    delay_offset = math.floor(delay_offset_float)
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
      # Prefer not slicing through if submodule starts or ends in this delay unit
      # Unless already sliced there
      did_boundary_slice = False
      '''
      if not skip_boundary_slice:
        # Check for start or end in this delay unit
        starts_this_delay = submodule_inst not in prev_submodule_insts
        ends_this_delay = submodule_inst not in next_submodule_insts
        
        # If starts and ends then round to start or end
        if starts_this_delay and ends_this_delay:
          if delay_offset_decimal < 0.5:
            # Put reg before
            starts_this_delay = True
            ends_this_delay = False
          else:
            # Put reg after
            starts_this_delay = False
            ends_this_delay = True
        
        # Slice boundary?
        if starts_this_delay or ends_this_delay:
          if starts_this_delay:
            if print_debug:
              print submodule_inst, "starts stage", slice_starts_stage
              
            # Might not be able to add if slices are too close...
            did_boundary_slice = timing_params.ADD_SUBMODULE_START_STAGE(submodule_inst, slice_starts_stage)
            
            # If did not do boundary slice then prev slice must have already cut boundary
            if not did_boundary_slice:
              ### Temp return bad slice?
              ##return slice_index
              # Why doesnt this work?
              #pass
              # Cant continue onto non-boundary slice because boundary slice is techncially to the right of current slice and messes up timing?
              # IDK MAN # I Only Wear Blue - Dr. Dog
              if print_debug:
                print "Could not do starting boundary slice index", slice_index
              return slice_index      
                      
          else:
            # This submodule ends this delay
            # Add to list
            if print_debug:
              print submodule_inst, "ends stage", slice_ends_stage
              
            # Might not be able to add if slices are too close...
            did_boundary_slice = timing_params.ADD_SUBMODULE_END_STAGE(submodule_inst, slice_ends_stage)
            
            # If did not do boundary slice then prev slice must have already cut boundary
            if not did_boundary_slice:
              ### Temp return bad slice?
              ##return slice_index
              # Why doesnt this work?
              #pass
              # Cant continue onto non-boundary slice because boundary slice is techncially to the right of current slice and messes up timing?
              # IDK MAN # I Only Wear Blue - Dr. Dog
              if print_debug:
                print "Could not do ending boundary slice index", slice_index
              return slice_index  
            
                              
          # Write into timing params dict - might have been modified
          TimingParamsLookupTable[inst_name] = timing_params
      '''
      
      # Not sliced on boundary then slice through submodule
      if not did_boundary_slice:
        # Slice through submodule
        # Only slice when >= 1 delay unit?
        submodule_func_name = logic.submodule_instances[submodule_inst]
        submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
        containing_logic = logic
        
        submodule_inst_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
        submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
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
  
  
  #print inst_name, "len(timing_params.slices)", len(timing_params.slices)
  
  
  # Check latency here too  
  timing_params = TimingParamsLookupTable[inst_name]
  total_latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  # Check latency calculation
  if est_total_latency != total_latency:
    # This seems to be catching slices that are too close together?
    # WEEEEELLLLLLL
    if rounding_so_fuck_it:
      # Return bad slice
      if print_debug:
        print("Rounding so allowed to fail latency test with bad slice index", slice_index)
      return slice_index
    else:
      print("Not doing dumb global fuckery but still bad slicing?")
      print("inst_name",inst_name)
      print("Did not slice down hierarchy right!?2 est_total_latency",est_total_latency, "calculated total_latency",total_latency)
      print("Adding new slice:2", new_slice_pos)
      print("timing_params.slices2",timing_params.slices)
      sys.exit(-1)
  
  
  
  return TimingParamsLookupTable
  
  
# Returns index of bad slices or working TimingParamsLookupTable
def ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(inst_name, logic, current_slices, parser_state, TimingParamsLookupTable=None, write_files=True, rounding_so_fuck_it=False):
  # Reset to initial timing params if nothing to start with
  if not TimingParamsLookupTable or TimingParamsLookupTable==dict():
    TimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state.LogicInstLookupTable)
  
  # Do slice to main logic for each slice
  for current_slice_i in current_slices:
    #print "  current_slice_i:",current_slice_i
    skip_boundary_slice = False
    TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(inst_name, logic, current_slice_i, parser_state, TimingParamsLookupTable, skip_boundary_slice, write_files,rounding_so_fuck_it)
    # Might be bad slice
    if type(TimingParamsLookupTable) is int:
      return TimingParamsLookupTable
  
  # Sanity check
  if not rounding_so_fuck_it:
    est_total_latency = len(current_slices)
    timing_params = TimingParamsLookupTable[inst_name]
    total_latency_maybe_recalc = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
    total_latency = total_latency_maybe_recalc
      
    if est_total_latency != total_latency:
      print("Did not slice down hierarchy right!? est_total_latency",est_total_latency, "calculated total_latency",total_latency)
      print("current slices:",current_slices)
      print("timing_params.slices",timing_params.slices)   
      sys.exit(-1)
  
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
  else:
    # Sufjan Stevens - Video Game
    print("Add constraints file ext for syn tool",SYN_TOOL.__name__)
    sys.exit(-1)
    
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
      clock_mhz = parser_state.main_mhz[main_func]
      clk_mhz_str = VHDL.CLK_MHZ_STR(clock_mhz)
      clk_name = "clk_" + clk_mhz_str
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
  
def WRITE_FINAL_FILES(multimain_timing_params, parser_state):
  is_final_top = True
  VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top)
  
  # read_vhdl.tcl only for Vivado for now
  if SYN_TOOL is VIVADO:
    # TODO better quartus GUI / tcl scripts support
    # Write read_vhdl.tcl
    tcl = VIVADO.GET_SYN_IMP_AND_REPORT_TIMING_TCL(multimain_timing_params, parser_state)
    rv_lines = []
    for line in tcl.split('\n'):
      if "read_vhdl" in line:
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
    f=open(out_filepath,"w")
    f.write(rv)
    f.close()

def DO_SYN_FROM_TIMING_PARAMS(multimain_timing_params, parser_state):
  # Dont write files if log file exists
  write_files = False

  # Then run syn
  timing_report = SYN_TOOL.SYN_AND_REPORT_TIMING_MULTIMAIN(parser_state, multimain_timing_params)
  if len(timing_report.path_reports) == 0:
    print(timing_report.orig_text)
    print("Using a bad syn log file?")
    sys.exit(-1)
    
  return timing_report
  
# Sweep state for a single pipeline of logic
class LogicSweepState:
  def __init__(self):
    # State about which stage being adjusted?
    self.stage_range = [0] # The current worst path stage estimate from the timing report
    self.working_stage_range = [0] # Temporary stage range to guide adjustments to slices
    # By how much?
    self.slice_step = 0.0
    self.zero_clk_pipeline_map = None #zero_clk_pipeline_map # was deep copy
    
    # States adjusted over time
    self.seen_slices=dict() # dict[main func] = list of above lists
    self.latency_to_best_slices = dict() 
    self.latency_to_best_delay = dict()
    self.stages_adjusted_this_latency = {0 : 0} # stage -> num times adjusted
    
    # These only make sense after re writing fine sweep?
    #self.mhz_to_latency = dict() #dict[mhz] = latency
    #self.mhz_to_slices = dict() # dict[mhz] = slices   
    

# SweepState for the entire multimain top
class SweepState:
  def __init__(self):
    self.multimain_timing_params = None # Current timing params
    self.timing_report = None # Current timing report
    self.fine_grain_sweep = False
    self.curr_main_func = None
    self.func_sweep_state = dict() # dict[main_func_name] = LogicSweepState
    self.timing_params_to_mhz = dict() # dict[multimain_timing_params]=mhz
    
  def SEEN_TIMING_PARAMS(self, multimain_timing_params):
    todo
    
    
def GET_MOST_RECENT_OR_DEFAULT_SWEEP_STATE(parser_state, multimain_timing_params):
  # Try to use cache
  cached_sweep_state = GET_MOST_RECENT_CACHED_SWEEP_STATE()
  sweep_state = None
  if not(cached_sweep_state is None):
    print("Using cached most recent sweep state...")
    sweep_state = cached_sweep_state
  else:
    print("Starting with blank sweep state...")
    sweep_state = SweepState()
    # Set defaults
    sweep_state.multimain_timing_params = multimain_timing_params
    print("...determining slicing information for each main function...")
    for func_name in parser_state.main_mhz:
      func_logic = parser_state.FuncLogicLookupTable[func_name]
      sweep_state.func_sweep_state[func_name] = LogicSweepState()
      # Get get pipeline map of vhdl text module?
      if func_logic.is_vhdl_text_module:
        continue
      # Any instance will do 
      inst_name = list(parser_state.FuncToInstances[func_name])[0]
      sweep_state.func_sweep_state[func_name].zero_clk_pipeline_map = GET_ZERO_CLK_PIPELINE_MAP(inst_name, func_logic, parser_state, write_files=False)
      # Only need slicing if has delay?
      delay = sweep_state.func_sweep_state[func_name].zero_clk_pipeline_map.zero_clk_max_delay
      if delay > 0.0:
        sweep_state.func_sweep_state[func_name].slice_ep = SLICE_EPSILON(delay)
  
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

'''   
def INCREASE_SLICE_STEP(slice_step, state):
  n=99999 # Start from small and go up via lower n
  while True:
    maybe_new_slice_step = 1.0/((SLICE_STEPS_BETWEEN_REGS+1+n)*(state.total_latency+1))
    if maybe_new_slice_step > slice_step:
      return maybe_new_slice_step
    
    n = n - 1
''' 
  
def ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(current_slices, parser_state, sweep_state):
  # Debug?
  print_debug = False
  if print_debug:
    print("Rounding:", current_slices)
  
  total_delay = sweep_state.func_sweep_state[sweep_state.curr_main_func].zero_clk_pipeline_map.zero_clk_max_delay
  epsilon = SLICE_EPSILON(total_delay)
  # OHBOYYEEE
  if sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step is None:
    sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step = epsilon / 2.0
  else:
    sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step = min(epsilon / 2.0, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step)
  working_slices = current_slices[:]
  working_params_dict = None
  seen_bad_slices = []
  bad_slice_or_params = None
  while working_params_dict is None:
    
    
    if print_debug:
      print("Trying slices:", working_slices)
    
    # Try to find next bad slice
    bad_slice_or_params_OLD = bad_slice_or_params
    bad_slice_or_params = ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(sweep_state.curr_main_func, parser_state.FuncLogicLookupTable[sweep_state.curr_main_func], working_slices, parser_state, None, write_files=False, rounding_so_fuck_it=True)
  
    if bad_slice_or_params == bad_slice_or_params_OLD:
      print("Looped working on bad_slice_or_params_OLD",bad_slice_or_params_OLD)
      print("And didn't change?")
      sys.exit(-1)
  
    if type(bad_slice_or_params) is dict:
      # Got timing params dict so good
      working_params_dict = bad_slice_or_params
      break
    else:
      # Got bad slice
      bad_slice = bad_slice_or_params
      
      if print_debug:
        print("Bad slice index:", bad_slice)
      
      # Done too much?
      # If and slice index has been adjusted twice something is wrong and give up
      for slice_index in range(0,len(current_slices)):
        if seen_bad_slices.count(slice_index) >= 2:
          print("current_slices",current_slices)
          print("Wtf? Can't round away from globals?")
          print("TODO: Fix dummy.")
          sys.exit(-1)
          #return None
          print_debug = True # WTF???
      seen_bad_slices.append(bad_slice)
      
      # Get initial slice value
      to_left_val = working_slices[bad_slice]
      to_right_val = working_slices[bad_slice]
      
      # Once go too far we try again with lower slice step
      while (to_left_val > sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step) or (to_right_val < 1.0-sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step):
        ## Push slices to left and right until get working slices
        if (to_left_val > sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step):
          to_left_val = to_left_val - sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
        if (to_right_val < 1.0-sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step):
          to_right_val = to_right_val + sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
        pushed_left_slices = working_slices[:]
        pushed_left_slices[bad_slice] = to_left_val
        pushed_right_slices = working_slices[:]
        pushed_right_slices[bad_slice] = to_right_val
        
        # Sanity sort them? idk wtf
        pushed_left_slices = sorted(pushed_left_slices)
        pushed_right_slices = sorted(pushed_right_slices)
        
        if print_debug:
          print("working_slices",working_slices)
          print("total_delay",total_delay)
          print("sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step",sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step)
          print("pushed_left_slices",pushed_left_slices)
          print("pushed_right_slices",pushed_right_slices)
          
          
        # Try left and right
        left_bad_slice_or_params = ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(sweep_state.curr_main_func, parser_state.FuncLogicLookupTable[sweep_state.curr_main_func], pushed_left_slices, parser_state, None, write_files=False, rounding_so_fuck_it=True)
        right_bad_slice_or_params = ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(sweep_state.curr_main_func, parser_state.FuncLogicLookupTable[sweep_state.curr_main_func], pushed_right_slices, parser_state, None, write_files=False, rounding_so_fuck_it=True)
      
        if (type(left_bad_slice_or_params) is type(0)) and (left_bad_slice_or_params != bad_slice):
          # Got different bad slice, use pushed slices as working
          if print_debug:
            print("bad left slice", left_bad_slice_or_params)
          bad_slice = left_bad_slice_or_params
          working_slices = pushed_left_slices[:]
          break
        elif (type(right_bad_slice_or_params) is type(0)) and (right_bad_slice_or_params != bad_slice):
          # Got different bad slice, use pushed slices as working
          if print_debug:
            print("bad right slice", right_bad_slice_or_params)
          bad_slice = right_bad_slice_or_params
          working_slices = pushed_right_slices[:]
          break
        elif type(left_bad_slice_or_params) is dict:
          # Worked
          working_params_dict = left_bad_slice_or_params
          working_slices = pushed_left_slices[:]
          if print_debug:
            print("Shift to left worked!")
          break
        elif type(right_bad_slice_or_params) is dict:
          # Worked
          working_params_dict = right_bad_slice_or_params
          working_slices = pushed_right_slices[:]
          if print_debug:
            print("Shift to right worked!")
          break
        elif (type(left_bad_slice_or_params) is type(0)) and (type(right_bad_slice_or_params) is type(0)):
          # Slices are still bad, keep pushing
          if print_debug:
            print("Slices are still bad, keep pushing")
            print("left_bad_slice_or_params",left_bad_slice_or_params)
            print("right_bad_slice_or_params",right_bad_slice_or_params)
                        
          #print "WHAT"
          #print left_bad_slice_or_params, right_bad_slice_or_params
          pass
        else:
          print("pushed_left_slices",pushed_left_slices)
          print("pushed_right_slices",pushed_right_slices)
          print("left_bad_slice_or_params",left_bad_slice_or_params)
          print("right_bad_slice_or_params",right_bad_slice_or_params)
          print("WTF?")
          sys.exit(-1)
      
      
  return working_slices

'''
# Returns sweep state
def ADD_ANOTHER_PIPELINE_STAGE(sweep_state, parser_state):
  # Increment latency and get best guess slicing
  sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency = sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency + 1
  
  # Sanity check cant more clocks than delay units
  if sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency >= sweep_state.func_sweep_state[sweep_state.curr_main_func].zero_clk_pipeline_map.zero_clk_max_delay:
    print "Not enough resolution to slice this logic into",sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency,"clocks..."
    print "Increase DELAY_UNIT_MULT?"
    sys.exit(-1)
  
  sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step = 1.0/((SLICE_STEPS_BETWEEN_REGS+1)*(sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency+1))
  print "Starting slice_step:",sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step  
  best_guess_ideal_slices = GET_BEST_GUESS_IDEAL_SLICES(sweep_state.func_sweep_state[sweep_state.curr_main_func])
  print "Best guess slices:", best_guess_ideal_slices
  # Adjust to not slice globals
  print "Adjusting to not slice through global logic..."
  rounded_slices = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(best_guess_ideal_slices, parser_state, sweep_state)
  if rounded_slices is None:
    print "Could not round slices away from globals? Can't add another pipeline stage!"
    sys.exit(-1) 
  print "Starting this latency with: ", rounded_slices
  sweep_state.multimain_timing_params.REBUILD_FROM_MAIN_SLICES(rounded_slices[:], sweep_state.curr_main_func, parser_state)
  
  # Reset adjustments
  for stage in range(0, len(rounded_slices) + 1):
    sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency[stage] = 0

  return state
'''   
    
def GET_DEFAULT_SLICE_ADJUSTMENTS(slices, stage_range, sweep_state, parser_state, multiplier=1, include_bad_changes=True):
  slice_step = sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
  slice_ep = sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep
  min_dist = SLICE_DISTANCE_MIN(sweep_state.func_sweep_state[sweep_state.curr_main_func].zero_clk_pipeline_map.zero_clk_max_delay)
  
  if len(slices) == 0:
    # no possible adjsutmwents
    # Return list with no change
    return [ slices ]
    
  INCLUDE_BAD_CHANGES_TOO = include_bad_changes
  
  # At least 1 slice, get possible changes
  rv = []
  last_stage = len(slices)
  for stage in stage_range:
    if stage == 0:
      # Since there is only one solution to a stage 0 path
      # push slice as far to left as to not be seen change
      n = multiplier

      current_slices = SHIFT_SLICE(slices, 0, 'l', slice_step*n, min_dist)
      if current_slices not in rv:
        rv += [current_slices]
      
      if INCLUDE_BAD_CHANGES_TOO:
        current_slices = SHIFT_SLICE(slices, 0, 'r', slice_step*n, min_dist)
        if current_slices not in rv:
          rv += [current_slices]
            
    elif stage == last_stage:
      # Similar, only one way to fix last stage path so loop until change is unseen
      n = multiplier

      last_index = len(slices)-1
      current_slices = SHIFT_SLICE(slices, last_index, 'r', slice_step*n, min_dist)
      if current_slices not in rv:
        rv += [current_slices]
      
      if INCLUDE_BAD_CHANGES_TOO:
        current_slices = SHIFT_SLICE(slices, last_index, 'l', slice_step*n, min_dist)
        if current_slices not in rv:
          rv += [current_slices]
      
    elif stage > 0:
      # 3 possible changes
      # Right slice to left
      current_slices = SHIFT_SLICE(slices, stage, 'l', slice_step*multiplier, min_dist)
      if current_slices not in rv:
        rv += [current_slices]
      if INCLUDE_BAD_CHANGES_TOO: 
        current_slices = SHIFT_SLICE(slices, stage, 'r', slice_step*multiplier, min_dist)
        if current_slices not in rv:
          rv += [current_slices]
      
      # Left slice to right
      current_slices = SHIFT_SLICE(slices, stage-1, 'r', slice_step*multiplier, min_dist)
      if current_slices not in rv:
        rv += [current_slices]
      if INCLUDE_BAD_CHANGES_TOO:
        current_slices = SHIFT_SLICE(slices, stage-1, 'l', slice_step*multiplier, min_dist)
        if current_slices not in rv:
          rv += [current_slices]

      # BOTH
      current_slices = SHIFT_SLICE(slices, stage, 'l', slice_step*multiplier, min_dist)
      current_slices = SHIFT_SLICE(current_slices, stage-1, 'r', slice_step*multiplier, min_dist)
      if current_slices not in rv:
        rv += [current_slices]
      if INCLUDE_BAD_CHANGES_TOO:
        current_slices = SHIFT_SLICE(slices, stage, 'r', slice_step*multiplier, min_dist)
        current_slices = SHIFT_SLICE(current_slices, stage-1, 'l', slice_step*multiplier, min_dist)
        if current_slices not in rv:
          rv += [current_slices]
      
  
  #print "Rounding slices:",rv
  # Round each possibility away from globals
  rounded_rv = []
  for rv_slices in rv:
    rounded = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(rv_slices, parser_state, sweep_state)
    if rounded is not None:
      rounded_rv.append(rounded)
  
  # Remove duplicates
  rounded_rv  = REMOVE_DUP_SLICES(rounded_rv, epsilon)
      
  return rounded_rv
  
def REMOVE_DUP_SLICES(slices_list, epsilon):
  rv_slices_list = []
  for slices in slices_list:
    dup = False
    for rv_slices in rv_slices_list:
      if SLICES_EQ(slices, rv_slices, epsilon):
        dup = True
    if not dup:
      rv_slices_list.append(slices)
  return rv_slices_list
  
'''
# Each call to SYN_AND_REPORT_TIMING is a new thread
def PARALLEL_SYN_WITH_CURR_MAIN_SLICES_PICK_BEST(sweep_state, parser_state, possible_adjusted_slices):
  NUM_PROCESSES = int(open("num_processes.cfg",'r').readline())
  my_thread_pool = ThreadPool(processes=NUM_PROCESSES)
  inst_name = sweep_state.curr_main_func
  Logic = parser_state.LogicInstLookupTable[inst_name]
  
  # Stage range
  if len(possible_adjusted_slices) <= 0:
    # No adjustments no change in state
    return sweep_state
  
  # Round slices and try again
  print("Rounding slices for syn...")
  old_possible_adjusted_slices = possible_adjusted_slices[:]
  possible_adjusted_slices = []
  for slices in old_possible_adjusted_slices:
    rounded_slices = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(slices, parser_state, sweep_state)
    if rounded_slices not in possible_adjusted_slices:
      possible_adjusted_slices.append(rounded_slices)
  
  print("Slices after rounding:")
  for slices in possible_adjusted_slices: 
    print(slices)
  
  slices_to_multimain_timing_params = dict()
  slices_to_syn_tup = dict()
  slices_to_thread = dict()
  for slices in possible_adjusted_slices:
    do_latency_check=False
    do_get_stage_range=False
    # Make copy of current params to start with
    multimain_timing_params = copy.deepcopy(sweep_state.multimain_timing_params)
    # Rebuild from current main slices
    multimain_timing_params.REBUILD_FROM_MAIN_SLICES(slices, sweep_state.curr_main_func, parser_state, do_latency_check)
    my_async_result = my_thread_pool.apply_async(DO_SYN_FROM_TIMING_PARAMS, (multimain_timing_params, parser_state))
    slices_to_thread[str(slices)] = my_async_result
    slices_to_multimain_timing_params[str(slices)] = multimain_timing_params
    
  # Collect all the results
  for slices in possible_adjusted_slices:
    my_async_result = slices_to_thread[str(slices)]
    print("...Waiting on synthesis for slices:", slices)
    my_syn_tup = my_async_result.get()
    slices_to_syn_tup[str(slices)] = my_syn_tup
  
  
  # Check that each result isnt the same (only makes sense if > 1 elements)
  syn_tups = list(slices_to_syn_tup.values())
  datapath_delays = []
  for syn_tup in syn_tups:
    syn_tup_timing_report = syn_tup
    datapath_delays.append(syn_tup_timing_report.path_delay_ns)
  all_same_delays = len(set(datapath_delays))==1 and len(datapath_delays) > 1
  
  if all_same_delays:
    # Cant pick best
    print("All adjustments yield same result...")
    return sweep_state # was deep copy
  else:
    # Pick the best result
    # Do not allow results that have not changed MHz/delay at all 
    # - we obviously didnt change anything measureable so cant be "best"
    curr_delay = None
    if sweep_state.timing_report is not None:
      curr_delay = sweep_state.timing_report.path_delay_ns # TODO use actual path names?
    best_slices = None
    best_mhz = 0
    best_syn_tup = None
    for slices in possible_adjusted_slices:
      syn_tup = slices_to_syn_tup[str(slices)]
      syn_tup_main_func, syn_tup_stage_range, syn_tup_timing_report = syn_tup
      # Only if Changed Mhz / changed critical path
      if syn_tup_timing_report.path_delay_ns != curr_delay:
        mhz = 1000.0 / syn_tup_timing_report.path_delay_ns
        print(" ", slices, "MHz:", mhz)
        if (mhz > best_mhz) :
          best_mhz = mhz
          best_slices = slices
          best_syn_tup = syn_tup
    if best_mhz == 0:
      print("All adjustments yield same (equal to current) result...")
      return sweep_state # unchanged state, no best ot pick
        
    # Check for tie
    best_tied_slices = []
    for slices in possible_adjusted_slices:
      syn_tup = slices_to_syn_tup[str(slices)]
      syn_tup_main_func, syn_tup_stage_range, syn_tup_timing_report = syn_tup
      mhz = 1000.0 / syn_tup_timing_report.path_delay_ns
      if (mhz == best_mhz) :
        best_tied_slices.append(slices)
    
    # Pick best unseen from tie
    if len(best_tied_slices) > 1:
      # Pick first one not seen
      for best_tied_slice in best_tied_slices:
        syn_tup = slices_to_syn_tup[str(best_tied_slice)]
        syn_tup_main_func, syn_tup_stage_range, syn_tup_timing_report = syn_tup
        mhz = 1000.0 / syn_tup_timing_report.path_delay_ns
        if not SEEN_SLICES(best_tied_slice, sweep_state):
          best_mhz = mhz
          best_slices = best_tied_slice
          best_syn_tup = syn_tup
          break
    
    best_main_func, best_stage_range, best_timing_report = best_syn_tup
    # Update state with return value from best
    rv_state = sweep_state # Was deep copy
    # Did not do stage range above, get now
    rv_state.curr_main_func = best_main_func
    rv_state.timing_report = best_timing_report
    rv_state.multimain_timing_params = slices_to_multimain_timing_params[str(best_slices)]
    rv_state.timing_params_to_mhz[rv_state.multimain_timing_params] = best_mhz
    rv_state.func_sweep_state[rv_state.curr_main_func].stage_range = best_stage_range
    
  
  return rv_state
'''
  
'''
def LOG_SWEEP_STATE(sweep_state, parser_state):
  print "Current main pipeline:", sweep_state.curr_main_func
  print "CURRENT SLICES:", sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices
  print "Slice Step:", sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step  
  logic_delay_percent = sweep_state.timing_report.logic_delay / sweep_state.timing_report.path_delay_ns
  mhz = (1.0 / (sweep_state.timing_report.path_delay_ns / 1000.0)) 
  print "MHz:", mhz
  print "Path delay (ns):",sweep_state.timing_report.path_delay_ns
  print "Logic delay (ns):",sweep_state.timing_report.logic_delay, "(",logic_delay_percent,"%)"
  print "STAGE RANGE:",sweep_state.func_sweep_state[sweep_state.curr_main_func].stage_range
  
  # After syn working stage range is from timing report
  sweep_state.func_sweep_state[sweep_state.curr_main_func].working_stage_range = sweep_state.func_sweep_state[sweep_state.curr_main_func].stage_range[:]
  
  # Print best so far for this latency
  print "Latency (clks):", len(sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices)
  if sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency in sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_slices:
    ideal_slices = sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_slices[sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency]
    best_delay = sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_delay[sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency]
    best_mhz = 1000.0 / best_delay
    print " Best so far: = ", best_mhz, "MHz: ",ideal_slices
  
  # Keep record of ___BEST___ delay and best slices
  if sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency in sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_delay:
    # Is it better?
    if sweep_state.timing_report.path_delay_ns < sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_delay[sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency]:
      sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_delay[sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency] = sweep_state.timing_report.path_delay_ns
      sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_slices[sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency] = sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices[:]
  else:
    # Just add
    sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_delay[sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency] = sweep_state.timing_report.path_delay_ns
    sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_slices[sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency] = sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices[:]
  # RECORD __ALL___ MHZ TO LATENCY AND SLICES
  # Only add if there are no higher Mhz with lower latency already
  # I.e. ignore obviously bad results
  # What the fuck am I talking about?
  do_add = True
  for mhz_i in sorted(sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_latency):
    latency_i = sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_latency[mhz_i]
    if (mhz_i > mhz) and (latency_i < sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency):
      # Found a better result already - dont add this high latency result
      print "Have better result so far (", mhz_i, "Mhz",latency_i, "clks)... not logging this one..."
      do_add = False
      break
  if do_add:
    if mhz in sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_latency:
      if sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency < sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_latency[mhz]:
        sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_latency[mhz] = sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency   
        sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_slices[mhz] = sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices[:]
    else:
      sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_latency[mhz] = sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency
      sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_slices[mhz] = sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices[:]   
      
  # IF GOT BEST RESULT SO FAR
  if mhz >= max(sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_slices) and not SEEN_CURRENT_SLICES(state):
    # Reset stages adjusted since want full exploration
    print "BEST SO FAR! :)"
    print "Resetting stages adjusted this latency since want full exploration..."
    for stage in range(0, len(sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices) + 1):
      sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency[stage] = 0
    
    # Got best, write log files if requested
    #if write_files:
    # wRITE TO LOG
    text = ""
    text += "MHZ  LATENCY SLICES\n"
    for mhz_i in sorted(sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_latency):
      latency = sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_latency[mhz_i]
      slices = sweep_state.func_sweep_state[sweep_state.curr_main_func].mhz_to_slices[mhz_i]
      text += str(mhz_i) + "  " + str(latency) + "  " + str(slices) + "\n"
    #print text
    f=open(SYN_OUTPUT_DIRECTORY + "/" + sweep_state.curr_main_func + "_mhz_to_latency_and_slices.log","w")
    f.write(text)
    f.close()
    
  # Write state
  WRITE_SWEEP_STATE_CACHE_FILE(sweep_state, parser_state)
'''
      

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

def SEEN_SLICES(slices, sweep_state):
  return GET_EQ_SEEN_SLICES(slices, sweep_state) is not None
  
def GET_EQ_SEEN_SLICES(slices, sweep_state):
  # Point of this is to check if we have seen these slices
  # But exact floating point equal is dumb
  # Min floating point that matters is 1 bit of adjsutment
  
  # Check for matching slices in seen slices:
  for slices_i in sweep_state.func_sweep_state[sweep_state.curr_main_func].seen_slices:
    if SLICES_EQ(slices_i, slices, SLICE_EPSILON(sweep_state.func_sweep_state[sweep_state.curr_main_func].zero_clk_pipeline_map.zero_clk_max_delay)):
      return slices_i
      
  return None
  
def ROUND_SLICES_TO_SEEN(slices, sweep_state):
  rv = slices[:]
  equal_seen_slices = GET_EQ_SEEN_SLICES(slices, sweep_state)
  if equal_seen_slices is not None:
    rv =  equal_seen_slices
  return rv
  

def SEEN_CURRENT_SLICES(sweep_state):
  return SEEN_SLICES(sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices, sweep_state)
  
def FILTER_OUT_SEEN_ADJUSTMENTS(possible_adjusted_slices, sweep_state):
  unseen_possible_adjusted_slices = []
  for possible_slices in possible_adjusted_slices:
    if not SEEN_SLICES(possible_slices,sweep_state):
      unseen_possible_adjusted_slices.append(possible_slices)
    else:
      print(" Saw,",possible_slices,"already")
  return unseen_possible_adjusted_slices

def GET_MAIN_FUNCS_FROM_PATH_REPORT(path_report, parser_state):
  main_funcs = set()
  # Include start and end regs in search 
  all_netlist_resources = set(path_report.netlist_resources)
  all_netlist_resources.add(path_report.start_reg_name)
  all_netlist_resources.add(path_report.end_reg_name)
  for netlist_resource in all_netlist_resources:
    toks = netlist_resource.split("/")
    if toks[0] in parser_state.main_mhz:
      main_funcs.add(toks[0])
      
  return main_funcs

# Todo just coarse for now until someone other than me care to squeeze performance?
# Course then fine - knowhaimsayin
def DO_THROUGHPUT_SWEEP(parser_state): #,skip_coarse_sweep=False, skip_fine_sweep=False):
  for main_func in parser_state.main_mhz:
    print("Function:",main_func,"Target MHz:",parser_state.main_mhz[main_func])
  
  # Populate timing lookup table as all 0 clk
  ZeroClockTimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state.LogicInstLookupTable)
  multimain_timing_params = MultiMainTimingParams()
  multimain_timing_params.TimingParamsLookupTable = ZeroClockTimingParamsLookupTable
  
  # Write clock cross entities
  VHDL.WRITE_CLK_CROSS_ENTITIES(parser_state, multimain_timing_params)
    
  # Write multi-main top
  VHDL.WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params)
  
  # Default sweep state is zero clocks
  sweep_state = GET_MOST_RECENT_OR_DEFAULT_SWEEP_STATE(parser_state, multimain_timing_params)
  
  # Maybe skip coarse grain
  #if not sweep_state.fine_grain_sweep and not skip_coarse_sweep:
  sweep_state = DO_COARSE_THROUGHPUT_SWEEP(parser_state, sweep_state)#, skip_fine_sweep)
  
  # Maybe skip fine grain
  #if not skip_fine_sweep:
  # # Then fine grain
  # return DO_FINE_THROUGHPUT_SWEEP(parser_state, sweep_state)
  #else:
  return sweep_state.multimain_timing_params

# Return SWEEP STATE for DO_FINE_THROUGHPUT_SWEEP someday again...
# Of Montreal - The Party's Crashing Us
# Starting guess really only saves 1 extra syn run for dup multimain top
def DO_COARSE_THROUGHPUT_SWEEP(parser_state, sweep_state, do_starting_guess=True, do_incremental_guesses=True): #, skip_fine_sweep=False):
  # Reasonable starting guess and coarse throughput strategy is dividing each main up to meet target
  # Dont even bother running multimain top as combinatorial logic
  main_func_to_coarse_latency = dict()
  for main_func in parser_state.main_mhz:
    main_func_to_coarse_latency[main_func] = 0 # initial guess is 0
    if do_starting_guess:
      main_func_logic = parser_state.FuncLogicLookupTable[main_func]
      target_mhz = parser_state.main_mhz[main_func]
      path_delay_ns = float(main_func_logic.delay) / DELAY_UNIT_MULT
      if path_delay_ns > 0.0:
        curr_mhz = 1000.0 / path_delay_ns
        # How many multiples are we away from the goal
        mult = target_mhz / curr_mhz
        if mult > 1.0:
          # Divide up into that many clocks as a starting guess
          # If doesnt have global wires
          if main_func_logic.CAN_BE_SLICED():
            clks = int(mult) - 1
            main_func_to_coarse_latency[main_func] = clks
      
  # Do loop of:
  #   Reset top to 0 clk
  #   Slice each main evenly based on latency
  #   Syn multimain top
  #   Course adjust func latency
  # until mhz goals met
  last_loop = False
  main_to_last_non_passing_latency = dict()
  main_to_last_latency_increase = dict()
  while True:
    # Reset to zero clock
    sweep_state.multimain_timing_params.TimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state.LogicInstLookupTable)
    
    # Do slicing
    # For each main set the slices in timing params and then rebuild
    done = False
    for main_func in parser_state.main_mhz:
      main_func_logic = parser_state.FuncLogicLookupTable[main_func]
      target_mhz = parser_state.main_mhz[main_func]
      # Sanity check on resolution
      if not main_func_logic.is_vhdl_text_module:
        # Sanity check cant more clocks than delay units
        if main_func_to_coarse_latency[main_func] > sweep_state.func_sweep_state[main_func].zero_clk_pipeline_map.zero_clk_max_delay:
          print("Not enough resolution to slice this logic into",main_func_to_coarse_latency[main_func],"clocks...")
          print("Increase DELAY_UNIT_MULT?")
          sys.exit(-1)
      
      # Make even slices      
      best_guess_slices = GET_BEST_GUESS_IDEAL_SLICES(main_func_to_coarse_latency[main_func])
      # Update slice step
      sweep_state.func_sweep_state[main_func].slice_step = 1.0/((SLICE_STEPS_BETWEEN_REGS+1)*(main_func_to_coarse_latency[main_func]+1))  
      # If making slices then make sure the slices dont go through global logic
      if len(best_guess_slices) > 0:
        #print(" ...rounding away from globals...")
        inst_name = main_func
        sweep_state.curr_main_func = main_func
        best_guess_slices = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(best_guess_slices, parser_state, sweep_state)
        #print(" ...rounded slices:", best_guess_slices)
      print(main_func,":",main_func_to_coarse_latency[main_func],"clocks latency, sliced coarsely...")
      # Do slicing and writing VHDL
      sweep_state.multimain_timing_params.REBUILD_FROM_MAIN_SLICES(best_guess_slices, main_func, parser_state)
    
    # Run syn on multi main top
    sweep_state.timing_report = DO_SYN_FROM_TIMING_PARAMS(sweep_state.multimain_timing_params, parser_state)
    # Did it meet timing?
    fmax = INF_MHZ
    timing_met = len(sweep_state.timing_report.path_reports) > 0
    for clock_group in sweep_state.timing_report.path_reports:
      path_report = sweep_state.timing_report.path_reports[clock_group]
      curr_mhz = 1000.0 / path_report.path_delay_ns
      actual_mhz = 1000.0 / path_report.source_ns_per_clock
      print("Clock Goal (MHz):",actual_mhz,", Current MHz:", curr_mhz, "(", path_report.path_delay_ns, "ns)")
      if curr_mhz < actual_mhz:
        timing_met = False
      if curr_mhz < fmax:
        fmax = curr_mhz
    # Record min mhz as fmax
    sweep_state.timing_params_to_mhz[sweep_state.multimain_timing_params] = fmax
    
    # Last loop?
    if last_loop:
      break
  
    # Passed timing?
    if timing_met:
      # Yes, ok run one more time at last non passing latency
      print("Found maximum pipeline latencies...")
      ## If skipping fine grain then return passing latency now
      #if skip_fine_sweep:
      break 
      ## Prepare for fine sweep
      #print "Resetting state to last non passing run to begin fine grain sweep..."
      #last_loop = True
      #for main_func in parser_state.main_mhz:
      # sweep_state.func_sweep_state[main_func].total_latency = main_to_last_non_passing_latency[main_func]
    else: 
      # And make coarse adjustmant
      print("Making coarse adjustment and trying again...")
      made_adj = False
      # Get timing report info
      # If only one main func then dont need to even read timing report
      # Blegh hacky for now?...
      main_func_to_path_reports = dict()
      if len(parser_state.main_mhz) > 1:
        # Which main funcs show up in timing report?
        for path_report in list(sweep_state.timing_report.path_reports.values()):
          main_funcs = GET_MAIN_FUNCS_FROM_PATH_REPORT(path_report, parser_state)
          for main_func in main_funcs:
            if main_func not in main_func_to_path_reports:
              main_func_to_path_reports[main_func] = []
            main_func_to_path_reports[main_func].append(path_report)
      else:
        main_func_to_path_reports[list(parser_state.main_mhz.keys())[0]] = [list(sweep_state.timing_report.path_reports.values())[0]]
        
      # Make adjustment for each main func
      for main_func in main_func_to_path_reports:
        main_func_logic = parser_state.FuncLogicLookupTable[main_func]
        main_func_path_reports = main_func_to_path_reports[main_func]
        if main_func_logic.CAN_BE_SLICED():
          # DO incremental guesses based on time report results
          if do_incremental_guesses:
            # What max path delay is associated with this func?
            max_path_delay = 0.0
            for path_report in main_func_path_reports:
              if path_report.path_delay_ns > max_path_delay:
                max_path_delay = path_report.path_delay_ns
            # Given current latency for pipeline and stage delay what new total comb logic delay does this imply?
            total_delay = max_path_delay * (main_func_to_coarse_latency[main_func] + 1)
            # How many slices for that delay to meet timing
            target_mhz = parser_state.main_mhz[main_func]
            fake_one_clk_mhz = 1000.0 / total_delay
            mult = target_mhz / fake_one_clk_mhz
            if mult > 1.0:
              # Divide up into that many clocks
              clks = int(mult) - 1
              # If very close to goal suggestion might be same clocks, still increment
              if main_func_to_coarse_latency[main_func] == clks:
                clks += 1
              # Calc diff in latency change, should be getting smaller
              clk_inc = clks - main_func_to_coarse_latency[main_func]
              made_adj = True
              if main_func in main_to_last_latency_increase and clk_inc >= main_to_last_latency_increase[main_func]:
                # Clip to last inc size - 1, minus one to always be narrowing down
                clk_inc = main_to_last_latency_increase[main_func] - 1
                if clk_inc <= 0:
                  clk_inc = 1
                clks = main_func_to_coarse_latency[main_func] + clk_inc
              main_to_last_non_passing_latency[main_func] = main_func_to_coarse_latency[main_func]
              main_func_to_coarse_latency[main_func] = clks
              main_to_last_latency_increase[main_func] = clk_inc
          else:
            # No guess, dumb increment by 1
            # Save non passing latency
            main_to_last_non_passing_latency[main_func] = main_func_to_coarse_latency[main_func]
            main_func_to_coarse_latency[main_func] += 1
            main_to_last_latency_increase[main_func] = 1
            made_adj = True
          
          # Reset adjustments
          for stage in range(0, main_func_to_coarse_latency[main_func] + 1):
            sweep_state.func_sweep_state[main_func].stages_adjusted_this_latency[stage] = 0
              
      # Stuck?
      if not made_adj:
        print("Unable to make further adjustments. Failed to meet timing.")
        # Print some help
        for clock_group in sweep_state.timing_report.path_reports:
          path_report = sweep_state.timing_report.path_reports[clock_group]
          curr_mhz = 1000.0 / path_report.path_delay_ns
          actual_mhz = 1000.0 / path_report.source_ns_per_clock
          if curr_mhz < actual_mhz:
            print("")
            print("Clock Goal (MHz):",actual_mhz,", Current MHz:", curr_mhz)
            print("Problem computation path:")
            print("START: ", path_report.start_reg_name,"=>")
            print(" ~", path_report.path_delay_ns, "ns of logic ~")
            print("END: =>",path_report.end_reg_name) 
        sys.exit(-1)
          
  return sweep_state

'''
def DO_FINE_THROUGHPUT_SWEEP(parser_state, sweep_state):
  # Doing fine grain sweep now
  sweep_state.fine_grain_sweep = True
  LogicInstLookupTable = parser_state.LogicInstLookupTable
  FuncLogicLookupTable = parser_state.FuncLogicLookupTable
  
  # Make adjustments via temp working stage range
  for main_func in parser_state.main_mhz:
    sweep_state.func_sweep_state[main_func].working_stage_range = sweep_state.func_sweep_state[main_func].stage_range[:]
  
  # Begin the loop of synthesizing adjustments to pick best one
  while True:
    print "|||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||"
    print "|||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||" 
    # Are we done now?
    if sweep_state.timing_report.slack_ns >= 0.0:
      print "Design has met timing operating frequency goals."
      # Return current params?
      return sweep_state.multimain_timing_params
    
    # We have a curr_main_func and stage range to work with
    print "Geting default adjustments for pipeline:",sweep_state.curr_main_func
    print "Current slices:", sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices
    print "Working stage range:", sweep_state.func_sweep_state[sweep_state.curr_main_func].working_stage_range
    print "Slice Step:", sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
    
    print "Adjusting based on working stage range:", sweep_state.func_sweep_state[sweep_state.curr_main_func].working_stage_range     
    # Record that we are adjusting stages in the stage range
    #for stage in sweep_state.func_sweep_state[sweep_state.curr_main_func].working_stage_range:
    for stage in sweep_state.func_sweep_state[sweep_state.curr_main_func].stage_range: # Not working range since want to only count adjustments based on syn results
      sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency[stage] += 1

    # Sometimes all possible changes are the same result and best slices will be none
    # Get default set of possible adjustments
    possible_adjusted_slices = GET_DEFAULT_SLICE_ADJUSTMENTS(sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices,sweep_state.func_sweep_state[sweep_state.curr_main_func].working_stage_range, sweep_state, parser_state)
    print "Possible adjustments:"
    for possible_slices in possible_adjusted_slices:
      print " ", possible_slices
    
    # Round slices to nearest if seen before
    new_possible_adjusted_slices = []
    for possible_slices in possible_adjusted_slices:
      new_possible_slices = ROUND_SLICES_TO_SEEN(possible_slices, sweep_state)
      new_possible_adjusted_slices.append(new_possible_slices)
    possible_adjusted_slices = REMOVE_DUP_SLICES(new_possible_adjusted_slices, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep)
    print "Possible adjustments after rounding to seen slices:"
    for possible_slices in possible_adjusted_slices:
      print " ", possible_slices
    
    # Add the current slices result to list
    if not SEEN_CURRENT_SLICES(sweep_state):
      # Only if not seen yet
      sweep_state.func_sweep_state[sweep_state.curr_main_func].seen_slices.append(sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices[:])
    
    print "Running syn for all possible adjustments..."
    sweep_state = PARALLEL_SYN_WITH_CURR_MAIN_SLICES_PICK_BEST(sweep_state, parser_state, possible_adjusted_slices) 


    print "Best result out of possible adjustments:"
    LOG_SWEEP_STATE(sweep_state, parser_state)
    
    
    # Only need to do additional improvement if best of possible adjustments has been seen already
    if not SEEN_CURRENT_TIMING_PARAMS(sweep_state):
      # Not seen before, OK to skip additional adjustment below
      continue      

    # HOW DO WE ADJUST IF DEFAULT BRINGS US SOMEWHERE WEVE BEEN?
    print "Saw best result of possible adjustments... getting different stage range / slice step"
      
    # IF LOOPED BACK TO BEST THEN 
    if SLICES_EQ(sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices, sweep_state.func_sweep_state[sweep_state.curr_main_func].latency_to_best_slices[sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency], sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep) and sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency > 1: # 0 or 1 slice will always loop back to best
      print "Looped back to best result, decreasing slice step to narrow in on best..."
      print "Reducing slice_step..."
      old_slice_step = sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
      sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step = REDUCE_SLICE_STEP(sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step, sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep)
      print "New slice_step:",sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
      if old_slice_step == sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step:
        print "Can't reduce slice step any further..."
        # Do nothing and end up adding pipeline stage
        pass
      else:
        # OK to try and get another set of slices
        continue
      
    # BACKUP PLAN TO AVOID LOOPS
    elif sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency > 0:
      # Check for unadjsuted stages
      # Need difference or just guessing which can go forever
      missing_stages = []
      if min(sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency.values()) != max(sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency.values()):
        print "Checking if all stages have been adjusted..."
        # Find min adjusted count 
        min_adj = 99999999
        for i in range(0, sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency+1):
          adj = sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency[i]
          print "Stage",i,"adjusted:",adj
          if adj < min_adj:
            min_adj = adj
        
        # Get stages matching same minimum 
        for i in range(0, sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency+1):
          adj = sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency[i]
          if adj == min_adj:
            missing_stages.append(i)
      
      # Keep emphasizing suggested slicing changes if other stages have been adjusted too
      actual_min_adj = min(sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency.values())
      # Only continue to adjust this stage range if not currently over the adjustment limit
      stage_range_adjusted_too_much = False
      for stage in sweep_state.func_sweep_state[sweep_state.curr_main_func].stage_range:
        if sweep_state.func_sweep_state[sweep_state.curr_main_func].stages_adjusted_this_latency[stage] >= MAX_STAGE_ADJUSTMENT:
          stage_range_adjusted_too_much = True
          break     
      if (actual_min_adj != 0) and not stage_range_adjusted_too_much:
        print "Multiplying suggested change with limit:",SLICE_MOVEMENT_MULT
        orig_slice_step = sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
        n = 1
        # Dont want to increase slice offset and miss fine grain adjustments
        working_slice_step = sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step 
        # This change needs to produce different slices or we will end up in loop
        orig_slices = sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices[:]
        # Want to increase slice step if all adjustments yield same result
        # That should be the case when we iterate this while loop after running syn
        num_par_syns = 0
        while SLICES_EQ(orig_slices, sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep) and (n <= SLICE_MOVEMENT_MULT):
          # Start with no possible adjustments
          print "Working slice step:",working_slice_step
          print "Multiplier:", n
          # Keep increasing slice step until get non zero length of possible adjustments
          possible_adjusted_slices = GET_DEFAULT_SLICE_ADJUSTMENTS(sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices,sweep_state.func_sweep_state[sweep_state.curr_main_func].stage_range, sweep_state, parser_state, multiplier=1, include_bad_changes=False)
          # Filter out ones seen already
          possible_adjusted_slices = FILTER_OUT_SEEN_ADJUSTMENTS(possible_adjusted_slices, sweep_state)     
              
          if len(possible_adjusted_slices) > 0:
            print "Got some unseen adjusted slices (with working slice step = ", working_slice_step, ")"
            print "Possible adjustments:"
            for possible_slices in possible_adjusted_slices:
              print " ", possible_slices
            print "Picking best out of possible adjusments..."
            sweep_state = PARALLEL_SYN_WITH_CURR_MAIN_SLICES_PICK_BEST(sweep_state, parser_state, possible_adjusted_slices)
            num_par_syns += 1
            

          # Increase WORKING slice step
          n = n + 1
          print "Increasing working slice step, multiplier:", n
          working_slice_step = orig_slice_step * n
          print "New working slice_step:",working_slice_step
          
        # If actually got new slices then continue to next run
        if not SLICES_EQ(orig_slices, sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep):
          print "Got new slices, running with those:", sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices
          print "Increasing slice step based on number of syn attempts:", num_par_syns
          sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step = num_par_syns * sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
          print "New slice_step:",sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
          LOG_SWEEP_STATE(sweep_state, parser_state)
          continue
        else:
          print "Did not get any unseen slices to try?"
          print "Now trying backup check of all stages adjusted equally..."
      
      ##########################################################
      ##########################################################
      
      
      # Allow cutoff if sad
      AM_SAD = (int(open("i_am_sad.cfg",'r').readline()) > 0) and (actual_min_adj > 1)
      if AM_SAD:
        print "I AM SAD"
        # Wait until file reads 0 again
        while len(open("i_am_sad.cfg",'r').readline())==1 and (int(open("i_am_sad.cfg",'r').readline()) > 0):
          pass
      
      # Why do _I_ exist?
      print "Reducing slice_step..."
      sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step = REDUCE_SLICE_STEP(sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step, sweep_state.func_sweep_state[sweep_state.curr_main_func].total_latency, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep)
      print "New slice_step:",sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
      
      # Magical maximum to keep runs out of the weeds?
      if actual_min_adj >= MAX_STAGE_ADJUSTMENT:
        print "Hit limit of",MAX_STAGE_ADJUSTMENT, "for adjusting all stages... moving on..."
        
      elif (len(missing_stages) > 0) and (actual_min_adj < MAX_STAGE_ADJUSTMENT) and not AM_SAD:
        print "These stages have not been adjusted much: <<<<<<<<<<< ", missing_stages
        sweep_state.func_sweep_state[sweep_state.curr_main_func].working_stage_range = missing_stages
        print "New working stage range:",sweep_state.func_sweep_state[sweep_state.curr_main_func].working_stage_range
        EXPAND_UNTIL_SEEN_IN_SYN = True
        if not EXPAND_UNTIL_SEEN_IN_SYN:
          print "So running with working stage range..."
          continue
        else:
          print "<<<<<<<<<<< Expanding missing stages until seen in syn results..."
          local_seen_slices = []
          # Keep expanding those stages until one of them is seen in timing report stage range
          new_stage_range = []
          new_slices = sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices[:]
          found_missing_stages = []
          try_num = 0
          
          while len(found_missing_stages)==0:
            print "<<<<<<<<<<< TRY",try_num
            try_num += 1
            # Do adjustment
            pre_expand_slices = new_slices[:]
            new_slices = EXPAND_STAGES_VIA_ADJ_COUNT(missing_stages, new_slices, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step, sweep_state, SLICE_DISTANCE_MIN(sweep_state.func_sweep_state[sweep_state.curr_main_func].zero_clk_pipeline_map.zero_clk_max_delay))
            
            # If expansion is same as current slices then stop
            if SLICES_EQ(new_slices, pre_expand_slices, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep):
              print "Expansion was same as current? Give up..."
              new_slices = None
              break
              
            seen_new_slices_locally = False
            # Check for matching slices in local seen slices:
            for slices_i in local_seen_slices:
              if SLICES_EQ(slices_i, new_slices, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep):
                seen_new_slices_locally = True
                break
                        
            if SEEN_SLICES(new_slices, sweep_state) or seen_new_slices_locally:
              print "Expanding further, saw these slices already:", new_slices
              continue
              
            print "<<<<<<<<<<< Rounding", new_slices, "away flom globals..."
            pre_round = new_slices[:]
            new_slices = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(new_slices, parser_state, sweep_state)
            
            seen_new_slices_locally = False
            # Check for matching slices in local seen slices:
            for slices_i in local_seen_slices:
              if SLICES_EQ(slices_i, new_slices, sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_ep):
                seen_new_slices_locally = True
                break
            
            if SEEN_SLICES(new_slices, sweep_state) or seen_new_slices_locally:
              print "Expanding further, saw rounded slices:",new_slices
              new_slices = pre_round
              continue        
            
            print "<<<<<<<<<<< Running syn with expanded slices:", new_slices
            
            
            
            # Make copy of current params to start with
            new_multimain_timing_params = copy.deepcopy(sweep_state.multimain_timing_params)
            # Rebuild from current main slices
            new_multimain_timing_params.REBUILD_FROM_MAIN_SLICES(new_slices, sweep_state.curr_main_func, parser_state)
            new_main_func, new_stage_range, new_timing_report = DO_SYN_FROM_TIMING_PARAMS(new_multimain_timing_params, parser_state)
            print "<<<<<<<<<<< Got stage range:",new_stage_range
            for new_stage in new_stage_range:
              if new_stage in missing_stages:
                found_missing_stages.append(new_stage)
                print "<<<<<<<<<<< Has missing stage", new_stage
                
            # Record having seen these slices but keep it local yo
            local_seen_slices.append(new_slices)
            
                
          
          if new_slices is not None:
            print "<<<<<<<<<<< Using adjustment", new_slices, "that resulted in missing stage", found_missing_stages
            sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices = new_slices
            # Then use new main func
            sweep_state.curr_main_func = new_main_func
            sweep_state.timing_report = new_timing_report
            sweep_state.multimain_timing_params = new_multimain_timing_params
            sweep_state.func_sweep_state[sweep_state.curr_main_func].stage_range = new_stage_range  
            
            # Slice step should match the total adjustment that was needed?
            print "<<<<<<<<<<< Slice step should match the total adjustment that was needed (based on num tries)?"
            sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step = try_num * sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
            print "<<<<<<<<<<< Increasing slice step to:", sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step
            LOG_SWEEP_STATE(sweep_state, parser_state)
            continue
          else:
            print "<<<<<<<<<<< Couldnt shrink other stages anymore? No adjustment made..."
          
      else:
        print "Cannot find missing stage adjustment?"       
        
    
    # Result of either unclear or clear sweep_state.func_sweep_state[sweep_state.curr_main_func].stage 
    print "Didn't make any changes?",sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices

    # If seen this config (made no adjsutment) add another pipeline slice
    if SEEN_CURRENT_SLICES(sweep_state):
      print "Saw this slice configuration already. We gave up."
      print "Adding another pipeline stage..."
      sweep_state = ADD_ANOTHER_PIPELINE_STAGE(sweep_state, parser_state)
      # Run syn to get started with this new set of slices
      # Run syn with these slices
      print "Running syn after adding pipeline stage..."
      #print "Current slices:", sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices
      #print "Slice Step:",sweep_state.func_sweep_state[sweep_state.curr_main_func].slice_step          
      new_main_func, new_stage_range, new_timing_report = DO_SYN_FROM_TIMING_PARAMS(new_multimain_timing_params, parser_state)
      sweep_state.curr_main_func = new_main_func
      sweep_state.timing_report = new_timing_report
      sweep_state.func_sweep_state[sweep_state.curr_main_func].stage_range = new_stage_range
      sweep_state.multimain_timing_params = new_multimain_timing_params
      LOG_SWEEP_STATE(sweep_state, parser_state)
    else:
      print "What didnt make change and got new slices?", sweep_state.multimain_timing_params.TimingParamsLookupTable[sweep_state.curr_main_func].slices
      sys.exit(-1)

  sys.exit(-1)

'''

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
  else:
    # Use source file if not built in?
    src_file = str(Logic.c_ast_node.coord.file)
    # hacky catch generated files from output dir already?
    if src_file.startswith(SYN_OUTPUT_DIRECTORY+"/"):
      output_directory = os.path.dirname(src_file)
    else:
      # Otherwise normal
      output_directory = SYN_OUTPUT_DIRECTORY + "/" + src_file + "/" + Logic.func_name
    
  return output_directory
  
def LOGIC_IS_ZERO_DELAY(logic, parser_state):
  if logic.func_name in parser_state.func_marked_wires:
    return True
  elif SW_LIB.IS_BIT_MANIP(logic):
    return True
  elif SW_LIB.IS_CLOCK_CROSSING(logic):
    return True # For now? How to handle paths through clock cross logic?
  elif logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
    return True
  elif logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SL_NAME) or logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SR_NAME):
    return True
  elif logic.is_vhdl_text_module:
    return False # No idea what user has in there
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
  
  user_code = (not logic.is_c_built_in and not SW_LIB.IS_AUTO_GENERATED(logic)) # ???? or (not VHDL.C_TYPES_ARE_INTEGERS(input_types) or (not C_TO_LOGIC.C_TYPES_ARE_BUILT_IN(input_types))
  
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
  PATH_DELAY_CACHE_DIR="./path_delay_cache/" + str(SYN_TOOL.__name__).lower() + "/" + parser_state.part

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
  
  print("Starting with combinatorial logic...")  
  # initial params are 0 clk latency for all submodules
  TimingParamsLookupTable = GET_ZERO_CLK_TIMING_PARAMS_LOOKUP(parser_state.LogicInstLookupTable)
  
  print("Writing VHDL files for all functions (as combinatorial logic)...")
  WRITE_ALL_ZERO_CLK_VHDL(parser_state, TimingParamsLookupTable)
  
  #print "WHY SLO?"
  #sys.exit(-1)

  print("Writing the constant struct+enum definitions as defined from C code...")
  VHDL.WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(parser_state)
  print("Writing clock cross defintions as parsed from C code...")
  VHDL.WRITE_CLK_CROSS_VHDL_PACKAGE(parser_state)
  
  print("Synthesizing as combinatorial logic to get total logic delay...")
  print("")
  
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
          #print "Warning?: No logic instance for function:", logic.func_name, "never used?"
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
      if len(logic.submodule_instances) > 0:
        zero_clk_pipeline_map = GET_ZERO_CLK_PIPELINE_MAP(inst_name, logic, parser_state) # use inst_logic since timing params are by inst
        zero_clk_pipeline_map_str = str(zero_clk_pipeline_map)
        out_dir = GET_OUTPUT_DIRECTORY(logic)
        if not os.path.exists(out_dir):
          os.makedirs(out_dir) 
        out_path = out_dir + "/pipeline_map.log"
        f=open(out_path,'w')
        f.write(zero_clk_pipeline_map_str)
        f.close()
      print("Synthesizing function:",logic.func_name)
      
    # Start parallel syn for parallel_func_names
    # Parallelized
    NUM_PROCESSES = int(open("num_processes.cfg",'r').readline())
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
      # Run Syn
      total_latency=0
      my_async_result = my_thread_pool.apply_async(SYN_TOOL.SYN_AND_REPORT_TIMING, (inst_name, logic, parser_state, TimingParamsLookupTable, total_latency))
      func_name_to_async_result[logic_func_name] = my_async_result
      
    # Finish parallel syn
    for logic_func_name in parallel_func_names:
      # Get logic
      logic = parser_state.FuncLogicLookupTable[logic_func_name]
      # Get result
      my_async_result = func_name_to_async_result[logic_func_name]
      print("...Waiting on synthesis for:", logic_func_name)
      parsed_timing_report =  my_async_result.get()
      # Sanity should be one path reported
      if len(parsed_timing_report.path_reports) > 1:
        print("Too many paths reported!",parsed_timing_report.orig_text)
        sys.exit(-1)
      path_report = list(parsed_timing_report.path_reports.values())[0]
      if path_report.path_delay_ns is None:
        print("Cannot synthesize for path delay ",logic.func_name)
        print(parsed_timing_report.orig_text)
        if DO_SYN_FAIL_SIM:
          MODELSIM.DO_OPTIONAL_DEBUG(do_debug=True)
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
      if SW_LIB.IS_CLOCK_CROSSING(logic):
        continue    
      syn_out_dir = GET_OUTPUT_DIRECTORY(logic)
      if not os.path.exists(syn_out_dir):
        os.makedirs(syn_out_dir)
      print("Writing func",func_name,"...")
      VHDL.WRITE_LOGIC_ENTITY(inst_name, logic, syn_out_dir, parser_state, ZeroClkTimingParamsLookupTable)
      
  # Include a zero clock multi main top too
  print("Writing multi main top level files...")
  multimain_timing_params = MultiMainTimingParams()
  multimain_timing_params.TimingParamsLookupTable = ZeroClkTimingParamsLookupTable;
  is_final_top = True
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
      
  needs_clk_cross_t = not inst_name # is multimain
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
  
  func_name_slices_so_far = set() # of (func_name,slices) tuples
  while len(inst_names) > 0:
    next_inst_names = set()
    for inst_name_i in inst_names:
      logic_i = parser_state.LogicInstLookupTable[inst_name_i]
      # Write file text
      # ONly write non vhdl
      if logic_i.is_vhdl_func or logic_i.is_vhdl_expr or logic_i.func_name == C_TO_LOGIC.VHDL_FUNC_NAME:
        continue
      # Dont write clock cross
      if SW_LIB.IS_CLOCK_CROSSING(logic_i):
        continue
      timing_params_i = multimain_timing_params.TimingParamsLookupTable[inst_name_i]
      func_name_slices = (logic_i.func_name,tuple(timing_params_i.slices))
      if func_name_slices not in func_name_slices_so_far:
        func_name_slices_so_far.add(func_name_slices)
        # Include entity file for this functions slice variant
        entity_filename = VHDL.GET_ENTITY_NAME(inst_name_i, logic_i,multimain_timing_params.TimingParamsLookupTable, parser_state) + ".vhd" 
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
  
def GET_WIRE_NAME_FROM_WRITE_PIPE_VAR_NAME(wire_write_pipe_var_name, logic):
  # Reg name can be wire name or submodule and port
  #print "GET_WIRE_NAME_FROM_WRITE_PIPE_VAR_NAME", wire_reg_name
  # Check for submodule inst in name
  for submodule_inst_name in logic.submodule_instances:
    if C_TO_LOGIC.LEAF_NAME(submodule_inst_name) in wire_write_pipe_var_name:
      # Port name is without inst name
      port_name = wire_write_pipe_var_name.replace(C_TO_LOGIC.LEAF_NAME(submodule_inst_name)+"_", "")
      wire_name = submodule_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + port_name
      return wire_name
      
  # Not a submodule port wire 
  print("GET_WIRE_NAME_FROM_WRITE_PIPE_VAR_NAME Not a submodule port wire ?")
  print("wire_write_pipe_var_name",wire_write_pipe_var_name)
  sys.exit(-1)

'''
# Identify stage range of raw hdl registers in the pipeline
def GET_START_STAGE_END_STAGE_FROM_REGS(inst_name, logic, start_reg_name, end_reg_name, parser_state, TimingParamsLookupTable, parsed_timing_report):
  LogicLookupTable = parser_state.LogicInstLookupTable
  
  # Default smallest range
  timing_params = TimingParamsLookupTable[inst_name]
  start_stage = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  end_stage = 0
  
  DO_WHOLE_PIPELINE = True
  if DO_WHOLE_PIPELINE:
    start_stage = 0
    end_stage = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
    return start_stage, end_stage
  
  if SYN_TOOL.REG_NAME_IS_INPUT_REG(start_reg_name) and SYN_TOOL.REG_NAME_IS_OUTPUT_REG(end_reg_name):
    print " Comb path to and from register in top.vhd"
    # Search entire space (should be 0 clk anyway)
    start_stage = 0
    end_stage = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)  
  elif SYN_TOOL.REG_NAME_IS_INPUT_REG(start_reg_name) and not(SYN_TOOL.REG_NAME_IS_OUTPUT_REG(end_reg_name)):
    print " Comb path from input register in top.vhd to pipeline logic"
    start_stage = 0
  elif not(SYN_TOOL.REG_NAME_IS_INPUT_REG(start_reg_name)) and SYN_TOOL.REG_NAME_IS_OUTPUT_REG(end_reg_name):
    print " Comb path from pipeline logic to output register in top.vhd"
    end_stage = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  else:
    print " Comb path somewhere in the pipeline logic"
    
  print " Taking register merging into account and assuming largest search range based on earliest when used and latest when complete times"
  found_start_stage = None
  if not(SYN_TOOL.REG_NAME_IS_INPUT_REG(start_reg_name)):
    # all possible reg paths considering renaming
    # Start names
    start_names = [start_reg_name]
    start_aliases = []
    if start_reg_name in parsed_timing_report.reg_merged_with:
      start_aliases = parsed_timing_report.reg_merged_with[start_reg_name]
    start_names += start_aliases
    
    start_stages_when_used = []
    for start_name in start_names:
      start_inst = SYN_TOOL.GET_MOST_MATCHING_LOGIC_INST_FROM_REG_NAME(start_name, inst_name, logic, LogicLookupTable)
      when_used = GET_ABS_SUBMODULE_STAGE_WHEN_USED(start_inst, inst_name, logic, parser_state, TimingParamsLookupTable)
      print "   ",start_name
      print "     ",start_inst,"used in absolute stage number:",when_used
      start_stages_when_used.append(when_used)
    found_start_stage = min(start_stages_when_used)
  
  found_end_stage = None
  if not(SYN_TOOL.REG_NAME_IS_OUTPUT_REG(end_reg_name)):
    # all possible reg paths considering renaming
    # End names
    end_names = [end_reg_name]
    end_aliases = []
    if end_reg_name in parsed_timing_report.reg_merged_with:
      end_aliases = parsed_timing_report.reg_merged_with[end_reg_name]
    end_names += end_aliases

    end_stages_when_complete = []
    for end_name in end_names:
      end_inst = SYN_TOOL.GET_MOST_MATCHING_LOGIC_INST_FROM_REG_NAME(end_name, inst_name, logic, LogicLookupTable)
      when_complete = GET_ABS_SUBMODULE_STAGE_WHEN_COMPLETE(end_inst, inst_name, logic, LogicLookupTable, TimingParamsLookupTable)
      print "   ",end_name
      print "     ",end_inst,"completes in absolute stage number:",when_complete
      end_stages_when_complete.append(when_complete)
    found_end_stage = max(end_stages_when_complete)
  
  if not(found_start_stage is None) and (found_start_stage < start_stage):
    start_stage = found_start_stage
  if not(found_end_stage is None) and (found_end_stage > end_stage):
    end_stage = found_end_stage 
  
  # Adjust -1/+1 for start to include comb logic from previous stage
  if start_stage > 0:
    start_stage -= 1
  if end_stage < (timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)-1):
    end_stage += 1
    
  return start_stage, end_stage
  
'''
  

