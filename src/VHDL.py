#!/usr/bin/env python
import sys
import os
import copy
import math

import C_TO_LOGIC
import SW_LIB
import RAW_VHDL
import SYN
import VHDL_INSERT
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

def GET_INST_NAME(Logic, use_leaf_name):
	if use_leaf_name:
		return C_TO_LOGIC.LEAF_NAME(Logic.inst_name.replace(C_TO_LOGIC.SUBMODULE_MARKER, "_").replace(".","_").replace("[","_").replace("]","_")).strip("_").replace("__","_") # hacky fo sho
	else:
		# Need to use leaf name
		print "Need to use leaf name"
		sys.exit(0)
		
# VHDL variable name or const expression
def GET_CONST_MASKED_INPUT_WIRE_TEXT(input_wire,submodule_inst_name, parser_state):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	#print "GET_CONST_MASKED_INPUT_WIRE_TEXT input_wire",input_wire
	container_logic = C_TO_LOGIC.GET_CONTAINER_LOGIC_FOR_SUBMODULE_INST(submodule_inst_name, LogicInstLookupTable)
	if (container_logic is None):
		if submodule_inst_name != "main":
			print "(container_logic is None) and not(submodule_inst_name == main)"
			sys.exit(0)		
		else:
			# Regular variable input required
			return C_TO_LOGIC.LEAF_NAME(input_wire,True)
	else:
		# Got container logic
		const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(input_wire, container_logic)
		#print "const_driving_wire",const_driving_wire
		if not(const_driving_wire is None):
			# Get vhdl const expr
			const_id = GET_WRITE_PIPE_WIRE_VHDL(const_driving_wire, container_logic, parser_state)
			type_resolved_const_id = TYPE_RESOLVE_ASSIGNMENT_RHS(const_id, container_logic, const_driving_wire, input_wire, parser_state)
			return type_resolved_const_id
		else:	
			# Regular variable input
			return C_TO_LOGIC.LEAF_NAME(input_wire,True)

def WRITE_VHDL_TOP(Logic, output_directory, parser_state, TimingParamsLookupTable):	
	timing_params = TimingParamsLookupTable[Logic.inst_name]
	filename = GET_TOP_NAME(Logic,TimingParamsLookupTable, parser_state) + ".vhd"
	
	rv = ""
	rv += "library IEEE;" + "\n"
	rv += "use IEEE.STD_LOGIC_1164.ALL;" + "\n"
	rv += "use ieee.numeric_std.all;" + "\n"
	# Include C defined structs
	rv += "use work.c_structs_pkg.all;\n"
	
	rv += "use work." + GET_PACKAGE_NAME(Logic,TimingParamsLookupTable, parser_state) + ".all;" + "\n"
	
	rv += "entity " + GET_INST_NAME(Logic,use_leaf_name=True) + "_top is" + "\n"
	rv += "port(" + "\n"
	rv += "	clk : in std_logic;" + "\n"
	# The inputs of the logic
	for input_name in Logic.inputs:
		# Get type for input
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
		rv += "	" + C_TO_LOGIC.LEAF_NAME(input_name,True) + " : in " + vhdl_type_str + ";" + "\n"
	
	# Output is type of return wire
	vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(Logic.outputs[0],Logic,parser_state)
	rv += "	" + C_TO_LOGIC.LEAF_NAME(Logic.outputs[0],True) + " : out " + vhdl_type_str + "" + "\n"
	
	rv += ");" + "\n"
	rv += "end " + GET_INST_NAME(Logic,use_leaf_name=True) + "_top;" + "\n"

	rv += "architecture arch of " + GET_INST_NAME(Logic,use_leaf_name=True) + "_top is" + "\n"
	
	
	# Main regs nulled out
	rv += "signal " + GET_INST_NAME(Logic,use_leaf_name=True)+ "_registers_r : " + GET_INST_NAME(Logic,use_leaf_name=True) + "_registers_t := " + GET_INST_NAME(Logic,use_leaf_name=True) + "_registers_NULL;\n"
	rv += "\n"

	# The inputs of the logic
	for input_name in Logic.inputs:
		# Get type for input
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
		rv += "signal " + C_TO_LOGIC.LEAF_NAME(input_name,True) + "_input_reg : " + vhdl_type_str + " := " + WIRE_TO_VHDL_NULL_STR(input_name, Logic, parser_state) + ";" + "\n"
		
	rv += "\n"
	
	# Output reg
	output_vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(Logic.outputs[0],Logic,parser_state)
	rv += "signal " + C_TO_LOGIC.LEAF_NAME(Logic.outputs[0],True) + "_output_reg : " + output_vhdl_type_str + ";" + "\n"

	rv += "begin" + "\n"
	rv += "	" + "process(clk) is" + "\n"
	rv += "	" + "	" + "variable " + C_TO_LOGIC.RETURN_WIRE_NAME + "_output : " + output_vhdl_type_str + ";" + "\n"
	rv += "	" + "	" + "variable " + GET_INST_NAME(Logic,use_leaf_name=True) + "_registers : " + GET_INST_NAME(Logic,use_leaf_name=True) + "_registers_t;" + "\n"
	rv += "	" + "begin" + "\n"
	rv += "	" + "	" + "if rising_edge(clk) then" + "\n"
	
	# Register inputs
	for input_name in Logic.inputs:
		# Get type for input
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
		rv += "	" + "	" + "	" + C_TO_LOGIC.LEAF_NAME(input_name,True) + "_input_reg <= " + GET_CONST_MASKED_INPUT_WIRE_TEXT(input_name,Logic.inst_name, parser_state) + ";" + "\n"
	
	# Pipeline register read as variable		
	rv += "	" + "	" + "	" + GET_INST_NAME(Logic,use_leaf_name=True) + "_registers := " + GET_INST_NAME(Logic,use_leaf_name=True) + "_registers_r;" + "\n"
	
	# Single procedure call with multiple inputs
	rv += "	" + "	" + "	" + GET_INST_NAME(Logic,use_leaf_name=True) + "("
	for input_name in Logic.inputs:
		rv += C_TO_LOGIC.LEAF_NAME(input_name,True) + "_input_reg, " 
	rv += GET_INST_NAME(Logic,use_leaf_name=True) + "_registers, " + C_TO_LOGIC.RETURN_WIRE_NAME + "_output);" + "\n"
	
	# Pipeline register write to reg	
	rv += "	" + "	" + "	" +  GET_INST_NAME(Logic,use_leaf_name=True) + "_registers_r <= " + GET_INST_NAME(Logic,use_leaf_name=True) + "_registers" + ";\n"
	
	# Output reg	
	rv += "	" + "	" + "	" + C_TO_LOGIC.LEAF_NAME(Logic.outputs[0],True) + "_output_reg <= " + C_TO_LOGIC.RETURN_WIRE_NAME + "_output;" + "\n"
	
	rv += "	" + "	" + "end if;" + "\n"		
	rv += "	" + "end process;" + "\n"
		
	rv += "	" + C_TO_LOGIC.LEAF_NAME(Logic.outputs[0],True) +" <= " + C_TO_LOGIC.LEAF_NAME(Logic.outputs[0],True) + "_output_reg;" + "\n"
	rv += "end arch;" + "\n"
	
	if not os.path.exists(output_directory):
		os.mkdirs(output_directory)
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
		  logic_func_name.startswith(VHDL_INSERT.HDL_INSERT) or # HDl text insert, so yeah is raw hdl
		  logic_func_name.startswith(C_TO_LOGIC.STRUCT_RD_FUNC_NAME_PREFIX) or # Structref is raw vhdl
		( logic_func_name.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.UNARY_OP_NOT_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GT_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
	    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_PLUS_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MINUS_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_EQ_NAME)  ) or #and C_TYPES_ARE_INTEGERS(input_c_types)
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_AND_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_OR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_XOR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LTE_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GTE_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
		( logic_func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME)	)
		):# or		
		return True
	
	# IS NOT RAW VHDL
	if (  logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_DIV_NAME)                                          or
		  logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MULT_NAME)                                         or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_SL_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or # ASSUME FOR NOW
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_SR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or # ASSUME FOR NOW
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GT_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GTE_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_PLUS_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
		( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MINUS_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float"))
		):
		return False
	else:
		print "Is logic_func_name",logic_func_name,"with input types",input_c_types,"raw VHDL or not?"
		sys.exit(0)
	
	
