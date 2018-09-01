import os
import sys
import math
import re

import C_TO_LOGIC
import VHDL

# Hey lets bootstrap for fun

BIT_MANIP_HEADER_FILE = "bit_manip.h"
BIT_MATH_HEADER_FILE = "bit_math.h"

### HACKY
# Add bit manip pre VHDL insert for NON C?????????????????

# C supports 'integer promotion' = supports assignment to larger bit widths
# Sw will simulate with type defs
# Hacky special parsing of bit widths to be variable width descriptions?


def GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP(c_file, parser_state):
	# Use preprocessor to get text
	c_text = C_TO_LOGIC.preprocess_file(c_file)
	#print c_text
	return GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state)


# Uhh this seems wrong? But works for now?
def IS_AUTO_GENERATED(logic):
	#print "IS_AUTO_GENERATED",logic.func_name, logic.inst_name, logic.c_ast_node.coord
	return ( ( str(logic.c_ast_node.coord).split(":")[0].endswith(BIT_MANIP_HEADER_FILE) or
	              str(logic.c_ast_node.coord).split(":")[0].endswith(BIT_MATH_HEADER_FILE)     ) and
	         not logic.is_c_built_in )
	
def GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state):
	# DONT FORGET TO CHANGE IS_AUTO_GENERATED
	lookups = []
	
	# BIT manipulation is auto generated
	bit_manip_func_name_logic_lookup = GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state)
	lookups.append(bit_manip_func_name_logic_lookup)
	
	#print "bit_manip_func_name_logic_lookup",bit_manip_func_name_logic_lookup
	
	# Some (small?) math operations on bit specific types, ex. abs() which is not 0LLs - takes logic since twos complement
	# But also shouldnt implement as *-1 since more LLs
	###### THESE DEPEND ON BIT MANIP #TODO: Depedencies what?
	bit_math_func_name_logic_lookup = GET_BIT_MATH_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state)
	lookups.append(bit_math_func_name_logic_lookup)
	
	#print "bit_math_func_name_logic_lookup",bit_math_func_name_logic_lookup
	
	# Combine lookups
	rv = dict()
	for func_name_logic_lookup in lookups:
		for func_name in func_name_logic_lookup:
			if not(func_name in rv):
				rv[func_name] = func_name_logic_lookup[func_name]
				
				#print "func_name (func_name_logic_lookup)",func_name
				#if len(func_name_logic_lookup[func_name].wire_drives) == 0:
				#	print "BAD!"
				#	sys.exit(0)
				
			else:
				# For now allow if from bit manip
				#print "str(rv[func_name].c_ast_node.coord)",str(rv[func_name].c_ast_node.coord)
				if str(rv[func_name].c_ast_node.coord).startswith(BIT_MANIP_HEADER_FILE):
					pass
				else:
					print "GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_CODE_TEXT func_name in multiple dicts?", func_name
					print "bit_manip_func_name_logic_lookup",bit_manip_func_name_logic_lookup
					print "==="
					print "bit_math_func_name_logic_lookup",bit_math_func_name_logic_lookup
					sys.exit(0)
	
	return rv
	
def GET_BIT_MATH_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state):
	text = ""
	text += '''
#include "uintN_t.h"
#include "intN_t.h"
	'''	
	
	# Regex search c_text
	
	
	
	# Negate
	# Parse to list of width toks
	negate_func_names = []
	# uint24_negate(left_resized);
	for type_regex in ["uint[0-9]+_negate\s?\("]: #DO int,float negate?
		p = re.compile(type_regex)
		negate_func_names = p.findall(c_text)
		negate_func_names = list(set(negate_func_names))
		for negate_func_name in negate_func_names:
			negate_func_name = negate_func_name.strip("(").strip()
			toks = negate_func_name.split("_")
			in_prefix = toks[0]
			in_width = int(in_prefix.replace("uint",""))
			result_t = "int" + str(in_width+1) + "_t"
			result_uint_t = "uint" + str(in_width+1) + "_t"
			
			if type_regex == "float":
				print " #DO int,float negate?"
				sys.exit(0)
			else:
				in_t = in_prefix + "_t"
				
			func_name = in_prefix + "_negate"
			text += '''
// Negate
''' + result_t + " " + func_name+"("+ in_t + ''' x)
{
	// Twos comp
	
	''' + result_uint_t + ''' x_wide;
	x_wide = x;
	
	''' + result_uint_t + ''' x_wide_neg;
	x_wide_neg = !x_wide;
	
	''' + result_uint_t + ''' x_neg_wide_plus1;
	x_neg_wide_plus1 = x_wide_neg + 1;
	
	''' + result_t + ''' rv;
	rv = x_neg_wide_plus1;
	
	return rv;
}
'''

	# abs
	# Parse to list of width toks
	abs_func_names = []
	# uint24_abs(left_resized);
	for type_regex in ["int[0-9]+_abs\s?\("]: #DO float abs?
		p = re.compile(type_regex)
		abs_func_names = p.findall(c_text)
		abs_func_names = list(set(abs_func_names))
		for abs_func_name in abs_func_names:
			abs_func_name = abs_func_name.strip("(").strip()
			toks = abs_func_name.split("_")
			in_prefix = toks[0]
			in_width = int(in_prefix.replace("int",""))
			sign_index = in_width-1
			result_t = "uint" + str(in_width) + "_t"
			if type_regex == "float":
				print " #DO int,float abs?"
				sys.exit(0)
			else:
				in_t = in_prefix + "_t"
				
			func_name = in_prefix + "_abs"
			text += '''
#include "bit_manip.h"
			
// abs
''' + result_t + " " + func_name+"("+ in_t + ''' x)
{
	// Reverse twos comp?
	// Sub one and invert bits
	// Fine with condition since other way is something like  (x + (x >> 31)) ^ (x >> 31)
	// Which is dumb to do in SW
	
	// Get sign
	uint1_t sign;
	sign = ''' + in_prefix + '''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(x);
	
	// Get unsigned x
	''' + result_t + ''' x_uint;
	x_uint = x;
	
	// Minus 1
	''' + result_t + ''' x_uint_minus1;
	x_uint_minus1 = x_uint - 1;
	
	// Negate
	''' + result_t + ''' x_uint_minus1_neg;
	x_uint_minus1_neg = !x_uint_minus1;
	
	''' + result_t + ''' rv;
	if(sign==1)
	{
		rv = x_uint_minus1_neg;
	}
	else
	{
		rv = x;
	}
	
	return rv;
}
'''






	# N MUX
	# Parse to list of width toks
	nmux_func_names = []
	# uint24_mux24(left_resized);
	for type_regex in ["uint[0-9]+_mux[0-9]+\s?\("]:
		p = re.compile(type_regex)
		nmux_func_names = p.findall(c_text)
		nmux_func_names = list(set(nmux_func_names))
		for nmux_func_name in nmux_func_names:
			nmux_func_name = nmux_func_name.strip("(").strip()
			toks = nmux_func_name.split("_")
			type_prefix = toks[0]
			mux_name = toks[1]
			n = int(mux_name.replace("mux",""))
			sel_width = int(math.ceil(math.log(n,2)))
			sel_t = "uint" + str(sel_width) + "_t"
			type_width = int(type_prefix.replace("uint",""))
			result_t = type_prefix + "_t"
			in_t = result_t	
			func_name = type_prefix + "_" + mux_name
			var_2_type = dict()
			
			#FUCKFUCK
			#if n == 23:
			#	for i in range(0,n):
			#		text += "\n"
			
			text += '''
#include "bit_manip.h"			
			
// ''' + str(n) + ''' MUX
''' + result_t + " " + func_name+"("+ sel_t + ''' sel,'''
			# List each input
			for i in range(0, n):
				text += in_t + " in" + str(i) + ","
			# Remove last comma
			text = text.strip(",")
			text += ''')
{'''
			
			# Hierarchy of 2x1 muxes
			# Start with list of inputs
			layer = 0
			layer_nodes = [] 
			for i in range(0, n):
				layer_nodes.append("in" + str(i))
			
			# DO
			while True: 
				text += '''
	// Layer ''' + str(layer) + '''
		'''
				# Get sel bit
				sel_var = "sel"+ str(layer) 
				text += '''
	// Get sel bit
	uint1_t ''' + sel_var + ''';
	''' + sel_var + ''' = uint''' + str(sel_width) + "_" + str(layer) + "_" + str(layer) + '''(sel);
'''
				node = 0
				new_layer_nodes = []
				# Write adds in pairs
				# While 2 args to add
				while(len(layer_nodes) >= 2):
					# Declare result of this mux
					out_var = "layer" + str(layer) + "_node" + str(node)
					text += '''
	''' + result_t + ''' ''' + out_var + ''';
	'''
					# Do the if
					false_arg = layer_nodes.pop(0)
					true_arg = layer_nodes.pop(0)
					
					
					text +='''// Do regular mux
	if(''' + sel_var + ''')
	{
		''' + out_var + ''' = ''' + true_arg + ''';
	}
	else
	{
		''' + out_var + ''' = ''' + false_arg + ''';
	}
	'''
					
					# This out node is on next layer
					new_layer_nodes.append(out_var)
					node += 1
				
				# Out of while loop	
				# < 2 nodes left to sum in this node
				if len(layer_nodes) == 1:
					# One node left
					the_arg = layer_nodes.pop(0)
					# Declare result of this mux
					out_var = "layer" + str(layer) + "_node" + str(node)
					text += '''
	// Odd node in layer
	''' + result_t + ''' ''' + out_var + ''';
	''' + out_var + ''' = ''' + the_arg + ''';
	'''
					# This out node is on next layer
					new_layer_nodes.append(out_var)
					node += 1
					
				
				# WHILE
				if len(new_layer_nodes) >= 2:
					# Continue
					layer_nodes = new_layer_nodes
					layer += 1
				else:
					# DONE
					break;

	
	
	
			# Return last out var
			last_out_var = "layer" + str(layer) + "_node" + str(node-1)
			text += '''	
	return ''' + last_out_var + ''';
}
'''



	
	# count0 s
	# Parse to list of width toks
	count0_func_names = []
	# count0s_uint24(left_resized) # Count from left, uint24_count0s counts from right
	for type_regex in ["count0s_uint[0-9]+\s?\("]:
		p = re.compile(type_regex)
		count0_func_names = p.findall(c_text)
		count0_func_names = list(set(count0_func_names))
		for count0_func_name in count0_func_names:
			count0_func_name = count0_func_name.strip("(").strip()
			toks = count0_func_name.split("_")
			in_prefix = toks[1]
			in_t = in_prefix + "_t"
			in_width = int(in_prefix.replace("uint",""))
			# Result width depends on width of input
			# DONT COUNT all zeros since shift after this wont change
			# Only need to count to in_width-1
			result_width = int(math.ceil(math.log(in_width,2)))
			result_prefix = "uint" + str(result_width)
			result_t = result_prefix + "_t"
			func_name = count0_func_name
			
