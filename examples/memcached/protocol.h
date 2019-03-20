#include "../../uintN_t.h"
#include "../../intN_t.h"

// Memcached related sizes, types, constants, etc

// Generic functionality for extras, key, and value sizes
#define EXTRAS_MAX_LEN 16
#define KEY_MAX_LEN 250
#define key_len_t uint8_t
#define VALUE_MAX_LEN 250
#define value_len_t uint8_t
// Iterator to use for any variable length data (extras, key, and value sizes)
#define packet_iter_t uint8_t
#define packet_len_t uint8_t
// Helper functions for key byte arrays
#define key_to_uint uint8_array250_le
#define key_uint_t uint2000_t
#define sum_key uint8_array_sum250

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
#define NUM_ENTRY_SETS 64
#define addr_t uint6_t

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