def GET_PROCEDURE_PACKAGE_STAGES_TEXT(logic, parser_state, TimingParamsLookupTable):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	
	timing_params = TimingParamsLookupTable[logic.inst_name]
	package_file_text = ""
	# Raw hdl logic is static in the stages code here but coded as generic
	if len(logic.submodule_instances) <= 0 and logic.func_name != "main":
		package_file_text = RAW_VHDL.GET_RAW_HDL_PROCEDURE_PACKAGE_STAGES_TEXT(logic, parser_state, timing_params)
	else:
		package_file_text = GET_C_PROCEDURE_PACKAGE_STAGES_TEXT(logic, parser_state, TimingParamsLookupTable)
	
	return package_file_text
	
'''	
def GET_PROCEDURE_PACKAGE_PER_STAGE_TEXT(logic, parser_state, TimingParamsLookupTable):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	timing_params = TimingParamsLookupTable[logic.inst_name]
	per_stage_text = None
	# C built in logic is static in the stages code here but coded as generic
	if len(logic.submodule_instances) <= 0:
		per_stage_text = RAW_VHDL.GET_RAW_HDL_PROCEDURE_PACKAGE_PER_STAGE_TEXT(logic, LogicInstLookupTable, timing_params)
	else:
		per_stage_text = GET_C_PROCEDURE_PACKAGE_PER_STAGE_TEXT(logic, parser_state, TimingParamsLookupTable)
	
	return per_stage_text
'''
	
def WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(parser_state):
	
	text = ""
	
	text += '''
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
-- All structs defined in C code

package c_structs_pkg is
'''
	# Enum types
	for enum_name in parser_state.enum_to_ids_dict.keys():		
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


	# Hacky resolve struct dependencies
	done = False
	types_written = []
	while not done:
		done = True
		for struct_name in reversed(parser_state.struct_to_field_type_dict.keys()):
			# When to stop?
			if struct_name in types_written:
				continue
			done = False
				
			# Resolve dependencies:
			# Check if all the types for this struct are written or not structs
			field_type_dict = parser_state.struct_to_field_type_dict[struct_name]
			field_types_written_or_not_struct = True
			for field in field_type_dict:
				c_type = field_type_dict[field]
				if not( (c_type in types_written) or (c_type not in parser_state.struct_to_field_type_dict)  ):
					field_types_written_or_not_struct = False
					break
			if not field_types_written_or_not_struct:
				continue
					
			
			# Type
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
			types_written.append(struct_name)

	text += '''
end c_structs_pkg;
'''
	
	if not os.path.exists(SYN.SYN_OUTPUT_DIRECTORY):
		os.makedirs(SYN.SYN_OUTPUT_DIRECTORY)	
	
	
	path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "c_structs_pkg" + VHDL_PKG_EXT
	
	f=open(path,"w")
	f.write(text)
	f.close()
	
