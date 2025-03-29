#include "chacha20poly1305.h"

#pragma PART "xc7a200tffg1156-2" // Artix 7 200T

/*
// Flattened top level ports with AXIS style manager/subdorinate naming
// (could also have inputs and outputs of type stream(my_axis_32_t)
//  but ex. Verilog does not support VHDL records...)
// Input Stream
DECL_INPUT(uint128_t, s_axis_tdata)
DECL_INPUT(uint16_t, s_axis_tkeep)
DECL_INPUT(uint1_t, s_axis_tlast)
DECL_INPUT(uint1_t, s_axis_tvalid)
DECL_OUTPUT(uint1_t, s_axis_tready)
// Output Stream
DECL_OUTPUT(uint128_t, m_axis_tdata)
DECL_OUTPUT(uint16_t, m_axis_tkeep)
DECL_OUTPUT(uint1_t, m_axis_tlast)
DECL_OUTPUT(uint1_t, m_axis_tvalid)
DECL_INPUT(uint1_t, m_axis_tready)
*/

// The primary dataflow for single clock domain ChaCha20-Poly1305 encryption
// For now just testing the encrypt loop body
#pragma MAIN_MHZ main 80.0
chacha20_block_bytes_t main(
  chacha20_block_bytes_t in_data,
  uint32_t key[CHACHA20_KEY_NWORDS], 
  uint32_t nonce[CHACHA20_NONCE_NWORDS],
  uint32_t counter
){
  chacha20_block_bytes_t out_data = chacha20_encrypt_loop_body(
    in_data,
    key, 
    nonce,
    counter
  );
  return out_data;
}

// TODO revive simulation demo
/* FAKE TEST
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
}*/