#include "bit_manip.h"
			text += '''
			
// count0s from left
''' + result_t + " " + func_name+"("+ in_t + ''' x)
{
	// First do all the compares in parallel
	// All zeros yields 0 after shift so - fuck it only check 0-width-1
	// Also shift of 0 will be assumed if not of the other ORs are set'''
			for leading_zeros in range(1, in_width):
				text += '''
	uint1_t leading''' + str(leading_zeros) + ''';
	leading''' + str(leading_zeros) + ''' = ''' + in_prefix + '''_''' + str(in_width-1) + '''_'''+ str(in_width-1-leading_zeros) + '''(x) == 1;
	
	
	// Mux each one hot into a constant
	// This cant be optimal but better than before for sure
	// Cant i jsut be happy for a little?'''
			# SKIP SUM0 SINCE IS BY DEF 0
			var_2_type = dict()
			for leading_zeros in range(1, in_width):
				sum_width = int(math.ceil(math.log(leading_zeros+1,2)))
				sum_prefix = "uint" + str(sum_width)
				sum_t = sum_prefix + "_t"
				var = "sum"+ str(leading_zeros)
				var_2_type[var] = sum_t
				text += '''
	''' + sum_t + ''' ''' + var + ''';
	if(leading''' + str(leading_zeros) + ''')
	{
		''' + var + ''' = ''' + str(leading_zeros) + ''';
	}
	else
	{
		''' + var + ''' = 0;
	}
	'''
	
			# Now do binary tree ORing all these single only one will be set
			# Fuck jsut copy from binary tree for mult
			text += '''
	// Binary tree OR of "sums", can sine only one will be set
'''
			layer_nodes = []
			for p in range(1,in_width):
				layer_nodes.append("sum" + str(p))
				
			layer=0
			node=0
 
	
			# DO
			while True: 
				text += '''
	// Layer ''' + str(layer) + '''
'''
				node = 0
				new_layer_nodes = []
				# Write adds in pairs
				# While 2 args to add
				while(len(layer_nodes) >= 2):
					left_arg = layer_nodes.pop(0)
					right_arg = layer_nodes.pop(0)
					left_t = var_2_type[left_arg]
					right_t = var_2_type[right_arg]
					# Sum type is max width
					left_width = int(left_t.replace("uint","").replace("int","").replace("_t",""))
					right_width = int(right_t.replace("uint","").replace("int","").replace("_t",""))
					max_width = max(left_width,right_width)
					or_width = max_width
					
					sum_t = "uint" + str(or_width) + "_t"
					sum_var = "sum_layer" + str(layer) + "_node" + str(node)
					var_2_type[sum_var] = sum_t
					text += '''	''' + sum_t + ''' ''' + sum_var + ''';
	''' + sum_var + ''' = ''' + left_arg + " | " + right_arg + ''';
'''
					# This sum node is on next layer
					new_layer_nodes.append(sum_var)
					node += 1
				
				# Out of while loop	
				# < 2 nodes left to sum in this node
				if len(layer_nodes) == 1:
					# One node left
					the_arg = layer_nodes.pop(0)
					the_t = var_2_type[the_arg]
					sum_t = the_t			
					sum_var = "sum_layer" + str(layer) + "_node" + str(node)
					var_2_type[sum_var] = sum_t
					text += '''	// Odd node in layer
	''' + sum_t + ''' ''' + sum_var + ''';
	''' + sum_var + ''' = ''' + the_arg + ''';
'''
					# This sum node is on next layer
					new_layer_nodes.append(sum_var)
					node += 1
					
				
				# WHILE
				if len(new_layer_nodes) >= 2:
					# Continue
					layer_nodes = new_layer_nodes
					layer += 1
				else:
					# DONE
					break;
			
			# Done with outer layer while loop
				
			# Do return
			return_var = "sum_layer" + str(layer) + "_node" + str(node-1)
			return_t = var_2_type[return_var]
			text += '''
	''' + "// Return" + '''
	''' + return_t + ''' rv;
	rv = ''' + return_var + ''';
	return rv;
}
'''



	
	
	
	
	
	
	
	
	
	# N SUM
	# Parse to list of width toks
	nsum_func_names = []
	# uint24_sum24(left_resized);
	for type_regex in ["uint[0-9]+","uint[0-9]+_array","float","float_array"]:
		for regex in [type_regex+"_sum[0-9]+\s?\("]:
			p = re.compile(regex)
			nsum_func_names = p.findall(c_text)
			nsum_func_names = list(set(nsum_func_names))
			for nsum_func_name in nsum_func_names:
				nsum_func_name = nsum_func_name.strip("(").strip()
				toks = nsum_func_name.split("_")
				# type_prefix=float_array
				if len(toks) == 2:
					type_prefix = toks[0]
					sum_name = toks[1]
				else:
					type_prefix = toks[0] + "_" + toks[1]
					sum_name = toks[2]
				
				# how many to sum?				
				n_sum = int(sum_name.replace("sum",""))
				#print "n_sum",n_sum
				
				# Result type?
				if "float" in type_prefix:
					result_t = "float"
				else:
					type_width = int(type_prefix.replace("uint",""))
					# Sum 2 would be bit width increase of 1
					max_in_val = (math.pow(2,type_width)-1)
					max_sum = max_in_val * n_sum
					result_width = int(math.ceil(math.log(max_sum+1,2)))
					result_t = "uint" + str(result_width) + "_t"
				# input type?
				if "array" in type_prefix:
					in_t = type_prefix.replace("_array","") # Need to construct with var name
				else:
					in_t = type_prefix + "_t"	
				
				func_name = type_prefix + "_" + sum_name
				var_2_type = dict()
				text += '''
	#include "bit_manip.h"			
				
	// ''' + str(n_sum) + ''' sum
	''' + result_t + " " + func_name+"("
				if "array" in type_prefix:
					var_2_type["x"]=in_t + "[" + str(n_sum) + "]"
					text += in_t + " x" + "[" + str(n_sum) + "]"
				else: 
					# List each input
					for i in range(0, n):
						text += in_t + " x" + str(i) + ","
						var_2_type["x" + str(i)]=in_t
					# Remove last comma
					text = text.strip(",")
					
				text += ''')
	{'''

				layer_nodes = []
				if "array" in type_prefix:
					for n in range(0,n_sum):
						var = "x[" + str(n) + "]"
						layer_nodes.append(var)
						var_2_type[var] = in_t
				else:
					for n in range(0,n_sum):
						layer_nodes.append("x" + str(n))
						
				layer=0
				node=0
				
				text += '''
				// Binary summation of partial sums
			'''
			 
				
				# DO
				while True: 
					text += '''
				// Layer + ''' + str(layer) + '''
			'''
					node = 0
					new_layer_nodes = []
					# Write adds in pairs
					# While 2 args to add
					while(len(layer_nodes) >= 2):
						left_arg = layer_nodes.pop(0)
						right_arg = layer_nodes.pop(0)
						left_t = var_2_type[left_arg]
						right_t = var_2_type[right_arg]
						if "float" in type_prefix:
							sum_t = "float"
						else:
							# Sum type is max width+1
							left_width = int(left_t.replace("uint","").replace("int","").replace("_t",""))
							right_width = int(right_t.replace("uint","").replace("int","").replace("_t",""))
							max_width = max(left_width,right_width)
							sum_width = max_width+1
							sum_t = "uint" + str(sum_width) + "_t"
							
						
						sum_var = "sum_layer" + str(layer) + "_node" + str(node)
						var_2_type[sum_var] = sum_t
						text += '''	''' + sum_t + ''' ''' + sum_var + ''';
				''' + sum_var + ''' = ''' + left_arg + " + " + right_arg + ''';
			'''
						# This sum node is on next layer
						new_layer_nodes.append(sum_var)
						node += 1
					
					# Out of while loop	
					# < 2 nodes left to sum in this node
					if len(layer_nodes) == 1:
						# One node left
						the_arg = layer_nodes.pop(0)
						the_t = var_2_type[the_arg]
						sum_t = the_t			
						sum_var = "sum_layer" + str(layer) + "_node" + str(node)
						var_2_type[sum_var] = sum_t
						text += '''	// Odd node in layer
				''' + sum_t + ''' ''' + sum_var + ''';
				''' + sum_var + ''' = ''' + the_arg + ''';
				'''
						# This sum node is on next layer
						new_layer_nodes.append(sum_var)
						node += 1
						
					
					# WHILE
					if len(new_layer_nodes) >= 2:
						# Continue
						layer_nodes = new_layer_nodes
						layer += 1
					else:
						# DONE
						break;
				
				# Done with outer layer while loop
					
				# Do return
				return_var = "sum_layer" + str(layer) + "_node" + str(node-1)
				return_t = var_2_type[return_var]
				text += '''
				''' + "// Return" + '''
				''' + return_t + ''' rv;
				rv = ''' + return_var + ''';
				return rv;
			}
			'''
			
			
			
			
			
			
			
			
			
			
			
			
			
			
			

	
	
	outfile = BIT_MATH_HEADER_FILE
	
	
	# Parse the c doe to logic lookup
	bit_manip_func_name_logic_lookup = GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(text,parser_state)  # DEPENDS ON BIT MANIP # TODO: How to handle dependencies
	parser_state = C_TO_LOGIC.ParserState()
	parser_state.FuncName2Logic = bit_manip_func_name_logic_lookup # dict()  
	parse_body = True # BIT MATH IS SW IMPLEMENTATION
	func_name_2_logic = C_TO_LOGIC.GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(text, outfile, parser_state, parse_body)
	
	for func_name in func_name_2_logic:
		func_logic = func_name_2_logic[func_name]
		if len(func_logic.wire_drives) == 0 and str(func_logic.c_ast_node.coord).split(":")[0].endswith(BIT_MATH_HEADER_FILE):
			print "BIT_MATH_HEADER_FILE"
			print text
			print "Bad parsing of BIT MATH",func_name
			sys.exit(0)
	
	return func_name_2_logic


def GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state):

	# TODO: Do bit select and bit dup as "const int"
	
	text = ""
	text += '''
#include "uintN_t.h"
#include "intN_t.h"
	'''	
	
	# Regex search c_text
	# Bit select
	# Parse to list of width toks
	bit_sel_func_names = []
	# uint64_39_39(left_resized);
	for type_regex in ["uint[0-9]+","int[0-9]+","float"]:
		p = re.compile(type_regex + '_[0-9]+_[0-9]+\s?\(')
		bit_sel_func_names = p.findall(c_text)
		bit_sel_func_names = list(set(bit_sel_func_names))
		# Need bit concat and bit select
		# BIT SELECT
		# uint16_t uintX_15_0(uintX_t)
		for bit_sel_func_name in bit_sel_func_names:
			bit_sel_func_name = bit_sel_func_name.strip("(").strip()
			toks = bit_sel_func_name.split("_")
			high = int(toks[1])
			low = int(toks[2])
			in_prefix = toks[0]
			if type_regex == "float":
				in_t = "float"
			else:
				in_t = in_prefix + "_t"
			func_name = in_prefix + "_"+str(high)+"_"+str(low)
			# Catch reverse
			if high < low:
				temp = low
				low = high
				high = temp
			result_width = high - low + 1
			result_t = "uint" + str(result_width) + "_t"
			
			text += '''
// BIT SELECT
''' + result_t + " " + func_name+"("+ in_t + ''' x)
{
	//TODO
}
'''
	
	# BIT CONCAT
	# Parse to list of width toks
	bit_concat_func_names = []
	# uint64_uint15
	p = re.compile('u?int[0-9]+_u?int[0-9]+\s?\(')
	bit_concat_func_names = p.findall(c_text)
	bit_concat_func_names = list(set(bit_concat_func_names))
	#uint5_t uint2_uint3(uint2 x, uint3 y) 
	for bit_concat_func_name in bit_concat_func_names:
		bit_concat_func_name = bit_concat_func_name.strip("(").strip()
		toks = bit_concat_func_name.split("_")
		first_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
		second_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[1] + "_t")
		result_width = first_bit_width + second_bit_width
		result_t = "uint" + str(result_width) + "_t"
		first_in_prefix = toks[0]
		first_in_t = first_in_prefix + "_t"
		second_in_prefix = toks[1]
		second_in_t = second_in_prefix + "_t"
		func_name = first_in_prefix+"_"+second_in_prefix
		text += '''
// BIT CONCAT
''' + result_t + " " + func_name + "(" + first_in_t + " x, " + second_in_t + ''' y)
{
	//TODO
}
'''
	
	# BITS DUP
	# Parse to list of width toks
	bit_dup_func_names = []
	# uint64_5
	p = re.compile('[^_][u?]int[0-9]+_[0-9]+\s?\(')
	bit_dup_func_names = p.findall(c_text)
	bit_dup_func_names = list(set(bit_dup_func_names))
	# Questionable seems OK naming convention?
	# uint(X*15)_t uintX_15(uintX_t)
	# hacky dont match bit bit_sel_func_names
	for bit_dup_func_name in bit_dup_func_names:
		#if not(bit_dup_func_name in bit_sel_func_names):
		bit_dup_func_name = bit_dup_func_name.strip("(").strip()
		toks = bit_dup_func_name.split("_")
		input_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
		mult = int(toks[1])
		#if mult==0:
		#	continue
		result_width = input_bit_width * mult			
		result_t = "uint" + str(result_width) + "_t"
		in_prefix = toks[0]
		in_t = in_prefix + "_t"
		func_name = in_prefix + "_"+str(mult)
		text += '''
// BIT DUP
''' + result_t + " " + in_prefix + "_"+str(mult)+"("+ in_t + ''' x)
{
	//TODO
}
'''

	# Constant index assignment with N bits
	# Otherwise large slv is like ram lookup
	# Parse to list of width toks
	bit_ass_func_names = []
	# uint64_uint15_2(uint64_t in, uint15_t x)  // out = in; out(16 downto 2) = x
	p = re.compile('uint[0-9]+_uint[0-9]+_[0-9]+\s?\(')
	bit_ass_func_names = p.findall(c_text)
	bit_ass_func_names = list(set(bit_ass_func_names))
	for bit_ass_func_name in bit_ass_func_names:
		bit_ass_func_name = bit_ass_func_name.strip("(").strip()
		toks = bit_ass_func_name.split("_")
		input_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
		assign_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[1] + "_t")
		low_index = int(toks[2])
		high_index = low_index + assign_width - 1
		result_width = input_bit_width		
		result_t = "uint" + str(result_width) + "_t"
		in_prefix = toks[0]
		in_t = in_prefix + "_t"
		x_prefix = toks[1]
		x_t = x_prefix + "_t"
		func_name = bit_ass_func_name
		text += '''
// CONST BIT ASSIGNMENT
''' + result_t + " " + func_name +"("+ in_t + ''' inp, ''' + x_t + ''' x)
{
	//TODO
}
'''


	# Float SEM construction
	# Regex search c_text
	# Parse to list of width toks
	float_const_func_names = []
	# float_1_8_23(left_resized);
	for type_regex in ["float"]:
		p = re.compile(type_regex + '_uint[0-9]+_uint[0-9]+_uint[0-9]+\s?\(')
		float_const_func_names = p.findall(c_text)
		float_const_func_names = list(set(float_const_func_names))
		for float_const_func_name in float_const_func_names:
			float_const_func_name = float_const_func_name.strip("(").strip()
			toks = float_const_func_name.split("_")
			s_prefix = toks[1]
			s_t = s_prefix + "_t"
			e_prefix = toks[2]
			e_t = e_prefix + "_t"
			m_prefix = toks[3]
			m_t = m_prefix + "_t"
			result_t = type_regex
			func_name = float_const_func_name
			text += '''
// BIT SELECT
''' + result_t + " " + func_name+"("+ s_t + ''' sign, ''' + e_t + ''' exponent, ''' + m_t + ''' mantissa)
{
	//TODO
}
'''

	# Float UINT32 construction ... bleh ... implement unions?
	# Regex search c_text
	# Parse to list of width toks
	float_const_func_names = []
	# float_uint32(in);
	for type_regex in ["float"]:
		p = re.compile(type_regex + '_uint[0-9]+\s?\(')
		float_const_func_names = p.findall(c_text)
		float_const_func_names = list(set(float_const_func_names))
		for float_const_func_name in float_const_func_names:
			float_const_func_name = float_const_func_name.strip("(").strip()
			toks = float_const_func_name.split("_")
			in_prefix = toks[1]
			in_t = in_prefix + "_t"
			result_t = type_regex
			func_name = float_const_func_name
			text += '''
// BIT SELECT
''' + result_t + " " + func_name+"("+ in_t + ''' x)
{
	//TODO
}
'''



	# Byte swap, with same name as real C func
	# Parse to list of width toks
	bswap_func_names = []
	# uint64_5
	p = re.compile('bswap_[0-9]+\s?\(')
	bswap_func_names = p.findall(c_text)
	bswap_func_names = list(set(bswap_func_names))
	for bswap_func_name in bswap_func_names:
		bswap_func_name = bswap_func_name.strip("(").strip()
		toks = bswap_func_name.split("_")
		input_bit_width = int(toks[1])
		result_width = input_bit_width		
		result_t = "uint" + str(result_width) + "_t"
		in_prefix = "uint" + str(input_bit_width)
		in_t = in_prefix + "_t"
		func_name = bswap_func_name
		text += '''
// BYTE SWAP
''' + result_t + " " + func_name + "("+ in_t + ''' x)
{
	//TODO
}
'''


	
	#print "BIT_MANIP_HEADER_FILE"
	#print text

	
	#Just bit manip for now
	outfile = BIT_MANIP_HEADER_FILE
	# "GET_SW_FUNC_NAME_LOGIC_LOOKUP outfile",outfile
	
	# Parse the c doe to logic lookup
	parser_state = C_TO_LOGIC.ParserState()	
	parse_body = False # SINCE BIT MANIP IGNORES SW IMPLEMENTATION
	func_name_2_logic = C_TO_LOGIC.GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(text, outfile, parser_state, parse_body)
	return func_name_2_logic


