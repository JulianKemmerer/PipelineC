#!/usr/bin/env python

import sys
import os
import subprocess
import math
import hashlib
import copy
import difflib
import Levenshtein
import pickle
import glob

import C_TO_LOGIC
import VHDL
import SW_LIB
import MODELSIM
import SYN

# Default to env if there
# then fallback to hardcoded 
ENV_VIVADO_DIR = os.environ.get('XILINX_VIVADO')
if ENV_VIVADO_DIR:
	VIVADO_DIR = ENV_VIVADO_DIR
else:
	VIVADO_DIR  = "/media/1TB/Programs/Linux/Xilinx/Vivado/2018.2"
VIVADO_PATH = VIVADO_DIR+"/bin/vivado"
VIVADO_DEFAULT_ARGS = "-mode batch"
VIVADO_PART="xcvu9p-flgb2104-2-i"  # xcvu9p-flgb2104-2-i = AWS F1, xc7a35ticsg324-1l = Arty
TIMING_REPORT_DIVIDER="......................THIS IS THAT STUPID DIVIDER THING................"

def GET_SELF_OFFSET_FROM_REG_NAME(reg_name):
	# Parse the self offset from the reg names
	# main_registers_r_reg     [self]      [0][MUX_rv_main_c_46_iftrue][17]/D
	# main_registers_r_reg[submodules][BIN_OP_DIV_main_c_20_registers]    [self]      [1][BIN_OP_MINUS_BIN_OP_DIV_main_c_20_c_571_right][12]/C
	# Offset should be first tok after self str
	if "[self]" in reg_name:
		halves = reg_name.split("[self]")
		second_half = halves[1]
		toks = second_half.split("]")
		self_offset = int(toks[0].replace("[",""))
		return self_offset
	
	elif "[global_regs]" in reg_name:
		# Global regs are always in relative stage 0
		return 0
	elif "[volatile_global_regs]" in reg_name:
		# Volatile global regs are always in relative stage 0???
		return 0
		
	else:
		print "GET_SELF_OFFSET_FROM_REG_NAME no self, no global, no volatile globals",reg_name
		sys.exit(0)
		

def GET_MOST_MATCHING_LOGIC_INST_AND_ABS_REG_INDEX(reg_name, inst_name, logic, parser_state, TimingParamsLookupTable):
	LogicLookupTable = parser_state.LogicInstLookupTable
	
	# Get submodule inst
	inst = GET_MOST_MATCHING_LOGIC_INST_FROM_REG_NAME(reg_name, inst_name, logic, LogicLookupTable)
	
	# Get stage indices
	when_used = SYN.GET_ABS_SUBMODULE_STAGE_WHEN_USED(inst, inst_name, logic, parser_state, TimingParamsLookupTable)
	
	# Global funcs are always 0 clock and thus offset 0
	if LogicLookupTable[inst].uses_globals:
		self_offset = 0
	else:
		# Do normal check
		self_offset = GET_SELF_OFFSET_FROM_REG_NAME(reg_name)
	abs_stage = when_used + self_offset
	return inst, abs_stage
	

