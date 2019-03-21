#pragma once
#include "../../stream.h" // SBUF macro

#include "protocol.h"
#include "mem.c"


// Hash related stuff:
// 	1) The hash function
//  2) The hash map/table/dictionary functionality 


// Helper function to compare two variable length keys
uint1_t keys_match(uint8_t key1[KEY_MAX_LEN], key_len_t len1, 
			       uint8_t key2[KEY_MAX_LEN], key_len_t len2)
{
	uint1_t match;
	// Same length
	if(len1 == len2)
	{
		// Zero out everything past len
		packet_iter_t i;
		for(i = 0; i < KEY_MAX_LEN; i = i + 1)
		{
			if(i >= len1)
			{
				key1[i] = 0;
				key2[i] = 0;
			}
		}

		// C doesnt support equal operator on structs or arrays
		// Cast array of bytes to single uint value for compare then
		key_uint_t key1_uint;
		key1_uint = key_to_uint(key1);
		key_uint_t key2_uint;
		key2_uint = key_to_uint(key2);
		match = key1_uint == key2_uint;
	} 
	else
	{
		// Not same length
		match = 0;
	}
	return match;
} 


// Helper function for finding position of matching key
// -1 if not found
key_pos_t find_matching_key(entry_set_t set, uint8_t key[KEY_MAX_LEN], key_len_t key_len)
{
	// Do compares in parallel, only one match wil be found , ONE HOT
	// Or matches together to get result
	uint1_t key_match[SET_SIZE];
	set_iter_t key_positions[SET_SIZE];
	set_iter_t i;
	for(i=0;i<SET_SIZE; i = i + 1)
	{
		key_match[i] = keys_match(set.entries[i].key, set.entries[i].key_len,
							      key, key_len);
		if(key_match[i])
		{
			key_positions[i] = i;
		}
		else
		{
			key_positions[i] = 0;
		}
	}
	// Did we find match?
	uint1_t found_match;
	found_match = set_key_match_or(key_match); 
	key_pos_t rv;
	rv = -1;
	if(found_match)
	{
		rv = set_key_pos_or(key_positions);
	}
	return rv;
}


// Shift everything else back in LRU, put write at front most recent
// If item already in set then shift LRU back into that space, put write at front most recent
entry_set_t write_entry_set(entry_set_t set, entry_t data, key_pos_t existing_key_pos)
{
	// Some data is being shifted out for LRU adjustment
	// It might be the existing old data being shifted out to go front
	// Or it might just be the least recently used.
	// Default to moving out the least recently used at end of array
	set_iter_t to_move;
	to_move = SET_SIZE_MINUS1;
	// If key exists in set then use that instead
	if(existing_key_pos != -1)
	{
		to_move = existing_key_pos;
	}
		
	// Everything more recent moves back
	set_iter_t i;
	for(i=SET_SIZE_MINUS1; i > 0; i = i - 1)
	{
		if(i <= to_move)
		{
			set.entries[i] = set.entries[i-1];
		}
	}
	
	// Write to front
	set.entries[0] = data;
	return set;
}

// Adjust LRU if found
entry_set_t read_entry_set(entry_set_t set, key_pos_t existing_key_pos)
{
	// If in set then need to move to front of LRU
	if(existing_key_pos != -1)
	{
		entry_t write_back_data;
		write_back_data = set.entries[existing_key_pos];
		// Everything more recent moves back
		set_iter_t i;
		set_iter_t key_pos;
		key_pos = existing_key_pos; // Know existing_key_pos is >=0 
		for(i=SET_SIZE_MINUS1; i > 0; i = i - 1)
		{
			if(i <= key_pos)
			{
				set.entries[i] = set.entries[i-1];
			}
		}
		set.entries[0] = write_back_data;
	}
	return set;
}

// ^ TODO Can combine LRU shifting into one func, 
// dont need to duplicate for read and write

// Request read or write of a key,value pair
typedef struct hash_map_request_t
{
	addr_t address; // Hash calculated in advance
	uint8_t key[KEY_MAX_LEN];
	key_len_t key_len;
	uint8_t write_value[VALUE_MAX_LEN];
	value_len_t write_value_len;
	uint1_t write_en;	
} hash_map_request_t;
typedef struct hash_map_request_s
{
	hash_map_request_t data;
	uint1_t valid;
} hash_map_request_s;

// Result is read data (for reads, writes dont return anything)
typedef struct hash_map_result_t
{
	entry_t read_data;
	uint1_t read_valid;
} hash_map_result_t;
typedef struct hash_map_result_s
{
	hash_map_result_t data;
	uint1_t valid;
} hash_map_result_s;

// Input and output buffers needed since volatile globals used
SBUF(hash_map_request_s, hash_map_input_buffer)
SBUF(hash_map_result_s, hash_map_output_buffer)