def GENERATE_INT_N_HEADERS(max_bit_width=256):
	text = ""
	text += "#include <stdint.h>\n"
	
	# Do signed and unsigned
	for u in ["","u"]: 
		min_width = 1
		if u=="":
			min_width = 2
		for bitwidth in range(min_width,max_bit_width+1):
			standard_type = u + "int8_t"
			if bitwidth > 8:
				standard_type = u + "int16_t"
			if bitwidth > 16:
				standard_type = u + "int32_t"
			if bitwidth > 32:
				standard_type = u + "int64_t"
				
			the_type = u + "int" + str(bitwidth) + "_t"
			
			# Comment out standard types
			if the_type == standard_type:
				text += "//"
			
			text += "typedef " + standard_type + " " + the_type + ";\n"
	
		filename = u + "intN_t.h"
		f=open(filename,"w")
		f.write(text)
		f.close()
		
		
def GET_BIN_OP_SR_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]	
	
	# THIS CODE ASSUMES NON CONST/ is dumb to use as non const
	left_input_wire = partially_complete_logic.inst_name + C_TO_LOGIC.SUBMODULE_MARKER + partially_complete_logic.inputs[0]
	right_input_wire = partially_complete_logic.inst_name + C_TO_LOGIC.SUBMODULE_MARKER + partially_complete_logic.inputs[1]
	left_const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(left_input_wire, containing_func_logic)
	right_const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(right_input_wire, containing_func_logic)
	if not(left_const_driving_wire is None) or not(right_const_driving_wire is None):
		print "SW defined constant shift right?"
		sys.exit(0)
	
	if VHDL.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
		return GET_BIN_OP_SR_UINT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state)
	else:
		print "GET_BIN_OP_SR_C_CODE Only sr between uint for now!"
		sys.exit(0)
		
def GET_BIN_OP_SL_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]	
	
	# THIS CODE ASSUMES NON CONST/ is dumb to use as non const
	left_input_wire = partially_complete_logic.inst_name + C_TO_LOGIC.SUBMODULE_MARKER + partially_complete_logic.inputs[0]
	right_input_wire = partially_complete_logic.inst_name + C_TO_LOGIC.SUBMODULE_MARKER + partially_complete_logic.inputs[1]
	left_const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(left_input_wire, containing_func_logic)
	right_const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(right_input_wire, containing_func_logic)
	if not(left_const_driving_wire is None) or not(right_const_driving_wire is None):
		print "SW defined constant shift left?"
		sys.exit(0)
	
	if VHDL.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
		return GET_BIN_OP_SL_UINT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state)
	else:
		print "GET_BIN_OP_SL_C_CODE Only sl between uint for now!"
		sys.exit(0)	
			
def GET_BIN_OP_PLUS_C_CODE(partially_complete_logic, out_dir):
	# If one of inputs is signed int then other input will be bit extended to include positive sign bit
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]	
	if VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs, "float", partially_complete_logic):
		return GET_BIN_OP_PLUS_FLOAT_C_CODE(partially_complete_logic, out_dir)
	else:
		print "GET_BIN_OP_PLUS_C_CODE Only plus between float for now!"
		sys.exit(0)

def GET_BIN_OP_MINUS_C_CODE(partially_complete_logic, out_dir):
	# If one of inputs is signed int then other input will be bit extended to include positive sign bit
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]	
	if VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs, "float", partially_complete_logic):
		return GET_BIN_OP_MINUS_FLOAT_C_CODE(partially_complete_logic, out_dir)
	else:
		print "GET_BIN_OP_MINUS_C_CODE Only plus between float for now!"
		sys.exit(0)

	
def GET_BIN_OP_DIV_C_CODE(partially_complete_logic, out_dir):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]	
	if VHDL.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
		return GET_BIN_OP_DIV_UINT_N_C_CODE(partially_complete_logic, out_dir)
	elif VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs,"float",partially_complete_logic):
		return GET_BIN_OP_DIV_FLOAT_N_C_CODE(partially_complete_logic, out_dir)
	else:
		print "GET_BIN_OP_DIV_C_CODE Only div between uint for now!"
		sys.exit(0)
		
		
def GET_BIN_OP_MULT_C_CODE(partially_complete_logic, out_dir, parser_state):
	# If one of inputs is signed int then other input will be bit extended to include positive sign bit
	# TODO signed mult
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]	
	if VHDL.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
		return GET_BIN_OP_MULT_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state)
	elif VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs,"float",partially_complete_logic):
		return GET_BIN_OP_MULT_FLOAT_N_C_CODE(partially_complete_logic, out_dir)
	elif VHDL.WIRES_ARE_INT_N(partially_complete_logic.inputs, partially_complete_logic):
		return GET_BIN_OP_MULT_INT_N_C_CODE(partially_complete_logic, out_dir)
	else:
		print "GET_BIN_OP_MULT_C_CODE Only mult between uint and float for now!"
		sys.exit(0)
		
def GET_BIN_OP_PLUS_FLOAT_C_CODE(partially_complete_logic, out_dir):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	if not VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs + partially_complete_logic.outputs,"float",partially_complete_logic):
		print '''"left_t != "float" or  right_t != "float" output_t too  for plus'''
		sys.exit(0)
	
	left_width = 32
	right_width = 32
	output_width = 32
	
	mantissa_range = [22,0]
	mantissa_width = mantissa_range[0] - mantissa_range[1] + 1
	exponent_range = [30,23]
	exponent_width = exponent_range[0] - exponent_range[1] + 1
	sign_index = 31
	
	mantissa_w_hidden_bit_width = mantissa_width + 1 # 24
	mantissa_w_hidden_bit_sign_adj_width = mantissa_w_hidden_bit_width + 1 #25
	sum_mantissa_width = mantissa_w_hidden_bit_sign_adj_width + 1 #26
	leading_zeros_width = int(math.ceil(math.log(mantissa_width+1,2.0)))

	text = ''''''
	text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "bit_math.h"

