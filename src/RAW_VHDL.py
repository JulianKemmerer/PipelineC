#!/usr/bin/env python
import sys
import os
import copy
import math
from pycparser import c_parser, c_ast, c_generator # bleh for now

import C_TO_LOGIC
import SW_LIB
import VHDL



# Declare variables used internally to c built in C logic
def GET_RAW_HDL_WIRES_DECL_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	
	if logic.func_name.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX):
		wires_decl_text, package_stages_text = GET_UNARY_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state)
		return wires_decl_text
	elif logic.func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX):
		wires_decl_text, package_stages_text = GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
		return wires_decl_text
	elif logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME):	
		wires_decl_text, package_stages_text = GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
		return wires_decl_text
	# Is this bit manip raw HDL?
	elif SW_LIB.IS_BIT_MANIP(logic):
		wires_decl_text, package_stages_text = GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
		return wires_decl_text	
	# Mem uses no internal signals right now
	elif SW_LIB.IS_MEM(logic):
		return ""
	elif logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):	
		wires_decl_text, package_stages_text = GET_CONST_REF_RD_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
		return wires_decl_text
	elif logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SL_NAME) or logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SR_NAME):
		wires_decl_text, package_stages_text = GET_CONST_SHIFT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state)
		return wires_decl_text
	else:
		print "GET_RAW_HDL_WIRES_DECL_TEXT for", logic.func_name,"?",logic.c_ast_node.coord
		sys.exit(0)


def GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable	
	# Unary ops !
	if logic.func_name.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX):
		wires_decl_text, package_stages_text = GET_UNARY_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state)
		return package_stages_text
	# Binary ops + , ==, > etc
	elif logic.func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX):
		wires_decl_text, package_stages_text = GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
		return package_stages_text
	# IF STATEMENTS
	elif logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME):	
		wires_decl_text, package_stages_text = GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
		return package_stages_text	
	# Is this bit manip raw HDL?
	elif SW_LIB.IS_BIT_MANIP(logic):
		wires_decl_text, package_stages_text = GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
		return package_stages_text
	elif logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):	
		wires_decl_text, package_stages_text = GET_CONST_REF_RD_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
		return package_stages_text
	elif logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SL_NAME) or logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SR_NAME):
		wires_decl_text, package_stages_text = GET_CONST_SHIFT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state)
		return package_stages_text
	else:
		print "GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT for", logic.func_name,"?"
		sys.exit(0)
		
		
def GET_MEM_ARCH_DECL_TEXT(Logic, parser_state, TimingParamsLookupTable):
	if Logic.func_name.endswith("_" + SW_LIB.RAM_SP_RF+"_0"):
		return GET_RAM_SP_RF_ARCH_DECL_TEXT(Logic, parser_state, TimingParamsLookupTable, 0)
	elif Logic.func_name.endswith("_" + SW_LIB.RAM_SP_RF+"_2"):
		return GET_RAM_SP_RF_ARCH_DECL_TEXT(Logic, parser_state, TimingParamsLookupTable, 2)
	else:
		print "GET_MEM_ARCH_DECL_TEXT for func", Logic.func_name, "?"
		sys.exit(0)
			
def GET_MEM_PIPELINE_LOGIC_TEXT(Logic, parser_state, TimingParamsLookupTable):
	if Logic.func_name.endswith("_" + SW_LIB.RAM_SP_RF+"_0"):
		return GET_RAM_SP_RF_LOGIC_TEXT(Logic, parser_state, TimingParamsLookupTable, 0)
	elif Logic.func_name.endswith("_" + SW_LIB.RAM_SP_RF + "_2"):
		return GET_RAM_SP_RF_LOGIC_TEXT(Logic, parser_state, TimingParamsLookupTable, 2)
	else:
		print "GET_MEM_PIPELINE_LOGIC_TEXT for func", Logic.func_name, "?"
		sys.exit(0)
	
def GET_RAM_SP_RF_ARCH_DECL_TEXT(Logic, parser_state, TimingParamsLookupTable, clocks):
	# Is a clocked process assigning to global reg
	global_name = Logic.func_name.split("_"+SW_LIB.RAM_SP_RF)[0]
	global_c_type = Logic.wire_to_c_type[Logic.global_wires[0]]
	global_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(global_c_type,parser_state)
	
	# Know func looks like (addr_t addr, elem_t wd, uint1_t we)
	rv = '''
	signal ''' + global_name + ''' : ''' + global_vhdl_type + ''' := ''' + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(global_c_type,parser_state) + ''';
'''
	
	# Include IO regs if needed
	if clocks == 0:
		pass
	elif clocks == 2:
		addr_t = Logic.wire_to_c_type[Logic.inputs[0]]
		addr_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(addr_t,parser_state)
		elem_t = Logic.wire_to_c_type[Logic.inputs[1]]
		elem_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(elem_t,parser_state)
		we_t = Logic.wire_to_c_type[Logic.inputs[2]]
		we_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(we_t,parser_state)
		out_t = Logic.wire_to_c_type[Logic.outputs[0]]
		out_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(out_t,parser_state)
		rv += '''
		signal addr_r : ''' + addr_vhdl_type + ''' := ''' + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(addr_t,parser_state) + ''';
		signal wd_r : ''' + elem_vhdl_type + ''' := ''' + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(elem_t,parser_state) + ''';
		signal we_r : ''' + we_vhdl_type + ''' := ''' + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(we_t,parser_state) + ''';
		signal return_output_r : ''' + out_vhdl_type + ''' := ''' + VHDL.C_TYPE_STR_TO_VHDL_NULL_STR(out_t,parser_state) + ''';
'''
	else:
		print "Do other clocks for RAMSPRF"
		sys.exit(0)

	return rv
	
		
def GET_RAM_SP_RF_LOGIC_TEXT(Logic, parser_state, TimingParamsLookupTable, clocks):
	# Is a clocked process assigning to global reg
	global_name = Logic.func_name.split("_"+SW_LIB.RAM_SP_RF)[0]
	# Know func looks like (addr_t addr, elem_t wd, uint1_t we)
	if clocks == 0:
		rv = '''
		process(clk) is
		begin
			if rising_edge(clk) then
				if we(0) = '1' then
					''' + global_name + '''(to_integer(addr)) <= wd; 
				end if;
			end if;
		end process;
		-- Read first
		return_output <= '''  + global_name + '''(to_integer(addr));
'''
	elif clocks == 2:
		# In and out regs
		rv = '''
		process(clk) is
		begin
			if rising_edge(clk) then
				-- Register inputs
				addr_r <= addr;
				wd_r <= wd;
				we_r <= we;
				
				-- Read first
				return_output_r <= '''  + global_name + '''(to_integer(addr_r));
				-- RAM logic		
				if we_r(0) = '1' then
					''' + global_name + '''(to_integer(addr_r)) <= wd_r; 
				end if;
			end if;
		end process;
		-- Tie output ref to output
		return_output <= return_output_r;
'''
	else:
		print "Do other clocks for RAMSPRF fool"
		sys.exit(0)
	
	return rv
		
def GET_UNARY_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state):
	if str(logic.c_ast_node.op) == "!":
		return GET_UNARY_OP_NOT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state)
	else:
		print "GET_UNARY_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT for", str(logic.c_ast_node.op)
		sys.exit(0)


def GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	if str(logic.c_ast_node.op) == ">" or str(logic.c_ast_node.op) == ">=":
		return GET_BIN_OP_GT_GTE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params, str(logic.c_ast_node.op))
	if str(logic.c_ast_node.op) == "<" or str(logic.c_ast_node.op) == "<=":
		return GET_BIN_OP_LT_LTE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params, str(logic.c_ast_node.op))
	elif str(logic.c_ast_node.op) == "+":
		return GET_BIN_OP_PLUS_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
	elif str(logic.c_ast_node.op) == "-":
		return GET_BIN_OP_MINUS_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
	elif str(logic.c_ast_node.op) == "==" or str(logic.c_ast_node.op) == "!=":
		return GET_BIN_OP_EQ_NEQ_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state, str(logic.c_ast_node.op))
	elif str(logic.c_ast_node.op) == "&":
		return GET_BIN_OP_AND_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state)
	elif str(logic.c_ast_node.op) == "|":
		return GET_BIN_OP_OR_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params,parser_state)
	elif str(logic.c_ast_node.op) == "^":
		return GET_BIN_OP_XOR_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params)
	else:
		print "GET_BIN_OP_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT for", str(logic.c_ast_node.op)
		sys.exit(0)
		
def GET_BIN_OP_XOR_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# ONLY INTS FOR NOW
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	output_type = logic.wire_to_c_type[logic.outputs[0]]
	output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
	max_input_width = max(left_width,right_width)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
	
	
	wires_decl_text = '''
	left_resized : ''' + output_vhdl_type + ''';
	right_resized : ''' + output_vhdl_type + ''';
	return_output : ''' + output_vhdl_type + ''';
	right : ''' + right_vhdl_type + ''';
	left : ''' + left_vhdl_type + ''';
'''

	# MAx clocks is input reg and output reg
	#max_clocks = 2
	latency = timing_params.GET_TOTAL_LATENCY(parser_state)
	num_stages = latency + 1
	# Which stage gets the 1 LL ?
	stage_for_1ll = None
	if latency == 0:
		stage_for_1ll = 0
	elif latency == 1:
		# Rely on percent
		stage_for_1ll = 0
		# If slice is to left logic is on right
		if timing_params.slices[0] < 0.5:
			stage_for_1ll = 1	
	elif latency == 2:
		# INput reg and output reg logic in middle
		# IN stage 1 :  0 | 1 | 2
		stage_for_1ll = 1
	else:
		print "Cannot do a c built in XOR operation in", latency,  "clocks!"
		sys.exit(0)
		
		

	# 1 LL VHDL
	# VHDL text is just the IF for the stage in question
	text = ""
	text += '''
		if STAGE = ''' + str(stage_for_1ll) + ''' then
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(output_width) + ''');
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(output_width) + ''');
			write_pipe.return_output := write_pipe.left_resized xor write_pipe.right_resized;	
		end if;			
	'''


	return wires_decl_text, text
	
	

	
