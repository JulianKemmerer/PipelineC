#!/usr/bin/env python
import sys

import os
from pycparser import c_parser, c_ast, c_generator
import copy
import pickle
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import math
import hashlib

from subprocess import Popen, PIPE
from collections import OrderedDict

import VHDL
import SW_LIB
import SYN
import VHDL_INSERT



RETURN_WIRE_NAME = "return_output"
SUBMODULE_MARKER = "____" # Hacky, need to be something unlikely as wire name
DEFAULT_LIBRARY_NAME = "work"
CONST_PREFIX="CONST_"
MUX_LOGIC_NAME="MUX"
UNARY_OP_LOGIC_NAME_PREFIX="UNARY_OP"
BIN_OP_LOGIC_NAME_PREFIX="BIN_OP"
STRUCT_RD_FUNC_NAME_PREFIX = "STRUCT_RD"
ARRAY_REF_CONST_FUNC_NAME_PREFIX = "ARRAY_REF_CONST"
RAW_HDL_PREFIX = "RAW_HDL"
BOOL_C_TYPE = "uint1_t"

# Unary Operators
UNARY_OP_NOT_NAME = "NOT"

# Binary operators
BIN_OP_GT_NAME = "GT"
BIN_OP_GTE_NAME = "GTE"
BIN_OP_LT_NAME = "LT"
BIN_OP_LTE_NAME = "LTE"
BIN_OP_PLUS_NAME = "PLUS"
BIN_OP_MINUS_NAME = "MINUS"
BIN_OP_EQ_NAME = "EQ"
BIN_OP_AND_NAME = "AND" # Ampersand?
BIN_OP_OR_NAME="OR"
BIN_OP_XOR_NAME = "XOR"
BIN_OP_SL_NAME = "SL"
BIN_OP_SR_NAME = "SR"
BIN_OP_MULT_NAME = "MULT"
BIN_OP_DIV_NAME = "DIV"


# TAKEN FROM https://github.com/eliben/pycparser/blob/c5463bd43adef3206c79520812745b368cd6ab21/pycparser/__init__.py
def preprocess_file(filename, cpp_path='cpp', cpp_args=''):
    """ Preprocess a file using cpp.
        filename:
            Name of the file you want to preprocess.
        cpp_path:
        cpp_args:
            Refer to the documentation of parse_file for the meaning of these
            arguments.
        When successful, returns the preprocessed file's contents.
        Errors from cpp will be printed out.
    """
    path_list = [cpp_path]
    if isinstance(cpp_args, list):
        path_list += cpp_args
    elif cpp_args != '':
        path_list += [cpp_args]
    path_list += [filename]

    try:
        # Note the use of universal_newlines to treat all newlines
        # as \n for Python's purpose
        #
        pipe = Popen(   path_list,
                        stdout=PIPE,
                        universal_newlines=True)
        text = pipe.communicate()[0]
    except OSError as e:
        raise RuntimeError("Unable to invoke 'cpp'.  " +
            'Make sure its path was passed correctly\n' +
            ('Original error: %s' % e))

    return text
    

def preprocess_text(text, cpp_path='cpp'):
	""" Preprocess a file using cpp.
        filename:
            Name of the file you want to preprocess.
        cpp_path:
        cpp_args:
            Refer to the documentation of parse_file for the meaning of these
            arguments.
        When successful, returns the preprocessed file's contents.
        Errors from cpp will be printed out.
    """
    
	path_list = [cpp_path]
	path_list += ["-"] # TO read from std in

	try:
		# Note the use of universal_newlines to treat all newlines
		# as \n for Python's purpose
		#
		pipe = Popen(   path_list,
						stdout=PIPE,
						stdin=PIPE,
                        universal_newlines=True)
        # Send in C text and get output
		text = pipe.communicate(input=text)[0]
	except OSError as e:
		raise RuntimeError("Unable to invoke 'cpp'.  " +
			'Make sure its path was passed correctly\n' +
			('Original error: %s' % e))

	return text

def casthelp(arg):
	try:
		print arg
	except:
		pass;
	
	try:
		arg.show()
	except:
		pass;
	
	try:	
		print dir(arg)
	except:
		pass; 
		
def LIST_UNION(a,b):
	return list( set().union(*[a,b]) )

def C_AST_VAL_UNIQUE_KEY_DICT_MERGE(d1_arg,d2_arg):
	d1 = copy.copy(d1_arg)
	d2 = copy.copy(d2_arg)
	rv = d1
	for key in d2:
		if key in d1:
			v1 = d1[key]
			v2 = d2[key]
			if C_AST_COORD_STR(v1.coord) != C_AST_COORD_STR(v2.coord):
				print "C_AST_VAL_UNIQUE_KEY_DICT_MERGE Dicts aren't unique:",d1,d2
				print "key", key
				print "v1",C_AST_COORD_STR(v1.coord)
				print "v2",C_AST_COORD_STR(v2.coord)
				print 0/0
				sys.exit(0)
			else:
				rv[key] = d2[key]
		else:
			# Key only in d2
			rv[key] = d2[key]
			
	return rv

def LIST_VAL_UNIQUE_KEY_DICT_MERGE(d1_arg,d2_arg):
	d1 = copy.copy(d1_arg)
	d2 = copy.copy(d2_arg)
	rv = d1
	for key in d2:
		if key in d1:
			v1 = d1[key]
			v2 = d2[key]
			if str(v1) != str(v2):
				print "List val dicts aren't unique:",d1,d2
				print "key", key
				print "v1",v1
				print "v2",v2
				print 0/0
				sys.exit(0)
			else:
				rv[key] = d2[key]
		else:
			# Key only in d2
			rv[key] = d2[key]
			
	return rv

def UNIQUE_KEY_DICT_MERGE(d1_arg,d2_arg):
	d1 = copy.copy(d1_arg)
	d2 = copy.copy(d2_arg)
	rv = d1
	for key in d2:
		if key in d1:
			v1 = d1[key]
			v2 = d2[key]
			if v1 != v2:
				print "Dicts aren't unique:",d1,d2
				print "key", key
				print "v1",v1
				print "v2",v2
				print 0/0
				sys.exit(0)
			else:
				rv[key] = d2[key]
		else:
			# Key only in d2
			rv[key] = d2[key]
			
	return rv
	
def DICT_LIST_VALUE_MERGE(d1_arg,d2_arg):
	d1 = copy.copy(d1_arg)
	d2 = copy.copy(d2_arg)
	rv = d1
	for key in d2:
		if key in rv:
			# Result is union of two lists
			rv[key] = LIST_UNION(rv[key],d2[key])
		else:
			rv[key] = d2[key]
			
	return rv   
	
def STR_LIST_PREPEND(l,prepend_text):
	new_l = []
	for i in l:
		new_l.append(prepend_text+i)
	return new_l

def STR_DICT_KEY_PREPREND(d,prepend_text):
	new_d = dict()
	
	#print "d",d
	for key in d:
		new_d[prepend_text+key] = d[key]
	return new_d

def STR_DICT_KEY_AND_ALL_VALUES_PREPREND(d,prepend_text):
	new_d = dict()
	for key in d:
		value = d[key]
		if type(value) is list:
			new_d[prepend_text+key] = STR_LIST_PREPEND(value,prepend_text)
		else:
			new_d[prepend_text+key] = prepend_text + value
		
	return new_d


class Logic:
	def __init__(self):
		self.func_name=None #function, operation
		self.inst_name=None
		self.variable_names=[] # List of original variable names
		self.wires=[]  # ["a","b","return"] wire names (renamed variable regs), includes inputs+outputs
		self.inputs=[] #["a","b"]
		self.outputs=[] #["return"]
		self.global_wires=[]
		self.uses_globals = False
		self.submodule_instances = dict() # instance name -> logic func_name
		self.c_ast_node = None
		# Is this logic a c built in C function?
		self.is_c_built_in = False
		
		
		# Mostly for c built in C functions
		# TODO: make self.submodule_instances into dict of fake logic objectS?
		self.submodule_instance_to_c_ast_node = dict()
		self.submodule_instance_to_input_port_names = dict()
		
		# Python graph example was dict() of strings so this
		# string based wire naming makes Pythonic sense.
		# I think pointers would work better.
		# Wire names with a dot means sub module connection
		# func0.a  is a port on the func0 instance
		# Connections are given as two lists "drives" and "driven by"
		self.wire_drives = dict() # wire_name -> [driven,wire,names]
		self.wire_driven_by = dict() # wire_name -> driving wire
		
		# To keep track of C execution over time in logic graph,
		# each assignment assigns to a renamed variable, renamed
		# variables keep execution order
		# Need to keep dicts for variable names
		self.wire_aliases_over_time = dict() # orig var name -> [list,of,renamed,wire,names] # Further in list is further in time
		self.orig_var_name = dict() # alias -> orig var name
		self.orig_wire_name = dict() # alias -> orig wire name
		
		# Need to look up types by wire name
		# wire_to_c_type[wire_name] -> c_type_str
		self.wire_to_c_type = dict()
		
		# For timing, levels of logic
		# this is populated by vendor tool
		self.total_logic_levels = None
		
		# Save C code text for later
		self.c_code_text = None
		
		# My containing inst?
		self.containing_inst = None
	
	def INST_LOGIC_ADJUST_W_PREPEND(self, new_inst_name_prepend_text):
		# Return logic
		logic = copy.deepcopy(self)

		# FUNC NAME STAYS SAME self.func_name=None #function, operation
		
		# NEW INST NAME IS USED TO RENAME EVERYTHING
		# MAIN INST NAME IS SPECIAL case
		if self.inst_name == "main":
			# Allow prepend if raw hdl
			if new_inst_name_prepend_text == (RAW_HDL_PREFIX + "_"):
				logic.inst_name = new_inst_name_prepend_text + self.inst_name
			elif new_inst_name_prepend_text != "":
				print 'new_inst_name_prepend_text != ""', new_inst_name_prepend_text
				sys.exit(0)
			else:
				# All good to ignore prepend
				logic.inst_name = self.inst_name
		else:
			'''
			# C built in has c ast coord already
			if logic.is_c_built_in or (len(logic.submodule_instances) <= 0):
				logic.inst_name = new_inst_name_prepend_text + self.inst_name 
			else:
				logic.inst_name = new_inst_name_prepend_text + self.inst_name + "_" + C_AST_COORD_STR(c_ast_node_when_used.coord)
			'''
			logic.inst_name = new_inst_name_prepend_text + self.inst_name
			
			#print "GET_INST_NAME_ADJUSTED_LOGIC"
			#print "logic.func_name",logic.func_name
			#print "new_inst_name_prepend_text",new_inst_name_prepend_text
			#print "self.inst_name ",self.inst_name 
			#print "C_AST_COORD_STR", C_AST_COORD_STR(c_ast_node_when_used.coord)
			#print ""
			
				
		prepend_text = logic.inst_name + SUBMODULE_MARKER
		
		# Then do regular prepend
		return logic.PREPEND_TEXT(prepend_text)
		
	def MERGE_COMB_LOGIC(self,logic_b):
		logic_a = self
		rv = Logic()
		
		# Func name must match if set
		if (logic_a.func_name is not None) and (logic_b.func_name is not None):
			if logic_a.func_name != logic_b.func_name:
				print "Cannot merge comb logic with mismatching func names!"
				print logic_a.func_name
				print logic_b.func_name
			else:
				rv.func_name = logic_a.func_name
		# Otherwise use whichever is set
		elif logic_a.func_name is not None:
			rv.func_name = logic_a.func_name
		else:
			rv.func_name = logic_b.func_name
		
		# Inst must match if set
		if (logic_a.inst_name is not None) and (logic_b.inst_name is not None):
			if logic_a.inst_name != logic_b.inst_name:
				print "Cannot merge comb logic with mismatching instance names!"
				print logic_a.inst_name
				print logic_b.inst_name
			else:
				rv.inst_name = logic_a.inst_name
		# Otherwise use whichever is set
		elif logic_a.inst_name is not None:
			rv.inst_name = logic_a.inst_name
		else:
			rv.inst_name = logic_b.inst_name
			
		# C built in status must match if set
		if (logic_a.is_c_built_in is not None) and (logic_b.is_c_built_in is not None):
			if logic_a.is_c_built_in != logic_b.is_c_built_in:
				print "Cannot merge comb logic with mismatching is_c_built_in !"
				print logic_a.inst_name, logic_a.is_c_built_in
				print logic_b.inst_name, logic_b.is_c_built_in
				sys.exit(0)
			else:
				rv.is_c_built_in = logic_a.is_c_built_in
		# Otherwise use whichever is set
		elif logic_a.is_c_built_in is not None:
			rv.is_c_built_in = logic_a.is_c_built_in
		else:
			rv.is_c_built_in = logic_b.is_c_built_in
			
		# Absorb true values of using globals
		rv.uses_globals = logic_a.uses_globals or logic_b.uses_globals
		
		# Merge lists
		rv.wires = LIST_UNION(logic_a.wires,logic_b.wires)
		rv.global_wires = LIST_UNION(logic_a.global_wires,logic_b.global_wires)
		rv.variable_names = LIST_UNION(logic_a.variable_names,logic_b.variable_names)
		
		# I/O order matters - check that
		# If one is empty then thats fine
		if len(logic_a.inputs) > 0 and len(logic_b.inputs) > 0:
			# Check for equal
			if logic_a.inputs != logic_b.inputs:
				print "Cannot merge comb logic with mismatching inputs !"
				print logic_a.inst_name, logic_a.inputs
				print logic_b.inst_name, logic_b.inputs
				print 0/0
				sys.exit(0)
			else:
				rv.inputs = copy.deepcopy(logic_a.inputs)
		else:
			# Default a
			rv.inputs = copy.deepcopy(logic_a.inputs)
			if len(logic_a.inputs) <= 0:
				rv.inputs = copy.deepcopy(logic_b.inputs)
		
		if len(logic_a.outputs) > 0 and len(logic_b.outputs) > 0:
			# Check for equal
			if logic_a.outputs != logic_b.outputs:
				print "Cannot merge comb logic with mismatching outputs !"
				print logic_a.inst_name, logic_a.outputs
				print logic_b.inst_name, logic_b.outputs
				sys.exit(0)
			else:
				rv.outputs = copy.deepcopy(logic_a.outputs)
		else:
			# Default a
			rv.outputs = copy.deepcopy(logic_a.outputs)
			if len(logic_a.outputs) <= 0:
				rv.outputs = copy.deepcopy(logic_b.outputs)
			
		
		# Merge dicts
		rv.wire_to_c_type = UNIQUE_KEY_DICT_MERGE(logic_a.wire_to_c_type,logic_b.wire_to_c_type)
		rv.submodule_instances = UNIQUE_KEY_DICT_MERGE(logic_a.submodule_instances,logic_b.submodule_instances)	
		rv.wire_driven_by = UNIQUE_KEY_DICT_MERGE(logic_a.wire_driven_by,logic_b.wire_driven_by)
		rv.wire_drives = DICT_LIST_VALUE_MERGE(logic_a.wire_drives,logic_b.wire_drives)
		
		# C ast node values wont be == , manual check with coord str
		rv.submodule_instance_to_c_ast_node = C_AST_VAL_UNIQUE_KEY_DICT_MERGE(logic_a.submodule_instance_to_c_ast_node,logic_b.submodule_instance_to_c_ast_node)
		rv.submodule_instance_to_input_port_names = LIST_VAL_UNIQUE_KEY_DICT_MERGE(logic_a.submodule_instance_to_input_port_names,logic_b.submodule_instance_to_input_port_names)

		
		# Also for both wire drives and driven by, remove wire driving self:
		# wire_driven_by
		new_wire_driven_by = dict()
		for driven_wire in rv.wire_driven_by:
			# Filter out self driving
			driving_wire = rv.wire_driven_by[driven_wire]
			if driving_wire != driven_wire:
				new_wire_driven_by[driven_wire] = driving_wire
		
		#print "new_wire_driven_by",new_wire_driven_by
		rv.wire_driven_by = new_wire_driven_by
		
		# wire_drives
		new_wire_drives = dict()
		for driving_wire in rv.wire_drives:
			driven_wires = rv.wire_drives[driving_wire]
			new_driven_wires = []
			for driven_wire in driven_wires:
				if driven_wire != driving_wire:
					new_driven_wires.append(driven_wire)	
			new_wire_drives[driving_wire] = new_driven_wires
		rv.wire_drives=new_wire_drives
				
		'''		
		# If one node is null then use other
		if logic_a.c_ast_node is None:
			rv.c_ast_node = logic_b.c_ast_node
		if logic_b.c_ast_node is None:
			rv.c_ast_node = logic_a.c_ast_node
		'''
		# C ast must match if set
		if (logic_a.c_ast_node is not None) and (logic_b.c_ast_node is not None):
			# For now its the same c ast node if its the same coord
			# If causes problems... abandon then
			if C_AST_COORD_STR(logic_a.c_ast_node.coord) != C_AST_COORD_STR(logic_b.c_ast_node.coord):
				print "Cannot merge comb logic with mismatching c_ast_node!"
				print logic_a.func_name
				print logic_b.func_name
				print logic_a.c_ast_node
				print logic_b.c_ast_node
				print 0/0
				sys.exit(0)
			else:
				rv.c_ast_node = logic_a.c_ast_node
		# Otherwise use whichever is set
		elif logic_a.c_ast_node is not None:
			rv.c_ast_node = logic_a.c_ast_node
		else:
			rv.c_ast_node = logic_b.c_ast_node
		
		
		
		# Only way this makes sense with MERGE_SEQUENTIAL_LOGIC
		# is for dicts to be equal (checked python docs for eq syntax)
		if logic_a.wire_aliases_over_time != logic_b.wire_aliases_over_time:
			# Only OK if one dict is completely empty
			if not(logic_a.wire_aliases_over_time == dict() or logic_b.wire_aliases_over_time == dict()):		
				print "Aliases over time do not match in MERGE_COMB_LOGIC!"
				print logic_a.wire_aliases_over_time
				print logic_b.wire_aliases_over_time
				sys.exit(0)
		rv.wire_aliases_over_time = copy.deepcopy(logic_a.wire_aliases_over_time)
		if logic_a.wire_aliases_over_time == dict():
			rv.wire_aliases_over_time = copy.deepcopy(logic_b.wire_aliases_over_time)

		# Only one orig wire name per alias
		rv.orig_var_name = UNIQUE_KEY_DICT_MERGE(logic_a.orig_var_name,logic_b.orig_var_name)
		rv.orig_wire_name = UNIQUE_KEY_DICT_MERGE(logic_a.orig_wire_name,logic_b.orig_wire_name) 
		
		# Code text keep whichever is set
		if (logic_a.c_code_text is not None) and (logic_b.c_code_text is not None):
			if logic_a.c_code_text != logic_b.c_code_text:
				print "Cannot merge comb logic with mismatching c_code_text!"
				print logic_a.c_code_text
				print logic_b.c_code_text
			else:
				rv.c_code_text = logic_a.c_code_text
		# Otherwise use whichever is set
		elif logic_a.c_code_text is not None:
			rv.c_code_text = logic_a.c_code_text
		else:
			rv.c_code_text = logic_b.c_code_text
		
		return rv
		
	# Function to merge logic with implied execution order
	def MERGE_SEQ_LOGIC(self, second_logic):
		first_logic = self
		rv = Logic()
		
		#print "first_logic.wire_drives", first_logic.wire_drives 
		#print "first_logic.wire_driven_by", first_logic.wire_driven_by 
		#print "second_logic.wire_drives", second_logic.wire_drives 
		#print "second_logic.wire_driven_by", second_logic.wire_driven_by 
		
		# Func name must match if set
		if (first_logic.func_name is not None) and (second_logic.func_name is not None):
			if first_logic.func_name != second_logic.func_name:
				print "Cannot merge comb logic with mismatching func names!"
				print first_logic.func_name
				print second_logic.func_name
		# Otherwise use whichever is set
		if first_logic.func_name is not None:
			rv.func_name = first_logic.func_name
		else:
			rv.func_name = second_logic.func_name
		
		# Inst must match if set
		if (first_logic.inst_name is not None) and (second_logic.inst_name is not None):
			if first_logic.inst_name != second_logic.inst_name:
				print "Cannot merge comb logic with mismatching instance names!"
				print first_logic.inst_name
				print second_logic.inst_name
		# Otherwise use whichever is set
		if first_logic.inst_name is not None:
			rv.inst_name = first_logic.inst_name
		else:
			rv.inst_name = second_logic.inst_name	
		
		# Merge lists
		rv.wires = LIST_UNION(first_logic.wires,second_logic.wires)
		rv.global_wires = LIST_UNION(first_logic.global_wires,second_logic.global_wires)
		rv.variable_names = LIST_UNION(first_logic.variable_names,second_logic.variable_names)
		
		# Absorb true values of using globals
		rv.uses_globals = first_logic.uses_globals or second_logic.uses_globals
		
		# I/O order matters - check that
		# If one is empty then thats fine
		if len(first_logic.inputs) > 0 and len(second_logic.inputs) > 0:
			# Check for equal
			if first_logic.inputs != second_logic.inputs:
				print "Cannot merge seq logic with mismatching inputs !"
				print first_logic.inst_name, first_logic.inputs
				print second_logic.inst_name, second_logic.inputs
				sys.exit(0)
			else:
				rv.inputs = copy.deepcopy(first_logic.inputs)
		else:
			# Default first_logic
			rv.inputs = first_logic.inputs
			if len(first_logic.inputs) <= 0:
				rv.outputs = copy.deepcopy(second_logic.inputs)
		
		if len(first_logic.outputs) > 0 and len(second_logic.outputs) > 0:
			# Check for equal
			if first_logic.outputs != second_logic.outputs:
				print "Cannot merge seq logic with mismatching outputs !"
				print first_logic.inst_name, first_logic.outputs
				print second_logic.inst_name, second_logic.outputs
				sys.exit(0)
			else:
				rv.outputs = copy.deepcopy(first_logic.outputs)
		else:
			# Default first_logic
			rv.outputs = first_logic.outputs
			if len(first_logic.outputs) <= 0:
				rv.outputs = copy.deepcopy(second_logic.outputs)
		
		
		
		rv.wire_to_c_type = UNIQUE_KEY_DICT_MERGE(first_logic.wire_to_c_type,second_logic.wire_to_c_type)
		
		# Merge dict
		rv.submodule_instances = UNIQUE_KEY_DICT_MERGE(first_logic.submodule_instances,second_logic.submodule_instances)
		rv.submodule_instance_to_c_ast_node = C_AST_VAL_UNIQUE_KEY_DICT_MERGE(first_logic.submodule_instance_to_c_ast_node,second_logic.submodule_instance_to_c_ast_node)
		rv.submodule_instance_to_input_port_names = LIST_VAL_UNIQUE_KEY_DICT_MERGE(first_logic.submodule_instance_to_input_port_names,second_logic.submodule_instance_to_input_port_names)
		
		
		# Driving wires need to reflect over time
		# Last alias from first logic replaces original wire name in second logic
		# self.wire_drives = dict() # wire_name -> [driven,wire,names]
		for orig_var in first_logic.wire_aliases_over_time:
			# And the var drives second_logic 
			if orig_var in second_logic.wire_drives:
				# First logic has aliases for orig var
				# Second logic has record of the orig var driving things
				# Both first and second logic should have same driven wies
				first_driven_wires = []
				if orig_var in first_logic.wire_drives:
					first_driven_wires = first_logic.wire_drives[orig_var]
				second_driven_wires = []
				if orig_var in second_logic.wire_drives:
					second_driven_wires = second_logic.wire_drives[orig_var]
					
				sorted_first_driven_wires = sorted(first_driven_wires)
				sorted_second_driven_wires = sorted(second_driven_wires)
				# Was the second logic actually refering to something different?
				if sorted_first_driven_wires != sorted_second_driven_wires:	
					# If second just has extra then OK
					if len(sorted_first_driven_wires) < len(sorted_second_driven_wires):
						# Check for match, but not like a dummy?
						#for i in range(0, len(sorted_first_driven_wires)):
						#	if sorted_first_driven_wires[i] != sorted_second_driven_wires[i]:
						for sorted_first_driven_wire in sorted_first_driven_wires:
							if sorted_first_driven_wire not in sorted_second_driven_wires:
								print "first driven wire:", sorted_first_driven_wire,"was not in second logic driven wires? was removed? wtf?"
								print "first:",sorted_first_driven_wires
								print "second:", sorted_second_driven_wires
								#print 0/0
								sys.exit(0)
						# Got match, first is subset of second, update first to match second
						first_logic.wire_drives[orig_var] = second_driven_wires[:]
						for second_driven_wire in second_driven_wires:
							first_logic.wire_driven_by[second_driven_wire] = second_logic.wire_driven_by[second_driven_wire]						
						
					else:
						# First has same or more, cant match second at this point
						print "orig_var",orig_var
						aliases = first_logic.wire_aliases_over_time[orig_var]
						print "first aliases",aliases
						last_alias = aliases[len(aliases)-1]
						print "first logic last_alias",last_alias
						print "first_logic.wire_drives[orig_var]",first_driven_wires
						print "second_logic.wire_drives[orig_var]",second_driven_wires
						# Get the last alias for that var from first logic
						print "second aliases", second_logic.wire_aliases_over_time[orig_var]
						
						# If this last alias is not in the first logic 
						
						# If aliases over time already agree then no need 
						
						# And replace that wire in the 
						# second logic wire_drives key (not value)
						temp_value = copy.deepcopy(second_logic.wire_drives[orig_var])
						# Delete orig var key
						second_logic.wire_drives.pop(orig_var, None)
						# Replace with last alias
						second_logic.wire_drives[last_alias] = temp_value
						print last_alias," DRIVES ", temp_value
						sys.exit(0)
						
		
		#print "AFTER first_logic.wire_drives", first_logic.wire_drives 
		#print "first_logic.wire_driven_by", first_logic.wire_driven_by 
		#print "second_logic.wire_drives", second_logic.wire_drives 
		#print "second_logic.wire_driven_by", second_logic.wire_driven_by 
		
		# wire_driven_by can't have multiple drivers over time and
		# should error out in normal merge below
		
		# If one node is null then use other
		if first_logic.c_ast_node is None:
			rv.c_ast_node = second_logic.c_ast_node
		if second_logic.c_ast_node is None:
			rv.c_ast_node = first_logic.c_ast_node
		
		# wire_aliases_over_time	
		# Do first+second first
		# If first logic has aliases over time
		for var_name in first_logic.wire_aliases_over_time:
			if var_name in second_logic.wire_aliases_over_time:
				# And so does second
				# Merged value is first plus second
				first = first_logic.wire_aliases_over_time[var_name]
				second = second_logic.wire_aliases_over_time[var_name]
				# Start with including first
				rv.wire_aliases_over_time[var_name] = copy.deepcopy(first)
				
				# Check that the aliases over time are equal 
				# in the period of time they share (the first logic)
				for i in range(0, len(first)):
					if first[i] != second[i]:
						print "At time index", i,"for orig variable name =", var_name,"the first and second logic do not agree:"
						print "First logic aliases over time:", first
						print "Second logic aliases over time:", second
						print 0/0
						sys.exit(0)
				
				# Equal in shared time so only append not shared part of second
				for i in range(len(first), len(second)):
					rv.wire_aliases_over_time[var_name].append(second[i])
				#print "rv.wire_aliases_over_time",rv.wire_aliases_over_time
					
			else:
				# First only alias (second does not have alias)
				# Merged value is first only
				rv.wire_aliases_over_time[var_name] = copy.deepcopy(first_logic.wire_aliases_over_time[var_name])
		# Then include wire_aliases_over_time ONLY from second logic
		for var_name in second_logic.wire_aliases_over_time:
			# And first logic does not
			if not(var_name in first_logic.wire_aliases_over_time):
				# Merged value is just from second logic
				second = second_logic.wire_aliases_over_time[var_name]
				rv.wire_aliases_over_time[var_name] = copy.deepcopy(second)
		
		# To not error in normal MERGE_LOGIC below, first and second logic must have same 
		# resulting wire_aliases_over_time
		modified_first_logic = copy.copy(first_logic)
		modified_second_logic = copy.copy(second_logic)
		modified_first_logic.wire_aliases_over_time = copy.deepcopy(rv.wire_aliases_over_time)
		modified_second_logic.wire_aliases_over_time = copy.deepcopy(rv.wire_aliases_over_time)
		
		# orig_wire_name Only one orig wire name per alias, handled in MERGE_LOGIC
		
		# Then merge logic as normal
		tmp = modified_first_logic.MERGE_COMB_LOGIC(modified_second_logic)
		
		rv = rv.MERGE_COMB_LOGIC(tmp)
		
		return rv	
			
			
	def PREPEND_TEXT(self, prepend_text):
		logic = copy.deepcopy(self)
		logic.variable_names = STR_LIST_PREPEND(self.variable_names, prepend_text) #   # List of original variable names
		logic.wires = STR_LIST_PREPEND(self.wires, prepend_text) # =[]  # ["a","b","return"] wire names (renamed variable regs), includes inputs+outputs
		logic.inputs = STR_LIST_PREPEND(self.inputs, prepend_text) # =[] #["a","b"]
		logic.outputs = STR_LIST_PREPEND(self.outputs, prepend_text) # =[] #["return"]
		logic.global_wires = STR_LIST_PREPEND(self.global_wires, prepend_text)
		logic.submodule_instances = STR_DICT_KEY_PREPREND(self.submodule_instances, prepend_text) #  = dict() # instance name -> logic func_name
		logic.submodule_instance_to_c_ast_node = STR_DICT_KEY_PREPREND(self.submodule_instance_to_c_ast_node, prepend_text) #  = dict() # Mostly for c built in C functions
		logic.submodule_instance_to_input_port_names = STR_DICT_KEY_AND_ALL_VALUES_PREPREND(self.submodule_instance_to_input_port_names, prepend_text)
		# self.c_ast_node = None
	
		# Python graph example was dict() of strings so this
		# string based wire naming makes Pythonic sense.
		# I think pointers would work better.
		# Wire names with a dot means sub module connection
		# func0.a  is a port on the func0 instance
		# Connections are given as two lists "drives" and "driven by"
		logic.wire_drives = STR_DICT_KEY_AND_ALL_VALUES_PREPREND(self.wire_drives, prepend_text) #  = dict() # wire_name -> [driven,wire,names]
		logic.wire_driven_by = STR_DICT_KEY_AND_ALL_VALUES_PREPREND(self.wire_driven_by, prepend_text) #  = dict() # wire_name -> driving wire
		
		# To keep track of C execution over time in logic graph,
		# each assignment assigns to a renamed variable, renamed
		# variables keep execution order
		# Need to keep dicts for variable names
		logic.wire_aliases_over_time = STR_DICT_KEY_AND_ALL_VALUES_PREPREND(self.wire_aliases_over_time, prepend_text) #  = dict() # orig var name -> [list,of,renamed,wire,names] # Further in list is further in time
		logic.orig_var_name = STR_DICT_KEY_AND_ALL_VALUES_PREPREND(self.orig_var_name, prepend_text) #  = dict() # alias -> orig var name
		logic.orig_wire_name = STR_DICT_KEY_AND_ALL_VALUES_PREPREND(self.orig_wire_name, prepend_text) #  = dict() # alias -> orig wire name
		
		# Need to look up types by wire name
		logic.wire_to_c_type = STR_DICT_KEY_PREPREND(self.wire_to_c_type, prepend_text) #  = dict() # wire_to_c_type[wire_name] -> c_type_str
		
		# For timing, levels of logic
		# this is populated by vendor tool
		#self.total_logic_levels=None
		
		
		return logic
		
		
			
	def SHOW(self):
		# Make adjency matrix out of all wires and submodule isnts and own 'wire'/node in network
		nodes = self.wires
		for submodule_inst in self.submodule_instances:
			nodes.append(submodule_inst)
		sorted_nodes = sorted(nodes)
		num_nodes = len(sorted_nodes)
		adjacency_matrix = np.zeros((num_nodes,num_nodes), dtype=np.int)
		# Build labels
		labels_dict = make_label_dict(sorted_nodes)
		rev_labels_dict = make_rev_label_dict(sorted_nodes)
		
		# Populate adjaceny matrix 
		for wire in self.wire_drives:
			driver_num = rev_labels_dict[wire]
			driven_wires = self.wire_drives[wire]
			
			# Get what a submodule inst form this wire would look like
			driving_submodule_inst_name = None
			if SUBMODULE_MARKER in wire:
				toks = wire.split(SUBMODULE_MARKER)
				inst_name = SUBMODULE_MARKER.join(toks[0:len(toks)-1])
				if inst_name in self.submodule_instances:
					driving_submodule_inst_name = inst_name
			
			# Do driven wires
			for driven_wire in driven_wires:
				driven_num = rev_labels_dict[driven_wire]
				adjacency_matrix[driver_num,driven_num] = 1
				
				# Get what a submodule inst form this driven wire would look like
				driven_submodule_inst_name = None
				if SUBMODULE_MARKER in driven_wire:
					toks = driven_wire.split(SUBMODULE_MARKER)
					inst_name = SUBMODULE_MARKER.join(toks[0:len(toks)-1])
					if inst_name in self.submodule_instances:
						driven_submodule_inst_name = inst_name
					
				# Assign IO for submodule insts
				if not(driving_submodule_inst_name is None):
					# Mus tbe output add common driver from submodule inst to output driver wire
					driving_submodule_node_num = rev_labels_dict[driving_submodule_inst_name]
					adjacency_matrix[driving_submodule_node_num,driver_num] = 1
				# Assign IO for submodule insts
				if not(driven_submodule_inst_name is None):
					# Msut be input
					# Add common inst driven by driver wire
					driven_submodule_node_num = rev_labels_dict[driven_submodule_inst_name]
					adjacency_matrix[driven_num,driven_submodule_node_num] = 1				
				
				
		show_graph_with_labels(adjacency_matrix, labels_dict)
			
			
		