# [possible,stage,indices]
def FIND_ABS_STAGE_RANGE_FROM_TIMING_REPORT(parsed_timing_report, inst_name, logic, parser_state, TimingParamsLookupTable):	
	LogicLookupTable = parser_state.LogicInstLookupTable
	timing_params = TimingParamsLookupTable[inst_name]
	total_latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	last_stage = total_latency
	
	start_reg_name = parsed_timing_report.start_reg_name
	end_reg_name = parsed_timing_report.end_reg_name
	
	#print "PATH:", start_reg_name, "=>", end_reg_name
	
	# all possible reg paths considering renaming
	# Start names
	start_names = [start_reg_name]
	start_aliases = []
	if start_reg_name in parsed_timing_report.reg_merged_with:
		start_aliases = parsed_timing_report.reg_merged_with[start_reg_name]
	start_names += start_aliases
	
	# all possible reg paths considering renaming
	# end names
	end_names = [end_reg_name]
	end_aliases = []
	if end_reg_name in parsed_timing_report.reg_merged_with:
		end_aliases = parsed_timing_report.reg_merged_with[end_reg_name]
	end_names += end_aliases
	
	
	possible_stages_indices = []	
	# Loop over all possible start end pairs
	for start_name in start_names:
		for end_name in end_names:
			# Check this path
			if REG_NAME_IS_INPUT_REG(start_name) and REG_NAME_IS_OUTPUT_REG(end_name):
				print "	Path to and from register IO regs in top..."
				possible_stages_indices.append(0)
			elif REG_NAME_IS_INPUT_REG(start_name) and not(REG_NAME_IS_OUTPUT_REG(end_name)):
				print "	Path from input register to pipeline logic..."
				#start_stage = 0
				possible_stages_indices.append(0)
			elif not(REG_NAME_IS_INPUT_REG(start_name)) and REG_NAME_IS_OUTPUT_REG(end_name):
				print "	Path from pipeline logic to output register..."
				possible_stages_indices.append(last_stage)
			elif REG_NAME_IS_OUTPUT_REG(start_name):
				print "	Path is loop from global register acting as output register from last stage?"
				print "	Is this normal?"
				sys.exit(0)
				# Starting at output reg must be global combinatorial loop path in last stage
				possible_stages_indices.append(last_stage)
			elif REG_NAME_IS_INPUT_REG(end_name):
				# Ending at input reg must be global combinatorial loop in first stage
				print "	Path is loop from global register acting as input reg in first stage?"
				print "	Is this normal?"
				sys.exit(0)
				possible_stages_indices.append(0)
			else:
				# Start
				start_inst, found_start_reg_abs_index = GET_MOST_MATCHING_LOGIC_INST_AND_ABS_REG_INDEX(start_name, inst_name, logic, parser_state, TimingParamsLookupTable)
				# End
				end_inst, found_end_reg_abs_index = GET_MOST_MATCHING_LOGIC_INST_AND_ABS_REG_INDEX(end_name, inst_name, logic, parser_state, TimingParamsLookupTable)
							
				# Expect a one stage length path
				if found_end_reg_abs_index - found_start_reg_abs_index != 1:
					# Not normal path?
					
					'''
					# Globals can be same module same reg index?
					if "[global_regs]" in start_name and "[global_regs]" in end_name and found_start_reg_abs_index==found_end_reg_abs_index:
						possible_stages_indices.append(found_start_reg_abs_index)
					
						# Dont need to handle volatiles separately since like regular regs in terms of path in pipeline?
						
					elif "[volatile_global_regs]" in start_name and "[volatile_global_regs]" in end_name and found_start_reg_abs_index<=found_end_reg_abs_index:
						possible_stages_indices = range(found_start_reg_abs_index,found_end_reg_abs_index+1)
						print "Double check volatile regs:"
						print "	Start?:",found_start_reg_abs_index, start_name, start_inst
						print "	End?:",found_end_reg_abs_index, end_name, end_inst
			
					else:
					'''
					print "	Unclear stages from register names..."
					print "	Start?:",found_start_reg_abs_index, start_name
					print "		", start_inst.replace(C_TO_LOGIC.SUBMODULE_MARKER, "/")
					print "	End?:",found_end_reg_abs_index, end_name
					print "		", end_inst.replace(C_TO_LOGIC.SUBMODULE_MARKER, "/")
					
					# Global regs do not have self offset so hard to know exact offset
					# Prefer if one end of the path isnt a global
					if "global_regs]" not in start_name and  "global_regs]" in end_name:
						# Prefer start reg
						possible_stages_indices.append(found_start_reg_abs_index+1) # Reg0 starts stage 1
					elif "global_regs]" in start_name and  "global_regs]" not in end_name:
						# Prefer end reg
						possible_stages_indices.append(found_end_reg_abs_index) # Reg1 ends stage 1
					else:
						# Do dumb inclusive range plus +1 before and after if globals?
						# Uh... totally guessing now?
						print "Really unclear regs?"
						guessed_start_reg_abs_index = min(found_start_reg_abs_index,found_end_reg_abs_index-1) # -1 since corresponding start index from end index is minus 1 
						guessed_end_reg_abs_index = max(found_start_reg_abs_index+1,found_end_reg_abs_index) # +1 since corresponding end index from start index is plus 1
						# Stage range bounds
						min_bound = guessed_start_reg_abs_index+1
						max_bound = guessed_end_reg_abs_index+1

						# PLus 1 before and after if globals in the mix?
						if "global_regs]" in start_name:
							min_bound = max(0, min_bound-1)
						if "global_regs]" in end_name:
							max_bound = min(last_stage+1, max_bound+1)
						stage_range = range(min_bound, max_bound)
						for stage in stage_range:
							possible_stages_indices.append(stage)				
						
					'''
						#print "CHECK THIS!!!!^"
						#raw_input("Press Enter to continue...")
						#sys.exit(0)
						
						#If same value then assume? idk wtf
						if found_end_reg_abs_index == found_start_reg_abs_index:
							#### ??? possible_stages_indices.append(found_start_reg_abs_index+1) # comb->(stage0)->reg0->(stage1)->reg1 is a stage 1 path 
							# Fuckit
							possible_stages_indices.append(found_end_reg_abs_index)
							if found_start_reg_abs_index+1 <= last_stage:
								possible_stages_indices.append(found_start_reg_abs_index+1)
						else:
							# Sort them into new values
							guessed_start_reg_abs_index = min(found_start_reg_abs_index,found_end_reg_abs_index-1) # -1 since corresponding start index from end index is minus 1 
							guessed_end_reg_abs_index = max(found_start_reg_abs_index+1,found_end_reg_abs_index) # +1 since corresponding end index from start index is plus 1 
							if guessed_end_reg_abs_index - guessed_start_reg_abs_index == 1:
								# This seems like we got the start stage right?
								#print "		Swapped indices, start reg index =", guessed_start_reg_abs_index
								possible_stages_indices.append(guessed_start_reg_abs_index+1) # comb->(stage0)->reg0->(stage1)->reg1 is a stage 1 path 
							else:
								# Got a range of stages?
								#print "		Found range of reg stage indices:", guessed_start_reg_abs_index,"to", guessed_end_reg_abs_index
								rv = range(guessed_start_reg_abs_index+1, guessed_end_reg_abs_index+1)
								# Remove last stage
								if last_stage in rv:
									rv = range(guessed_start_reg_abs_index+1, guessed_end_reg_abs_index)
								possible_stages_indices += rv
								
					''' 					
				else:
					# Normal 1 stage path
					possible_stages_indices.append(found_start_reg_abs_index+1) # +1 since reg0 means stage 1 path
	
	
	# Get real range accounting for duplcates from renamed/merged regs
	rv = sorted(list(set(possible_stages_indices)))
	
	
	print "Stage range:",rv
	
	return rv
		