// Float adds std_logic_vector in VHDL
// Adds are complicated
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Get exponent for left and right
	uint''' + str(exponent_width) + '''_t left_exponent;
	left_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
	uint''' + str(exponent_width) + '''_t right_exponent;
	right_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
		
	float x;
	float y;
	// Step 1: Copy inputs so that left's exponent >= than right's.
	// ?????????MAYBE TODO: 
	//		Is this only needed for shift operation that takes unsigned only?
	// 		ALLOW SHIFT BY NEGATIVE?????
	//		OR NO since that looses upper MSBs of mantissa which not acceptable? IDK too many drinks
	if ( right_exponent > left_exponent ) // Lazy switch to GT
	{
	   x = right;  
	   y = left;
	}
	else
	{ 
	   x = left;
	   y = right;
	}
	
	// Step 2: Break apart into S E M
	// X
	uint''' + str(mantissa_width) + '''_t x_mantissa;	
	x_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(x);
	uint''' + str(exponent_width) + '''_t x_exponent;
	x_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(x);
	uint1_t x_sign;
	x_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(x);
	// Y
	uint''' + str(mantissa_width) + '''_t y_mantissa;
	y_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(y);
	uint''' + str(exponent_width) + '''_t y_exponent;
	y_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(y);
	uint1_t y_sign;
	y_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(y);
	
	// Mantissa needs +3b wider
	// 	[sign][overflow][hidden][23 bit mantissa]
	// Put 0's in overflow bit and sign bit
	// Put a 1 hidden bit if exponent is non-zero.
	// X
	// Determine hidden bit
	uint1_t x_hidden_bit;
	if(x_exponent == 0) // lazy swith to ==
	{
		x_hidden_bit = 0;
	}
	else
	{
		x_hidden_bit = 1;
	}
	// Apply hidden bit
	uint''' + str(mantissa_w_hidden_bit_width) + '''_t x_mantissa_w_hidden_bit; 
	x_mantissa_w_hidden_bit = uint1_uint''' + str(mantissa_width) + '''(x_hidden_bit, x_mantissa);
	// Y
	// Determine hidden bit
	uint1_t y_hidden_bit;
	if(y_exponent == 0) // lazy swith to ==
	{
		y_hidden_bit = 0;
	}
	else
	{
		y_hidden_bit = 1;
	}
	// Apply hidden bit
	uint''' + str(mantissa_w_hidden_bit_width) + '''_t y_mantissa_w_hidden_bit; 
	y_mantissa_w_hidden_bit = uint1_uint''' + str(mantissa_width) + '''(y_hidden_bit, y_mantissa);

	// Step 3: Un-normalize Y (including hidden bit) so that xexp == yexp.
	// Already swapped left/right based on exponent
	// diff will be >= 0
	uint''' + str(exponent_width) + '''_t diff;
	diff = x_exponent - y_exponent;
	// Shift y by diff (bit manip pipelined function)
	uint''' + str(mantissa_w_hidden_bit_width) + '''_t y_mantissa_w_hidden_bit_unnormalized;
	y_mantissa_w_hidden_bit_unnormalized = y_mantissa_w_hidden_bit >> diff;
	
	// Step 4: If necessary, negate mantissas (twos comp) such that add makes sense
	// STEP 2.B moved here
	// Make wider for twos comp/sign
	int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''_t x_mantissa_w_hidden_bit_sign_adj;
	int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''_t y_mantissa_w_hidden_bit_sign_adj;
	if(x_sign) //if(x_sign == 1)
	{
		x_mantissa_w_hidden_bit_sign_adj = uint''' + str(mantissa_w_hidden_bit_width) + '''_negate(x_mantissa_w_hidden_bit); //Returns +1 wider signed, int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''t
	}
	else
	{
		x_mantissa_w_hidden_bit_sign_adj = x_mantissa_w_hidden_bit;
	}
	if(y_sign) // if(y_sign == 1)
	{
		y_mantissa_w_hidden_bit_sign_adj = uint''' + str(mantissa_w_hidden_bit_width) + '''_negate(y_mantissa_w_hidden_bit_unnormalized);
	}
	else
	{
		y_mantissa_w_hidden_bit_sign_adj = y_mantissa_w_hidden_bit_unnormalized;
	}
	
	// Step 5: Compute sum 
	int''' + str(sum_mantissa_width) + '''_t sum_mantissa;
	sum_mantissa = x_mantissa_w_hidden_bit_sign_adj + y_mantissa_w_hidden_bit_sign_adj;

	// Step 6: Save sign flag and take absolute value of sum.
	uint1_t sum_sign;
	sum_sign = int''' + str(sum_mantissa_width) + '''_''' + str(sum_mantissa_width-1) + '''_''' + str(sum_mantissa_width-1) + '''(sum_mantissa);
	uint''' + str(sum_mantissa_width) + '''_t sum_mantissa_unsigned;
	sum_mantissa_unsigned = int''' + str(sum_mantissa_width) + '''_abs(sum_mantissa);

	// Step 7: Normalize sum and exponent. (Three cases.)
	uint1_t sum_overflow;
	sum_overflow = uint''' + str(sum_mantissa_width) + '''_''' + str(mantissa_w_hidden_bit_sign_adj_width-1) + '''_''' + str(mantissa_w_hidden_bit_sign_adj_width-1) + '''(sum_mantissa_unsigned);
	uint''' + str(exponent_width) + '''_t sum_exponent_normalized;
	uint''' + str(mantissa_width) + '''_t sum_mantissa_unsigned_normalized;
	if (sum_overflow) //if ( sum_overflow == 1 )
	{
	   // Case 1: Sum overflow.
	   //         Right shift significand by 1 and increment exponent.
	   sum_exponent_normalized = x_exponent + 1;
	   sum_mantissa_unsigned_normalized = uint''' + str(sum_mantissa_width) + '''_''' + str(mantissa_range[0]+1) + '''_''' + str(mantissa_range[1]+1) + '''(sum_mantissa_unsigned);
	}
    else if(sum_mantissa_unsigned == 0) // laxy switch to ==
    {
	   //
	   // Case 3: Sum is zero.
	   sum_exponent_normalized = 0;
	   sum_mantissa_unsigned_normalized = 0;
	}
	else
	{
	   // Case 2: Sum is nonzero and did not overflow.
	   // Dont waste zeros at start of mantissa
	   // Find position of first non-zero digit from left
	   // Know bit25(sign) and bit24(overflow) are not set
	   // Hidden bit is [23], can narrow down to 24b wide including hidden bit 
	   uint''' + str(mantissa_w_hidden_bit_width) + '''_t sum_mantissa_unsigned_narrow;
	   sum_mantissa_unsigned_narrow = sum_mantissa_unsigned;
	   uint''' + str(leading_zeros_width) + '''_t leading_zeros; // width = ceil(log2(len(sumsig)))
	   leading_zeros = count0s_uint''' + str(mantissa_w_hidden_bit_width) + '''(sum_mantissa_unsigned_narrow); // Count from left/msbs downto, uintX_count0s counts from right
	   // NOT CHECKING xexp < adj
	   // Case 2b: Adjust significand and exponent.
	   sum_exponent_normalized = x_exponent - leading_zeros;
	   sum_mantissa_unsigned_normalized = sum_mantissa_unsigned_narrow << leading_zeros;
    }
	
	// Declare the output portions
	uint''' + str(mantissa_width) + '''_t z_mantissa;
	uint''' + str(exponent_width) + '''_t z_exponent;
	uint1_t z_sign;
	z_sign = sum_sign;
	z_exponent = sum_exponent_normalized;
	z_mantissa = sum_mantissa_unsigned_normalized;
	// Assemble output	
	return float_uint1_uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

	#print "C CODE"
	#print text

	return text
	
def GET_BIN_OP_GT_GTE_C_CODE(partially_complete_logic, out_dir, op_str):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]	
	if VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs,"float",partially_complete_logic):
		return GET_BIN_OP_GT_GTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str)
	else:
		print "GET_BIN_OP_GT_GTE_C_CODE Only between float for now!"
		sys.exit(0)
	
# GT/GTE
def GET_BIN_OP_GT_GTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	if not VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs ,"float",partially_complete_logic):
		print '''"left_t != "float" or  right_t != "float" for >= '''
	# Output must be bool
	if output_t != "uint1_t":
		print "GET_BIN_OP_GT_GTE_FLOAT_C_CODE output_t != uint1_t"
		sys.exit(0)
	
	left_width = 32
	right_width = 32
	
	mantissa_range = [22,0]
	mantissa_width = mantissa_range[0] - mantissa_range[1] + 1
	exponent_range = [30,23]
	exponent_width = exponent_range[0] - exponent_range[1] + 1
	sign_index = 31
	
	abs_val_width = exponent_width + mantissa_width
	abs_val_prefix = "uint" + str(abs_val_width)
	abs_val_t = abs_val_prefix + "_t"
	

	text = ''''''
	text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"

// Float GT/GTE std_logic_vector in VHDL
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// LEFT
	uint''' + str(mantissa_width) + '''_t left_mantissa;	
	left_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
	uint''' + str(exponent_width) + '''_t left_exponent;
	left_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
	uint1_t left_sign;
	left_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
	// RIGHT
	uint''' + str(mantissa_width) + '''_t right_mantissa;
	right_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(right);
	uint''' + str(exponent_width) + '''_t right_exponent;
	right_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
	uint1_t right_sign;
	right_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
	
	// Do abs value compare by using exponent as msbs
	// 	(-1)^s    * m  *   2^(e - 127)
	''' + abs_val_t + ''' left_abs;
	left_abs = uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(left_exponent, left_mantissa);
	''' + abs_val_t + ''' right_abs;
	right_abs = uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(right_exponent, right_mantissa);'''
	
	# if both neg then 
	# Switches GT->LT(=flip args GTE), GTE->LTE(flipped args GT)
	if op_str == ">":
		flipped_op_str = ">="
	else:
		# op str >=
		flipped_op_str = ">"
	
	text += '''
	// Adjust for sign
	uint1_t rv;
	uint1_t same_sign;
	same_sign = left_sign == right_sign;
	uint1_t pos_signs;
	uint1_t neg_signs;
	neg_signs = left_sign; // Only used if same sign
	pos_signs = !left_sign; // Only used if same sign
	if(same_sign & pos_signs)
	{
		rv = left_abs ''' + op_str + ''' right_abs;
	}
	else if(same_sign & neg_signs)
	{
		// Switches GT->LT(=flip args GTE), GTE->LTE(flipped args GT)
		rv = right_abs ''' + flipped_op_str + ''' left_abs;
	}
	else
	{
		// NOT SAME SIGN so can never equal ( but op is GT or GTE so GT is important part)
		// left must be pos to be GT (neg)right 
		rv = right_sign; // right_sign=1, left_sign=0 right is neg, can never GT left so true
	}

	return rv;
}'''

	#print "C CODE"
	#print text

	return text
	
	
def GET_BIN_OP_MINUS_FLOAT_C_CODE(partially_complete_logic, out_dir):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	if not VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs + partially_complete_logic.outputs,"float",partially_complete_logic):
		print '''"left_t != "float" or  right_t != "float" output_t too  for minus'''
		sys.exit(0)
	
	left_width = 32
	right_width = 32
	output_width = 32
	
	mantissa_range = [22,0]
	mantissa_width = mantissa_range[0] - mantissa_range[1] + 1
	exponent_range = [30,23]
	exponent_width = exponent_range[0] - exponent_range[1] + 1
	sign_index = 31
	
	mantissa_w_hidden_bit_width = mantissa_width + 1 # 24
	mantissa_w_hidden_bit_sign_adj_width = mantissa_w_hidden_bit_width + 1 #25
	sum_mantissa_width = mantissa_w_hidden_bit_sign_adj_width + 1 #26
	leading_zeros_width = int(math.ceil(math.log(mantissa_width+1,2.0)))

	text = ''''''
	text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "bit_math.h"

