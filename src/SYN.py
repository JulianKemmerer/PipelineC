#!/usr/bin/env python

import sys
import os
import subprocess
import signal
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

SYN_OUTPUT_DIRECTORY="/home/" + getpass.getuser() + "/pipelinec_syn_output"
PATH_DELAY_CACHE_DIR="./path_delay_cache"
INF_MHZ = 1000 # Impossible timing goal
DO_SYN_FAIL_SIM = False

# Welcome to the land of magic numbers
# 	"But I think its much worse than you feared" Modest Mouse - I'm Still Here
SLICE_MOVEMENT_MULT = 2 # 3 is max/best? Multiplier for how explorative to be in moving slices for better timing
MAX_STAGE_ADJUSTMENT = 4 # 20 is max, best? Each stage of the pipeline will be adjusted at most this many times when searching for best timing
SLICE_EPSILON_MULTIPLIER = 5 # 6.684491979 max/best? # Constant used to determine when slices are equal. Higher=finer grain slicing, lower=similar slices are said to be equal
SLICE_STEPS_BETWEEN_REGS = 3 # Multiplier for how narrow to start off the search for better timing. Higher=More narrow start, Experimentally 2 isn't enough, slices shift <0 , > 1 easily....what?
DELAY_UNIT_MULT = 1.0 # Timing is reported in nanoseconds. Multiplier to convert that time into integer units (nanosecs, tenths, hundreds of nanosecs)

# These are the parameters that describe how a pipeline should be formed
class TimingParams:
	def __init__(self,logic):
		self.logic = logic
		# Slices reach down into submodules and cause them to be > 0 latency
		self.slices = []
		# Sometimes slices are between submodules,
		# This can specify where a stage is artificially started by not allowing submodules to be instantiated even if driven in an early state
		self.submodule_to_start_stage = dict()
		
		# Cached stuff
		self.calcd_total_latency = None
		self.hash_ext = None
		self.timing_report_stage_range = None
		
		
	def INVALIDATE_CACHE(self):
		self.calcd_total_latency = None
		self.hash_ext = None
		self.timing_report_stage_range = None
		self.cache_slices = None
		
	def GET_ABS_STAGE_RANGE_FROM_TIMING_REPORT(self, parsed_timing_report, parser_state, TimingParamsLookupTable):
		if self.timing_report_stage_range is None:
			self.timing_report_stage_range = VIVADO.FIND_ABS_STAGE_RANGE_FROM_TIMING_REPORT(parsed_timing_report, self.logic, parser_state, TimingParamsLookupTable)
		#else:
		#	print "Using cache!"
		return self.timing_report_stage_range
		
	# I was dumb and used get latency all over
	# mAKE CACHED VERSION
	def GET_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None, force_recalc=False):
		#if force_recalc:
		#	print "Dont force_recalc!"
		#	print 0/0
		
		# C built in has multiple shared latencies based on where used
		if len(self.logic.submodule_instances) <= 0:
			return len(self.slices)		
		
		if self.calcd_total_latency is None or force_recalc:
			#if self.logic.inst_name == "main____foo[main_c_l224_c20]____BIN_OP_PLUS[main_c_l210_c15]":
			#	print "RECALC LATENCY!", self.logic.inst_name
			self.calcd_total_latency = self.CALC_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
			#if self.logic.inst_name == "main____foo[main_c_l224_c20]____BIN_OP_PLUS[main_c_l210_c15]":
			#	print "RECALC LATENCY:", self.logic.inst_name, "calcd_total_latency", self.calcd_total_latency
		#else:
		#	if self.logic.inst_name == "main____foo[main_c_l224_c20]____BIN_OP_PLUS[main_c_l210_c15]":
		#		print "Using cache!", self.logic.inst_name, "calcd_total_latency", self.calcd_total_latency
		return self.calcd_total_latency
		
	# Haha why uppercase everywhere ...
	def CALC_TOTAL_LATENCY(self, parser_state, TimingParamsLookupTable=None):
		# C built in has multiple shared latencies based on where used
		if len(self.logic.submodule_instances) <= 0:
			return len(self.slices)
		
		if TimingParamsLookupTable is None:
			print "Need TimingParamsLookupTable for non raw hdl latency"
			print 0/0
			sys.exit(0)
			
		force_pipelinemap_recalc = False
		pipeline_map = GET_PIPELINE_MAP(self.logic, parser_state, TimingParamsLookupTable, force_pipelinemap_recalc)
		latency = pipeline_map.num_stages - 1
		return latency
		
	def GET_HASH_EXT(self, TimingParamsLookupTable, parser_state):
		if self.hash_ext is None:
			self.hash_ext = BUILD_HASH_EXT(self.logic, TimingParamsLookupTable, parser_state)
			#self.cache_slices = self.slices
			
		'''
		lookup_slices = TimingParamsLookupTable[self.logic.inst_name].slices
		if (self.slices != self.cache_slices) or (lookup_slices != self.cache_slices):
			print "Using hash ext that does match cache slices?"
			print "self.slices",self.slices
			print "self.cache_slices",self.cache_slices
			print "lookup_slices",lookup_slices
			print 0/0
			sys.exit(0)
		'''
		
		return self.hash_ext
		
	def ADD_SLICE(self, slice_point):			
		if slice_point > 1.0:
			print "Slice > 1.0?"
			sys.exit(0)
			slice_point = 1.0
		if slice_point < 0.0:
			print "Slice < 0.0?"
			sys.exit(0)
			slice_point = 0.0

		if not(slice_point in self.slices):
			self.slices.append(slice_point)
		self.slices = sorted(self.slices)
		self.INVALIDATE_CACHE()
		
		if self.calcd_total_latency is not None:
			print "WTF adding a slice and has latency cache?",self.calcd_total_latency
			print 0/0
			sys.exit(0)
		
	def SET_RAW_HDL_SLICE(self, slice_index, slice_point):
		self.slices[slice_index]=slice_point
		self.slices = sorted(self.slices)
		self.INVALIDATE_CACHE()
	
	# Returns if add was success
	def ADD_SUBMODULE_START_STAGE(self, start_submodule, start_stage):
		if start_submodule not in self.submodule_to_start_stage:
			self.submodule_to_start_stage[start_submodule] = start_stage
			self.INVALIDATE_CACHE()	
		else:
			if start_stage != self.submodule_to_start_stage[start_submodule]:
				return False # For now
				print "Does submodule", start_submodule, "start in stage",self.submodule_to_start_stage[start_submodule], "or",start_stage, "?"
				print 0/0
				sys.exit(0)
				
		return True
		
	def GET_SUBMODULE_LATENCY(self, submodule_inst_name, parser_state, TimingParamsLookupTable):
		submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
		return submodule_timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
		
		