# Return package file name
def GENERATE_PACKAGE_FILE(logic, parser_state, TimingParamsLookupTable, timing_params, dest_dir):	
	# If this is called for HDL inser then fail
	if logic.func_name.startswith(VHDL_INSERT.HDL_INSERT):
		print "Dont try to generate package file for HDL INSERT func",logic.func_name
		print 0/0
		return None
	
	package_filename = GET_PACKAGE_FILENAME(logic,TimingParamsLookupTable, parser_state)
	package_name = GET_PACKAGE_NAME(logic, TimingParamsLookupTable, parser_state)
	package_file_name = dest_dir + "/" + package_filename
	
	
	package_file_text = ""
	package_file_text = package_file_text + """
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;\n"""

	# Include C defined structs
	package_file_text += "use work.c_structs_pkg.all;\n"
	
	# Need an include for each submodule type
	included_package_names = []
	package_file_text = package_file_text + "-- Includes\n"
	package_file_text = package_file_text + "-- An include for each submodule\n"
	#print "logic.inst_name",logic.inst_name
	#print "logic.submodule_instances",logic.submodule_instances
	#print "parser_state.LogicInstLookupTable",parser_state.LogicInstLookupTable
	#print "^^^^^^^^^^^^^^^^^^^^^^^"
	for submodule_inst_name in logic.submodule_instances:
		if submodule_inst_name in parser_state.LogicInstLookupTable:
			#print "submodule_inst_name in parser_state.LogicInstLookupTable",submodule_inst_name ,(submodule_inst_name in parser_state.LogicInstLookupTable)
			submodule_logic = parser_state.LogicInstLookupTable[submodule_inst_name]
			
			# Vhdl inserts dont get package
			if submodule_logic.func_name.startswith(VHDL_INSERT.HDL_INSERT):
				continue		
			
			submodule_timing_params = TimingParamsLookupTable[submodule_logic.inst_name]
			submodule_package_name = GET_PACKAGE_NAME(submodule_logic,TimingParamsLookupTable,parser_state)
			#print "submodule_package_name",submodule_package_name
			if submodule_package_name not in included_package_names:
				package_file_text += "use work." +submodule_package_name+".all;\n"
				included_package_names.append(submodule_package_name)
		else:
			print "Package for", submodule_inst_name, "?"
			sys.exit(0)
	
	package_file_text += "\n"
	package_file_text += "package " + package_name + " is\n"
	package_file_text += "-- Declarations\n"
	
	# Declare total latency for logic
	package_file_text += "constant " + GET_INST_NAME(logic,use_leaf_name=True) + "_LATENCY : integer := " + str(timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)) + ";\n"
	
	

	# Type for wires/variables
	package_file_text += "\n"
	package_file_text += "-- One struct to represent this modules variables\n"
	package_file_text += "type " + GET_INST_NAME(logic,use_leaf_name=True) + "_variables_t is record\n"
	package_file_text += "	-- All of the wires in function\n"
	# Raw HDL functions are done differently
	if len(logic.submodule_instances) <= 0 and logic.func_name != "main":
		package_file_text += RAW_VHDL.GET_RAW_HDL_WIRES_DECL_TEXT(logic, parser_state, timing_params)
	else:
		# Not c built in
		# First get wires from declarations and assignments logic itself
		# sort wires so easy to find bugs?
		text_additions = []
		for wire_name in logic.wire_to_c_type:
			# Skip constants here
			if C_TO_LOGIC.WIRE_IS_CONSTANT(wire_name,logic.inst_name):
				continue
			'''
			# Skip org var names that arent inputs or outputs for logic with submodules (C code)
			if len(logic.submodule_instances) > 0:
				if not(wire_name in logic.inputs) and not(wire_name in logic.outputs) and (wire_name in logic.variable_names):
					continue
			'''
			# Skip globals too
			if wire_name in logic.global_wires:
				continue
				
			#print "wire_name", wire_name
			vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(wire_name, logic, parser_state)
			#print "wire_name",wire_name
			write_pipe_wire_var_vhdl = WIRE_TO_VHDL_NAME(wire_name, logic)
			#print "write_pipe_wire_var_vhdl",write_pipe_wire_var_vhdl
			text_additions.append("	" + write_pipe_wire_var_vhdl + " : " + vhdl_type_str + ";\n")
		text_additions.sort()
		for text_addition in text_additions:
			package_file_text += text_addition
			
	package_file_text += "end record;\n"
	
	
	
	
	package_file_text += '''
-- Type for this modules register pipeline
type ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_register_pipeline_t is array(0 to ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_LATENCY) of ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_variables_t;
	'''
	
	# If raw hdl then no submodules
	if len(logic.submodule_instances) > 0:
		# Submodule wire names are local wire name, type is global wire name
		package_file_text += '''
-- Type holding all submodule registers
type ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_submodule_registers_t is record'''
		# Each func instance gets records
		package_file_text += '''
	-- Each function instance gets registers\n'''
		for instance_name in logic.submodule_instances:
			submodule_logic_name = logic.submodule_instances[instance_name]
			submodule_logic = parser_state.LogicInstLookupTable[instance_name]
			# No regs for vhdl inserts
			if submodule_logic.func_name.startswith(VHDL_INSERT.HDL_INSERT):
				continue
			# For now strip off hierarchy levels from instance name
			new_inst_name = C_TO_LOGIC.LEAF_NAME(instance_name, do_submodule_split=True)
			package_file_text += "	" + GET_SUBMODULE_REGS_WRITE_PIPE_VAR(instance_name) + " : " + GET_INST_NAME(submodule_logic,True) + "_registers_t;\n"

		package_file_text += "end record;\n"
		
	# GLOBALS
	if len(logic.global_wires) > 0:
		package_file_text += '''
-- Type holding all global registers
type ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_global_registers_t is record'''
		# Each func instance gets records
		package_file_text += '''
	-- Global vars\n'''
	
		## Get just global vars from global wires
		#global_vars = []
		#for global_wire in logic.global_wires:
		#	orig_var_name = ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(global_wire)
		#	global_vars.append(orig_var_name)
		
		for global_wire in logic.global_wires:
			vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(global_wire, logic, parser_state)
			#print "wire_name",wire_name
			vhdl_name = WIRE_TO_VHDL_NAME(global_wire, logic)
			package_file_text += "	" + vhdl_name + " : " + vhdl_type_str + ";\n"
		package_file_text += "end record;\n"
		
		
	# ALL REGISTERS
	package_file_text += '''	
-- Type holding all registers for this function
type ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_registers_t is record
	self : ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_register_pipeline_t;'''
	
	# Submodules if not raw hdl
	if len(logic.submodule_instances) > 0:
		package_file_text += '''
	submodules : ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_submodule_registers_t;'''
	
	# Global regs
	if len(logic.global_wires) > 0:
		package_file_text += '''
	global_regs : ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_global_registers_t;'''
	
	package_file_text += '''	
end record;
'''

	# Function to null out globals
	package_file_text += "\n-- Function to null out just global regs\n"
	package_file_text += "function " + GET_INST_NAME(logic,use_leaf_name=True) + "_registers_NULL return " + GET_INST_NAME(logic,use_leaf_name=True)+ "_registers_t;\n"
	

	# Procedure decl
	procedure_decl_text = "\n"
	procedure_decl_text += "-- Function decl\n"
	procedure_decl_text += "procedure " + GET_INST_NAME(logic,use_leaf_name=True) + "(\n"
	procedure_decl_text += "	-- Inputs\n"
	for input_wire in logic.inputs:
		vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_wire, logic, parser_state)
		#procedure_decl_text += "	" + C_TO_LOGIC.LEAF_NAME(input_wire, True) + " : in " + vhdl_type_str + ";\n"
		procedure_decl_text += "	" + WIRE_TO_VHDL_NAME(input_wire, logic) + " : in " + vhdl_type_str + ";\n"
		
	procedure_decl_text += "	-- Function registers\n"
	procedure_decl_text += "	" + "registers : inout " + GET_INST_NAME(logic,use_leaf_name=True) + "_registers_t;\n"
	procedure_decl_text += "	-- Return wire\n"
	procedure_decl_text += "	" + C_TO_LOGIC.RETURN_WIRE_NAME + " : out " + WIRE_TO_VHDL_TYPE_STR(logic.outputs[0], logic, parser_state) + "\n"  # ASSUME ONE OUTPUT FOR NOW... well established by now I think
	procedure_decl_text += ");\n"
	package_file_text += procedure_decl_text
	package_file_text += "end " + package_name + ";\n"
	package_file_text += "\n"
	package_file_text += "package body " + package_name + " is\n"
	package_file_text += "\n"
	
	
	# Function to null out globals
	package_file_text += "\n-- Function to null out just global regs\n"
	package_file_text += "function " + GET_INST_NAME(logic,use_leaf_name=True) + "_registers_NULL return " + GET_INST_NAME(logic,use_leaf_name=True)+ "_registers_t is\n"
	package_file_text += "	variable rv : " + GET_INST_NAME(logic,use_leaf_name=True) + '''_registers_t;
begin
'''
	# Do each global var
	for global_wire in logic.global_wires:
		package_file_text += "	rv.global_regs." + WIRE_TO_VHDL_NAME(global_wire, logic) + " := " + WIRE_TO_VHDL_NULL_STR(global_wire, logic, parser_state) + ";\n"
	
	# Null out each submodule
	for submodule_inst in logic.submodule_instances:
		submodule_logic = parser_state.LogicInstLookupTable[submodule_inst]
		if len(submodule_logic.submodule_instances) > 0:
			package_file_text += "	rv.submodules." + GET_SUBMODULE_REGS_WRITE_PIPE_VAR(submodule_inst) + " := " + GET_INST_NAME(submodule_logic,use_leaf_name=True) + "_registers_NULL;\n"
		
	package_file_text += '''
	return rv;
end function;\n
'''
	
	# Package body has procedure decl as start
	package_file_text += procedure_decl_text.strip(";\n")
	package_file_text += "is \n"
	
	# READ PIPE
	package_file_text += "	-- Read and write variables to do register transfers per clock\n"
	package_file_text += "	-- from the previous to next stage\n"
	package_file_text += "	" + "variable read_pipe : " + GET_INST_NAME(logic,use_leaf_name=True) + "_variables_t;\n"
	package_file_text += "	" + "variable write_pipe : " + GET_INST_NAME(logic,use_leaf_name=True) + "_variables_t;\n"
	
	
	# Self regs
	package_file_text += '''
	-- This modules self pipeline registers read once per clock
	variable read_self_regs : ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_register_pipeline_t;
	variable write_self_regs : ''' + GET_INST_NAME(logic,use_leaf_name=True) + '''_register_pipeline_t;
'''	

	# Submodules if not raw hdl
	if len(logic.submodule_instances) > 0:
		package_file_text += "	" + "-- Submodule registers read once per clock\n"
		package_file_text += "	" + "variable read_submodule_regs : " + GET_INST_NAME(logic,use_leaf_name=True) + "_submodule_registers_t;\n"
		package_file_text += "	" + "variable write_submodule_regs : " + GET_INST_NAME(logic,use_leaf_name=True) + "_submodule_registers_t;\n"
	
	# Global regs
	if len(logic.global_wires) > 0:
		package_file_text += "	" + "-- Global registers read once per clock\n"
		package_file_text += "	" + "variable read_global_regs : " + GET_INST_NAME(logic,use_leaf_name=True) + "_global_registers_t;\n"
		package_file_text += "	" + "variable write_global_regs : " + GET_INST_NAME(logic,use_leaf_name=True) + "_global_registers_t;\n"
	
	
	# BEGIN BEGIN BEGIN
	package_file_text += "begin\n"
	
	# Self regs
	package_file_text += '''
	-- SELF REGS
	-- Default read self regs once per clock
	read_self_regs := registers.self;
	-- Default write contents of self regs
	write_self_regs := read_self_regs;'''
	
	# Submodules if not raw hdl
	if len(logic.submodule_instances) > 0:
		package_file_text += '''
	-- SUBMODULE REGS
	-- Default read submodule regs once per clock
	read_submodule_regs := registers.submodules;
	-- Default write contents of submodule regs
	write_submodule_regs := read_submodule_regs;'''
	
	# Globals
	if len(logic.global_wires) > 0:
		package_file_text += '''
	-- GLOBAL REGS
	-- Default read global regs once per clock
	read_global_regs := registers.global_regs;
	-- Default write contents of global regs
	write_global_regs := read_global_regs;
'''
		
	package_file_text += "	-- Loop to construct simultaneous register transfers for each of the pipeline stages\n"
	package_file_text += "	-- LATENCY=0 is combinational logic\n"
	package_file_text += "	" + "for STAGE in 0 to " + GET_INST_NAME(logic,use_leaf_name=True) + "_LATENCY loop\n"
	package_file_text += "	" + "	" + "-- Input to first stage are inputs to function\n"
	package_file_text += "	" + "	" + "if STAGE=0 then\n"
	package_file_text += "	" + "	" + "	" + "-- Mux in inputs\n"
	for input_wire in logic.inputs:
		#package_file_text += "	" + "	" + "	" + "read_pipe." + C_TO_LOGIC.LEAF_NAME(input_wire,True) + " := " + GET_CONST_MASKED_INPUT_WIRE_TEXT(input_wire,logic.inst_name, parser_state.LogicInstLookupTable) + ";\n"
		#package_file_text += "	" + "	" + "	" + "read_pipe." + C_TO_LOGIC.LEAF_NAME(input_wire,True) + " := " + C_TO_LOGIC.LEAF_NAME(input_wire,True) + ";\n"
		package_file_text += "	" + "	" + "	" + "read_pipe." + WIRE_TO_VHDL_NAME(input_wire, logic) + " := " + WIRE_TO_VHDL_NAME(input_wire, logic) + ";\n"
		
	package_file_text += "	" + "	" + "else\n"
	package_file_text += "	" + "	" + "	" + "-- Default read from previous stage\n"
	package_file_text += "	" + "	" + "	" + "read_pipe := " + "read_self_regs(STAGE-1);\n"
	#package_file_text += "	" + "	" + "	" + "read_pipe := " + "write_self_regs(STAGE-1);\n"
	package_file_text += "	" + "	" + "end if;\n"
	package_file_text += "	" + "	" + "-- Default write contents of previous stage\n"
	package_file_text += "	" + "	" + "write_pipe := read_pipe;\n"
	package_file_text += "\n"
	
	# C built in logic is static in the stages code here but coded as generic
	package_file_text += GET_PROCEDURE_PACKAGE_STAGES_TEXT(logic, parser_state, TimingParamsLookupTable)
		
	package_file_text += "	" + "	" + "-- Write to stage reg\n"
	package_file_text += "	" + "	" + "write_self_regs(STAGE) := write_pipe;\n"
	package_file_text += "	" + "end loop;\n"
	package_file_text += "\n"
	package_file_text += "	" + "-- Last stage of pipeline return wire to function return wire\n"
	# Need conversion to return wire?
	# BAH DONT DO THAT NOW	
	package_file_text += "	" + C_TO_LOGIC.RETURN_WIRE_NAME + " := " + "write_self_regs(" + GET_INST_NAME(logic,use_leaf_name=True) + "_LATENCY)." + C_TO_LOGIC.RETURN_WIRE_NAME + ";\n"
	# Regs
	package_file_text += "	" + "-- Per clock write back registers\n"
	package_file_text += "	" + "registers.self := write_self_regs;\n"
	# Submodules if not raw hdl
	if len(logic.submodule_instances) > 0:
		package_file_text += "	" + "registers.submodules := write_submodule_regs;\n"
	# Globals
	if len(logic.global_wires) > 0:
		package_file_text += "	" + "registers.global_regs := write_global_regs;\n"
	package_file_text += "end procedure;\n"
	package_file_text += "\n"
	package_file_text += "end " + package_name + ";\n"
	
	#print "Writing package:",package_file_name
	
	f=open(package_file_name,"w")
	f.write(package_file_text)
	f.close()
	
	#print package_file_name
	#print ""
	#print package_file_text
	#sys.exit(0)
	
	return package_file_name
	
	'''
def GET_SUBMODULE_INST_NAME_FROM_PROCEDURE_NAME(procedure_name, LogicInstLookupTable):
	# Procedure name is made via
	# 	procedure_name = GET_INST_NAME(submodule_logic, use_leaf_name=True)
	most_matching_inst = None
	for inst_name in LogicInstLookupTable:
		inst_logic = LogicInstLookupTable[inst_name]
		inst_procedure_name = GET_INST_NAME(inst_logic, use_leaf_name=True)
		if inst_procedure_name == procedure_name:
			if most_matching_inst is None:
				most_matching_inst = inst_name
			else:
				print "Two matching instances for procedure name"
				print "procedure_name",procedure_name
				print "most_matchign_inst",most_matchign_inst
				print "other matching inst_name",inst_name
				sys.exit(0)
				
	return most_matching_inst
	'''

			