# Thanks stack overflow
#https://stackoverflow.com/questions/29572623/plot-networkx-graph-from-adjacency-matrix-in-csv-file
def show_graph_with_labels(adjacency_matrix, mylabels):
    rows, cols = np.where(adjacency_matrix == 1)
    edges = zip(rows.tolist(), cols.tolist())
    gr = nx.Graph()
    gr.add_edges_from(edges)
    nx.draw(gr, node_size=500, labels=mylabels, with_labels=True)
    plt.show()
    
def make_label_dict(labels):
    l = {}
    for i, label in enumerate(labels):
        l[i] = label
    return l
def make_rev_label_dict(labels):
    l = {}
    for i, label in enumerate(labels):
        l[label] = i
    return l   
 


'''
# Returns output wires list for a given submodule
def GET_OUTPUT_WIRES_FROM_SUBMODULE(submodule_inst_name,logic):
	output_wires = []
	# Find driving wires from submodule name
	for driving_wire in logic.wire_drives:
		if SUBMODULE_MARKER in driving_wire:
			toks = driving_wire.split(SUBMODULE_MARKER)
			name = toks[0]
			output_wire = driving_wire
			if name == submodule_inst_name:
				output_wires.append(output_wire)
	return output_wires
'''
	
def WIRE_IS_CONSTANT(wire, logic_inst_name):
	# Remove inst name
	new_wire = wire.replace(logic_inst_name+SUBMODULE_MARKER,"")
	
	# Also split on last submodule marker
	toks = new_wire.split(SUBMODULE_MARKER)
	last_tok = toks[len(toks)-1]
	
	rv = last_tok.startswith(CONST_PREFIX)
	
	if (CONST_PREFIX in wire) and not(rv) and not(ARRAY_REF_CONST_FUNC_NAME_PREFIX in wire):
		print "WHJAT!?"
		print "logic_inst_name",logic_inst_name
		print "wire",wire
		print "new_wire", new_wire
		print "WIRE_IS_CONSTANT   but is not?"
		sys.exit(0)	
	
	return rv
	

def WIRE_IS_SUBMODULE_PORT(wire, logic):
	# Is everything but last item submodule in this logic?
	toks = wire.split(SUBMODULE_MARKER)
	possible_submodule_inst = SUBMODULE_MARKER.join(toks[0:len(toks)-1])
	
	# Check port name too?
	# No for now?
	return possible_submodule_inst in logic.submodule_instances
	
	
	

	

def BUILD_C_BUILT_IN_SUBMODULE_LOGIC_INST(containing_func_logic, new_inst_name_prepend_text, submodule_inst_name, parser_state):	
	# Construct a fake 'submodule_logic' with correct name, inputs, outputs
	submodule_logic = Logic()
	submodule_logic.is_c_built_in = True
	# Look up logic name for the submodule instance
	#print "containing_func_logic.submodule_instances",containing_func_logic.submodule_instances
	submodule_logic_name = containing_func_logic.submodule_instances[submodule_inst_name]
	#print "submodule_inst_name",submodule_inst_name
	#print "submodule_logic_name",submodule_logic_name
	submodule_logic.func_name = submodule_logic_name
	submodule_logic.inst_name = submodule_inst_name
	
	# Ports and types are specific to the submodule instance
	# Get data from c ast node
	c_ast_node = containing_func_logic.submodule_instance_to_c_ast_node[submodule_inst_name]
	submodule_logic.c_ast_node = c_ast_node
	
	# It looks like the c parser doesnt let you look up type from name...
	# Probably would be complicated
	# Lets manually do it.
	# 1) parse funtion param declartions in wire_to_c_type
	# 2) parse var decls to wire_to_c_type
	# 3) Look up driver of submodule to determine type
	
	# Assume children list is is order of args if not HDL INSERT
	input_names = []
	if submodule_logic.func_name.startswith(VHDL_INSERT.HDL_INSERT):
		# STRUCTREF READ?
		structref_rd = VHDL_INSERT.HDL_INSERT + "_" + VHDL_INSERT.STRUCTREF_RD
		structref_wr = VHDL_INSERT.HDL_INSERT + "_" + VHDL_INSERT.STRUCTREF_WR
		if submodule_logic.func_name.startswith(structref_rd):
			# One input
			input_names = [VHDL_INSERT.STRUCTREF_VAR_PORT]
		elif submodule_logic.func_name.startswith(structref_wr):
			# Two inputs
			# Order matters
			input_names = [VHDL_INSERT.STRUCTREF_VAR_PORT, VHDL_INSERT.STRUCTREF_FIELD_PORT]						
		else:
			print "What are the inputs for this HDL_INSERT?", submodule_logic.func_name
			sys.exit(0)		
			
		submodule_logic.inputs += input_names
		
	elif submodule_logic.func_name.startswith(STRUCT_RD_FUNC_NAME_PREFIX):
		# Input port names can be figured out from wires?
		# Seems hacky but OK for now?
		#NO CANT and cante be hard coded ... damn..include port names in func name? aw wtf
		# Call to logic ?
		
		#...
		#add dict to container logic that is submodule inst to inport port list? wrtf
		
		input_names = containing_func_logic.submodule_instance_to_input_port_names[submodule_inst_name]

		submodule_logic.inputs += input_names
	else:
		if submodule_inst_name in containing_func_logic.submodule_instance_to_input_port_names:
			input_names = containing_func_logic.submodule_instance_to_input_port_names[submodule_inst_name]
			submodule_logic.inputs += input_names
		else:
			for child in c_ast_node.children():
				name=child[0]
				input_names.append(name)
				submodule_logic.inputs.append(name)
		
	
	# For each input wire look up type of driving wire
	input_types = []
	for input_name in input_names:	
		input_wire_name = submodule_inst_name + SUBMODULE_MARKER + input_name
		#print logic.wire_driven_by
		driving_wire = containing_func_logic.wire_driven_by[input_wire_name]
		c_type = containing_func_logic.wire_to_c_type[driving_wire]
		# If driving wire c type is enum and this is BIN OP == then replace with input port wire with uint
		if (c_type in parser_state.enum_to_ids_dict) and (submodule_logic_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_EQ_NAME)):
			#print "submodule_logic_name", submodule_logic_name, "BIN_OP_EQ_NAME ENUM"
			#print "right enum"
			num_ids = len(parser_state.enum_to_ids_dict[c_type])
			width = int(math.ceil(math.log(num_ids,2)))
			c_type = "uint" + str(width) + "_t"
		submodule_logic.wire_to_c_type[input_name] = c_type
		input_types.append(c_type)
		
	# Output wire is return wire and type is type of what is driven
	output_port_name = RETURN_WIRE_NAME
	submodule_logic.outputs.append(RETURN_WIRE_NAME)
	output_wire_name = submodule_inst_name + SUBMODULE_MARKER + output_port_name
	
	# Mux output type is that of inputs
	if submodule_logic.func_name.startswith(MUX_LOGIC_NAME):
		# Mux is cond is input[0], left is [1] and should be of same type as right
		submodule_logic.wire_to_c_type[output_port_name]=input_types[1]
			
	# By default assume type of driven wire
	elif output_wire_name in containing_func_logic.wire_drives:
		driven_wires = containing_func_logic.wire_drives[output_wire_name]
		if len(driven_wires)==0 :
			print "Built in submodule not driving anthying?",submodule_inst_name
			sys.exit(0)
		c_type = containing_func_logic.wire_to_c_type[driven_wires[0]]
		submodule_logic.wire_to_c_type[output_port_name]=c_type
		
	else:
		print "Input type to output type mapping assumption for built in submodule output "
		print submodule_logic.func_name
		print submodule_logic.inst_name
		sys.exit(0)		
			
	
	# Also do submodule instances for built in logic that is not raw VHDL
	if VHDL.C_BUILT_IN_FUNC_IS_RAW_HDL(submodule_logic_name,input_types):	
		# IS RAW VHDL
		pass
	# NOT RAW VHDL (assumed to be built from C code then)
	else:
		submodule_logic = BUILD_LOGIC_AS_C_CODE(new_inst_name_prepend_text, submodule_logic, parser_state, containing_func_logic)
	
	
	# Do here for early debug
	SYN.IS_BITWISE_OP(submodule_logic)
			
	return submodule_logic
	