_GET_ZERO_CLK_PIPELINE_MAP_cache = dict()
def GET_ZERO_CLK_PIPELINE_MAP(Logic, parser_state, write_files=True):
	if Logic.inst_name is None:
		print "Wtf none inst?"
		sys.exit(0)
	key = Logic.inst_name
	if Logic.delay is None:
		print "Can't get zero clock pipeline map without delay?"
		print 0/0 
		sys.exit(0)
	# Try cache
	try:
		rv = _GET_ZERO_CLK_PIPELINE_MAP_cache[key]
		#print "_GET_ZERO_CLK_PIPELINE_MAP_cache",key
		
		# Sanity?
		if rv.logic.inst_name != Logic.inst_name:
			print "Zero clock cache no mactho"
			sys.exit(0)
		
		return rv
	except:
		pass
	
	
	# Populate table as all 0 clk
	ZeroClockLogicInst2TimingParams = dict()
	for logic_inst_name in parser_state.LogicInstLookupTable: 
		logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
		timing_params_i = TimingParams(logic_i)
		ZeroClockLogicInst2TimingParams[logic_inst_name] = timing_params_i
	
	# Get params for this logic
	#print "Logic.inst_name",Logic.inst_name
	#print "Logic.func_name",Logic.func_name
	#zero_clk_timing_params = ZeroClockLogicInst2TimingParams[Logic.inst_name]

	# Get pipeline map
	zero_clk_pipeline_map = GET_PIPELINE_MAP(Logic, parser_state, ZeroClockLogicInst2TimingParams)
	
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
				inst_name = ""
				if self.logic.inst_name is not None:
					inst_name = self.logic.inst_name
				submodule_func_names.append(submodules_inst.replace(inst_name+C_TO_LOGIC.SUBMODULE_MARKER,""))

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
def GET_PIPELINE_MAP(logic, parser_state, TimingParamsLookupTable, force_recalc=False):
	if force_recalc:
		print "Dont force_recalc pipelinemap"
		print 0/0
	
	# RAW HDL doesnt need this
	if len(logic.submodule_instances) <= 0 and logic.func_name != "main":
		print "DONT USE GET_PIPELINE_MAP ON RAW HDL LOGIC!"
		print 0/0
		sys.exit(0)
		
	# FORGIVE ME - never
	print_debug = False #True #logic.inst_name == "main____do_requests[main_c_l30_c11_7ef5]____do_commands[do_requests_c_l173_c28_fd1d]"
	bad_inf_loop = False
		
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	timing_params = TimingParamsLookupTable[logic.inst_name]
	est_total_latency = len(timing_params.slices)
	rv = PipelineMap(logic)
	
	# Shouldnt need debug for zero clock?
	print_debug = print_debug and (est_total_latency>0)
	
	if print_debug:
		print "GET_PIPELINE_MAP:"
		print "logic.func_name",logic.func_name
		print "logic.inst_name",logic.inst_name
	
	# Delay stuff was hacked into here and only works for combinatorial logic
	is_zero_clk = est_total_latency == 0
	has_delay = logic.delay is not None
	is_zero_clk_has_delay = is_zero_clk and has_delay

	if print_debug:
		print "timing_params.slices",timing_params.slices
		
	
	
	if print_debug:
		print "==============================Getting pipline map======================================="


	# Upon writing a submodule do not 
	# add output wire (and driven by output wires) to wires_driven_so_far
	# Intead delay them for N clocks as counted by the clock loop
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
		else:
			driven_wires = [driven_wire_or_wires]
		for driven_wire in driven_wires:
			wires_driven_by_so_far[driven_wire] = driving_wire
	
	# Some wires are driven to start with
	RECORD_DRIVEN_BY(None, logic.inputs)
	RECORD_DRIVEN_BY(None, logic.global_wires)
	RECORD_DRIVEN_BY(None, logic.volatile_global_wires)
	# Keep track of submodules whos inputs are fully driven
	fully_driven_submodule_inst_name_2_logic = dict() 
	
	# Also "CONST" wires representing constants like '2' are already driven
	for wire in logic.wires:
		#print "wire=",wire
		if C_TO_LOGIC.WIRE_IS_CONSTANT(wire, logic.inst_name):
			#print "CONST->",wire
			RECORD_DRIVEN_BY(None, wire)
			wire_to_remaining_clks_before_driven[wire] = 0
	
	# Keep track of delay offset when wire is driven
	# ONLY MAKES SENSE FOR 0 CLK DIRHGT NOW
	delay_offset_when_driven = dict()
	for wire_driven_so_far in wires_driven_by_so_far.keys():
		delay_offset_when_driven[wire_driven_so_far] = 0 # Is per stage value but we know is start of stage 0 
	
	# Start with wires that have drivers
	last_wires_starting_level = None
	wires_starting_level=wires_driven_by_so_far.keys()[:] 
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
					print "Pipeline not done.",output
				return False
			if print_debug:
				print "Output driven ", output, "<=",wires_driven_by_so_far[output]
		# ALl globals driven
		for global_wire in logic.global_wires:
			if (global_wire not in wires_driven_by_so_far) or (wires_driven_by_so_far[global_wire]==None):
				if print_debug:
					print "Pipeline not done.",global_wire
				return False
			if print_debug:
				print "Global driven ", global_wire, "<=",wires_driven_by_so_far[global_wire]
		# ALl globals driven
		# Some volatiles are read only - ex. valid indicator bit
		# And thus are never driven
		# Allow a volatile global wire not to be driven if logic says it is undriven 
		for volatile_global_wire in logic.volatile_global_wires:
			if volatile_global_wire in logic.wire_driven_by:
				# Has a driving wire so must be driven for func to be done
				if (volatile_global_wire not in wires_driven_by_so_far) or (wires_driven_by_so_far[volatile_global_wire]==None):
					if print_debug:
						print "Pipeline not done.",volatile_global_wire
					return False
			if print_debug:
				print "Volatile driven ", volatile_global_wire, "<=",wires_driven_by_so_far[volatile_global_wire]
				
		return True
	
	# WHILE LOOP FOR MULTI STAGE/CLK
	while not PIPELINE_DONE():			
		# Print stuff and set debug if obviously wrong
		if (stage_num >= max_possible_latency_with_extra):
			#print "wires_driven_by_so_far"
			#for wire_i in wires_driven_by_so_far:
			#	print wire_i.replace(logic.inst_name + C_TO_LOGIC.SUBMODULE_MARKER,""), wires_driven_by_so_far[wire_i]
			
			#print "'",logic.outputs[0].replace(logic.inst_name + C_TO_LOGIC.SUBMODULE_MARKER,""),"'NOT in wires_driven_by_so_far"
			#C_TO_LOGIC.PRINT_DRIVER_WIRE_TRACE(logic.outputs[0], logic)	
			print "Something is wrong here, infinite loop probably..."
			print "logic.inst_name", logic.inst_name
			print 0/0
			sys.exit(0)
		elif (stage_num >= max_possible_latency+1):
			bad_inf_loop = True
			print_debug = True
			
		if print_debug:
			print "STAGE NUM =", stage_num

		rv.per_stage_texts[stage_num] = []
		submodule_level = 0
		# DO WHILE LOOP FOR PER COMB LOGIC SUBMODULE LEVELS
		while True: # DO
			submodule_level_text = ""
						
			if print_debug:
				print "SUBMODULE LEVEL",submodule_level
			
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
						print "driving_wire",driving_wire
					
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
							print "driven_wires",driven_wires
							
						# Sort for easy debug
						driven_wires = sorted(driven_wires)
						for driven_wire in driven_wires:
							if bad_inf_loop:
								print "handling driven wire", driven_wire
								
							if not(driven_wire in logic.wire_driven_by):
								# In
								print "!!!!!!!!!!!! DANGLING LOGIC???????",driven_wire, "is not driven!?"
								continue
							#	# This is ok since this dangling logic isnt actually used?
							#	continue
							#	#print "logic.wire_driven_by"
							#	#print logic.wire_driven_by
							#	#print ""fully_driven_submodule_inst_name_2_logic
														
							# Add driven wire to wires driven so far
							# Record driving this wire, at this logic level offset
							if (driven_wire in wires_driven_by_so_far) and (wires_driven_by_so_far[driven_wire] is not None):#  (driven_wire not in logic.global_wires) and (driven_wire not in logic.volatile_global_wires):
								# Already handled this wire
								continue
							RECORD_DRIVEN_BY(driving_wire, driven_wire)
								
							# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
							if is_zero_clk_has_delay:
								delay_offset_when_driven[driven_wire] = delay_offset_when_driven[driving_wire]
							#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~		
							
							# If the driving wire is a submodule output AND LATENCY>0 then RHS uses register style 
							# as way to ensure correct multi clock behavior	
							RHS = VHDL.GET_RHS(driving_wire, logic, parser_state, TimingParamsLookupTable, timing_params, rv.stage_ordered_submodule_list, stage_num)												

							# Submodule or not LHS is write pipe wire
							LHS = VHDL.GET_LHS(driven_wire, logic, parser_state)
							#print "LHS:",LHS							
							#print ""
							
							# Submodules input ports is handled at hierarchy cross later - do nothing here
							if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(driven_wire, logic):
								pass
							else:
								# Record reaching another wire
								next_wires_to_follow.append(driven_wire)	
							
							#print "logic.func_name",logic.func_name
							#print "driving_wire, driven_wire",driving_wire, driven_wire
							# Need VHDL conversions for this type assignment?
							TYPE_RESOLVED_RHS = VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS(RHS, logic, driving_wire, driven_wire, parser_state)
							submodule_level_text += "	" + "	" + "	" + LHS + " := " + TYPE_RESOLVED_RHS + ";" + " -- " + driven_wire + " <= " + driving_wire + "\n"
								
								
				wires_to_follow=next_wires_to_follow[:]
				next_wires_to_follow=[]
			
			
			#########################################################################################
			
			
			
			# \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/ GET FULLY DRIVEN SUBMODULES TO POPULATE SUBMODULE LEVEL \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/ 
			# Have followed this levels wires to submodules
			# We only want to consider the submodules whose inputs have all 
			# been driven by now in clock cycle to keep execution order
			#  	ALSO:
			# 		Slicing between submodules is done via artificially delaying when submodules are instantiated/connected into later stages
			fully_driven_submodule_inst_name_this_level_2_logic = dict()
			# Get submodule logics
			# Loop over each sumodule and check if all inputs are driven
			for submodule_inst_name in logic.submodule_instances:
				
				# Skip submodules weve done already
				already_fully_driven = submodule_inst_name in fully_driven_submodule_inst_name_2_logic
				# Also skip if not the correct stage for this submodule 
				incorrect_stage_for_submodule = False
				if submodule_inst_name in timing_params.submodule_to_start_stage:
					incorrect_stage_for_submodule = stage_num != timing_params.submodule_to_start_stage[submodule_inst_name]
	
				#if print_debug:
				#	print ""
				#	print "########"
				#	print "SUBMODULE INST",submodule_inst_name, "FULLY DRIVEN?:",already_fully_driven
				
				if not already_fully_driven and not incorrect_stage_for_submodule:
					#print submodule_inst_name_2_logic
					submodule_logic = LogicInstLookupTable[submodule_inst_name]
					# Check each input
					submodule_has_all_inputs_driven = True
					submodule_input_port_driving_wires = []
					for input_port_name in submodule_logic.inputs:
						driving_wire = C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(logic, submodule_inst_name,input_port_name)
						submodule_input_port_driving_wires.append(driving_wire)
						if driving_wire not in wires_driven_by_so_far:
							submodule_has_all_inputs_driven = False
							if bad_inf_loop:
								print "!! " + submodule_inst_name + " input wire " + input_port_name
								print " is driven by", driving_wire
								print "  <<<<<<<<<<<<< ", driving_wire , "is not (fully?) driven?"
								print " <<<<<<<<<<<<< YOU ARE PROBABALY NOT DRIVING ALL LOCAL VARIABLES COMPLETELY(STRUCTS) >>>>>>>>>>>> "
								C_TO_LOGIC.PRINT_DRIVER_WIRE_TRACE(driving_wire, logic, wires_driven_by_so_far)
							break
					
					# If all inputs are driven
					if submodule_has_all_inputs_driven: 
						fully_driven_submodule_inst_name_2_logic[submodule_inst_name]=submodule_logic
						fully_driven_submodule_inst_name_this_level_2_logic[submodule_inst_name] = submodule_logic
						if bad_inf_loop:
							print "submodule",submodule_inst_name, "HAS ALL INPUTS DRIVEN"


						# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
						if is_zero_clk_has_delay:
							# Record delay offset as max of driving wires
							# Do zero_clk_submodule_start_offset INPUT OFFSET as max of input wires
							input_port_delay_offsets = []
							for submodule_input_port_driving_wire in submodule_input_port_driving_wires:
								delay_offset = delay_offset_when_driven[submodule_input_port_driving_wire]
								input_port_delay_offsets.append(delay_offset)
							max_input_port_delay_offset = max(input_port_delay_offsets)
							
							# All submodules should be driven at some offset right?
							#print "wires_driven_by_so_far",wires_driven_by_so_far
							#print "delay_offset_when_driven",delay_offset_when_driven
							rv.zero_clk_submodule_start_offset[submodule_inst_name] = max_input_port_delay_offset
							
							
							# Do  delay starting at the input offset
							# This delay_offset_when_driven value wont be used 
							# until the stage when the output wire is read
							# So needs delay expected in last stage
							submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
							submodule_delay = LogicInstLookupTable[submodule_inst_name].delay
							if submodule_delay is None:
								print "What cant do this without delay!"
								sys.exit(0)
							#print "submodule_inst_name",submodule_inst_name
							#print "submodule_delay",submodule_delay
							submodule_latency = submodule_timing_params.GET_TOTAL_LATENCY(parser_state,TimingParamsLookupTable)
							
							
							# Sanity?
							if submodule_latency > 0:
								print "What non zero latency for pipeline map? FIX MEhow? Probably dont fix now since fractional delay dont/cant make sense yet?"
								#HOW TO ALLOCATE delay?
								print 0/0
								sys.exit(0)
							# End offset is start offset plus delay
							# Ex. 0 delay in offset 0 
							# Starts and ends in offset 0
							# Ex. 1 delay unit in offset 0 
							# ALSO STARTS AND ENDS IN STAGE 0
							if submodule_delay > 0:
								abs_delay_end_offset = submodule_delay + rv.zero_clk_submodule_start_offset[submodule_inst_name] - 1
							else:
								abs_delay_end_offset = rv.zero_clk_submodule_start_offset[submodule_inst_name]	
							rv.zero_clk_submodule_end_offset[submodule_inst_name] = abs_delay_end_offset
								
							# Do PARALLEL submodules map with start and end offsets from each stage
							# Dont do for 0 delay submodules, ok fine
							if submodule_delay > 0:
								start_offset = rv.zero_clk_submodule_start_offset[submodule_inst_name]
								end_offset = rv.zero_clk_submodule_end_offset[submodule_inst_name]
								for abs_delay in range(start_offset,end_offset+1):
									if abs_delay < 0:
										print "<0 delay offset?"
										print start_offset,end_offset
										print delay_offset_when_driven
										sys.exit(0)
									# Submodule isnts
									if not(abs_delay in rv.zero_clk_per_delay_submodules_map):
										rv.zero_clk_per_delay_submodules_map[abs_delay] = []
									if not(submodule_inst_name in rv.zero_clk_per_delay_submodules_map[abs_delay]):
										rv.zero_clk_per_delay_submodules_map[abs_delay].append(submodule_inst_name)
										
						# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
						
						
					else:
						# Otherwise save for later
						if bad_inf_loop:
							print "submodule",submodule_inst_name, "does not have all inputs driven yet"
						

			#print "got input driven submodules, wires_driven_by_so_far",wires_driven_by_so_far
			if bad_inf_loop:
				print "fully_driven_submodule_inst_name_this_level_2_logic",fully_driven_submodule_inst_name_this_level_2_logic
			#/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\
			
			# Im dumb
			submodule_level_iteration_has_submodules = len(fully_driven_submodule_inst_name_this_level_2_logic) > 0
					
			############################# GET OUTPUT WIRES FROM SUBMODULE LEVEL #############################################
			# Get list of output wires for this all the submodules in this level
			# by writing submodule connections / entity connections
			submodule_level_output_wires = []
			for submodule_inst_name in fully_driven_submodule_inst_name_this_level_2_logic:
				submodule_logic = LogicInstLookupTable[submodule_inst_name]
				
				# Record this submodule in this stage
				if stage_num not in rv.stage_ordered_submodule_list:
					rv.stage_ordered_submodule_list[stage_num] = []
				if submodule_inst_name not in rv.stage_ordered_submodule_list[stage_num]:
					rv.stage_ordered_submodule_list[stage_num].append(submodule_inst_name)
					
				# Get latency
				submodule_latency_from_container_logic = timing_params.GET_SUBMODULE_LATENCY(submodule_inst_name, parser_state, TimingParamsLookupTable)
				
				# Use submodule logic to write vhdl
				# REGULAR ENTITY CONNECITON
				#print "submodule_inst_name",submodule_inst_name,submodule_latency_from_container_logic
				submodule_level_text += "	" + "	" + "	-- " + C_TO_LOGIC.LEAF_NAME(submodule_inst_name, True) + " LATENCY=" + str(submodule_latency_from_container_logic) +  "\n"
				entity_connection_text = VHDL.GET_ENTITY_CONNECTION_TEXT(submodule_logic,submodule_inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic)			
				submodule_level_text += "	" + "	" + "	" + entity_connection_text + "\n"

				# Add output wires of this submodule to wires driven so far after latency
				for output_wire in submodule_logic.outputs:
					# Construct the name of this wire in the original logic
					submodule_output_wire = output_wire # submodule_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + output_wire
					if bad_inf_loop:
						print "following output",output_wire
					# Add this output port wire on the submodule after the latency of the submodule
					#print "submodule_latencies[",submodule_inst_name, "]==", submodule_latency
					if bad_inf_loop:
						print "submodule_output_wire",submodule_output_wire
					wire_to_remaining_clks_before_driven[submodule_output_wire] = submodule_latency_from_container_logic
			
					# Sanity?
					submodule_timing_params = TimingParamsLookupTable[submodule_inst_name]
					submodule_latency = submodule_timing_params.GET_TOTAL_LATENCY(parser_state,TimingParamsLookupTable)
					if submodule_latency != submodule_latency_from_container_logic:
						print "submodule_latency != submodule_latency_from_container_logic"
						sys.exit(0)
						
					# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
					# Set delay_offset_when_driven for this output wire
					if is_zero_clk_has_delay:
						# Assume zero latency fix me
						if submodule_latency != 0:
							print "non zero submodule latency? fix me"
							sys.exit(0)
						# Set delay offset for this wire
						submodule_delay = LogicInstLookupTable[submodule_inst_name].delay
						abs_delay_offset = rv.zero_clk_submodule_end_offset[submodule_inst_name]
						delay_offset_when_driven[output_wire] = abs_delay_offset
						# ONly +1 if delay > 0
						if submodule_delay > 0:
							delay_offset_when_driven[output_wire] += 1 # "+1" Was seeing stacked parallel submodules where they dont exist
					# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
			####################################################################################################################
		
	
			# END
			# SUBMODULE
			# LEVEL
			# ITERATION
			
			# This ends one submodule level iteration
			# Record text from this iteration
			submodule_level_prepend_text = "	" + "	" + "	" + "-- SUBMODULE LEVEL " + str(submodule_level) + "\n"
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
					print submodule_level_text
					
			# Sometimes submodule levels iterations dont have submodules as we iterate driving wires / for multiple clks
			# Only update counters if was real submodule level with submodules
			if submodule_level_iteration_has_submodules:				
				# Update counters
				submodule_level = submodule_level + 1
			#else:
			#	print "NOT submodule_level_iteration_has_submodules, and that is weird?"
			#	sys.exit(0)
			
			# Wires starting next level include wires whose latency has elapsed just now
			# Also are added to wires driven so far
			# (done per submodule level iteration since ALSO DOES 0 CLK SUBMODULE OUTPUTS)
			wires_starting_level=[]
			for wire in wire_to_remaining_clks_before_driven:
				if wire_to_remaining_clks_before_driven[wire]==0:
					if wire not in wires_driven_by_so_far:
						if bad_inf_loop:
							print "wire remaining clks done, is driven now",wire
						
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
					print "Same wires starting level?"
					print wires_starting_level
					#if print_debug:
					sys.exit(0)
					#print_debug = True
					#sys.exit(0)
				else:				
					last_wires_starting_level = wires_starting_level[:]
			
		# PER CLOCK
		# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ DELAY ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
		if is_zero_clk_has_delay:
			# Get max delay
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
		if len(logic.volatile_global_wires) <= 0:
			# Sanity check that output is driven in last stage
			my_total_latency = stage_num - 1
			if PIPELINE_DONE() and (my_total_latency!= est_total_latency):
				print "Seems like pipeline is done before or after last stage?"	
				print "logic.inst_name",logic.inst_name, timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
				print "est_total_latency",est_total_latency, "calculated total_latency",my_total_latency
				print "timing_params.slices",timing_params.slices
				print 0/0
				sys.exit(0)
				print_debug = True
	
	#*************************** End of while loops *****************************************************#
	
	
	
	# Save number of stages using stage number counter
	rv.num_stages = stage_num
	my_total_latency = rv.num_stages - 1
		
	# Sanity check against estimate
	if est_total_latency != my_total_latency:
		print "BUG IN PIPELINE MAP!"
		print "logic.inst_name",logic.inst_name, timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
		print "est_total_latency",est_total_latency, "calculated total_latency",my_total_latency
		print "timing_params.slices5",timing_params.slices
		#for logic_inst_name in parser_state.LogicInstLookupTable: 
		#	logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
		#	timing_params_i = TimingParams(logic_i)
		#	print "logic_i.inst_name5",logic_i.inst_name, timing_params_i.slices
		
		sys.exit(0)
		
		
	return rv