# Returns dict[stage_num]=stage_text
def GET_C_PROCEDURE_PACKAGE_PER_STAGE_TEXT(logic, parser_state, TimingParamsLookupTable):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	# Get the per stage texts and combine
	per_stage_texts = GET_C_PROCEDURE_PACKAGE_PER_STAGE_TEXTS(logic, parser_state, TimingParamsLookupTable)
	
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

	'''
def GET_PER_STAGE_LOCAL_TIME_ORDER_SUBMODULE_INSTANCE_NAMES(logic, parser_state, LogicInst2TimingParams):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	timing_params = LogicInst2TimingParams[logic.inst_name]
	per_stage_text = GET_C_PROCEDURE_PACKAGE_PER_STAGE_TEXT(logic, parser_state, LogicInst2TimingParams)
	per_stage_time_order = dict()
	for stage_num in per_stage_text:
		per_stage_time_order[stage_num] = []
		stage_time_order = []
		text = per_stage_text[stage_num]
		# Loop over text and find submodule leaf names
		for line in text.split("\n"):
			if not(":=" in line) and  ("(" in line) and (")" in line):
				procedure_name = line.split("(")[0].strip()
				submodule_inst = GET_SUBMODULE_INST_NAME_FROM_PROCEDURE_NAME(procedure_name, LogicInstLookupTable)
				submodule_logic = LogicInstLookupTable[submodule_inst]
				per_stage_time_order[stage_num].append(submodule_inst)
					
	return per_stage_time_order
	'''


	