def BUILD_LOGIC_AS_C_CODE(new_inst_name_prepend_text, partially_complete_logic, parser_state, containing_func_logic):
	out_dir = SYN.GET_OUTPUT_DIRECTORY(partially_complete_logic, implement=False)
	# Get C code depending on function
	#print "partially_complete_logic.func_name",partially_complete_logic.func_name
	if partially_complete_logic.func_name == (BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MULT_NAME):
		# Get the c code
		c_code_text = SW_LIB.GET_BIN_OP_MULT_C_CODE(partially_complete_logic, out_dir, parser_state)
	elif partially_complete_logic.func_name == (BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_DIV_NAME):
		c_code_text = SW_LIB.GET_BIN_OP_DIV_C_CODE(partially_complete_logic, out_dir)
	elif partially_complete_logic.func_name == (BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_GT_NAME):
		c_code_text = SW_LIB.GET_BIN_OP_GT_GTE_C_CODE(partially_complete_logic, out_dir, op_str=">")
	elif partially_complete_logic.func_name == (BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_GTE_NAME):
		c_code_text = SW_LIB.GET_BIN_OP_GT_GTE_C_CODE(partially_complete_logic, out_dir, op_str=">=")
	elif partially_complete_logic.func_name == (BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_PLUS_NAME):
		c_code_text = SW_LIB.GET_BIN_OP_PLUS_C_CODE(partially_complete_logic, out_dir)
	elif partially_complete_logic.func_name == (BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MINUS_NAME):
		c_code_text = SW_LIB.GET_BIN_OP_MINUS_C_CODE(partially_complete_logic, out_dir)
	elif partially_complete_logic.func_name == (BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_SL_NAME):
		c_code_text = SW_LIB.GET_BIN_OP_SL_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state)
	elif partially_complete_logic.func_name == (BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_SR_NAME):
		c_code_text = SW_LIB.GET_BIN_OP_SR_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state)
	else:
		print "How to BUILD_LOGIC_AS_C_CODE for",partially_complete_logic.func_name, "?"
		sys.exit(0)
		
	# Use the c code to get the logic
	partially_complete_logic.c_code_text = c_code_text
	
	#print "c_code_text"
	#print c_code_text
	
	# And read logic
	#print "partially_complete_logic.
	fake_filename = VHDL.GET_INST_NAME(partially_complete_logic, use_leaf_name=True) + ".c"
	#print "fake_filename",fake_filename
	out_path = out_dir + "/" + fake_filename
		
	# Parse and return the only func def
	func_name = partially_complete_logic.func_name
	#print ""
	#print "BUILD_BIN_OP_MULT_LOGIC_AS_C_CODE"
	sw_func_name_2_logic = SW_LIB.GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_CODE_TEXT(c_code_text, parser_state)
	# Merge into existing
	for sw_func_name in sw_func_name_2_logic:
		#print "sw_func_name",sw_func_name
		parser_state.FuncName2Logic[sw_func_name] = sw_func_name_2_logic[sw_func_name]
	
	FuncName2Logic = GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(c_code_text, fake_filename, parser_state, parse_body = True)
	
	# Get the other partial logic if it exists
	if not(func_name in FuncName2Logic):
		print "I cant find func name",func_name,"in the C code so far"
		print "c_code_text"
		print c_code_text
		print "========="
		print "sw_func_name_2_logic"
		print sw_func_name_2_logic
		print "CHECK CODE PARSING autogenerated stuff?"
		sys.exit(0)
	other_partial_logic = FuncName2Logic[func_name]
	
	#print "partially_complete_logic.func_name",partially_complete_logic.func_name
	#print "partially_complete_logic.inst_name",partially_complete_logic.inst_name
	#print "other_partial_logic.func_name", other_partial_logic.func_name
	#print "other_partial_logic.submodule_instances", other_partial_logic.submodule_instances
	#print "partially_complete_logic.inputs",partially_complete_logic.inputs
	#print "other_partial_logic.inputs", other_partial_logic.inputs
	if other_partial_logic.func_name in other_partial_logic.submodule_instances:
		print "other_partial_logic.func_name in other_partial_logic.submodule_instances"
		print "other_partial_logic.func_name",other_partial_logic.func_name
		sys.exit(0)
	
	# Func logic has wrong inst name
	other_partial_logic.inst_name = partially_complete_logic.inst_name
	#print "other_partial_logic.inst_name",other_partial_logic.inst_name
	# Also needs built in flag from partial logic
	other_partial_logic.is_c_built_in = partially_complete_logic.is_c_built_in
	# Fix cast ndoe too
	other_partial_logic.c_ast_node = partially_complete_logic.c_ast_node
	
	# Combine two partial logics
	#print "partially_complete_logic.c_ast_node.coord", partially_complete_logic.c_ast_node.coord
	#print "other_partial_logic.c_ast_node.coord", other_partial_logic.c_ast_node.coord
	merged_logic = partially_complete_logic.MERGE_COMB_LOGIC(other_partial_logic)
	#print "merged_logic.c_ast_node.coord", merged_logic.c_ast_node.coord
	
	#print "merged_logic.inst_name", merged_logic.inst_name
	#print "merged_logic.func_name", merged_logic.func_name
	
	return merged_logic
		
	
def GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(text, fake_filename, parser_state, parse_body):
	# Build function name to logic from func defs from files
	func_name_2_logic = copy.deepcopy(parser_state.FuncName2Logic)
	
	func_defs = GET_C_AST_FUNC_DEFS_FROM_C_CODE_TEXT(text, fake_filename)
	for func_def in func_defs:
		# Each func def produces a single logic item
		existing_logic=None
		driven_wire_names=[]
		prepend_text=""
		logic = C_AST_FUNC_DEF_TO_LOGIC(func_def, parser_state, parse_body)
		#logic = C_AST_NODE_TO_LOGIC(func_def,existing_logic, driven_wire_names, prepend_text, func_name_2_logic)
		func_name_2_logic[logic.func_name] = logic
		func_name_2_logic[logic.func_name].inst_name = logic.func_name 
	return func_name_2_logic
	
		
# WHY CAN I NEVER REMEMBER DICT() IS NOT IMMUTABLE (AKA needs copy operator)
	
# Returns list of logics
def MERGE_LOGIC_LISTS(logics_a,logics_b):
	# Mere logic items if same name
	# Store as dict name-> logic
	# Return as list
	logic_lookup_table = dict()
	both_lists = logics_a + logics_b
	
	for logic in both_lists:
		logic_into_table = None
		if logic.name in logic_lookup_table:
			logic_from_table = logic_lookup_table[logic.name]
			logic_into_table = logic.MERGE_COMB_LOGIC(logic_from_table)
		else:
			logic_into_table = logic
			
		if not(logic_into_table is None):
			logic_lookup_table[logic.name] = logic_into_table
			
	return logic_lookup_table.values()
	

# Node needs context for variable renaming over time, can give existing logic
def C_AST_NODE_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
	func_name_2_logic = parser_state.FuncName2Logic
	
	rv = Logic()
	existing_logic_copy = Logic()
	if parser_state.existing_logic is not None:
		existing_logic_copy = rv.MERGE_COMB_LOGIC(parser_state.existing_logic)
	
	# Cover logic as far up in c ast tree as possible
	# Each node will have function to deal with node type:
	# which may or may not recursively call this function.
	
	# C_AST nodes can represent pure structure logic
	if type(c_ast_node) == c_ast.FuncDef:
		if prepend_text!="":
			print "prepend for func def what?"
			sys.exit(0)
		return C_AST_FUNC_DEF_TO_LOGIC(c_ast_node, parser_state)
	elif type(c_ast_node) == c_ast.Compound:
		return C_AST_COMPOUND_TO_LOGIC(c_ast_node, prepend_text, parser_state)
	elif type(c_ast_node) == c_ast.Decl:
		return C_AST_DECL_TO_LOGIC(c_ast_node, prepend_text, parser_state)	
	elif type(c_ast_node) == c_ast.If:
		return C_AST_IF_TO_LOGIC(c_ast_node,prepend_text, parser_state)
	elif type(c_ast_node) == c_ast.Return:
		return C_AST_RETURN_TO_LOGIC(c_ast_node, prepend_text, parser_state)
	elif type(c_ast_node) == c_ast.FuncCall:
		return C_AST_FUNC_CALL_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
	elif type(c_ast_node) == c_ast.BinaryOp:
		return C_AST_BINARY_OP_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
	elif type(c_ast_node) == c_ast.UnaryOp:
		return C_AST_UNARY_OP_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
	elif type(c_ast_node) == c_ast.Constant:
		return C_AST_CONSTANT_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
		'''
	elif type(c_ast_node) == c_ast.ID:
		ret = C_AST_ID_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state)
		return ret
	elif type(c_ast_node) == c_ast.StructRef:
		ret = C_AST_STRUCTREF_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state)
		return ret
		'''
	elif type(c_ast_node) == c_ast.ID or type(c_ast_node) == c_ast.StructRef :
		return C_AST_ID_OR_STRUCTREF_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
	elif type(c_ast_node) == c_ast.ArrayRef:
		return C_AST_ARRAYREF_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
	elif type(c_ast_node) == c_ast.Assignment:
		return C_AST_ASSIGNMENT_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state)
	else:
		#start here
		print "Cannot parse c ast node to logic: ",c_ast_node
		casthelp(c_ast_node)
		print "driven_wire_names=",driven_wire_names
		sys.exit(0)
		
	# Update parser state since merged in exsiting logic earlier
	parser_state.existing_logic = rv
		
	return rv
	
def C_AST_RETURN_TO_LOGIC(c_ast_return, prepend_text, parser_state):
	# Check for double return
	if RETURN_WIRE_NAME in parser_state.existing_logic.wire_driven_by:
		print "What, more than one return? Come on man don't make me sad...", str(c_ast_return.coord)
		sys.exit(0)	
	
	# Return is just connection to wire
	# Since each logic blob is a C function
	# only one return per function allowed
	# connect variable wire name to "return"
	driven_wire_names=[RETURN_WIRE_NAME]
	prepend_text=""
	return_logic = C_AST_NODE_TO_LOGIC(c_ast_return.expr, driven_wire_names, prepend_text, parser_state)
	

	##### Bleh do the easier hard coded for 0 clk way for now
	
	# Also tie all globals to global wire
	# Collpase struct ref hierarchy to get top most orig wire name nodes	
	#print "parser_state.existing_logic.global_wires",parser_state.existing_logic.global_wires
	global_orig_wire_names = REDUCE_STRUCTREF_WIRES(parser_state.existing_logic.global_wires, parser_state)
	#print "global_orig_wire_names",global_orig_wire_names
	# Whooray
	for global_wire in global_orig_wire_names:
		'''
		# Most recent alias drives global output
		orig_var_name = ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(global_wire)
		mra = GET_MOST_RECENT_ALIAS(parser_state.existing_logic, orig_var_name)
		orig_wire_name = mra
		if mra in parser_state.existing_logic.orig_wire_name:
			orig_wire_name = parser_state.existing_logic.orig_wire_name[mra]
		'''
		# Most recent alias of global wire drives global wire 
		# Read orig wire takes care of struct refs
		connect_logic = READ_ORIG_WIRE_LOGIC(global_wire, [global_wire], c_ast_return, prepend_text, parser_state)
		return_logic = return_logic.MERGE_COMB_LOGIC(connect_logic)
	
	
	parser_state.existing_logic = return_logic
	# Connect the return logic node to this one
	return return_logic

def C_AST_ID_TO_ORIG_WIRE_NAME(c_ast_id):
	orig_wire_name = str(c_ast_id.name)
	return orig_wire_name
	
def GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref):
	if type(c_ast_structref.name) == c_ast.StructRef:
		names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref.name)
		names_list = names_list + [c_ast_structref.field.name]
		return names_list
	elif type(c_ast_structref.name) == c_ast.ID:
		name_wire = str(c_ast_structref.name.name)
		names_list = [name_wire, c_ast_structref.field.name]
		return names_list
	elif type(c_ast_structref.name) == c_ast.ArrayRef:
		names_list = GET_NAMES_LIST_FROM_ARRAYREF(c_ast_structref.name)
		names_list = names_list + [c_ast_structref.field.name]
		return names_list
	else:
		print "Need entry in GET_NAMES_LIST_FROM_STRUCTREF", 
		casthelp(c_ast_structref.name)
		sys.exit(0)
	
	return rv

'''	
def GET_NAMES_LIST_FROM_ARRAYREF(c_ast_arrayref):
	casthelp(c_ast_arrayref)
	sys.exit(0)
	
	if type(c_ast_structref.name) == c_ast.StructRef:
		names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref.name)
		names_list = names_list + [c_ast_structref.field.name]
		return names_list
	elif type(c_ast_structref.name) == c_ast.ID:
		name_wire = str(c_ast_structref.name.name)
		names_list = [name_wire, c_ast_structref.field.name]
		return names_list
	elif type(c_ast_structref.name) == c_ast.ArrayRef:
		names_list = GET_NAMES_LIST_FROM_ARRAYREF(c_ast_structref.name)
		names_list = names_list + [c_ast_structref.field.name]
		return names_list
	else:
		print "Need entry in GET_NAMES_LIST_FROM_STRUCTREF", 
'''	
	
def GET_LEAF_FIELD_NAME_FROM_STRUCTREF(c_ast_structref):
	names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref)
	return names_list[len(names_list)-1]
	
	
def GET_BASE_VARIABLE_NAME_FROM_STRUCTREF(c_ast_structref):
	names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref)
	return names_list[0]

	
def C_AST_STRUCTREF_TO_ORIG_WIRE_NAME(c_ast_structref):
	names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref)
	return ".".join(names_list)
	#return c_ast_structref.field.name

'''
def C_AST_ARRAYREF_TO_ORIG_WIRE_NAME(c_ast_arrayref):
	# FOR ASSIGNMENT
	# TODO
	print "Do C_AST_ARRAYREF_TO_ORIG_WIRE_NAME for asingment"
	print 0/0
	sys.exit(0)
	#names_list = GET_NAMES_LIST_FROM_ARRAYREF(c_ast_arrayref)
	#return ".".join(names_list) #Uhh?
'''
		
def C_AST_NODE_TO_MOST_RECENT_WIRE_NAME(c_ast_node,existing_logic):
	orig_var_name = C_AST_NODE_TO_ORIG_VAR_NAME(c_ast_node)
	if existing_logic is not None:
		most_recent_alias = GET_MOST_RECENT_ALIAS(existing_logic, orig_var_name)
		return most_recent_alias
	else:
		return orig_wire_name
		
def ORIG_VAR_NAME_TO_MOST_RECENT_ALIAS(orig_var_name, existing_logic):
	if existing_logic is not None:
		most_recent_alias = GET_MOST_RECENT_ALIAS(existing_logic, orig_var_name)
		return most_recent_alias
	else:
		return orig_var_name	

def ORIG_VAR_NAME_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(orig_wire_name, c_ast_node,  existing_logic):
	# Alias will include location in src
	coord_str = C_AST_COORD_STR(c_ast_node.coord)
	# Base name
	alias_base = orig_wire_name+"_"+coord_str+"_"
	
	# Check existing logic for alias
	# First one to try is "0"
	i=0
	alias = alias_base+str(i)
	if existing_logic is not None:
		if orig_wire_name in existing_logic.wire_aliases_over_time:
			aliases = existing_logic.wire_aliases_over_time[orig_wire_name]
			while alias in aliases:
				i=i+1
				alias = alias_base+str(i)
	
	return alias


def C_AST_NODE_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(c_ast_node, existing_logic):
	if type(c_ast_node) == c_ast.ID:
		orig_wire = C_AST_ID_TO_ORIG_WIRE_NAME(c_ast_node)
		return ORIG_VAR_NAME_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(orig_wire,c_ast_node,existing_logic)
	elif type(c_ast_node) == c_ast.StructRef:
		orig_wire = C_AST_STRUCTREF_TO_ORIG_WIRE_NAME(c_ast_node)
		return ORIG_VAR_NAME_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(orig_wire,c_ast_node,existing_logic)
	else:
		print "No entry in C_AST_NODE_TO_NEXT_WIRE_ASSIGNMENT_ALIAS, only allow variable IDs/names only ? Can't need pointers right?"
		casthelp(c_ast_node)
		sys.exit(0)
		
def C_AST_NODE_TO_ORIG_WIRE_NAME(c_ast_node):
	# This needs to be resursive?
	# Maybe can loop
	curr_node = c_ast_node
	
	# Get text for curr
	curr_text = None
	if type(c_ast_node) == c_ast.ID:
		curr_text = C_AST_ID_TO_ORIG_WIRE_NAME(c_ast_node)
	elif type(c_ast_node) == c_ast.StructRef:
		curr_text = C_AST_STRUCTREF_TO_ORIG_WIRE_NAME(c_ast_node)
	elif type(c_ast_node) == c_ast.ArrayRef:
		curr_text = C_AST_ARRAYREF_TO_ORIG_WIRE_NAME(c_ast_node)
	#elif type(c_ast_node) == c_ast.Constant:
	#	curr_text = C_AST_CONSTANT_TO_ORIG_WIRE_NAME(c_ast_node)
	else:
		print "No entry in C_AST_NODE_TO_ORIG_WIRE_NAME"
		casthelp(c_ast_node)
		sys.exit(0)
			
	# Done?
	return curr_text
	

def C_AST_CONSTANT_TO_ORIG_WIRE_NAME(c_ast_node):
	return str(c_ast_node.value)
		
def GET_MOST_RECENT_ALIAS(logic,orig_var_name):
	if orig_var_name in logic.wire_aliases_over_time:
		aliases =  logic.wire_aliases_over_time[orig_var_name]
		last_alias = aliases[len(aliases)-1]
		return last_alias
	else:
		return orig_var_name
		
		
		
# Wire aliases over time?
#L1 p = q     p_1 <= q
#L2 p.x = something  
#L3 z = p.x

# Handle struct refs as submodules/functions
# Those functions are written as raw vhdl text but in logic cloud look like submodules
# If this works great, if not ill be so sad

# ****Write to struct ref is recorded as:
#     p_2 <= HDL_INSERT_p.x(p_1,something)
# ****Read from to struct ref is recorded as:
#     z_3 <= HDL_INSERT_p.x(p_2)
# Lets us keep wire alias over time behavior and lots of other nice working, unfound bugs, code there, awesome, whatever

		
def C_AST_ASSIGNMENT_TO_LOGIC(c_ast_assignment,driven_wire_names,prepend_text, parser_state):	
	func_name_2_logic = parser_state.FuncName2Logic
	existing_logic = parser_state.existing_logic
	
	rv = Logic()
	if existing_logic is not None:
		rv = rv.MERGE_COMB_LOGIC(existing_logic)
	# BOTH LHS and RHS CAN BE EXPRESSIONS!!!!!!
	# BUT LEFT SIDE MUST RESULT IN VARIABLE ADDRESS / wire?
	#^^^^^^^^^^^^^^^^^
	
	###########################################
	# RECORD NEW ALIAS FOR THIS ASSIGNMENT!!!
	
	# Assignments are ordered over time with existing logic
	# Assigning to a variable creates an alias
	# future reads on this variable are done from the alias
	lhs_next_wire_assignment_alias = prepend_text+C_AST_NODE_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(c_ast_assignment.lvalue, rv)
	#print "lhs_next_wire_assignment_alias",lhs_next_wire_assignment_alias
	# Orig wire name
	lhs_orig_wire_name = C_AST_NODE_TO_ORIG_WIRE_NAME(c_ast_assignment.lvalue)
	lhs_orig_var_name = C_AST_NODE_TO_ORIG_VAR_NAME(c_ast_assignment.lvalue)
	#### GLOBALS \/
	# This is the first place we should see a global reference in terms of this function/logic
	if lhs_orig_var_name in parser_state.global_info:
		# Copy info into existing_logic
		rv.wire_to_c_type[lhs_orig_var_name] = parser_state.global_info[lhs_orig_var_name].type_name
		
		lhs_c_type = ORIG_WIRE_NAME_TO_C_TYPE(lhs_orig_wire_name, parser_state)
		rv.wire_to_c_type[lhs_orig_wire_name] = lhs_c_type

		# Add as global
		#if lhs_orig_wire_name not in rv.global_wires:
		#	rv.global_wires.append(lhs_orig_wire_name)
		if lhs_orig_var_name not in rv.global_wires:
			rv.global_wires.append(lhs_orig_var_name)
			
		# Record using globals
		rv.uses_globals = True
		
		# Record change in parser state
		parser_state.existing_logic = rv
		
	# /\
	# SET LHS TYPE
	parser_state.existing_logic = rv
	lhs_c_type = ORIG_WIRE_NAME_TO_C_TYPE(lhs_orig_wire_name, parser_state)
	if not(lhs_orig_var_name in rv.variable_names):
		rv.variable_names.append(lhs_orig_var_name)
	#print "lhs_orig_wire_name", lhs_orig_wire_name
	# Type of alias wire is same as original wire
	#if lhs_orig_wire_name in rhs_to_lhs_logic.wire_to_c_type:
	rv.wire_to_c_type[lhs_orig_wire_name] = lhs_c_type
	rv.wire_to_c_type[lhs_next_wire_assignment_alias] = lhs_c_type
	
	
	###### DO EVUALTION OF RIGHT SIDE FIRST BEFORE MAKING ALIAS OF LEFT SIDE
	# Need intermediate wire 
	
	#print "c_ast_assignment.rvalue"
	#casthelp(c_ast_assignment.rvalue)
	driven_wire_names=[lhs_next_wire_assignment_alias]
	parser_state.existing_logic = rv
	rhs_to_lhs_logic = C_AST_NODE_TO_LOGIC(c_ast_assignment.rvalue, driven_wire_names, prepend_text, parser_state)
	#print "after 'rv' in rv.wire_to_c_type", "rv" in rv.wire_to_c_type
	
	# Set type of RHS wire as LHS type if not known
	rhs_driver = rhs_to_lhs_logic.wire_driven_by[lhs_next_wire_assignment_alias]
	if rhs_driver not in rhs_to_lhs_logic.wire_to_c_type:
		rhs_to_lhs_logic.wire_to_c_type[rhs_driver] = lhs_c_type	
	
	#print "rv.wire_aliases_over_time",existing_logic.wire_aliases_over_time
	
	#print "rhs_to_lhs_logic",rhs_to_lhs_logic
	#print "==="
	##print "rhs_to_lhs_logic.wire_driven_by",rhs_to_lhs_logic.wire_driven_by
	#print "rhs_to_lhs_logic.wire_aliases_over_time",rhs_to_lhs_logic.wire_aliases_over_time
	
	# Merge existing and rhs logic
	#print "rhs_to_lhs_logic.wire_aliases_over_time",rhs_to_lhs_logic.wire_aliases_over_time
	#print "existing_logic.wire_aliases_over_time",existing_logic.wire_aliases_over_time
	rv = rv.MERGE_SEQ_LOGIC(rhs_to_lhs_logic)	
	#print "rv.wire_aliases_over_time",ret_logic.wire_aliases_over_time
	
	############## LEFT SIDE

	
	
	
	# Add alias to list in existing logic
	existing_aliases = []
	if lhs_orig_var_name in rv.wire_aliases_over_time:
		existing_aliases = rv.wire_aliases_over_time[lhs_orig_var_name]
	new_aliases = existing_aliases
	
    # Dont double add aliases
	if not(lhs_next_wire_assignment_alias in new_aliases):
		new_aliases = new_aliases + [lhs_next_wire_assignment_alias]
	rv.wire_aliases_over_time[lhs_orig_var_name] = new_aliases
	rv.orig_wire_name[lhs_next_wire_assignment_alias] = lhs_orig_wire_name
	rv.orig_var_name[lhs_next_wire_assignment_alias] = lhs_orig_var_name
	
	#print "lhs_orig_wire_name",lhs_orig_wire_name
	#print "rv.wire_aliases_over_time[lhs_orig_wire_name]",rv.wire_aliases_over_time[lhs_orig_wire_name]
	
	#print "existing_logic.wire_aliases_over_time",existing_logic.wire_aliases_over_time
	
	# Set wire_drives/wire_driven_by with logic for RHS drigin LHS alias	
	#print "'rv' in rv.wire_to_c_type", "rv" in rv.wire_to_c_type
	#if not("rv" in rv.wire_to_c_type):
	#	print "AHH"
	#	sys.exit(0)
	
	# Update parser state since merged in exsiting logic earlier
	parser_state.existing_logic = rv
	
	
	return rv