class ParsedTimingReport:
	def __init__(self, syn_output):
		
		# Doing multiple things
		cmd_outputs = syn_output.split(TIMING_REPORT_DIVIDER)
		single_timing_report = cmd_outputs[0]
		worst_paths_timing_report = None
		if len(cmd_outputs) > 2:
			worst_paths_timing_report = cmd_outputs[2] # divider is printed in log twice
		
		
		# SINGLE TIMING REPORT STUFF
		self.logic_levels = 0
		self.slack_ns = None
		self.source_ns_per_clock = 0.0
		self.start_reg_name = None
		self.end_reg_name = None
		self.path_delay = None
		self.logic_delay = None
		self.orig_text = single_timing_report
		#self.reg_merged_into = dict() # dict[orig_sig] = new_sig
		self.reg_merged_with = dict() # dict[new_sig] = [orig,sigs]
		self.has_loops = True
		self.has_latch_loops = True
		
		# Parsing:	
		syn_output_lines = single_timing_report.split("\n")
		prev_line=""
		for syn_output_line in syn_output_lines:
			# LOGIC LEVELS
			tok1="Logic Levels:           "
			if tok1 in syn_output_line:
				self.logic_levels = int(syn_output_line.replace(tok1,"").split("(")[0].strip())
				
			# SLACK_NS
			tok1="Slack ("
			tok2="  (required time - arrival time)"
			if (tok1 in syn_output_line) and (tok2 in syn_output_line):
				slack_w_unit = syn_output_line.replace(tok1,"").replace(tok2,"").split(":")[1].strip()
				slack_ns_str = slack_w_unit.strip("ns")
				self.slack_ns = float(slack_ns_str)
				
				
			# CLOCK PERIOD
			tok1="Source:                 "
			tok2="                            (rising edge-triggered"
			tok3="period="
			if (tok1 in prev_line) and (tok2 in syn_output_line):
				toks = syn_output_line.split(tok3)
				per_and_trash = toks[len(toks)-1]
				period = per_and_trash.strip("ns})")
				self.source_ns_per_clock = float(period)
				# START REG
				self.start_reg_name = prev_line.replace(tok1,"").strip()
				# Remove everything after last "/"
				toks = self.start_reg_name.split("/")
				self.start_reg_name = "/".join(toks[0:len(toks)-1])
				
				
			
			# END REG
			tok1="Destination:            "
			if (tok1 in prev_line) and (tok2 in syn_output_line):
				self.end_reg_name = prev_line.replace(tok1,"").strip()
				# Remove everything after last "/"
				toks = self.end_reg_name.split("/")
				self.end_reg_name = "/".join(toks[0:len(toks)-1])				
				
			
				
			#####################################################################################################
			# Data path delay in report is not the total delay in the path
			# OMG slack is not jsut a funciton of slack=goal-delay
			# Wow so dumb of me
			# VIVADO prints out for 1ns clock
			'''
			Slack (VIOLATED) :        -1.021ns  (required time - arrival time)
			Source:                 add0/U0/i_synth/ADDSUB_OP.ADDSUB/SPEED_OP.DSP.OP/DSP48E1_BODY.ALIGN_ADD/SML_DELAY/i_pipe/opt_has_pipe.first_q_reg[0]/C
									(rising edge-triggered cell FDRE clocked by clk  {rise@0.000ns fall@0.500ns period=1.000ns})
			Destination:            add0/U0/i_synth/ADDSUB_OP.ADDSUB/SPEED_OP.DSP.OP/DSP48E1_BODY.ALIGN_ADD/DSP2/DSP/A[0]
									(rising edge-triggered cell DSP48E1 clocked by clk  {rise@0.000ns fall@0.500ns period=1.000ns})
			Path Group:             clk
			Path Type:              Setup (Max at Slow Process Corner)
			Requirement:            1.000ns  (clk rise@1.000ns - clk rise@0.000ns)
			Data Path Delay:        0.688ns  (logic 0.254ns (36.896%)  route 0.434ns (63.104%))
			'''
			# ^ Actual operating freq period = goal - slack
			# period = 1.0 - (-1.021) = 2.021 ns
			''' Another example from own program
			Slack (VIOLATED) :        -0.738ns  (required time - arrival time)
			Source:                 main_registers_r_reg[submodules][BIN_OP_PLUS_main_c_9_registers][submodules][uint24_negate_BIN_OP_PLUS_main_c_9_c_108_registers][submodules][BIN_OP_PLUS_bit_math_h_17_registers][self][0][left_resized][11]/C
									(rising edge-triggered cell FDRE clocked by sys_clk_pin  {rise@0.000ns fall@0.500ns period=1.000ns})
			Destination:            main_registers_r_reg[submodules][BIN_OP_PLUS_main_c_9_registers][submodules][int26_abs_BIN_OP_PLUS_main_c_9_c_123_registers][self][0][rv_bit_math_h_58_0][21]/D
									(rising edge-triggered cell FDRE clocked by sys_clk_pin  {rise@0.000ns fall@0.500ns period=1.000ns})
			Path Group:             sys_clk_pin
			Path Type:              Setup (Max at Slow Process Corner)
			Requirement:            1.000ns  (sys_clk_pin rise@1.000ns - sys_clk_pin rise@0.000ns)
			Data Path Delay:        1.757ns  (logic 1.258ns (71.599%)  route 0.499ns (28.401%))
			'''
			# 1.0 - (-0.738) = 1.738ns
			tok1="Data Path Delay:        "
			if tok1 in syn_output_line:
				self.path_delay = self.source_ns_per_clock - self.slack_ns
			#####################################################################################################
			
			
			# LOGIC DELAY
			tok1="Data Path Delay:        "
			if tok1 in syn_output_line:
				self.logic_delay = float(syn_output_line.split("  (logic ")[1].split("ns (")[0])			
				
				
			# LOOPS!
			if "There are 0 combinational loops in the design." in syn_output_line:
				self.has_loops = False
			if "There are 0 combinational latch loops in the design" in syn_output_line:
				self.has_latch_loops = False
			if "[Synth 8-295] found timing loop." in syn_output_line:
				#print single_timing_report
				print syn_output_line
				#print "FOUND TIMING LOOPS!"
				#print 

				# Do debug?
				#latency=0
				#do_debug=True
				#print "ASSUMING LATENCY=",latency
				#MODELSIM.DO_OPTIONAL_DEBUG(do_debug, latency)
				#sys.exit(0)
			
			# OK so apparently mult by self results in constants
			# See scratch notes "wtf_multiply_by_self" dir
			if ( (("propagating constant" in syn_output_line) and ("across sequential element" in syn_output_line) and ("_output_reg_reg" in syn_output_line)) or
			     (("propagating constant" in syn_output_line) and ("across sequential element" in syn_output_line) and ("_intput_reg_reg" in syn_output_line)) ):
				print syn_output_line
				
				
			# Constant outputs?	
			if (("port return_output[" in syn_output_line) and ("] driven by constant " in syn_output_line)):
				print single_timing_report
				print "Unconnected or constant ports!? Wtf man"
				print syn_output_line
				# Do debug?
				#latency=1
				#do_debug=True
				#print "ASSUMING LATENCY=",latency
				#MODELSIM.DO_OPTIONAL_DEBUG(do_debug, latency)
				sys.exit(0)

			
			# Unconnected ports are maybe problem?
			if ("design " in syn_output_line) and (" has unconnected port " in syn_output_line):
				if "unconnected port clk" in syn_output_line:
					# Clock NOT OK to disconnect
					print "Disconnected clock!?",syn_output_line
					sys.exit(0)
				#else:
				#	print syn_output_line
				
				
			# REG MERGING
			# INFO: [Synth 8-4471] merging register 
			# Build dict of per bit renames
			tok1 = "INFO: [Synth 8-4471] merging register"
			if tok1 in syn_output_line:
				# Get left and right names
				'''
				INFO: [Synth 8-4471] merging register 'main_registers_r_reg[submodules][BIN_OP_GT_main_c_12_registers][self][0][same_sign]' into 'main_registers_r_reg[submodules][BIN_OP_GT_main_c_8_registers][self][0][same_sign]' [/media/1TB/Dropbox/HaramNailuj/ZYBO/idea/single_timing_report/main/main_4CLK.vhd:25]
				INFO: [Synth 8-4471] merging register 'main_registers_r_reg[submodules][BIN_OP_GT_main_c_12_registers][self][1][left][31:0]' into 'main_registers_r_reg[submodules][BIN_OP_GT_main_c_8_registers][self][1][left][31:0]' [/media/1TB/Dropbox/HaramNailuj/ZYBO/idea/single_timing_report/main/main_4CLK.vhd:25]
				'''
				# Split left and right on "into"
				line_toks = syn_output_line.split("' into '")
				left_text = line_toks[0]
				right_text = line_toks[1]
				left_reg_text = left_text.split("'")[1]
				right_reg_text = right_text.split("'")[0]
				# Do regs have a bit width or signal name?
				left_has_bit_width = ":" in left_reg_text
				right_has_bit_width = ":" in right_reg_text
				
				# Break a part brackets
				left_reg_toks = left_reg_text.split("[")
				right_reg_toks = right_reg_text.split("[")
				 
				
				# Get left and right signal names per bit (if applicable)
				left_names = []
				if left_has_bit_width:
					# What is bit width
					
					#print left_reg_toks
					width_str = left_reg_toks[len(left_reg_toks)-1].strip("]")
					width_toks = width_str.split(":")
					left_index = int(width_toks[0])
					right_index = int(width_toks[1])
					start_index = min(left_index,right_index)
					end_index = max(left_index,right_index)
					# What is signal base name?
					#print "width_str",width_str
					left_name_no_bitwidth = left_reg_text.replace("["+width_str+"]","")
					#print left_reg_text
					#print "left_name_no_bitwidth",left_name_no_bitwidth
					# Add to left names list
					for i in range(start_index,end_index+1):
						left_name_with_bit = left_name_no_bitwidth + "[" + str(i) + "]"
						left_names.append(left_name_with_bit)
				else:
					# No bit width on signal
					left_names.append(left_reg_text)
						
			
						
				right_names = []
				if right_has_bit_width:
					# What is bit width
					#print right_reg_text
					#print right_reg_toks
					width_str = right_reg_toks[len(right_reg_toks)-1].strip("]")
					width_toks = width_str.split(":")
					left_index = int(width_toks[0])
					right_index = int(width_toks[1])
					start_index = min(left_index,right_index)
					end_index = max(left_index,right_index)
					# What is signal base name?
					right_name_no_bitwidth = right_reg_text.replace("["+width_str+"]","")
					# Add to right names list
					for i in range(start_index,end_index+1):
						right_name_with_bit = right_name_no_bitwidth + "[" + str(i) + "]"
						right_names.append(right_name_with_bit)
				else:
					# No bit width on signal
					right_names.append(right_reg_text)
					
					
				#print left_names[0:2]
				#print right_names[0:2]
				
				# Need same count
				if len(left_names) != len(right_names):
					print "Reg merge len(left_names) != len(right_names) ??"
					print "left_names",left_names
					print "right_names",right_names
					sys.exit(0)
				
				for i in range(0, len(left_names)):
					#if left_names[i] in self.reg_merged_into and (self.reg_merged_into[left_names[i]] != right_names[i]):
					#	print "How to deal with ",left_names[i], "merged in to " ,self.reg_merged_into[left_names[i]] , "and ", right_names[i]
					#	sys.exit(0)
					
					#self.reg_merged_into = dict() # dict[orig_sig] = new_sig
					#self.reg_merged_with = dict() # dict[new_sig] = [orig,sigs]
					#self.reg_merged_into[left_names[i]] = right_names[i]
					if not(right_names[i] in self.reg_merged_with):
						self.reg_merged_with[right_names[i]] = []
					self.reg_merged_with[right_names[i]].append(left_names[i])
				
			
			# SAVE PREV LINE
			prev_line = syn_output_line
		
		# Catch problems
		if self.slack_ns is None:
			print "Something is wrong with this timing report?"
			print single_timing_report
			#latency=0
			#do_debug=True
			#print "ASSUMING LATENCY=",latency
			#MODELSIM.DO_OPTIONAL_DEBUG(do_debug, latency)					
			sys.exit(0)
		
		#LOOPS
		if self.has_loops or self.has_latch_loops:
			#print single_timing_report
			#print syn_output_line
			print "TIMING LOOPS!"
			## Do debug?
			#latency=0
			#do_debug=True
			#print "ASSUMING LATENCY=",latency
			#MODELSIM.DO_OPTIONAL_DEBUG(do_debug, latency)
			#sys.exit(0)
		
		
		# Multiple timign report stuff
		self.worst_paths = None # List of tuples[ (start,end,path_delay), ...,.,.,.]
		# Also duh just another list of timing reports
		self.worst_path_reports = None
		
		if worst_paths_timing_report is None:
			return
		self.worst_paths = []
		self.worst_path_reports = []
		
		# Split this multi timing report into individual ones
		worst_path_timing_reports = worst_paths_timing_report.split("                         slack                                 ")	
		for worst_path_timing_report in worst_path_timing_reports:
			parsed_report = ParsedTimingReport(worst_path_timing_report)
			# Add to list of tuples
			self.worst_paths.append( (parsed_report.start_reg_name, parsed_report.end_reg_name, parsed_report.path_delay) )
			# And add report 
			self.worst_path_reports.append(parsed_report)
			
			
			