def GET_CONST_REF_RD_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params):
	#print "======="
	#print "logic.func_name",logic.func_name
	
	
	'''
	ref_str = logic.func_name.replace(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX + "_","")
	# Try to recover ref toks
	# Get ref toks as best we can
	ref_tok_strs = ref_str.split(C_TO_LOGIC.REF_TOK_DELIM)
	ref_toks = []
	for ref_tok_str in ref_tok_strs:
		if ref_tok_str.isdigit():
			# Array ref
			ref_toks.append(int(ref_tok_str))
		else:
			ref_toks.append(ref_tok_str)
			
	orig_var_name = ref_toks[0]
	#print "orig_var_name",orig_var_name
	'''
	
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	container_logic = LogicInstLookupTable[logic.containing_inst]
	
		
	# Copy parser state since not intending to change existing logic in this func
	parser_state_copy = copy.copy(parser_state)
	parser_state_copy.existing_logic = container_logic	
	
	ref_toks = container_logic.ref_submodule_instance_to_ref_toks[logic.inst_name]
	orig_var_name = ref_toks[0]
	#print orig_var_name
	#sys.exit(0)
	
	
	
	#print "container_logic.wire_to_c_type",container_logic.wire_to_c_type
	#BAH fuck is this normal? ha yes, doing for var ref rd too
	orig_var_name_inst_name = logic.containing_inst + C_TO_LOGIC.SUBMODULE_MARKER + orig_var_name
	'''
	# Sanity check
	if orig_var_name_inst_name not in container_logic.wire_to_c_type:
		for wire in container_logic.wire_to_c_type:
			print wire, container_logic.wire_to_c_type[wire]
		#print container_logic.wire_to_c_type
	'''	
	base_c_type = container_logic.wire_to_c_type[orig_var_name_inst_name]
	base_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(base_c_type,parser_state_copy) # Structs handled and have same name as C types
	
	wires_decl_text = ""
	wires_decl_text +=  '''	
	variable base : ''' + base_vhdl_type + ''';'''
	
	

	#print "logic.func_name",logic.func_name
	
	# # Then wire for each input
	# for input_port_inst_name in logic.inputs:
	# 	input_port = input_port_inst_name.replace(logic.inst_name+C_TO_LOGIC.SUBMODULE_MARKER,"")
	# 	input_port_type_c_type = logic.wire_to_c_type[input_port_inst_name]
	# 	input_port_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(input_port_type_c_type,parser_state_copy)
	# 	vhdl_input_port = VHDL.WIRE_TO_VHDL_NAME(input_port, logic) #.replace(C_TO_LOGIC.REF_TOK_DELIM,"_REF_").re
	# 	
	# 	wires_decl_text +=  '''	
	# variable ''' + vhdl_input_port + ''' : ''' + input_port_type + ''';'''
	
	# Then output
	output_c_type = logic.wire_to_c_type[logic.outputs[0]]
	output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_c_type,parser_state_copy)
	wires_decl_text +=  '''	
	variable return_output : ''' + output_vhdl_type + ''';'''
	
	# The text is the writes in correct order
	text = ""
	# Inputs drive base, any undriven wires here should have syn error right?
	
	driven_ref_toks_list = container_logic.ref_submodule_instance_to_input_port_driven_ref_toks[logic.inst_name]
	driven_ref_toks_i = 0
	for input_port_inst_name in logic.inputs:
		input_port = input_port_inst_name.replace(logic.inst_name+C_TO_LOGIC.SUBMODULE_MARKER,"")
		vhdl_input_port = VHDL.WIRE_TO_VHDL_NAME(input_port, logic) # input_port.replace(C_TO_LOGIC.REF_TOK_DELIM,"_REF_")
		#print "input_port",input_port
		
		# ref toks not from port name
		driven_ref_toks = driven_ref_toks_list[driven_ref_toks_i]
		driven_ref_toks_i += 1
		var_ref_toks = not C_TO_LOGIC.C_AST_REF_TOKS_ARE_CONST(driven_ref_toks)
		
		# Get ref toks as best we can
		#ref_tok_strs = input_port.split(C_TO_LOGIC.REF_TOK_DELIM)
		# Is this a variable ref tok?
		#var_ref_tok_strs = "*" in ref_tok_strs
		
		# Read just the variable indicies from the right side
		# Get ref tok index of variable indicies
		var_ref_tok_indicies = []
		for ref_tok_i in range(0,len(driven_ref_toks)):
			driven_ref_tok = driven_ref_toks[ref_tok_i]
			if isinstance(driven_ref_tok, c_ast.Node):
				var_ref_tok_indicies.append(ref_tok_i)	
		
		
		# Expand to constant refs
		#if driven_ref_toks[0] == "bs":
		#	print "logic.inst_name",logic.inst_name
		#	print "parser_state_copy.existing_logic.inst_name",parser_state_copy.existing_logic.inst_name
		#	print "CONST ref rd:"
		#	print "input",input_port_inst_name
		#	print "driven_ref_toks",driven_ref_toks
		
		
		
		expanded_ref_tok_list = C_TO_LOGIC.EXPAND_REF_TOKS_OR_STRS(driven_ref_toks, logic.c_ast_node, parser_state_copy)
		for expanded_ref_toks in expanded_ref_tok_list:			
			# Build vhdl str doing the reference assignment to base
			vhdl_ref_str = ""
			for ref_tok in expanded_ref_toks[1:]: # Dont need base var name
				if type(ref_tok) == int:
					vhdl_ref_str += "(" + str(ref_tok) + ")"
				elif type(ref_tok) == str:
					vhdl_ref_str += "." + ref_tok
				else:
					print "Only constant references here!", c_ast_ref.coord
					sys.exit(0)
		
			# Var ref needs to read input port differently than const
			expr = '''			base''' + vhdl_ref_str + ''' := ''' + vhdl_input_port
			if var_ref_toks:
				# Index into RHS
				# Uses that DUMB_STRUCT_THING struct wrapper?
				# Need to have ".data"?
				expr += ".data"
				for var_ref_tok_index in var_ref_tok_indicies:
					val = expanded_ref_toks[var_ref_tok_index]
					expr += "(" + str(val) + ")"
					
			# Append to text
			text += expr + ";\n"
	    
	    
	    
	# Then base drives return_output
	# Need to parse func name
	# Build vhdl str doing the output reference
	vhdl_ref_str = ""
	# THIS IS A CONSTANT REF READ SO NO VAR TOKS
	'''
	output_ref_toks_str = logic.func_name.replace(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX+"_","")
	#.replace(logic.inst_name+C_TO_LOGIC.SUBMODULE_MARKER,"")
	ref_tok_strs = output_ref_toks_str.split(C_TO_LOGIC.REF_TOK_DELIM)
	# Output doesnt need base variable name, is already named 'base'
	ref_tok_strs = ref_tok_strs[1:]
	ref_toks = []
	for ref_tok_str in ref_tok_strs:
		if ref_tok_str.isdigit():
			# Array ref
			ref_toks.append(int(ref_tok_str))
		else:
			ref_toks.append(ref_tok_str)
	'''
	
	
	for ref_tok in ref_toks[1:]: # Skip base var name
		if type(ref_tok) == int:
			vhdl_ref_str += "(" + str(ref_tok) + ")"
		elif type(ref_tok) == str:
			vhdl_ref_str += "." + ref_tok
		else:
			print "Only constant references right now blbblbaaaghghhh!", c_ast_ref.coord
			sys.exit(0)
	
	text += '''
			return_output := base''' + vhdl_ref_str + ''';
			return return_output; '''
	   
	#print "=="
	#print "logic.inst_name",logic.inst_name
	#print wires_decl_text
	#print  text
	#sys.exit(0)
	
	return wires_decl_text, text	
	 
	

def GET_UNARY_OP_NOT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state):
	# ONLY INTS FOR NOW
	input_type = logic.wire_to_c_type[logic.inputs[0]]
	input_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(input_type, parser_state)
	input_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, input_type)
	output_type = logic.wire_to_c_type[logic.outputs[0]]
	output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
	
	
	wires_decl_text = '''
	expr_resized : ''' + output_vhdl_type + ''';
	return_output : ''' + output_vhdl_type + ''';
	expr : ''' + input_vhdl_type + ''';
'''

	# MAx clocks is input reg and output reg
	#max_clocks = 2
	latency = timing_params.GET_TOTAL_LATENCY(parser_state)
	num_stages = latency + 1
	# Which stage gets the 1 LL ?
	stage_for_1ll = None
	if latency == 0:
		stage_for_1ll = 0
	elif latency == 1:
		# Rely on percent
		stage_for_1ll = 0
		# If slice is to left logic is on right
		if timing_params.slices[0] < 0.5:
			stage_for_1ll = 1	
	elif latency == 2:
		# INput reg and output reg logic in middle
		# IN stage 1 :  0 | 1 | 2
		stage_for_1ll = 1
	else:
		print "Cannot do a c built in NOT operation in", latency,  "clocks!"
		sys.exit(0)
		
		

	# 1 LL VHDL		
	# VHDL text is just the IF for the stage in question
	text = ""
	text += '''
		if STAGE = ''' + str(stage_for_1ll) + ''' then
			write_pipe.expr_resized := resize(write_pipe.expr, ''' + str(output_width) + ''');
			write_pipe.return_output := not write_pipe.expr_resized;
		end if;			
	'''

	return wires_decl_text, text


