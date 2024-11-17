#pragma once
// Logic for doing a memcached request/command

#include "protocol.h"
#include "hash.c"

// Only supporting GET and SET right now
#define GET 0
#define SET 1

// Result includes original request and result of the hash table lookup
typedef struct memcached_command_result_t
{
	memcached_packet_t request;
	hash_map_result_t hash_map_result;
} memcached_command_result_t;
typedef struct memcached_command_result_s
{
	memcached_command_result_t data;
	uint1_t valid;
} memcached_command_result_s;

// Input buffer since using volatile globals
SBUF(memcached_packet_s, command_input_buffer)

// Doing commmand has multple parts
typedef enum command_state_t 
{
	GET_REQ,
	READ_START,
	READ_END,
	WRITE_START,
	WRITE_END
} command_state_t;
volatile command_state_t command_state;
volatile memcached_packet_t command_request;
volatile uint1_t command_volatiles_valid = 1;
// We assume only one of these rmws are in process at a given time
memcached_command_result_s do_commands(memcached_packet_s incoming_request)
{	
	// Volatile state is not valid every iteration
	// But incoming request could show up any iteration
	// Use global state (inside other func) to hold incoming request until state is valid
	// Only read out that request when state is valid
	uint1_t input_buffer_read_en;
	input_buffer_read_en = (command_state==GET_REQ) & command_volatiles_valid;
	memcached_packet_s buffered_request;
	buffered_request = command_input_buffer(incoming_request, input_buffer_read_en);
	// Replace the current request if something shows up in buffer
	if(buffered_request.valid)
	{
		command_request = buffered_request.data;
	}
	
	// Because of the buffer, from here on out all code is written knowing
	// only a single request is in process at any given time 
	// (as opposed to constant stream of incoming requests)
	
	// Leave state when we pulled new request from the buffer
	if(buffered_request.valid)
	{
		// What is the command?
		if(command_request.header.opcode == GET)
		{
			// Start the read
			command_state = READ_START;
		}
		else // SET
		{
			// Start the write
			command_state = WRITE_START;
		}
	}

	// Memory is global, so can only be used in one func
	// So hash_map read and write is one function
	hash_map_request_s hash_map_request;
	// Set invalid/partial defaults
	hash_map_request.valid = 0;
	hash_map_request.data.address = command_request.address;
	hash_map_request.data.key = command_request.key;
	hash_map_request.data.key_len = command_request.header.key_len;
	hash_map_request.data.write_value = command_request.value;
	hash_map_request.data.write_value_len = command_request.value_len;
	hash_map_request.data.write_en = 0;	
	// Determine actual contents of request
	if(command_volatiles_valid)
	{
		if(command_state==READ_START)
		{
			hash_map_request.valid = 1;
		}
		else if(command_state==WRITE_START)
		{
			hash_map_request.data.write_en = 1;
			hash_map_request.valid = 1;
		}
	}

	// Read hash map result if state is valid (doesnt matter result of read or write)
	uint1_t hash_map_result_read_en;
	hash_map_result_read_en = command_volatiles_valid;
	// Do hash map RW
	hash_map_result_s hash_map_result;
	hash_map_result = do_hash_map(hash_map_request, hash_map_result_read_en);
	
	// If started either read or write, switch to end
	if(hash_map_request.valid)
	{
		if(command_state==READ_START)
		{
			command_state = READ_END;
		}
		else if(command_state==WRITE_START)
		{
			command_state = WRITE_END;
		}
	}
	
	// Got hash_map result? What were we ending a read or write?
	// Ending write or read determines output
	memcached_command_result_s rv;
	rv.valid = 0;
	rv.data.request = command_request;
	rv.data.hash_map_result = hash_map_result.data; // Need some default
	if(hash_map_result.valid)
	{
		if(command_state==READ_END)
		{
			// Ending read
			// What was the command?
			if(command_request.header.opcode == GET)
			{
				// GET is just a read, done now
				rv.valid = 1;
				// Start next request
				command_state = GET_REQ;
			}
			// No other commands do reads yet			
		}
		else if(command_state==WRITE_END)
		{
			// Ending write
			// What was the command?
			if(command_request.header.opcode == SET)
			{
				// SET is just a write, done now
				rv.valid = 1;
				// Start next request
				command_state = GET_REQ;
			}
			// No other commands do writes yet		
		}
	}
	
	return rv;
}


// Doing requests means taking an input request 
// and returning the result of some previous request
memcached_command_result_s do_requests(memcached_packet_s incoming_request)
{		
	// Hash:
	// Do hash before getting into actual functionality of the command
	// (commands keep state between requests thus using 
	//  slow global mem, hash can be kept stateless and fast)
	incoming_request.data.address = hash(incoming_request.data.key, incoming_request.data.header.key_len);

	// Doing commands means taking an input command
	// and returning the result of some previous command
	memcached_command_result_s outgoing_command_result;
	outgoing_command_result = do_commands(incoming_request);
	
	return outgoing_command_result;
}