// Doing hash lookup has multiple parts
typedef enum hash_map_state_t 
{
	GET_REQ,
	READ_START,
	READ_END,
	WRITE_START,
	WRITE_END
} hash_map_state_t;
volatile hash_map_state_t hash_map_state;
volatile hash_map_request_t hash_map_request;
volatile entry_set_t hash_map_write_data;
volatile key_pos_t hash_map_existing_key_pos; // -1 if not found
// Volatile global variables arent always valid
volatile uint1_t hash_map_volatiles_valid = 1;
hash_map_result_s do_hash_map(hash_map_request_s incoming_request, uint1_t read_result)
{	
	// Volatile state is not valid every iteration
	// But incoming request could show up any iteration
	// Buffer incoming requests
	uint1_t input_buffer_read_en;
	input_buffer_read_en = (hash_map_state==GET_REQ) & hash_map_volatiles_valid;
	hash_map_request_s buffered_request;
	buffered_request = hash_map_input_buffer(incoming_request, input_buffer_read_en);
	// Replace the current request if something shows up in buffer
	if(buffered_request.valid)
	{
		hash_map_request = buffered_request.data;
	}
	
	// Because of the buffer, from here on out all code is written knowing
	// only a single request is in process at any given time 
	// (as opposed to back to back stream of requests)
	
	// Leave state when we pulled new request from the buffer
	if(buffered_request.valid)
	{
		// Regardless of hash map operation we start with a memory read (to adjust LRU)
		hash_map_state = READ_START;
	}

	// Memory is global, so can only be used in one func
	// So memory read and write is one function
	mem_request_s mem_request;
	// Set invalid/partial defaults
	mem_request.valid = 0;
	mem_request.data.address = hash_map_request.address;
	mem_request.data.write_data = hash_map_write_data; // Set after read
	mem_request.data.write_en = 0;
	// Determine when to make a memory request
	if(hash_map_volatiles_valid)
	{
		if(hash_map_state==READ_START)
		{
			mem_request.valid = 1;
		}
		else if(hash_map_state==WRITE_START)
		{
			mem_request.data.write_en = 1;
			mem_request.valid = 1;
		}
	}

	// Read memory result if state is valid (doesnt matter result of read or write)
	uint1_t mem_read_result;
	mem_read_result = hash_map_volatiles_valid;
	// Do hash map RW
	mem_result_s mem_result;
	mem_result = do_mem(mem_request, mem_read_result);
	
	// If started read or write, switch to ending state
	if(mem_request.valid)
	{
		if(hash_map_state==READ_START)
		{
			hash_map_state = READ_END;
		}
		else if(hash_map_state==WRITE_START)
		{
			hash_map_state = WRITE_END;
		}
	}
	
	// Got memory result? What were we ending a read or write?
	// Ending write or read determines output
	// Start with partial/invalid defaults
	hash_map_result_s output;
	output.valid = 0;
	output.data.read_data = hash_map_write_data.entries[0]; // Read data was written back at most recent position in LRU
	output.data.read_valid = hash_map_existing_key_pos != -1;
	if(mem_result.valid)
	{
		if(hash_map_state==READ_END)
		{
			// Just read an entry set from memory
			// Does the key,value already exist in the cache?
			hash_map_existing_key_pos = find_matching_key(mem_result.data.read_data, hash_map_request.key, hash_map_request.key_len);

			// Ending read, was this for a READ operation or WRITE?
			if(hash_map_request.write_en)
			{
				// WRITE OPERATION
				// Write into the entry_set
				entry_t write_entry;
				write_entry.key = hash_map_request.key;
				write_entry.key_len = hash_map_request.key_len;
				write_entry.value = hash_map_request.write_value;
				write_entry.value_len = hash_map_request.write_value_len;
				hash_map_write_data = write_entry_set(mem_result.data.read_data, write_entry, hash_map_existing_key_pos);
				// Then start write back process
				hash_map_state = WRITE_START;
			}
			else
			{
				// READ OPERATION
				// Adjust the LRU in the set and write it back
				hash_map_write_data = read_entry_set(mem_result.data.read_data, hash_map_existing_key_pos);
				// Start write back process
				hash_map_state = WRITE_START;	
			}		
		}
		else if(hash_map_state==WRITE_END)
		{
			// Ending write, was this for a READ operation or WRITE?
			// Doesnt matter, output is ready now
			output.valid = 1;
			// Start next request
			hash_map_state = GET_REQ;
		}
	}
	
	
	// Output buffer
	return hash_map_output_buffer(output, read_result);
}


// The hash function
addr_t hash(uint8_t data[KEY_MAX_LEN], key_len_t len)
{
	// Uhhh not interested in deciding on hash function right now
	// Just sum as filler logic
	// Zero out everything past len
	packet_iter_t i;
	key_len_t len_minus1;
	len_minus1 = len -1;
	for(i=0; i<KEY_MAX_LEN; i = i+ 1)
	{
		if(i > len_minus1)
		{
			data[i] = 0;
		}
	}
	// Sum everything
	addr_t sum;
	sum = sum_key(data);
	
	return sum;
}