def GET_BIN_OP_AND_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state):
	# ONLY INTS FOR NOW
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	output_type = logic.wire_to_c_type[logic.outputs[0]]
	output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
	max_input_width = max(left_width,right_width)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
	
	
	wires_decl_text = '''
	left_resized : ''' + output_vhdl_type + ''';
	right_resized : ''' + output_vhdl_type + ''';
	return_output : ''' + output_vhdl_type + ''';
	right : ''' + right_vhdl_type + ''';
	left : ''' + left_vhdl_type + ''';
'''

	# MAx clocks is input reg and output reg
	#max_clocks = 2
	latency = timing_params.GET_TOTAL_LATENCY(parser_state)
	num_stages = latency + 1
	# Which stage gets the 1 LL ?
	stage_for_1ll = None
	if latency == 0:
		stage_for_1ll = 0
	elif latency == 1:
		# Rely on percent
		stage_for_1ll = 0
		# If slice is to left logic is on right
		if timing_params.slices[0] < 0.5:
			stage_for_1ll = 1	
	elif latency == 2:
		# INput reg and output reg logic in middle
		# IN stage 1 :  0 | 1 | 2
		stage_for_1ll = 1
	else:
		print "Cannot do a c built in AND operation in", latency,  "clocks!"
		sys.exit(0)
		

	# 1 LL VHDL	
	# VHDL text is just the IF for the stage in question
	text = ""
	text += '''
		if STAGE = ''' + str(stage_for_1ll) + ''' then
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(output_width) + ''');
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(output_width) + ''');
			write_pipe.return_output := write_pipe.left_resized and write_pipe.right_resized;		
		end if;			
	'''
	
	

	return wires_decl_text, text
	
	
def GET_BIN_OP_OR_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state):
	# ONLY INTS FOR NOW
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	output_type = logic.wire_to_c_type[logic.outputs[0]]
	output_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(output_type, parser_state)
	max_input_width = max(left_width,right_width)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
	
	
	wires_decl_text = '''
	left_resized : ''' + output_vhdl_type + ''';
	right_resized : ''' + output_vhdl_type + ''';
	return_output : ''' + output_vhdl_type + ''';
	right : ''' + right_vhdl_type + ''';
	left : ''' + left_vhdl_type + ''';
'''

	# MAx clocks is input reg and output reg
	#max_clocks = 2
	latency = timing_params.GET_TOTAL_LATENCY(parser_state)
	num_stages = latency + 1
	# Which stage gets the 1 LL ?
	stage_for_1ll = None
	if latency == 0:
		stage_for_1ll = 0
	elif latency == 1:
		# Rely on percent
		stage_for_1ll = 0
		# If slice is to left logic is on right
		if timing_params.slices[0] < 0.5:
			stage_for_1ll = 1	
	elif latency == 2:
		# INput reg and output reg logic in middle
		# IN stage 1 :  0 | 1 | 2
		stage_for_1ll = 1
	else:
		print "Cannot do a c built in OR operation in", latency,  "clocks!"
		sys.exit(0)
		
		

	# 1 LL VHDL	
	# VHDL text is just the IF for the stage in question
	text = ""
	text += '''
		if STAGE = ''' + str(stage_for_1ll) + ''' then
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(output_width) + ''');
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(output_width) + ''');
			write_pipe.return_output := write_pipe.left_resized or write_pipe.right_resized;		
		end if;			
	'''
	
	

	return wires_decl_text, text
	
def GET_BIN_OP_EQ_NEQ_C_BUILT_IN_AS_SLV_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# ONLY INTS FOR NOW
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	left_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(left_type, parser_state)
	right_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(right_type, parser_state)
	
	# HACK OH GOD NO dont look up enums
	# Left
	#if left_type in parser_state.enum_to_ids_dict:
	#	num_ids = len(parser_state.enum_to_ids_dict[left_type])
	#	left_width = int(math.ceil(math.log(num_ids,2)))
	#else:
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	# Right
	#if right_type in parser_state.enum_to_ids_dict:
	#	num_ids = len(parser_state.enum_to_ids_dict[right_type])
	#	right_width = int(math.ceil(math.log(num_ids,2)))
	#else:
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
		
	max_width = max(left_width,right_width)
		
	# Left
	#if left_type in parser_state.enum_to_ids_dict:
	#	left_cast_toks = ["std_logic_vector(to_unsigned(" + left_type + "'pos(" , ") ," + str(max_width) + "))"]
	#else:
	left_cast_toks = ["std_logic_vector(resize(","," + str(max_width) + "))"]
	# Right
	#if right_type in parser_state.enum_to_ids_dict:
	#	right_cast_toks = ["std_logic_vector(to_unsigned(" + right_type + "'pos(" , ") ," + str(max_width) + "))"]
	#else:
	right_cast_toks = ["std_logic_vector(resize(","," + str(max_width) + "))"]

	
	wires_decl_text = '''
	left_resized : std_logic_vector(''' + str(max_width-1) + ''' downto 0);
	right_resized : std_logic_vector(''' + str(max_width-1) + ''' downto 0);
	return_output_bool : boolean;
	return_output : unsigned(0 downto 0);
	right : ''' + right_vhdl_type + ''';
	left :  ''' + left_vhdl_type + ''';
'''

	# Set width equal to max width
	width = max_width

	# Max clocks does one bit per clock 
	max_clocks = width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in EQ operation of",width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)	

	# Write loops to do operation
	text = ""
	text += '''
		-- COMPARE N bits per clock, 
		-- num_stages = ''' + str(num_stages) + "\n"
	text += "\n"
	# This needs to be in stage 0
	text += '''
		if STAGE = 0 then			
			write_pipe.return_output_bool := true;
			write_pipe.left_resized := ''' + left_cast_toks[0] + '''write_pipe.left''' + left_cast_toks[1] + ''';
			write_pipe.right_resized := ''' + right_cast_toks[0] + '''write_pipe.right''' + right_cast_toks[1] + ''';
	'''
	# Write bound of loop per stage 
	stage = 0
	up_bound = width - 1
	low_bound = up_bound - bits_per_stage_dict[stage] + 1
	for stage in range(0,num_stages): 
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text += '''		
			-- bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + '''
			'''
			text +=	'''
				-- Assign output based on range for this stage
				write_pipe.return_output_bool := write_pipe.return_output_bool and (write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') = write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') );
				'''

		# More stages?
		if stage == (num_stages - 1):
			# Last stage so no else if
			# optional negate
			maybe_not = ""
			if op_str == "!=":
				maybe_not = "not"
				
			text += '''
			if ''' + maybe_not + ''' write_pipe.return_output_bool then
				write_pipe.return_output := (others => '1');
			else
				write_pipe.return_output := (others => '0');
			end if;
			
		end if;
		'''
			return wires_decl_text, text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment
			up_bound = up_bound - bits_per_stage_dict[stage-1]
			low_bound = up_bound - bits_per_stage_dict[stage] + 1			
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''

def GET_BIN_OP_EQ_NEQ_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state, op_str):
	# Binary operation between what two types?
	# Only ints for now, check all inputs
	if VHDL.WIRES_ARE_INT_N(logic.inputs, logic) or VHDL.WIRES_ARE_UINT_N(logic.inputs, logic) or VHDL.WIRES_ARE_C_TYPE(logic.inputs,"float",logic) or VHDL.WIRES_ARE_ENUM(logic.inputs,logic,parser_state):
		return GET_BIN_OP_EQ_NEQ_C_BUILT_IN_AS_SLV_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str)
	else:
		print "Binary op EQ for ", logic.wire_to_c_type, " as SLV?"
		sys.exit(0)
		
def GET_BIN_OP_MINUS_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	output_type = logic.wire_to_c_type[logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	max_input_width = max(left_width,right_width)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
	wires_decl_text = '''
	carry : std_logic_vector(0 downto 0);
	intermediate : std_logic_vector(''' + str(max_input_width) + ''' downto 0);
	left_resized : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	right_resized : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	left_range_slv : std_logic_vector(''' + str(max_input_width-1) + ''' downto 0);
	right_range_slv : std_logic_vector(''' + str(max_input_width-1) + ''' downto 0);
	full_width_return_output : signed(''' + str(max_input_width-1) + ''' downto 0);
	return_output : signed(''' + str(output_width-1) + ''' downto 0);
	right : signed(''' + str(right_width-1) + ''' downto 0);
	left : signed(''' + str(left_width-1) + ''' downto 0);
'''
	
	# Do each bit over a clock cycle 
	
	# TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
	width = max_input_width
	
	# Output width must be ???
	# Is vhdl allowing equal or larger assignments?
	'''
	output_width = GET_OUTPUT_C_INT_BIT_WIDTH(logic)
	if output_width != (width*2):
		print logic.inst_name,"Output width must be sum of two widths"
		print "output_width",output_width
		print "input width",width
		sys.exit(0)
	'''
	
	max_clocks = width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in uint binary plus operation of",width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)
	
	
	
	# Write loops to do operation
	text = ""
	text += '''
	--
	-- One bit adder with carry
