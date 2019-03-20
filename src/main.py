#!/usr/bin/env python
import sys
sys.dont_write_bytecode = True

import C_TO_LOGIC
import VHDL
import SYN
import SW_LIB
import MODELSIM
import VIVADO

c_file = "main.c"
top_level_func_name = "main"
mhz=31.25  #57.83 #SYN.INF_MHZ # TEST 31.25

print "TODO:"
print "	FIX EXTRA LOGIC LEVEL AND LUTS IN SOME FUNCTIONS! +1 extra logic level in some places..."
print "	OPTIMIZE AWAY CONSTANT IF and constant float mult by 1?"
print "	Be a real C compiler yo"
print "	Does const work in C? Use that for 'compile time' constant replacement?"
print "	TODO: Syn each pipeline stage (from top level main, so easy) individually and use delays instead of LLs?"
print "	~~~~~ REPLACE MANY INSTANCE VHDL FILES WITH JUST INSTANCES OF DIFFERENT SLICES ~~~~~ ?"
print "	Switch over to delay ns instead of logic levels"
print "	Maybe can implement variable time loops as PipelineC state machines? Thanks Andrew"
print "	Allow mix of volatile and non-volatile globals by isolating logic using globals (as is done now by putting in other global func)?"
print "	Redo eq,and,or,..etc raw vhdl ops with pipelined binary trees instead of equal bit sequential stages? Bad for slicing.. probably can work"
print "================== Generating (u)intN_t.h Headers ================================"
SW_LIB.GENERATE_INT_N_HEADERS()

print "================== Parsing C Code to Logical Hierarchy ================================"
parser_state = C_TO_LOGIC.PARSE_FILE(top_level_func_name, c_file)

print "================== Adding Logic Level Information To Lookup Table ================================"
parser_state.LogicInstLookupTable = SYN.ADD_TOTAL_LOGIC_LEVELS_TO_LOOKUP(parser_state.LogicInstLookupTable[top_level_func_name], parser_state)
logic = parser_state.LogicInstLookupTable[top_level_func_name]

print "================== Doing Optional Modelsim Debug ================================"
MODELSIM.DO_OPTIONAL_DEBUG(False)

print "================== Beginning Throughput Sweep ================================"
TimingParamsLookupTable = SYN.DO_THROUGHPUT_SWEEP(logic, parser_state, mhz)

print "================== Writing Results of Throughput Sweep ================================"
timing_params = TimingParamsLookupTable[top_level_func_name]
hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
print "Use theses TCL commands from .tcl file with hash extension:", hash_ext
tcl = VIVADO.GET_READ_VHDL_TCL(logic, SYN.GET_OUTPUT_DIRECTORY(logic, implement=False), TimingParamsLookupTable, SYN.INF_MHZ, parser_state, implement=False)
print "remove_files {" + SYN.SYN_OUTPUT_DIRECTORY + "/*}"
print tcl
print "Use the above tcl in Vivado."