def GET_STRUCTREF_TYPE(c_ast_structref, parser_state):
	orig_wire = C_AST_STRUCTREF_TO_ORIG_WIRE_NAME(c_ast_structref)
	return GET_STRUCTREF_WIRE_TYPE(orig_wire, parser_state)

def GET_STRUCTREF_WIRE_TYPE(structref_orig_wire, parser_state):
	# Descend hierarchy to this particular struct ref
	field_names = structref_orig_wire.split(".")

	# Get base variable name
	var_name = field_names[0]
	
	# This is the first place we should see a global reference in terms of this function/logic
	if var_name in parser_state.global_info:
		# Copy info into existing_logic
		parser_state.existing_logic.wire_to_c_type[var_name] = parser_state.global_info[var_name].type_name

		# Add as global
		#if orig_wire_name not in parser_state.existing_logic.global_wires:
		#	parser_state.existing_logic.global_wires.append(orig_wire_name)
		if var_name not in parser_state.existing_logic.global_wires:
			parser_state.existing_logic.global_wires.append(var_name)
			
		# Record using globals
		parser_state.existing_logic.uses_globals = True
	
		
	# Get the type of this base name
	if var_name not in parser_state.existing_logic.wire_to_c_type:
		print "It looks like variable", var_name, "is not defined?"
		print 0/0
		sys.exit(0)
		
	base_type = parser_state.existing_logic.wire_to_c_type[var_name]
	#print "base_type",base_type
	
	# Lead field name
	leaf_name = field_names[len(field_names)-1]
	#print "LEAF", leaf_name
	
	# Look up struct info
	#print "parser_state.struct_to_field_type_dict",parser_state.struct_to_field_type_dict
	field_type_dict = parser_state.struct_to_field_type_dict[base_type]
		
	#print "field_names",field_names
	
	#print "field_type_dict",field_type_dict
	i = 1 # [0] is base var name
	field_i = field_names[i]
	if field_i not in field_type_dict:
		print field_i, "is not a member field of",base_type
		sys.exit(0)
	field_i_type = field_type_dict[field_i]
	field_is_struct = field_i_type in parser_state.struct_to_field_type_dict
	
	rv = field_i_type
	#print "parser_state.struct_to_field_type_dict",parser_state.struct_to_field_type_dict
	while field_is_struct:
		if field_i == leaf_name:
			rv = field_i_type
			break
		
		# Lookup new info
		i = i + 1
		field_i = field_names[i] # [0] is base var name
		field_is_struct = field_i_type in parser_state.struct_to_field_type_dict
		if field_is_struct:
			next_field_type_dict = parser_state.struct_to_field_type_dict[field_i_type]
			#print "field_i_type",field_i_type
			#print "next_field_type_dict:",next_field_type_dict
			if field_i not in next_field_type_dict:
				print structref_orig_wire,"is not a valid struct ref.", field_i, "not found in that struct's hierarchy?"
				sys.exit(0)
			
			field_i_type = next_field_type_dict[field_i]
		else:
			print "field_i_type", field_i_type, "is not struct?"
			sys.exit(0)
		
		
	if field_i != leaf_name:
		print "What didnt find leaf?"
		sys.exit(0)
		
	return rv
	
	
def C_AST_NODE_TO_ORIG_VAR_NAME(c_ast_node):
	if type(c_ast_node) == c_ast.ID:
		return C_AST_ID_TO_ORIG_WIRE_NAME(c_ast_node)
	elif type(c_ast_node) == c_ast.StructRef:
		return GET_BASE_VARIABLE_NAME_FROM_STRUCTREF(c_ast_node)
	else:
		print "WHat C_AST_NODE_TO_ORIG_VAR_NAME", c_ast_node
		sys.exit(0)

	
def ORIG_WIRE_NAME_TO_C_TYPE(orig_wire_name,parser_state):	
	# Is this an orig var name? no dots
	if "." in orig_wire_name:
		c_type = GET_STRUCTREF_WIRE_TYPE(orig_wire_name, parser_state)
		'''
	elif ORIG_WIRE_NAME_IS_ARRAYREF(orig_wire_name):
		# Remove subscript
		orig_wire_no_sub = REMOVE_ARRAY_SUBSCRIPT(orig_wire_name)
		# Get type of wire without subscript, should be array type
		array_type = ORIG_WIRE_NAME_TO_C_TYPE(orig_wire_no_sub,parser_state)
		if not C_TYPE_IS_ARRAY(array_type):
			print "Wtf not array type?"
			sys.exit(0)
		array_item_type = REMOVE_ARRAY_SUBSCRIPT(array_type)
		return array_item_type
	'''
	else:
		if orig_wire_name in parser_state.existing_logic.wire_to_c_type:
			c_type = parser_state.existing_logic.wire_to_c_type[orig_wire_name]
		elif orig_wire_name in parser_state.global_info:
			c_type = parser_state.global_info[orig_wire_name].type_name
		else:
			print "It looks like '",orig_wire_name,"' isn't declared?"
			print "orig_wire_name not in parser_state.existing_logic.wire_to_c_type"
			#print 0/0
			sys.exit(0)
		
	return c_type
	
	
# Rv a base type has one branch
# Rv (a struct): has many branches, rv.a, rv.c.d
def ORIG_WIRE_NAME_TO_ALL_BRANCH_WIRES(orig_wire_name, parser_state):
	c_type = ORIG_WIRE_NAME_TO_C_TYPE(orig_wire_name,parser_state)
	is_struct = c_type in parser_state.struct_to_field_type_dict
	
	# Is name a struct?
	if is_struct:
		rv = []
		# Yes is struct
		# Return list is this child branches of this wire
		# Child branches are struct field names
		field_type_dict = parser_state.struct_to_field_type_dict[c_type]
		for field in field_type_dict:
			new_wire = orig_wire_name + "." + field
			rv += [new_wire]
			# Recurse on new wire
			rv += ORIG_WIRE_NAME_TO_ALL_BRANCH_WIRES(new_wire, parser_state)
			
		return rv		
	else:
		# Not struct so is leaf
		return [orig_wire_name]
		

def REDUCE_STRUCTREF_WIRES(wires, parser_state):
	# Collpase ex. [struct.pointa.x, struct.pointa.y, struct.pointb.x]
	# collpases down to [struct.pointa, struct.pointb.x] since sub elements of point are all driven
	rv_wires = wires[:]
	still_removing_elements = True
	while still_removing_elements:
		# Assume stopping now
		still_removing_elements = False
		
		# Loop over all orig wires
		loop_copy_rv_wires = rv_wires[:]
		for orig_wire_name in loop_copy_rv_wires:

			# Remove children of this orig_wire_name struct ref
			# Remove any of those
			for orig_wire_name_i in loop_copy_rv_wires:
				if orig_wire_name_i.startswith(orig_wire_name + "."):
					if orig_wire_name_i in rv_wires:
						#print "orig_wire_name_i",orig_wire_name_i
						rv_wires.remove(orig_wire_name_i)
					#else:
					#	print "missing orig_wire_name_i",orig_wire_name_i
			
			# Record if change was made and jump to next iteration
			if rv_wires != loop_copy_rv_wires:
				still_removing_elements = True
				break
				
			## If not a struct ref then no more collpasing possible
			if "." not in orig_wire_name:
				continue					

			# Get root struct for this struct ref
			toks = orig_wire_name.split(".")
			root_wire = ".".join(toks[0:len(toks)-1])
			# Check if all fields of this root struct ref are in this list
			struct_c_type = ORIG_WIRE_NAME_TO_C_TYPE(root_wire,parser_state)
			field_types_dict = parser_state.struct_to_field_type_dict[struct_c_type]
			all_fields_present = True
			for field_name in field_types_dict:
				possible_wire  = root_wire + "." + field_name
				if possible_wire not in rv_wires:
					all_fields_present = False
			# If all there then remove them all
			if all_fields_present:
				still_removing_elements = True
				for field_name in field_types_dict:
					possible_wire  = root_wire + "." + field_name
					rv_wires.remove(possible_wire)
				# And replace with root
				rv_wires.append(root_wire)
				
	return rv_wires

# THIS IS DIFFERENT FROM REDUCE DONE ABOVE
def REMOVE_COVERED_BRANCHES(remaining_wires, alias, parser_state):
	# Get orig wire name from alias
	# First assume isnt alias
	orig_wire_name = alias
	if alias in parser_state.existing_logic.orig_wire_name:
		orig_wire_name = parser_state.existing_logic.orig_wire_name[alias]
		
	# Loop over each wire
	new_remaining_wires = []
	
	# First loop for obvious coverage 
	# Given alias wire a.b.c , it covers any remaining wire a.b.c.x, a.b.c.y
	for remaining_wire in remaining_wires:
		if not remaining_wire.startswith(orig_wire_name):
			# Save this wire
			new_remaining_wires.append(remaining_wire)
	
	# Then remove any struct types with no remaining driven children
	rv = []
	for remaining_wire in new_remaining_wires:
		c_type = ORIG_WIRE_NAME_TO_C_TYPE(remaining_wire,parser_state)
		if c_type in parser_state.struct_to_field_type_dict:
			# Is struct type, what branches does it have?
			branches = ORIG_WIRE_NAME_TO_ALL_BRANCH_WIRES(remaining_wire,parser_state)
			# Any of those left in list
			has_remaining_branch = False
			for branch in branches:
				if branch in new_remaining_wires:
					has_remaining_branch = True
					break
			if not has_remaining_branch:
				# No remaining branches so elminate this wire
				continue
				
		# Save this wire
		rv.append(remaining_wire)
	
	return rv
	
def GET_STRUCT_RD_INPUT_PORT_NAME_FROM_DRIVING_WIRE(driving_wire, parser_state):
	if driving_wire in parser_state.existing_logic.orig_wire_name:
		# Is alias get orig wire name
		# Driving alias could be entire orig struct or some branch
		orig_wire_name = parser_state.existing_logic.orig_wire_name[driving_wire]
	else:
		# Assume is orig wire name
		orig_wire_name = driving_wire
	
	
	#print "driving_alias",driving_alias
	#print "orig_wire_name",orig_wire_name
	
	if "." in orig_wire_name:
		toks = orig_wire_name.split(".")
		fields = ".".join(toks[1:])
		port_name = "." + fields
	else:
		# must be self, use whole var as port name then?
		port_name = orig_wire_name
		
	return port_name
	

# Struct read is different from array read since:
# At the time of struct read it is possible to narrow down the 
# renamed intermediate wires that of what the struct ref is referreing
# for an array reference the "struct locations in memory / memory addrs" cannot be known ahead of time
# Always need to input entire array unless constant, when constant do like struct ref?

	'''
DID you do struct ref wrong?
CANT PROCESS AS single x.y.z expression
Need to recursively get X, with .y  ... then get output of that DOT z
fuck

ONly diff between constant array and dynamic is where the "branches" start in the structref/array search
# Since arrays are written to like structs, COPY ON READ
Structref and constant array look very similar
'''

	'''
def C_AST_REF_TO_LOGIC(c_ast_ref,driven_wire_names, prepend_text, parser_state):


	# Need to recursively identify the wire that is the result of dereferencing
	return C_AST_REF_TO_LOGIC(c_ast_arrayref,driven_wire_names, prepend_text, parser_state)
'''


	
# ID could be a struct ID which needs struct read logic
# So combine ID and STRUCTREF
def C_AST_ID_OR_STRUCTREF_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state):
	# Convert this into orig wire read
	orig_wire_name = C_AST_NODE_TO_ORIG_WIRE_NAME(c_ast_node)
	
	# Is the ID an ENUM constant?
	is_enum_const = ID_OR_STRUCTREF_IS_ENUM_CONST(orig_wire_name, parser_state.existing_logic, parser_state)
	if is_enum_const:
		#print "orig_wire_name",orig_wire_name,"is_enum_const"
		return C_AST_ENUM_CONST_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
	else:
		#print orig_wire_name,"IS NOT ENUM CONST"
		return READ_ORIG_WIRE_LOGIC(orig_wire_name, driven_wire_names, c_ast_node, prepend_text, parser_state)

'''
def ORIG_WIRE_NAME_IS_ARRAYREF(orig_wire_name):
	return "[" in orig_wire_name and orig_wire_name.endswith("]")
'''

def REMOVE_LAST_ARRAY_SUBSCRIPT(wire):
	return wire.split("[")[0]
def ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(orig_wire_name):
	struct_base_var_name = orig_wire_name.split(".")[0]
	'''
	if ORIG_WIRE_NAME_IS_ARRAYREF(struct_base_var_name):
		# Remove subscript
		struct_base_var_name = REMOVE_ARRAY_SUBSCRIPT(struct_base_var_name)
	'''
	return struct_base_var_name
	
def C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_array_type):
	toks = input_array_type.split("[")
	#print toks
	elem_type = toks[0]
	dims = []
	for tok_i in range(1,len(toks)):
		tok = toks[tok_i]
		dim = int(tok.replace("]",""))
		dims.append(dim)
	return elem_type, dims
	
def GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(input_array_type):
	elem_type, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_array_type)
	output_dims = dims[1:]
	output_type = elem_type
	for output_dim in output_dims:
		output_type = output_type + "[" + str(output_dim) + "]"
		
	return output_type


#_omg_fuck_me_this_is_dumb = 0
def C_AST_ARRAYREF_TO_LOGIC(c_ast_arrayref,driven_wire_names, prepend_text, parser_state):
	#casthelp(c_ast_arrayref)
	#print str(c_ast_arrayref)
	#children = c_ast_arrayref.children()
	#print c_ast_arrayref.subscript
	#print c_ast_arrayref.coord
	# array ref
	# <expr>[<subscript>]
	
	# What do we know that identifies this array ref?
	# holy shit column numbers are useless here
	# fuck this is dumb
	# But I tried a few even more dumb things first
	# Fuck
	hash_ext = "_" + ((hashlib.md5(str(c_ast_arrayref)).hexdigest())[0:4]) # Uh 4 chars enough?

	# Is this a constant array ref?
	# Fuck only accept constants for now
	# Will eventually need to evaluate expressions from constant loop variables
	subscript_node = c_ast_arrayref.subscript
	if type(subscript_node) == c_ast.Constant:
		func_name = ARRAY_REF_CONST_FUNC_NAME_PREFIX + hash_ext
	else:
		print "Non constant array reference at:", c_ast_arrayref.coord
		sys.exit(0)
	func_inst_name = BUILD_INST_NAME(prepend_text,func_name, c_ast_arrayref)
	
	# The name expression is is just a wire
	# Name that wire
	array_input_port_name = "input_array"
	input_expr_wire = func_inst_name + "_interm_" + array_input_port_name
	
	# Get logic that drives input array
	name_node = c_ast_arrayref.name
	input_array_logic = C_AST_NODE_TO_LOGIC(name_node, [input_expr_wire], prepend_text, parser_state)
	parser_state.existing_logic.MERGE_COMB_LOGIC(input_array_logic)
	if input_expr_wire not in parser_state.existing_logic.wire_to_c_type:
		print parser_state.existing_logic.wire_to_c_type
	input_array_type = parser_state.existing_logic.wire_to_c_type[input_expr_wire]
	
	# Can we look up type of array
	#print "=========="
	#print "func_inst_name",func_inst_name
	#print "INput array type:", input_array_type
	elem_type, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_array_type)
	n_dims = len(dims)
	#print "n_dims",n_dims
	#print "dims",dims
	
	# Subscript width is based on how widethe inner subscript is
	subscript_bits = int(math.ceil(math.log(dims[0], 2)))
	subscript_type = "uint" + str(subscript_bits) + "_t"
	# Subscript is another wire
	subscript_input_port_name = "subscript"
	subscript_wire = func_inst_name + "_interm_" + subscript_input_port_name
	parser_state.existing_logic.wire_to_c_type[subscript_wire] = subscript_type
	
	# Get logic that drives subscript
	subscript_logic = C_AST_NODE_TO_LOGIC(subscript_node, [subscript_wire], prepend_text, parser_state)
	parser_state.existing_logic.MERGE_COMB_LOGIC(subscript_logic)
	
	# Remove inner subscript to form output type
	output_type = GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(input_array_type)
	

	#print "output_type",output_type
	
	
	# Connect the input array and subscript to an array ref function
	c_ast_node_2_driven_input_wire_names = OrderedDict()
	# N input port names named by their arg name
	# Decompose inputs to N ARG FUNCTION
	# Dont use input nodes
	use_input_nodes_fuck_it = False
	# INput array
	input_port_wire = func_inst_name+SUBMODULE_MARKER+array_input_port_name
	c_ast_node_2_driven_input_wire_names[input_expr_wire] = [input_port_wire]
	parser_state.existing_logic.wire_to_c_type[input_port_wire] = input_array_type
	# Subscript
	subscript_port_wire = func_inst_name+SUBMODULE_MARKER+subscript_input_port_name
	c_ast_node_2_driven_input_wire_names[subscript_wire] = [subscript_port_wire]
	parser_state.existing_logic.wire_to_c_type[subscript_port_wire] = subscript_type
	# Output
	output_port_name = RETURN_WIRE_NAME		
	output_wire = func_inst_name+SUBMODULE_MARKER+output_port_name
	parser_state.existing_logic.wire_to_c_type[output_wire] = output_type
	
	
	func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(func_name, c_ast_node_2_driven_input_wire_names, output_wire, driven_wire_names,prepend_text,c_ast_arrayref,parser_state,use_input_nodes_fuck_it)
	parser_state.existing_logic.MERGE_COMB_LOGIC(func_logic)
	
	# Santy set types of driven wires based on output wire type?
	for driven_wire_name in driven_wire_names:
		parser_state.existing_logic.wire_to_c_type[driven_wire_name] = output_type
	
	return parser_state.existing_logic
	


