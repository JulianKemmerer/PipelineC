#!/usr/bin/env python
import sys

import VHDL

HDL_INSERT="HDL_INSERT"

STRUCTREF_RD = "STRUCTREF_RD"
STRUCTREF_WR = "STRUCTREF_WR"
STRUCTREF_VAR_PORT="var"
STRUCTREF_FIELD_PORT="field"


def GET_HDL_INSERT_TEXT(submodule_logic,submodule_inst_name, logic, timing_params):
	
	SR_RD = HDL_INSERT + "_" + STRUCTREF_RD
	SR_WR = HDL_INSERT + "_" + STRUCTREF_WR
	if submodule_logic.func_name.startswith(SR_RD):
		# Read has one input
		in_wire = submodule_logic.inputs[0]
		in_wire_write_pipe_dot_var = VHDL.GET_WRITE_PIPE_WIRE_VHDL(in_wire, logic, parser_state)
		# One output
		out_wire = submodule_logic.outputs[0]
		out_wire_write_pipe_dot_var = VHDL.GET_WRITE_PIPE_WIRE_VHDL(out_wire, logic, parser_state)
		
		#<something> = a.b.c
		# Get .b.c
		id_str = submodule_logic.func_name.replace(SR_RD+"_","")
		fields = ".".join(id_str.split(".")[1:])

		return out_wire_write_pipe_dot_var + " := " + in_wire_write_pipe_dot_var + "." + fields + "; -- STRUCTREF RD"
		
		
	elif submodule_logic.func_name.startswith(SR_WR):
		# WR has two inputs, first is orig var, second is field assignment
		var_input = submodule_logic.inputs[0]
		var_input_write_pipe_dot_var = VHDL.GET_WRITE_PIPE_WIRE_VHDL(var_input, logic, parser_state)
		field_input = submodule_logic.inputs[1]
		field_input_write_pipe_dot_var = VHDL.GET_WRITE_PIPE_WIRE_VHDL(field_input, logic, parser_state)		
		# One output
		out_wire = submodule_logic.outputs[0]
		out_wire_write_pipe_dot_var = VHDL.GET_WRITE_PIPE_WIRE_VHDL(out_wire, logic, parser_state)
		
		#<something> = a.b.c
		# Get .b.c
		id_str = submodule_logic.func_name.replace(SR_WR+"_","")
		fields = ".".join(id_str.split(".")[1:])

		text = ""
		# First write input orig var to next alias (without fields)
		# Then field input write to next alias with fields
		text += out_wire_write_pipe_dot_var + " := " + var_input_write_pipe_dot_var + "; "
		text += out_wire_write_pipe_dot_var + "." + fields + " := " + field_input_write_pipe_dot_var + "; -- STRUCTREF WR"
		return text
	else:
		print "What hdl insert?"
		sys.exit(0)