def GET_SHELL_CMD_OUTPUT(cmd_str):
	# Kill pid after 
	process = subprocess.Popen(cmd_str, shell=True, stdout=subprocess.PIPE)
	output_text = process.stdout.read()
	# For some reason vivado likes to stay alive? Be sure to kill?
	os.kill(process.pid, signal.SIGTERM)
	#print "All vivado dead?"
	#raw_input("")
	return output_text
	
def BUILD_HASH_EXT(Logic, TimingParamsLookupTable, parser_state):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	
	'''
	# Need unique ID for this configuration of submodules, regular submodules use latency as keey
	submodule_names_and_latencies = []
	# Top level starts with just inst name and RAW HDL slices (if applicable)
	top_level_str = Logic.inst_name + "_"
	if len(Logic.submodule_instances) <= 0:
		timing_params = TimingParamsLookupTable[Logic.inst_name]
		top_level_str += str(timing_params.slices) + "_"
	submodule_names_and_latencies.append(top_level_str)
	'''
	# All modules get sliced, not just raw hdl
	# Might even be through submodule markers so would never slice all the way down to raw HDL
	top_level_str = "" # Should be ok to just use slices alone? # Logic.func_name + "_"
	timing_params = TimingParamsLookupTable[Logic.inst_name]
	top_level_str += str(timing_params.slices)
	# Top level slices ALONE should uniquely identify a pipeline configuration
	# Dont need to go down into submodules
	s = top_level_str
	
	'''
	# Fake recurses through every submodule instance
	next_logics = []
	for submodule_inst in Logic.submodule_instances:
		next_logics.append(LogicInstLookupTable[submodule_inst])

	while len(next_logics) > 0:
		new_next_logics = []
		for next_logic in next_logics:
			next_logic_timing_params = TimingParamsLookupTable[next_logic.inst_name]
			
			# Write latency key for this logic
			# If no submodules then is raw HDl and use slices as latency key
			if len(next_logic.submodule_instances) <= 0:
				latency_key = str(next_logic_timing_params.slices)
				submodule_names_and_latencies.append( next_logic.inst_name + "_" + latency_key + "_" )
			else:
				# Has submodules
				# Latency key is just integer				
				latency_key = str(next_logic_timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable))
				submodule_names_and_latencies.append( next_logic.inst_name + "_" + latency_key + "_" )
				
			# Repeat this for each submodule			
			for submodule_inst in next_logic.submodule_instances:
				submodule_logic = LogicInstLookupTable[submodule_inst]
				if submodule_logic not in new_next_logics:
					new_next_logics.append(submodule_logic)						
						
		next_logics = new_next_logics
		
	# Sort list of names and latencies
	unsorted_submodule_names_and_latencies = submodule_names_and_latencies[:]
	submodule_names_and_latencies = sorted(unsorted_submodule_names_and_latencies)
	
	s = ""
	for submodule_name_and_latency in submodule_names_and_latencies:
		s += submodule_name_and_latency
	'''
	
		
	hash_ext = "_" + ((hashlib.md5(s).hexdigest())[0:4]) #4 chars enough?
		
	return hash_ext
	
# Returns updated TimingParamsLookupTable
# Index of bad slice if sliced through globals, scoo # Passing Afternoon - Iron & Wine
def SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(logic, new_slice_pos, parser_state, TimingParamsLookupTable, write_files=True):	
	
	print_debug = False #logic.inst_name == "main____do_requests[main_c_l30_c11_7ef5]____do_commands[do_requests_c_l173_c28_fd1d]" #False
	
	# Sanity?
	if logic.inst_name is None:
		print "Wtf inst name?"
		sys.exit(0)
	
	# Get timing params for this logic
	timing_params = TimingParamsLookupTable[logic.inst_name]
	# Add slice
	timing_params.ADD_SLICE(new_slice_pos)
	slice_index = timing_params.slices.index(new_slice_pos)
	slice_ends_stage = slice_index
	slice_starts_stage = slice_ends_stage + 1
	
	# Write into timing params dict, almost certainly unecessary
	TimingParamsLookupTable[logic.inst_name] = timing_params
	
	# Check for globals
	if logic.uses_globals:
		# Can't slice globals, return index of bad slice
		if print_debug:
			print "Can't slice, uses globals"
		return slice_index
	
	# Double check slice
	est_total_latency = len(timing_params.slices)
	
	if print_debug:
		print "SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES", logic.inst_name, new_slice_pos, "write_files",write_files
	

	# Shouldnt need debug for zero clock?
	print_debug = print_debug and (est_total_latency>0)
	
	# Raw HDL doesnt need further slicing, bottom of hierarchy
	if len(logic.submodule_instances) > 0:
		#print "logic.submodule_instances",logic.submodule_instances
		# Get the zero clock pipeline map for this logic
		zero_clk_pipeline_map = GET_ZERO_CLK_PIPELINE_MAP(logic, parser_state)
		total_delay = zero_clk_pipeline_map.zero_clk_max_delay
		epsilon = SLICE_EPSILON(total_delay)
		
		# Sanity?
		if logic.inst_name != zero_clk_pipeline_map.logic.inst_name:
			print "logic.inst_name",logic.inst_name
			print "Zero clk inst name:",zero_clk_pipeline_map.logic.inst_name
			print "Wtf using pipeline map from other instance?"
			sys.exit(0)
		
		# Get the offset as float
		delay_offset_float = new_slice_pos * total_delay
		delay_offset = math.floor(delay_offset_float)
		delay_offset_decimal = delay_offset_float - delay_offset
		
		# Slice can be through modules or on the boundary between modules
		# The boundary between modules is important for moving slices right up against global logic?
		# I forget exxxxactly why 
		
		# Prefer not slicing through if submodule starts or ends in this delay unit
		# Get submodules at this offset
		submodule_insts = zero_clk_pipeline_map.zero_clk_per_delay_submodules_map[delay_offset]
		# Get submodules in previous and next 
		prev_submodule_insts = []
		if delay_offset - 1 in zero_clk_pipeline_map.zero_clk_per_delay_submodules_map:
			prev_submodule_insts = zero_clk_pipeline_map.zero_clk_per_delay_submodules_map[delay_offset - 1]
		next_submodule_insts = []
		if delay_offset + 1 in zero_clk_pipeline_map.zero_clk_per_delay_submodules_map:
			next_submodule_insts = zero_clk_pipeline_map.zero_clk_per_delay_submodules_map[delay_offset + 1]
		
		# Slice each submodule at offset
		# Record if submodules need to be artifically delayed to start in a later stage
		for submodule_inst in submodule_insts:
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
			
			# Slice via ending stage?
			if starts_this_delay or ends_this_delay:
				if starts_this_delay:
					if print_debug:
						print submodule_inst, "starts stage", slice_starts_stage
					# Might not be able to add if slices are too close... I think that only happens when pushing slices to dodge globals?
					added = timing_params.ADD_SUBMODULE_START_STAGE(submodule_inst, slice_starts_stage)
					if not added:
						return slice_index
				else:
					# This submodule ends this delay
					# Need to find which submodules start in the next delay 
					# Find which submodules are not in current delay but are in next submodule
					added = False
					for next_submodule_inst in next_submodule_insts:
						if next_submodule_inst not in submodule_insts:
							if print_debug:
								print next_submodule_inst, "starts stage", slice_starts_stage
							added = timing_params.ADD_SUBMODULE_START_STAGE(next_submodule_inst, slice_starts_stage)
							# This one catches slices that are too close
							if not added:
								return slice_index
					# This one catches slices at the end of the pipeline with nothing after them
					if not added:
						return slice_index
					
					
				# Write into timing params dict, almost certainly unecessary
				TimingParamsLookupTable[logic.inst_name] = timing_params
			else:
				# Slice through submodule
				# Only slice when >= 1 delay unit?
				submodule_logic = parser_state.LogicInstLookupTable[submodule_inst]
				containing_logic = parser_state.LogicInstLookupTable[submodule_logic.containing_inst]
				#print "SLICING containing_logic.func_name",containing_logic.func_name, containing_logic.uses_globals
					
				submodule_timing_params = TimingParamsLookupTable[submodule_logic.inst_name]
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
					print "	Slicing:", submodule_inst
					print "		@", slice_pos
						
				# Slice into that submodule
				TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(submodule_logic, slice_pos, parser_state, TimingParamsLookupTable, write_files)	
				
				# Might be bad slice
				if type(TimingParamsLookupTable) is int:
					# Slice into submodule was bad
					if print_debug:
						print "Adding slice",slice_pos
						print "To", submodule_inst
						print "Submodule Slice index", TimingParamsLookupTable
						print "Container slice index", slice_index
						print "Was bad"
					# Return the slice in the container that was bad
					return slice_index
				
	
	if write_files:	
		# Final write package
		# Write VHDL file for submodule
		# Re write submodule package with updated timing params
		timing_params = TimingParamsLookupTable[logic.inst_name]
		syn_out_dir = GET_OUTPUT_DIRECTORY(logic)
		if not os.path.exists(syn_out_dir):
			os.makedirs(syn_out_dir)		
		VHDL.WRITE_VHDL_ENTITY(logic, syn_out_dir, parser_state, TimingParamsLookupTable)
	
	
	#print logic.inst_name, "len(timing_params.slices)", len(timing_params.slices)
	
	
	# Check latency here too	
	timing_params = TimingParamsLookupTable[logic.inst_name]
	total_latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	# Check latency calculation
	if est_total_latency != total_latency:
		print "logic.inst_name",logic.inst_name
		print "Did not slice down hierarchy right!?2 est_total_latency",est_total_latency, "calculated total_latency",total_latency
		print "Adding new slice:2", new_slice_pos
		print "timing_params.slices2",timing_params.slices
		#for logic_inst_name in parser_state.LogicInstLookupTable: 
		#	logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
		#	timing_params_i = TimingParams(logic_i)
		#	#print "logic_i.inst_name2",logic_i.inst_name, timing_params_i.slices
		
		sys.exit(0)
	
	
	
	return TimingParamsLookupTable
	
	
