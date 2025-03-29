/**
 * based on code from
 * https://github.com/chili-chips-ba/wireguard-fpga/blob/main/2.sw/app/chacha20poly1305/chacha20.c
*/

#include "intN_t.h"
#include "uintN_t.h"
#include "compiler.h"

#define CHACHA20_STATE_NWORDS 16
#define CHACHA20_KEY_NWORDS 32
#define CHACHA20_NONCE_NWORDS 12
#define CHACHA20_BLOCK_SIZE 64

// ChaCha20 state structure
typedef struct chacha20_state
{
    uint32_t state[CHACHA20_STATE_NWORDS]; // ChaCha20 state (16 words)
} chacha20_state;
// TODO is byte order for above struct little endian / does it match type_bytes_t.h?
#include "chacha20_state_bytes_t.h" // PipelineC byte casting funcs

// TODO use key and nonce structs if need to return these from funcs
/* // ChaCha20 key structure
typedef struct chacha20_key_t
{
    uint32_t key[CHACHA20_KEY_NWORDS]; // ChaCha20 key (32 words)
} chacha20_key_t;
// ChaCha20 nonce structure
typedef struct chacha20_nonce_t
{
    uint32_t nonce[CHACHA20_NONCE_NWORDS]; // ChaCha20 nonce (12 words)
} chacha20_nonce_t;*/

// ChaCha20 block as bytes structure
typedef struct chacha20_block_bytes_t
{
    uint8_t bytes[CHACHA20_BLOCK_SIZE]; // ChaCha20 block (64 bytes)
} chacha20_block_bytes_t;

// The ChaCha20 quarter round function
// TODO abcd are constants and might get better results if this function made into macro
chacha20_state quarter_round(chacha20_state s, uint4_t a, uint4_t b, uint4_t c, uint4_t d)
{
    chacha20_state o = s;

    // decompose ops
    uint32_t a1 = o.state[a] + o.state[b];
    uint32_t d1 = rotl32_16(o.state[d] ^ a1);
    uint32_t c1 = o.state[c] + d1;
    uint32_t b1 = rotl32_12(o.state[b] ^ c1);
    uint32_t a2 = a1 + b1;
    uint32_t d2 = rotl32_8(d1 ^ a2);
    uint32_t c2 = c1 + d2;
    uint32_t b2 = rotl32_7(b1 ^ c2);
    
    // join output
    o.state[a] = a2;
    o.state[b] = b2;
    o.state[c] = c2;
    o.state[d] = d2;

    return o;
}

chacha20_state chacha20_block_step(chacha20_state state0){
    // make a giant pipeline with 8 parallel ops
    chacha20_state state1 = quarter_round(state0, 0, 4, 8, 12);
    chacha20_state state2 = quarter_round(state1, 1, 5, 9, 13);
    chacha20_state state3 = quarter_round(state2, 2, 6, 10, 14);
    chacha20_state state4 = quarter_round(state3, 3, 7, 11, 15);
    chacha20_state state5 = quarter_round(state4, 0, 5, 10, 15);
    chacha20_state state6 = quarter_round(state5, 1, 6, 11, 12);
    chacha20_state state7 = quarter_round(state6, 2, 7, 8, 13);
    chacha20_state state8 = quarter_round(state7, 3, 4, 9, 14);
    return state8;
}

// ChaCha20 block function pipeline
chacha20_state chacha20_block(chacha20_state state)
{
    chacha20_state output;

    // 1. do 20 steps (2x each step) (giant pipeline)
    // TODO could be loop?
    chacha20_state step1  = chacha20_block_step(state);
    chacha20_state step2  = chacha20_block_step(step1);
    chacha20_state step3  = chacha20_block_step(step2);
    chacha20_state step4  = chacha20_block_step(step3);
    chacha20_state step5  = chacha20_block_step(step4);
    chacha20_state step6  = chacha20_block_step(step5);
    chacha20_state step7  = chacha20_block_step(step6);
    chacha20_state step8  = chacha20_block_step(step7);
    chacha20_state step9  = chacha20_block_step(step8);
    chacha20_state step10 = chacha20_block_step(step9);
    
    // 2. final parallel add
    uint4_t i;
    for (i = 0; i < 16; i+=1)
    {
        output.state[i] = step10.state[i] + state.state[i];
    }

    return output;
}


