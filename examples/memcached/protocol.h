#pragma once
#include "../../uintN_t.h"
#include "../../intN_t.h"

// Memcached related sizes, types, constants, etc

// xc7a35ticsg324
// 	key,val max len 250 , num sets 64 = 630% luts
// 	key,val max len 128 , num sets 32 = 321% luts
// 	key,val max len 64 , num sets 16 = 152% luts
// 	key,val max len 32 , num sets 8 = 71% luts
// Seems like logic, as opposed to memory scales badly
// So decrease logic by decreasing size of key
// 	key,val max len 8 (64b words?) , num sets 128 = 28% luts
// 	key,val max len 8 (64b words?) , num sets 1024 = 67% luts
// 	key,val max len 8 (64b words?) , num sets 2048 = 111% luts
//  key,val max len 16, num sets 1024 = 132% luts (real hash too)
//  key,val max len 16, num sets 512 = 86% luts (real hash too)
// Switched to using 2 clk SP RF BRAMS for mem (real hash too)
//  key,val max len 16, num sets 512 = 94% BRAMS, 58% luts (mem not all as BRAMS since using all of them, overflow to luts?)
//  key,val max len 16, num sets 1024 = 94% BRAMS, 79% luts  <<< BEST?
//  key,val max len 16, num sets 2048 = 94% BRAMS, 110% luts
//  key,val max len 32, num sets 1024 = 94% BRAMS, 183% luts

// Generic functionality for extras, key, and value sizes
#define EXTRAS_MAX_LEN 16
#define KEY_MAX_LEN 16 // HASH REQUIRES KEY OF AT LEAST 12 BYTES
#define key_len_t uint5_t
#define VALUE_MAX_LEN 16
#define value_len_t uint5_t
// Iterator to use for any variable length data (extras, key, and value sizes)
#define packet_iter_t uint4_t
#define packet_len_t uint5_t
// Helper functions for key byte arrays
#define key_to_uint uint8_array16_le
#define key_uint_t uint128_t
#define sum_key uint8_array_sum16

// Resolve hash collisions with 'associative set'
#define SET_SIZE 4
#define SET_SIZE_MINUS1 3
#define set_iter_t uint2_t
#define key_pos_t int3_t // Signed version set iter
// Helper functions for OR reducing set entry comparisons
#define set_key_match_or uint1_array_or4
#define set_key_pos_or uint2_array_or4

// What is stored at each entry in the dictionary?
typedef struct entry_t
{
	// Copy of key for find in set
	uint8_t key[KEY_MAX_LEN];
	key_len_t key_len;
	// The value
	uint8_t value[VALUE_MAX_LEN];
	value_len_t value_len;
} entry_t;

// 'Associative set' wrapped in struct for now
// (plain old type defs arent supported yet)
// Also can't return arrays in C
typedef struct entry_set_t
{
	entry_t entries[SET_SIZE];
} entry_set_t;

// How many of these sets to store?
#define NUM_ENTRY_SETS 1024
#define addr_t uint10_t

// Packet stuff
typedef struct memcached_header_t
{
	uint8_t magic;
	uint8_t opcode;
	uint16_t key_len;
	uint8_t extras_len;
	uint8_t data_type;
	uint16_t vbucket_status;
	uint32_t total_body_len;
	uint32_t opaque;
	uint64_t cas;
} memcached_header_t;

typedef struct memcached_packet_t
{
	memcached_header_t header;
	uint8_t extras[EXTRAS_MAX_LEN];
	uint8_t key[KEY_MAX_LEN];
	uint8_t value[VALUE_MAX_LEN]; 
	// Not pulled from packet data but here for convenience 
	value_len_t value_len;
	addr_t address;
} memcached_packet_t;

// '_s' (stream?) is shorthand for .data+.valid
typedef struct memcached_packet_s
{
	memcached_packet_t data;
	uint1_t valid;
} memcached_packet_s;