# Returns index of bad slices
def GET_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(logic, current_slices, parser_state, write_files=True):	
	#print "GET_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES", logic.inst_name, current_slices, "write_files",write_files
	# Reset to initial timing params before adding slices
	TimingParamsLookupTable = dict()
	for logic_inst_name in parser_state.LogicInstLookupTable: 
		logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
		timing_params_i = TimingParams(logic_i)
		TimingParamsLookupTable[logic_inst_name] = timing_params_i
	
	# Do slice to main logic for each slice
	for current_slice_i in current_slices:
		#print "	current_slice_i:",current_slice_i
		TimingParamsLookupTable = SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(logic, current_slice_i, parser_state, TimingParamsLookupTable, write_files)
		# Might be bad slice
		if type(TimingParamsLookupTable) is int:
			return TimingParamsLookupTable
	
	est_total_latency = len(current_slices)
	timing_params = TimingParamsLookupTable[logic.inst_name]
	total_latency_maybe_recalc = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	
	'''
	# FUCKBUGZ - check for calc errror
	print "TODO: Need bugs check ?"
	force_recalc = True
	total_latency_recalc = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable, force_recalc)
	if total_latency_maybe_recalc != total_latency_recalc:
		print "Wtf the cached latency is wrong!?"
		print "total_latency_maybe_recalc",total_latency_maybe_recalc
		print "total_latency_recalc",total_latency_recalc
		sys.exit(0)
	total_latency = total_latency_recalc	
	'''
	total_latency = total_latency_maybe_recalc
		
	if est_total_latency != total_latency:
		print "Did not slice down hierarchy right!? est_total_latency",est_total_latency, "calculated total_latency",total_latency
		print "current slices:",current_slices
		print "timing_params.slices",timing_params.slices
		for logic_inst_name in parser_state.LogicInstLookupTable: 
			logic_i = parser_state.LogicInstLookupTable[logic_inst_name]
			timing_params_i = TimingParams(logic_i)
			print "logic_i.inst_name",logic_i.inst_name, timing_params_i.slices
		
		sys.exit(0)
	
	return TimingParamsLookupTable
				
				

def DO_SYN_WITH_SLICES(current_slices, Logic, zero_clk_pipeline_map, parser_state, do_latency_check=True, do_get_stage_range=True):
	clock_mhz = INF_MHZ
	total_latency = len(current_slices)
	
	# Dont write files if log file exists
	write_files = False
	log_file_exists = False
	output_directory = GET_OUTPUT_DIRECTORY(Logic)
	TimingParamsLookupTable = GET_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(Logic, current_slices, parser_state, write_files)
	
	# TimingParamsLookupTable == None 
	# means these slices go through global code
	if type(TimingParamsLookupTable) is not dict:
		print "Can't syn when slicing through globals!"
		return None, None, None, None
		#stage_range, timing_report, total_latency, TimingParamsLookupTable	
	
	# Check if log file exists
	timing_params = TimingParamsLookupTable[Logic.inst_name]
	hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)		
	log_path = output_directory + "/vivado" + "_" +  str(total_latency) + "CLK" + hash_ext + ".log"
	log_file_exists = os.path.exists(log_path)
	if not log_file_exists:
		#print "Slicing the RAW HDL submodules..."
		write_files = True
		TimingParamsLookupTable = GET_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(Logic, current_slices, parser_state, write_files)
		
	# Then get main logic timing params
	#print "Recalculating total latency (building pipeline map)..."
	total_latency = len(current_slices)
	timing_params = TimingParamsLookupTable[Logic.inst_name]
	if do_latency_check:
		total_latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
		#print "Latency (clocks):",total_latency
		if len(current_slices) != total_latency:
			print "Calculated total latency based on timing params does not match latency from number of slices?"
			print "	current_slices:",current_slices
			print "	total_latency",total_latency
			sys.exit(0)
	
	# Then run syn
	timing_report = VIVADO.SYN_AND_REPORT_TIMING(Logic, parser_state, TimingParamsLookupTable, clock_mhz, total_latency, hash_ext)
	if timing_report.start_reg_name is None:
		print timing_report.orig_text
		print "Using a bad syn log file?"
		sys.exit(0)
	
	stage_range = None
	if do_get_stage_range:
		stage_range = timing_params.GET_ABS_STAGE_RANGE_FROM_TIMING_REPORT(timing_report, parser_state, TimingParamsLookupTable)
		
	return stage_range, timing_report, total_latency, TimingParamsLookupTable
	

class SweepState:
	def __init__(self, zero_clk_pipeline_map): #, zero_clk_pipeline_map):
		# Slices by default is empty
		self.current_slices = []
		self.seen_slices=[] # list of above lists
		self.mhz_to_latency = dict()
		self.mhz_to_slices = dict()
		self.stage_range = [0] # The current worst path stage estimate from the timing report
		self.working_stage_range = [0] # Temporary stage range to guide adjustments to slices
		self.timing_report = None # Current timing report
		self.total_latency = 0 # Current total latency
		self.latency_2_best_slices = dict() 
		self.latency_2_best_delay = dict()
		self.zero_clk_pipeline_map = zero_clk_pipeline_map # was deep copy
		self.slice_step = 0.0
		self.stages_adjusted_this_latency = {0 : 0} # stage -> num times adjusted
		self.TimingParamsLookupTable = None # Current timing params with current slices
		
		
def GET_MOST_RECENT_OR_DEFAULT_SWEEP_STATE(Logic, zero_clk_pipeline_map):	
	# Try to use cache
	cached_sweep_state = GET_MOST_RECENT_CACHED_SWEEP_STATE(Logic)
	sweep_state = None
	if not(cached_sweep_state is None):
		print "Using cached most recent sweep state..."
		sweep_state = cached_sweep_state
	else:
		print "Starting with blank sweep state..."
		sweep_state = SweepState(zero_clk_pipeline_map)
	
	return sweep_state
	
def GET_MOST_RECENT_CACHED_SWEEP_STATE(Logic):
	output_directory = GET_OUTPUT_DIRECTORY(Logic)
	# Search for most recently modified
	sweep_files = [file for file in glob.glob(os.path.join(output_directory, '*.sweep'))]
	
	if len(sweep_files) > 0 :
		#print "sweep_files",sweep_files
		sweep_files.sort(key=os.path.getmtime)
		print sweep_files[-1] # most recent file
		most_recent_sweep_file = sweep_files[-1]
		
		with open(most_recent_sweep_file, 'rb') as input:
			sweep_state = pickle.load(input)
			return sweep_state
	else:
		return None
	
	
		
def WRITE_SWEEP_STATE_CACHE_FILE(state, Logic):#, LogicInstLookupTable):
	#TimingParamsLookupTable = state.TimingParamsLookupTable
	output_directory = GET_OUTPUT_DIRECTORY(Logic)
	# ONly write one sweep per clk for space sake?
	filename = Logic.inst_name.replace("/","_") + "_" + str(state.total_latency) + "CLK.sweep"
	filepath = output_directory + "/" + filename
	
	# Write dir first if needed
	if not os.path.exists(output_directory):
		os.makedirs(output_directory)
		
	# Write file
	with open(filepath, 'w') as output:
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
		print "WHATATSTDTSTTTS"
		sys.exit(0)
		
		
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
				print "WHATATSTD$$$$TSTTTS"
				sys.exit(0)
			break
	
	
	new_slices.append(new_slice)
	new_slices = sorted(new_slices)
	
	return new_slices
		

	
def GET_BEST_GUESS_IDEAL_SLICES(state):
	# Build ideal slices at this latency
	chunks = state.total_latency+1
	slice_per_chunk = 1.0/chunks
	slice_total = 0
	ideal_slices = []
	for i in range(0,state.total_latency):
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
		
def INCREASE_SLICE_STEP(slice_step, state):
	n=99999 # Start from small and go up via lower n
	while True:
		maybe_new_slice_step = 1.0/((SLICE_STEPS_BETWEEN_REGS+1+n)*(state.total_latency+1))
		if maybe_new_slice_step > slice_step:
			return maybe_new_slice_step
		
		n = n - 1
	
	
def ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(logic, current_slices, slice_step, parser_state, zero_clk_pipeline_map):
	#print "Rounding:", current_slices
	
	total_delay = zero_clk_pipeline_map.zero_clk_max_delay
	epsilon = SLICE_EPSILON(total_delay)
	slice_step = epsilon / 2.0
	working_slices = current_slices[:]
	working_params_dict = None
	seen_bad_slices = []
	min_dist = SLICE_DISTANCE_MIN(total_delay)
	bad_slice_or_params = None
	while working_params_dict is None:
		# Debug?
		print_debug = False
		
		if print_debug:
			print "Trying slices:", working_slices
		
		# Try to find next bad slice
		bad_slice_or_params_OLD = bad_slice_or_params
		bad_slice_or_params = GET_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(logic, working_slices, parser_state, write_files=False)
	
		if bad_slice_or_params == bad_slice_or_params_OLD:
			print "Looped working on bad_slice_or_params_OLD",bad_slice_or_params_OLD
			print "And didn't change?"
			sys.exit(0)
	
		if type(bad_slice_or_params) is dict:
			# Got timing params dict so good
			working_params_dict = bad_slice_or_params
			break
		else:
			# Got bad slice
			bad_slice = bad_slice_or_params
			
			if print_debug:
				print "Bad slice index:", bad_slice
			
			# Done too much?
			# If and slice index has been adjusted twice something is wrong and give up
			for slice_index in range(0,len(current_slices)):
				if seen_bad_slices.count(slice_index) >= 2:
					print "current_slices",current_slices
					print "Wtf? Can't round away from globals?"
					print "TODO: Fix dummy."
					sys.exit(0)
					#return None
					print_debug = True # WTF???

			seen_bad_slices.append(bad_slice)
			
			
			# Get initial slice value
			to_left_val = working_slices[bad_slice]
			to_right_val = working_slices[bad_slice]
			
			# Once go too far we try again with lower slice step
			while (to_left_val > slice_step) or (to_right_val < 1.0-slice_step):
				## Push slices to left and right until get working slices
				#pushed_left_slices = SHIFT_SLICE(working_slices, bad_slice, 'l', slice_step, min_dist)
				#pushed_right_slices = SHIFT_SLICE(working_slices, bad_slice, 'r', slice_step, min_dist)
				if (to_left_val > slice_step):
					to_left_val = to_left_val - slice_step
				if (to_right_val < 1.0-slice_step):
					to_right_val = to_right_val + slice_step
				pushed_left_slices = working_slices[:]
				pushed_left_slices[bad_slice] = to_left_val
				pushed_right_slices = working_slices[:]
				pushed_right_slices[bad_slice] = to_right_val
				
				# Sanity sort them? idk wtf
				pushed_left_slices = sorted(pushed_left_slices)
				pushed_right_slices = sorted(pushed_right_slices)
				
				if print_debug:
					print "working_slices",working_slices
					print "total_delay",total_delay
					print "epsilon",epsilon
					print "min_dist",min_dist
					print "pushed_left_slices",pushed_left_slices
					print "pushed_right_slices",pushed_right_slices
					
					
				# Try left and right
				left_bad_slice_or_params = GET_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(logic, pushed_left_slices, parser_state, write_files=False)
				right_bad_slice_or_params = GET_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(logic, pushed_right_slices, parser_state, write_files=False)
			
				if (type(left_bad_slice_or_params) is type(0)) and (left_bad_slice_or_params != bad_slice):
					# Got different bad slice, use pushed slices as working
					if print_debug:
						print "bad left slice", left_bad_slice_or_params
					bad_slice = left_bad_slice_or_params
					working_slices = pushed_left_slices[:]
					break
				elif (type(right_bad_slice_or_params) is type(0)) and (right_bad_slice_or_params != bad_slice):
					# Got different bad slice, use pushed slices as working
					if print_debug:
						print "bad right slice", right_bad_slice_or_params
					bad_slice = right_bad_slice_or_params
					working_slices = pushed_right_slices[:]
					break
				elif type(left_bad_slice_or_params) is dict:
					# Worked
					working_params_dict = left_bad_slice_or_params
					working_slices = pushed_left_slices[:]
					if print_debug:
						print "Shift to left worked!"
					break
				elif type(right_bad_slice_or_params) is dict:
					# Worked
					working_params_dict = right_bad_slice_or_params
					working_slices = pushed_right_slices[:]
					if print_debug:
						print "Shift to right worked!"
					break
				elif (type(left_bad_slice_or_params) is type(0)) and (type(right_bad_slice_or_params) is type(0)):
					# Slices are still bad, keep pushing
					if print_debug:
						print "Slices are still bad, keep pushing"
						print "left_bad_slice_or_params",left_bad_slice_or_params
						print "right_bad_slice_or_params",right_bad_slice_or_params
												
					#print "WHAT"
					#print left_bad_slice_or_params, right_bad_slice_or_params
					pass
				else:
					print "pushed_left_slices",pushed_left_slices
					print "pushed_right_slices",pushed_right_slices
					print "left_bad_slice_or_params",left_bad_slice_or_params
					print "right_bad_slice_or_params",right_bad_slice_or_params
					print "WTF?"
					sys.exit(0)
			
			
	return working_slices
	
