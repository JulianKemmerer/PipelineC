/**
 * based on code from
 * https://github.com/chili-chips-ba/wireguard-fpga/blob/main/2.sw/app/chacha20poly1305/chacha20.c
*/

// Includes
#include "intN_t.h"
#include "uintN_t.h"
#include "compiler.h"

// Install part
#pragma PART "LFE5U-85F-6BG381C"

#define CHACHA20_KEY_SIZE 32
#define CHACHA20_NONCE_SIZE 12
#define CHACHA20_BLOCK_SIZE 64

// ChaCha20 state structure
typedef struct chacha20_state
{
    uint32_t state[16]; // ChaCha20 state (16 words)
} chacha20_state;

// ChaCha20 key structure
typedef struct chacha20_key_t
{
    uint32_t key[CHACHA20_KEY_SIZE]; // ChaCha20 key (32 words)
} chacha20_key_t;

// ChaCha20 nonce structure
typedef struct chacha20_nonce_t
{
    uint32_t nonce[CHACHA20_NONCE_SIZE]; // ChaCha20 nonce (12 words)
} chacha20_nonce_t;

// The ChaCha20 quarter round function
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
chacha20_state chacha20_init(chacha20_key_t key, chacha20_nonce_t nonce, uint32_t counter)
{
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
        state.state[4 + i] = key.key[i];
    }

    // Counter
    state.state[12] = counter;

    // Nonce
    for (i = 0; i < 3; i+=1)
    {
        state.state[13 + i] = nonce.nonce[i];
    }

    return state;
}

// FAKE TEST
#pragma MAIN_MHZ main 80.0
chacha20_state main(){
    static uint32_t counter;

    // change for actual key ?
    chacha20_key_t key = {{
        0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF,
        0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF,
        0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF,
        0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF
    }};

    // change for actual nonce ?
    chacha20_nonce_t nonce = {{
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        0x00000000, 0x00000000, 0x00000000, 0x00000000
    }};

    // these 3 steps would be on a FSM
    chacha20_state state = chacha20_init(key, nonce, counter);
    chacha20_state block = chacha20_block(state);
    counter += 1;

    return block;
}