def READ_ORIG_WIRE_LOGIC(orig_wire_name, driven_wire_names, c_ast_node, prepend_text, parser_state):
	
	# Does this need a struct read function?
	# Does last alias cover the entire struct/wire 
	# Kinda assuming is struct so dont assume c_ast type
	
	# Get the base var name
	base_var_name = ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(orig_wire_name)
	c_type = ORIG_WIRE_NAME_TO_C_TYPE(orig_wire_name, parser_state)
	
	
	# This is the first place we should see a global reference in terms of this function/logic
	if base_var_name in parser_state.global_info:
		# Copy info into existing_logic
		parser_state.existing_logic.wire_to_c_type[base_var_name] = parser_state.global_info[base_var_name].type_name
		parser_state.existing_logic.wire_to_c_type[orig_wire_name] = c_type

		# Add as global
		#if orig_wire_name not in parser_state.existing_logic.global_wires:
		#	parser_state.existing_logic.global_wires.append(orig_wire_name)
		if base_var_name not in parser_state.existing_logic.global_wires:
			parser_state.existing_logic.global_wires.append(base_var_name)
			
		# Record using globals
		parser_state.existing_logic.uses_globals = True
	
	# Use base var (NOT ORIG WIRE SINCE structs) to look up alias list
	driving_aliases_over_time = [base_var_name]
	aliases_over_time = []
	if base_var_name in parser_state.existing_logic.wire_aliases_over_time:
		aliases_over_time = parser_state.existing_logic.wire_aliases_over_time[base_var_name]
	driving_aliases_over_time += aliases_over_time
	
	# Does most recent alias cover entire wire?
	# Break orig wire name to all branches
	all_wires = ORIG_WIRE_NAME_TO_ALL_BRANCH_WIRES(orig_wire_name, parser_state)
	
	#print "orig_wire_name",orig_wire_name
	#print "all_wires",all_wires
	
	# Find the first alias (IN REVERSE ORDER) that elminates some branches
	remaining_wires = all_wires[:]
	i = len(driving_aliases_over_time)-1
	first_driving_alias = None
	len_pre_drive = None
	while remaining_wires == all_wires:
		alias = driving_aliases_over_time[i]
		alias_c_type = parser_state.existing_logic.wire_to_c_type[alias]
	
		len_pre_drive = len(remaining_wires)
		remaining_wires = REMOVE_COVERED_BRANCHES(remaining_wires, alias, parser_state)
		# Next alias working backwards
		i = i - 1
	
	# At this point alias is first driver
	first_driving_alias = alias
	first_driving_alias_c_type = alias_c_type
	# If all wires elminated because was exact type match then do simple wire assignment
	orig_wire_c_type = ORIG_WIRE_NAME_TO_C_TYPE(orig_wire_name,parser_state)
	first_driving_alias_type_match = first_driving_alias_c_type==orig_wire_c_type
	
	if len(remaining_wires) == 0 and first_driving_alias_type_match:
		return GET_SIMPLE_CONNECT_LOGIC(first_driving_alias, driven_wire_names, c_ast_node, prepend_text, parser_state)		
	else:
		######
		# TODO: Replace 1 input functions (not first alias or type match) with VHDL insert
		#
		#######

		# Create list of driving aliases
		driving_aliases = []
		if len(remaining_wires) < len_pre_drive:
			driving_aliases += [first_driving_alias]
		
		# Needs struct read function
		func_name = STRUCT_RD_FUNC_NAME_PREFIX + "_" + orig_wire_name
		func_inst_name = BUILD_INST_NAME(prepend_text,func_name, c_ast_node)
		
		# Input wire is most recent copy of input ID node 
		c_ast_node_2_driven_input_wire_names = OrderedDict()
			
		# N input port names named by their arg name
		# Decompose inputs to N ARG FUNCTION
		# Dont use input nodes
		use_input_nodes_fuck_it = False
		
		
		#print "func_inst_name",func_inst_name
		#print "driving_aliases_over_time",driving_aliases_over_time
		#print "first_driving_alias",first_driving_alias
		#print "remaining_wires after first alias",remaining_wires

		# Work backwards in alias list starting with next wire
		i = len(driving_aliases_over_time)-2
		while len(remaining_wires) > 0:
			alias = driving_aliases_over_time[i]

			# Then remove all branch wires covered by this driver
			len_pre_drive = len(remaining_wires)
			remaining_wires = REMOVE_COVERED_BRANCHES(remaining_wires, alias, parser_state)
			
			# Record this alias as driver if it drove wires
			if len(remaining_wires) < len_pre_drive:
				driving_aliases += [alias]
			
			# Next alias working backwards
			i = i - 1	
		
		# Reverse order of drivers
		driving_aliases = driving_aliases[::-1]
	
		#print "driving_aliases",driving_aliases
		#sys.exit(0)
		
		# Each of those aliases drives an input port
		# Input port names are important?
		# input port names are derived form aliases
		# 
		for driving_alias in driving_aliases:
			input_port_name = GET_STRUCT_RD_INPUT_PORT_NAME_FROM_DRIVING_WIRE(driving_alias, parser_state)
			input_port_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
			# Remember using driving wire not c ast node  (since doing use_input_nodes_fuck_it = False)
			#print "driving_alias",driving_alias
			#print "drives:"
			#print "input_port_wire",input_port_wire
			c_ast_node_2_driven_input_wire_names[driving_alias] = [input_port_wire]
			
		#print "c_ast_node_2_driven_input_wire_names"
		#for x,y in c_ast_node_2_driven_input_wire_names.iteritems():
		#	print x,y
			
		# Output wire is the type of the struct ref
		output_port_name = RETURN_WIRE_NAME
		# If we know type of output then use that
		if driven_wire_names[0] in parser_state.existing_logic.wire_to_c_type:
			output_c_type = parser_state.existing_logic.wire_to_c_type[driven_wire_names[0]]
		else:
			# Otherwise output wire is the type of the struct ref 
			output_c_type = GET_STRUCTREF_WIRE_TYPE(orig_wire_name, parser_state)
			# Set type of output wire too
			parser_state.existing_logic.wire_to_c_type[driven_wire_names[0]] = output_c_type
			
		output_wire = func_inst_name+SUBMODULE_MARKER+output_port_name
		parser_state.existing_logic.wire_to_c_type[output_wire] = output_c_type
		

		# Before evaluating input nodes make sure type of port is there so constants can be evaluated
		# Get type from driving aliases (since doing use_input_nodes_fuck_it = False)
		for driving_alias in c_ast_node_2_driven_input_wire_names:
			input_port_wires = c_ast_node_2_driven_input_wire_names[driving_alias]
			for input_port_wire in input_port_wires:
				parser_state.existing_logic.wire_to_c_type[input_port_wire] = parser_state.existing_logic.wire_to_c_type[driving_alias]
		
		
		# DO THE N ARG FUNCTION
		func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(func_name, c_ast_node_2_driven_input_wire_names, output_wire, driven_wire_names,prepend_text,c_ast_node,parser_state,use_input_nodes_fuck_it)
		parser_state.existing_logic = func_logic
			
		
		return func_logic
		

def GET_SIMPLE_CONNECT_LOGIC(driving_wire, driven_wire_names, c_ast_node, prepend_text, parser_state):
	existing_logic = parser_state.existing_logic
	
	# Connect driving wire to driven wires	
	connect_logic = CONNECT_WIRES_LOGIC(driving_wire, driven_wire_names)
	
	
	# Technically the existing logic is before this SEQ merge
	if not(existing_logic is None):
		first_logic = existing_logic
		second_logic = connect_logic
		seq_merged_logic = first_logic.MERGE_SEQ_LOGIC(second_logic)

		# Look up that type and make sure if the driven wire names have types that they match	
		#print c_ast_id.coord
		if not(driving_wire in seq_merged_logic.wire_to_c_type):
			print "Looks like wire'",driving_wire,"'isn't declared?"
			print C_AST_COORD_STR(c_ast_node.coord)
			sys.exit(0)
		rhs_type = seq_merged_logic.wire_to_c_type[driving_wire]
		
		
		for driven_wire_name in driven_wire_names:
			if driven_wire_name in seq_merged_logic.wire_to_c_type:
				driven_wire_type = seq_merged_logic.wire_to_c_type[driven_wire_name]
				if driven_wire_type != rhs_type:
					
					# Integer promotion / slash supported truncation in C lets this be OK
					if ( ( VHDL.WIRES_ARE_INT_N([driven_wire_name],seq_merged_logic) or VHDL.WIRES_ARE_UINT_N([driven_wire_name],seq_merged_logic))
						and 
						 ( VHDL.C_TYPE_IS_INT_N(rhs_type) or VHDL.C_TYPE_IS_UINT_N(rhs_type) )   ):
							 continue
					# Enum driving UINT is fine
					elif VHDL.WIRES_ARE_UINT_N([driven_wire_name],seq_merged_logic) and WIRE_IS_ENUM(driving_wire, parser_state.existing_logic, parser_state):
						continue
					
					# Otherwise bah!
					#print "VHDL.WIRES_ARE_UINT_N([driven_wire_name],seq_merged_logic)",VHDL.WIRES_ARE_UINT_N([driven_wire_name],seq_merged_logic)
					#print "WIRE_IS_ENUM(driving_wire, parser_state.existing_logic, parser_state)",WIRE_IS_ENUM(driving_wire, parser_state.existing_logic, parser_state)
					print "RHS",driving_wire,"drives",driven_wire_name,"with different types?"
					print driven_wire_type, rhs_type
					sys.exit(0)
			else:
				# Driven wire type isnt set, set it
				seq_merged_logic.wire_to_c_type[driven_wire_name] = rhs_type
		
				
		#print "seq_merged_logic.wire_drives", seq_merged_logic.wire_drives 
		#print "seq_merged_logic.wire_driven_by", seq_merged_logic.wire_driven_by 
				
		# Update parser state since merged in exsiting logic earlier
		parser_state.existing_logic = seq_merged_logic
				
		return seq_merged_logic
	else:
		# No existing logic just return connect logic
		return connect_logic	


	
def WIRE_IS_ENUM(maybe_not_enum_wire, existing_logic, parser_state):	
	# Will not be:
	#	(this is dumb)
	#   known to enum
	#	input
	#	global
	#	variable
	# 	output
	#
	# Then must be ENUM
	if (maybe_not_enum_wire in existing_logic.wire_to_c_type) and (existing_logic.wire_to_c_type[maybe_not_enum_wire] in parser_state.enum_to_ids_dict):
		return True
	elif ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(maybe_not_enum_wire) in existing_logic.inputs:
		return False
	elif (maybe_not_enum_wire in existing_logic.global_wires) or (ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(maybe_not_enum_wire) in parser_state.global_info):
		return False
	elif ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(maybe_not_enum_wire) in existing_logic.variable_names:
		return False
	elif ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(maybe_not_enum_wire) in existing_logic.outputs:
		return False
	else:
		#print "ENUM:",maybe_not_enum_wire
		return True
		
def ID_OR_STRUCTREF_IS_ENUM_CONST(id_or_struct_ref_maybe_enum_wire, existing_logic, parser_state):	
	
	# Will not be:
	#	(this is dumb)
	#   known to enum const
	#	input
	#	global
	#	variable
	# 	output
	#
	# Then must be ENUM
	inst_name = ""
	if existing_logic.inst_name is not None:
		inst_name = existing_logic.inst_name
	
	
	if (id_or_struct_ref_maybe_enum_wire in existing_logic.wire_to_c_type) and (existing_logic.wire_to_c_type[id_or_struct_ref_maybe_enum_wire] in parser_state.enum_to_ids_dict) and WIRE_IS_CONSTANT(id_or_struct_ref_maybe_enum_wire, inst_name):
		return True
	elif ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(id_or_struct_ref_maybe_enum_wire) in existing_logic.inputs:
		return False
	elif (id_or_struct_ref_maybe_enum_wire in existing_logic.global_wires) or (ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(id_or_struct_ref_maybe_enum_wire) in parser_state.global_info):
		return False
	elif ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(id_or_struct_ref_maybe_enum_wire) in existing_logic.variable_names:
		return False
	elif ORIG_WIRE_NAME_TO_ORIG_VAR_NAME(id_or_struct_ref_maybe_enum_wire) in existing_logic.outputs:
		return False
	else:
		# Check that is one of the enum consts available at least :(
		for enum_type in parser_state.enum_to_ids_dict:
			ids = parser_state.enum_to_ids_dict[enum_type]
			for id_str in ids:
				if id_str == id_or_struct_ref_maybe_enum_wire:
					return True
		return False
	
# ENUM is like constant
def C_AST_ENUM_CONST_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state):
	existing_logic = parser_state.existing_logic
	
	# Create wire for this constant
	#wire_name = prepend_text+"CONST_" + str(c_ast_node.type)+ "_"+ str(c_ast_node.value) + "_" + C_AST_COORD_STR(c_ast_node.coord)
	#wire_name =  CONST_PREFIX + str(c_ast_node.type)+ "_"+ str(c_ast_node.value)
	value = str(c_ast_node.name)
	#casthelp(c_ast_node)
	#print "value",value
	#print "==="
	# Hacky use $ for enum only oh sad
	wire_name =  CONST_PREFIX + str(value) + "$" + C_AST_COORD_STR(c_ast_node.coord)
	rv = CONNECT_WIRES_LOGIC(wire_name, driven_wire_names)
	
	rv = rv.MERGE_COMB_LOGIC(existing_logic)
	

	### FUCK CAN'T DO ENUM TYPE CHECKING SINCE OPERATORS IMPLEMENTED AS unsigned compare (not num type compare, for pipelining...)
	'''
	# Use type of driven wire if available
	c_type_str = None
	for driven_wire_name in driven_wire_names:
		if driven_wire_name in existing_logic.wire_to_c_type:
			print "driven_wire_name",driven_wire_name
			type_str = existing_logic.wire_to_c_type[driven_wire_name]
			if not(c_type_str is None):
				if type_str != c_type_str:
					print "Constant driving a wire with multiple types!?"
					sys.exit(0)
			c_type_str = type_str
	if not(c_type_str is None):
		# Check that this enum const exists for this type
		ids = parser_state.enum_to_ids_dict[c_type_str]
		if not(value in ids):
			print "Enum:",value, "is not part of the enum type:", c_type_str,C_AST_COORD_STR(c_ast_node.coord)
			sys.exit(0)	
	'''
	
	parser_state.existing_logic = rv
		 
	return rv
	

# Const jsut makes wire with CONST name
def C_AST_CONSTANT_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state, is_negated=False):
	existing_logic = parser_state.existing_logic
	
	# Since constants are constants... dont add prepend text or line location info
	# Create wire for this constant
	#wire_name = prepend_text+"CONST_" + str(c_ast_node.type)+ "_"+ str(c_ast_node.value) + "_" + C_AST_COORD_STR(c_ast_node.coord)
	#wire_name =  CONST_PREFIX + str(c_ast_node.type)+ "_"+ str(c_ast_node.value)
	value = int(c_ast_node.value)
	if is_negated:
		value = value * -1
	#casthelp(c_ast_node)
	#print "value",value
	#print "==="
	wire_name =  CONST_PREFIX + str(value) + "_" + C_AST_COORD_STR(c_ast_node.coord)
	rv = CONNECT_WIRES_LOGIC(wire_name, driven_wire_names)
	
	rv = rv.MERGE_COMB_LOGIC(existing_logic)
	
	# Use type of driven wire if available
	c_type_str = None
	for driven_wire_name in driven_wire_names:
		if driven_wire_name in existing_logic.wire_to_c_type:
			type_str = existing_logic.wire_to_c_type[driven_wire_name]
			if not(c_type_str is None):
				if type_str != c_type_str:
					print "Constant with multiple types!?"
					sys.exit(0)
			c_type_str = type_str
	if not(c_type_str is None):
		rv.wire_to_c_type[wire_name]=c_type_str		
		
	parser_state.existing_logic = rv
		 
	return rv
	
def C_AST_DECL_TO_LOGIC(c_ast_decl, prepend_text, parser_state):
	existing_logic = parser_state.existing_logic
	
	# Only encountered as variable decl right now
	# All we need is wire name right now
	rv = Logic()
	if not(existing_logic is None):
		rv = rv.MERGE_COMB_LOGIC(existing_logic)
	
	# Dont use prepend text for decl since cant decl twice?
	# TODO check this if it does work and I forget about it
	#prepend_text+
	wire_name = c_ast_decl.name
	#print "DECL", wire_name
	#casthelp(c_ast_decl)
	#casthelp(c_ast_decl.init)
	#sys.exit(0)
	rv.wires.append(wire_name)
	rv.wire_to_c_type[wire_name] = c_ast_decl.type.type.names[0]
	# Orig wire var here too
	rv.wire_to_c_type[c_ast_decl.name] = c_ast_decl.type.type.names[0]
	#print "wire_name",wire_name, rv.wire_to_c_type[wire_name]
	
	# This is a variable declaration
	rv.variable_names.append(wire_name)
	
	# If has init value then is also assignment
	if not(c_ast_decl.init is None):
		print "No variable declarations with intialziations yet..."
		casthelp(c_ast_decl)
		sys.exit(0)
		
	# Update parser state since merged in exsiting logic earlier
	parser_state.existing_logic = rv
	
	return rv

	
def C_AST_COMPOUND_TO_LOGIC(c_ast_compound, prepend_text, parser_state):
	existing_logic = parser_state.existing_logic
	
	# How to handle assignment over time?
	# Use function that merges logic over time
	# MERGE_SEQUENTIAL_LOGIC
	# TODO: Do this every place merge logic is used? probabhly not
	# Assumption: Compound logic block items imply execution order
	rv = Logic()
	if existing_logic is not None:
		rv = rv.MERGE_COMB_LOGIC(existing_logic)
		
	if not(c_ast_compound.block_items is None):
		for block_item in c_ast_compound.block_items:
			#print "block_item in c_ast_compound.block_items"
			#casthelp(block_item)
			#print '"leading_zeros" in rv.wire_to_c_type', ("leading_zeros" in rv.wire_to_c_type)
			#print "block_item",block_item
			parser_state.existing_logic = rv
			driven_wire_names=[]
			item_logic = C_AST_NODE_TO_LOGIC(block_item, driven_wire_names, prepend_text, parser_state)
			prev_logic = rv
			next_logic = item_logic
			
			#print "MERGING block item sequentially"
			#print "PRE SEQ MERGE rv.wire_drives", rv.wire_drives 
			#print "PRE SEQ MERGE rv.wire_driven_by", rv.wire_driven_by 
			
			rv = prev_logic.MERGE_SEQ_LOGIC(next_logic)
			
			# Update parser state since merged in exsiting logic
			parser_state.existing_logic = rv
			
			#print str(block_item)
			#print "rv.wire_drives", rv.wire_drives 
			#print "rv.wire_driven_by", rv.wire_driven_by 
			
		
			
	return rv
	
def C_AST_COORD_STR(c_ast_node_cord):
	c_ast_node_cord
	
	file_coord_str = str(c_ast_node_cord.file) + "_l" + str(c_ast_node_cord.line) + "_c" + str(c_ast_node_cord.column)
	# Get leaf name (just stem file name of file hierarcy)
	file_coord_str = LEAF_NAME(file_coord_str)
	#file_coord_str = file_coord_str.replace(".","_").replace(":","_")
	#file_coord_str = file_coord_str.replace(":","_")
	# Lose readability for sake of having DOTs mean struct ref in wire names
	file_coord_str = file_coord_str.replace(".","_")
	return file_coord_str

	

