#!/usr/bin/env python
import sys
import os
import copy
import math
import math
import hashlib

import C_TO_LOGIC
import SW_LIB
import RAW_VHDL
import SYN
import VIVADO


VHDL_FILE_EXT=".vhd"
VHDL_PKG_EXT=".pkg"+VHDL_FILE_EXT


def WIRE_TO_VHDL_TYPE_STR(wire_name, logic, parser_state=None):
	#print "logic.wire_to_c_type",logic.wire_to_c_type
	c_type_str = logic.wire_to_c_type[wire_name]
	return C_TYPE_STR_TO_VHDL_TYPE_STR(c_type_str, parser_state)
	
def WIRE_TO_VHDL_NULL_STR(global_wire, logic, parser_state):
	c_type_str = logic.wire_to_c_type[global_wire]
	return C_TYPE_STR_TO_VHDL_NULL_STR(c_type_str, parser_state)

# Could be volatile global too
def GLOBAL_WIRE_TO_VHDL_INIT_STR(wire, logic, parser_state):
	# Does this wire have an init?
	leaf = C_TO_LOGIC.LEAF_NAME(wire, True)
	c_type = logic.wire_to_c_type[wire]
	init = None
	if leaf in parser_state.global_info:
		init = parser_state.global_info[leaf].init
	elif leaf in parser_state.volatile_global_info:
		init = parser_state.volatile_global_info[leaf].init
		
	if type(init) == int:
		width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
		if WIRES_ARE_UINT_N([wire], logic) :
			return "to_unsigned(" + str(init) + "," + str(width) + ")"
		elif WIRES_ARE_INT_N([wire], logic):
			return "to_signed(" + str(init) + "," + str(width) + ")"
		else:
			print "What type of int blah?"
			sys.exit(0)

		return 
	# If not use null
	else:
		return WIRE_TO_VHDL_NULL_STR(wire, logic, parser_state)


def WRITE_VHDL_TOP(inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable):	
	timing_params = TimingParamsLookupTable[inst_name]
	filename = GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + "_top.vhd"
	
	rv = ""
	rv += "library ieee;" + "\n"
	rv += "use ieee.std_logic_1164.all;" + "\n"
	rv += "use ieee.numeric_std.all;" + "\n"
	# Include C defined structs
	rv += "use work.c_structs_pkg.all;\n"
	
	latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	needs_clk = LOGIC_NEEDS_CLOCK(inst_name, Logic, parser_state, TimingParamsLookupTable)
	
	rv += "entity " + GET_ENTITY_NAME(inst_name, Logic, TimingParamsLookupTable, parser_state) + "_top is" + "\n"
	rv += "port(" + "\n"
	rv += "	clk : in std_logic;" + "\n"
	# The inputs of the logic
	for input_name in Logic.inputs:
		# Get type for input
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
		
		rv += "	" + WIRE_TO_VHDL_NAME(input_name, Logic) + " : in " + vhdl_type_str + ";" + "\n"
	
	# Output is type of return wire
	vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(Logic.outputs[0],Logic,parser_state)
	rv += "	" + WIRE_TO_VHDL_NAME(Logic.outputs[0], Logic) + " : out " + vhdl_type_str + "" + "\n"
	
	rv += ");" + "\n"
	rv += "end " + GET_ENTITY_NAME(inst_name, Logic, TimingParamsLookupTable, parser_state) + "_top;" + "\n"

	rv += "architecture arch of " + GET_ENTITY_NAME(inst_name, Logic, TimingParamsLookupTable, parser_state) + "_top is" + "\n"
	
	# Dont touch IO
	rv += "attribute dont_touch : string;\n"
	
	# The inputs of the logic
	for input_name in Logic.inputs:
		# Get type for input
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
		rv += "signal " + WIRE_TO_VHDL_NAME(input_name, Logic) + "_input_reg : " + vhdl_type_str + " := " + WIRE_TO_VHDL_NULL_STR(input_name, Logic, parser_state) + ";" + "\n"
		# Dont touch
		rv += "attribute dont_touch of " + WIRE_TO_VHDL_NAME(input_name, Logic) + '''_input_reg : signal is "true";\n'''
		
	rv += "\n"
	
	# Output reg and signal
	output_vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(Logic.outputs[0],Logic,parser_state)
	rv += "signal " + WIRE_TO_VHDL_NAME(Logic.outputs[0], Logic) + "_output : " + output_vhdl_type_str + ";" + "\n"
	rv += "signal " + WIRE_TO_VHDL_NAME(Logic.outputs[0], Logic) + "_output_reg : " + output_vhdl_type_str + ";" + "\n"
	# Dont touch
	rv += "attribute dont_touch of " + WIRE_TO_VHDL_NAME(Logic.outputs[0], Logic) + '''_output_reg : signal is "true";\n'''

	
	# Write vhdl func if needed
	if Logic.is_vhdl_func:
		rv += GET_VHDL_FUNC_DECL(inst_name, Logic, parser_state, timing_params)
	
	rv += "begin" + "\n"
	
	# Instantiate main
	# As entity or as function?
	if Logic.is_vhdl_func:
		# FUNCTION INSTANCE
		rv += WIRE_TO_VHDL_NAME(Logic.outputs[0], Logic) + "_output <= " + Logic.func_name + "(\n"
		# Inputs from regs
		for in_port in Logic.inputs:
			rv += WIRE_TO_VHDL_NAME(in_port, Logic) + "_input_reg"  + ",\n"
		# Remove last two chars
		rv = rv[0:len(rv)-len(",\n")]
		rv += ");\n"
	else:
		# ENTITY
		rv += "-- Instantiate entity\n"
		rv += GET_ENTITY_NAME(inst_name, Logic, TimingParamsLookupTable, parser_state) +" : entity work." + GET_ENTITY_NAME(inst_name, Logic, TimingParamsLookupTable, parser_state) +" port map (\n"
		if needs_clk:
			rv += "clk,\n"
		# Inputs from regs
		for in_port in Logic.inputs:
			rv += WIRE_TO_VHDL_NAME(in_port, Logic) + "_input_reg"  + ",\n"
		# Outputs to signal
		for out_port in Logic.outputs:
			rv += WIRE_TO_VHDL_NAME(out_port, Logic) + "_output" + ",\n"
		# Remove last two chars
		rv = rv[0:len(rv)-len(",\n")]
		rv += ");\n"
	
	rv += "\n"	
	rv += "	" + "-- IO regs\n"
	rv += "	" + "process(clk) is" + "\n"
	rv += "	" + "begin" + "\n"
	rv += "	" + "	" + "if rising_edge(clk) then" + "\n"
	
	# Register inputs
	for input_name in Logic.inputs:
		# Get type for input
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
		rv += "	" + "	" + "	" + WIRE_TO_VHDL_NAME(input_name, Logic) + "_input_reg <= " + WIRE_TO_VHDL_NAME(input_name, Logic) + ";" + "\n"
		
	# Output regs	
	for out_wire in Logic.outputs:
		rv += "	" + "	" + "	" + WIRE_TO_VHDL_NAME(out_wire, Logic) + "_output_reg <= " + WIRE_TO_VHDL_NAME(out_wire, Logic) + "_output;" + "\n"
	
	rv += "	" + "	" + "end if;" + "\n"		
	rv += "	" + "end process;" + "\n"
		
	rv += "	" + WIRE_TO_VHDL_NAME(Logic.outputs[0], Logic) +" <= " + WIRE_TO_VHDL_NAME(Logic.outputs[0], Logic) + "_output_reg;" + "\n"
	rv += "end arch;" + "\n"
	
	if not os.path.exists(output_directory):
		os.mkdirs(output_directory)
	
	#print "NOT WRIT TOP"
	f = open(output_directory+ "/" + filename,"w")
	f.write(rv)
	f.close()
	
def GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type_str):
	if not (C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str)):
		print "Cant GET_WIDTH_FROM_C_TYPE_STR since isnt int/uint N", c_type_str
		print 0/0
		sys.exit(0)	
	return int(c_type_str.replace("uint","").replace("int","").replace("_t",""))
	
def GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type_str):
	if C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str):
		return GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type_str)
	elif c_type_str == "float":
		return 32
	elif c_type_str in parser_state.enum_to_ids_dict:
		# Enum type, width is log2(elements)
		num_ids = len(parser_state.enum_to_ids_dict[c_type_str])
		bits = int(math.ceil(math.log(num_ids,2)))
		return bits	
	else:
		print "Cant GET_WIDTH_FROM_C_TYPE_STR for ", c_type_str
		print 0/0
		sys.exit(0)		
	
	
def C_TYPE_IS_UINT_N(type_str):
	try:
		width = int(type_str.replace("uint","").replace("_t",""))
		return True
	except:
		return False
	
def C_TYPE_IS_INT_N(type_str):
	try:
		width = int(type_str.replace("int","").replace("_t",""))
		return True
	except:
		return False
		
# Includes intN and uintN
def C_TYPES_ARE_INTEGERS(c_types):
	for c_type in c_types:
		if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
			elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
			c_type = elem_type
			#print "c_type",c_type
		
		if not( C_TYPE_IS_INT_N(c_type) or C_TYPE_IS_UINT_N(c_type) ):
			return False
	return True

# Includes intN and uintN
def C_TYPES_ARE_TYPE(c_types, the_type):
	for c_type in c_types:
		if c_type != the_type:
			return False
	return True
		
def C_BUILT_IN_FUNC_IS_RAW_HDL(logic_func_name, input_c_types):
	# IS RAW VHDL
	if  (
		  logic_func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX + "_") or
		  logic_func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SL_NAME + "_") or
		  logic_func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SR_NAME + "_") or
		( logic_func_name.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.UNARY_OP_NOT_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GT_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
	    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_PLUS_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MINUS_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_EQ_NAME)  ) or #and C_TYPES_ARE_INTEGERS(input_c_types)
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_NEQ_NAME)  ) or #and C_TYPES_ARE_INTEGERS(input_c_types)
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_AND_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_OR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_XOR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LT_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LTE_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GTE_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME)	)
		):# or		
		return True
	
	# IS NOT RAW VHDL
	elif (  logic_func_name.startswith(C_TO_LOGIC.VAR_REF_RD_FUNC_NAME_PREFIX + "_")                                                                    or  
		  logic_func_name.startswith(C_TO_LOGIC.VAR_REF_ASSIGN_FUNC_NAME_PREFIX + "_")                                                                or
		  logic_func_name.startswith(C_TO_LOGIC.CAST_FUNC_NAME_PREFIX + "_")                                                                          or
		  logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_DIV_NAME)                                          or
		  logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MULT_NAME)                                         or
		  logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MOD_NAME)                                          or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_SL_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or # ASSUME FOR NOW
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_SR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or # ASSUME FOR NOW
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GT_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GTE_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LT_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LTE_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_PLUS_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MINUS_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float"))
		):
		return False
	else:
		print "Is logic_func_name",logic_func_name,"with input types",input_c_types,"raw VHDL or not?"
		sys.exit(0)
	
	
def GET_ENTITY_PROCESS_STAGES_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	
	timing_params = TimingParamsLookupTable[inst_name]
	package_file_text = ""
	# Raw hdl logic is static in the stages code here but coded as generic
	if len(logic.submodule_instances) <= 0 and logic.func_name != "main":
		package_file_text = RAW_VHDL.GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT(inst_name, logic, parser_state, timing_params)
	else:
		package_file_text = GET_C_ENTITY_PROCESS_STAGES_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable)
	
	return package_file_text


def WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(parser_state):
	
	text = ""
	
	text += '''
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
-- All structs defined in C code

package c_structs_pkg is
'''
	
	
	# Do this stupid dumb loop to resolve dependencies
	# Hacky resolve dependencies
	types_written = []
	# Uhh sooopppaa hacky
	for i in range(1, 257):
		types_written.append("uint" + str(i) + "_t")
		types_written.append("int" + str(i) + "_t")
	# Oh dont forget to be extra dumb
	types_written.append("float")
	
	
	# Write structs
	done = False
	while not done:
		done = True
	
	
		######## ENUMS
		# Enum types
		for enum_name in parser_state.enum_to_ids_dict.keys():		
			if enum_name not in types_written:
				done = False
				types_written.append(enum_name)
				# Type
				text += '''
	type ''' + enum_name + ''' is (
		'''	
				ids_list = parser_state.enum_to_ids_dict[enum_name]
				for field in ids_list:
					text += '''
			''' + field + ''','''
				
				text = text.strip(",")
				text += '''
	);
	'''

	
		########## ARRAYS
		# C arrays are multidimensional and single element type
		# Find all array types - need to do this since array types are not (right now) 
		# declared/typedef individually like structs
		array_types = []
		for func_name in parser_state.FuncLogicLookupTable:
			logic = parser_state.FuncLogicLookupTable[func_name]
			for wire in logic.wire_to_c_type:
				c_type = logic.wire_to_c_type[wire]
				if (c_type not in types_written) and C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type) and (c_type not in array_types):
					elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
					if elem_type in types_written:
						array_types.append(c_type)
		# Get array types declared in structs
		for struct_name in parser_state.struct_to_field_type_dict:
			field_type_dict = parser_state.struct_to_field_type_dict[struct_name]
			for field_name in field_type_dict:
				field_type = field_type_dict[field_name]
				if  (field_type not in types_written) and C_TO_LOGIC.C_TYPE_IS_ARRAY(field_type) and not(field_type in array_types):
					elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(field_type)
					if elem_type in types_written:
						array_types.append(field_type)	
									
		# Write VHDL type for each
		for array_type in array_types:
			vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(array_type,parser_state)
			elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(array_type)
			# type uint64_t_3_4 is array(0 to 2) of uint64_t_4;
			for i in range(len(dims)-1, -1, -1):
				# Build type
				new_dims = dims[i:]
				new_type = elem_type
				for new_dim in new_dims:
					new_type += "[" + str(new_dim) + "]"
				
				# Write the type if nto already written
				if new_type not in types_written:
					types_written.append(new_type)
					done = False
					new_vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(new_type,parser_state)
					inner_type_dims = new_dims[1:]
					inner_type = elem_type
					for inner_type_dim in inner_type_dims:
						inner_type += "[" + str(inner_type_dim) + "]"
					inner_vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(inner_type,parser_state)
					line = "type " + new_vhdl_type + " is array(0 to " + str(new_dims[0]-1) + ") of " + inner_vhdl_type + ";\n"
					text += line
	

		######## STRUCTS
		for struct_name in parser_state.struct_to_field_type_dict:
			#print "STRUCT",struct_name, struct_name in types_written
			# When to stop?
			if struct_name in types_written:
				continue	
							
			# Resolve dependencies:
			# Check if all the types for this struct are written or not structs
			field_type_dict = parser_state.struct_to_field_type_dict[struct_name]
			field_types_written = True
			for field in field_type_dict:
				c_type = field_type_dict[field]
				if c_type not in types_written:
					#print c_type, "NOT IN TYPES WRITTEN"
					field_types_written = False
					break
			if not field_types_written:
				continue
					
			
			# Write type
			types_written.append(struct_name)
			done = False
				
			text += '''
	type ''' + struct_name + ''' is record
	'''
			for field in field_type_dict:
				c_type = field_type_dict[field]
				vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type,parser_state)
				text += '''
		''' + field + ''' : ''' + vhdl_type + ''';'''
			
			text += '''
	end record;
	'''

			# Null value
			text += '''
	constant ''' + struct_name + '''_NULL : ''' + struct_name + ''' := (
	'''
			for field in field_type_dict:
				c_type = field_type_dict[field]
				vhdl_null_str = C_TYPE_STR_TO_VHDL_NULL_STR(c_type,parser_state)
				text += '''
		''' + field + ''' => ''' + vhdl_null_str + ''','''
		
			text = text.strip(",")
			
			text += '''
	);
	'''
			
			
		
	######################
	# End dumb while loop				
	

	text += '''
end c_structs_pkg;
'''
	
	if not os.path.exists(SYN.SYN_OUTPUT_DIRECTORY):
		os.makedirs(SYN.SYN_OUTPUT_DIRECTORY)	
	
	
	path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "c_structs_pkg" + VHDL_PKG_EXT
	
	f=open(path,"w")
	f.write(text)
	f.close()
	
def LOGIC_NEEDS_CLOCK(inst_name, Logic, parser_state, TimingParamsLookupTable):
	timing_params = TimingParamsLookupTable[inst_name]
	latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	i_need_clk = latency>0 or len(Logic.global_wires) > 0 or len(Logic.volatile_global_wires) > 0
	
	needs_clk = i_need_clk
	# Check submodules too
	for inst in Logic.submodule_instances:
		instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
		submodule_logic_name = Logic.submodule_instances[inst]
		submodule_logic = parser_state.LogicInstLookupTable[instance_name]
		needs_clk = needs_clk or LOGIC_NEEDS_CLOCK(instance_name, submodule_logic, parser_state, TimingParamsLookupTable)
	
	return needs_clk
	
def GET_ARCH_DECL_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
	if SW_LIB.IS_MEM(Logic):
		return RAW_VHDL.GET_MEM_ARCH_DECL_TEXT(Logic, parser_state, TimingParamsLookupTable)
	else:
		return GET_PIPELINE_ARCH_DECL_TEXT(inst_name,Logic, parser_state, TimingParamsLookupTable)
		
def GET_PIPELINE_ARCH_DECL_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
	timing_params = TimingParamsLookupTable[inst_name]
	latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	
	rv = ""
	# Stuff originally in package
	rv += "-- Types and such\n"
	rv += "-- Declarations\n"
	
	# Declare total latency for Logic
	rv += "constant LATENCY : integer := " + str(latency) + ";\n"
	
	

	# Type for wires/variables
	varables_t_pre = ""
	varables_t_pre += "\n"
	varables_t_pre += "-- One struct to represent this modules variables\n"
	varables_t_pre += "type variables_t is record\n"
	varables_t_pre += "	-- All of the wires in function\n"
	wrote_variables_t = False
	# Raw HDL functions are done differently
	if len(Logic.submodule_instances) <= 0 and Logic.func_name != "main":
		text = RAW_VHDL.GET_RAW_HDL_WIRES_DECL_TEXT(inst_name, Logic, parser_state, timing_params)
		if text != "":
			rv += varables_t_pre
			rv += text
			rv += "end record;\n"
			wrote_variables_t = True
	else:
		wrote_variables_t = True
		rv += varables_t_pre
		# Not c built in
		# First get wires from declarations and assignments Logic itself
		# sort wires so easy to find bugs?
		text_additions = []
		for wire_name in Logic.wire_to_c_type:
			# Skip constants here
			if C_TO_LOGIC.WIRE_IS_CONSTANT(wire_name):
				continue

			# Skip globals too
			if wire_name in Logic.global_wires:
				continue
			# Dont skip volatile globals, they are like regular wires
				
			#print "wire_name", wire_name
			vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(wire_name, Logic, parser_state)
			#print "wire_name",wire_name
			write_pipe_wire_var_vhdl = WIRE_TO_VHDL_NAME(wire_name, Logic)
			#print "write_pipe_wire_var_vhdl",write_pipe_wire_var_vhdl
			text_additions.append("	" + write_pipe_wire_var_vhdl + " : " + vhdl_type_str + ";\n")
		text_additions.sort()
		for text_addition in text_additions:
			rv += text_addition
			
		rv += "end record;\n"
	
	
	
	if wrote_variables_t:
		rv += '''
-- Type for this modules register pipeline
type register_pipeline_t is array(0 to LATENCY) of variables_t;
	'''
	
		
	# GLOBALS
	if len(Logic.global_wires) > 0:
		rv += '''
-- Type holding all global registers
type global_registers_t is record'''
		# Each func instance gets records
		rv += '''
	-- Global vars\n'''
		#print "Logic.global_wires",Logic.global_wires
		for global_wire in Logic.global_wires:
			vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(global_wire, Logic, parser_state)
			vhdl_name = WIRE_TO_VHDL_NAME(global_wire, Logic)
			rv += "	" + vhdl_name + " : " + vhdl_type_str + ";\n"
		rv += "end record;\n"
		
	# VOLATILE GLOBALS
	if len(Logic.volatile_global_wires) > 0:
		rv += '''
-- Type holding all volatile global registers
type volatile_global_registers_t is record'''
		# Each func instance gets records
		rv += '''
	-- Volatile global vars\n'''
		for volatile_global_wire in Logic.volatile_global_wires:
			vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(volatile_global_wire, Logic, parser_state)
			vhdl_name = WIRE_TO_VHDL_NAME(volatile_global_wire, Logic)
			rv += "	" + vhdl_name + " : " + vhdl_type_str + ";\n"
		rv += "end record;\n"
		
		
		
	# ALL REGISTERS
	rv += '''	
-- Type holding all registers for this function
type registers_t is record'''
	if wrote_variables_t:
		rv += '''
	self : register_pipeline_t;'''
	
	# Global regs
	if len(Logic.global_wires) > 0:
		rv += '''
	global_regs : global_registers_t;'''
	# Volatile global regs
	if len(Logic.volatile_global_wires) > 0:
		rv += '''
	volatile_global_regs : volatile_global_registers_t;'''
	
	
	
	rv += '''	
end record;
'''	
	
	# Function to null out globals
	rv += "\n-- Function to null out just global regs\n"
	rv += "function registers_NULL return registers_t is\n"
	rv += '''	variable rv : registers_t;
begin
'''
	# Do each global var
	for global_wire in Logic.global_wires:
		rv += "	rv.global_regs." + WIRE_TO_VHDL_NAME(global_wire, Logic) + " := " + GLOBAL_WIRE_TO_VHDL_INIT_STR(global_wire, Logic, parser_state) + ";\n"
	# Volatile globals too?
	for volatile_global_wire in Logic.volatile_global_wires:
		rv += "	rv.volatile_global_regs." + WIRE_TO_VHDL_NAME(volatile_global_wire, Logic) + " := " + GLOBAL_WIRE_TO_VHDL_INIT_STR(volatile_global_wire, Logic, parser_state) + ";\n"
	
	rv += '''
	return rv;
end function;\n
'''
	
	
	
	rv += '''-- Registers and signals for this function\n'''
	# Comb signal of main regs
	rv += "signal " + "registers : registers_t;\n"
	# Main regs nulled out
	rv += "signal " + "registers_r : registers_t := registers_NULL;\n"
	rv += "\n"

	# Signals for submodule ports
	rv += '''-- Each function instance gets signals\n'''
	for inst in Logic.submodule_instances:
		instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
		submodule_logic_name = Logic.submodule_instances[inst]
		submodule_logic = parser_state.LogicInstLookupTable[instance_name]
		rv += "-- " + instance_name + "\n"
		# Inputs
		for in_port in submodule_logic.inputs:
			in_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + in_port
			vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(in_wire,Logic,parser_state)
			rv += "signal " + WIRE_TO_VHDL_NAME(in_wire, Logic)	 + " : " + vhdl_type_str + ";\n"
		# Outputs
		for out_port in submodule_logic.outputs:
			out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
			vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(out_wire,Logic,parser_state)
			rv += "signal " + WIRE_TO_VHDL_NAME(out_wire, Logic) + " : " + vhdl_type_str + ";\n"
		rv += "\n"
		
		
	# Certain submodules are always 0 delay "IS_VHDL_FUNC"
	rv += GET_VHDL_FUNC_SUBMODULE_DECLS(inst_name, Logic, parser_state, TimingParamsLookupTable)

	rv += "\n"
	
	return rv
	
	