'''
	
	text += '''
	-- num_stages = ''' + str(num_stages) + '''
	'''
	text += '''
		if STAGE = 0 then
			-- This stuff must be in stage 0
			write_pipe.carry := (others => '0'); --	One bit unsigned	
			write_pipe.intermediate := (others => '0'); -- N bit unused depending on bits per stage
			write_pipe.left_resized := unsigned(resize(write_pipe.left, ''' + str(width) + '''));
			write_pipe.right_resized := unsigned(resize(write_pipe.right, ''' + str(width) + '''));
			write_pipe.return_output := (others => '0');
			write_pipe.full_width_return_output := (others => '0');
			'''		
		
		
			
	# Write bound of loop per stage 
	stage = 0
	up_bound = bits_per_stage_dict[stage]-1 # Skip sign (which should be 0 for abs values)
	low_bound = 0
	for stage in range(0, num_stages):
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text +=	'''
				--  bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + '''
				write_pipe.left_range_slv := (others => '0');
				write_pipe.right_range_slv := (others => '0');
				write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0) := std_logic_vector(write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + '''));
				write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0) := std_logic_vector(write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + '''));	

				-- DOIGN SUB OP,  carry indicates -1
				-- Sub signed values
				write_pipe.intermediate := (others => '0'); -- Zero out for this stage
				write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0) := std_logic_vector( signed('0' & write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) - signed('0' & write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) - signed('0' & write_pipe.carry) );	
	'''

			text +=	'''
				-- New carry is sign (negative carry)
				write_pipe.carry(0) := write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''');
				-- Assign output bits into full width
				write_pipe.full_width_return_output(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') := signed(write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0));
				--write_pipe.return_output(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') := signed(write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0));
			'''
			
		# More stages?
		if stage == (num_stages - 1):
			# Last stage
			# sign is in last stage
			# depends on carry
			text +=	'''
			write_pipe.return_output := resize(write_pipe.full_width_return_output(''' + str(max_input_width-1) + ''' downto 0), ''' + str(output_width) + ''');			
'''
			# Last stage so no else if
			text += '''
		end if;
		'''
			return wires_decl_text, text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment 
			up_bound = up_bound + bits_per_stage_dict[stage]
			low_bound = low_bound + bits_per_stage_dict[stage-1]
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''


def GET_BIN_OP_MINUS_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	output_type = logic.wire_to_c_type[logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	max_input_width = max(left_width,right_width)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
	wires_decl_text = '''
	carry : std_logic_vector(0 downto 0);
	intermediate : std_logic_vector(''' + str(max_input_width) + ''' downto 0);
	left_resized : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	right_resized : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	left_range_slv : std_logic_vector(''' + str(max_input_width-1) + ''' downto 0);
	right_range_slv : std_logic_vector(''' + str(max_input_width-1) + ''' downto 0);
	full_width_return_output : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	return_output : unsigned(''' + str(output_width-1) + ''' downto 0);
	right : unsigned(''' + str(right_width-1) + ''' downto 0);
	left : unsigned(''' + str(left_width-1) + ''' downto 0);
'''
	
	# Do each bit over a clock cycle 
	
	# TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
	width = max_input_width
	
	# Output width must be ???
	# Is vhdl allowing equal or larger assignments?
	'''
	output_width = GET_OUTPUT_C_INT_BIT_WIDTH(logic)
	if output_width != (width*2):
		print logic.inst_name,"Output width must be sum of two widths"
		print "output_width",output_width
		print "input width",width
		sys.exit(0)
	'''
	
	max_clocks = width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in uint binary plus operation of",width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)

	# Write loops to do operation
	text = ""
	text += '''
	--
	-- One bit adder with carry
'''
	
	text += '''
	-- num_stages = ''' + str(num_stages) + '''
	'''
	text += '''
		if STAGE = 0 then
			-- This stuff must be in stage 0
			write_pipe.carry := (others => '0'); --	One bit unsigned	
			write_pipe.intermediate := (others => '0'); -- N bit unused depending on bits per stage
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(width) + ''');
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(width) + ''');
			write_pipe.return_output := (others => '0');
			write_pipe.full_width_return_output := (others => '0');
			'''		
		
		
			
	# Write bound of loop per stage 
	stage = 0
	up_bound = bits_per_stage_dict[stage]-1 # Skip sign (which should be 0 for abs values)
	low_bound = 0
	for stage in range(0, num_stages):
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text +=	'''
				--  bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + '''
				write_pipe.left_range_slv := (others => '0');
				write_pipe.right_range_slv := (others => '0');
				write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0) := std_logic_vector(write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + '''));
				write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0) := std_logic_vector(write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + '''));	

				-- DOIGN SUB OP,  carry indicates -1
				-- Sub signed values
				write_pipe.intermediate := (others => '0'); -- Zero out for this stage
				write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0) := std_logic_vector( signed('0' & write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) - signed('0' & write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) - signed('0' & write_pipe.carry) );	
	'''

			text +=	'''
				-- New carry is sign (negative carry)
				write_pipe.carry(0) := write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''');
				-- Assign output bits
				write_pipe.full_width_return_output(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') := unsigned(write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0));
			'''
			
		# More stages?
		if stage == (num_stages - 1):
			# Last stage
			# sign is in last stage
			# depends on carry
			text +=	'''
			write_pipe.return_output := resize(write_pipe.full_width_return_output(''' + str(max_input_width-1) + ''' downto 0), ''' + str(output_width) + ''');			
'''
			# Last stage so no else if
			text += '''
		end if;
		'''
			return wires_decl_text, text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment 
			up_bound = up_bound + bits_per_stage_dict[stage]
			low_bound = low_bound + bits_per_stage_dict[stage-1]
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''
		


def GET_BIN_OP_MINUS_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	
	# Binary operation between what two types?
	# Only ints for now, check all inputs
	if VHDL.WIRES_ARE_UINT_N(logic.inputs, logic):
		return GET_BIN_OP_MINUS_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
	elif VHDL.WIRES_ARE_INT_N(logic.inputs, logic):
		return GET_BIN_OP_MINUS_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
	else:
		print "Only u/int binary op minus raw vhdl for now!", logic.wire_to_c_type
		sys.exit(0)

def GET_BITS_PER_STAGE_DICT(num_bits, timing_params):
	bits_per_stage_dict = dict()	
	
	# Default everything in stage 0 if no slices
	bits_per_stage_dict[0] = num_bits
	
	# Build a list of absolute percent sizes for each stage
	# ex. two even slices = [0.333,0.3333,0.333]
	removed_percent = 0.0
	adj_percents = []
	# This does for >= 1clks
	for raw_hdl_slice in timing_params.slices:
		adj_percent = raw_hdl_slice - removed_percent
		adj_percents.append(adj_percent)
		removed_percent += adj_percent
	# Do last/default stage0 only stage
	remaining_percent = 1.0 - removed_percent
	adj_percents.append(remaining_percent)
		
	# Apply slice
	# (will have zero bits per stage in some places)
	stage = 0
	for adj_percent in adj_percents:
		# Take away N percent 
		int_bits_to_take = int(round(adj_percent * float(num_bits)))
		bits_per_stage_dict[stage] = int_bits_to_take
		stage += 1
		
	# Allow for 0 bits per stage at start and end of pipeline otherwise doesnt make sense
	# TODO ^
	'''
	# Do not allow 0 bits per stage, min 1 bit per stage
	for stage in bits_per_stage_dict:
		if bits_per_stage_dict[stage] <= 0:
			bits_per_stage_dict[stage] = 1
	'''
			
	# Might have used too many or too little bits?	
	excess = sum(bits_per_stage_dict.values()) - num_bits
	
	# Handle excess
	while excess != 0:
		if excess > 0:
			# Too many bits, need to subtract some
			# Best thing for timing is to subtract from max bits stage
			max_bits = 0
			max_stage = None
			for stage in bits_per_stage_dict:
				bits = bits_per_stage_dict[stage]
				if bits > max_bits:
					max_stage = stage
					max_bits = bits
			bits_per_stage_dict[max_stage] -= 1
		elif excess < 0:
			# Need more bits
			# Best thing for timing is to add 1 bit to lowest bit stage
			min_bits = 9999999
			min_stage = None
			for stage in bits_per_stage_dict:
				bits = bits_per_stage_dict[stage]
				if bits < min_bits:
					min_stage = stage
					min_bits = bits
			#print "bits_per_stage_dict",bits_per_stage_dict
			bits_per_stage_dict[min_stage] += 1
			
			
		excess = sum(bits_per_stage_dict.values()) - num_bits
		
		
	# sanity check
	maybe_num_bits = sum(bits_per_stage_dict.values())
	if maybe_num_bits != num_bits:
		print "maybe_num_bits != num_bits"
		print "maybe_num_bits",maybe_num_bits
		print "num_bits",num_bits
		print 0/0
		sys.exit(0)		
	
		
	return bits_per_stage_dict
	

def GET_BIN_OP_PLUS_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	output_type = logic.wire_to_c_type[logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	max_input_width = max(left_width,right_width)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
	wires_decl_text = '''
	carry : std_logic_vector(0 downto 0);
	intermediate : std_logic_vector(''' + str(max_input_width) + ''' downto 0);
	left_resized : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	right_resized : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	left_range_slv : std_logic_vector(''' + str(max_input_width-1) + ''' downto 0);
	right_range_slv : std_logic_vector(''' + str(max_input_width-1) + ''' downto 0);
	full_width_return_output : unsigned(''' + str(max_input_width) + ''' downto 0);
	return_output : unsigned(''' + str(output_width-1) + ''' downto 0);
	right : unsigned(''' + str(right_width-1) + ''' downto 0);
	left : unsigned(''' + str(left_width-1) + ''' downto 0);
'''
	
	# Do each bit over a clock cycle 
	
	# TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
	width = max_input_width
	
	# Output width must be ???
	# Is vhdl allowing equal or larger assignments?
	'''
	output_width = GET_OUTPUT_C_INT_BIT_WIDTH(logic)
	if output_width != (width*2):
		print logic.inst_name,"Output width must be sum of two widths"
		print "output_width",output_width
		print "input width",width
		sys.exit(0)
	'''
	
	max_clocks = width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in uint binary plus operation of",width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)
	#print "num_stages",num_stages
	#print "bits_per_stage_dict",bits_per_stage_dict
	
	# Write loops to do operation
	text = ""
	text += '''
	--
	-- One bit adder with carry
'''
	
	text += '''
	-- width = ''' + str(width) + '''
	-- num_stages = ''' + str(num_stages) + '''
	-- bits per stage = ''' + str(bits_per_stage_dict) + '''
	'''
	text += '''
		if STAGE = 0 then
			-- This stuff must be in stage 0
			write_pipe.carry := (others => '0'); --	One bit unsigned
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(width) + ''');
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(width) + ''');
			write_pipe.return_output := (others => '0');
			write_pipe.full_width_return_output := (others => '0');
			'''		
		
		
			
	# Write bound of loop per stage 
	stage = 0
	up_bound = bits_per_stage_dict[stage]-1 # Skip sign (which should be 0 for abs values)
	low_bound = 0
	for stage in range(0, num_stages):
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text +=	'''
				--  bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + '''
				write_pipe.left_range_slv := (others => '0');
				write_pipe.right_range_slv := (others => '0');
				write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0) := std_logic_vector(write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + '''));
				write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0) := std_logic_vector(write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + '''));	

				-- Adding unsigned values
				write_pipe.intermediate := (others => '0'); -- Zero out for this stage'''
			
			# No carry for stage 0
			if stage == 0:
				text += '''
				write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0) := std_logic_vector( unsigned('0' & write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) + unsigned('0' & write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) );'''
			else:
				text += '''
				write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0) := std_logic_vector( unsigned('0' & write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) + unsigned('0' & write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) + unsigned(write_pipe.carry) );'''
			
			text += '''
				-- New carry is msb of intermediate
				write_pipe.carry(0) := write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''');
				-- Assign output bits
				-- Carry full_width_return_output(up_bound+1) will be overidden in next iteration and included as carry
				write_pipe.full_width_return_output(''' + str(up_bound+1) + ''' downto ''' + str(low_bound) + ''') := unsigned(write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0));
			'''
			
		# More stages?
		if stage == (num_stages - 1):
			# Last stage
			# sign is in last stage
			# depends on carry
			text +=	'''
			write_pipe.return_output := resize(write_pipe.full_width_return_output(''' + str(max_input_width) + ''' downto 0), ''' + str(output_width) + ''');			
