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
		// Use locals to avoid some bad vhdl generation for now :(
		uint8_t key1_local[KEY_MAX_LEN];
		key1_local = key1;
		uint8_t key2_local[KEY_MAX_LEN];
		key2_local = key2;
		
		// Zero out everything past len
		packet_iter_t i;
		for(i = 0; i < KEY_MAX_LEN; i = i + 1)
		{
			if(i >= len1)
			{
				key1_local[i] = 0;
				key2_local[i] = 0;
			}
		}

		// C doesnt support equal operator on structs or arrays
		// Cast array of bytes to single uint value for compare then
		key_uint_t key1_uint;
		key1_uint = key_to_uint(key1_local);
		key_uint_t key2_uint;
		key2_uint = key_to_uint(key2_local);
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
/*
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
}*/

// Thanks Bob -Julian

//typedef  unsigned long  int  ub4;   /* unsigned 4-byte quantities */
//typedef  unsigned       char ub1;   /* unsigned 1-byte quantities */

//#define hashsize(n) ((ub4)1<<(n))
//#define hashmask(n) (hashsize(n)-1)

/*
--------------------------------------------------------------------
mix -- mix 3 32-bit values reversibly.
For every delta with one or two bits set, and the deltas of all three
  high bits or all three low bits, whether the original value of a,b,c
  is almost all zero or is uniformly distributed,
* If mix() is run forward or backward, at least 32 bits in a,b,c
  have at least 1/4 probability of changing.
* If mix() is run forward, every bit of c will change between 1/3 and
  2/3 of the time.  (Well, 22/100 and 78/100 for some 2-bit deltas.)
mix() was built out of 36 single-cycle latency instructions in a 
  structure that could supported 2x parallelism, like so:
      a -= b; 
      a -= c; x = (c>>13);
      b -= c; a ^= x;
      b -= a; x = (a<<8);
      c -= a; b ^= x;
      c -= b; x = (b>>13);
      ...
  Unfortunately, superscalar Pentiums and Sparcs can't take advantage 
  of that parallelism.  They've also turned some of those single-cycle
  latency instructions into multi-cycle latency instructions.  Still,
  this is the fastest good hash I could find.  There were about 2^^68
  to choose from.  I only looked at a billion or so.
--------------------------------------------------------------------
*/
typedef struct mix_t
{
	uint32_t a;
	uint32_t b;
	uint32_t c;
} mix_t;
mix_t mix(uint32_t a, uint32_t b, uint32_t c)
{  
  a = a - b; a = a - c; a = a ^ (c>>13);
  b = b - c; b = b - a; b = b ^ (a<<8);
  c = c - a; c = c - b; c = c ^ (b>>13);
  a = a - b; a = a - c; a = a ^ (c>>12); 
  b = b - c; b = b - a; b = b ^ (a<<16);
  c = c - a; c = c - b; c = c ^ (b>>5);
  a = a - b; a = a - c; a = a ^ (c>>3);
  b = b - c; b = b - a; b = b ^ (a<<10);
  c = c - a; c = c - b; c = c ^ (b>>15);
  
  mix_t rv;
  rv.a = a;
  rv.b = b;
  rv.c = c;
  return rv;  
}

/*
--------------------------------------------------------------------
hash() -- hash a variable-length key into a 32-bit value
  k       : the key (the unaligned variable-length array of bytes)
  len     : the length of the key, counting by bytes
  initval : can be any 4-byte value
Returns a 32-bit value.  Every bit of the key affects every bit of
the return value.  Every 1-bit and 2-bit delta achieves avalanche.
About 6*len+35 instructions.

The best hash table sizes are powers of 2.  There is no need to do
mod a prime (mod is sooo slow!).  If you need less than 32 bits,
use a bitmask.  For example, if you need only 10 bits, do
  h = (h & hashmask(10));
In which case, the hash table should have hashsize(10) elements.

If you are hashing n strings (ub1 **)k, do it like this:
  for (i=0, h=0; i<n; ++i) h = hash( k[i], len[i], h);

By Bob Jenkins, 1996.  bob_jenkins@burtleburtle.net.  You may use this
code any way you wish, private, educational, or commercial.  It's free.

See http://burtleburtle.net/bob/hash/evahash.html
Use for hash table lookup, or anything where one collision in 2^^32 is
acceptable.  Do NOT use for cryptographic purposes.
--------------------------------------------------------------------
*/

uint32_t hash(uint8_t k[KEY_MAX_LEN], key_len_t length) //, initval)
//register ub1 *k;        /* the key */
//register uint32_t  length;   /* the length of the key */
//register uint32_t  initval;  /* the previous hash, or an arbitrary value */
{
	uint32_t a,b,c; //,len;
	key_len_t len;
	/* Set up the internal state */
	len = length;
	a = 2654435769; //0x9e3779b9;  /* the golden ratio; an arbitrary value */
	b = 2654435769; //0x9e3779b9;  /* the golden ratio; an arbitrary value */
	c = 2654435769; //initval;         /* the previous hash value */
	packet_iter_t i;
	mix_t mix;
	mix.a = a;
	mix.b = b;
	mix.c = c;
	
	/*---------------------------------------- handle most of the key */
	for(i=0; i < KEY_MAX_LEN_MINUS_12; i = i + 12)
	{
		if(len >= 12)
		{
			a = a + (k[i+0] +(k[i+1]<<8) +(k[i+2]<<16) +(k[i+3]<<24));
			b = b + (k[i+4] +(k[i+5]<<8) +(k[i+6]<<16) +(k[i+7]<<24));
			c = c + (k[i+8] +(k[i+9]<<8) +(k[i+10]<<16)+(k[i+11]<<24));
			mix = mix(a,b,c);
			a = mix.a;
			b = mix.b;
			c = mix.c;
			len = len - 12;
		}
	}

	/*------------------------------------- handle the last 11 bytes */
	i = len - 1;
	c = c + length;
	//switch(len)              /* all the case statements fall through */
	//{
	if(len == 11) c = c + (k[i+10]<<24);
	if(len >= 10) c = c + (k[i+9]<<16);
	if(len >= 9 ) c = c + (k[i+8]<<8);
	  /* the first byte of c is reserved for the length */
	if(len >= 8 ) b = b + (k[i+7]<<24);
	if(len >= 7 ) b = b + (k[i+6]<<16);
	if(len >= 6 ) b = b + (k[i+5]<<8);
	if(len >= 5 ) b = b + k[i+4];
	if(len >= 4 ) a = a - (k[i+3]<<24);
	if(len >= 3 ) a = a - (k[i+2]<<16);
	if(len >= 2 ) a = a - (k[i+1]<<8);
	if(len >= 1 ) a = a - k[i+0];
	 /* case 0: nothing left to add */
	//}
	
	mix = mix(a,b,c);
	a = mix.a;
	b = mix.b;
	c = mix.c;
	/*-------------------------------------------- report the result */
	return c;
}