def C_AST_IF_TO_LOGIC(c_ast_node,prepend_text, parser_state):
	existing_logic = parser_state.existing_logic
	func_name_2_logic = parser_state.FuncName2Logic
	
	# Each if is just an IF ELSE (no explicit logic for "else if")
	# If logic is MUX with SEL, TRUE, and FALSE logic connected
	rv = Logic()
	rv = rv.MERGE_COMB_LOGIC(existing_logic)
		
	# One submodule MUX instance per variable contains in the if at this location
	# Name comes from location in file
	file_coord_str = C_AST_COORD_STR(c_ast_node.coord)
		
	# Helpful check for now
	#if len(c_ast_node.children()) < 3:
	#	print "All ifs must have else statements for now."
	#	sys.exit(0)
	
	# Port names from c_ast
	
	
	
	# Mux select is driven by intermediate shared wire without variable name
	mux_cond_port_name = c_ast_node.children()[0][0]
	mux_intermediate_cond_wire_wo_var_name = prepend_text + MUX_LOGIC_NAME + "_" + file_coord_str + "_interm_" + mux_cond_port_name
	rv.wires.append(mux_intermediate_cond_wire_wo_var_name)
	rv.wire_to_c_type[mux_intermediate_cond_wire_wo_var_name] = BOOL_C_TYPE		
	# Get logic for this if condition with it driving the shared condition wire
	parser_state.existing_logic = rv
	cond_logic = C_AST_NODE_TO_LOGIC(c_ast_node.cond, [mux_intermediate_cond_wire_wo_var_name], prepend_text, parser_state)
	first = rv
	second = cond_logic
	rv = first.MERGE_SEQ_LOGIC(second)
	parser_state.existing_logic = rv
	
	
	# Get true/false logic
	# Add prepend text to seperate the two branches into paralel combinational logic
	# Rename each driven wire with inst name and _true or _false
	prepend_text_true = ""#prepend_text+MUX_LOGIC_NAME+"_"+file_coord_str+"_true"+"/"   # Line numbers should be enough?
	prepend_text_false = ""#prepend_text+MUX_LOGIC_NAME+"_"+file_coord_str+"_false"+"/" # Line numbers should be enough?
	driven_wire_names=[] 
	#
	parser_state_for_true = copy.copy(parser_state)
	parser_state_for_true.existing_logic = rv
	mux_true_port_name = c_ast_node.children()[1][0]
	true_logic = C_AST_NODE_TO_LOGIC(c_ast_node.iftrue, driven_wire_names, prepend_text_true, parser_state_for_true)
	#
	if len(c_ast_node.children()) >= 3:
		# Do false branch
		parser_state_for_false = copy.copy(parser_state)
		parser_state_for_false.existing_logic = rv
		mux_false_port_name = c_ast_node.children()[2][0]
		false_logic = C_AST_NODE_TO_LOGIC(c_ast_node.iffalse, driven_wire_names, prepend_text_false, parser_state_for_false)
	else:
		# No false branch false logic if identical to existing logic
		false_logic = copy.copy(parser_state.existing_logic)
		mux_false_port_name = "iffalse" # Will this work?
	
	# Var names cant be mixed type per C spec
	merge_var_names = LIST_UNION(true_logic.variable_names,false_logic.variable_names)
		
	# Find out which orig_wire names rv, p.x, p.y etc are driven inside this IF
	# Driving is recorded with aliases over time
	# True and false can share some existing drivings we dont want to consider
	# Loop over each variable
	var_name_2_all_if_orig_wire_names = dict()
	#print "==== IF",file_coord_str,"======="
	for var_name in merge_var_names:		
		# vars declared inside and IF cannot be used outside that if so cannot/should not have MUX inputs+outputs
		declared_in_this_if = not(var_name in existing_logic.variable_names) and (var_name not in parser_state.global_info)
		if declared_in_this_if:
			#print var_name, "declared_in_this_if"
			continue
		
		# Get aliases over time
		# original
		original_aliases= []
		if var_name in existing_logic.wire_aliases_over_time:
			original_aliases = existing_logic.wire_aliases_over_time[var_name]
		# true
		true_aliases = []
		if var_name in true_logic.wire_aliases_over_time:
			true_aliases = true_logic.wire_aliases_over_time[var_name]
		# false
		false_aliases = []
		if var_name in  false_logic.wire_aliases_over_time:
			false_aliases = false_logic.wire_aliases_over_time[var_name]
		# Max len
		max_aliases_len = max(len(true_aliases),len(false_aliases))
	
		#print var_name, "original_aliases:", original_aliases
		#print var_name, "true_aliases",true_aliases
		#print var_name, "false_aliases",false_aliases
	
		# Find where the differences start in the wire aliases over time
		diff_start_i = None
		for i in range(0, max_aliases_len):
			# If no element here then difference starts here
			if (i > len(true_aliases)-1) or (i > len(false_aliases)-1):
				diff_start_i = i
				break
			
			# Both have elements, same?
			if true_aliases[i] != false_aliases[i]:
				diff_start_i = i
				break
				
		# If no difference then this var was not driven inside this IF
		if diff_start_i is None:
			#print var_name, "NO DIFFERENT ALIASES = NOT DRIVEN" 
			continue
		
		# Collect all the orig wire names from aliases - whatever order
		all_if_orig_wire_names = []
		for i in range(diff_start_i, max_aliases_len):
			if (i < len(true_aliases)):
				true_orig_wire_name = true_logic.orig_wire_name[true_aliases[i]]
				if true_orig_wire_name not in all_if_orig_wire_names:
					all_if_orig_wire_names.append(true_orig_wire_name)
			if (i < len(false_aliases)):
				false_orig_wire_name = false_logic.orig_wire_name[false_aliases[i]]
				if false_orig_wire_name not in all_if_orig_wire_names:
					all_if_orig_wire_names.append(false_orig_wire_name)
		
		# Collpase hierarchy to get top most orig wire name nodes	
		#print var_name, "original all_if_orig_wire_names",all_if_orig_wire_names
		all_if_orig_wire_names = REDUCE_STRUCTREF_WIRES(all_if_orig_wire_names, parser_state)
		#print var_name, "reduced all_if_orig_wire_names",all_if_orig_wire_names
		# Ok now have collpased list of orig wire names that needed MUXes for this IF
		# Save this for later too
		var_name_2_all_if_orig_wire_names[var_name] = all_if_orig_wire_names[:]
		
		# Now do MUX inst logic		
		for orig_wire_name in all_if_orig_wire_names:
			##### SHARE COND WIRE DRIVEN drives SUBMODULE INST COND PORT
			##### NOT TRUE FALSE SPECIFIC  ######
			# indivudal mux submodule per orig wire
			mux_inst_name = prepend_text+MUX_LOGIC_NAME+"_"+orig_wire_name+"_"+file_coord_str
			# Instance per variable cond port is driven by intermediate wire with var name	
			mux_inst_cond_wire = mux_inst_name + SUBMODULE_MARKER + mux_cond_port_name
			connect_logic = CONNECT_WIRES_LOGIC(mux_intermediate_cond_wire_wo_var_name,[mux_inst_cond_wire])
			connect_logic.wire_to_c_type[mux_inst_cond_wire] = BOOL_C_TYPE
			# Set submodule instance
			# TODO: USE N ARG FUNC INST
			connect_logic.submodule_instances[mux_inst_name]=MUX_LOGIC_NAME
			connect_logic.submodule_instance_to_c_ast_node[mux_inst_name]=c_ast_node
			connect_logic.submodule_instance_to_input_port_names[mux_inst_name]=[mux_cond_port_name,mux_true_port_name,mux_false_port_name]
			# Apply to both branches here?
			true_logic = true_logic.MERGE_COMB_LOGIC(connect_logic)
			false_logic = false_logic.MERGE_COMB_LOGIC(connect_logic)
			
			# Connect true and false wires using id_or_structref read logic
			mux_true_connection_wire_name = mux_inst_name + SUBMODULE_MARKER + mux_true_port_name
			mux_false_connection_wire_name = mux_inst_name + SUBMODULE_MARKER + mux_false_port_name
			
			# Type of true and false ports are the same
			orig_wire_name_c_type = ORIG_WIRE_NAME_TO_C_TYPE(orig_wire_name, parser_state)
		
			# Add C type for input ports based on connecting wire
			true_logic.wire_to_c_type[mux_true_connection_wire_name]=orig_wire_name_c_type
			false_logic.wire_to_c_type[mux_false_connection_wire_name]=orig_wire_name_c_type
					
			# Using each branches logic use id_or_structref logic to form read wire driving T/F ports
			# TRUE
			parser_state_for_true = copy.copy(parser_state)
			parser_state_for_true.existing_logic = true_logic
			true_read_logic = READ_ORIG_WIRE_LOGIC(orig_wire_name, [mux_true_connection_wire_name], c_ast_node, "TRUE_INPUT_MUX_", parser_state_for_true)
			# Merge in read
			true_logic = true_logic.MERGE_COMB_LOGIC(true_read_logic)
			
			# FALSE
			parser_state_for_false = copy.copy(parser_state)
			parser_state_for_false.existing_logic = false_logic
			false_read_logic = READ_ORIG_WIRE_LOGIC(orig_wire_name, [mux_false_connection_wire_name], c_ast_node, "FALSE_INPUT_MUX_", parser_state_for_false)
			# Merge in read
			false_logic = false_logic.MERGE_COMB_LOGIC(false_read_logic)
			
			# Cant handle outputs here since outputs are added as last alias
			# But can add alias to single list yet since havent merged true and false
			# So merge TF first
			
	
	
	# Merge T/F branches
	# Wire aliases over time from the true and false branches CANT be merged  
	# since selection of final alias from either true or false branch is what THIS MUX DOES
	# Loop over and remove branch-only aliases over time
	# RV contains logic before T/F logic so orig aliases
	new_true_false_logic_wire_aliases_over_time = dict()
	for orig_var in merge_var_names:		
		# Filtered aliases contains orig from RV logic
		filtered_aliases = []
		original_aliases = []
		if orig_var in rv.wire_aliases_over_time:
			original_aliases = rv.wire_aliases_over_time[orig_var]
		filtered_aliases += original_aliases
			
		# Remove aliases not in original
		if orig_var in true_logic.wire_aliases_over_time:
			for alias in true_logic.wire_aliases_over_time[orig_var]:
				if alias in original_aliases:
					# Is in orig, keep if not in list already
					if not(alias in filtered_aliases):
						filtered_aliases.append(alias)
				
		if orig_var in false_logic.wire_aliases_over_time:
			for alias in false_logic.wire_aliases_over_time[orig_var]:
				if alias in original_aliases:
					# Is in orig, keep if not in list already
					if not(alias in filtered_aliases):
						filtered_aliases.append(alias)
			
		if len(filtered_aliases) > 0:
			new_true_false_logic_wire_aliases_over_time[orig_var] = filtered_aliases
						
	# Shared comb mergeable wire alaises over time
	true_logic.wire_aliases_over_time = new_true_false_logic_wire_aliases_over_time
	false_logic.wire_aliases_over_time = new_true_false_logic_wire_aliases_over_time
	# Merge the true and false logic as parallel COMB logic since aliases over time fixed above
	true_false_merged = true_logic.MERGE_COMB_LOGIC(false_logic)
	
	
	

	# After TF merge we can have correct alias list include the mux output
	# Alias list for struct variable may be appended to multiple times
	# But since by def those drivings dont overlap then order doesnt really matter
	for variable in merge_var_names:
		# vars declared inside and IF cannot be used outside that if so cannot/should not have MUX inputs+outputs
		declared_in_this_if = not(variable in existing_logic.variable_names) and (variable not in parser_state.global_info)
		if declared_in_this_if:
			continue
			
		# If not driven then skip
		if variable not in var_name_2_all_if_orig_wire_names:
			continue
		# Otherwise get drive orig wire names (already collapsed)
		all_if_orig_wire_names = var_name_2_all_if_orig_wire_names[variable]
		
		# Add mux output as alias for this var
		aliases = []
		if variable in true_false_merged.wire_aliases_over_time:
			aliases = true_false_merged.wire_aliases_over_time[variable]
			# Remove and re add after
			true_false_merged.wire_aliases_over_time.pop(variable)
		
		# Ok to add to same list multiple times for each orig_wire
		for orig_wire_name in all_if_orig_wire_names:
			mux_inst_name = prepend_text+MUX_LOGIC_NAME+"_"+orig_wire_name+"_"+file_coord_str
			mux_connection_wire_name = mux_inst_name + SUBMODULE_MARKER + RETURN_WIRE_NAME
			true_false_merged.orig_var_name[mux_connection_wire_name] = variable
			true_false_merged.orig_wire_name[mux_connection_wire_name] = orig_wire_name
			# set the C type for output connection based on orig var name
			true_false_merged.wire_to_c_type[mux_connection_wire_name] = ORIG_WIRE_NAME_TO_C_TYPE(orig_wire_name, parser_state)
			# Mux output just adds an alias over time to the original variable
			# So that the next read of the variable uses the mux output
			if not(mux_connection_wire_name in aliases):
				aliases.append(mux_connection_wire_name)
		
		# Re add if not empty list
		if len(aliases) > 0:
			true_false_merged.wire_aliases_over_time[variable] = aliases

	
	# Update parser state since merged in exsiting logic earlier
	parser_state.existing_logic = true_false_merged
	
	return true_false_merged
	

	
def LEAF_NAME(name, do_submodule_split=False):
	new_name = name
	
	# Pick last submodule item 
	if (SUBMODULE_MARKER in name) and do_submodule_split:
		toks = new_name.split(SUBMODULE_MARKER)
		toks.reverse()
		new_name = toks[0]	
	
	# And last leaf item
	if "/" in new_name:
		toks = new_name.split("/")
		toks.reverse()
		new_name = toks[0]
		
	return new_name

# Function instance is module connection
# Connect certain input nodes to certain lists of wire names
# dict[c_ast_node] => [list of driven wire names]
def SEQ_C_AST_NODES_TO_LOGIC(c_ast_node_2_driven_wire_names, prepend_text, parser_state):
	rv = Logic()
	rv = rv.MERGE_COMB_LOGIC(parser_state.existing_logic)

	# Get logic for each connection and merge
	for c_ast_node in c_ast_node_2_driven_wire_names:
		driven_wire_names = c_ast_node_2_driven_wire_names[c_ast_node]
		#rv.wires = rv.wires + driven_wire_names
		parser_state.existing_logic = rv
		l = C_AST_NODE_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state)
		first = rv
		second = l
		rv = first.MERGE_SEQ_LOGIC(second)
		parser_state.existing_logic = rv		
	
	return rv

# ORDER OF ARGS MATTERS
def C_AST_N_ARG_FUNC_INST_TO_LOGIC(func_name, c_ast_node_2_driven_input_wire_names, output_wire_name, output_wire_driven_wire_names, prepend_text, func_c_ast_node, parser_state, use_input_nodes_fuck_it=True):
	func_name_2_logic = parser_state.FuncName2Logic
	existing_logic = parser_state.existing_logic
	rv = Logic()
	rv = existing_logic.MERGE_COMB_LOGIC(rv)
	func_inst_name = BUILD_INST_NAME(prepend_text,func_name, func_c_ast_node)
	# Sub module inst
	rv.submodule_instances[func_inst_name] = func_name
	# C ast node
	rv.submodule_instance_to_c_ast_node[func_inst_name]=func_c_ast_node
	
	if use_input_nodes_fuck_it:
		# Inputs
		#print "c_ast_node_2_driven_input_wire_names",c_ast_node_2_driven_input_wire_names
		# The order of evaluation of the postfix expression and the argument expression list is unspecified.
		#  ... All arguments are evaluated. Order not defined (as per standard). But all implementations of C/C++ (that I know of) evaluate function arguments from right to left. <<<<<<<<<<<<<<<<TTODO: Fix me? baaaaaaaaahhh
		parser_state.existing_logic = rv
		in_logic = SEQ_C_AST_NODES_TO_LOGIC(c_ast_node_2_driven_input_wire_names, prepend_text, parser_state)
		rv = in_logic.MERGE_COMB_LOGIC(rv)		
	else:
		# The nodes are jsut the connections driving wire names, loop doing CONNECT_WIRES_LOGIC
		for driving_wire in c_ast_node_2_driven_input_wire_names:
			driven_input_port_wires = c_ast_node_2_driven_input_wire_names[driving_wire]
			# Assume only one for now
			if len(driven_input_port_wires) != 1:
				print driven_input_port_wires
				assert len(driven_input_port_wires) == 1
			driven_input_port_wire = driven_input_port_wires[0]
			if type(driving_wire) == type(driven_input_port_wire): #Both must be wires
				connect_logic = CONNECT_WIRES_LOGIC(driving_wire,[driven_input_port_wire])
				rv = connect_logic.MERGE_COMB_LOGIC(rv)
				
	# Get list of input port names in order
	input_port_names = []
	for thing in c_ast_node_2_driven_input_wire_names:
		driven_input_port_wires = c_ast_node_2_driven_input_wire_names[thing]
		assert len(driven_input_port_wires) == 1
		driven_input_port_wire = driven_input_port_wires[0]
		# Get last leaf
		toks = driven_input_port_wire.split(SUBMODULE_MARKER)
		last_tok = toks[len(toks)-1]
		input_port_names.append(last_tok)
	rv.submodule_instance_to_input_port_names[func_inst_name] = input_port_names[:]
	
	# IF use_input_nodes_fuck_it the keys are all fucked, their jsut strings
	for c_ast_node in c_ast_node_2_driven_input_wire_names:
		driven_input_wire_names = c_ast_node_2_driven_input_wire_names[c_ast_node]
		for driven_input_wire_name in driven_input_wire_names:
			# Get type for inputs based on func_name if possible
			if func_name in func_name_2_logic:
				func_def_logic_object = func_name_2_logic[func_name]
				# Get port name from driven wire
				toks = driven_input_wire_name.split(SUBMODULE_MARKER)
				port_name = toks[len(toks)-1]
				driving_wire_c_type = func_def_logic_object.wire_to_c_type[port_name]
				if driven_input_wire_name not in rv.wire_to_c_type:
					rv.wire_to_c_type[driven_input_wire_name] = driving_wire_c_type
			else:
				# Set type for this wire by type of wire that drives this
				driving_wire = rv.wire_driven_by[driven_input_wire_name]
				# Type of driving wire
				driving_wire_c_type = rv.wire_to_c_type[driving_wire]
				if driven_input_wire_name not in rv.wire_to_c_type:
					rv.wire_to_c_type[driven_input_wire_name] = driving_wire_c_type
			
	# Set type for outputs based on func_name if possible
	if func_name in func_name_2_logic:
		func_def_logic_object = func_name_2_logic[func_name]
		# Get type of output
		output_type = func_def_logic_object.wire_to_c_type[RETURN_WIRE_NAME]
		# Set this type for the output if not set already? # This seems really hacky
		for output_wire_driven_wire_name in output_wire_driven_wire_names:
			if(not(output_wire_driven_wire_name in rv.wire_to_c_type)):
				rv.wire_to_c_type[output_wire_driven_wire_name] = output_type
	
	
	# Raw vhdl stuff shouldnt use globals right?
	# So assign using globals based on func name to logic entry
	if func_name in func_name_2_logic:
		func_logic = func_name_2_logic[func_name]
		rv.uses_globals = rv.uses_globals or func_logic.uses_globals	
	
	
	#print "C_AST_N_ARG_FUNC_INST_TO_LOGIC rv.wires",rv.wires
	# Outputs
	# Finally connect the output of DO_THROUGHPUT_SWEEPthis operation to each of the driven wires
	out_logic = CONNECT_WIRES_LOGIC(output_wire_name, output_wire_driven_wire_names)	
	rv = out_logic.MERGE_COMB_LOGIC(rv)
	
	# Update parser state since merged in exsiting logic earlier
	parser_state.existing_logic = rv

	
	#print "C_AST_N_ARG_FUNC_INST rv.wire_driven_by", rv.wire_driven_by
	
	return rv	
	
def BUILD_INST_NAME(prepend_text,func_name, c_ast_node):
	file_coord_str = C_AST_COORD_STR(c_ast_node.coord)
	inst_name = prepend_text+ func_name + "[" + file_coord_str + "]"
	return inst_name
def C_AST_FUNC_CALL_TO_LOGIC(c_ast_func_call,driven_wire_names,prepend_text,parser_state):
	func_name_2_logic = parser_state.FuncName2Logic
	func_name = str(c_ast_func_call.name.name)
	file_coord_str = C_AST_COORD_STR(c_ast_func_call.coord)
	func_inst_name = BUILD_INST_NAME(prepend_text,func_name, c_ast_func_call)
	if not(func_name in func_name_2_logic):
		print "C_AST_FUNC_CALL_TO_LOGIC Havent parsed func name '", func_name, "' yet. Where does that function come from?"
		print c_ast_func_call.coord
		sys.exit(0)
	not_inst_func_logic = func_name_2_logic[func_name]
		
	# N input port names named by their arg name
	# Decompose inputs to N ARG FUNCTION
	# dict[c_ast_input_node] => [list of driven wire names]
	c_ast_node_2_driven_input_wire_names = OrderedDict()
	
	# Helpful check
	if len(c_ast_func_call.args.exprs) != len(not_inst_func_logic.inputs): #<
		print "The function definition for",func_name,"has",len(c_ast_func_call.args.exprs), "arguments."
		print "as used at", c_ast_func_call.coord, "it has", len(not_inst_func_logic.inputs), "arguments."
		sys.exit(0)
	
	# Assume inputs are in arg order
	for i in range(0, len(not_inst_func_logic.inputs)):
		input_port_name = not_inst_func_logic.inputs[i]
		input_port_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
		input_c_ast_node = c_ast_func_call.args.exprs[i]
		c_ast_node_2_driven_input_wire_names[input_c_ast_node] = [input_port_wire]
		
	# Output is type of logic not_inst_func_logic output wire
	if len(not_inst_func_logic.outputs) != 1:
		print "Whats going on here multiple outputs??"
		sys.exit(0)
	output_port_name = not_inst_func_logic.outputs[0]
	output_c_type = not_inst_func_logic.wire_to_c_type[output_port_name]
	output_wire = func_inst_name+SUBMODULE_MARKER+output_port_name
	parser_state.existing_logic.wire_to_c_type[output_wire] = output_c_type
	
	# Before evaluating input nodes make sure type of port is there so constants can be evaluated
	# Get types from func defs
	func_def_logic_object = func_name_2_logic[func_name]
	for input_port in func_def_logic_object.inputs:
		input_port_wire = func_inst_name + SUBMODULE_MARKER + input_port
		parser_state.existing_logic.wire_to_c_type[input_port_wire] = func_def_logic_object.wire_to_c_type[input_port]	

	# Decompose inputs to N ARG FUNCTION
	func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(func_name, c_ast_node_2_driven_input_wire_names, output_wire, driven_wire_names,prepend_text,c_ast_func_call,parser_state)	
	
	#print "func_logic.inst_name",func_logic.inst_name
	
	# Save c ast node of binary op
	
	if not(output_wire in func_logic.wire_to_c_type):
		print "444444444444   output_wire in func_logic.wire_to_c_type", bin_op_output in func_logic.wire_to_c_type
		sys.exit(0)
		
	parser_state.existing_logic = func_logic
		
	
	return func_logic
	