def GET_VHDL_FUNC_SUBMODULE_DECLS(inst_name, Logic, parser_state, TimingParamsLookupTable):
	rv = ""
	vhdl_funcs = []
	for inst in Logic.submodule_instances:
		instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
		submodule_logic_name = Logic.submodule_instances[inst]
		timing_params = TimingParamsLookupTable[instance_name]
		submodule_logic = parser_state.LogicInstLookupTable[instance_name]
		if submodule_logic.is_vhdl_func and submodule_logic.func_name not in vhdl_funcs:
			vhdl_funcs.append(submodule_logic.func_name)
			rv += GET_VHDL_FUNC_DECL(instance_name, submodule_logic, parser_state, timing_params)
			rv += "\n"
	return rv;
	
def GET_VHDL_FUNC_DECL(inst_name, vhdl_func_logic, parser_state, timing_params):
	
	# Modelsim doesnt like 'subtype' names in funcs?
	# (vcom-1115) Subtype indication found where type mark is required.
	def modeldumbsim(vhdl_type_str):
		if vhdl_type_str.startswith("unsigned"):
			vhdl_type_str = "unsigned"
		if vhdl_type_str.startswith("signed"):
			vhdl_type_str = "signed"
		if vhdl_type_str.startswith("std_logic_vector"):
			vhdl_type_str = "std_logic_vector"
		return vhdl_type_str		
	
	rv = ""
	
	rv = '''
function ''' + vhdl_func_logic.func_name + '''('''
	# The inputs of the Logic
	for input_name in vhdl_func_logic.inputs:
		# Get type for input
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,vhdl_func_logic,parser_state)
		vhdl_type_str = modeldumbsim(vhdl_type_str)		
		rv += "	" + WIRE_TO_VHDL_NAME(input_name, vhdl_func_logic) + " : " + vhdl_type_str + ";\n"
	
	# Remove last line and semi
	rv = rv.strip("\n")
	rv = rv.strip(";")
	
	# Output is type of return wire
	vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(vhdl_func_logic.outputs[0],vhdl_func_logic,parser_state)
	vhdl_type_str = modeldumbsim(vhdl_type_str)
	
	# Finish params
	rv += ") return " + vhdl_type_str + " is\n"
	
	# Wires (abusing existing function)
	rv += RAW_VHDL.GET_RAW_HDL_WIRES_DECL_TEXT(inst_name, vhdl_func_logic, parser_state, timing_params)
	
	# Func logic (abuse existing logic)
	rv += "\n"
	rv += "begin\n"
	rv += RAW_VHDL.GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT(inst_name, vhdl_func_logic, parser_state, timing_params)
	rv += "\n"
	# End func
	rv += '''
end function;
	'''
	
	return rv
	

	