def GET_C_PROCEDURE_PACKAGE_PER_STAGE_TEXTS(logic, parser_state, TimingParamsLookupTable):
	#timing_params = TimingParamsLookupTable[logic.inst_name]
	pipeline_map = SYN.GET_PIPELINE_MAP(logic, parser_state, TimingParamsLookupTable)
	return pipeline_map.per_stage_texts 

def GET_C_PROCEDURE_PACKAGE_STAGES_TEXT(logic, parser_state, TimingParamsLookupTable):
	# Get text per stage
	per_stage_text = GET_C_PROCEDURE_PACKAGE_PER_STAGE_TEXT(logic, parser_state, TimingParamsLookupTable)
	
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
				print "Inputs not all same width for C int?", logic.inst_name
				print logic.wire_to_c_type
				print "rv_width, width", rv_width, width
				print 0/0
				sys.exit(0)
	return rv_width
	
def GET_OUTPUT_C_INT_BIT_WIDTH(logic):
	rv_width = None
	for out in logic.outputs:
		c_type = logic.wire_to_c_type[out]
		width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
		if rv_width is None:
			rv_width = width
		else:
			if rv_width != width:
				print "Outputs not all same width for C int?", logic.inst_name
				print logic.wire_to_c_type
				print "rv_width, width", rv_width, width
				sys.exit(0)
	return rv_width



	
