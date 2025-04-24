/*
int chacha20poly1305_encrypt(
    uint8_t *ciphertext,
    uint8_t *auth_tag,
    const uint8_t *key,
    const uint8_t *nonce,
    const uint8_t *plaintext,
    size_t plaintext_len,
    const uint8_t *aad,
    size_t aad_len)
{
    // 1. Generate Poly1305 one-time key using the first 32 bytes of ChaCha20 keystream with counter 0
    uint8_t poly1305_key[32];
    poly1305_key_gen(poly1305_key, key, nonce);

    // 2. Encrypt plaintext using ChaCha20 starting with counter 1
    chacha20_encrypt(ciphertext, plaintext, plaintext_len, key, nonce, 1);

    // 3. Prepare the authenticated data for Poly1305
    // Allocate memory for AAD || padding || ciphertext || padding || AAD length || ciphertext length
    size_t aad_padding = (16 - (aad_len % 16)) % 16;
    size_t ciphertext_padding = (16 - (plaintext_len % 16)) % 16;
    size_t auth_data_len = aad_len + aad_padding + plaintext_len + ciphertext_padding + 16;

    uint8_t *auth_data = (uint8_t *)calloc(auth_data_len, 1);
    if (!auth_data)
        return -1; // Memory allocation failure

    // Copy AAD
    if (aad && aad_len > 0)
        memcpy(auth_data, aad, aad_len);

    // Copy ciphertext after AAD (and padding)
    memcpy(auth_data + aad_len + aad_padding, ciphertext, plaintext_len);

    // Append AAD and ciphertext lengths as little-endian 64-bit integers
    uint8_t *lengths = auth_data + aad_len + aad_padding + plaintext_len + ciphertext_padding;
    encode_le64(lengths, aad_len);
    encode_le64(lengths + 8, plaintext_len);

    // 4. Compute the Poly1305 tag over the authenticated data
    poly1305_mac(auth_tag, poly1305_key, auth_data, auth_data_len);

    free(auth_data);
    return 0;
}
*/
#include "arrays.h"
// Instance of chacha20 part of encryption
#include "chacha20/chacha20_encrypt.c"
// Instance of preparing auth data part of encryption
#include "prep_auth_data/prep_auth_data.c"
// Instance of poly1305 part of encryption
#include "poly1305/poly1305_mac_loop_fsm.c"

// The primary dataflow for single clock domain ChaCha20-Poly1305 encryption
#pragma PART "xc7a200tffg1156-2" // Artix 7 200T
#pragma MAIN_MHZ main 80.0

// Flattened top level ports with AXIS style manager/subordinate naming
// (could also have inputs and outputs of type stream(my_axis_32_t)
//  but ex. Verilog does not support VHDL records...)
// Top level input wires
DECL_INPUT(uint1024_t, key)
DECL_INPUT(uint384_t, nonce)
DECL_INPUT(uint32_t, counter)
DECL_INPUT(uint256_t, poly1305_key)
// Top level input Stream
DECL_INPUT(uint128_t, s_axis_tdata)
DECL_INPUT(uint16_t, s_axis_tkeep)
DECL_INPUT(uint1_t, s_axis_tlast)
DECL_INPUT(uint1_t, s_axis_tvalid)
DECL_OUTPUT(uint1_t, s_axis_tready)
// Top level output wires
DECL_OUTPUT(uint128_t, poly1305_auth_tag)
DECL_OUTPUT(uint1_t, poly1305_auth_tag_valid)
// Top level output Stream
DECL_OUTPUT(uint128_t, m_axis_tdata)
DECL_OUTPUT(uint16_t, m_axis_tkeep)
DECL_OUTPUT(uint1_t, m_axis_tlast)
DECL_OUTPUT(uint1_t, m_axis_tvalid)
DECL_INPUT(uint1_t, m_axis_tready)

void main(){
    // Convert flattened multiple input wires to stream(axis128_t)
    stream(axis128_t) s_axis;
    UINT_TO_BYTE_ARRAY(s_axis.data.tdata, 16, s_axis_tdata)
    UINT_TO_BIT_ARRAY(s_axis.data.tkeep, 16, s_axis_tkeep)
    s_axis.data.tlast = s_axis_tlast;
    s_axis.valid = s_axis_tvalid;

    // chacha20 -> prepare auth data -> poly1305

    // Connect input stream to chacha20_encrypt
    for(int32_t i=0; i<CHACHA20_KEY_NWORDS; i+=1){
        chacha20_encrypt_key[i] = key >> (i*32);
    }
    for(int32_t i=0; i<CHACHA20_NONCE_NWORDS; i+=1){
        chacha20_encrypt_nonce[i] = nonce >> (i*32);
    }
    chacha20_encrypt_counter = counter;
    chacha20_encrypt_axis_in = s_axis;
    s_axis_tready = chacha20_encrypt_axis_in_ready;

    // Connect chacha20_encrypt output to prep_auth_data input
    prep_auth_data_axis_in = chacha20_encrypt_axis_out;
    chacha20_encrypt_axis_out_ready = prep_auth_data_axis_in_ready;

    // Connect prep_auth_data output to poly1305_mac input
    for(int32_t i=0; i<32; i+=1){
        poly1305_mac_loop_fsm_data_key[i] = poly1305_key >> (i*8);
    }
    poly1305_mac_loop_fsm_data_in = prep_auth_data_axis_out;
    prep_auth_data_axis_out_ready = poly1305_mac_loop_fsm_data_in_ready;

    // Connect poly1305_mac output to output
    poly1305_auth_tag = uint8_array16_le(poly1305_mac_loop_fsm_auth_tag);
    poly1305_auth_tag_valid = poly1305_mac_loop_fsm_auth_tag_valid;
    stream(axis128_t) m_axis = poly1305_mac_loop_fsm_data_out;
    poly1305_mac_loop_fsm_data_out_ready = m_axis_tready;

    // Convert stream(axis128_t) to flattened output multiple wires
    m_axis_tdata = uint8_array16_le(m_axis.data.tdata);
    m_axis_tkeep = uint1_array16_le(m_axis.data.tkeep);
    m_axis_tlast = m_axis.data.tlast;
    m_axis_tvalid = m_axis.valid;
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