def GET_SLACK_NS(syn_output):
	parsed_timing_report = ParsedTimingReport(syn_output)
	return parsed_timing_report.slack_ns
	
def GET_NS_PER_CLOCK(syn_output):
	parsed_timing_report = ParsedTimingReport(syn_output)
	return parsed_timing_report.source_ns_per_clock
	
def GET_START_END_REGS(syn_output):
	parsed_timing_report = ParsedTimingReport(syn_output)
	return parsed_timing_report.start_reg_name,parsed_timing_report.end_reg_name
	

def WRITE_FINAL_FILES(inst_name, Logic,TimingParamsLookupTable, parser_state):
	# This writes:
	# 	The plain old main.vhd entity of the best timing result
	# 	The read_vhdl.tcl containing most of the gnerated vhdl includes
	output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)
	
	# Write an entity without timing info so name stays the same
	VHDL.WRITE_VHDL_ENTITY(inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable, name_timing_info=False)
		
	# Write read_vhdl.tcl
	clock_mhz = 1000.0 #doesnt matter read_vhdl only
	tcl = GET_SYN_IMP_AND_REPORT_TIMING_TCL(inst_name, Logic,output_directory,TimingParamsLookupTable, clock_mhz, parser_state)
	rv_lines = []
	for line in tcl.split('\n'):
		if "read_vhdl" in line:
			rv_lines.append(line)
	
	rv = ""
	for line in rv_lines:
		rv += line + "\n"
	
	# One more read_vhdl line for the final entity	with constant name
	top_file_path = output_directory + "/" + Logic.func_name + ".vhd"
	rv += "read_vhdl -library work {" + top_file_path + "}\n"
		
	# Write file
	out_filename = "read_vhdl.tcl"
	out_filepath = output_directory+"/"+out_filename
	f=open(out_filepath,"w")
	f.write(rv)
	f.close()