# Returns sweep state
def ADD_ANOTHER_PIPELINE_STAGE(logic, state, parser_state):
	# Increment latency and get best guess slicing
	state.total_latency = state.total_latency + 1
	state.slice_step = 1.0/((SLICE_STEPS_BETWEEN_REGS+1)*(state.total_latency+1))
	print "Starting slice_step:",state.slice_step	
	best_guess_ideal_slices = GET_BEST_GUESS_IDEAL_SLICES(state)
	print "Best guess slices:", best_guess_ideal_slices
	# Adjust to not slice globals
	print "Adjusting to not slice through global logic..."
	rounded_slices = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(logic, best_guess_ideal_slices, state.slice_step, parser_state, state.zero_clk_pipeline_map)
	if rounded_slices is None:
		print "Could not round slices away from globals? Can't add another pipeline stage!"
		sys.exit(0)	
	print "Starting this latency with: ", rounded_slices
	state.current_slices = rounded_slices[:]
	
	
	# Reset adjustments
	for stage in range(0, len(state.current_slices) + 1):
		state.stages_adjusted_this_latency[stage] = 0

	return state
		
		
def GET_DEFAULT_SLICE_ADJUSTMENTS(logic, slices, stage_range, parser_state, zero_clk_pipeline_map, slice_step, epsilon, min_dist, multiplier=1, include_bad_changes=True):
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
		rounded = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(logic, rv_slices, slice_step, parser_state, zero_clk_pipeline_map)
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
	
# Each call to SYN_AND_REPORT_TIMING is a new thread
def PARALLEL_SYN_WITH_SLICES_PICK_BEST(Logic, state, parser_state, possible_adjusted_slices):
	clock_mhz = INF_MHZ
	implement = False
	
	NUM_PROCESSES = int(open("num_processes.cfg",'r').readline())
	
	my_thread_pool = ThreadPool(processes=NUM_PROCESSES)
	
	# Stage range
	if len(possible_adjusted_slices) <= 0:
		# No adjustments no change in state
		return state
	
		
	# Round slices and try again
	print "Rounding slices for syn..."
	old_possible_adjusted_slices = possible_adjusted_slices[:]
	possible_adjusted_slices = []
	for slices in old_possible_adjusted_slices:
		rounded_slices = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(Logic, slices, state.slice_step, parser_state, state.zero_clk_pipeline_map)
		if rounded_slices not in possible_adjusted_slices:
			possible_adjusted_slices.append(rounded_slices)
	
	print "Slices after rounding:"
	for slices in possible_adjusted_slices: 
		print slices
	
	slices_to_syn_tup = dict()
	if NUM_PROCESSES > 1:
		slices_to_thread = dict()
		for slices in possible_adjusted_slices:
			do_latency_check=False
			do_get_stage_range=False
			my_async_result = my_thread_pool.apply_async(DO_SYN_WITH_SLICES, (slices, Logic, state.zero_clk_pipeline_map, parser_state, do_latency_check, do_get_stage_range))
			slices_to_thread[str(slices)] = my_async_result
			
		# Collect all the results
		for slices in possible_adjusted_slices:
			my_async_result = slices_to_thread[str(slices)]
			print "...Waiting on synthesis for slices:", slices
			my_syn_tup = my_async_result.get()
			slices_to_syn_tup[str(slices)] = my_syn_tup
	else:
		for slices in possible_adjusted_slices:
			do_latency_check=False
			do_get_stage_range=False
			my_syn_tup = DO_SYN_WITH_SLICES(slices, Logic, state.zero_clk_pipeline_map, parser_state, do_latency_check, do_get_stage_range)
			slices_to_syn_tup[str(slices)] = my_syn_tup
	
	# Check that each result isnt the same (only makes sense if > 1 elements)
	syn_tups = slices_to_syn_tup.values()
	datapath_delays = []
	for syn_tup in syn_tups:
		datapath_delays.append(syn_tup[1].path_delay)
	all_same_delays = len(set(datapath_delays))==1 and len(datapath_delays) > 1
	
	if all_same_delays:
		# Cant pick best
		print "All adjustments yield same result..."
		return state # was deep copy
	else:
		# Pick the best result
		# Do not allow results that have not changed MHz/delay at all 
		# - we obviously didnt change anything measureable so cant be "best"
		curr_delay = None
		if state.timing_report is not None:
			curr_delay = state.timing_report.path_delay # TODO use actual path names?
		best_slices = None
		best_mhz = 0
		best_syn_tup = None
		for slices in possible_adjusted_slices:
			syn_tup = slices_to_syn_tup[str(slices)]
			timing_report = syn_tup[1]
			# Only if Changed Mhz / changed critical path
			if timing_report.path_delay != curr_delay:
				mhz = 1000.0 / timing_report.path_delay
				print "	", slices, "MHz:", mhz
				if (mhz > best_mhz) :
					best_mhz = mhz
					best_slices = slices
					best_syn_tup = syn_tup
		if best_mhz == 0:
			print "All adjustments yield same (equal to current) result..."
			return state # unchanged state, no best ot pick
				
		# Check for tie
		best_tied_slices = []
		for slices in possible_adjusted_slices:
			syn_tup = slices_to_syn_tup[str(slices)]
			timing_report = syn_tup[1]
			mhz = (1.0 / (timing_report.path_delay / 1000.0)) 
			if (mhz == best_mhz) :
				best_tied_slices.append(slices)
		
		# Pick best unseen from tie
		if len(best_tied_slices) > 1:
			# Pick first one not seen
			for best_tied_slice in best_tied_slices:
				syn_tup = slices_to_syn_tup[str(best_tied_slice)]
				timing_report = syn_tup[1]
				mhz = 1000.0 / timing_report.path_delay
				if not SEEN_SLICES(best_tied_slice, state):
					best_mhz = mhz
					best_slices = best_tied_slice
					best_syn_tup = syn_tup
					break
		
		# Update state with return value from best
		rv_state = state # Was deep copy
		# Did not do stage range above, get now
		rv_state.timing_report = best_syn_tup[1]
		rv_state.TimingParamsLookupTable = best_syn_tup[3]
		best_timing_params = rv_state.TimingParamsLookupTable[Logic.inst_name]
		rv_state.total_latency = best_timing_params.GET_TOTAL_LATENCY(parser_state, rv_state.TimingParamsLookupTable)
		rv_state.stage_range = best_timing_params.GET_ABS_STAGE_RANGE_FROM_TIMING_REPORT(rv_state.timing_report, parser_state, rv_state.TimingParamsLookupTable)
		rv_state.current_slices = best_slices
	
	return rv_state
	
	
def LOG_SWEEP_STATE(state, Logic): #, write_files = False):
	# Record the new delay
	print "CURRENT SLICES:", state.current_slices
	print "Slice Step:", state.slice_step	
	logic_delay_percent = state.timing_report.logic_delay / state.timing_report.path_delay
	mhz = (1.0 / (state.timing_report.path_delay / 1000.0)) 
	print "MHz:", mhz
	print "Path delay (ns):",state.timing_report.path_delay
	print "Logic delay (ns):",state.timing_report.logic_delay, "(",logic_delay_percent,"%)"
	print "STAGE RANGE:",state.stage_range
	
	# After syn working stage range is from timing report
	state.working_stage_range = state.stage_range[:]
	
	# Print best so far for this latency
	print "Latency (clks):", state.total_latency
	if state.total_latency in state.latency_2_best_slices:
		ideal_slices = state.latency_2_best_slices[state.total_latency]
		best_delay = state.latency_2_best_delay[state.total_latency]
		best_mhz = 1000.0 / best_delay
		print "	Best so far: = ", best_mhz, "MHz:	",ideal_slices
	
	# Keep record of ___BEST___ delay and best slices
	if state.total_latency in state.latency_2_best_delay:
		# Is it better?
		if state.timing_report.path_delay < state.latency_2_best_delay[state.total_latency]:
			state.latency_2_best_delay[state.total_latency] = state.timing_report.path_delay
			state.latency_2_best_slices[state.total_latency] = state.current_slices[:]
	else:
		# Just add
		state.latency_2_best_delay[state.total_latency] = state.timing_report.path_delay
		state.latency_2_best_slices[state.total_latency] = state.current_slices[:]
	# RECORD __ALL___ MHZ TO LATENCY AND SLICES
	# Only add if there are no higher Mhz with lower latency already
	# I.e. ignore obviously bad results
	# What the fuck am I talking about?
	do_add = True
	for mhz_i in sorted(state.mhz_to_latency):
		latency_i = state.mhz_to_latency[mhz_i]
		if (mhz_i > mhz) and (latency_i < state.total_latency):
			# Found a better result already - dont add this high latency result
			print "Have better result so far (", mhz_i, "Mhz",latency_i, "clks)... not logging this one..."
			do_add = False
			break
	if do_add:
		if mhz in state.mhz_to_latency:
			if state.total_latency < state.mhz_to_latency[mhz]:
				state.mhz_to_latency[mhz] = state.total_latency		
				state.mhz_to_slices[mhz] = state.current_slices[:]
		else:
			state.mhz_to_latency[mhz] = state.total_latency
			state.mhz_to_slices[mhz] = state.current_slices[:]		
			
	# IF GOT BEST RESULT SO FAR
	if mhz >= max(state.mhz_to_slices) and not SEEN_CURRENT_SLICES(state):
		# Reset stages adjusted since want full exploration
		print "BEST SO FAR! :)"
		print "Resetting stages adjusted this latency since want full exploration..."
		for stage in range(0, len(state.current_slices) + 1):
			state.stages_adjusted_this_latency[stage] = 0
		
		# Got best, write log files if requested
		#if write_files:
		# wRITE TO LOG
		text = ""
		text += "MHZ	LATENCY	SLICES\n"
		for mhz_i in sorted(state.mhz_to_latency):
			latency = state.mhz_to_latency[mhz_i]
			slices = state.mhz_to_slices[mhz_i]
			text += str(mhz_i) + "	" + str(latency) + "	" + str(slices) + "\n"
		#print text
		f=open(SYN_OUTPUT_DIRECTORY + "/" + "mhz_to_latency_and_slices.log","w")
		f.write(text)
		f.close()
		
		# Write state
		WRITE_SWEEP_STATE_CACHE_FILE(state, Logic)
			

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

def SEEN_SLICES(slices, state):
	return GET_EQ_SEEN_SLICES(slices, state) is not None
	
def GET_EQ_SEEN_SLICES(slices, state):
	# Point of this is to check if we have seen these slices
	# But exact floating point equal is dumb
	# Min floating point that matters is 1 bit of adjsutment
	
	# Check for matching slices in seen slices:
	for slices_i in state.seen_slices:
		if SLICES_EQ(slices_i, slices, SLICE_EPSILON(state.zero_clk_pipeline_map.zero_clk_max_delay)):
			return slices_i
			
	return None
	
def ROUND_SLICES_TO_SEEN(slices, state):
	rv = slices[:]
	equal_seen_slices = GET_EQ_SEEN_SLICES(slices, state)
	if equal_seen_slices is not None:
		rv =  equal_seen_slices
	return rv
	

def SEEN_CURRENT_SLICES(state):
	return SEEN_SLICES(state.current_slices, state)
	
def FILTER_OUT_SEEN_ADJUSTMENTS(possible_adjusted_slices, state):
	unseen_possible_adjusted_slices = []
	for possible_slices in possible_adjusted_slices:
		if not SEEN_SLICES(possible_slices,state):
			unseen_possible_adjusted_slices.append(possible_slices)
		else:
			print "	Saw,",possible_slices,"already"
	return unseen_possible_adjusted_slices