def GET_RHS(driving_wire_to_handle, logic, parser_state, TimingParamsLookupTable, timing_params, stage_ordered_submodule_list, stage):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	RHS = ""
	# SUBMODULE PORT?
	if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(driving_wire_to_handle, logic):
		# Get submodule name
		#print "driving_wire_to_handle",driving_wire_to_handle
		toks=driving_wire_to_handle.split(C_TO_LOGIC.SUBMODULE_MARKER)
		#driving_submodule_name = C_TO_LOGIC.SUBMODULE_MARKER.join(toks[0:len(toks)-2])
		driving_submodule_name = C_TO_LOGIC.SUBMODULE_MARKER.join(toks[0:len(toks)-1])
		driving_submodule_logic = LogicInstLookupTable[driving_submodule_name]
		#print "driving_submodule_name",driving_submodule_name
		#print "vhdl_tLogicInstLookupTableiming_params._submodule_latencies",timing_params._submodule_latencies
		
		driving_submodule_latency = timing_params.GET_SUBMODULE_LATENCY(driving_submodule_name, parser_state, TimingParamsLookupTable)
		
		
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
			# Different, previous stage, use submodule regs approach if latency > 0 
			if driving_submodule_latency > 0:
				port_name = driving_wire_to_handle.replace(driving_submodule_name+C_TO_LOGIC.SUBMODULE_MARKER,"")
				write_pipe_submodule_regs_var = GET_SUBMODULE_REGS_WRITE_PIPE_VAR(driving_submodule_name)
				# Pretty sure we want write submodule regs?
				#RHS = "read_submodule_regs." + write_pipe_submodule_regs_var + ".self(" + GET_INST_NAME(driving_submodule_logic, True) + "_LATENCY)." + port_name
				RHS = "write_submodule_regs." + write_pipe_submodule_regs_var + ".self(" + GET_INST_NAME(driving_submodule_logic, True) + "_LATENCY)." + port_name
			else:
				RHS = GET_WRITE_PIPE_WIRE_VHDL(driving_wire_to_handle, logic, parser_state)
	
		
	# GLOBAL?
	elif driving_wire_to_handle in logic.global_wires:
		#print "DRIVING WIRE GLOBAL"						
		# Globals come from input regs to this procedure
		RHS = "write_global_regs." + WIRE_TO_VHDL_NAME(driving_wire_to_handle, logic)
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
		# Globals come from input regs to this procedure
		LHS = "write_global_regs." + WIRE_TO_VHDL_NAME(driven_wire_to_handle, logic)
	else:
		# Otherwise use regular wire connection
		LHS = GET_WRITE_PIPE_WIRE_VHDL(driven_wire_to_handle, logic, parser_state)
		
	return LHS

def GET_WRITE_PIPE_WIRE_VHDL(wire_name, Logic, parser_state):
	inst_name = ""
	if Logic.inst_name is not None:
		inst_name = Logic.inst_name
	
	# If a constant 
	if C_TO_LOGIC.WIRE_IS_CONSTANT(wire_name, inst_name):
		inst_name = ""
		if Logic.inst_name is not None:
			inst_name = Logic.inst_name
		local_name = wire_name.replace(inst_name+C_TO_LOGIC.SUBMODULE_MARKER,"")
		
		# Ge tlast submodule tok
		toks = local_name.split(C_TO_LOGIC.SUBMODULE_MARKER)
		last_tok = toks[len(toks)-1]
		local_name = last_tok	
		
		# What type of const
		# Strip off CONST_
		stripped_wire_name = local_name
		if local_name.startswith(C_TO_LOGIC.CONST_PREFIX):
			stripped_wire_name = local_name[len(C_TO_LOGIC.CONST_PREFIX):]
		#print "stripped_wire_name",stripped_wire_name
		# Split on under
		toks = stripped_wire_name.split("_")
		
		ami_digit = toks[0]
		ami_digit_no_neg = ami_digit.strip("-")
		if ami_digit.isdigit():
			# Check for unsigned digit constant
			# unsigned 0 downto 0 needs special cast?
			c_type =  Logic.wire_to_c_type[wire_name]
			width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
			return "to_unsigned(" + ami_digit + ", " + str(width) + ")"
		elif ami_digit_no_neg.isdigit():
			# Check for neg signed constant
			c_type =  Logic.wire_to_c_type[wire_name]
			width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
			return "to_signed(" + ami_digit + ", " + str(width) + ")"
		#elif Logic.wire_to_c_type[wire_name] in 
		#else:
		#	print "What to do with this const wire const?",wire_name,
		#	print toks
		#	sys.exit(0)
		else:
			# ASSUMING ENUM AAUAUGHGHGHG????
			#print "wire_name",wire_name
			#print "local_name",local_name
			#print "stripped_wire_name",stripped_wire_name
			return stripped_wire_name.split("$")[0]
		
	else:
		#print wire_name, "IS NOT CONSTANT"
		return "write_pipe." + WIRE_TO_VHDL_NAME(wire_name, Logic)	
	
	