'''
			# Last stage so no else if
			text += '''
		end if;
		'''
			return wires_decl_text, text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment 
			up_bound = up_bound + bits_per_stage_dict[stage]
			low_bound = low_bound + bits_per_stage_dict[stage-1]
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''
		
		

	
def GET_BIN_OP_PLUS_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# Was confused abotu twos compliment ... I think you can just add and the sign takes care of self?
	# Especially if dont care about overflow or carry?
	# Uh too many drinks
	# Fuck this
	
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	output_type = logic.wire_to_c_type[logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	max_input_width = max(left_width,right_width)
	
	
	# Do each bit over a clock cycle 
	width = max_input_width + 1
	
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_type)
	wires_decl_text = '''
	carry : std_logic_vector(0 downto 0);
	intermediate : std_logic_vector(''' + str(max_input_width+1) + ''' downto 0);
	--left_resized : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	--right_resized : unsigned(''' + str(max_input_width-1) + ''' downto 0);
	left_resized : unsigned(''' + str(max_input_width) + ''' downto 0);
	right_resized : unsigned(''' + str(max_input_width) + ''' downto 0);
	--left_range_slv : std_logic_vector(''' + str(max_input_width-1) + ''' downto 0);
	--right_range_slv : std_logic_vector(''' + str(max_input_width-1) + ''' downto 0);
	left_range_slv : std_logic_vector(''' + str(max_input_width) + ''' downto 0);
	right_range_slv : std_logic_vector(''' + str(max_input_width) + ''' downto 0);
	full_width_return_output : unsigned(''' + str(max_input_width+1) + ''' downto 0);
	return_output : signed(''' + str(output_width-1) + ''' downto 0);
	right : signed(''' + str(right_width-1) + ''' downto 0);
	left : signed(''' + str(left_width-1) + ''' downto 0);
'''
	
	
	
	# Output width must be 1 greater than max of input widths
	# Is vhdl allowing equal or larger assignments?
	'''
	output_width = GET_OUTPUT_C_INT_BIT_WIDTH(logic)
	if output_width != (width*2):
		print logic.inst_name,"Output width must be sum of two widths"
		print "output_width",output_width
		print "input width",width
		sys.exit(0)
	'''
	
	max_clocks = width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in uint binary plus operation of",width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)
	
	
	
	# Write loops to do operation
	text = ""
	text += '''
	--
	-- One bit adder with carry
'''
	
	text += '''
	-- num_stages = ''' + str(num_stages) + '''
	'''
	text += '''
		if STAGE = 0 then
			-- This stuff must be in stage 0
			write_pipe.carry := (others => '0'); --	One bit unsigned	
			write_pipe.intermediate := (others => '0'); -- N bit unused depending on bits per stage
			write_pipe.left_resized := unsigned(std_logic_vector(resize(write_pipe.left, ''' + str(width) + ''')));
			write_pipe.right_resized := unsigned(std_logic_vector(resize(write_pipe.right, ''' + str(width) + ''')));
			write_pipe.full_width_return_output := (others => '0');
			write_pipe.return_output := (others => '0');
			'''		
		
    # 1111111111111111111111111111111110000000000000000000000000000000
    # +
    # 1111111111111111111111111111111110000000000000000000000000000000
    # ===============================================================
	# 1111111111111111111111111111111100000000000000000000000000000000
		
			
	# Write bound of loop per stage 
	stage = 0
	up_bound = bits_per_stage_dict[stage]-1 
	low_bound = 0
	for stage in range(0, num_stages):
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text +=	'''
				--  bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + '''
				write_pipe.left_range_slv := (others => '0');
				write_pipe.right_range_slv := (others => '0');
				write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0) := std_logic_vector(write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + '''));
				write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0) := std_logic_vector(write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + '''));	

				-- Adding unsigned values
				write_pipe.intermediate := (others => '0'); -- Zero out for this stage
				write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0) := std_logic_vector( unsigned('0' & write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) + unsigned('0' & write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) + unsigned(write_pipe.carry) );	
				--write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0) := std_logic_vector( unsigned('0' & write_pipe.left_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0)) + unsigned('0' & write_pipe.right_range_slv(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0))  );	
				--write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0) := std_logic_vector( unsigned(write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0)) + unsigned(write_pipe.carry) );
				
	'''			

			text +=	'''
				-- New carry is msb of intermediate
				write_pipe.carry(0) := write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''');
				-- Assign output bits
			'''
			# Only last iteration writes carry into full_width_return_output?
			if stage == (num_stages - 1):
				text += '''
				-- Only last iteration writes carry into full_width_return_output?
				-- Carry full_width_return_output(up_bound+1) will be overidden in next iteration and included as carry
				write_pipe.full_width_return_output(''' + str(up_bound+1) + ''' downto ''' + str(low_bound) + ''') := unsigned(write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]) + ''' downto 0));
			'''
			else:
				text += '''
				-- Dont include carry since not last stage
				write_pipe.full_width_return_output(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') := unsigned(write_pipe.intermediate(''' + str(bits_per_stage_dict[stage]-1) + ''' downto 0));
			'''
			
		# More stages?
		if stage == (num_stages - 1):
			# Last stage
			# sign is in last stage
			# depends on carry
			text +=	'''
			-- ???Full width output last bit is always dropped since DOING SIGNED ADD, can't meanfully overflow
			--???? SIGN EXTENSION DONE AS PART OF SIGNED RESIZED
			write_pipe.full_width_return_output(''' + str(max_input_width+1) + ''') := '0';
			-- Resize from full width to output width
			--???write_pipe.return_output := resize(signed(std_logic_vector(write_pipe.full_width_return_output(''' + str(max_input_width-1) + ''' downto 0))), ''' + str(output_width) + ''');		
			write_pipe.return_output := resize(signed(std_logic_vector(write_pipe.full_width_return_output(''' + str(max_input_width) + ''' downto 0))), ''' + str(output_width) + ''');		

'''
			# Last stage so no else if
			text += '''
		end if;
		'''
			return wires_decl_text, text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment 
			up_bound = up_bound + bits_per_stage_dict[stage]
			low_bound = low_bound + bits_per_stage_dict[stage-1]
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''
	
	
	
		
def GET_BIN_OP_PLUS_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# Binary operation between what two types?
	# Only ints for now, check all inputs
	if VHDL.WIRES_ARE_INT_N(logic.inputs, logic):
		return GET_BIN_OP_PLUS_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
	elif VHDL.WIRES_ARE_UINT_N(logic.inputs, logic):
		return GET_BIN_OP_PLUS_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
	else:
		print "Only u/int binary op plus for now!", logic.wire_to_c_types
		sys.exit(0)
		
def GET_BIN_OP_LT_LTE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params, op_str):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# Binary operation between what two types?
	# Only ints for now, check all inputs
	if VHDL.WIRES_ARE_INT_N(logic.inputs,logic):
		return GET_BIN_OP_LT_LTE_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str)
	elif VHDL.WIRES_ARE_UINT_N(logic.inputs,logic):
		return GET_BIN_OP_LT_LTE_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str)
	else:
		print logic.c_ast_node
		print "Binary op LT/E for type?", logic.c_ast_node.coord
		sys.exit(0)
		
