#!/usr/bin/env python
# -*- coding: utf-8 -*- 

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

# AWS example runs at 125
# However, experiments show we need ~30% margin to meet timing at scale, ~162MHz
mhz = 162.0

print '''
██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗ ██████╗
██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝██╔════╝
██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ██║     
██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ██║     
██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗╚██████╗
╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝
'''

print "TODO:"
print "	Built in raw vhdl funcs for array copy / manipulation instead of many const rek tok loops. Built in funcs can return arrays (handled internally) but user can write such funcs  uint8*4_t[N/4] = uint8_arrayN_by_4_le(uint8_t x[N])"
print "	Fix bug where user can't have empty/pass through/no submodules functions"
print "	Really write/generate? headers for full gcc compatibilty - write SW generated C bit manip/math?"
print "	Get serious about using C macros fool because yall know you aint parsing C++"
print "	How to do module instantiation? Does that need to be macro based? #define to set 'generics'?"
print "	Do clock crossing with globals and 'false path' volatile globals"
print "	FIX EXTRA LOGIC LEVEL AND LUTS IN SOME FUNCTIONS! +1 extra logic level in some places...mostly needed for 0 clk delay measurement?"
print "	Use gcc array init instead of for loop many const ref tok assignments that are bulky?"
print "	Add timing info via syn top level without flatten, then report timing on each module? No IO regs so will paths make sense? / doesnt work for combinatorial logic? Hah syn weird top level with _top version of everything?"
print "	OPTIMIZE AWAY CONSTANTs: mult by 1 or neg 1, mult by 2 and div by 2, (floats and ints!)"
print "	When doing const ref read with many ref toks, make new 'assignment' alias of new reduced wire so future reads of the same const ref can use the single wire"
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
print "	Got rid of pipeline map cache... is slow now?"
print "	Redo old code to use for loops instead of generated code (ex. float div)"
print "	Fix for vhdl restricted words. Append _restricted?"
print "	Maybe can implement variable time loops as PipelineC state machines?? Weird idea Andrew"
print "	CANNOT PROPOGATE CONSTANTS through compound references (structs, arrays)"

print "================== Parsing C Code to Logical Hierarchy ================================"
parser_state = C_TO_LOGIC.PARSE_FILE(top_level_func_name, c_file)

print "================== Adding Timing Information from Synthesis Tool (Vivado) ================================"
parser_state = SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state.LogicInstLookupTable[top_level_func_name], parser_state)
logic = parser_state.FuncLogicLookupTable[top_level_func_name]

print "================== Doing Optional Modelsim Debug ================================"
MODELSIM.DO_OPTIONAL_DEBUG(False)

print "================== Beginning Throughput Sweep ================================"
skip_course_sweep=False
skip_fine_sweep=True
TimingParamsLookupTable = SYN.DO_THROUGHPUT_SWEEP(top_level_func_name, logic, parser_state, mhz, skip_course_sweep, skip_fine_sweep)

print "================== Writing Results of Throughput Sweep ================================"
VIVADO.WRITE_FINAL_FILES(top_level_func_name, logic, TimingParamsLookupTable, parser_state)
print "Done."