def WIRE_TO_VHDL_NAME(wire_name, Logic):
	if C_TO_LOGIC.SUBMODULE_MARKER in wire_name:
		just_local_wire_name = wire_name.replace(Logic.inst_name+C_TO_LOGIC.SUBMODULE_MARKER,"")
		leaf_name = C_TO_LOGIC.LEAF_NAME(just_local_wire_name)	
		new_wire_name = leaf_name.replace(C_TO_LOGIC.SUBMODULE_MARKER,"_").replace(".","DOT").replace("[","_").replace("]","")
		return new_wire_name
	else:
		return C_TO_LOGIC.LEAF_NAME(wire_name)


def GET_SUBMODULE_REGS_WRITE_PIPE_VAR(submodule_inst_name):
	new_inst_name = C_TO_LOGIC.LEAF_NAME(submodule_inst_name, do_submodule_split=True)
	new_inst_name = new_inst_name.replace(".","_").replace("[","_").replace("]","")
	return new_inst_name + "_registers"


		

def GET_PROCEDURE_CALL_TEXT(submodule_logic, submodule_inst_name, logic, timing_params, parser_state):
	# Use logic to write vhdl
	procedure_name = GET_INST_NAME(submodule_logic, use_leaf_name=True)
	text = procedure_name + "("
	for input_port_name in submodule_logic.inputs:
		#print "submodule_logic.name",submodule_logic.name
		#print "input: " ,input_wire
		# Look up what drives this input
		submodule_input_wire = input_port_name # submodule_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + input_port_name
		#driving_wire = GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(logic,submodule_inst_name,input_wire)
		# Regular pipe dot var 
		write_pipe_dot_var = GET_WRITE_PIPE_WIRE_VHDL(submodule_input_wire, logic, parser_state)
		text += write_pipe_dot_var+ ", "			
		
	# Then list registers for this instance
	text += "write_submodule_regs." + GET_SUBMODULE_REGS_WRITE_PIPE_VAR(submodule_inst_name) + ", "
	

	# list outputs
	for output_wire in submodule_logic.outputs:
		# Look up what is driven by this output
		# Construct the name of this wire in the original logic
		out_port_wire = output_wire # submodule_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + output_wire
		#if not(out_port_wire in logic.wire_drives):
		#	text += "open,"
		#else:
		#driven_wires = logic.wire_drives[out_port_wire]
		text += GET_WRITE_PIPE_WIRE_VHDL(out_port_wire, logic, parser_state) + ","
			
	
	return text.strip(", ") + ");\n"
	
def GET_PACKAGE_NAME(logic,TimingParamsLookupTable, parser_state):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	timing_params = TimingParamsLookupTable[logic.inst_name]
	package_name = GET_INST_NAME(logic, use_leaf_name=True) + "_" +  str(timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)) + "CLK" + timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state) + "_pkg"
	return package_name
	
# File name is less info since is in directory hierarchy
def GET_PACKAGE_FILENAME(logic,TimingParamsLookupTable, parser_state):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	timing_params = TimingParamsLookupTable[logic.inst_name]
	short_inst_name = C_TO_LOGIC.LEAF_NAME(logic.inst_name, do_submodule_split=True)
	#short_inst_name = leaf.replace(C_TO_LOGIC.SUBMODULE_MARKER, "_").replace(".","_").replace("[","_").replace("]","_").strip("_").replace("__","_") # rerrrreeaalllu hacky fo sho
	package_filename = short_inst_name + "_" +  str(timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)) + "CLK" + timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state) + "_pkg.pkg.vhd"
	return package_filename
	
def GET_TOP_NAME(Logic, TimingParamsLookupTable, parser_state):
	LogicInstLookupTable = parser_state.LogicInstLookupTable
	timing_params = TimingParamsLookupTable[Logic.inst_name]
	return C_TO_LOGIC.LEAF_NAME(Logic.inst_name, do_submodule_split=True) + "_" +  str(timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)) + "CLK" + timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
	
def C_TYPE_IS_STRUCT(c_type_str, parser_state):
	if parser_state is None:
		print 0/0
	return c_type_str in parser_state.struct_to_field_type_dict
	
def C_TYPE_IS_ENUM(c_type_str, parser_state):
	if parser_state is None:
		print 0/0
	return c_type_str in parser_state.enum_to_ids_dict
	
	
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
	elif C_TYPE_IS_STRUCT(c_type_str, parser_state):
		# Use same type from C
		return c_type_str
	elif C_TYPE_IS_ENUM(c_type_str, parser_state):
		# Use same type from C
		return c_type_str
	else:
		print "Unknown VHDL type for C type: '" + c_type_str + "'"
		#print 0/0
		sys.exit(0)


def C_TYPE_STR_TO_VHDL_NULL_STR(c_type_str, parser_state):
	# Check for int types
	if C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str) or (c_type_str == C_TO_LOGIC.BOOL_C_TYPE) or (c_type_str =="float"):
		return "(others => '0')"
	elif C_TYPE_IS_STRUCT(c_type_str, parser_state):
		# Use same type from C
		return c_type_str + "_NULL"
	elif C_TYPE_IS_ENUM(c_type_str, parser_state):
		# Null is always first,left value
		return c_type_str + "'left"
	else:
		print "Unknown VHDL null str for C type: '" + c_type_str + "'"
		print 0/0
		sys.exit(0)