def GET_BIN_OP_GT_GTE_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params, op_str):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# Binary operation between what two types?
	# Only ints for now, check all inputs
	if VHDL.WIRES_ARE_INT_N(logic.inputs,logic):
		return GET_BIN_OP_GT_GTE_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str)
	elif VHDL.WIRES_ARE_UINT_N(logic.inputs,logic):
		return GET_BIN_OP_GT_GTE_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str)
	else:
		print "Binary op GT/GTE for type?", logic.c_ast_node.coord
		sys.exit(0)
		
def GET_BIN_OP_GT_GTE_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str):
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	max_width = max(left_width,right_width)
	wires_decl_text = '''	
	return_output : unsigned(0 downto 0);
	return_output_bool : boolean;
	right : signed(''' + str(right_width-1) + ''' downto 0);
	left : signed(''' + str(left_width-1) + ''' downto 0);
	right_resized : signed(''' + str(max_width-1) + ''' downto 0);
	left_resized : signed(''' + str(max_width-1) + ''' downto 0);
	inequality_found : boolean;
	same_sign : boolean;
'''
	
	
	# C built in VHDL GT uses 5 LLs, this is 6LLs ... OK for now.... 
	
	# Goal here is to have a maximum pipeline depth and crazy utilization if it meets timing
	# Whats the max number of clocks we can do?
	# Smallest possible computation of binary op should be one bit at a time?
	# WIKI:"we inspect the relative magnitudes of pairs of significant digits, 
	# starting from the most significant bit, gradually proceeding towards 
	# lower significant bits until an inequality is found. 
	# When an inequality is found, if the corresponding bit of A is 1 
	# and that of B is 0 then we conclude that A>B"
	
	# Do each bit over a clock cycle 
	
	# TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
	width = max_width
	unsigned_width = width-1 # sign bit 
	max_clocks = unsigned_width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in int binary op GT operation of",compare_width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1
	
	
		
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(unsigned_width, timing_params)
	
	
	
	# Write loops to do operation
	text = ""
	text += '''
	-- we inspect the relative magnitudes of pairs of significant digits, 
	-- starting from the most significant bit, gradually proceeding towards 
	-- lower significant bits until an inequality is found. 
	-- When an inequality is found, if the corresponding bit of A is 1 
	-- and that of B is 0 then we conclude that A>B"
	--
	-- num_stages = ''' + str(num_stages) + '''
	'''
	text += '''
		if STAGE = 0 then
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(max_width) + ''');
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(max_width) + ''');
			write_pipe.inequality_found := false; -- Must be at stage 0			
			-- Default: assume signs are different
			-- -left > +right = false 
			-- left > -right = true
			write_pipe.return_output_bool := write_pipe.right_resized('''+str(width-1)+''') = '1'; -- True if right is neg
			-- Check if signs are equal
			write_pipe.same_sign := write_pipe.left_resized('''+str(width-1)+''') = write_pipe.right_resized('''+str(width-1)+''');
	'''
	# Write bound of loop per stage 
	stage = 0
	up_bound = unsigned_width - 1 # Skip sign (which should be 0 for abs values)
	low_bound = up_bound - bits_per_stage_dict[stage] + 1
	for stage in range(0, num_stages):
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text +=	'''
				--  bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + ''' 
				--- Assign output based on compare range for this stage
				if write_pipe.inequality_found = false then
					write_pipe.inequality_found := ( write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') /= write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') ) ;
					-- Check if signs are equal
					if write_pipe.same_sign then
						-- Same sign only compare magnitude, twos complement makes it make sense
						write_pipe.return_output_bool := ( write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') > write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') );
					end if;
				end if;'''
		
		
		# More stages?
		if stage == (num_stages - 1):
			# Last stage so no else if
			# Maybe include or equal in this last stage -  sad. Chaos Arpeggiating - of Montreal 
			if op_str.endswith("="):
				text += '''
			-- OR EQUAL
			write_pipe.return_output_bool := write_pipe.return_output_bool or (not write_pipe.inequality_found and write_pipe.same_sign);'''
			
			# Convert bool to unsigned
			text += '''
			if write_pipe.return_output_bool then
				write_pipe.return_output := (others => '1');
			else
				write_pipe.return_output := (others => '0');
			end if;
			
		end if;'''
			return wires_decl_text,text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment 
			up_bound = up_bound - bits_per_stage_dict[stage-1]
			low_bound = up_bound - bits_per_stage_dict[stage] + 1
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''	
		
def GET_BIN_OP_LT_LTE_C_BUILT_IN_INT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str):
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	max_width = max(left_width,right_width)
	wires_decl_text = '''	
	return_output : unsigned(0 downto 0);
	return_output_bool : boolean;
	right : signed(''' + str(right_width-1) + ''' downto 0);
	left : signed(''' + str(left_width-1) + ''' downto 0);
	right_resized : signed(''' + str(max_width-1) + ''' downto 0);
	left_resized : signed(''' + str(max_width-1) + ''' downto 0);
	inequality_found : boolean;
	same_sign : boolean;
'''

	# Goal here is to have a maximum pipeline depth and crazy utilization if it meets timing
	# Do each bit over a clock cycle if needed
	
	# TEMP ASSUMER SIGN COMPARE IS DONE AS PART OF STAGE 0
	width = max_width
	unsigned_width = width-1 # sign bit 
	max_clocks = unsigned_width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in int binary op LT/LTE operation of",compare_width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix - you lie, never fix?
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1	
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(unsigned_width, timing_params)
	
	# Write loops to do operation
	text = ""
	text += '''
	--
	-- num_stages = ''' + str(num_stages) + '''
	'''
	text += '''
		if STAGE = 0 then
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(max_width) + ''');
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(max_width) + ''');
			write_pipe.inequality_found := false; -- Must be at stage 0			
			-- Default: assume signs are different
			-- -left < +right = true 
			-- +left < -right = false
			write_pipe.return_output_bool := write_pipe.left_resized('''+str(width-1)+''') = '1'; -- True if left is neg
			-- Check if signs are equal
			write_pipe.same_sign := write_pipe.left_resized('''+str(width-1)+''') = write_pipe.right_resized('''+str(width-1)+''');
	'''
	# Write bound of loop per stage 
	stage = 0
	up_bound = unsigned_width - 1 # Skip sign (which should be 0 for abs values)
	low_bound = up_bound - bits_per_stage_dict[stage] + 1
	for stage in range(0, num_stages):
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text +=	'''
				--  bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + ''' 
				--- Assign output based on compare range for this stage
				if write_pipe.inequality_found = false then
					write_pipe.inequality_found := ( write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') /= write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') ) ;
					-- Check if signs are equal
					if write_pipe.same_sign then
						-- Same sign only compare magnitude, twos complement makes it make sense
						write_pipe.return_output_bool := ( write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') < write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') );
					end if;
				end if;'''
		
		
		# More stages?
		if stage == (num_stages - 1):
			# Last stage so no else if
			# Maybe include or equal in this last stage -  sad. Chaos Arpeggiating - of Montreal 
			if op_str.endswith("="):
				text += '''
			-- OR EQUAL
			write_pipe.return_output_bool := write_pipe.return_output_bool or (not write_pipe.inequality_found and write_pipe.same_sign);'''
			
			# Convert bool to unsigned
			text += '''
			if write_pipe.return_output_bool then
				write_pipe.return_output := (others => '1');
			else
				write_pipe.return_output := (others => '0');
			end if;
			
		end if;'''
			return wires_decl_text,text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment 
			up_bound = up_bound - bits_per_stage_dict[stage-1]
			low_bound = up_bound - bits_per_stage_dict[stage] + 1
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''
	
	
def GET_BIN_OP_LT_LTE_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	max_width = max(left_width,right_width)
	wires_decl_text = '''
	return_output_bool : boolean;
	return_output : unsigned(0 downto 0);
	right : unsigned(''' + str(right_width-1) + ''' downto 0);
	left : unsigned(''' + str(left_width-1) + ''' downto 0);
	right_resized : unsigned(''' + str(max_width-1) + ''' downto 0);
	left_resized : unsigned(''' + str(max_width-1) + ''' downto 0);
	inequality_found : boolean;
'''
	
	
	# TODO: FIX extra logic levels
	
	# Do each bit over a clock cycle 
	width = max_width
	max_clocks = width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in uint binary LT operation of",max_width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1
	
	
		
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)
	
	
	
	# Write loops to do operation
	text = ""
	text += '''
	-- num_stages = ''' + str(num_stages) + '''
	'''
	text += '''
		if STAGE = 0 then
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(max_width) + ''');
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(max_width) + ''');
			write_pipe.inequality_found := false; -- Must be at stage 0
	'''
	
	# Write bound of loop per stage 
	stage = 0
	up_bound = width - 1
	low_bound = up_bound - bits_per_stage_dict[stage] + 1
	for stage in range(0, num_stages):
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text +=	'''
				--  bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + ''' 
				--- Assign output based on compare range for this stage
				if write_pipe.inequality_found = false then
					write_pipe.inequality_found := ( write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') /= write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') ) ;
					-- Compare magnitude
					write_pipe.return_output_bool := ( write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') < write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') );
				end if;'''
		
		
		# More stages?
		if stage == (num_stages - 1):
			# Last stage so no else if
			# Maybe include or equal in this last stage -  sad. How I Left the Ministry - The Mountain Goats
			if op_str.endswith("="):
				text += '''
			-- OR EQUAL
			write_pipe.return_output_bool := write_pipe.return_output_bool or not write_pipe.inequality_found'''
			
			# Convert bool to unsigned
			text += '''
			if write_pipe.return_output_bool then
				write_pipe.return_output := (others => '1');
			else
				write_pipe.return_output := (others => '0');
			end if;
			
		end if;'''
			return wires_decl_text,text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment 
			up_bound = up_bound - bits_per_stage_dict[stage-1]
			low_bound = up_bound - bits_per_stage_dict[stage] + 1
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''
		

# TODO: Combine GT+LT? Since using op_str?
		
def GET_BIN_OP_GT_GTE_C_BUILT_IN_UINT_N_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, op_str):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	left_type = logic.wire_to_c_type[logic.inputs[0]]
	right_type = logic.wire_to_c_type[logic.inputs[1]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
	max_width = max(left_width,right_width)
	wires_decl_text = '''	
	return_output_bool : boolean;
	return_output : unsigned(0 downto 0);
	right : unsigned(''' + str(right_width-1) + ''' downto 0);
	left : unsigned(''' + str(left_width-1) + ''' downto 0);
	right_resized : unsigned(''' + str(max_width-1) + ''' downto 0);
	left_resized : unsigned(''' + str(max_width-1) + ''' downto 0);
	inequality_found : boolean;