def DO_THROUGHPUT_SWEEP(Logic, parser_state, target_mhz):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	FuncLogicLookupTable = parser_state.FuncLogicLookupTable
	print "Function:",Logic.func_name
	
	zero_clk_pipeline_map = GET_ZERO_CLK_PIPELINE_MAP(Logic, parser_state)
	print zero_clk_pipeline_map
	
	print ""
	orig_total_delay = zero_clk_pipeline_map.zero_clk_max_delay
	print "Total Delay Units In Pipeline Map:",orig_total_delay
	slice_ep = SLICE_EPSILON(zero_clk_pipeline_map.zero_clk_max_delay)
	print "SLICE EPSILON:", slice_ep
	# START WITH NO SLICES
	
	# Default sweep state is zero clocks ... this is cleaner
	state = GET_MOST_RECENT_OR_DEFAULT_SWEEP_STATE(Logic, zero_clk_pipeline_map)
	
	# Make adjustments via working stage range
	state.working_stage_range = state.stage_range[:]
	
	# Begin the loop of synthesizing adjustments to pick best one
	while True:
		print "|||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||"
		print "|||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||"	
		# Are we done now?
		if state.total_latency in state.latency_2_best_delay:
			curr_mhz = 1000.0 / state.latency_2_best_delay[state.total_latency]
			if curr_mhz >= target_mhz:
				print "Reached target operating frequency of",target_mhz,"MHz"
				write_files = False
				return GET_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(Logic, state.latency_2_best_slices[state.total_latency], parser_state,  write_files)
			
		# We have a stage range to work with
		print "Geting default adjustments for these slices:"
		print "Current slices:", state.current_slices
		print "Working stage range:", state.working_stage_range
		print "Slice Step:", state.slice_step
		# If we just got the best result (not seen yet) 
		# then try all possible changes by overriding stage range
		if not SEEN_CURRENT_SLICES(state):
			# Sanity check that never missing a peak we climb
			if state.total_latency in state.latency_2_best_slices:
				#if SLICES_EQ(state.current_slices , state.latency_2_best_slices[state.total_latency], slice_ep):
				if (state.timing_report is not None) and (state.latency_2_best_delay[state.total_latency] == state.timing_report.path_delay):
					print "Got best result so far, dumb checking all possible adjustments from here."
					state.working_stage_range = range(0,state.total_latency+1)
					print "New working stage range:", state.working_stage_range
			
		print "Adjusting based on working stage range:", state.working_stage_range			
		# Record that we are adjusting stages in the stage range
		#for stage in state.working_stage_range:
		for stage in state.stage_range: # Not working range since want to only count adjustments based on syn results
			state.stages_adjusted_this_latency[stage] += 1

		# Sometimes all possible changes are the same result and best slices will be none
		# Get default set of possible adjustments
		possible_adjusted_slices = GET_DEFAULT_SLICE_ADJUSTMENTS(Logic, state.current_slices,state.working_stage_range, parser_state, state.zero_clk_pipeline_map, state.slice_step, slice_ep, SLICE_DISTANCE_MIN(state.zero_clk_pipeline_map.zero_clk_max_delay))
		print "Possible adjustments:"
		for possible_slices in possible_adjusted_slices:
			print "	", possible_slices
		
		# Round slices to nearest if seen before
		new_possible_adjusted_slices = []
		for possible_slices in possible_adjusted_slices:
			new_possible_slices = ROUND_SLICES_TO_SEEN(possible_slices, state)
			new_possible_adjusted_slices.append(new_possible_slices)
		possible_adjusted_slices = REMOVE_DUP_SLICES(new_possible_adjusted_slices, slice_ep)
		print "Possible adjustments after rounding to seen slices:"
		for possible_slices in possible_adjusted_slices:
			print "	", possible_slices
		
		# Add the current slices result to list
		if not SEEN_CURRENT_SLICES(state):
			# Only if not seen yet
			state.seen_slices.append(state.current_slices[:])
		
		print "Running syn for all possible adjustments..."
		state = PARALLEL_SYN_WITH_SLICES_PICK_BEST(Logic, state, parser_state, possible_adjusted_slices)	

		
		
		#__/\\\___________________/\\\\\__________/\\\\\\\\\\\\_        
		# _\/\\\_________________/\\\///\\\______/\\\//////////__       
		#  _\/\\\_______________/\\\/__\///\\\___/\\\_____________      
		#   _\/\\\______________/\\\______\//\\\_\/\\\____/\\\\\\\_     
		#    _\/\\\_____________\/\\\_______\/\\\_\/\\\___\/////\\\_    
		#     _\/\\\_____________\//\\\______/\\\__\/\\\_______\/\\\_   
		#      _\/\\\______________\///\\\__/\\\____\/\\\_______\/\\\_  
		#       _\/\\\\\\\\\\\\\\\____\///\\\\\/_____\//\\\\\\\\\\\\/__ 
		#        _\///////////////_______\/////________\////////////____
		print "Best result out of possible adjustments:"
		write_files = True
		LOG_SWEEP_STATE(state, Logic) #, write_files)
		
		
				
		#__/\\\\\\\\\\\__/\\\\____________/\\\\__/\\\\\\\\\\\\\______/\\\\\\\\\___________/\\\\\_______/\\\________/\\\__/\\\\\\\\\\\\\\\_        
		# _\/////\\\///__\/\\\\\\________/\\\\\\_\/\\\/////////\\\__/\\\///////\\\_______/\\\///\\\____\/\\\_______\/\\\_\/\\\///////////__       
		#  _____\/\\\_____\/\\\//\\\____/\\\//\\\_\/\\\_______\/\\\_\/\\\_____\/\\\_____/\\\/__\///\\\__\//\\\______/\\\__\/\\\_____________      
		#   _____\/\\\_____\/\\\\///\\\/\\\/_\/\\\_\/\\\\\\\\\\\\\/__\/\\\\\\\\\\\/_____/\\\______\//\\\__\//\\\____/\\\___\/\\\\\\\\\\\_____     
		#    _____\/\\\_____\/\\\__\///\\\/___\/\\\_\/\\\/////////____\/\\\//////\\\____\/\\\_______\/\\\___\//\\\__/\\\____\/\\\///////______    
		#     _____\/\\\_____\/\\\____\///_____\/\\\_\/\\\_____________\/\\\____\//\\\___\//\\\______/\\\_____\//\\\/\\\_____\/\\\_____________   
		#      _____\/\\\_____\/\\\_____________\/\\\_\/\\\_____________\/\\\_____\//\\\___\///\\\__/\\\________\//\\\\\______\/\\\_____________  
		#       __/\\\\\\\\\\\_\/\\\_____________\/\\\_\/\\\_____________\/\\\______\//\\\____\///\\\\\/__________\//\\\_______\/\\\\\\\\\\\\\\\_ 
		#        _\///////////__\///______________\///__\///______________\///________\///_______\/////_____________\///________\///////////////__
		# Only need to do additional improvement if best of possible adjustments has been seen already
		if not SEEN_CURRENT_SLICES(state):
			# Not seen before, OK to skip additional adjustment
			continue
			
			
		# SEEN THIS BEST state.current_slices BEFORE
		# DO adjustment to get out of loop
		# HOW DO WE ADJUST SLICES??????	
		print "Saw best result of possible adjustments... getting different stage range / slice step"
			
		# IF LOOPED BACK TO BEST THEN 
		if SLICES_EQ(state.current_slices , state.latency_2_best_slices[state.total_latency], slice_ep) and state.total_latency > 1: # 0 or 1 slice will always loop back to best
			print "Looped back to best result, decreasing slice step to narrow in on best..."
			print "Reducing slice_step..."
			old_slice_step = state.slice_step
			state.slice_step = REDUCE_SLICE_STEP(state.slice_step, state.total_latency, slice_ep)
			print "New slice_step:",state.slice_step
			if old_slice_step == state.slice_step:
				print "Can't reduce slice step any further..."
				# Do nothing and end up adding pipeline stage
				pass
			else:
				# OK to try and get another set of slices
				continue
			
		# BACKUP PLAN TO AVOID LOOPS
		elif state.total_latency > 0:
			# Check for unadjsuted stages
			# Need difference or just guessing which can go forever
			missing_stages = []
			if min(state.stages_adjusted_this_latency.values()) != max(state.stages_adjusted_this_latency.values()):
				print "Checking if all stages have been adjusted..."
				# Find min adjusted count 
				min_adj = 99999999
				for i in range(0, state.total_latency+1):
					adj = state.stages_adjusted_this_latency[i]
					print "Stage",i,"adjusted:",adj
					if adj < min_adj:
						min_adj = adj
				
				# Get stages matching same minimum 
				for i in range(0, state.total_latency+1):
					adj = state.stages_adjusted_this_latency[i]
					if adj == min_adj:
						missing_stages.append(i)
			
			# Only do multiplied adjustments if adjusted all stages at least once
			# Otherwise get caught making stupid adjustments right after init
			actual_min_adj = min(state.stages_adjusted_this_latency.values())
			if (actual_min_adj != 0) and (actual_min_adj < MAX_STAGE_ADJUSTMENT):
				print "Multiplying suggested change with limit:",SLICE_MOVEMENT_MULT
				orig_slice_step = state.slice_step
				n = 1
				# Dont want to increase slice offset and miss fine grain adjustments
				working_slice_step = state.slice_step 
				# This change needs to produce different slices or we will end up in loop
				orig_slices = state.current_slices[:]
				# Want to increase slice step if all adjustments yield same result
				# That should be the case when we iterate this while loop after running syn
				num_par_syns = 0
				while SLICES_EQ(orig_slices, state.current_slices, slice_ep) and (n <= SLICE_MOVEMENT_MULT):
					# Start with no possible adjustments
					print "Working slice step:",working_slice_step
					print "Multiplier:", n
					# Keep increasing slice step until get non zero length of possible adjustments
					possible_adjusted_slices = GET_DEFAULT_SLICE_ADJUSTMENTS(Logic, state.current_slices,state.stage_range, parser_state, state.zero_clk_pipeline_map, working_slice_step, slice_ep, SLICE_DISTANCE_MIN(state.zero_clk_pipeline_map.zero_clk_max_delay), multiplier=1, include_bad_changes=False)
					# Filter out ones seen already
					possible_adjusted_slices = FILTER_OUT_SEEN_ADJUSTMENTS(possible_adjusted_slices, state)			
							
					if len(possible_adjusted_slices) > 0:
						print "Got some unseen adjusted slices (with working slice step = ", working_slice_step, ")"
						print "Possible adjustments:"
						for possible_slices in possible_adjusted_slices:
							print "	", possible_slices
						print "Picking best out of possible adjusments..."
						state = PARALLEL_SYN_WITH_SLICES_PICK_BEST(Logic, state, parser_state, possible_adjusted_slices)
						num_par_syns += 1
						

					# Increase WORKING slice step
					n = n + 1
					print "Increasing working slice step, multiplier:", n
					working_slice_step = orig_slice_step * n
					print "New working slice_step:",working_slice_step
					
				# If actually got new slices then continue to next run
				if not SLICES_EQ(orig_slices, state.current_slices, slice_ep):
					print "Got new slices, running with those:", state.current_slices
					print "Increasing slice step based on number of syn attempts:", num_par_syns
					state.slice_step = num_par_syns * state.slice_step
					print "New slice_step:",state.slice_step
					LOG_SWEEP_STATE(state, Logic)
					continue
				else:
					print "Did not get any unseen slices to try?"
					print "Now trying backup check of all stages adjusted equally..."
			
			##########################################################
			##########################################################
			
			
			# Allow cutoff if sad
			AM_SAD = (int(open("i_am_sad.cfg",'r').readline()) > 0) and (actual_min_adj > 1)
			if AM_SAD:
				print '''                               
 .-.                           
( __)                          
(''")                          
 | |                           
 | |                           
 | |                           
 | |                           
 | |                           
 | |                           
(___)                          
                               
                               
                               
                               
  .---.   ___ .-. .-.          
 / .-, \ (   )   '   \         
(__) ; |  |  .-.  .-. ;        
  .'`  |  | |  | |  | |        
 / .'| |  | |  | |  | |        
| /  | |  | |  | |  | |        
; |  ; |  | |  | |  | |        
' `-'  |  | |  | |  | |        
`.__.'_. (___)(___)(___)       
                               
                               
                          ___  
                         (   ) 
    .--.      .---.    .-.| |  
  /  _  \    / .-, \  /   \ |  
 . .' `. ;  (__) ; | |  .-. |  
 | '   | |    .'`  | | |  | |  
 _\_`.(___)  / .'| | | |  | |  
(   ). '.   | /  | | | |  | |  
 | |  `\ |  ; |  ; | | '  | |  
 ; '._,' '  ' `-'  | ' `-'  /  
  '.___.'   `.__.'_.  `.__,'   
                                                           
'''
				# Wait until file reads 0 again
				while len(open("i_am_sad.cfg",'r').readline())==1 and (int(open("i_am_sad.cfg",'r').readline()) > 0):
					pass
			
			# Do something with missing stage or backup		
			stages_off_balance = ((max(state.stages_adjusted_this_latency.values()) - min(state.stages_adjusted_this_latency.values())) >= len(state.current_slices)) or (actual_min_adj == 0)
			
			# Moved this here from start of # BACKUP PLAN TO AVOID LOOPS ^
			print "Reducing slice_step..."
			state.slice_step = REDUCE_SLICE_STEP(state.slice_step, state.total_latency, slice_ep)
			print "New slice_step:",state.slice_step
			
			# Magical maximum to keep runs out of the weeds?
			if actual_min_adj >= MAX_STAGE_ADJUSTMENT:
				print "Hit limit of",MAX_STAGE_ADJUSTMENT, "for adjusting all stages... moving on..."
				
			elif (len(missing_stages) > 0) and stages_off_balance and not AM_SAD:
				print "These stages have not been adjusted much: <<<<<<<<<<< ", missing_stages
				state.working_stage_range = missing_stages
				print "New working stage range:",state.working_stage_range
				EXPAND_UNTIL_SEEN_IN_SYN = True
				if not EXPAND_UNTIL_SEEN_IN_SYN:
					print "So running with working stage range..."
					continue
				else:
					print "<<<<<<<<<<< Expanding missing stages until seen in syn results..."
					local_seen_slices = []
					# Keep expanding those stages until one of them is seen in timing report stage range
					new_stage_range = []
					new_slices = state.current_slices[:]
					found_missing_stages = []
					try_num = 0
					
					while len(found_missing_stages)==0:
						print "<<<<<<<<<<< TRY",try_num
						try_num += 1
						# Do adjustment
						pre_expand_slices = new_slices[:]
						new_slices,new_stages_adjusted_this_latency = EXPAND_STAGES_VIA_ADJ_COUNT(missing_stages, new_slices, state.slice_step, state, SLICE_DISTANCE_MIN(state.zero_clk_pipeline_map.zero_clk_max_delay))
						state.stages_adjusted_this_latency = new_stages_adjusted_this_latency
						
						# If expansion is same as current slices then stop
						if SLICES_EQ(new_slices, pre_expand_slices, slice_ep):
							print "Expansion was same as current? Give up..."
							new_slices = None
							break
							
						seen_new_slices_locally = False
						# Check for matching slices in local seen slices:
						for slices_i in local_seen_slices:
							if SLICES_EQ(slices_i, new_slices, slice_ep):
								seen_new_slices_locally = True
								break
												
						if SEEN_SLICES(new_slices, state) or seen_new_slices_locally:
							print "Expanding further, saw these slices already:", new_slices
							continue
							
						print "<<<<<<<<<<< Rounding", new_slices, "away flom globals..."
						pre_round = new_slices[:]
						new_slices = ROUND_SLICES_AWAY_FROM_GLOBAL_LOGIC(Logic, new_slices, state.slice_step, parser_state, state.zero_clk_pipeline_map)
						
						seen_new_slices_locally = False
						# Check for matching slices in local seen slices:
						for slices_i in local_seen_slices:
							if SLICES_EQ(slices_i, new_slices, slice_ep):
								seen_new_slices_locally = True
								break
						
						if SEEN_SLICES(new_slices, state) or seen_new_slices_locally:
							print "Expanding further, saw rounded slices:",new_slices
							new_slices = pre_round
							continue				
						
						print "<<<<<<<<<<< Running syn with expanded slices:", new_slices
						new_stage_range, new_timing_report, new_total_latency, new_TimingParamsLookupTable = DO_SYN_WITH_SLICES(new_slices, Logic, zero_clk_pipeline_map, parser_state)
						print "<<<<<<<<<<< Got stage range:",new_stage_range
						for new_stage in new_stage_range:
							if new_stage in missing_stages:
								found_missing_stages.append(new_stage)
								print "<<<<<<<<<<< Has missing stage", new_stage
						# Record having seen these slices but keep it local yo
						local_seen_slices.append(new_slices)
						
								
					
					if new_slices is not None:
						print "<<<<<<<<<<< Using adjustment", new_slices, "that resulted in missing stage", found_missing_stages
						state.current_slices= new_slices
						state.stage_range = new_stage_range
						state.timing_report = new_timing_report
						state.total_latency = new_total_latency
						state.TimingParamsLookupTable = new_TimingParamsLookupTable
						
						# Slice step should match the total adjustment that was needed?
						print "<<<<<<<<<<< Slice step should match the total adjustment that was needed (based on num tries)?"
						state.slice_step = try_num * state.slice_step
						print "<<<<<<<<<<< Increasing slice step to:", state.slice_step
						LOG_SWEEP_STATE(state, Logic)
						continue
					else:
						print "<<<<<<<<<<< Couldnt shrink other stages anymore? No adjustment made..."
					
			else:
				print "Cannot find missing stage adjustment?"				
				
		
		# Result of either unclear or clear state.stage 
		print "Didn't make any changes?",state.current_slices

		# If seen this config (made no adjsutment) add another pipeline slice
		if SEEN_CURRENT_SLICES(state):
			print "Saw this slice configuration already. We gave up."
			print "Adding another pipeline stage..."
			state = ADD_ANOTHER_PIPELINE_STAGE(Logic, state, parser_state)
			# Run syn to get started with this new set of slices
			# Run syn with these slices
			print "Running syn after adding pipeline stage..."
			#print "Current slices:", state.current_slices
			#print "Slice Step:",state.slice_step
			state.stage_range, state.timing_report, state.total_latency, state.TimingParamsLookupTable = DO_SYN_WITH_SLICES(state.current_slices, Logic, zero_clk_pipeline_map, parser_state)
			mhz = (1.0 / (state.timing_report.path_delay / 1000.0)) 
			write_files = True
			LOG_SWEEP_STATE(state, Logic) #, write_files)
		else:
			print "What didnt make change and got new slices?", state.current_slices
			sys.exit(0)
			
		
		
	
	sys.exit(0)
	
	

	
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
	
