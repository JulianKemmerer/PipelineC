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

print '''
██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗ ██████╗
██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝██╔════╝
██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ██║     
██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ██║     
██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗╚██████╗
╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝
'''
print "TODO:"
print "	FIX EXTRA LOGIC LEVEL AND LUTS IN SOME FUNCTIONS! +1 extra logic level in some places...mostly needed for 0 clk delay measurement?"
print "	OPTIMIZE AWAY CONSTANTs: IF, mult by 1 or neg 1, mult by 2 and div by 2, (floats and ints!)"
print "	Yo dummy dont make built in operations have resize() on outputs, output determined by inputs only"
print "	Add look ahead for built in functions so cast can be inferred"
print "	Look into intermediate representation such FIRRTL instead of VHDL..."
print "	Remove RESOLVE_CONST_ARRAY_REF from C_AST_REF_TO_TOKENS, and max var ref / var assignement optimize to const ref and const assignment... complicated..."
print "	Consider doing constant optimization as second pass (faster than current way of optimizing as part of first pass?)? How to unroll const for-loop then?"
print "	Add checks for globals not being used conditionally"
print "	Syn each pipeline stage ... this is hard... like slicing zero clock logic "
print "	Allow mix of volatile and non-volatile globals by isolating logic using globals (as is done now by putting in other global func)?"
print "	Redo eq,and,or,..etc raw vhdl ops with pipelined binary trees instead of equal bit sequential stages? Bad for slicing.. probably can work"
print "	Check for non global functions that call global functions when evaluating const"
print "	Prune away logic from user C code as to not write generate vhdl? Work backwards from outputs/globals?"
print "	Got rid of pipeline map cache... is slow now?"
print "	Redo old code to use for loops instead of generated code (ex. float div)"
print "	Fix for vhdl restricted words. Append _restricted?"
print "	Maybe can implement variable time loops as PipelineC state machines?? Weird idea Andrew"

print "================== Generating (u)intN_t.h Headers ================================"
SW_LIB.GENERATE_INT_N_HEADERS()

print "================== Parsing C Code to Logical Hierarchy ================================"
parser_state = C_TO_LOGIC.PARSE_FILE(top_level_func_name, c_file)

print "================== Adding Logic Delay Information To Lookup Table ================================"
parser_state = SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state.LogicInstLookupTable[top_level_func_name], parser_state)
logic = parser_state.LogicInstLookupTable[top_level_func_name]

print "================== Doing Optional Modelsim Debug ================================"
MODELSIM.DO_OPTIONAL_DEBUG(False)

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