// Float minus std_logic_vector in VHDL
// Minus is as complicated as add?
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Get exponent for left and right
	uint''' + str(exponent_width) + '''_t left_exponent;
	left_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
	uint''' + str(exponent_width) + '''_t right_exponent;
	right_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
		
	float x;
	float y;
	// Step 1: Copy inputs so that left's exponent >= than right's.
	// ?????????MAYBE TODO: 
	//		Is this only needed for shift operation that takes unsigned only?
	// 		ALLOW SHIFT BY NEGATIVE?????
	//		OR NO since that looses upper MSBs of mantissa which not acceptable? IDK too many drinks
	uint1_t do_swap;
	do_swap = right_exponent > left_exponent; // Lazy switch to GT
	if ( do_swap ) 
	{
	   x = right;  
	   y = left;
	}
	else
	{ 
	   x = left;
	   y = right;
	}
	
	// Step 2: Break apart into S E M
	// X
	uint''' + str(mantissa_width) + '''_t x_mantissa;	
	x_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(x);
	uint''' + str(exponent_width) + '''_t x_exponent;
	x_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(x);
	uint1_t left_sign;
	left_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
	// Y
	uint''' + str(mantissa_width) + '''_t y_mantissa;
	y_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(y);
	uint''' + str(exponent_width) + '''_t y_exponent;
	y_exponent = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(y);
	uint1_t right_sign;
	right_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
	
	
	// SUBTRACT FLIP SIGN IF LR SWAP AND SIGNS EQUAL
	uint1_t x_sign;
	uint1_t y_sign;
	// +1.23 - +4.56 = -4.56 - -1.23     11 00
	// -1.23 - -4.56 = +4.56 - +1.23     00 11
	// -1.23 - +4.56 = -4.56 - +1.23     01 01
	// +1.23 - -4.56 = +4.56 - -1.23     10 10
	// If signs are equal and did swap then invert both
	uint1_t signs_eq;
	signs_eq = left_sign == right_sign;
	if(signs_eq & do_swap) // OK to do bit and
	{
		x_sign = !left_sign;
		y_sign = !right_sign;
	}
	else
	{
		// No swap or signs unequal : then keep orig left/right sign
		x_sign = left_sign;
		y_sign = right_sign;
	}

	
	// Mantissa needs +3b wider
	// 	[sign][overflow][hidden][23 bit mantissa]
	// Put 0's in overflow bit and sign bit
	// Put a 1 hidden bit if exponent is non-zero.
	// X
	// Determine hidden bit
	uint1_t x_hidden_bit;
	if(x_exponent == 0) // lazy swith to ==
	{
		x_hidden_bit = 0;
	}
	else
	{
		x_hidden_bit = 1;
	}
	// Apply hidden bit
	uint''' + str(mantissa_w_hidden_bit_width) + '''_t x_mantissa_w_hidden_bit; 
	x_mantissa_w_hidden_bit = uint1_uint''' + str(mantissa_width) + '''(x_hidden_bit, x_mantissa);
	// Y
	// Determine hidden bit
	uint1_t y_hidden_bit;
	if(y_exponent == 0) // lazy swith to ==
	{
		y_hidden_bit = 0;
	}
	else
	{
		y_hidden_bit = 1;
	}
	// Apply hidden bit
	uint''' + str(mantissa_w_hidden_bit_width) + '''_t y_mantissa_w_hidden_bit; 
	y_mantissa_w_hidden_bit = uint1_uint''' + str(mantissa_width) + '''(y_hidden_bit, y_mantissa);

	// Step 3: Un-normalize Y (including hidden bit) so that xexp == yexp.
	// Already swapped left/right based on exponent
	// diff will be >= 0
	uint''' + str(exponent_width) + '''_t diff;
	diff = x_exponent - y_exponent;
	// Shift y by diff (bit manip pipelined function)
	uint''' + str(mantissa_w_hidden_bit_width) + '''_t y_mantissa_w_hidden_bit_unnormalized;
	y_mantissa_w_hidden_bit_unnormalized = y_mantissa_w_hidden_bit >> diff;
	
	// Step 4: If necessary, negate mantissas (twos comp) such that add makes sense
	// STEP 2.B moved here
	// Make wider for twos comp/sign
	int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''_t x_mantissa_w_hidden_bit_sign_adj;
	int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''_t y_mantissa_w_hidden_bit_sign_adj;
	if(x_sign) //if(x_sign == 1)
	{
		x_mantissa_w_hidden_bit_sign_adj = uint''' + str(mantissa_w_hidden_bit_width) + '''_negate(x_mantissa_w_hidden_bit); //Returns +1 wider signed, int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''t
	}
	else
	{
		x_mantissa_w_hidden_bit_sign_adj = x_mantissa_w_hidden_bit;
	}
	if(y_sign) //y_sign == 1
	{
		y_mantissa_w_hidden_bit_sign_adj = uint''' + str(mantissa_w_hidden_bit_width) + '''_negate(y_mantissa_w_hidden_bit_unnormalized);
	}
	else
	{
		y_mantissa_w_hidden_bit_sign_adj = y_mantissa_w_hidden_bit_unnormalized;
	}
	
	// Step 5: Compute subtraction 
	int''' + str(sum_mantissa_width) + '''_t sum_mantissa;
	sum_mantissa = x_mantissa_w_hidden_bit_sign_adj - y_mantissa_w_hidden_bit_sign_adj;

	// Step 6: Save sign flag and take absolute value of sum.
	uint1_t sum_sign;
	sum_sign = int''' + str(sum_mantissa_width) + '''_''' + str(sum_mantissa_width-1) + '''_''' + str(sum_mantissa_width-1) + '''(sum_mantissa);
	uint''' + str(sum_mantissa_width) + '''_t sum_mantissa_unsigned;
	sum_mantissa_unsigned = int''' + str(sum_mantissa_width) + '''_abs(sum_mantissa);

	// Step 7: Normalize sum and exponent. (Three cases.)
	uint1_t sum_overflow;
	sum_overflow = uint''' + str(sum_mantissa_width) + '''_''' + str(mantissa_w_hidden_bit_sign_adj_width-1) + '''_''' + str(mantissa_w_hidden_bit_sign_adj_width-1) + '''(sum_mantissa_unsigned);
	uint''' + str(exponent_width) + '''_t sum_exponent_normalized;
	uint''' + str(mantissa_width) + '''_t sum_mantissa_unsigned_normalized;
	if(sum_overflow) //if ( sum_overflow == 1 )
	{
	   // Case 1: Sum overflow.
	   //         Right shift significand by 1 and increment exponent.
	   sum_exponent_normalized = x_exponent + 1;
	   sum_mantissa_unsigned_normalized = uint''' + str(sum_mantissa_width) + '''_''' + str(mantissa_range[0]+1) + '''_''' + str(mantissa_range[1]+1) + '''(sum_mantissa_unsigned);
	}
    else if(sum_mantissa_unsigned == 0) // laxy switch to ==
    {
	   //
	   // Case 3: Sum is zero.
	   sum_exponent_normalized = 0;
	   sum_mantissa_unsigned_normalized = 0;
	}
	else
	{
	   // Case 2: Sum is nonzero and did not overflow.
	   // Dont waste zeros at start of mantissa
	   // Find position of first non-zero digit from left
	   // Know bit25(sign) and bit24(overflow) are not set
	   // Hidden bit is [23], can narrow down to 24b wide including hidden bit 
	   uint''' + str(mantissa_w_hidden_bit_width) + '''_t sum_mantissa_unsigned_narrow;
	   sum_mantissa_unsigned_narrow = sum_mantissa_unsigned;
	   uint''' + str(leading_zeros_width) + '''_t leading_zeros; // width = ceil(log2(len(sumsig)))
	   leading_zeros = count0s_uint''' + str(mantissa_w_hidden_bit_width) + '''(sum_mantissa_unsigned_narrow); // Count from left/msbs downto, uintX_count0s counts from right
	   // NOT CHECKING xexp < adj
	   // Case 2b: Adjust significand and exponent.
	   sum_exponent_normalized = x_exponent - leading_zeros;
	   sum_mantissa_unsigned_normalized = sum_mantissa_unsigned_narrow << leading_zeros;
    }
	
	// Declare the output portions
	uint''' + str(mantissa_width) + '''_t z_mantissa;
	uint''' + str(exponent_width) + '''_t z_exponent;
	uint1_t z_sign;
	z_sign = sum_sign;
	z_exponent = sum_exponent_normalized;
	z_mantissa = sum_mantissa_unsigned_normalized;
	// Assemble output	
	return float_uint1_uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

	#print "C CODE"
	#print text

	return text	
	
	
def GET_BIN_OP_DIV_FLOAT_N_C_CODE(partially_complete_logic, out_dir):
	# Taking this directly from the 1 clock version VHDL from
	'''
	-- Company: Instituto Superior Tecnico
	-- Prof: Paulo Alexandre Crisostomo Lopes
	-- paulo.lopes@inesc-id.pt
	'''
	# Can improve in future
	# Thanks man
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	if not VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs + partially_complete_logic.outputs,"float",partially_complete_logic):
		print '''"left_t != "float" or  right_t != "float" output_t too'''
		sys.exit(0)
	
	left_width = 32
	right_width = 32
	output_width = 32
	
	mantissa_range = [22,0]
	mantissa_width = mantissa_range[0] - mantissa_range[1] + 1
	mantissa_t_prefix = "uint" + str(mantissa_width)
	mantissa_t = mantissa_t_prefix + "_t"
	exponent_range = [30,23]
	exponent_width = exponent_range[0] - exponent_range[1] + 1
	exponent_t_prefix = "uint" + str(exponent_width)
	exponent_t = exponent_t_prefix + "_t"
	exponent_width_plus1 = exponent_width + 1
	exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
	exponent_wide_t = exponent_wide_t_prefix + "_t"
	exponent_bias_to_add = int(math.pow(2,exponent_width-1) - 1)
	exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
	sign_index = 31
	sign_width = 1
	sign_t_prefix = "uint" + str(sign_width)
	sign_t = sign_t_prefix + "_t"
	
	a_width = mantissa_width + 3
	a_prefix = "uint" + str(a_width)
	a_t = a_prefix + "_t"
	
	remainder_width = mantissa_width + 2
	remainder_prefix = "uint" + str(remainder_width)
	remainder_t = remainder_prefix + "_t"
	
	tmp_remainder_width = mantissa_width + 2
	tmp_remainder_prefix = "uint" + str(tmp_remainder_width)
	tmp_remainder_t = tmp_remainder_prefix + "_t"
	
	exponent_aux_width = exponent_width + 1
	exponent_aux_t_prefix = "uint" + str(exponent_aux_width)
	exponent_aux_t = exponent_aux_t_prefix + "_t"
	
	mantissa_w_extra_bit_width = mantissa_width + 2
	mantissa_w_extra_bit_prefix = "uint" + str(mantissa_w_extra_bit_width)
	mantissa_w_extra_bit_t = mantissa_w_extra_bit_prefix + "_t"
	
	
	text = ""
	
	text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// Float div std_logic_vector in VHDL
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Get mantissa exponent and sign for both
	// LEFT
	''' + mantissa_t + ''' x_mantissa;
	x_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
	''' + exponent_wide_t + ''' x_exponent_wide;
	x_exponent_wide = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
	''' + sign_t + ''' x_sign;
	x_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
	// RIGHT
	''' + mantissa_t + ''' y_mantissa;
	y_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(right);
	''' + exponent_wide_t + ''' y_exponent_wide;
	y_exponent_wide = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
	''' + sign_t + ''' y_sign;
	y_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
	
	// Delcare intermediates
	''' + a_t + ''' a;
	a = 0;
	''' + remainder_t + ''' partial_remainder;
	partial_remainder = 0;
	''' + remainder_t + ''' tmp_remainder;
	tmp_remainder = 0;
	''' + exponent_aux_t + ''' exponent_aux;
	exponent_aux = 0;
	''' + mantissa_w_extra_bit_t + ''' x_mantissa_w_extra_bit;
	x_mantissa_w_extra_bit = 0;
	''' + mantissa_w_extra_bit_t + ''' y_mantissa_w_extra_bit;
	y_mantissa_w_extra_bit = 0;
	uint1_t a_i;
	a_i = 0;
	
	// Mantissas with extra bit
	x_mantissa_w_extra_bit = uint2_''' + mantissa_t_prefix + '''(1,x_mantissa);
	y_mantissa_w_extra_bit = uint2_''' + mantissa_t_prefix + '''(1,y_mantissa);
	
	// BIAS CONST
	''' + exponent_bias_t + ''' BIAS;
	BIAS = ''' + str(exponent_bias_to_add) + ''';
	
	// Declare the output portions
	''' + mantissa_t + ''' z_mantissa;
	''' + exponent_t + ''' z_exponent;
	''' + sign_t + ''' z_sign;
	
	// Sign
	z_sign = x_sign ^ y_sign;
	
	// Initial exponent sub and add bias
	exponent_aux = x_exponent_wide - y_exponent_wide;
	exponent_aux = exponent_aux + BIAS;
	
	// Divide unrolled since isnt simple unsigned div of mantissa
	partial_remainder = x_mantissa_w_extra_bit;'''
	for i in range(a_width-1, -1, -1):
		text += '''
	// Bit ''' + str(i) + '''
	/*
	    tmp_remainder := partial_remainder - y_mantissa_w_extra_bit;
		if ( tmp_remainder(24)='0' ) then 
			-- result is non negative: partial_remainder >= y_mantissa_w_extra_bit
			-- note that tmp_remainder < 2 so bit 24 should be zero
			a(i):='1';
			partial_remainder := tmp_remainder;
		else
			a(i):='0'
		end if;
		partial_remainder := partial_remainder(23 downto 0) & '0'; -- sll
	*/
	tmp_remainder = partial_remainder - y_mantissa_w_extra_bit;
	if(''' + remainder_prefix + '''_''' + str(remainder_width-1) + '''_''' + str(remainder_width-1) + '''(tmp_remainder) == 0 )
	{
		// result is non negative: partial_remainder >= y_mantissa_w_extra_bit
		// note that tmp_remainder < 2 so bit 24 should be zero
		a_i = 1;
		partial_remainder = tmp_remainder;
	}
	else
	{
		a_i = 0;
		partial_remainder = partial_remainder; // No change
	}
	partial_remainder = ''' + remainder_prefix + '''_uint1(partial_remainder, 0); // sll
	
	// Assign a(i)
	a = ''' + a_prefix + '''_uint1_'''+str(i)+'''(a,a_i);
	'''
	
	
	text += '''	
	/////////////////////
	// END OF DIV LOOP
	//////////////////////
	
	// NO ROUND
	
	if(''' + a_prefix + '''_''' + str(a_width-1) + '''_''' + str(a_width-1) + '''(a)) //== 1)
	{
		z_mantissa = ''' + a_prefix + '''_''' + str(a_width-2) + '''_2(a);
		exponent_aux = exponent_aux; // No change
	}
	else
	{
		z_mantissa = ''' + a_prefix + '''_''' + str(a_width-3) + '''_1(a);
		exponent_aux = exponent_aux - 1;
	}
	
	z_exponent = ''' + exponent_aux_t_prefix + '''_''' + str(exponent_width-1) + '''_0(exponent_aux);	
	
	// Assemble output
	return float_uint''' + str(sign_width) + '''_uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

	#print "C CODE"
	#print text

	return text
	