// ChaCha20 initialization function
chacha20_state chacha20_init(
  uint32_t key[CHACHA20_KEY_NWORDS], 
  uint32_t nonce[CHACHA20_NONCE_NWORDS], 
  uint32_t counter
){
    chacha20_state state;
    // Set the initial state (constants + key + nonce)
    // "expand 32-byte k"
    state.state[0] = 0x61707865; // "apxe"
    state.state[1] = 0x3320646e; // "3 dn"
    state.state[2] = 0x79622d32; // "yb-2"
    state.state[3] = 0x6b206574; // "k et"

    // Key
    uint8_t i;
    for (i = 0; i < 8; i+=1)
    {
        state.state[4 + i] = key[i];
    }

    // Counter
    state.state[12] = counter;

    // Nonce
    for (i = 0; i < 3; i+=1)
    {
        state.state[13 + i] = nonce[i];
    }

    return state;
}

/* Original software C
// ChaCha20 encryption/decryption function
void chacha20_encrypt(uint8_t *out, const uint8_t *in, size_t length, const uint8_t *key, const uint8_t *nonce, uint32_t counter)
{
    chacha20_state state;
    chacha20_state block;
    uint8_t *block_bytes = (uint8_t *)(block.state);

    while (length > 0)
    {
        chacha20_init(&state, key, nonce, counter);
        chacha20_block(&state, &block);

        size_t chunk_size = length > 64 ? 64 : length;
        for (size_t i = 0; i < chunk_size; i++)
        {
            out[i] = in[i] ^ block_bytes[i];
        }

        counter++;
        length -= chunk_size;
        out += chunk_size;
        in += chunk_size;
    }
}
// Pseudo code version of above chacha20_encrypt using fixed size arrays and no pointers
uint8_t[64] chacha20_encrypt_fixed(
  uint8_t in[64], 
  size_t length, 
  uint32_t key[32], 
  uint32_t nonce[12], 
  uint32_t counter
){
  chacha20_state state;
  chacha20_state block;
  uint8_t out[64];
  int pos = 0;
  while(length > 0){
    state = chacha20_init(key, nonce, counter);
    block = chacha20_block(state);
    uint8_t block_bytes[64] = chacha20_state_to_bytes(block);
    size_t chunk_size = length > 64 ? 64 : length;
    for (size_t i = 0; i < chunk_size; i++)
    {
      out[pos] = in[pos] ^ block_bytes[i];
      pos++;
    }
    counter++;
    length -= chunk_size;
  }
  return out;
}*/
// PipelineC code for the loop body above
chacha20_block_bytes_t chacha20_encrypt_loop_body(
  chacha20_block_bytes_t in_data,
  uint32_t key[CHACHA20_KEY_NWORDS], 
  uint32_t nonce[CHACHA20_NONCE_NWORDS],
  uint32_t counter
){
  chacha20_state state = chacha20_init(key, nonce, counter);
  chacha20_state block = chacha20_block(state);

  // PipelineC byte casting funcs
  chacha20_state_bytes_t bytes = chacha20_state_to_bytes(block);
  chacha20_block_bytes_t block_bytes = {.bytes = bytes.data};

  chacha20_block_bytes_t out_data;
  // TODO partial in data, i.e. partial tkeep
  //    size_t chunk_size = length > 64 ? 64 : length;
  for(uint32_t i = 0; i < CHACHA20_BLOCK_SIZE; i+=1)
  {
    out_data.bytes[i] = in_data.bytes[i] ^ block_bytes.bytes[i];
  }
  return out_data;
}