def WRITE_VHDL_ENTITY(inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable):	
	# Sanity check until complete sanity has been 100% ensured with absolute certainty
	if Logic.is_vhdl_func:
		print "Why write vhdl func entity?"
		print 0/0
		sys.exit(0)
	
	timing_params = TimingParamsLookupTable[inst_name]
	filename = GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + ".vhd"
	
	rv = ""
	rv += "library ieee;" + "\n"
	rv += "use ieee.std_logic_1164.all;" + "\n"
	rv += "use ieee.numeric_std.all;" + "\n"
	rv += "library ieee_proposed;" + "\n"
	rv += "use ieee_proposed.float_pkg.all;" + "\n" #
	# Include C defined structs
	rv += "use work.c_structs_pkg.all;\n"
	
	latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	needs_clk = LOGIC_NEEDS_CLOCK(inst_name,Logic, parser_state, TimingParamsLookupTable)
	
	rv += "entity " + GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + " is" + "\n"
	rv += "port(" + "\n"
	if needs_clk:
		rv += "	clk : in std_logic;" + "\n"
	# The inputs of the Logic
	for input_name in Logic.inputs:
		# Get type for input
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
		
		rv += "	" + WIRE_TO_VHDL_NAME(input_name, Logic) + " : in " + vhdl_type_str + ";" + "\n"
	
	# Output is type of return wire
	vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(Logic.outputs[0],Logic,parser_state)
	rv += "	" + WIRE_TO_VHDL_NAME(Logic.outputs[0], Logic) + " : out " + vhdl_type_str + "" + "\n"
	
	rv += ");" + "\n"
	rv += "end " + GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + ";" + "\n"

	rv += "architecture arch of " + GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + " is" + "\n"
	
	# Get declarations for this arch
	rv += GET_ARCH_DECL_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
	
	rv += "begin" + "\n"

	rv += "\n"
	# Connect submodules
	if len(Logic.submodule_instances) > 0:
		rv += "-- SUBMODULE INSTANCES \n"
		for inst in Logic.submodule_instances:
			instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
			submodule_logic_name = Logic.submodule_instances[inst]
			submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
			new_inst_name = WIRE_TO_VHDL_NAME(inst, Logic)
			rv += "-- " + new_inst_name + "\n"
			
			# AS ENTITY OR FUNC?
			if submodule_logic.is_vhdl_func:
				# FUNC INSTANCE
				out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + submodule_logic.outputs[0]
				rv += WIRE_TO_VHDL_NAME(out_wire, Logic) + " <= " + submodule_logic.func_name + "(\n"
				for in_port in submodule_logic.inputs:
					in_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + in_port
					rv += WIRE_TO_VHDL_NAME(in_wire, Logic) + ",\n"
				# Remove last two chars
				rv = rv[0:len(rv)-2]
				rv += ");\n\n"
			else:
				# ENTITY
				submodule_timing_params = TimingParamsLookupTable[instance_name];
				submodule_latency = submodule_timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
				submodule_needs_clk = LOGIC_NEEDS_CLOCK(instance_name, submodule_logic, parser_state, TimingParamsLookupTable)
				rv += new_inst_name+" : entity work." + GET_ENTITY_NAME(instance_name, submodule_logic,TimingParamsLookupTable, parser_state) +" port map (\n"
				if submodule_needs_clk:
					rv += "clk,\n"
				# Inputs
				for in_port in submodule_logic.inputs:
					in_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + in_port
					rv += WIRE_TO_VHDL_NAME(in_wire, Logic) + ",\n"
				# Outputs
				for out_port in submodule_logic.outputs:
					out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
					rv += WIRE_TO_VHDL_NAME(out_wire, Logic) + ",\n"
				# Remove last two chars
				rv = rv[0:len(rv)-2]
				rv += ");\n\n"
				
	# Get the text that is actually the pipeline logic in this entity
	rv += "\n"
	rv += GET_PIPELINE_LOGIC_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
	
	# Done with entity
	rv += "end arch;" + "\n"

	if not os.path.exists(output_directory):
		os.mkdirs(output_directory)
	
	#print "NOT WRITE ENTITY"
	f = open(output_directory+ "/" + filename,"w")
	f.write(rv)
	f.close()
	
def GET_PIPELINE_LOGIC_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
	# Special case logic that does not do usage pipeline
	if SW_LIB.IS_MEM(Logic):
		return RAW_VHDL.GET_MEM_PIPELINE_LOGIC_TEXT(Logic, parser_state, TimingParamsLookupTable)
	else:
		# Regular comb logic pipeline
		return GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)

def GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
	# Comb Logic pipeline
	needs_clk = LOGIC_NEEDS_CLOCK(inst_name, Logic, parser_state, TimingParamsLookupTable)
	rv = ""
	rv += "\n"
	rv += "	-- Combinatorial process for pipeline stages\n"
	rv += "process (\n"
	rv += "	-- Inputs\n"
	for input_wire in Logic.inputs:
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_wire, Logic, parser_state)
		rv += "	" + WIRE_TO_VHDL_NAME(input_wire, Logic) + ",\n"
	rv += "	-- Registers\n"
	rv += "	" + "registers_r,\n"
	if len(Logic.submodule_instances) > 0:
		rv += "	-- All submodule outputs\n"
		# Connect submodules
		for inst in Logic.submodule_instances:
			instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
			submodule_logic_name = Logic.submodule_instances[inst]
			submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
			new_inst_name = C_TO_LOGIC.LEAF_NAME(instance_name, do_submodule_split=True)
			rv += "	-- " + new_inst_name + "\n"
			# Outputs
			if len(submodule_logic.outputs) <= 0:
				print "Submodule has no outputs?", instance_name
				sys.exit(0)
			for out_port in submodule_logic.outputs:
				out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
				rv += "	" + WIRE_TO_VHDL_NAME(out_wire, Logic) + ",\n"
	# Remove last two chars
	rv = rv[0:len(rv)-2]
	rv += ")\n"
	rv += "is \n"
	
	# READ PIPE
	rv += "	-- Read and write variables to do register transfers per clock\n"
	rv += "	-- from the previous to next stage\n"
	rv += "	" + "variable read_pipe : variables_t;\n"
	rv += "	" + "variable write_pipe : variables_t;\n"
	
	
	# Self regs
	rv += '''
	-- This modules self pipeline registers read once per clock
	variable read_self_regs : register_pipeline_t;
	variable write_self_regs : register_pipeline_t;
'''	
	
	# Global regs
	if len(Logic.global_wires) > 0:
		rv += "	" + "-- Global registers read once per clock\n"
		rv += "	" + "variable read_global_regs : global_registers_t;\n"
		rv += "	" + "variable write_global_regs : global_registers_t;\n"
	# Volatile global regs
	if len(Logic.volatile_global_wires) > 0:
		rv += "	" + "-- Volatile global registers read once per clock\n"
		rv += "	" + "variable read_volatile_global_regs : volatile_global_registers_t;\n"
		rv += "	" + "variable write_volatile_global_regs : volatile_global_registers_t;\n"
	
	
	# BEGIN BEGIN BEGIN
	rv += "begin\n"
	
	# Self regs
	rv += '''
	-- SELF REGS
	-- Default read self regs once per clock
	read_self_regs := registers_r.self;
	-- Default write contents of self regs
	write_self_regs := read_self_regs;'''
	
	
	# Globals
	if len(Logic.global_wires) > 0:
		rv += '''
	-- GLOBAL REGS
	-- Default read global regs once per clock
	read_global_regs := registers_r.global_regs;
	-- Default write contents of global regs
	write_global_regs := read_global_regs;
'''
	# Volatile globals
	if len(Logic.volatile_global_wires) > 0:
		rv += '''
	-- VOLATILE GLOBAL REGS
	-- Default read volatile global regs once per clock
	read_volatile_global_regs := registers_r.volatile_global_regs;
	-- Default write contents of volatile global regs
	write_volatile_global_regs := read_volatile_global_regs;
'''
	
	rv += "	-- Loop to construct simultaneous register transfers for each of the pipeline stages\n"
	rv += "	-- LATENCY=0 is combinational Logic\n"
	rv += "	" + "for STAGE in 0 to LATENCY loop\n"
	rv += "	" + "	" + "-- Input to first stage are inputs to function\n"
	rv += "	" + "	" + "if STAGE=0 then\n"
	rv += "	" + "	" + "	" + "-- Mux in inputs\n"
	for input_wire in Logic.inputs:
		rv += "	" + "	" + "	" + "read_pipe." + WIRE_TO_VHDL_NAME(input_wire, Logic) + " := " + WIRE_TO_VHDL_NAME(input_wire, Logic) + ";\n"
	if len(Logic.volatile_global_wires) > 0:
		# Also mux volatile global regs into wires
		rv += "	" + "	" + "	" + "-- Mux in volatile globals\n"
		for volatile_global_wire in Logic.volatile_global_wires:
			rv += "	" + "	" + "	" + "read_pipe." + WIRE_TO_VHDL_NAME(volatile_global_wire, Logic) + " := write_volatile_global_regs." + WIRE_TO_VHDL_NAME(volatile_global_wire, Logic) + ";\n"
			
	rv += "	" + "	" + "else\n"
	rv += "	" + "	" + "	" + "-- Default read from previous stage\n"
	rv += "	" + "	" + "	" + "read_pipe := " + "read_self_regs(STAGE-1);\n"
	#rv += "	" + "	" + "	" + "read_pipe := " + "write_self_regs(STAGE-1);\n"
	rv += "	" + "	" + "end if;\n"
	rv += "	" + "	" + "-- Default write contents of previous stage\n"
	rv += "	" + "	" + "write_pipe := read_pipe;\n"
	rv += "\n"
	
	# C built in Logic is static in the stages code here but coded as generic
	rv += GET_ENTITY_PROCESS_STAGES_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
		
	rv += "	" + "	" + "-- Write to stage reg\n"
	rv += "	" + "	" + "write_self_regs(STAGE) := write_pipe;\n"
	rv += "	" + "end loop;\n"
	rv += "\n"
	if len(Logic.volatile_global_wires) > 0:
		rv += "	" + "-- Last stage of pipeline volatile global wires write to function volatile global regs\n"
		for volatile_global_wire in Logic.volatile_global_wires:
			rv += "	" + "write_volatile_global_regs." + WIRE_TO_VHDL_NAME(volatile_global_wire, Logic) + " := write_self_regs(LATENCY)." + WIRE_TO_VHDL_NAME(volatile_global_wire, Logic) + ";\n"
	rv += "\n"	
	rv += "	" + "-- Drive registers and outputs\n"
	rv += "	" + "-- Last stage of pipeline return wire to entity return port\n"
	rv += "	" + C_TO_LOGIC.RETURN_WIRE_NAME + " <= " + "write_self_regs(LATENCY)." + C_TO_LOGIC.RETURN_WIRE_NAME + ";\n"
	rv += "	" + "registers.self <= write_self_regs;\n"
	# 	Globals
	if len(Logic.global_wires) > 0:
		rv += "	" + "registers.global_regs <= write_global_regs;\n"
	# 	Volatile globals
	if len(Logic.volatile_global_wires) > 0:
		rv += "	" + "registers.volatile_global_regs <= write_volatile_global_regs;\n"
		
	rv += "end process;\n"
	
	# Register the combinatorial registers signal
	if needs_clk:
		rv += "registers_r <= registers when rising_edge(clk);\n"
		
	return rv
	

			
# Returns dict[stage_num]=stage_text
def GET_C_ENTITY_PROCESS_PER_STAGE_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# Get the per stage texts and combine
	per_stage_texts = GET_C_ENTITY_PROCESS_PER_STAGE_SUDMODULE_LEVEL_TEXTS(inst_name, logic, parser_state, TimingParamsLookupTable)
	
	per_stage_text = dict()
	for stage in per_stage_texts:
		per_stage_text[stage] = ""
		stages_texts = per_stage_texts[stage]
		for text in stages_texts:
			per_stage_text[stage] += text
	
	return per_stage_text
	
def TYPE_RESOLVE_ASSIGNMENT_RHS(RHS, logic, driving_wire, driven_wire, parser_state):
	# Need conversion from right to left?
	right_type = logic.wire_to_c_type[driving_wire]
	#print "driving_wire",driving_wire, right_type
	left_type = logic.wire_to_c_type[driven_wire]
	if left_type != right_type:
		# DO VHDL CONVERSION FUNCTIONS
		resize_toks = []
		
		# Combine driving and driven into one list
		wires_to_check = [driving_wire, driven_wire]
		# If both are of same type then VHDL resize should work
		if WIRES_ARE_INT_N(wires_to_check, logic) or  WIRES_ARE_UINT_N(wires_to_check, logic):
			# Do integer promotion conversion
			right_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
			left_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
			# Can resize do smaller, and unsigned to unsigned too?
			resize_toks = ["resize(", ", " + str(left_width) + ")" ]
			
		# Otherwise need to 
		# UINT driving INT
		elif WIRES_ARE_INT_N([driven_wire], logic) and WIRES_ARE_UINT_N([driving_wire], logic):
			right_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
			left_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
			# Just need to add sign bit
			#signed(std_logic_vector(resize(x,left_width)))
			resize_toks = ["signed(std_logic_vector(resize(", ", " + str(left_width) + ")))" ]		
			
		# INT driving UINT
		elif WIRES_ARE_UINT_N([driven_wire], logic) and WIRES_ARE_INT_N([driving_wire], logic):
			right_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
			left_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
			
			# Dont infer sign extend
			if left_width > right_width:
				print "What to do about sign extension ? Can't infer if RHS should be sign extended?"
				print "driven_wire",driven_wire,left_type
				print "driving_wire",driving_wire,right_type
				sys.exit(0)
			else:			
				# Cast int to slv then to unsigned then resize
				#resize(unsigned(std_logic_vector(x)),31)
				#signed(std_logic_vector(resize(x,left_width)))
				resize_toks = ["resize(unsigned(std_logic_vector(", "))," + str(left_width) + ")" ]	
			
		# ENUM DRIVING UINT is ok
		elif WIRES_ARE_UINT_N([driven_wire], logic) and (logic.wire_to_c_type[driving_wire] in parser_state.enum_to_ids_dict):
			left_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
			if right_type in parser_state.enum_to_ids_dict:
				num_ids = len(parser_state.enum_to_ids_dict[right_type])
				right_width = int(math.ceil(math.log(num_ids,2)))
			else:
				right_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
			max_width = max(left_width,right_width)
			resize_toks = ["to_unsigned(" + right_type + "'pos(" , ") ," + str(max_width) + ")"]
		else:
			print "What cant support this assignment in vhdl?"
			print driving_wire, right_type
			print "DRIVING"
			print driven_wire, left_type
			sys.exit(0)
		
		
		# APPPLY CONVERSION
		RHS = resize_toks[0] + RHS + resize_toks[1]	
		
			
	return RHS


	