def GET_BIN_OP_MULT_FLOAT_N_C_CODE(partially_complete_logic, out_dir):
	# Taking this directly from the 1 clock version VHDL from
	'''
	-- Company: Instituto Superior Tecnico
	-- Prof: Paulo Alexandre Crisostomo Lopes
	-- paulo.lopes@inesc-id.pt
	'''
	# Can improve in future
	# Thanks man
	
	
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	if not VHDL.WIRES_ARE_C_TYPE(partially_complete_logic.inputs + partially_complete_logic.outputs,"float",partially_complete_logic):
		print '''"left_t != "float" or  right_t != "float" output_t too'''
		sys.exit(0)
	
	left_width = 32
	right_width = 32
	output_width = 32
	
	mantissa_range = [22,0]
	mantissa_width = mantissa_range[0] - mantissa_range[1] + 1
	mantissa_t_prefix = "uint" + str(mantissa_width)
	mantissa_t = mantissa_t_prefix + "_t"
	exponent_range = [30,23]
	exponent_width = exponent_range[0] - exponent_range[1] + 1
	exponent_t_prefix = "uint" + str(exponent_width)
	exponent_t = exponent_t_prefix + "_t"
	exponent_width_plus1 = exponent_width + 1
	exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
	exponent_wide_t = exponent_wide_t_prefix + "_t"
	exponent_bias_to_sub = int(math.pow(2,exponent_width-1) - 1)
	exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
	sign_index = 31
	sign_width = 1
	sign_t_prefix = "uint" + str(sign_width)
	sign_t = sign_t_prefix + "_t"
	aux_width = 1
	aux_t_prefix = "uint" + str(aux_width)
	aux_t = aux_t_prefix + "_t"
	aux2_width = (mantissa_width+1)*2 # 48 for fp32
	aux2_t_prefix = "uint" + str(aux2_width)
	aux2_t = aux2_t_prefix + "_t"
	aux2_in_width = (mantissa_width+1)
	aux2_in_t_prefix = "uint" + str(aux2_in_width)
	aux2_in_t = aux2_in_t_prefix + "_t"
	exponent_sum_width = exponent_width + 1
	exponent_sum_t_prefix = "uint" + str(exponent_sum_width)
	exponent_sum_t = exponent_sum_t_prefix + "_t"
	'''
	e_m_width = exponent_width + mantissa_width
	e_m_t_prefix = "uint" + str(e_m_width)
	e_m_t = e_m_t_prefix + "_t"
	s_e_m_width = sign_width + e_m_width
	s_e_m_t_prefix = "uint" + str(s_e_m_width)
	s_e_m_t = s_e_m_t_prefix + "_t"
	'''
	
	
	text = ""
	
	text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// Float mult std_logic_vector in VHDL
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Get mantissa exponent and sign for both
	// LEFT
	''' + mantissa_t + ''' x_mantissa;
	x_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
	''' + exponent_wide_t + ''' x_exponent_wide;
	x_exponent_wide = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
	''' + sign_t + ''' x_sign;
	x_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
	// RIGHT
	''' + mantissa_t + ''' y_mantissa;
	y_mantissa = float_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(right);
	''' + exponent_wide_t + ''' y_exponent_wide;
	y_exponent_wide = float_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
	''' + sign_t + ''' y_sign;
	y_sign = float_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
	
	// Delcare intermediates
	''' + aux_t + ''' aux;
	''' + aux2_in_t + ''' aux2_x;
	''' + aux2_in_t + ''' aux2_y;
	''' + aux2_t + ''' aux2;
	''' + exponent_bias_t + ''' BIAS;
	BIAS = ''' + str(exponent_bias_to_sub) + ''';
	''' + exponent_sum_t + ''' exponent_sum;
	
	// Declare the output portions
	''' + mantissa_t + ''' z_mantissa;
	''' + exponent_t + ''' z_exponent;
	''' + sign_t + ''' z_sign;
	
	// HACKY NOT CHECKING
	// if (x_exponent=255 or y_exponent=255) then
	// elsif (x_exponent=0 or y_exponent=0) then 
	aux2_x = uint1_''' + mantissa_t_prefix + '''(1, x_mantissa);
	aux2_y = uint1_''' + mantissa_t_prefix + '''(1, y_mantissa);
	aux2 =  aux2_x * aux2_y;
	// args in Q23 result in Q46
	aux = ''' + aux2_t_prefix + '''_''' + str(aux2_width-1) + '''_''' + str(aux2_width-1) + '''(aux2);
	if(aux) //if(aux == 1)
	{ 
		// >=2, shift left and add one to exponent
		// HACKY NO ROUNDING + aux2(23); // with round18
		z_mantissa = ''' + aux2_t_prefix + '''_''' + str(aux2_width-2) + '''_''' + str(aux2_width - mantissa_width -1) + '''(aux2); 
	}
	else
	{	
		// HACKY NO ROUNDING + aux2(22); // with rounding
		z_mantissa = ''' + aux2_t_prefix + '''_''' + str(aux2_width-3) + '''_''' + str(aux2_width - mantissa_width -2) + '''(aux2); 
	}
	
	// calculate exponent in parts 
	// do sequential unsigned adds and subs to avoid signed numbers for now
	// X and Y exponent are already 1 bit wider than needed
	// (0 & x_exponent) + (0 & y_exponent);
	exponent_sum = x_exponent_wide + y_exponent_wide;
	exponent_sum = exponent_sum + aux;
	exponent_sum = exponent_sum - BIAS;
	
	// HACKY NOT CHECKING
	// if (exponent_sum(8)='1') then
	z_exponent = ''' + exponent_sum_t_prefix + '''_''' + str(exponent_width-1) + '''_0(exponent_sum);
	z_sign = x_sign ^ y_sign;
	
	// Assemble output
	return float_uint''' + str(sign_width) + '''_uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

	#print "C CODE"
	#print text

	return text
	
	
def GET_BIN_OP_SR_UINT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)	
	output_prefix = "uint" + str(output_width)
	
	# TODO: FIX THIS
	# SHIFT WIDTH IS TRUNCATED TO 2^log2(math.ceil(math.log(max_shift+1,2))) -1
	# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
	
	
	# TODO: Remove 1 LL
	# return x0 << x1;  // First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs
	
	# Shift size is limited by width of left input
	max_shift = left_width
	shift_bit_width = int(math.ceil(math.log(max_shift+1,2)))
	# Shift amount is resized
	resized_prefix = "uint" + str(shift_bit_width)
	resized_t = resized_prefix + "_t"
	
	text = ""
	
	text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''shifted right by maximum ''' + str(max_shift) + '''b
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Resize the shift amount (right)
	''' + resized_t + ''' resized_shift_amount;
	resized_shift_amount = right;
	
	// Output
	''' + output_t + ''' rv;
	
	// Check for oversized and use N mux otherwise
	if(right > ''' + str(max_shift-1) + ''')
	{
		// Big shift, all zeros
		rv = 0;
	}
	else
	{
		// Otherwise use N mux
		// right < max_shift , right_max = max_shift-1
		// Append bits on left and select rv from MSBs
		rv = ''' + output_prefix + "_mux" + str(max_shift) + "(resized_shift_amount,"

	# Array of inputs to mux for each shift
	for shift in range(0, max_shift):
		interm_width = shift+left_width
		if shift == 0:
			text += '''
				left,'''
		else:
			text += '''
				uint'''+str(interm_width) + '''_''' + str(interm_width-1) + '''_''' + str(interm_width-left_width) + '''( uint''' + str(shift) + '''_uint''' + str(left_width) + '''(0,left) ),'''
		
	text = text.strip(",")
	text += '''
		);
	}
	return rv;
}'''
	#print "GET_BIN_OP_SR_UINT_C_CODE text"
	#print text
	#sys.exit(0)
	return text
	

#// 64B  First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs
#// 32B also 4 LLs?
#// 128B 8 LLs
def GET_BIN_OP_SL_UINT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)	
	output_prefix = "uint" + str(output_width)
	
	# TODO: FIX THIS
	# SHIFT WIDTH IS TRUNCATED TO 2^log2(math.ceil(math.log(max_shift+1,2))) -1
	# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
	
	
	# TODO: Remove 1 LL
	# return x0 << x1;  // First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs
	
	# Shift size is limited by width of left input
	max_shift = left_width
	shift_bit_width = int(math.ceil(math.log(max_shift+1,2)))
	# Shift amount is resized
	resized_prefix = "uint" + str(shift_bit_width)
	resized_t = resized_prefix + "_t"
	
	text = ""
	
	text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''shifted left by maximum ''' + str(max_shift) + '''b
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Resize the shift amount (right)
	''' + resized_t + ''' resized_shift_amount;
	resized_shift_amount = right;
	
	// Output
	''' + output_t + ''' rv;
	
	// Check for oversized and use N mux otherwise
	if(right > ''' + str(max_shift-1) + ''')
	{
		// Big shift, all zeros
		rv = 0;
	}
	else
	{
		// Otherwise use N mux
		rv = ''' + output_prefix + "_mux" + str(max_shift) + "(resized_shift_amount,"

	# Array of inputs to mux for each shift
	for shift in range(0, max_shift):
		if shift == 0:
			text += '''
				left,'''
		else:
			text += '''
				uint''' + str(left_width) + '''_uint''' + str(shift) + '''(left, 0),'''
		
	text = text.strip(",")
	text += '''
		);
	}
	return rv;
}'''


	#print "GET_BIN_OP_SL_UINT_C_CODE text"
	#print text
	
	return text
	
	

	
def GET_BIN_OP_MULT_INT_N_C_CODE(partially_complete_logic, out_dir):
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
	max_input_width = max(left_width,right_width)
	resized_prefix = "uint" + str(max_input_width)
	resized_t = resized_prefix + "_t"
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)	
	output_prefix = "uint" + str(output_width)
	
	# Temp try to reduce bit width?
	# Output width is max =  left_width+right_width
	# Actual max internal width is min out output width and max of input widths
	# Does not include output width because of sign for signed mult???
	# TODO: Check if can limit like UINT including output width
	max_intermidate_bit_width = left_width+right_width
	
	
	text = ""
	
	# Generate abs path to uint headers
	#top_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
	#uint_h ='''#include "''' + top_dir + '''/uintN_t.h"'''
	#int_h ='''#include "''' + top_dir + '''/intN_t.h"'''
	
	text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''b x ''' + str(right_width) + '''b mult
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Resize
	''' + resized_t + ''' left_resized;
	left_resized = left;
	''' + resized_t + ''' right_resized;
	right_resized = right;
	
	// Left repeated bit unsigneds
'''
	for rb in range(0,max_input_width):
		text += '''	// BIT''' + str(rb) + ''' REPEATED
	// Select bit
	uint1_t left''' + str(rb) + '''_x1;
	left''' + str(rb) + '''_x1 = ''' + resized_prefix + '''_''' + str(rb) + '''_''' + str(rb) + '''(left_resized);
	// Dup
	uint''' + str(max_input_width) + '''_t  left''' + str(rb) + '''_x''' + str(max_input_width) + ''';
	left''' + str(rb) + '''_x''' + str(max_input_width) + ''' = uint1_''' + str(max_input_width) + '''(left''' + str(rb) + '''_x1);
'''
	
	text += '''
	// Partial sums
'''
	for rb in range(0,max_input_width):
		text += "	" + resized_t + ''' p''' + str(rb) + ''';
	p''' + str(rb) + ''' = left''' + str(rb) + '''_x''' + str(max_input_width) + ''' & right_resized;
'''

	# Save types of shifted partial sum vars for ease later
	var_2_type = dict()
	
	text += '''
	// Shifted partial sums
	''' + resized_t + ''' p0_shifted;
	p0_shifted = p0;
'''
	var_2_type["p0_shifted"] = resized_t
	p_width = max_input_width
	for p in range(1,max_input_width):
		uintp_prefix = "uint" + str(p)
		uintp_t =  uintp_prefix + "_t"
		#p_width_minus1 = p_width - 1
		p_t_prefix = "uint" + str(p_width)
		p_shifted_t = "uint" + str(p_width + p) + "_t"
		p_shifted = '''p''' + str(p) + '''_shifted'''
		var_2_type[p_shifted] = p_shifted_t
		text += '''	''' + uintp_t + ''' zero_x''' + str(p) + ''';
	zero_x''' + str(p) + ''' = 0;
	''' + p_shifted_t + ''' p''' + str(p) + '''_shifted;
	p''' + str(p) + '''_shifted = ''' + p_t_prefix + '''_''' + uintp_prefix + '''(p''' + str(p) + ''' ,zero_x''' + str(p) + ''');