def C_AST_UNARY_OP_TO_LOGIC(c_ast_unary_op,driven_wire_names, prepend_text, parser_state):
	existing_logic = parser_state.existing_logic
	# Decompose to C_AST_N_ARG_FUNC_INST_TO_LOGIC
	c_ast_unary_op_str = str(c_ast_unary_op.op)
	
	# Is this UNARY op negating a constant?
	if (c_ast_unary_op_str=="-") and (type(c_ast_unary_op.expr) == c_ast.Constant):
		# THis is just a constant wire with negative value
		return C_AST_CONSTANT_TO_LOGIC(c_ast_unary_op.expr,driven_wire_names, prepend_text, parser_state, is_negated=True)
	
	# Determine op string to use in func name
	if c_ast_unary_op_str == "!":
		c_ast_op_str = UNARY_OP_NOT_NAME
	else:
		print "UNARY_OP name for c_ast_unary_op_str '" + c_ast_unary_op_str + "'?"
		sys.exit(0)
		
	# Set port names based on func name
	func_name = UNARY_OP_LOGIC_NAME_PREFIX + "_" + c_ast_op_str
	
	file_coord_str = C_AST_COORD_STR(c_ast_unary_op.coord)
	func_inst_name = BUILD_INST_NAME(prepend_text,func_name, c_ast_unary_op)
		
	unary_op_input_port_name = c_ast_unary_op.children()[0][0]
	unary_op_input = func_inst_name+SUBMODULE_MARKER+unary_op_input_port_name
	unary_op_output=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
	
	# Determine output type based on operator or driving wire type
	driven_c_type_str = GET_C_TYPE_FROM_WIRE_NAMES(driven_wire_names, parser_state.existing_logic, allow_fail=True)
	if driven_c_type_str is not None:
		# Most unary ops use the type of the driven wire
		if c_ast_unary_op_str == "!":
			output_c_type = driven_c_type_str
		else:
			print "Output C type for c_ast_unary_op_str '" + c_ast_unary_op_str + "'?"
			sys.exit(0)	
		# Set type for output wire
		parser_state.existing_logic.wire_to_c_type[unary_op_output] = output_c_type
	
	
	# Inputs
	# Decompose inputs to N ARG FUNCTION
	# dict[c_ast_input_node] => [list of driven wire names]
	c_ast_node_2_driven_input_wire_names = OrderedDict()
	c_ast_node_2_driven_input_wire_names[c_ast_unary_op.expr] = [unary_op_input]
	
	# Before evaluating input nodes make sure type of port is there so constants can be evaluated
	# Input must be non const or wtf guys
	in_logic = SEQ_C_AST_NODES_TO_LOGIC(c_ast_node_2_driven_input_wire_names, prepend_text, parser_state)
	if unary_op_input in in_logic.wire_to_c_type:
		input_type = in_logic.wire_to_c_type[unary_op_input]
	else:
		print func_inst_name, "looks like a constant unary op, what's going on?"
		print "in_logic.wire_to_c_type"
		print in_logic.wire_to_c_type
		sys.exit(0)
		
	in_logic.wire_to_c_type[unary_op_input] = input_type
	if unary_op_output not in in_logic.wire_to_c_type:
		in_logic.wire_to_c_type[unary_op_output] = input_type
	
	# In logic exists before funciton
	parser_state.existing_logic = in_logic
	
	
	func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(func_name, c_ast_node_2_driven_input_wire_names, unary_op_output,  driven_wire_names,prepend_text,c_ast_unary_op, parser_state)	

	parser_state.existing_logic = func_logic
	

	return func_logic

def C_AST_BINARY_OP_TO_LOGIC(c_ast_binary_op,driven_wire_names,prepend_text, parser_state):
	# Decompose to C_AST_N_ARG_FUNC_INST_TO_LOGIC
	c_ast_bin_op_str = str(c_ast_binary_op.op)
	
	# Determine op string to use in func name
	if c_ast_bin_op_str == ">":
		c_ast_op_str = BIN_OP_GT_NAME
	elif c_ast_bin_op_str == ">=":
		c_ast_op_str = BIN_OP_GTE_NAME
	elif c_ast_bin_op_str == "<":
		c_ast_op_str = BIN_OP_LT_NAME
	elif c_ast_bin_op_str == "<=":
		c_ast_op_str = BIN_OP_LTE_NAME
	elif c_ast_bin_op_str == "+":
		c_ast_op_str = BIN_OP_PLUS_NAME
	elif c_ast_bin_op_str == "-":
		c_ast_op_str = BIN_OP_MINUS_NAME
	elif c_ast_bin_op_str == "*":
		c_ast_op_str = BIN_OP_MULT_NAME
	elif c_ast_bin_op_str == "/":
		c_ast_op_str = BIN_OP_DIV_NAME
	elif c_ast_bin_op_str == "==":
		c_ast_op_str = BIN_OP_EQ_NAME
	elif c_ast_bin_op_str == "&":
		c_ast_op_str = BIN_OP_AND_NAME
	elif c_ast_bin_op_str == "|":
		c_ast_op_str = BIN_OP_OR_NAME
	elif c_ast_bin_op_str == "^":
		c_ast_op_str = BIN_OP_XOR_NAME
	elif c_ast_bin_op_str == "<<":
		c_ast_op_str = BIN_OP_SL_NAME
	elif c_ast_bin_op_str == ">>":
		c_ast_op_str = BIN_OP_SR_NAME
	else:
		print "BIN_OP name for c_ast_bin_op_str '" + c_ast_bin_op_str + "'?"
		sys.exit(0)
		
	# Set port names based on func name
	func_name = BIN_OP_LOGIC_NAME_PREFIX + "_" + c_ast_op_str
	
	file_coord_str = C_AST_COORD_STR(c_ast_binary_op.coord)
	func_inst_name = BUILD_INST_NAME(prepend_text,func_name, c_ast_binary_op)
		
	bin_op_left_input_port_name = c_ast_binary_op.children()[0][0]
	bin_op_right_input_port_name = c_ast_binary_op.children()[1][0]
	
	bin_op_left_input = func_inst_name+SUBMODULE_MARKER+bin_op_left_input_port_name
	bin_op_right_input = func_inst_name+SUBMODULE_MARKER+bin_op_right_input_port_name
	bin_op_output=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
	
	# Determine output type based on operator or driving wire type
	driven_c_type_str = GET_C_TYPE_FROM_WIRE_NAMES(driven_wire_names, parser_state.existing_logic)
	# Most binary ops use the type of the driven wire
	
	if c_ast_bin_op_str == ">":
		output_c_type = BOOL_C_TYPE
	elif c_ast_bin_op_str == ">=":
		output_c_type = BOOL_C_TYPE
	elif c_ast_bin_op_str == "<":
		output_c_type = BOOL_C_TYPE
	elif c_ast_bin_op_str == "<=":
		output_c_type = BOOL_C_TYPE
	elif c_ast_bin_op_str == "==":
		output_c_type = BOOL_C_TYPE
	elif c_ast_bin_op_str == "+":
		output_c_type = driven_c_type_str
	elif c_ast_bin_op_str == "-":
		output_c_type = driven_c_type_str
	elif c_ast_bin_op_str == "*":
		output_c_type = driven_c_type_str
	elif c_ast_bin_op_str == "/":
		output_c_type = driven_c_type_str
	elif c_ast_bin_op_str == "&":
		output_c_type = driven_c_type_str
	elif c_ast_bin_op_str == "|":
		output_c_type = driven_c_type_str
	elif c_ast_bin_op_str == "^":
		output_c_type = driven_c_type_str
	elif c_ast_bin_op_str == "<<":
		output_c_type = driven_c_type_str
	elif c_ast_bin_op_str == ">>":
		output_c_type = driven_c_type_str
	else:
		print "Output C type for '" + c_ast_bin_op_str + "'?"
		sys.exit(0)
	
	
	# Set type for output wire
	parser_state.existing_logic.wire_to_c_type[bin_op_output] = output_c_type
	#print " ----- ", bin_op_output, output_c_type
	
	rv = Logic()
	rv = rv.MERGE_COMB_LOGIC(parser_state.existing_logic)
	
	
	# Inputs
	# Decompose inputs to N ARG FUNCTION
	# dict[c_ast_input_node] => [list of driven wire names]
	c_ast_node_2_driven_input_wire_names = OrderedDict()
	c_ast_node_2_driven_input_wire_names[c_ast_binary_op.left] = [bin_op_left_input]
	c_ast_node_2_driven_input_wire_names[c_ast_binary_op.right] = [bin_op_right_input]
	
	# FIRST PROCESS THE INPUT CONNECTIONS ALONE
	in_logic = SEQ_C_AST_NODES_TO_LOGIC(c_ast_node_2_driven_input_wire_names, prepend_text, parser_state)
	parser_state.existing_logic = parser_state.existing_logic.MERGE_COMB_LOGIC(in_logic)
	left_type = None
	# Was either input type evaluated?
	if bin_op_left_input in in_logic.wire_to_c_type:
		left_type = in_logic.wire_to_c_type[bin_op_left_input]
	right_type = None
	if bin_op_right_input in in_logic.wire_to_c_type:
		right_type = in_logic.wire_to_c_type[bin_op_right_input]
	# Which ones to use?
	if (left_type is None) and (right_type is None):
		print func_inst_name, "doesn't have type information for either input? What's going on?"
		print "in_logic.wire_to_c_type"
		print "bin_op_left_input",bin_op_left_input
		print "bin_op_right_input",bin_op_right_input
		print "Know types:"
		print in_logic.wire_to_c_type
		sys.exit(0)
	elif not(left_type is None) and (right_type is None):
		# Use left
		parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
		parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = left_type
	elif (left_type is None) and not(right_type is None):
		# Use Right
		parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = right_type
		parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type
	else:
		# Different types set for each input
		parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
		parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type
		
	#print "left_type",left_type
	#print "right_type",right_type
		
	# Replace ENUM with INT type of input wire so cast happens? :/?
	# Left
	if parser_state.existing_logic.wire_to_c_type[bin_op_left_input] in parser_state.enum_to_ids_dict:
		#print "left enum"
		# Set BIN OP input wire as UINT
		enum_type = parser_state.existing_logic.wire_to_c_type[bin_op_left_input]
		num_ids = len(parser_state.enum_to_ids_dict[enum_type])
		left_width = int(math.ceil(math.log(num_ids,2)))
		parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = "uint" + str(left_width) + "_t"
		# Set driver of input as ENUM
		driving_wire = parser_state.existing_logic.wire_driven_by[bin_op_left_input]
		parser_state.existing_logic.wire_to_c_type[driving_wire] = enum_type
		#print "driving_wire",driving_wire,enum_type
		
	# Right
	if parser_state.existing_logic.wire_to_c_type[bin_op_right_input] in parser_state.enum_to_ids_dict:
		# Set BIN OP input wire as UINT
		enum_type = parser_state.existing_logic.wire_to_c_type[bin_op_right_input]
		num_ids = len(parser_state.enum_to_ids_dict[enum_type])
		right_width = int(math.ceil(math.log(num_ids,2)))
		parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = "uint" + str(right_width) + "_t"
		# Set driver of input as ENUM
		driving_wire = parser_state.existing_logic.wire_driven_by[bin_op_right_input]
		parser_state.existing_logic.wire_to_c_type[driving_wire] = enum_type
		#print "driving_wire",driving_wire,enum_type
	
	#print "parser_state.existing_logic.wire_to_c_type[bin_op_left_input]",parser_state.existing_logic.wire_to_c_type[bin_op_left_input]
	#print "parser_state.existing_logic.wire_to_c_type[bin_op_right_input]",parser_state.existing_logic.wire_to_c_type[bin_op_right_input]
	
	
	func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(func_name, c_ast_node_2_driven_input_wire_names, bin_op_output, driven_wire_names,prepend_text,c_ast_binary_op, parser_state)	
	
	# Save c ast node of binary op
	
	
	parser_state.existing_logic = func_logic
	#print "AFTER:"
	#print "parser_state.existing_logic.wire_to_c_type[bin_op_left_input]",parser_state.existing_logic.wire_to_c_type[bin_op_left_input]
	#print "parser_state.existing_logic.wire_to_c_type[bin_op_right_input]",parser_state.existing_logic.wire_to_c_type[bin_op_right_input]
	return func_logic

	
def GET_C_TYPE_FROM_WIRE_NAMES(wire_names, logic, allow_fail=False):
	rv = None
	for wire_name in wire_names:
		if not(wire_name in logic.wire_to_c_type):
			if allow_fail:
				return None
			else:
				print "Cant GET_C_TYPE_FROM_WIRE_NAMES since", wire_name,"not in logic.wire_to_c_type"
				print "logic.wire_to_c_type",logic.wire_to_c_type
				print 0/0
				sys.exit(0)
		c_type_str = logic.wire_to_c_type[wire_name]
		if rv is None:
			rv = c_type_str
		else:
			if rv != c_type_str:
				print "GET_C_TYPE_FROM_WIRE_NAMES multilpe types?"
				print "wire_name",wire_name
				print rv, c_type_str
				print 0/0
				sys.exit(0)
			
	return rv

# Return None if wire is not driven by const (or anything)
def FIND_CONST_DRIVING_WIRE(wire, logic):
	if WIRE_IS_CONSTANT(wire,logic.inst_name):
		return wire
	else:
		if wire in logic.wire_driven_by:
			driving_wire = logic.wire_driven_by[wire]
			return FIND_CONST_DRIVING_WIRE(driving_wire, logic)
		else:
			return None		

def CONNECT_WIRES_LOGIC(driving_wire, driven_wire_names):
	rv = Logic()
	rv.wires = [driving_wire] + driven_wire_names
	rv.wire_drives[driving_wire] = driven_wire_names
	for driven_wire_name in driven_wire_names:
		rv.wire_driven_by[driven_wire_name] = driving_wire
	return rv	
	
# int x[2]     returns "int", 2
# int x[2][2]  returns "int[2]", 2
def C_AST_ARRAYDECL_TO_ELEM_TYPE_AND_DIM(array_decl):
	#casthelp(array_decl)
	#print 
	#sys.exit(0)
	
	# Will be N nested ArrayDecls with dimensions folowed by the element type
	children = array_decl.children()
	dims = []
	while len(children)>1 and children[1][0]=='dim':
		# Get the dimension
		dim = int(children[1][1].value)
		dims.append(dim)
		array_decl = children[0][1]
		children = array_decl.children()
		
	# Reverse order from parsing
	#dims = dims[::-1]
	
	# Get base type
	# Array decl is now holding the inner type
	type_decl = array_decl
	type_name = type_decl.type.names[0]
	#casthelp(type_decl)
	#print "type_name",type_name
	
	 
	
	# Append everything but last dim
	elem_type = type_name
	for dim_i in range(0, len(dims)-1):
		elem_type = elem_type + "[" + str(dims[dim_i]) + "]"
	
	dim = dims[len(dims)-1]
	#print elem_type
	#print dim
	#sys.exit(0)
	return elem_type,dim
	
	
	
def C_AST_PARAM_DECL_TO_C_TYPE(param_decl):
	# Need to get array type differently 
	if type(param_decl.type) == c_ast.ArrayDecl:
		elem_type, dim = C_AST_ARRAYDECL_TO_ELEM_TYPE_AND_DIM(param_decl.type)
		array_type = elem_type + "[" + str(dim) + "]"
		#print "array_type",array_type
		return array_type			
	else:
		# Non array decl
		#print "Non array decl", param_decl
		return param_decl.type.type.names[0]
	
def C_AST_FUNC_DEF_TO_LOGIC(c_ast_funcdef, parser_state, parse_body = True):
	rv = Logic()
	# Save the c_ast node
	rv.c_ast_node = c_ast_funcdef
	
	# All func def logic has an output wire called "return"
	return_wire_name = RETURN_WIRE_NAME
	rv.outputs.append(return_wire_name)
	rv.wires.append(return_wire_name)
	rv.wire_to_c_type[return_wire_name] = c_ast_funcdef.decl.type.type.type.names[0]

	# First get name of function from the declaration
	rv.func_name = c_ast_funcdef.decl.name
	
	# Then get input wire names from the function def
	for param_decl in c_ast_funcdef.decl.type.args.params:
		input_wire_name = param_decl.name
		rv.inputs.append(input_wire_name)
		rv.wires.append(input_wire_name)
		c_type = C_AST_PARAM_DECL_TO_C_TYPE(param_decl)
		rv.wire_to_c_type[input_wire_name] = c_type
	
	# Merge with logic from the body of the func def
	existing_logic=rv
	driven_wire_names=[]
	prepend_text=""
	if parse_body:
		parser_state.existing_logic = rv
		body_logic = C_AST_NODE_TO_LOGIC(c_ast_funcdef.body, driven_wire_names, prepend_text, parser_state)
		rv = body_logic.MERGE_COMB_LOGIC(rv)
				
	# Sanity check for return
	if RETURN_WIRE_NAME not in rv.wire_driven_by and not SW_LIB.IS_AUTO_GENERATED(rv):
		print "No return statement in function:", rv.func_name
		sys.exit(0)
	
	return rv

def RECURSIVE_GET_ALL_SUBMODULE_INSTANCES(main_logic, LogicInstLookupTable):
	all_submodule_instances = []
	for submodule_inst in main_logic.submodule_instances:
		all_submodule_instances.append(submodule_inst)
		if submodule_inst in LogicInstLookupTable:
			submodule_logic = LogicInstLookupTable[submodule_inst]
			all_sub_submodule_instances = RECURSIVE_GET_ALL_SUBMODULE_INSTANCES(submodule_logic, LogicInstLookupTable)
			all_submodule_instances = all_submodule_instances + all_sub_submodule_instances
	
	#print "all_submodule_instances",all_submodule_instances
	return all_submodule_instances

def GET_LOGIC_INST_LOOKUP_CACHE_FILEPATH(Logic):
	key = Logic.inst_name
	key = key.replace("/","_");
	output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic, implement=False)
	filepath = output_directory + "/" + key + ".logic"
	return filepath

def WRITE_LOGIC_INST_LOOKUP_CACHE(Logic, logic_lookup_table):
	filepath = GET_LOGIC_INST_LOOKUP_CACHE_FILEPATH(Logic)
	output_directory = SYN.GET_OUTPUT_DIRECTORY(Logic, implement=False)
	# Write dir first if needed
	if not os.path.exists(output_directory):
		os.makedirs(output_directory)
		
	# Write file
	with open(filepath, 'w') as output:
		pickle.dump(logic_lookup_table, output, pickle.HIGHEST_PROTOCOL)

def GET_CACHED_LOGIC_INST_LOOKUP(Logic):
	filepath = GET_LOGIC_INST_LOOKUP_CACHE_FILEPATH(Logic)
	if os.path.exists(filepath):
		with open(filepath, 'rb') as input:
			logic_lookup_table = pickle.load(input)
			return logic_lookup_table
	return None	

def GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(logic, submodule_inst_name, input_port_name):
	#print "logic.func_name", logic.func_name
	name = input_port_name #  submodule_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + input_port_name
	#print " logic.wire_driven_by"
	#print logic.wire_driven_by
	driving_wire = logic.wire_driven_by[name]
	return driving_wire
	
def PRINT_DRIVER_WIRE_TRACE(start, logic, wires_driven_so_far=None):
	text = ""
	while not(start is None):
		if wires_driven_so_far is None:
			text += start + " <= "
		else:
			text += start + "(driven? " +  str(start in wires_driven_so_far) + ") <= "
			
		if start in logic.wire_driven_by:
			start = logic.wire_driven_by[start]
		else:
			text += "has no driver!!!!?"
			start = None
	print text
	return start

def GET_CONTAINER_LOGIC_FOR_SUBMODULE_INST(submodule_inst, LogicInstLookupTable):
	rv = None
	submodule_logic = LogicInstLookupTable[submodule_inst]
	if submodule_logic.containing_inst in LogicInstLookupTable:
		containing_logic = LogicInstLookupTable[submodule_logic.containing_inst]
		rv = containing_logic
	return rv
	
	
	
# This class hold all the state obtained by parsing a single C file
class ParserState:
	def __init__(self):
		self.FuncName2Logic=dict() #dict[func_name]=Logic() instance with just func info
		self.LogicInstLookupTable=dict() #dict[inst_name]=Logic() instance in full
		#self.RawHdlLogic = None
		self.existing_logic = None # Temp working copy of logic ? idk it should work
		self.struct_to_field_type_dict = dict()
		self.enum_to_ids_dict = dict()
		self.global_info = dict()
		self.global_mhz_limit = None
	
# Returns ParserState
def PARSE_FILE(top_level_func_name, c_file):
	# Catch pycparser exceptions
	try:
		parser_state = ParserState()
		print "Parsing PipelinedC code..."
		# Get SW existing logic for this c file
		parser_state.FuncName2Logic = SW_LIB.GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP(c_file, parser_state)
		# Get the parsed struct def info
		parser_state.struct_to_field_type_dict = GET_STRUCT_FIELD_TYPE_DICT(c_file)
		# Get the parsed enum info
		parser_state.enum_to_ids_dict = GET_ENUM_IDS_DICT(c_file)
		#print "parser_state.struct_to_field_type_dict",parser_state.struct_to_field_type_dict
		# Get global variable info
		parser_state = GET_GLOBAL_INFO(parser_state, c_file)
		# Get the function definitions
		parser_state.FuncName2Logic = GET_FUNC_NAME_LOGIC_LOOKUP_TABLE([c_file], parser_state)
		
		# cHECK FOR EXPECTED FUNC NAME
		if top_level_func_name not in parser_state.FuncName2Logic:
			print "There doesnt seem to be as function called '", top_level_func_name,"' in the file '",c_file,"'"
			sys.exit(0)
			
		# Check for double use of globals the dumb way to print useful info
		for func_name1 in parser_state.FuncName2Logic:
			func1_logic = parser_state.FuncName2Logic[func_name1]
			for func_name2 in parser_state.FuncName2Logic:
				if func_name2 == func_name1:
					continue
				func2_logic = parser_state.FuncName2Logic[func_name2]
				for func1_global in func1_logic.global_wires:
					if func1_global in func2_logic.global_wires:
						print "Heyo can't use globals in more than one function!"
						print func1_global, "used in", func_name1, "and", func_name2
						sys.exit(0)
			
		
		c_ast_node_when_used = parser_state.FuncName2Logic[top_level_func_name].c_ast_node
		unadjusted_logic_lookup_table_so_far = None
		adjusted_containing_logic_inst_name=""		
		parser_state.LogicInstLookupTable = None
		# First check if is cached
		top_level_logic = parser_state.FuncName2Logic[top_level_func_name]
		logic_lookup_table_cache = GET_CACHED_LOGIC_INST_LOOKUP(top_level_logic)
		if not(logic_lookup_table_cache is None):
			print "Using cached hierarchy elaboration for '",top_level_func_name,"'"
			parser_state.LogicInstLookupTable = logic_lookup_table_cache
		else:
			print "Elaborating hierarchy down to raw HDL logic..."	
			parser_state.LogicInstLookupTable = RECURSIVE_CREATE_LOGIC_INST_LOOKUP_TABLE(top_level_func_name, top_level_func_name, parser_state, unadjusted_logic_lookup_table_so_far, adjusted_containing_logic_inst_name, c_ast_node_when_used)
		
		
		
		# Write cache
		# top_level_func_name = main = inst name
		top_level_logic = parser_state.LogicInstLookupTable[top_level_func_name]
		
		WRITE_LOGIC_INST_LOOKUP_CACHE(top_level_logic, parser_state.LogicInstLookupTable)
		
		print "Writing generated pipelined C code to output directories..."
		for inst_name in parser_state.LogicInstLookupTable:
			logic = parser_state.LogicInstLookupTable[inst_name]
			if not(logic.c_code_text is None):
				# Fake name
				fake_filename = LEAF_NAME(logic.inst_name, True) + ".c"
				out_dir = SYN.GET_OUTPUT_DIRECTORY(logic, implement=False)
				outpath = out_dir + "/" + fake_filename
				if not os.path.exists(out_dir):
					os.makedirs(out_dir)
				f=open(outpath,"w")
				f.write(logic.c_code_text)
				f.close()		
				
		print "Doing that dumb loop to find containing submodules for everyone..."
		for inst_name in parser_state.LogicInstLookupTable:
			logic = parser_state.LogicInstLookupTable[inst_name]
			for submodule_inst in logic.submodule_instances:
				submodule_logic = parser_state.LogicInstLookupTable[submodule_inst]
				# Adjust listing containing inst
				submodule_logic.containing_inst = inst_name
				# Write back - this is bad python probably not required cuz im bad at python ok
				parser_state.LogicInstLookupTable[submodule_inst] = submodule_logic
				
		print
		
		
		return parser_state
		
	except c_parser.ParseError as pe:
		print "pycparser says you messed up here:",pe
		sys.exit(0)
		