def GET_C_ENTITY_PROCESS_PER_STAGE_SUDMODULE_LEVEL_TEXTS(inst_name, logic, parser_state, TimingParamsLookupTable):
	pipeline_map = SYN.GET_PIPELINE_MAP(inst_name, logic, parser_state, TimingParamsLookupTable)
	return pipeline_map.per_stage_texts 

def GET_C_ENTITY_PROCESS_STAGES_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable):
	# Get text per stage
	per_stage_text = GET_C_ENTITY_PROCESS_PER_STAGE_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable)
	
	package_file_text = ""
	for stage_num in range(0, len(per_stage_text)):
		# Write if stage= portion
		if stage_num == 0:
			package_file_text += "	" + "	" + "if STAGE = 0 then\n"
		else:
			package_file_text += "	" + "	" + "elsif STAGE = " + str(stage_num) + " then\n"
	
		# Write the text
		package_file_text += per_stage_text[stage_num]
		
	# End the stages if
	package_file_text += "	" + "	" + "end if;\n"
	
	return package_file_text
	

	
def WIRES_ARE_ENUM(wires, logic, parser_state):
	for wire in wires:
		#print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
		if not C_TO_LOGIC.WIRE_IS_ENUM(wire, logic, parser_state):
			return False
	return True

	

def WIRES_ARE_C_TYPE(wires,c_type_str, logic):
	for wire in wires:
		#print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
		if c_type_str != logic.wire_to_c_type[wire]:
			return False
	return True
	

def WIRES_ARE_UINT_N(wires, logic):
	for wire in wires:
		#print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
		if not C_TYPE_IS_UINT_N(logic.wire_to_c_type[wire]):
			return False
	return True

def WIRES_ARE_INT_N(wires, logic):
	for wire in wires:
		#print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
		if not C_TYPE_IS_INT_N(logic.wire_to_c_type[wire]):
			return False
	return True


	
	
def WIRES_TO_C_INT_BIT_WIDTH(wires,logic):
	rv_width = None
	for wire in wires:
		c_type = logic.wire_to_c_type[wire]
		width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
		if rv_width is None:
			rv_width = width
		else:
			if rv_width != width:
				print "Inputs not all same width for C int?", logic.func_name
				print logic.wire_to_c_type
				print "rv_width, width", rv_width, width
				print 0/0
				sys.exit(0)
	return rv_width
	
def GET_RHS(driving_wire_to_handle, inst_name, logic, parser_state, TimingParamsLookupTable, timing_params, stage_ordered_submodule_list, stage):
	RHS = ""
	# SUBMODULE PORT?
	if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(driving_wire_to_handle, logic):		
		# Get submodule name
		toks=driving_wire_to_handle.split(C_TO_LOGIC.SUBMODULE_MARKER)
		driving_submodule_name = C_TO_LOGIC.SUBMODULE_MARKER.join(toks[0:len(toks)-1])
		driving_submodule_inst_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + driving_submodule_name
		driving_submodule_latency = timing_params.GET_SUBMODULE_LATENCY(driving_submodule_inst_name, parser_state, TimingParamsLookupTable)
		
		# Which stage was the driving submodule inst
		driving_submodule_stage = None
		for stage_i in stage_ordered_submodule_list:
			submodules_in_stage = stage_ordered_submodule_list[stage_i]
			if driving_submodule_name in submodules_in_stage:
				driving_submodule_stage = stage_i
			
		
		# DO NOT USE write_pipe FOR SUBMOUDLE OUTPUT LATER LATENCY
		'''
		if STAGE = 0 then
			write_pipe.BIN_OP_PLUS_main_c_7_left := write_pipe.x; -- main____BIN_OP_PLUS[main_c_7]____left <= main____x
			write_pipe.BIN_OP_PLUS_main_c_7_right := write_pipe.y; -- main____BIN_OP_PLUS[main_c_7]____right <= main____y
			-- BIN_OP_PLUS[main_c_7] LATENCY=2
			main_BIN_OP_PLUS_main_c_7(write_pipe.BIN_OP_PLUS_main_c_7_right, write_pipe.BIN_OP_PLUS_main_c_7_left, write_submodule_regs.BIN_OP_PLUS_main_c_7_registers, write_pipe.BIN_OP_PLUS_main_c_7_return_output);
		elsif STAGE = 1 then
		elsif STAGE = 2 then
			write_pipe.local_main_c_7_0 := write_pipe.BIN_OP_PLUS_main_c_7_return_output; -- main____local_main_c_7_0 <= main____BIN_OP_PLUS[main_c_7]____return_output
			write_pipe.return_output := write_pipe.local_main_c_7_0; -- main____return_output <= main____local_main_c_7_0
		end if;
		'''
		# In above example read of "write_pipe.BIN_OP_PLUS_main_c_7_return_output" in stage 2 is getting the value of BIN_OP_PLUS's output during stage 0 not what we want
		if driving_submodule_stage == stage:
			# Same stage / zero latency use regular write pipe
			RHS = GET_WRITE_PIPE_WIRE_VHDL(driving_wire_to_handle, logic, parser_state)
		else:
			# Different, previous stage, use signal from submodule instance if latency > 0 
			if driving_submodule_latency > 0:
				# Use signal from submodule entity
				RHS = WIRE_TO_VHDL_NAME(driving_wire_to_handle, logic)
			else:
				RHS = GET_WRITE_PIPE_WIRE_VHDL(driving_wire_to_handle, logic, parser_state)
		
		
		
	# GLOBAL?
	elif driving_wire_to_handle in logic.global_wires:
		#print "DRIVING WIRE GLOBAL"						
		# Globals come from input regs to this process
		RHS = "write_global_regs." + WIRE_TO_VHDL_NAME(driving_wire_to_handle, logic)
	# Volatile globals are like regular wires
	else:
		# Otherwise use regular wire connection
		RHS = GET_WRITE_PIPE_WIRE_VHDL(driving_wire_to_handle, logic, parser_state)
		
	return RHS
	
def GET_LHS(driven_wire_to_handle, logic, parser_state):
	LHS = ""
	# SUBMODULE PORT?
	if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(driven_wire_to_handle, logic):
		LHS = GET_WRITE_PIPE_WIRE_VHDL(driven_wire_to_handle, logic, parser_state)

	# GLOBAL?
	elif driven_wire_to_handle in logic.global_wires:
		#print "DRIVING WIRE GLOBAL"						
		# Globals come from input regs to this process
		LHS = "write_global_regs." + WIRE_TO_VHDL_NAME(driven_wire_to_handle, logic)
	# Volatile globals are like regular wires
	else:
		# Otherwise use regular wire connection
		LHS = GET_WRITE_PIPE_WIRE_VHDL(driven_wire_to_handle, logic, parser_state)
		
	return LHS