'''
	
	
	
	# Cap shifted partiual sums to max intermediate width
	max_intermidate_prefix = "uint" + str(max_intermidate_bit_width)
	max_intermidate_t = max_intermidate_prefix + "_t"
	
	# Do Signed trick with inverted bits, already have shifted version in 'pN_shifted'
	'''
                                                    1  ~p0[7]  p0[6]  p0[5]  p0[4]  p0[3]  p0[2]  p0[1]  p0[0]
                                                ~p1[7] +p1[6] +p1[5] +p1[4] +p1[3] +p1[2] +p1[1] +p1[0]   0
                                         ~p2[7] +p2[6] +p2[5] +p2[4] +p2[3] +p2[2] +p2[1] +p2[0]   0      0
                                  ~p3[7] +p3[6] +p3[5] +p3[4] +p3[3] +p3[2] +p3[1] +p3[0]   0      0      0
                           ~p4[7] +p4[6] +p4[5] +p4[4] +p4[3] +p4[2] +p4[1] +p4[0]   0      0      0      0
                    ~p5[7] +p5[6] +p5[5] +p5[4] +p5[3] +p5[2] +p5[1] +p5[0]   0      0      0      0      0
             ~p6[7] +p6[6] +p6[5] +p6[4] +p6[3] +p6[2] +p6[1] +p6[0]   0      0      0      0      0      0
   1  +p7[7] ~p7[6] ~p7[5] ~p7[4] ~p7[3] ~p7[2] ~p7[1] ~p7[0]   0      0      0      0      0      0      0
 ------------------------------------------------------------------------------------------------------------
P[15]  P[14]  P[13]  P[12]  P[11]  P[10]   P[9]   P[8]   P[7]   P[6]   P[5]   P[4]   P[3]   P[2]   P[1]  P[0]
	'''

	msb_prefix = "uint1"
	msb_t = msb_prefix + "_t"
	for p in range(0,max_input_width):
		# Shifted p
		p_shifted_width = p_width + p
		p_shifted_prefix = "uint" + str(p_shifted_width)
		p_shifted_t = "uint" + str(p_shifted_width) + "_t"
		p_shifted = '''p''' + str(p) + '''_shifted'''
		
		# Get msb
		p_shifted_msb = p_shifted + "_msb"
		text += '''
		
	// P ''' + str(p) + ''' adjusted
	''' + msb_t + ''' ''' + p_shifted_msb + ''';
	''' + p_shifted_msb + ''' = ''' + p_shifted_prefix + '''_''' + str(p_shifted_width-1) + '''_''' + str(p_shifted_width-1) + '''(''' + p_shifted + ''');'''
		
		
		# First is special case
		if p == 0:
			# Get lower bits of shfited
			lsbs_width = p_shifted_width - 1
			lsbs_prefix = "uint" + str(lsbs_width)
			lsbs_t = lsbs_prefix + "_t"
			p_shifted_lsbs = p_shifted + "_lsbs"
			text += '''
	// First is special case
	''' + lsbs_t + ''' ''' + p_shifted_lsbs + ''';
	''' + p_shifted_lsbs + ''' = ''' + p_shifted_prefix + '''_''' + str(lsbs_width-1) + '''_0(''' + p_shifted + ''');'''
			
			# Invert msb
			p_shifted_msb_neg = p_shifted_msb + "_neg"
			text += '''
	''' + msb_t + ''' ''' + p_shifted_msb_neg + ''';
	''' + p_shifted_msb_neg + ''' = !''' + p_shifted_msb + ''';'''
			
			# Concat negated msb and lsbs
			p_shifted_neg_msb_and_lsbs_prefix_width = lsbs_width + 1
			p_shifted_neg_msb_and_lsbs_prefix = "uint" + str(p_shifted_neg_msb_and_lsbs_prefix_width)
			p_shifted_neg_msb_and_lsbs_t = p_shifted_neg_msb_and_lsbs_prefix + "_t"
			p_shifted_neg_msb_and_lsbs = p_shifted + "_neg_msb_and_lsbs"
			text += '''
	''' + p_shifted_neg_msb_and_lsbs_t + ''' ''' + p_shifted_neg_msb_and_lsbs + ''';
	''' + p_shifted_neg_msb_and_lsbs + ''' = ''' + msb_prefix + '''_''' + lsbs_prefix + '''(''' + p_shifted_msb_neg + ''',''' + p_shifted_lsbs + ''');'''
			
			# Adjusted result has 1 added as MSB
			# 1  ~p0[7]  p0[6]  p0[5]  p0[4]  p0[3]  p0[2]  p0[1]  p0[0]
			adj_width = p_shifted_width + 1
			# Cap shifted partiual sums to max intermediate width
			if adj_width > max_intermidate_bit_width:
				adj_width = max_intermidate_bit_width
			adj_width_prefix = "uint" + str(adj_width)
			adj_t = adj_width_prefix+ "_t"
			p_shifted_adj = p_shifted + "_adj"
			text += '''
	''' + adj_t + ''' ''' + p_shifted_adj + ''';
	''' + p_shifted_adj + ''' = uint1_''' + p_shifted_neg_msb_and_lsbs_prefix + '''(1, ''' + p_shifted_neg_msb_and_lsbs + ''');'''
			var_2_type[p_shifted_adj] = adj_t
			
		# End is special case
		elif p == (max_input_width-1):
			
			#1  +p7[7] ~p7[6] ~p7[5] ~p7[4] ~p7[3] ~p7[2] ~p7[1] ~p7[0]   0      0      0      0      0      0      0
			# Get zeros
			p_shifted_zeros_width = p
			p_shifted_zeros_prefix = "uint" + str(p_shifted_zeros_width)
			p_shifted_zeros_t = p_shifted_zeros_prefix + "_t"
			p_shifted_zeros = p_shifted + "_zeros"
			text += '''
	// End special case
	''' + p_shifted_zeros_t + ''' ''' + p_shifted_zeros + ''';
	''' + p_shifted_zeros + ''' = ''' + p_shifted_prefix + '''_''' + str(p_shifted_zeros_width-1) + '''_0(''' + p_shifted + ''');'''
	
			# Get upper lsbs that arent zero
			# DOES NOT INCLUDE MSB
			p_shifted_upper_lsbs_width = p_width - 1
			p_shifted_upper_lsbs_prefix = "uint" + str(p_shifted_upper_lsbs_width)
			p_shifted_upper_lsbs_t = p_shifted_upper_lsbs_prefix + "_t"
			p_shifted_upper_lsbs = p_shifted + "_upper_lsbs"
			low = p_shifted_zeros_width
			high = p_shifted_width - 2 # SKIP MSB
			text += '''
	''' + p_shifted_upper_lsbs_t + ''' ''' + p_shifted_upper_lsbs + ''';
	''' + p_shifted_upper_lsbs + ''' = ''' + p_shifted_prefix + '''_''' + str(high) + '''_''' + str(low) + '''(''' + p_shifted + ''');'''
	
			# Invert upper lsbs 
			p_shifted_upper_lsbs_neg = p_shifted_upper_lsbs + "_neg"
			text += '''
	''' + p_shifted_upper_lsbs_t + ''' ''' + p_shifted_upper_lsbs_neg + ''';
	''' + p_shifted_upper_lsbs_neg + ''' = !''' + p_shifted_upper_lsbs + ''';'''
			
			# Concat zeros and negated upper lsbs
			p_shifted_upper_lsbs_neg_and_zeros_width = p_shifted_upper_lsbs_width + p_shifted_zeros_width
			p_shifted_upper_lsbs_neg_and_zeros_prefix = "uint" + str(p_shifted_upper_lsbs_neg_and_zeros_width)
			p_shifted_upper_lsbs_neg_and_zeros_t = p_shifted_upper_lsbs_neg_and_zeros_prefix + "_t"
			p_shifted_upper_lsbs_neg_and_zeros = p_shifted_upper_lsbs_neg + "_and_zeros"
			text += '''
	''' + p_shifted_upper_lsbs_neg_and_zeros_t + ''' ''' + p_shifted_upper_lsbs_neg_and_zeros + ''';
	''' + p_shifted_upper_lsbs_neg_and_zeros + ''' = ''' + p_shifted_upper_lsbs_prefix + '''_''' + p_shifted_zeros_prefix + '''(''' + p_shifted_upper_lsbs_neg + ''', ''' + p_shifted_zeros + ''');'''
			
			# Concat msb
			p_shifted_upper_lsbs_neg_and_zeros_w_msb_width = p_shifted_upper_lsbs_neg_and_zeros_width + 1
			p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix = "uint" + str(p_shifted_upper_lsbs_neg_and_zeros_w_msb_width)
			p_shifted_upper_lsbs_neg_and_zeros_w_msb_t = p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix + "_t"
			p_shifted_upper_lsbs_neg_and_zeros_w_msb = p_shifted_upper_lsbs_neg_and_zeros + "_w_msb"
			text += '''
	''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb_t + ''' ''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb + ''';
	''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb + ''' = uint1_''' + p_shifted_upper_lsbs_neg_and_zeros_prefix + '''(''' +  p_shifted_msb + ''', ''' + p_shifted_upper_lsbs_neg_and_zeros + ''');'''
			
			
			# Concat 1 as MSB for adjusted result
			adj_width = p_shifted_upper_lsbs_neg_and_zeros_w_msb_width + 1
			# Cap shifted partiual sums to max intermediate width
			if adj_width > max_intermidate_bit_width:
				adj_width = max_intermidate_bit_width
			adj_width_prefix = "uint" + str(adj_width)
			adj_t = adj_width_prefix+ "_t"
			p_shifted_adj = p_shifted + "_adj"
			text += '''
	''' + adj_t + ''' ''' + p_shifted_adj + ''';
	''' + p_shifted_adj + ''' = uint1_''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix + '''(1, ''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb + ''');'''
			var_2_type[p_shifted_adj] = adj_t
			
		# Mid is normal case (very similar to p==0)
		else:
			# Get lower bits of shfited
			lsbs_width = p_shifted_width - 1
			lsbs_prefix = "uint" + str(lsbs_width)
			lsbs_t = lsbs_prefix + "_t"
			p_shifted_lsbs = p_shifted + "_lsbs"
			text += '''
	// Mid is normal case		
	''' + lsbs_t + ''' ''' + p_shifted_lsbs + ''';
	''' + p_shifted_lsbs + ''' = ''' + p_shifted_prefix + '''_''' + str(lsbs_width-1) + '''_0(''' + p_shifted + ''');'''
			
			# Invert msb
			p_shifted_msb_neg = p_shifted_msb + "_neg"
			text += '''
	''' + msb_t + ''' ''' + p_shifted_msb_neg + ''';
	''' + p_shifted_msb_neg + ''' = !''' + p_shifted_msb + ''';'''
			
			# Adjusted result has Concat negated msb and lsbs
			adj_width = p_shifted_width
			# Cap shifted partiual sums to max intermediate width
			if adj_width > max_intermidate_bit_width:
				adj_width = max_intermidate_bit_width
			adj_width_prefix = "uint" + str(adj_width)
			adj_t = adj_width_prefix+ "_t"
			p_shifted_adj = p_shifted + "_adj"
			# ~p1[7] +p1[6] +p1[5] +p1[4] +p1[3] +p1[2] +p1[1] +p1[0]   0
			text += '''
	''' + adj_t + ''' ''' + p_shifted_adj + ''';
	''' + p_shifted_adj + ''' = ''' + msb_prefix + '''_''' + lsbs_prefix + '''(''' + p_shifted_msb_neg + ''',''' + p_shifted_lsbs + ''');'''
			var_2_type[p_shifted_adj] = adj_t
	
	
	
	
	# BINARY TREE SUM
	layer_nodes = []
	for p in range(0,max_input_width):
		layer_nodes.append("p" + str(p) + "_shifted_adj")
		
	layer=0
	node=0
	
	text += '''
	// Binary summation of partial sums
'''
 
	
	# DO
	while True: 
		text += '''
	// Layer + ''' + str(layer) + '''
'''
		node = 0
		new_layer_nodes = []
		# Write adds in pairs
		# While 2 args to add
		while(len(layer_nodes) >= 2):
			left_arg = layer_nodes.pop(0)
			right_arg = layer_nodes.pop(0)
			left_t = var_2_type[left_arg]
			right_t = var_2_type[right_arg]
			# Sum type is max width
			left_width = int(left_t.replace("uint","").replace("int","").replace("_t",""))
			right_width = int(right_t.replace("uint","").replace("int","").replace("_t",""))
			max_width = max(left_width,right_width)
			sum_width = max_width+1
			
			# Reduce sum width to max intermediate width
			if sum_width > max_intermidate_bit_width:
				sum_width = max_intermidate_bit_width
			
			sum_t = "uint" + str(sum_width) + "_t"
			sum_var = "sum_layer" + str(layer) + "_node" + str(node)
			var_2_type[sum_var] = sum_t
			text += '''	''' + sum_t + ''' ''' + sum_var + ''';
	''' + sum_var + ''' = ''' + left_arg + " + " + right_arg + ''';
'''
			# This sum node is on next layer
			new_layer_nodes.append(sum_var)
			node += 1
		
		# Out of while loop	
		# < 2 nodes left to sum in this node
		if len(layer_nodes) == 1:
			# One node left
			the_arg = layer_nodes.pop(0)
			the_t = var_2_type[the_arg]
			sum_t = the_t			
			sum_var = "sum_layer" + str(layer) + "_node" + str(node)
			var_2_type[sum_var] = sum_t
			text += '''	// Odd node in layer
	''' + sum_t + ''' ''' + sum_var + ''';
	''' + sum_var + ''' = ''' + the_arg + ''';
	'''
			# This sum node is on next layer
			new_layer_nodes.append(sum_var)
			node += 1
			
		
		# WHILE
		if len(new_layer_nodes) >= 2:
			# Continue
			layer_nodes = new_layer_nodes
			layer += 1
		else:
			# DONE
			break;
	
	# Done with outer layer while loop
		
	# Do return
	return_var = "sum_layer" + str(layer) + "_node" + str(node-1)
	return_t = var_2_type[return_var]
	text += '''
	''' + "// Return" + '''
	''' + return_t + ''' rv;
	rv = ''' + return_var + ''';
	return rv;
}
'''
	
	
	return text 
	#print text
	#sys.exit(0)


		
def GET_BIN_OP_MULT_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
	'''
 p0[7:0] = a[0] x b[7:0] = {8{a[0]}} & b[7:0]
 p1[7:0] = a[1] x b[7:0] = {8{a[1]}} & b[7:0]
 p2[7:0] = a[2] x b[7:0] = {8{a[2]}} & b[7:0]
 p3[7:0] = a[3] x b[7:0] = {8{a[3]}} & b[7:0]
 p4[7:0] = a[4] x b[7:0] = {8{a[4]}} & b[7:0] 
 
 
 p5[7:0] = a[5] x b[7:0] = {8{a[5]}} & b[7:0]
 p6[7:0] = a[6] x b[7:0] = {8{a[6]}} & b[7:0]
 p7[7:0] = a[7] x b[7:0] = {8{a[7]}} & b[7:0]
where {8{a[0]}} means repeating a[0] (the 0th bit of a) 8 times (Verilog notation).

To produce our product, we then need to add up all eight of our partial products, as shown here:

                                                p0[7] p0[6] p0[5] p0[4] p0[3] p0[2] p0[1] p0[0]
                                        + p1[7] p1[6] p1[5] p1[4] p1[3] p1[2] p1[1] p1[0] 0
                                  + p2[7] p2[6] p2[5] p2[4] p2[3] p2[2] p2[1] p2[0] 0     0
                            + p3[7] p3[6] p3[5] p3[4] p3[3] p3[2] p3[1] p3[0] 0     0     0
                      + p4[7] p4[6] p4[5] p4[4] p4[3] p4[2] p4[1] p4[0] 0     0     0     0
                + p5[7] p5[6] p5[5] p5[4] p5[3] p5[2] p5[1] p5[0] 0     0     0     0     0
          + p6[7] p6[6] p6[5] p6[4] p6[3] p6[2] p6[1] p6[0] 0     0     0     0     0     0
    + p7[7] p7[6] p7[5] p7[4] p7[3] p7[2] p7[1] p7[0] 0     0     0     0     0     0     0
-------------------------------------------------------------------------------------------
P[15] P[14] P[13] P[12] P[11] P[10]  P[9]  P[8]  P[7]  P[6]  P[5]  P[4]  P[3]  P[2]  P[1]  P[0]
	'''
	# Need bit select
	# Need bit concat
	# Need bitwise AND
	# Have sum already


	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
	max_input_width = max(left_width,right_width)
	resized_prefix = "uint" + str(max_input_width)
	resized_t = resized_prefix + "_t"
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)	
	output_prefix = "uint" + str(output_width)
	
	# Temp try to reduce bit width?
	# Output width is max =  left_width+right_width
	# Actual max internal width is min out output width and ma xof input widths
	max_intermidate_bit_width = min(output_width, left_width+right_width)
	
	
	text = ""
	
	# Generate abs path to uint headers
	#top_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
	#uint_h ='''#include "''' + top_dir + '''/uintN_t.h"'''
	#int_h ='''#include "''' + top_dir + '''/intN_t.h"'''
	
	text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''b x ''' + str(right_width) + '''b mult
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Resize
	''' + resized_t + ''' left_resized;
	left_resized = left;
	''' + resized_t + ''' right_resized;
	right_resized = right;
	
	// Left repeated bit unsigneds
