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
mhz = 125.0 #SYN.INF_MHZ #57.83 #SYN.INF_MHZ # TEST 31.25

print '''
██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗ ██████╗
██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝██╔════╝
██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ██║     
██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ██║     
██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗╚██████╗
╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝
'''
print "TODO:"
print "	Get serious about using C macros fool because yall know you aint parsing C++"
print "	FIX EXTRA LOGIC LEVEL AND LUTS IN SOME FUNCTIONS! +1 extra logic level in some places...mostly needed for 0 clk delay measurement?"
print "	OPTIMIZE AWAY CONSTANTs: mult by 1 or neg 1, mult by 2 and div by 2, (floats and ints!)"
print "	Yo dummy dont make built in operations have resize() on outputs, output determined by inputs only"
print "	Implement multi dimensional arrays from BRAM, the dumb way"
print "	Add look ahead for built in functions so cast can be inferred"
print "	Look into intermediate representation such FIRRTL instead of VHDL..."
print "	Do clock crossing with globals and 'false path' volatile globals"
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

print "================== Generating (u)intN_t.h headers ================================"
SW_LIB.GENERATE_INT_N_HEADERS()

print "================== Parsing C Code to logical hierarchy ================================"
parser_state = C_TO_LOGIC.PARSE_FILE(top_level_func_name, c_file)

print "================== Adding logic delay information from synthesis tool (Vivado) ================================"
parser_state = SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state.LogicInstLookupTable[top_level_func_name], parser_state)
logic = parser_state.FuncLogicLookupTable[top_level_func_name]

print "================== Doing Optional Modelsim Debug ================================"
MODELSIM.DO_OPTIONAL_DEBUG(False)

print "================== Beginning Throughput Sweep ================================"
skip_course_sweep=False
skip_fine_sweep=True
TimingParamsLookupTable = SYN.DO_THROUGHPUT_SWEEP(top_level_func_name, logic, parser_state, mhz, skip_course_sweep, skip_fine_sweep)

print "================== Writing Results of Throughput Sweep ================================"
timing_params = TimingParamsLookupTable[top_level_func_name]
hash_ext = timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)
print "Use theses TCL commands from .tcl file with hash extension:", hash_ext
tcl = VIVADO.GET_READ_VHDL_TCL(top_level_func_name, logic, SYN.GET_OUTPUT_DIRECTORY(logic), TimingParamsLookupTable, SYN.INF_MHZ, parser_state, implement=False)
print "remove_files {" + SYN.SYN_OUTPUT_DIRECTORY + "/*}"
print tcl
print "Use the above tcl in Vivado."