def GET_SYN_IMP_AND_REPORT_TIMING_TCL(inst_name, Logic,output_directory,TimingParamsLookupTable,clock_mhz, parser_state):
	clk_xdc_filepath = WRITE_CLK_XDC(output_directory, clock_mhz)

	# Bah tcl doesnt like brackets in file names
	# Becuase dumb
	
	timing_params = TimingParamsLookupTable[inst_name]
	rv = ""
	
	# Add in VHDL 2008 fixed/float support?
	rv += "add_files -norecurse " + VIVADO_DIR + "/scripts/rt/data/fixed_pkg_c.vhd\n"
	rv += "set_property library ieee_proposed [get_files " + VIVADO_DIR + "/scripts/rt/data/fixed_pkg_c.vhd]\n"
	rv += "add_files -norecurse " + VIVADO_DIR + "/scripts/rt/data/float_pkg_c.vhd\n"
	rv += "set_property library ieee_proposed [get_files " + VIVADO_DIR + "/scripts/rt/data/float_pkg_c.vhd]\n"
	
	# Read in vhdl files with a single (faster than multiple) read_vhdl
	files_txt = ""
	
	# C defined structs
	files_txt += SYN.SYN_OUTPUT_DIRECTORY + "/" + "c_structs_pkg" + VHDL.VHDL_PKG_EXT + " "
	
	# Entity file
	entity_filename = VHDL.GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + ".vhd"
	files_txt += output_directory + "/" + entity_filename + " "
	
	# Top not shared
	files_txt += output_directory + "/" +  VHDL.GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + "_top.vhd" + " "
	
	# ~~~~ NON ZERO CLOCK
	# Maybe timing params should only be for non-zero clock?
	# For now try to filter?
	NonZeroClkTimingParamsLookupTable = dict()
	ZeroClkTimingParamsLookupTable = dict()
	for inst_i in TimingParamsLookupTable:
		timing_params_i = TimingParamsLookupTable[inst_i]
		if timing_params_i.slices != []:
			NonZeroClkTimingParamsLookupTable[inst_i] = timing_params_i
			ZeroClkTimingParamsLookupTable[inst_i] = SYN.TimingParams(inst_i, parser_state.LogicInstLookupTable[inst_i])
		else:
			# Is already zero clock
			ZeroClkTimingParamsLookupTable[inst_i] = timing_params_i
		
	# Files are per func name + timing param so dont duplicate
	submodule_funcs = []
	for submodule_inst_name in NonZeroClkTimingParamsLookupTable:
		submodule_logic = parser_state.LogicInstLookupTable[submodule_inst_name]
		# ONly write non vhdl
		if not submodule_logic.is_vhdl_func and not submodule_logic.is_vhdl_expr:
			submodule_entity_filename = VHDL.GET_ENTITY_NAME(submodule_inst_name, submodule_logic, NonZeroClkTimingParamsLookupTable, parser_state) + ".vhd"
			if submodule_entity_filename not in submodule_funcs:			
				submodule_syn_output_directory = SYN.GET_OUTPUT_DIRECTORY(submodule_logic)
				files_txt += submodule_syn_output_directory + "/" + submodule_entity_filename + " "
				submodule_funcs.append(submodule_entity_filename)		
	
	
	# ~~~~ ALL ZERO CLOCK
	# Majority of funcs will have zero clock instance too (lower level funcs)
	# All instances are from ZeroClkTimingParamsLookupTable so just pick any instance
	for func_name in parser_state.FuncLogicLookupTable:
		if func_name in parser_state.FuncToInstances:
			submodule_inst_name = parser_state.FuncToInstances[func_name][0]
			submodule_logic = parser_state.FuncLogicLookupTable[func_name]
			# ONly write non vhdl
			if submodule_logic.is_vhdl_func or submodule_logic.is_vhdl_expr:
				continue
			submodule_entity_filename = VHDL.GET_ENTITY_NAME(submodule_inst_name, submodule_logic,ZeroClkTimingParamsLookupTable, parser_state) + ".vhd"	
			submodule_syn_output_directory = SYN.GET_OUTPUT_DIRECTORY(submodule_logic)
			files_txt += submodule_syn_output_directory + "/" + submodule_entity_filename + " "
	
	
	# Single read vhdl line
	rv += "read_vhdl -library work {" + files_txt + "}\n" #-vhdl2008 
	
	# Single xdc with single clock for now
	rv += 'read_xdc {' + clk_xdc_filepath + '}\n'
	
	################
	# MSG Config
	#
	# ERROR WARNING: [Synth 8-312] ignoring unsynthesizable construct: non-synthesizable procedure call
	rv += "set_msg_config -id {Synth 8-312} -new_severity ERROR" + "\n"
	# ERROR WARNING: [Synth 8-614] signal is read in the process but is not in the sensitivity list
	rv += "set_msg_config -id {Synth 8-614} -new_severity ERROR" + "\n"
	# ERROR WARNING: [Synth 8-2489] overwriting existing secondary unit arch
	rv += "set_msg_config -id {Synth 8-2489} -new_severity ERROR" + "\n"
	
	# Set high limit for these msgs
	# [Synth 8-4471] merging register
	rv += "set_msg_config -id {Synth 8-4471} -limit 10000" + "\n"
	# [Synth 8-3332] Sequential element removed
	rv += "set_msg_config -id {Synth 8-3332} -limit 10000" + "\n"
	# [Synth 8-3331] design has unconnected port
	rv += "set_msg_config -id {Synth 8-3331} -limit 10000" + "\n"
	# [Synth 8-5546] ROM won't be mapped to RAM because it is too sparse
	rv += "set_msg_config -id {Synth 8-5546} -limit 10000" + "\n"
	
	# SYNTHESIS@@@@@@@@@@@@@@!@!@@@!@
	rv += "synth_design -top " + VHDL.GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + "_top -part " + VIVADO_PART + " \n"
	

	# Report clocks
	#rv += "report_clocks" + "\n"
	# Report timing
	#rv += "report_timing" + "\n"
	rv += "report_timing_summary -setup" + "\n"
	
	return rv