'''
	for rb in range(0,max_input_width):
		text += '''	// BIT''' + str(rb) + ''' REPEATED
	// Select bit
	uint1_t left''' + str(rb) + '''_x1;
	left''' + str(rb) + '''_x1 = ''' + resized_prefix + '''_''' + str(rb) + '''_''' + str(rb) + '''(left_resized);
	// Dup
	uint''' + str(max_input_width) + '''_t  left''' + str(rb) + '''_x''' + str(max_input_width) + ''';
	left''' + str(rb) + '''_x''' + str(max_input_width) + ''' = uint1_''' + str(max_input_width) + '''(left''' + str(rb) + '''_x1);
'''
	
	
	
	text += '''
	// Partial sums
'''
	for rb in range(0,max_input_width):
		text += "	" + resized_t + ''' p''' + str(rb) + ''';
	p''' + str(rb) + ''' = left''' + str(rb) + '''_x''' + str(max_input_width) + ''' & right_resized;
'''
	# Save types of vars for ease later
	var_2_type = dict()
	
	# Cap shifted partiual sums to max intermediate width
	max_intermidate_prefix = "uint" + str(max_intermidate_bit_width)
	max_intermidate_t = max_intermidate_prefix + "_t"
	
	text += '''
	// Shifted partial sums
	''' + resized_t + ''' p0_shifted;
	p0_shifted = p0;
'''
	var_2_type["p0_shifted"] = resized_t
	for p in range(1,max_input_width):
		uintp_prefix = "uint" + str(p)
		uintp_t =  uintp_prefix + "_t"
		p_width = max_input_width
		#p_width_minus1 = p_width - 1
		p_t_prefix = "uint" + str(p_width)
		
		p_shifted_width = p_width + p
		# Cap shifted partiual sums to max intermediate width
		if p_shifted_width > max_intermidate_bit_width:
			p_shifted_width = max_intermidate_bit_width
		p_shifted_t = "uint" + str(p_shifted_width) + "_t"
				
		p_shifted = '''p''' + str(p) + '''_shifted'''
		var_2_type[p_shifted] = p_shifted_t
		
		text += '''	''' + uintp_t + ''' zero_x''' + str(p) + ''';
	zero_x''' + str(p) + ''' = 0;
	''' + p_shifted_t + ''' p''' + str(p) + '''_shifted;
	p''' + str(p) + '''_shifted = ''' + p_t_prefix + '''_''' + uintp_prefix + '''(p''' + str(p) + ''' ,zero_x''' + str(p) + ''');
'''
	
	layer_nodes = []
	for p in range(0,max_input_width):
		layer_nodes.append("p" + str(p) + "_shifted")
		
	layer=0
	node=0
	
	text += '''
	// Binary summation of partial sums
'''
 
	
	# DO
	while True: 
		text += '''
	// Layer + ''' + str(layer) + '''
'''
		node = 0
		new_layer_nodes = []
		# Write adds in pairs
		# While 2 args to add
		while(len(layer_nodes) >= 2):
			left_arg = layer_nodes.pop(0)
			right_arg = layer_nodes.pop(0)
			left_t = var_2_type[left_arg]
			right_t = var_2_type[right_arg]
			# Sum type is max width
			left_width = int(left_t.replace("uint","").replace("int","").replace("_t",""))
			right_width = int(right_t.replace("uint","").replace("int","").replace("_t",""))
			max_width = max(left_width,right_width)
			sum_width = max_width+1
			
			# Reduce sum width to max intermediate width
			if sum_width > max_intermidate_bit_width:
				sum_width = max_intermidate_bit_width
			
			sum_t = "uint" + str(sum_width) + "_t"
			sum_var = "sum_layer" + str(layer) + "_node" + str(node)
			var_2_type[sum_var] = sum_t
			text += '''	''' + sum_t + ''' ''' + sum_var + ''';
	''' + sum_var + ''' = ''' + left_arg + " + " + right_arg + ''';
'''
			# This sum node is on next layer
			new_layer_nodes.append(sum_var)
			node += 1
		
		# Out of while loop	
		# < 2 nodes left to sum in this node
		if len(layer_nodes) == 1:
			# One node left
			the_arg = layer_nodes.pop(0)
			the_t = var_2_type[the_arg]
			sum_t = the_t			
			sum_var = "sum_layer" + str(layer) + "_node" + str(node)
			var_2_type[sum_var] = sum_t
			text += '''	// Odd node in layer
	''' + sum_t + ''' ''' + sum_var + ''';
	''' + sum_var + ''' = ''' + the_arg + ''';
	'''
			# This sum node is on next layer
			new_layer_nodes.append(sum_var)
			node += 1
			
		
		# WHILE
		if len(new_layer_nodes) >= 2:
			# Continue
			layer_nodes = new_layer_nodes
			layer += 1
		else:
			# DONE
			break;
	
	# Done with outer layer while loop
		
	# Do return
	return_var = "sum_layer" + str(layer) + "_node" + str(node-1)
	return_t = var_2_type[return_var]
	text += '''
	''' + "// Return" + '''
	''' + return_t + ''' rv;
	rv = ''' + return_var + ''';
	return rv;
}
'''
	
	
	return text 
	#print text
	#sys.exit(0)		
	
	
	
# 128 LLs in own code
# 192 lls as VHDL
# TODO: Is this bad/broken? test edge cases
def GET_BIN_OP_DIV_UINT_N_C_CODE(partially_complete_logic, out_dir):	
	left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
	right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
	output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
	left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
	right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
	max_input_width = max(left_width,right_width)
	resized_prefix = "uint" + str(max_input_width)
	resized_t = resized_prefix + "_t"
	output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t)	
	output_prefix = "uint" + str(output_width)
	
	text = ""
	
	text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''b / ''' + str(right_width) + '''b mult
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
	// Resize
	''' + resized_t + ''' left_resized;
	left_resized = left;
	''' + resized_t + ''' right_resized;
	right_resized = right;
	
	// Output
	''' + resized_t + ''' output;
	output = 0;
	// Remainder
	''' + resized_t + ''' remainder;
	remainder = 0;
	uint1_t new_remainder0;	
	

	/*
	UNROLL THIS
	remainder := 0                     
	for i := n - 1 .. 0 do  -- Where left is number of bits in left
	  remainder := remainder << 1           -- Left-shift remainder by 1 bit
	  remainder(0) := left(i)          -- Set the least-significant bit of remainder equal to bit i of the numerator
	  if remainder >= right then
		remainder := remainder - right
		output(i) := 1
	  end
	end 
	*/
	'''
	
	
	
	for i in range(max_input_width-1, -1,-1):
		text += '''
	// Bit ''' + str(i) + '''
	/*
	  remainder := remainder << 1           -- Left-shift remainder by 1 bit
	  remainder(0) := left(i)          -- Set the least-significant bit of remainder equal to bit i of the numerator
	  if remainder >= right then
		remainder := remainder - right
		output(i) := 1
	  end
	*/
	
	// << 1           // Left-shift remainder by 1 bit
	// Set shift left and set the least-significant bit of remainder equal to bit i of the numerator
	new_remainder0 = ''' + resized_prefix + '''_''' + str(i) + '''_''' + str(i) + '''(left);
	remainder = ''' + resized_prefix + '''_uint1(remainder, new_remainder0);       
	if(remainder >= right)
	{
		remainder = remainder - right;
		// Set output(i)=1
		output = ''' + output_prefix + '''_uint1_''' + str(i) + '''(output, 1);
	}
	else
	{
		remainder = remainder; // No change
		output = output; // No change
	}
'''

	text += '''
	return output;
}'''
	
	#print text
	#sys.exit(0)
	
	return text 
		
	
