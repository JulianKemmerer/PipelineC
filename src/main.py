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
mhz=31.25

print "TODO: IMPLEMENT LT/E for fucks sake"

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































'''
LATENCY IN ASSIGNMENT OPERATOR MEANS MULTICYCLE MEMORY ACCESS?



EVENT BASED PROGRAMMING:
An event can occur on any clk cycle
	If an event occurs without a valid signal from logic then exception?
	(Can convert to always valid with buffering acting as pipeline if bursty)


0 Clk cycle logic is combinational?

1 Clk cycle of logic is a function(struct) return struct that takes 1 cycle to execute
	A) Should be able to do VHDL functions direct synthesis
	
N clk cycle logic is either:
	A) Pipelined: 
		a function(struct) return struct that takes N cycles to return, 
		accepting arguments every cycle (no ready indicator required)
	B) Not pipelined
		a function(struct) return struct that takes N cycles to return, 
		accepting arguments every N cycles (ready indicator required)
		
Variable clk cycle logic is either:
	A) Pipelined: 
		a function(struct) return struct that takes an unknown amount of cycles to return, 
		accepting arguments every cycle (no ready indicator required)
	B) Not pipelined
		a function(struct) return struct that takes an unknown amount of cycles to return 
		and ready indicator required
		

// Try to convert by hand

// Returns LEDs
int main(int switches)
{
  int rv = 0;
  
  if(sqrt(switches) > 2)
  {
	rv = switches;
  }
  else
  {
	rv = 0;
  }
  return rv;
}

type sqrt_variables_t is record
end record;
type gt_variables_t is record
end record;
type mux_variables_t is record
end record;

...
...
...
-- These are populated by tool
-- EACH FUNCTION INSTANCE NEEDS OFFSET AND LATENCY!
-- Keep 
constant MAIN_LATENCY : integer := 0;
constant SQRT_8_LATENCY : integer := 0;
constant SQRT_8_OFFSET : integer := 0;
constant MUX_8_LATENCY : integer := 0;
constant MUX_8_OFFSET : integer := 0;
constant GT_8_LATENCY : integer := 0;
constant GT_8_OFFSET : integer := 0;


type main_variables_t is record:
	-- Each function instance gets registers
	sqrt_8_registers : sqrt_variables_t(0 to SQRT_8_LATENCY);
	mux_8_registers : mux_variables_t(0 to MUX_8_LATENCY);
	gt_8_registers : gt_variables_t(0 to GT_8_LATENCY);
	-- This will be populated with all wires in the logic
	switches : integer;
	rv : integer;
	gt_8_return : boolean;
	-- implicit return wire
	_return : integer;
end record;
type main_register_pipeline_t is array(natural range<>) of main_variables_t;

signal main_pipeline_r : main_register_pipeline_t(0 to MAIN_LATENCY);


--  in a clocked region?
procedure main(
	signal switches : in integer;
	signal main_pipeline : inout main_register_pipeline_t;
	signal return_  : out integer;
) is



-- Connections?
variable if_8_cond : boolean;

variable read_pipe : main_variables_t;
variable write_pipe : main_variables_t;
begin

	-- Loop to contruct clocks
	-- LATENCY=0 is combinational logic
	for STAGE in 0 to MAIN_LATENCY loop
		-- Stage 0 is inputs
		-- Stage input muxing
		if STAGE = 0 then
			--Pipe inputs
			read_pipe.switches := switches;
		else
			-- Default read from previous stage
			read_pipe := main_pipeline(STAGE-1);
		end if;
		-- Default write contents of previous stage
		write_pipe := read_pipe;
		
		
		--
		
		if STAGE = 0 then
			-- For each function, if offset=STAGE put procedure here
			-- Dont need to worry about order of operations 
			-- because we trust tool to make assignments make sense over time
			-- USE WRITE PIPE EVERYWHERE 
			SQRT(write_pipe.switches, write_pipe.sqrt_8_registers, write_pipe.sqrt_8_return)
			GT(write_pipe.sqrt_8_return, 2, write_pipe.gt_8_registers, write_pipe.gt_8_return) -- switches > 2
			write_pipe.rv10 := write_pipe.switches;
			write_pipe.rv14 := 0;
			-- For each variable involved in mux do individual 2 input muxing
			-- 			COND 					T				F					REGS				OUT
			MUX(write_pipe.gt_8_return, write_pipe.rv10, write_pipe.rv14,write_pipe.mux_8_registers, write_pipe._return)
		
		
		--elsif STAGE = 
		end if;
		
		
		-- Write to stage reg
		main_pipeline(STAGE) <= write_pipe;
		
	end loop;

	-- Last stage of pipeline return val
	return_ <= main_pipeline(MAIN_LATENCY)._return


end procedure;

'''




















# EACH C CODE EQUALS SIGN IS REGISTER TRANSFER (since always dealing with structs? when dealing w structs?)


# Good idea from Ada? " if the control flow of the task reaches an 
# ACCEPT statement, the task is blocked until 
# the corresponding entry is called by another task

# Allow WAIT statements in C code and should be delaying clock cycles?

# VHPI - C interface to VHDL simulation





# Do some processing on the user C code...


# SPEND TIME thinking about how C code should work and be parsed into VHDl

# Function call starts with single clock of valid AXIS data 
# New data can come the cycle after so either:
#	1) all of the function must complete before the next call 
# 	2) function calls act as independent threads?
# 2 is possible but best to start with basis of HDL, one clk at a time
# Directly connecting a stream (with no register delay) 
# should be done as a structutral feature in python
# Registered data can be done with function calls

# https://chisel.eecs.berkeley.edu/latest/getting-started.html