# return path 
def WRITE_CLK_XDC(output_directory, clock_mhz):
	#out_filename = str(clock_mhz) + "MHz.xdc"
	out_filename = "clock.xdc"
	out_filepath = output_directory+"/"+out_filename
	
	# MHX to ns
	ns = (1.0 / clock_mhz) * 1000.0
	
	f=open(out_filepath,"w")
	f.write("create_clock -add -name sys_clk_pin -period " + str(ns) + " -waveform {0 " + str(ns/2.0) + "} [get_ports clk]\n");
	f.close()
	return out_filepath
	

# return path to tcl file
def WRITE_SYN_IMP_AND_REPORT_TIMING_TCL_FILE(inst_name, Logic,output_directory,TimingParamsLookupTable, clock_mhz, parser_state):
	syn_imp_and_report_timing_tcl = GET_SYN_IMP_AND_REPORT_TIMING_TCL(inst_name,Logic,output_directory,TimingParamsLookupTable, clock_mhz,parser_state)
	timing_params = TimingParamsLookupTable[inst_name]
	hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)	
	out_filename = Logic.func_name + "_" +  str(timing_params.GET_TOTAL_LATENCY(parser_state,TimingParamsLookupTable)) + "CLK"+ hash_ext + ".syn.tcl"
	out_filepath = output_directory+"/"+out_filename
	f=open(out_filepath,"w")
	f.write(syn_imp_and_report_timing_tcl)
	f.close()
	return out_filepath
	
	
