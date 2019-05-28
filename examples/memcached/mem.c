#pragma once
// Access to memory (just an entry_set_t block RAM)

#include "protocol.h"
#include "../../stream.h" // SBUF macro

// Request to memory is read+write address and data
typedef struct mem_request_t
{
	addr_t address;
	entry_set_t write_data;
	uint1_t write_en;
} mem_request_t;
typedef struct mem_request_s
{
	mem_request_t data;
	uint1_t valid;
} mem_request_s;

// Result of accessing memory right just reads+writes a single entry_set_t
typedef struct mem_result_t
{
	entry_set_t read_data;	
} mem_result_t;
typedef struct mem_result_s
{
	mem_result_t data;
	uint1_t valid;
} mem_result_s;

// Wrapper for more complicated memory
// Currently just 2 clk RAM_SP_RF_2
typedef enum mem_state_t 
{
	CLK0_INPUT,
	CLK1_WAIT,
	CLK2_OUTPUT
} mem_state_t;

// Buffer output data until read_result
SBUF(mem_result_s, mem_output_buffer)
// The main memory
entry_set_t entry_sets[NUM_ENTRY_SETS];
// State for 2 clk BRAM
mem_state_t mem_state;

mem_result_s do_mem(mem_request_s request, uint1_t read_result)
{
	// Only signal write during the input state
	uint1_t write_en;
	write_en = 0;
	if(mem_state == CLK0_INPUT)
	{
		// Wait for input request
		if(request.valid)
		{
			// Got new request, go to next state
			mem_state = CLK1_WAIT;		
			// Write enable as requested
			write_en = request.data.write_en;
		}
	}
	
	// The 2 clk RAM_SP_RF instance
	entry_set_t rd_data;
	rd_data = entry_sets_RAM_SP_RF_2(request.data.address, request.data.write_data, write_en);
	
	// Only thing wait state does is go to next state
	if(mem_state == CLK1_WAIT)
	{
		mem_state = CLK2_OUTPUT;		
	}
	
	// Only output data during output state
	mem_result_s output;
	output.data.read_data = rd_data;
	output.valid = 0;
	if(mem_state == CLK2_OUTPUT)
	{
		output.valid = 1;
		// Back to first state
		mem_state = CLK0_INPUT;	
	}
	return mem_output_buffer(output, read_result);
}