class GlobalInfo:
	def __init__(self):
		self.name = None
		self.type_name = None
		#self.file nvm not allowing extern so should not need
		
def GET_GLOBAL_INFO(parser_state, c_file):
	# Read in file with C parser and get function def nodes
	parser_state.global_info = dict()
	
	global_defs = GET_C_AST_GLOBALS(c_file)
	
	for global_def in global_defs:
		#casthelp(global_def.type.type.names[0])
		global_info = GlobalInfo()
		global_info.name = str(global_def.name)
		global_info.type_name = str(global_def.type.type.names[0])
		
		# Check for multiple types!
		if global_info.name in parser_state.global_info:
			if parser_state.global_info[global_info.name].type_name != global_info.type_name:
				print "Global variable with multiple types?", global_info.name
				sys.exit(0)
				
		# Save info
		parser_state.global_info[global_info.name] = global_info
			
	return parser_state

def GET_ENUM_IDS_DICT(c_file):
	# Read in file with C parser and get function def nodes
	rv = dict()
	enum_defs = GET_C_AST_ENUM_DEFS(c_file)
	for enum_def in enum_defs:
		#casthelp(enum_def)
		#sys.exit(0)
		enum_name = str(enum_def.name)
		#print "struct_name",struct_name
		rv[enum_name] = []
		#casthelp(enum_def.values)
		#sys.exit(0)
		for child in enum_def.values.enumerators:
			if len(child.children()) > 0:
				child.show()
				print "Don't assign enums values for now OK?"
				sys.exit(0)			
			
			#sys.exit(0)
			id_str = str(child.name)
			#print id_str
			rv[enum_name].append(id_str)
			
			'''
			type_name = str(child.children()[0][1].children()[0][1].names[0])
			rv[struct_name][field_name] = type_name
			
			if struct_def.name is None:
				sys.exit(0)
			'''
	#print rv
	#sys.exit(0)
	return rv

_printed_GET_STRUCT_FIELD_TYPE_DICT = False
def GET_STRUCT_FIELD_TYPE_DICT(c_file):
	# Read in file with C parser and get function def nodes
	rv = dict()
	struct_defs = GET_C_AST_STRUCT_DEFS(c_file)
	for struct_def in struct_defs:
		if struct_def.name is None:
			global _printed_GET_STRUCT_FIELD_TYPE_DICT
			if not _printed_GET_STRUCT_FIELD_TYPE_DICT:
				print "WARNING: Must use tag_name and struct_alias in struct definitions... for now... Ex."
				print '''typedef struct tag_name {
	type member1;
	type member2;
} struct_alias;'''
				_printed_GET_STRUCT_FIELD_TYPE_DICT = True
			continue
					
		#casthelp(struct_def)
		struct_name = str(struct_def.name)
		#print "struct_name",struct_name
		rv[struct_name] = dict()
		for child in struct_def.decls:
			# Assume type decl	
			field_name = str(child.name)
			if type(child.type) == c_ast.ArrayDecl:
				#TODO 
				print " GET MULTIPLE DIMENSIONS!"
				sys.exit(0)
				
				dim = int(child.type.dim.value)
				base_type = child.type.type.type.names[0]
				type_name = base_type + "[" + str(dim) + "]"	
			else:
				# Non array
				type_name = str(child.children()[0][1].children()[0][1].names[0])
			rv[struct_name][field_name] = type_name
			
	return rv
	

# This will likely be called multiple times when loading multiple C files
def GET_FUNC_NAME_LOGIC_LOOKUP_TABLE(c_files, parser_state, parse_body = True):
	existing_func_name_2_logic = parser_state.FuncName2Logic
	
	# Build function name to logic from func defs from files
	func_name_2_logic = copy.deepcopy(existing_func_name_2_logic)
	
	# Loop over C files in order and collect func logic (not instance) from func defs
	# Each func def needs existing logic func name lookup
	for c_filename in c_files:
		# Read in file with C parser and get function def nodes
		func_defs = GET_C_AST_FUNC_DEFS(c_filename)
		for func_def in func_defs:
			# Each func def produces a single logic item
			parser_state.existing_logic=None
			driven_wire_names=[]
			prepend_text=""
			logic = C_AST_FUNC_DEF_TO_LOGIC(func_def, parser_state, parse_body)
			func_name_2_logic[logic.func_name] = logic
			func_name_2_logic[logic.func_name].inst_name = logic.func_name 
			
			parser_state.FuncName2Logic = func_name_2_logic
			
			
	'''
	# Remove unused instances
	if remove_unused:
		print "Removing unused function definitions..."
		new_func_name_2_logic = dict()
		for func_name in func_name_2_logic:
			found_as_submodule = False
			# Find func name in some other logic
			for being_searched_func_name in func_name_2_logic:
				being_searched_func_logic = func_name_2_logic[being_searched_func_name]
				for submodule_instance in being_searched_func_logic.submodule_instances:
					submodule_func_name = being_searched_func_logic.submodule_instances[submodule_instance]
					# Found func name as submodule?
					if submodule_func_name == func_name:
						new_func_name_2_logic[func_name] = func_name_2_logic[func_name]
						found_as_submodule = True
						break
				if found_as_submodule:
					break
						
		print "new_func_name_2_logic",new_func_name_2_logic
	'''
			
	return func_name_2_logic
			
def RECURSIVE_CREATE_LOGIC_INST_LOOKUP_TABLE(orig_logic_func_name, orig_logic_inst_name, parser_state, unadjusted_logic_lookup_table_so_far=None, adjusted_containing_logic_inst_name="", c_ast_node_when_used=None, recursion_level=0):	
	#if recursion_level==0:
	#	print "...Recursing from instance: '",LEAF_NAME(orig_logic_inst_name),"'"
	
	new_inst_name_prepend_text = adjusted_containing_logic_inst_name + SUBMODULE_MARKER
	if orig_logic_func_name == "main":
		# Main never gets prepend text
		if adjusted_containing_logic_inst_name != "":
			print "Wtf main never has container?",adjusted_containing_logic_inst_name
			sys.exit(0) 
		# Override
		new_inst_name_prepend_text = ""	
	
	func_name_2_logic = parser_state.FuncName2Logic
	logic_lookup_table_so_far = parser_state.LogicInstLookupTable
	
	# Adjust none input args for main
	if func_name_2_logic is None:
		func_name_2_logic = dict()
	
	if logic_lookup_table_so_far is None:
		new_logic_lookup_table_so_far = dict()
	else:
		new_logic_lookup_table_so_far = logic_lookup_table_so_far # copy.deepcopy(logic_lookup_table_so_far)
	
	if unadjusted_logic_lookup_table_so_far is None:
		unadjusted_logic_lookup_table_so_far = dict()
		
	
	#print ""
	#print "RECURSIVE_CREATE_LOGIC_INST_LOOKUP_TABLE"
	#print "len(new_logic_lookup_table_so_far)",len(new_logic_lookup_table_so_far)	
	#print "orig_logic_func_name",orig_logic_func_name
	#print "orig_logic_inst_name",orig_logic_inst_name
	#print "new_inst_name_prepend_text",new_inst_name_prepend_text
	#print "orig_logic_inst_name in unadjusted_logic_lookup_table_so_far",orig_logic_inst_name in unadjusted_logic_lookup_table_so_far
	#print "orig_logic_func_name in func_name_2_logic",orig_logic_func_name in func_name_2_logic
	
	
	# Set instance for thsi submodule in lookup table	
	if (adjusted_containing_logic_inst_name,orig_logic_inst_name) in unadjusted_logic_lookup_table_so_far:
		orig_inst_logic = copy.copy(unadjusted_logic_lookup_table_so_far[(adjusted_containing_logic_inst_name,orig_logic_inst_name)])
	elif orig_logic_func_name in func_name_2_logic:
		# Logic parsed from C files
		orig_func_logic = copy.copy(func_name_2_logic[orig_logic_func_name])
		# Create artificial inst logic with inst name from func arg
		orig_inst_logic = orig_func_logic
		orig_inst_logic.inst_name = orig_logic_inst_name	
	else:
		# C built in logic
		# Look up containing logic for this submodule isnt
		containing_func_logic = None
		
		# Try to use adjusted_containing_logic_inst_name
		adjusted_containing_logic_inst = new_logic_lookup_table_so_far[adjusted_containing_logic_inst_name]
		containing_logic_func_name = adjusted_containing_logic_inst.func_name
		if containing_logic_func_name in func_name_2_logic:
			containing_func_logic = func_name_2_logic[containing_logic_func_name]		
		
		# If not found search func lookup table for containers with matching submodule instances
		if containing_func_logic is None:
			for func_name in func_name_2_logic:
				func_logic = func_name_2_logic[func_name]
				for submodule_inst in func_logic.submodule_instances:
					submodule_func_name = func_logic.submodule_instances[submodule_inst]
					if (submodule_inst == orig_logic_inst_name) and (submodule_func_name == orig_logic_func_name):
						if not(containing_func_logic is None):
							print "func_logic ONly one containering logic here"
							print "orig_logic_inst_name",orig_logic_inst_name
							print "orig_logic_func_name",orig_logic_func_name
							print 0/0
							sys.exit(0)
						containing_func_logic = func_logic
		
		# if not found search the logic lookup table
		# Look up containing func logic for this submodule inst		
		if containing_func_logic is None:
			unadjusted_containing_inst_logic = None
			for tup_key in unadjusted_logic_lookup_table_so_far:
				unadjusted_inst_logic = unadjusted_logic_lookup_table_so_far[tup_key]
				for unadjusted_submodule_inst in unadjusted_inst_logic.submodule_instances:
					submodule_func_name = unadjusted_inst_logic.submodule_instances[unadjusted_submodule_inst]
					if (unadjusted_submodule_inst == orig_logic_inst_name) and (submodule_func_name == orig_logic_func_name):
						if not(unadjusted_containing_inst_logic is None):
							print "1)new_logic_lookup_table_so_far ONly one containering logic here"
							print "unadjusted_containing_inst_logic.inst_name",unadjusted_containing_inst_logic.inst_name
							print "potential unadjusted_inst_logic.inst_name",unadjusted_inst_logic.inst_name
							print "unadjusted_logic_lookup_table_so_far",unadjusted_logic_lookup_table_so_far
							print 0/0
							sys.exit(0)
						unadjusted_containing_inst_logic = unadjusted_inst_logic
			
			containing_func_logic = unadjusted_containing_inst_logic
			
		'''
		# If still not found search the logic inst lookup table
		if containing_func_logic is None:
			adjusted_containing_inst_logic = None
			for adjusted_inst_name in new_logic_lookup_table_so_far:
				adjusted_inst_logic = new_logic_lookup_table_so_far[adjusted_inst_name]
				for adjusted_submodule_inst in adjusted_inst_logic.submodule_instances:
					leaf_submodule_inst_name = adjusted_submodule_inst.replace(adjusted_inst_name + SUBMODULE_MARKER,"")
					submodule_func_name = adjusted_inst_logic.submodule_instances[adjusted_submodule_inst]
					if (leaf_submodule_inst_name==orig_logic_inst_name) and (submodule_func_name == orig_logic_func_name):
						if not(adjusted_containing_inst_logic is None):
							print "Multiple matches for container of",orig_logic_inst_name
							print "New match:",adjusted_inst_name
							print "Old match:",adjusted_containing_inst_logic.inst_name
							sys.exit(0)
							
						adjusted_containing_inst_logic = adjusted_inst_logic
	
	
			# UNDO inst name adjsutments to get unadjusted container logic
			# Like would be found in unadjusted_logic_lookup_table_so_far
			
			containing_func_logic = adjusted_containing_inst_logic
			#if containing_func_logic is None:
			#	print "Cant find logic that contains orig_logic_inst_name in new_logic_lookup_table_so_far",orig_logic_inst_name
			#	sys.exit(0)
		'''
		
		if not(containing_func_logic is None):
			orig_inst_logic = BUILD_C_BUILT_IN_SUBMODULE_LOGIC_INST(containing_func_logic,new_inst_name_prepend_text, orig_logic_inst_name, parser_state)
						
		else:
			# NONE contining logic>?		
			print "!!!!!!!!!!!!!!!!!"
			print "BAH! Cant find logic that contains orig_logic_inst_name",orig_logic_inst_name
			print "orig_logic_func_name",orig_logic_func_name
			print "=== ALL NON_RAW_HDL func_name_2_logic ===="
			for func_name in func_name_2_logic:
				func_logic = func_name_2_logic[func_name]
				if len(func_logic.submodule_instances) > 0:
					print "func_name",func_name
					for submodule_inst in func_logic.submodule_instances:
						print "	submodule_inst ",submodule_inst
						
			print "=== ALL NON_RAW_HDL new_logic_lookup_table_so_far ===="
			for inst_name in new_logic_lookup_table_so_far:
				inst_logic = new_logic_lookup_table_so_far[inst_name]
				if len(inst_logic.submodule_instances) > 0:
					print "inst_name",inst_name
					for submodule_inst in inst_logic.submodule_instances:
						print "	submodule_inst ",submodule_inst
			
			sys.exit(0)
		
		

	# Since the original unadjusted instance name is not unique enough
	# Ex. A use of uint23_mux23 has a submodule MUX_layer0_node0 exactly as uint24_mux24 does so can store MUX_layer0_node0 as the inst name alone
	# Need to store containing inst too
	unadjusted_logic_lookup_table_so_far[(adjusted_containing_logic_inst_name,orig_inst_logic.inst_name)] = copy.deepcopy(orig_inst_logic)	
	
	
	
	
	# Adjust original logic for instance name
	#print "type(unadjusted_logic_lookup_table_so_far)",type(unadjusted_logic_lookup_table_so_far)
	#print "unadjusted_logic_lookup_table_so_far",unadjusted_logic_lookup_table_so_far
	#print "orig_logic.inst_name",orig_logic.inst_name
	#print "new_inst_name_prepend_text",new_inst_name_prepend_text
	inst_logic = orig_inst_logic.INST_LOGIC_ADJUST_W_PREPEND(new_inst_name_prepend_text)
	#print "After INST_NAME_ADJUSTED"
	#print "inst_logic.inst_name",inst_logic.inst_name
	#print "inst_logic.submodule_instances",inst_logic.submodule_instances
	new_logic_lookup_table_so_far[inst_logic.inst_name] = inst_logic
	#print "inst_logic.inst_name",inst_logic.inst_name
	#print "orig_inst_logic.c_ast_node.coord",orig_inst_logic.c_ast_node.coord
	#print "coord",inst_logic.c_ast_node.coord
	

	
	# Then recursively do submodules
	#print "orig_inst_logic.submodule_instances",orig_inst_logic.submodule_instances
	#print "orig_inst_logic has submodule_instances",orig_inst_logic.submodule_instances
	for orig_submodule_logic_inst_name in orig_inst_logic.submodule_instances:
		orig_submodule_logic_func_name = orig_inst_logic.submodule_instances[orig_submodule_logic_inst_name]
		submodule_c_ast_node_when_used = orig_inst_logic.submodule_instance_to_c_ast_node[orig_submodule_logic_inst_name]
		#print ""
		#print "RECURSIVELY DOING RECURSIVE_CREATE_LOGIC_INST_LOOKUP_TABLE"
		#submodule_new_inst_name_prepend_text = inst_logic.inst_name + SUBMODULE_MARKER
		submodule_adjusted_containing_logic_inst_name = inst_logic.inst_name
		#print "orig_submodule_logic_inst_name", orig_submodule_logic_inst_name
		#print "orig_submodule_logic_inst_name used at", C_AST_COORD_STR(submodule_c_ast_node_when_used.coord)
		#print "orig_submodule_logic_func_name",orig_submodule_logic_func_name
		#print "submodule_new_inst_name_prepend_text", submodule_new_inst_name_prepend_text
		
		parser_state.LogicInstLookupTable = new_logic_lookup_table_so_far
		
		new_logic_lookup_table_so_far = RECURSIVE_CREATE_LOGIC_INST_LOOKUP_TABLE(orig_submodule_logic_func_name, orig_submodule_logic_inst_name, parser_state, unadjusted_logic_lookup_table_so_far, submodule_adjusted_containing_logic_inst_name, submodule_c_ast_node_when_used, recursion_level)

		parser_state.LogicInstLookupTable = new_logic_lookup_table_so_far

	return new_logic_lookup_table_so_far



def GET_C_AST_FUNC_DEFS_FROM_C_CODE_TEXT(text, fake_filename):
	# Use C parser to do some lifting
	# See https://github.com/eliben/pycparser/blob/master/examples/explore_ast.py
	parser = c_parser.CParser()
	# Use preprocessor function
	c_text = preprocess_text(text)
	#print "========="
	#print "fake_filename",fake_filename
	#print "preprocessed text",c_text
	
	# Hacky because somehow parser.parse() getting filename from cpp output?
	c_text = c_text.replace("<stdin>",fake_filename)
	
	ast = parser.parse(c_text,filename=fake_filename)
	#ast.show()
	
	func_defs = GET_TYPE_FROM_LIST(c_ast.FuncDef, ast.ext)
	#if len(func_defs) > 0:
	#	print "Coord of func def", func_defs[0].coord
		
	#print "========="
	return func_defs

def GET_C_AST_FUNC_DEFS(c_filename):
	c_file_ast = GET_C_FILE_AST(c_filename)
	#c_file_ast.show()
	# children are "external declarations",
	# and are stored in a list called ext[]
	func_defs = GET_TYPE_FROM_LIST(c_ast.FuncDef, c_file_ast.ext)
	return func_defs
	
def GET_C_AST_STRUCT_DEFS(c_filename):
	c_file_ast = GET_C_FILE_AST(c_filename)

	# Get type defs
	type_defs = GET_TYPE_FROM_LIST(c_ast.Typedef, c_file_ast.ext)
	struct_defs = []
	for type_def in type_defs:
		#casthelp(type_def)
		thing = type_def.children()[0][1].children()[0][1]
		if type(thing) == c_ast.Struct:
			struct_defs.append(thing)
			
	return struct_defs
	
def GET_C_AST_ENUM_DEFS(c_filename):
	c_file_ast = GET_C_FILE_AST(c_filename)

	# Get type defs
	type_defs = GET_TYPE_FROM_LIST(c_ast.Typedef, c_file_ast.ext)
	enum_defs = []
	for type_def in type_defs:
		#casthelp(type_def)
		thing = type_def.children()[0][1].children()[0][1]
		if type(thing) == c_ast.Enum:
			enum_defs.append(thing)
	#print enum_defs
	#sys.exit(0)		
	return enum_defs
	
def GET_C_AST_GLOBALS(c_filename):
	c_file_ast = GET_C_FILE_AST(c_filename)
	#c_file_ast.show()
	
	# Get type defs
	variable_defs = GET_TYPE_FROM_LIST(c_ast.Decl, c_file_ast.ext)
	
	#print variable_defs
	#sys.exit(0)
		
	return variable_defs

# Filter out a certain type from a list
# Im dumb at python
def GET_TYPE_FROM_LIST(py_type, l):
	rv = []
	for i in l:
		if type(i) == py_type:
			rv.append(i)
	return rv
	
	
def GET_C_FILE_AST(c_filename):
	# Use C parser to do some lifting
	# See https://github.com/eliben/pycparser/blob/master/examples/explore_ast.py
	parser = c_parser.CParser()
	# Use preprocessor function
	c_text = preprocess_file(c_filename)
	#print "PREPROCESSED:"
	#print c_text
	ast = parser.parse(c_text,filename=c_filename)
	#ast.show()
	return ast

	
	
		
	