# Returns parsed timing report
def SYN_AND_REPORT_TIMING(inst_name, Logic, parser_state, TimingParamsLookupTable, clock_mhz, total_latency, hash_ext = None, use_existing_log_file = True):
	
	# Hard rule for now, functions with globals must be zero clk
	if total_latency > 0 and len(Logic.global_wires) > 0:
		print "Can't synthesize atomic global function '", inst_name, "' with latency = ", total_latency
		sys.exit(0)
		
	
	# Timing params for this logic
	timing_params = TimingParamsLookupTable[inst_name]
	
	#print "SYN: FUNC_NAME:", C_TO_LOGIC.LEAF_NAME(Logic.func_name)
	# First create syn/imp directory for this logic
	output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic)	

	
	if not os.path.exists(output_directory):
		os.makedirs(output_directory)
		
	
	# Set log path
	if hash_ext is None:
		hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
	log_path = output_directory + "/vivado" + "_" +  str(total_latency) + "CLK" + hash_ext + ".log"
	#vivado -mode batch -source <your_Tcl_script>
			
	# Use same configs based on to speed up run time?
	log_to_read = log_path
	
	# If log file exists dont run syn
	if os.path.exists(log_to_read) and use_existing_log_file:
		#print "SKIPPED:", syn_imp_bash_cmd
		print "Reading log", log_to_read
		f = open(log_path, "r")
		log_text = f.read()
		f.close()
	else:
		# O@O@()(@)Q@$*@($_!@$(@_$(
		# Here stands a moument to "[Synth 8-312] ignoring unsynthesizable construct: non-synthesizable procedure call"
		# meaning "procedure is named the same as the entity"
		#VHDL.GENERATE_PACKAGE_FILE(Logic, parser_state, TimingParamsLookupTable, timing_params, output_directory)
		VHDL.WRITE_VHDL_ENTITY(inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable)
		VHDL.WRITE_VHDL_TOP(inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable)
			
		# Write xdc describing clock rate
		
		# Write a syn tcl into there
		syn_imp_tcl_filepath = WRITE_SYN_IMP_AND_REPORT_TIMING_TCL_FILE(inst_name, Logic,output_directory,TimingParamsLookupTable, clock_mhz,parser_state)
		
		# Execute vivado sourcing the tcl
		syn_imp_bash_cmd = (
			VIVADO_PATH + " "
			"-journal " + output_directory + "/vivado.jou" + " " + 
			"-log " + log_path + " " +
			VIVADO_DEFAULT_ARGS + " " + 
			'-source "' + syn_imp_tcl_filepath + '"' )  # Quotes since I want to keep brackets in inst names
		
		print "Running:", syn_imp_bash_cmd
		log_text = SYN.GET_SHELL_CMD_OUTPUT(syn_imp_bash_cmd)
		
		
	
	return ParsedTimingReport(log_text)
	
	
def REG_NAME_IS_INPUT_REG(reg_name):
	if REG_NAME_IS_IO_REG(reg_name):
		# Know there is no submodules simple <name>[index]
		reg_name_no_index = reg_name.split("[")[0]
		if reg_name_no_index.endswith("_input_reg_reg"):
			return True
	return False
	
def REG_NAME_IS_OUTPUT_REG(reg_name):
	if REG_NAME_IS_IO_REG(reg_name):
		# Know there is no submodules simple <name>[index]
		reg_name_no_index = reg_name.split("[")[0]
		if reg_name_no_index.endswith("_output_reg_reg"):
			return True
	return False
	
	
