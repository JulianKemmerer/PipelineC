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
mhz=SYN.INF_MHZ # TEST 31.25

print "OPTIMIZE AWAY CONSTANT IF and constant float mult by 1?"
print "Be a real C compiler yo"
print "Does const work in C? Use that for 'compile time' constant replacement?"


print "================== Generating (u)intN_t.h Headers ================================"
SW_LIB.GENERATE_INT_N_HEADERS()

print "================== Parsing C Code to Logical Hierarchy ================================"
parser_state = C_TO_LOGIC.PARSE_FILE(top_level_func_name, c_file)

print "================== Adding Logic Level Information To Lookup Table ================================"
print "FIX EXTRA LOGIC LEVEL AND LUTS IN SOME FUNCTIONS! +1 extra logic level in some places..."
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