'''
	
	
	# C built in VHDL GT uses 5 LLs, this is 6LLs ... OK for now.... 
	
	# Goal here is to have a maximum pipeline depth and crazy utilization if it meets timing
	# Whats the max number of clocks we can do?
	# Smallest possible computation of binary op should be one bit at a time?
	# WIKI:"we inspect the relative magnitudes of pairs of significant digits, 
	# starting from the most significant bit, gradually proceeding towards 
	# lower significant bits until an inequality is found. 
	# When an inequality is found, if the corresponding bit of A is 1 
	# and that of B is 0 then we conclude that A>B"
	
	# Do each bit over a clock cycle 
	width = max_width
	max_clocks = width
	if timing_params.GET_TOTAL_LATENCY(parser_state) > max_clocks:
		print "Cannot do a c built in uint binary GT operation of",max_width, "bits in", timing_params.GET_TOTAL_LATENCY(parser_state),  "clocks!"
		sys.exit(0) # Eventually fix
	
		
	# How many bits per stage?
	# 0th stage is combinatorial logic
	num_stages = timing_params.GET_TOTAL_LATENCY(parser_state) + 1
	
	
		
	bits_per_stage_dict = GET_BITS_PER_STAGE_DICT(width, timing_params)
	
	
	
	# Write loops to do operation
	text = ""
	text += '''
	-- we inspect the relative magnitudes of pairs of significant digits, 
	-- starting from the most significant bit, gradually proceeding towards 
	-- lower significant bits until an inequality is found. 
	-- When an inequality is found, if the corresponding bit of A is 1 
	-- and that of B is 0 then we conclude that A>B"
	--
	-- num_stages = ''' + str(num_stages) + '''
	'''
	text += '''
		if STAGE = 0 then
			write_pipe.right_resized := resize(write_pipe.right, ''' + str(max_width) + ''');
			write_pipe.left_resized := resize(write_pipe.left, ''' + str(max_width) + ''');
			write_pipe.inequality_found := false; -- Must be at stage 0
	'''
	
	# Write bound of loop per stage 
	stage = 0
	up_bound = width - 1 # Skip sign (which should be 0 for abs values)
	low_bound = up_bound - bits_per_stage_dict[stage] + 1
	for stage in range(0, num_stages):
		# Do stage logic / bit pos increment if > 0 bits this stage
		if bits_per_stage_dict[stage] > 0:
			text +=	'''
				--  bits_per_stage_dict[''' + str(stage) + '''] = ''' + str(bits_per_stage_dict[stage]) + ''' 
				--- Assign output based on compare range for this stage
				if write_pipe.inequality_found = false then
					write_pipe.inequality_found := ( write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') /= write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') ) ;
					-- Compare magnitude
					write_pipe.return_output_bool := ( write_pipe.left_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') ''' + op_str + ''' write_pipe.right_resized(''' + str(up_bound) + ''' downto ''' + str(low_bound) + ''') );
				end if;'''
		
		
		# More stages?
		if stage == (num_stages - 1):
			# Last stage so no else if
			text += '''
			
			if write_pipe.return_output_bool then
				write_pipe.return_output := (others => '1');
			else
				write_pipe.return_output := (others => '0');
			end if;
			
		end if;'''
			return wires_decl_text,text
		else:
			# Next stage
			# Set next vals
			stage = stage + 1
			# Do stage logic / bit pos increment 
			up_bound = up_bound - bits_per_stage_dict[stage-1]
			low_bound = up_bound - bits_per_stage_dict[stage] + 1
			# More stages to go
			text += '''		
		elsif STAGE = ''' + str(stage) + ''' then '''
		
		
def GET_MUX_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, parser_state, timing_params):
	
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# Cond input is [0] and bool, look at true and false ones only
	tf_inputs = logic.inputs[1:]
	if len(tf_inputs) != 2:
		print "Not 2 input MUX??"
		for tf_input in tf_inputs:
			print tf_input, logic.wire_to_c_type[tf_input]
		print "logic.inputs",logic.inputs
		sys.exit(0)
		
	# Doesnt need to be clock divisiable at least for now
	# Cond input is bool look at true and false ones only
	in_wire = tf_inputs[0]
	c_type = logic.wire_to_c_type[in_wire]
	input_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state)
	
	#FUCKFUCKFUCK
	if "uint24_mux24" in logic.inst_name and "layer0_node0_" in in_wire:
		if input_vhdl_type != "unsigned(23 downto 0)":
			for wire in logic.wire_to_c_type:
				print wire, logic.wire_to_c_type[wire]
			print "INST",logic.inst_name
			print "in_wire",in_wire
			#print "MUX input_vhdl_type",input_vhdl_type
			print "c_type",c_type
			print "WHAT THE FUCK"
			sys.exit(0)
		
		
	wires_decl_text =  '''	
	return_output : ''' + input_vhdl_type + ''';
	cond : unsigned(0 downto 0);
	iftrue : ''' + input_vhdl_type + ''';
	iffalse : ''' + input_vhdl_type + ''';
'''
	
	# MAx clocks is input reg and output reg
	#max_clocks = 2
	latency = timing_params.GET_TOTAL_LATENCY(parser_state)
	num_stages = latency + 1
	# Which stage gets the 1 LL ?
	stage_for_1ll = None
	if latency == 0:
		stage_for_1ll = 0
	elif latency == 1:
		# Rely on percent
		stage_for_1ll = 0
		# If slice is to left logic is on right
		if timing_params.slices[0] < 0.5:
			stage_for_1ll = 1	
	elif latency == 2:
		# INput reg and output reg logic in middle
		# IN stage 1 :  0 | 1 | 2
		stage_for_1ll = 1
	else:
		print "Cannot do a c built in MUX operation in", latency,  "clocks!"
		sys.exit(0)
		
		
	# VHDL text is just the IF for the stage in question
	text = ""
	text += '''
		if STAGE = ''' + str(stage_for_1ll) + ''' then
			-- Assign output based on range for this stage
			if write_pipe.cond=1 then
				write_pipe.return_output := write_pipe.iftrue;
			else
				write_pipe.return_output := write_pipe.iffalse;
			end if;
		end if;			
	'''
	
	return wires_decl_text, text
	


def GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	toks = logic.func_name.split("_")
	# Bit slice or concat?
	#print "toks",toks
	# Bit slice
	if len(toks) ==4:
		# Only known thing is float SEM contructor
		# Just like bit concat
		if not(logic.func_name.startswith("float_")):
			print " Only known thing is float SEM constructor"
			sys.exit(0)
		else:
			return GET_FLOAT_SEM_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
	
	elif len(toks) == 3:
		# Array to unsigned # uint8_array250_le
		if "array" in toks[1]:
			return GET_ARRAY_TO_UNSIGNED_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
		# Eith BIT SLICE #uint64_39_39(
		elif toks[1].isdigit() and toks[2].isdigit():
			high = int(toks[1])
			low = int(toks[2])
			return GET_BIT_SLICE_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, high, low)
		# OR BIT ASSIGN # uint64_uint15_2(
		else:
			# Above will fail if is BIT assign
			return GET_BIT_ASSIGN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, timing_params, parser_state)
			
			
	elif len(toks) == 2:
		if toks[0] == "float":
			return GET_FLOAT_UINT32_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
		elif toks[0] == "bswap":
			# Byte swap
			return GET_BYTE_SWAP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
		# Bit concat or bit duplicate?
		elif toks[1].isdigit():
			# Duplicate
			return GET_BIT_DUP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, timing_params, parser_state)
		else:
			# Concat
			return GET_BIT_CONCAT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
	else:
		print "GET_BITMANIP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT for ", logic.func_name, "?"
		sys.exit(0)
		
		
		
def GET_FLOAT_UINT32_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# TODO check for ints only as constructing elements?
	# ONLY INTS FOR NOW
	in_type = logic.wire_to_c_type[logic.inputs[0]]
	in_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(in_type, parser_state)
	in_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_type)
	out_width = in_width
	out_vhdl_type = "std_logic_vector(" + str(out_width-1) + " downto 0)"
	
	wires_decl_text = '''
	--variable x : ''' + in_vhdl_type + ''';
	variable return_output : ''' + out_vhdl_type + ''';
'''

	# Float constrcut must always be zero clock
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do a float UINT32 construct concat in multiple clocks!?"
		sys.exit(0)
		
	text = '''
		return_output := std_logic_vector(x);
		return return_output;
'''

	return wires_decl_text, text
	