def GET_WRITE_PIPE_WIRE_VHDL(wire_name, Logic, parser_state):	
	# If a constant 
	if C_TO_LOGIC.WIRE_IS_CONSTANT(wire_name):
		# Use type to cast value string to type
		c_type =  Logic.wire_to_c_type[wire_name]
		val_str = C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE(wire_name, Logic, parser_state)
		
		if C_TYPE_IS_UINT_N(c_type):
			width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
			return "to_unsigned(" + val_str + ", " + str(width) + ")"
		elif C_TYPE_IS_INT_N(c_type):
			width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
			return "to_signed(" + val_str + ", " + str(width) + ")"
		elif c_type == "float":
			return "to_slv(to_float(" + val_str + ", 8, 23))"
		else:
			# ASSUMING ENUM AAUAUGHGHGHG????
			#print "wire_name",wire_name
			toks = wire_name.split(C_TO_LOGIC.SUBMODULE_MARKER)
			toks.reverse()
			local_name = toks[0]
			enum_wire = local_name.split("$")[0]
			if not enum_wire.startswith(C_TO_LOGIC.CONST_PREFIX):
				print "Non const enum constant?",enum_wire
				sys.exit(0)
			enum_name = enum_wire[len(C_TO_LOGIC.CONST_PREFIX):]
			#print "local_name",local_name
			#print "enum_name",enum_name
			
			# Sanity check that enum exists?
			match = False
			for enum_type in parser_state.enum_to_ids_dict:
				ids = parser_state.enum_to_ids_dict[enum_type]
				if enum_name in ids:
					match = True
					break
			if not match:
				print parser_state.enum_to_ids_dict
				print enum_name, "doesn't look like an ENUM constant?"
				sys.exit(0)
			
			return enum_name
		
	else:
		#print wire_name, "IS NOT CONSTANT"
		return "write_pipe." + WIRE_TO_VHDL_NAME(wire_name, Logic)	
	
	
def WIRE_TO_VHDL_NAME(wire_name, Logic):
	leaf_name = C_TO_LOGIC.LEAF_NAME(wire_name)
	
	#print "leaf_name",leaf_name
	rv = leaf_name.replace(C_TO_LOGIC.SUBMODULE_MARKER,"_").replace("_*","_STAR").replace("[*]","_STAR").replace(".","_").replace("[","_").replace("]","").replace(C_TO_LOGIC.REF_TOK_DELIM,"_REF_")
	#print rv
	return rv

	

def GET_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic):
	# Use logic to write vhdl
	timing_params = TimingParamsLookupTable[inst_name]
	text = ""
	# Drive input ports
	text += "			-- Inputs" + "\n"
	for input_port in submodule_logic.inputs:
		input_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + input_port
		text += "			" + WIRE_TO_VHDL_NAME(input_port_wire, logic) + " <= " + GET_WRITE_PIPE_WIRE_VHDL(input_port_wire, logic, parser_state) + ";\n"

	# Only do output connection if zero clk 
	if submodule_latency_from_container_logic == 0:
		text += "			-- Outputs" + "\n"
		for output_port in submodule_logic.outputs:
			output_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + output_port
			text +=  "			" + GET_WRITE_PIPE_WIRE_VHDL(output_port_wire, logic, parser_state) + " := " + WIRE_TO_VHDL_NAME(output_port_wire, logic) + ";\n"
		
	return text
	
	
def GET_TOP_NAME(inst_name, Logic, TimingParamsLookupTable, parser_state):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	timing_params = TimingParamsLookupTable[inst_name]
	return C_TO_LOGIC.LEAF_NAME(inst_name, do_submodule_split=True).replace(C_TO_LOGIC.REF_TOK_DELIM,"_REF_") + "_" +  str(timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)) + "CLK" + timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state) + "_top"
	
# FUCK? Really need to pull latency calculation out of pipeline map and file names and wtf help
def GET_ENTITY_NAME(inst_name, Logic, TimingParamsLookupTable, parser_state, est_total_latency=None):
	# Sanity check?
	if Logic.is_vhdl_func:
		print "Why entity for vhdl func?"
		print 0/0
		sys.exit(0)		
	
	timing_params = TimingParamsLookupTable[inst_name]
	latency = est_total_latency
	if latency is None:
		latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
	return Logic.func_name + "_" +  str(latency) + "CLK" + timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)

def C_ARRAY_TYPE_STR_TO_VHDL_TYPE_STR(c_array_type_str):
	# Just replace brackets with _
	# And add array
	c_array_type_str = c_array_type_str.replace("]","")
	vhdl_type = c_array_type_str.replace("[","_")
	# Like fuck it for now, dont think about it
	return vhdl_type
	
def C_TYPE_STR_TO_VHDL_TYPE_STR(c_type_str, parser_state):
	# Check for int types
	if C_TYPE_IS_INT_N(c_type_str):
		# Get bit width
		width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type_str)
		return "signed(" + str(width-1) + " downto 0)"
	elif C_TYPE_IS_UINT_N(c_type_str):
		# Get bit width
		width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type_str)
		return "unsigned(" + str(width-1) + " downto 0)"
	elif c_type_str == C_TO_LOGIC.BOOL_C_TYPE:
		return "unsigned(0 downto 0)"
	elif c_type_str =="float":
		return "std_logic_vector(31 downto 0)"
	elif C_TO_LOGIC.C_TYPE_IS_STRUCT(c_type_str, parser_state):
		# Use same type from C
		return c_type_str
	elif C_TO_LOGIC.C_TYPE_IS_ENUM(c_type_str, parser_state):
		# Use same type from C
		return c_type_str
	elif C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type_str):
		return C_ARRAY_TYPE_STR_TO_VHDL_TYPE_STR(c_type_str)		
	else:
		print "Unknown VHDL type for C type: '" + c_type_str + "'"
		#print 0/0
		sys.exit(0)


def C_TYPE_STR_TO_VHDL_NULL_STR(c_type_str, parser_state):
	# Check for int types
	if C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str) or (c_type_str == C_TO_LOGIC.BOOL_C_TYPE) or (c_type_str =="float"):
		return "(others => '0')"
	elif C_TO_LOGIC.C_TYPE_IS_STRUCT(c_type_str, parser_state):
		# Use same type from C
		return c_type_str + "_NULL"
	elif C_TO_LOGIC.C_TYPE_IS_ENUM(c_type_str, parser_state):
		# Null is always first,left value
		return c_type_str + "'left"
	elif C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type_str):
		elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type_str)
		text = ""
		for dim in dims:
			text += "(others => "
		# Null type
		elem_null = C_TYPE_STR_TO_VHDL_NULL_STR(elem_type, parser_state)
		text += elem_null
		# Close parens
		for dim in dims:
			text += ")"
		return text
	else:
		print "Unknown VHDL null str for C type: '" + c_type_str + "'"
		print 0/0
		sys.exit(0)