def REG_NAME_IS_IO_REG(reg_name):
	# IO wont have vivado submodule markers
	return "/" not in reg_name
	
	#return not REG_NAME_IS_SUBMODULE(reg_name) and not REG_NAME_IS_SELF(reg_name)
	#return not("_registers_r_reg[submodules]" in reg_name) and not("_registers_r_reg[self]" in reg_name) and not("[global_regs]" in reg_name)



def GET_RAW_HDL_SUBMODULE_LATENCY_INDEX_FROM_REG_NAME(reg_name, logic):
	# Break apart using brackets
	toks = reg_name.split("[")
	# ['main_registers_r_reg', 'submodules]', 'BIN_OP_GT_main_c_8_registers]', 'self]', '2]', 'left]', '9]']
	# ['main_registers_r_reg', 'submodules]', 'BIN_OP_PLUS_main_c_29_registers]', 'self]', '2]', 'left_as_signed]', '19]_srl6']
	
	# Get latency index
	latency_pos = -1
	
	last_tok = toks[len(toks)-1].split("]")[0]
	# If last thing is number then is bit index
	if last_tok.isdigit():
		# Bit index is last so 5th to last
		latency_pos = len(toks)-3
	else:
		# Wire name is last
		latency_pos = len(toks)-2
		
	latency_index_tok = toks[latency_pos]
	latency_index = int(latency_index_tok.strip("[").strip("]"))
	
	return latency_index

	
# Try to make vivado reg name match inst name
def GET_INST_NAME_ADJUSTED_REG_NAME(reg_name):
	# Adjust reg name for best match
	
	
	# Remove submodule marker
	adj_reg_name = reg_name.replace("/","_")
	
	# Remove all indexes
	index_toks = adj_reg_name.split("[")
	# Remove ] from each index tok
	new_index_toks = []
	for index_tok in index_toks:
		new_index_toks.append(index_tok.replace("]",""))
		
	# If tok is a number then remove
	no_indices_toks = []
	for new_index_tok in new_index_toks:
		if not(new_index_tok.isdigit()):
			no_indices_toks.append(new_index_tok)
			
	# Recontruct with underscores
	constructed_reg_name = "_".join(no_indices_toks)
	
	# Remove double underscore
	new_reg_name = constructed_reg_name.replace("__","_").strip("_")
	
	return new_reg_name
	
# Get deepest in hierarchy possible match , msot specfic match
def GET_MOST_MATCHING_LOGIC_INST_FROM_REG_NAME(reg_name, inst_name, logic, LogicInstLookupTable):
	#print "DEBUG: REG:", reg_name
	
	# Get matching submoduel isnt, dont care about var names after self or globals
	if "[self]" in reg_name:
		reg_name = reg_name.split("[self]")[0]
	if "[global_regs]" in reg_name:
		#print "DEBUG: Found global reg:", reg_name
		reg_name = reg_name.split("[global_regs]")[0]
	if "[volatile_global_regs]" in reg_name:
		#print "DEBUG: Found volatile global reg:", reg_name
		reg_name = reg_name.split("[volatile_global_regs]")[0]
	# Also remove reg 
	reg_name = reg_name.replace("/registers_r_reg","")
	
	# Easier now since submodules are actual modules and show up with "/" in reg name
	reg_toks = reg_name.split("/")
	if len(reg_toks) == 1:
		#print "Is this real?"
		#print reg_name
		#sys.exit(0)
		return inst_name
		
	# Assume starts with main
	# Loop constructing more and more specific match
	curr_logic = logic # Assumed to be main
	curr_inst_name = inst_name
	curr_end_tok_index = 2 # First two toks joined
	while curr_end_tok_index <= len(reg_toks):
		curr_reg_str = "/".join(reg_toks[0:curr_end_tok_index])
		# Sanitze
		new_reg_name = GET_INST_NAME_ADJUSTED_REG_NAME(curr_reg_str)	
		#print "new_reg_name",new_reg_name
		# Find most matching submodule inst if possible
		if len(curr_logic.submodule_instances) > 0:
			max_match = 0.0
			max_match_submodule_inst = None
			for submodule_inst in curr_logic.submodule_instances:
				submodule_inst_name = curr_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + submodule_inst
				#Sanitize
				new_inst = submodule_inst_name.replace(C_TO_LOGIC.SUBMODULE_MARKER,"_").replace("[","_").replace("]","").replace(".","_")
				#print "new_inst",new_inst
				# Compare
				lib_match_amount = difflib.SequenceMatcher(None, new_reg_name, new_inst).ratio()
				lev_match_amount = Levenshtein.ratio(new_reg_name, new_inst)
				match_amount = lib_match_amount * lev_match_amount
				#print "match_amount",match_amount
				if match_amount > max_match:
					max_match = match_amount
					max_match_submodule_inst = submodule_inst_name
			
			if max_match_submodule_inst is None:
				print "Wtf?", curr_reg_str
				print "curr_inst_name",curr_inst_name
				sys.exit(0)
			
			# Use this submodule as next logic
			curr_logic = LogicInstLookupTable[max_match_submodule_inst]
			curr_inst_name = max_match_submodule_inst
			
		# Include next reg tok
		curr_end_tok_index = curr_end_tok_index + 1
		
	# Must have most matching inst now
	
	#print "DEBUG: INST:", max_match_submodule_inst
	
	return max_match_submodule_inst