def GET_FLOAT_SEM_CONSTRUCT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# TODO check for ints only as constructing elements?
	# ONLY INTS FOR NOW
	s_type = logic.wire_to_c_type[logic.inputs[0]]
	e_type = logic.wire_to_c_type[logic.inputs[1]]
	m_type = logic.wire_to_c_type[logic.inputs[2]]
	s_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(s_type, parser_state)
	e_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(e_type, parser_state)
	m_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(m_type, parser_state)
	s_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, s_type)
	e_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, e_type)
	m_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, m_type)
	out_width = s_width + e_width + m_width
	out_vhdl_type = "std_logic_vector(" + str(out_width-1) + " downto 0)"
	
	wires_decl_text = '''
	--variable sign : ''' + s_vhdl_type + ''';
	--variable exponent : ''' + e_vhdl_type + ''';
	--variable mantissa : ''' + m_vhdl_type + ''';
	variable return_output : ''' + out_vhdl_type + ''';
'''

	# Float constrcut must always be zero clock
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do a float construct concat in multiple clocks!?"
		sys.exit(0)
		
	text = '''
		return_output := std_logic_vector(sign) & std_logic_vector(exponent) & std_logic_vector(mantissa);
		return return_output;
'''

	return wires_decl_text, text
	
def GET_BIT_CONCAT_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# TODO check for ints only?
	# ONLY INTS FOR NOW
	x_type = logic.wire_to_c_type[logic.inputs[0]]
	y_type = logic.wire_to_c_type[logic.inputs[1]]
	x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
	y_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(y_type, parser_state)
	x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
	y_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, y_type)
	out_width = x_width + y_width
	out_vhdl_type = "unsigned(" + str(out_width-1) + " downto 0)"
	
	wires_decl_text = '''
	--variable x : ''' + x_vhdl_type + ''';
	--variable y : ''' + y_vhdl_type + ''';
	variable return_output : ''' + out_vhdl_type + ''';
'''

	# Bit concat must always be zero clock
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do a bit concat in multiple clocks!?"
		sys.exit(0)
		
	text = '''
		return_output := unsigned(std_logic_vector(x)) & unsigned(std_logic_vector(y));
		return return_output;
'''

	return wires_decl_text, text


def GET_BYTE_SWAP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	toks = logic.func_name.split("_")
	input_bit_width = int(toks[1])
	result_width = input_bit_width
	
	#print "logic.inputs",logic.inputs
	x_type = logic.wire_to_c_type[logic.inputs[0]]
	x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
	x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
	
	wires_decl_text = '''
	--variable x : ''' + x_vhdl_type + ''';
	variable return_output : ''' + x_vhdl_type + ''';
'''

	# Byte swap must be zero clocks
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do a byte swap in multiple clocks!?"
		sys.exit(0)
		
	text = '''
		for i in 0 to (x'length/8)-1 loop
			-- j=((x'length/8)-1-i)
			return_output( (((x'length/8)-i)*8)-1 downto (((x'length/8)-1-i)*8) ) := x( ((i+1)*8)-1 downto (i*8) );
		end loop;
		
		return return_output;
'''

	return wires_decl_text, text

def GET_BIT_ASSIGN_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, timing_params, parser_state):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	toks = logic.func_name.split("_")
	input_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
	assign_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[1] + "_t")
	low_index = int(toks[2])
	high_index = low_index + assign_width - 1
	result_width = input_bit_width
	
	in_type = logic.wire_to_c_type[logic.inputs[0]]
	in_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(in_type, parser_state)
	in_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_type)
	
	#print "logic.inputs",logic.inputs
	x_type = logic.wire_to_c_type[logic.inputs[1]]
	x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
	x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
	
	intermediate_width = max(in_width, low_index + assign_width)
	intermediate_vhdl_type = "unsigned(" + str(intermediate_width-1) + " downto 0)"
	
	wires_decl_text = '''
	--variable inp : ''' + in_vhdl_type + ''';
	--variable x : ''' + x_vhdl_type + ''';
	variable intermediate : ''' + intermediate_vhdl_type + ''';
	variable return_output : ''' + in_vhdl_type + ''';
'''

	# Bit assign must always be zero clock
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do a bit assign in multiple clocks!?"
		sys.exit(0)
		
	text = '''
		intermediate := (others => '0');
		intermediate(''' +str(in_width-1) + ''' downto 0) := inp;
		intermediate(''' + str(high_index) + ''' downto ''' + str(low_index) + ''') := x;
		return_output := intermediate(''' +str(result_width-1) + ''' downto 0) ;
		return return_output;
'''

	return wires_decl_text, text

def GET_CONST_SHIFT_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT(logic, LogicInstLookupTable, timing_params, parser_state):
	# TODO check for ints only?
	# ONLY INTS FOR NOW
	x_type = logic.wire_to_c_type[logic.inputs[0]]
	x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
	x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
	x_is_signed = VHDL.C_TYPE_IS_INT_N(x_type)
	
	shift_func = None
	# Shift right might shift in sign bits if signed/arithmetic shfit
	if logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SL_NAME):
		shift_func = "sll"
	elif logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SR_NAME) and not x_is_signed:
		shift_func = "srl"
	elif logic.func_name.startswith(C_TO_LOGIC.CONST_PREFIX + C_TO_LOGIC.BIN_OP_SR_NAME) and x_is_signed:
		shift_func = "sra"
	else:
		print "Blaag: I should start putting the song I am listening too for debug if I remember"
		print '''Brother Sport
				Animal Collective - Merriweather Post Pavilion
				'''
		sys.exit(0)
		
	shift_const = None
	toks = logic.func_name.split("_")
	shift_const = toks[2]
	
	out_vhdl_type = x_vhdl_type
	
	wires_decl_text = '''
	x : ''' + x_vhdl_type + ''';
	return_output : ''' + out_vhdl_type + ''';
'''

	# Const shift must always be zero clock
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do a const shift in multiple clocks!?"
		sys.exit(0)
			
	text = '''
		write_pipe.return_output := write_pipe.x ''' + shift_func + " " + shift_const + ''';'''

	return wires_decl_text, text
	
	
	
def GET_BIT_SLICE_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params, high, low):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# TODO check for ints only?
	# ONLY INTS FOR NOW
	x_type = logic.wire_to_c_type[logic.inputs[0]]
	x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
	x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
	
	if high >= low:
		out_width = high - low + 1
	else:
		out_width = low - high + 1
	
	out_vhdl_type = "unsigned(" + str(out_width-1) + " downto 0)"
	
	wires_decl_text = '''
	--variable x : ''' + x_vhdl_type + ''';
	variable return_output : ''' + out_vhdl_type + ''';
'''

	# Bit slice must always be zero clock
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do a bit slice in multiple clocks!?"
		sys.exit(0)
		
	if high > low:
		# Regular slice
		text = '''
			return_output := unsigned(std_logic_vector(x(''' + str(high) + ''' downto ''' + str(low) + ''')));'''
	else:
		# Reverse slice
		text = '''
			for i in 0 to return_output'length-1 loop
				return_output(i) := x(''' + str(low) + '''- i);
			end loop;
		'''
		
	text += "return return_output;\n"

	return wires_decl_text, text

def GET_ARRAY_TO_UNSIGNED_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params):
	parser_state.LogicInstLookupTable
	# TODO check for ints only?
	# ONLY INTS FOR NOW
	x_type = logic.wire_to_c_type[logic.inputs[0]]
	x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
	# SHould be array
	elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(x_type)
	dim = dims[0]
	out_c_type = logic.wire_to_c_type[logic.outputs[0]]
	out_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(out_c_type, parser_state)
	
	wires_decl_text = '''
	--variable x : ''' + x_vhdl_type + ''';
	variable return_output : ''' + out_vhdl_type + ''';
'''

	# Bit slice must always be zero clock
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do array to unsigned in multiple clocks!?"
		sys.exit(0)
	
	# Big bit concat
	text = "return_output := "
	be_range = range(0, dim)
	le_range = range(dim-1, -1, -1)
	r = be_range
	if logic.func_name.endswith("_le"):
		r = le_range
	for i in r:
		text += "x(" + str(i) + ")&"
	text = text.strip("&")
	text += ";\n"
	text += "return return_output;"

	return wires_decl_text, text

	
def GET_BIT_DUP_C_ENTITY_WIRES_DECL_AND_PACKAGE_STAGES_TEXT(logic, timing_params, parser_state):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# TODO check for ints only?
	# ONLY INTS FOR NOW
	x_type = logic.wire_to_c_type[logic.inputs[0]]
	x_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(x_type, parser_state)
	x_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, x_type)
	# Multiplier
	multiplier = int(logic.func_name.split("_")[1])
	out_width = x_width * multiplier
	out_vhdl_type = "unsigned(" + str(out_width-1) + " downto 0)"
	
	wires_decl_text = '''
	--variable x : ''' + x_vhdl_type + ''';
	variable return_output : ''' + out_vhdl_type + ''';
'''

	# Bit slice must always be zero clock
	if timing_params.GET_TOTAL_LATENCY(parser_state) > 0:
		print "Cannot do a bit dup in multiple clocks!?"
		sys.exit(0)
		
	text = '''
		for i in 0 to ''' + str(multiplier-1) + ''' loop
			return_output( (((i+1)*''' + str(x_width) + ''')-1) downto (i*''' + str(x_width) + ''')) := unsigned(std_logic_vector(x));
		end loop;
'''

	text += "return return_output;"

	return wires_decl_text, text
