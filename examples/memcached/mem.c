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

// Result of accessing memory right jsut reads+writes a single entry_set_t
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
// Currently just 0 clk RAM_SP_RF
	
// Buffer output data until read_result
SBUF(mem_result_s, mem_output_buffer)
// The main memory
entry_set_t entry_sets[NUM_ENTRY_SETS];
mem_result_s do_mem(mem_request_s request, uint1_t read_result)
{
	entry_set_t rd_data;
	uint1_t valid_write_en;
	valid_write_en = request.valid & request.data.write_en;
	rd_data = entry_sets_RAM_SP_RF(request.data.address, request.data.write_data, valid_write_en);
	mem_result_s output;
	output.data.read_data = rd_data;
	output.valid = request.valid;
	return mem_output_buffer(output, read_result);
}