# Return slices and new copy of adjsuted stages dict
def EXPAND_STAGES_VIA_ADJ_COUNT(missing_stages, current_slices, slice_step, state, min_dist):	
	print "<<<<<<<<<<< EXPANDING", missing_stages, "VIA_ADJ_COUNT:",current_slices
	slice_per_stage = GET_SLICE_PER_STAGE(current_slices)
	# Each missing stage is expanded by slice_step/num missing stages
	# Div by num missing stages since might not be able to shrink enough slices 
	# to account for every missing stage getting slice step removed
	expansion = slice_step / len(missing_stages)
	total_expansion = 0.0
	stages_adjusted_this_latency = dict(state.stages_adjusted_this_latency) # was deep copy
	for missing_stage in missing_stages:
		slice_per_stage[missing_stage] = slice_per_stage[missing_stage] + expansion
		total_expansion = total_expansion + expansion
		# Record this expansion as adjustment
		stages_adjusted_this_latency[missing_stage] += 1
	
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
			print "Shrinking stage",stage, "curr size:", slice_per_stage[stage]
			slice_per_stage[stage] -= shrink_per_stage
			# Record adjustment
			stages_adjusted_this_latency[stage] += 1		
		
		# reconstruct new slcies
		rv = BUILD_SLICES(slice_per_stage)
		
		#print "RV",rv
		#sys.exit(0)
		
		return rv, stages_adjusted_this_latency
	else:
		# Can't shrink anything more
		return current_slices, state.stages_adjusted_this_latency

	


def ESTIMATE_MAX_THROUGHPUT(mhz_range, mhz_to_latency):
	'''
	High Clock	High Latency	High Period	Low Clock	Low Latency	Low Period	"Required parallel
	Low clock"	"Serialization
	Latency (1 or each clock?) (ns)"
	160	5	6.25	100		10	1.6	16.25
	240	10						
	100	2						
	260	10						
	40	0						
	220	10						
	140	5						
	80	1						
	200	10						
	20	0						
	300	43						
	120	5						
	180	8						
	60	1						
	280	32						
	'''
	min_mhz = min(mhz_range)
	max_mhz = max(mhz_range)
	max_div = int(math.ceil(max_mhz/min_mhz))
	
	text = ""
	text += "clk_mhz" + "	" +"high_clk_latency_ns" + "	" + "div_clk_mhz" + "	" + "div_clock_latency_ns" + "	" + "n_parallel" + "	" + "deser_delay" + "	" + "ser_delay" + "	" + "total_latency" + "\n"
	
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
				
				text += str(clk_mhz) + "	" + str(high_clk_latency_ns) + "	" + str(div_clk_mhz) + "	" + str(div_clock_latency_ns) + "	" + str(n_parallel) + "	" + str(deser_delay) + "	" + str(ser_delay) + "	" + str(total_latency) + "\n"
		
	
	f = open(SYN_OUTPUT_DIRECTORY + "/" + "estimated_max_throughput.log","w")
	f.write(text)
	f.close()


def GET_OUTPUT_DIRECTORY(Logic):
	if Logic.is_c_built_in:
		output_directory = SYN_OUTPUT_DIRECTORY + "/" + "built_in" + "/" + Logic.func_name
	else:
		# Use source file if not built in?
		src_file = str(Logic.c_ast_node.coord.file)
		output_directory = SYN_OUTPUT_DIRECTORY + "/" + src_file + "/" + Logic.func_name
		
	return output_directory
	
def IS_USER_CODE(logic, parser_state):
	# Check logic.is_built_in
	# or autogenerated code	
	
	user_code = (not logic.is_c_built_in and not SW_LIB.IS_AUTO_GENERATED(logic)) # ???? or (not VHDL.C_TYPES_ARE_INTEGERS(input_types) or (not C_TO_LOGIC.C_TYPES_ARE_BUILT_IN(input_types))
	
	# GAH NEED TO CHECK input and output TYPES
	# AND ALL INNNER WIRES TOO!
	all_types = []
	for input_wire in logic.inputs:
		all_types.append(logic.wire_to_c_type[input_wire])
	for wire in logic.wires: 
		all_types.append(logic.wire_to_c_type[wire])
	all_types.append(logic.wire_to_c_type[logic.outputs[0]])
	all_types = list(set(all_types))
	
	# Becomes user code if using struct or array of structs
	# For now???? fuck me
	for c_type in all_types:
		if C_TO_LOGIC.C_TYPE_IS_STRUCT(c_type,parser_state):
			if C_TO_LOGIC.DUMB_STRUCT_THING in c_type:
				# Gah dumb array struct types thing
				# BReak apart
				toks = c_type.split(C_TO_LOGIC.DUMB_STRUCT_THING+"_")
				# uint8_t_ARRAY_STRUCT_2_2
				elem_type = toks[0]
				if C_TO_LOGIC.C_TYPE_IS_STRUCT(elem_type,parser_state):
					user_code = True
			else:
				# Not the dumb array thing, is regular struct
				user_code = True
		elif C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
			elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
			if C_TO_LOGIC.C_TYPE_IS_STRUCT(elem_type,parser_state):
				user_code = True
	
	#print "?? USER? logic.func_name:",logic.func_name, user_code
	
	return user_code
		

def GET_CACHED_PATH_DELAY_FILE_PATH(logic):
	key = logic.func_name
	
	# MEM has var name - weird yo
	if SW_LIB.IS_MEM(logic):
		key = SW_LIB.GET_MEM_NAME(logic)
	
	func_name_includes_types = SW_LIB.FUNC_NAME_INCLUDES_TYPES(logic)
	if not func_name_includes_types:
		for input_wire in logic.inputs:
			c_type = logic.wire_to_c_type[input_wire]
			key += "_" + c_type
		
	file_path = PATH_DELAY_CACHE_DIR + "/" + key + ".delay"
	
	return file_path
	
def GET_CACHED_PATH_DELAY(logic):	
	# Look in cache dir
	file_path = GET_CACHED_PATH_DELAY_FILE_PATH(logic)
	if os.path.exists(file_path):
		#print "Reading Cached Delay File:", file_path
		return float(open(file_path,"r").readlines()[0])
		
	return None	
	


