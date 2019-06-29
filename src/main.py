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
mhz = SYN.INF_MHZ #57.83 #SYN.INF_MHZ # TEST 31.25

print "TODO:"
print "	Got rid of pipeline map cache... is slow now?"
print "	Yo dummy dont make built in operations have resize() on outputs, output determined by inputs only"
print "	FIX EXTRA LOGIC LEVEL AND LUTS IN SOME FUNCTIONS! +1 extra logic level in some places..."
print "	Look into intermediate representation such FIRRTL instead of VHDL..."
print "	Remove RESOLVE_CONST_ARRAY_REF from C_AST_REF_TO_TOKENS, and max var ref / var assignement optimize to const ref and const assignment... complicated..."
print "	Consider doing constant optimization as second pass (faster than current way of optimizing as part of first pass?)? How to unroll const for-loop then?"
print "	OPTIMIZE AWAY CONSTANT IF and constant float mult by 1?"
print "	Be a real C compiler yo"
print "	Const array refs need func names for each array index .... but are doing almost the same thing?... slow syn :( Dont need to use base var name in func name?"
print "	Syn each pipeline stage ... this is hard... like slicing zero clock logic "
print "	Maybe can implement variable time loops as PipelineC state machines? Thanks Andrew"
print "	Allow mix of volatile and non-volatile globals by isolating logic using globals (as is done now by putting in other global func)?"
print "	Redo eq,and,or,..etc raw vhdl ops with pipelined binary trees instead of equal bit sequential stages? Bad for slicing.. probably can work"
print "	Check for non global functions that call global functions when evaluating const"
print "	Does const work in C? Use that for 'compile time' constant wire replacement?"
print "	Generate bit manip vhdl funcs in own package?"
print "	Prune away logic from user C code as to not write generate vhdl? Work backwards from outputs/globals?"
print "================== Generating (u)intN_t.h Headers ================================"
SW_LIB.GENERATE_INT_N_HEADERS()

print "================== Parsing C Code to Logical Hierarchy ================================"
parser_state = C_TO_LOGIC.PARSE_FILE(top_level_func_name, c_file)

print "================== Adding Logic Delay Information To Lookup Table ================================"
parser_state = SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state.LogicInstLookupTable[top_level_func_name], parser_state)
logic = parser_state.LogicInstLookupTable[top_level_func_name]

print "================== Doing Optional Modelsim Debug ================================"
MODELSIM.DO_OPTIONAL_DEBUG(True)

print "================== Beginning Throughput Sweep ================================"
TimingParamsLookupTable = SYN.DO_THROUGHPUT_SWEEP(logic, parser_state, mhz)

print "================== Writing Results of Throughput Sweep ================================"
timing_params = TimingParamsLookupTable[top_level_func_name]
hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
print "Use theses TCL commands from .tcl file with hash extension:", hash_ext
tcl = VIVADO.GET_READ_VHDL_TCL(logic, SYN.GET_OUTPUT_DIRECTORY(logic), TimingParamsLookupTable, SYN.INF_MHZ, parser_state, implement=False)
print "remove_files {" + SYN.SYN_OUTPUT_DIRECTORY + "/*}"
print tcl
print "Use the above tcl in Vivado."