def ADD_PATH_DELAY_TO_LOOKUP(main_logic, parser_state):
	# TODO parallelize this
	
	print "Writing VHDL files for all functions (as combinatorial logic)..."
	WRITE_ALL_ZERO_CLK_VHDL_PACKAGES(parser_state)
	
	# initial params are 0 clk latency for all submodules
	TimingParamsLookupTable = dict()
	for logic_inst_name in parser_state.LogicInstLookupTable: 
		logic = parser_state.LogicInstLookupTable[logic_inst_name]
		timing_params = TimingParams(logic)
		TimingParamsLookupTable[logic_inst_name] = timing_params	
	
	print "Writing the constant struct+enum definitions as defined from C code..."
	VHDL.WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(parser_state)
	
	print "Synthesizing as combinatorial logic to get total logic delay..."
	print ""
	
	# Record stats on functions with globals
	min_mhz = 999999999
	min_mhz_func_name = None	
	
	# Some funcs dont need to be individually synthesized
	MUX_DELAY = None
	
	#bAAAAAAAAAAAhhhhhhh need to recursively do this 
	# Do depth first 
	# haha no do it the dumb easy way
	func_names_done_so_far = []
	all_funcs_done = False
	while not all_funcs_done:
		all_funcs_done = True
		for logic_func_name in parser_state.FuncLogicLookupTable:
			# If already done then skip
			if logic_func_name in func_names_done_so_far:
				continue

			# Get logic
			logic = parser_state.FuncLogicLookupTable[logic_func_name]
			# Do dumb thing finding an inst logic ... will all be zero clock so doesnt matter
			# TODO: Allow TimingParamsLookupTable to by by func name? Why not? Just for most things not?
			inst_logic = None
			for logic_inst_name in parser_state.LogicInstLookupTable: 
				maybe_inst_logic = parser_state.LogicInstLookupTable[logic_inst_name]
				if maybe_inst_logic.func_name == logic.func_name:
					inst_logic = maybe_inst_logic
					break
			if inst_logic is None:
				#print "Warning?: No logic instance for function:", logic.func_name, "never used?"
				continue
			
			# All dependencies met?
			all_dep_met = True
			for submodule_inst in logic.submodule_instances:
				submodule_func_name = logic.submodule_instances[submodule_inst]
				if submodule_func_name not in func_names_done_so_far:
					#print "submodule_func_name not in func_names_done_so_far",submodule_func_name
					all_dep_met = False
					break	
			
			# If not all dependencies met then dont do syn yet
			if not all_dep_met:
				all_funcs_done = False
				continue
			
			# Do syn for logic 
			#print "Function:", GET_OUTPUT_DIRECTORY(logic).replace(SYN_OUTPUT_DIRECTORY,"")
			
			# Try to get cached path delay
			cached_path_delay = GET_CACHED_PATH_DELAY(logic)

			if SW_LIB.IS_BIT_MANIP(logic):
				logic.delay = 0
			elif logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
				logic.delay = 0
			elif logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SL_NAME) or logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SR_NAME):
				logic.delay = 0
			elif logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME) and logic.is_c_built_in and MUX_DELAY is not None:
				logic.delay = MUX_DELAY				 
			elif cached_path_delay is not None:
				logic.delay = int(cached_path_delay * DELAY_UNIT_MULT)
				print "Function:",logic.func_name, "Cached path delay(ns):", cached_path_delay
			else:
				clock_mhz = INF_MHZ # Impossible goal for timing since just want path delay
				print "Function:",logic.func_name
				parsed_timing_report = VIVADO.SYN_AND_REPORT_TIMING(inst_logic, parser_state, TimingParamsLookupTable, clock_mhz, total_latency=0)
				if parsed_timing_report.path_delay is None:
					print "Cannot synthesize for path delay ",logic.func_name
					print parsed_timing_report.orig_text
					if DO_SYN_FAIL_SIM:
						MODELSIM.DO_OPTIONAL_DEBUG(do_debug=True)
					sys.exit(0)
				mhz = 1000.0 / parsed_timing_report.path_delay
				logic.delay = int(parsed_timing_report.path_delay * DELAY_UNIT_MULT)
				# Also update instance
				inst_logic.delay = logic.delay
				
				# Print pipeline map before syn results
				if len(logic.submodule_instances) > 0:
					zero_clk_pipeline_map = GET_ZERO_CLK_PIPELINE_MAP(inst_logic, parser_state) # use inst_logic since timing params are by inst
					print zero_clk_pipeline_map
				# Syn results are delay and clock	
				print "Path delay (ns):", parsed_timing_report.path_delay, "=",mhz, "MHz"
				print ""
				# Record worst global
				#if len(logic.global_wires) > 0:
				if logic.uses_globals:
					if mhz < min_mhz:
						min_mhz_func_name = logic.func_name
						min_mhz = mhz
						
				# Local cache of funcs first
				if logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME) and logic.is_c_built_in:
					MUX_DELAY = logic.delay
				# Cache delay syn result if not user code
				elif not IS_USER_CODE(logic, parser_state):
					filepath = GET_CACHED_PATH_DELAY_FILE_PATH(logic)
					if not os.path.exists(PATH_DELAY_CACHE_DIR):
						os.makedirs(PATH_DELAY_CACHE_DIR)					
					f=open(filepath,"w")
					f.write(str(parsed_timing_report.path_delay))
					f.close()				
			
			# Save logic with delay into lookup
			parser_state.FuncLogicLookupTable[logic_func_name] = logic
			# Update all instances now too
			for logic_inst_name_i in parser_state.LogicInstLookupTable:
				inst_logic_i = parser_state.LogicInstLookupTable[logic_inst_name_i]
				if inst_logic_i.func_name == logic.func_name:
					inst_logic_i.delay = logic.delay
					parser_state.LogicInstLookupTable[logic_inst_name_i] = inst_logic_i # Consistently dumb
			
			# Done
			func_names_done_so_far.append(logic_func_name)
	
	# Record worst global
	if min_mhz_func_name is not None:
		print "Design limited to ~", min_mhz, "MHz due to function:", min_mhz_func_name
		parser_state.global_mhz_limit = min_mhz
		
	return parser_state

	
	
# Generalizing is a bad thing to do
# Abstracting is something more


def WRITE_ALL_ZERO_CLK_VHDL_PACKAGES(parser_state):
	# Make zero clk lookup table
	TimingParamsLookupTable = dict()
	for inst_name in parser_state.LogicInstLookupTable:
		inst_logic = parser_state.LogicInstLookupTable[inst_name]
		TimingParamsLookupTable[inst_name] = TimingParams(inst_logic)
	
	# For now repeatedly write the same func files?
	for inst_name in parser_state.LogicInstLookupTable:		
		logic = parser_state.LogicInstLookupTable[inst_name]
		if not logic.is_vhdl_func:
			syn_out_dir = GET_OUTPUT_DIRECTORY(logic)
			if not os.path.exists(syn_out_dir):
				os.makedirs(syn_out_dir)
			VHDL.WRITE_VHDL_ENTITY(logic, syn_out_dir, parser_state, TimingParamsLookupTable)	

def GET_ABS_SUBMODULE_STAGE_WHEN_USED(submodule_inst_name, logic, parser_state, TimingParamsLookupTable):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# Start at contingin logic
	absolute_stage = 0
	curr_submodule_inst = submodule_inst_name

	# Stop once at top level
	# DO
	while curr_submodule_inst != logic.inst_name:
		#print "curr_submodule_inst",curr_submodule_inst
		#print "logic.inst_name",logic.inst_name
		#print "GET_ABS_SUBMODULE_STAGE_WHEN_USED"
		#print "curr_submodule_inst",curr_submodule_inst
		curr_container_logic = C_TO_LOGIC.GET_CONTAINER_LOGIC_FOR_SUBMODULE_INST(curr_submodule_inst, LogicInstLookupTable)
		containing_timing_params = TimingParamsLookupTable[curr_container_logic.inst_name]
		
		local_stage_when_used = GET_LOCAL_SUBMODULE_STAGE_WHEN_USED(curr_submodule_inst, curr_container_logic, parser_state, TimingParamsLookupTable)
		absolute_stage += local_stage_when_used
		
		# Update vars for next iter
		curr_submodule_inst = curr_container_logic.inst_name
		
	return absolute_stage
		

def GET_LOCAL_SUBMODULE_STAGE_WHEN_USED(submodule_inst, container_logic, parser_state, TimingParamsLookupTable):	
	timing_params = TimingParamsLookupTable[container_logic.inst_name]	
	
	pipeline_map = GET_PIPELINE_MAP(container_logic, parser_state, TimingParamsLookupTable)
	per_stage_time_order = pipeline_map.stage_ordered_submodule_list
	#per_stage_time_order = VHDL.GET_PER_STAGE_LOCAL_TIME_ORDER_SUBMODULE_INSTANCE_NAMES(container_logic, parser_state, TimingParamsLookupTable)
	
	# Find earliest occurance of this submodule inst in per stage order
	earliest_stage = TimingParamsLookupTable[container_logic.inst_name].GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	earliest_match = None
	for stage in per_stage_time_order:
		for c_built_in_inst_name in per_stage_time_order[stage]:
			if submodule_inst in c_built_in_inst_name:
				if stage <= earliest_stage:
					earliest_match = c_built_in_inst_name
					earliest_stage = stage
	
	if earliest_match is None:
		print "What stage when used?", submodule_inst
		print "per_stage_time_order",per_stage_time_order
		sys.exit(0)
		
	return earliest_stage

'''
def GET_LOCAL_SUBMODULE_STAGE_WHEN_COMPLETE(submodule_inst, container_logic, parser_state, TimingParamsLookupTable):
	# Add latency to when sued
	used = GET_LOCAL_SUBMODULE_STAGE_WHEN_USED(submodule_inst, container_logic, parser_state, TimingParamsLookupTable)
	#submodule_logic = LogicInstLookupTable[submodule_inst]
	return used + TimingParamsLookupTable[submodule_inst].GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
'''	

def GET_ABS_SUBMODULE_STAGE_WHEN_COMPLETE(submodule_inst_name, logic, LogicInstLookupTable, TimingParamsLookupTable):
	# Add latency to when sued
	used = GET_ABS_SUBMODULE_STAGE_WHEN_USED(submodule_inst_name, logic, parser_state, TimingParamsLookupTable)
	#submodule_logic = LogicInstLookupTable[submodule_inst]
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
	print "GET_WIRE_NAME_FROM_WRITE_PIPE_VAR_NAME Not a submodule port wire ?"
	print "wire_write_pipe_var_name",wire_write_pipe_var_name
	sys.exit(0)
	
'''	
def GET_CACHED_PIPELINE_MAP(Logic, TimingParamsLookupTable, parser_state, est_total_latency):	
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	
	output_directory = GET_OUTPUT_DIRECTORY(Logic)
	timing_params = TimingParamsLookupTable[Logic.inst_name]
	
	filename = VHDL.GET_ENTITY_NAME(Logic,  TimingParamsLookupTable, parser_state, est_total_latency) + "_" + str(est_total_latency) + "CLK" + timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state) + ".pipe"
	filepath = output_directory + "/" + filename
	if os.path.exists(filepath):
		_WRITE_PIPELINE_MAP_CACHE_FILE_lock.acquire()
		with open(filepath, 'rb') as input:
			_WRITE_PIPELINE_MAP_CACHE_FILE_lock.release()
			try:
				pipe_line_map = pickle.load(input)
			except:
				print "WTF? cant load pipeline map file",filepath
				#print sys.exc_info()[0]                                                                
				#sys.exit(0)
				return None

			return pipe_line_map
	return None	
'''
	
'''
_WRITE_PIPELINE_MAP_CACHE_FILE_lock = Lock()
def WRITE_PIPELINE_MAP_CACHE_FILE(Logic, pipeline_map, TimingParamsLookupTable, parser_state, est_total_latency):
	output_directory = GET_OUTPUT_DIRECTORY(Logic)
	timing_params = TimingParamsLookupTable[Logic.inst_name]
	filename = VHDL.GET_ENTITY_NAME(Logic,TimingParamsLookupTable, parser_state, est_total_latency) + "_" + str(est_total_latency) + "CLK" + timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state) + ".pipe"
	filepath = output_directory + "/" + filename
	# Write dir first if needed
	if not os.path.exists(output_directory):
		os.makedirs(output_directory)
		
	# Write file
	_WRITE_PIPELINE_MAP_CACHE_FILE_lock.acquire()
	with open(filepath, 'w') as output:
		pickle.dump(pipeline_map, output, pickle.HIGHEST_PROTOCOL)
	_WRITE_PIPELINE_MAP_CACHE_FILE_lock.release()
'''
	
# Identify stage range of raw hdl registers in the pipeline
def GET_START_STAGE_END_STAGE_FROM_REGS(logic, start_reg_name, end_reg_name, parser_state, TimingParamsLookupTable, parsed_timing_report):
	LogicLookupTable = parser_state.LogicInstLookupTable
	
	# Default smallest range
	timing_params = TimingParamsLookupTable[logic.inst_name]
	start_stage = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	end_stage = 0
	
	DO_WHOLE_PIPELINE = True
	if DO_WHOLE_PIPELINE:
		start_stage = 0
		end_stage = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
		return start_stage, end_stage
	
	if VIVADO.REG_NAME_IS_INPUT_REG(start_reg_name) and VIVADO.REG_NAME_IS_OUTPUT_REG(end_reg_name):
		print "	Comb path to and from register in top.vhd"
		# Search entire space (should be 0 clk anyway)
		start_stage = 0
		end_stage = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)	
	elif VIVADO.REG_NAME_IS_INPUT_REG(start_reg_name) and not(VIVADO.REG_NAME_IS_OUTPUT_REG(end_reg_name)):
		print "	Comb path from input register in top.vhd to pipeline logic"
		start_stage = 0
	elif not(VIVADO.REG_NAME_IS_INPUT_REG(start_reg_name)) and VIVADO.REG_NAME_IS_OUTPUT_REG(end_reg_name):
		print "	Comb path from pipeline logic to output register in top.vhd"
		end_stage = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	else:
		print "	Comb path somewhere in the pipeline logic"
		
	print "	Taking register merging into account and assuming largest search range based on earliest when used and latest when complete times"
	found_start_stage = None
	if not(VIVADO.REG_NAME_IS_INPUT_REG(start_reg_name)):
		# all possible reg paths considering renaming
		# Start names
		start_names = [start_reg_name]
		start_aliases = []
		if start_reg_name in parsed_timing_report.reg_merged_with:
			start_aliases = parsed_timing_report.reg_merged_with[start_reg_name]
		start_names += start_aliases
		
		start_stages_when_used = []
		for start_name in start_names:
			start_inst = VIVADO.GET_MOST_MATCHING_LOGIC_INST_FROM_REG_NAME(start_name, logic, LogicLookupTable)
			when_used = GET_ABS_SUBMODULE_STAGE_WHEN_USED(start_inst, logic, parser_state, TimingParamsLookupTable)
			print "		",start_name
			print "			",start_inst,"used in absolute stage number:",when_used
			start_stages_when_used.append(when_used)
		found_start_stage = min(start_stages_when_used)
	
	found_end_stage = None
	if not(VIVADO.REG_NAME_IS_OUTPUT_REG(end_reg_name)):
		# all possible reg paths considering renaming
		# End names
		end_names = [end_reg_name]
		end_aliases = []
		if end_reg_name in parsed_timing_report.reg_merged_with:
			end_aliases = parsed_timing_report.reg_merged_with[end_reg_name]
		end_names += end_aliases

		end_stages_when_complete = []
		for end_name in end_names:
			end_inst = VIVADO.GET_MOST_MATCHING_LOGIC_INST_FROM_REG_NAME(end_name, logic, LogicLookupTable)
			when_complete = GET_ABS_SUBMODULE_STAGE_WHEN_COMPLETE(end_inst, logic, LogicLookupTable, TimingParamsLookupTable)
			print "		",end_name
			print "			",end_inst,"completes in absolute stage number:",when_complete
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
	

	

