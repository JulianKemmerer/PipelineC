/**
 * based on code from
 * https://github.com/chili-chips-ba/wireguard-fpga/blob/main/2.sw/app/chacha20poly1305/
*/
#include "arrays.h"
// Top level IO port config, named like chacha20poly1305_encrypt_*
#include "chacha20poly1305_encrypt.h"
// Instance of chacha20 part of encryption
#include "chacha20/chacha20_encrypt.c"
// Instance of preparing auth data part of encryption
#include "prep_auth_data/prep_auth_data.c"
// Instance of poly1305 part of encryption
#include "poly1305/poly1305_mac.c"
// Instance of the appending auth tag part of encryption
#include "append_auth_tag/append_auth_tag.c"

// The primary dataflow for single clock domain ChaCha20-Poly1305 encryption
// plaintext -> chacha20 -> ciphertext ...
//  ...
// ciphertext -------------------------------------------------> append auth tag -> output axis
//             |-> prep auth data -> auth data -> poly1305 -> auth tag --^
#pragma PART "xc7a200tffg1156-2" // Artix 7 200T
#pragma MAIN_MHZ main 80.0
void main(){
    // Connect chacha20poly1305_encrypt_* input stream to chacha20_encrypt
    chacha20_encrypt_axis_in = chacha20poly1305_encrypt_axis_in;
    chacha20poly1305_encrypt_axis_in_ready = chacha20_encrypt_axis_in_ready;
    chacha20_encrypt_key = chacha20poly1305_encrypt_key;
    chacha20_encrypt_nonce = chacha20poly1305_encrypt_nonce;

    // Connect chacha20_encrypt output to both
    //  prep_auth_data input
    //  append auth tag input
    // Fork the stream by combining valids and readys
    //  default no data passing, invalidate passthrough
    prep_auth_data_axis_in = chacha20_encrypt_axis_out;
    prep_auth_data_axis_in.valid = 0;
    append_auth_tag_axis_in = chacha20_encrypt_axis_out;
    append_auth_tag_axis_in.valid = 0;
    //  allow pass through if both sinks are ready
    //  or if sink isnt ready (no data passing anyway)
    chacha20_encrypt_axis_out_ready = prep_auth_data_axis_in_ready & append_auth_tag_axis_in_ready;
    if(chacha20_encrypt_axis_out_ready | ~prep_auth_data_axis_in_ready){
        prep_auth_data_axis_in.valid = chacha20_encrypt_axis_out.valid;
    }
    if(chacha20_encrypt_axis_out_ready | ~append_auth_tag_axis_in_ready){
        append_auth_tag_axis_in.valid = chacha20_encrypt_axis_out.valid;
    }

    // Prep auth data CSR inputs
    prep_auth_data_aad = chacha20poly1305_encrypt_aad;
    prep_auth_data_aad_len = chacha20poly1305_encrypt_aad_len;

    // Connect prep_auth_data output to poly1305_mac input
    poly1305_mac_data_in = prep_auth_data_axis_out;
    prep_auth_data_axis_out_ready = poly1305_mac_data_in_ready;
    poly1305_mac_data_key = chacha20poly1305_encrypt_poly1305_key;

    // Connect poly1305_mac auth tag output to append auth tag input
    append_auth_tag_auth_tag_in = poly1305_mac_auth_tag;
    poly1305_mac_auth_tag_ready = append_auth_tag_auth_tag_in_ready;
    
    // Connect append auth tag output to chacha20poly1305_encrypt_* output
    chacha20poly1305_encrypt_axis_out = append_auth_tag_axis_out;
    append_auth_tag_axis_out_ready = chacha20poly1305_encrypt_axis_out_ready;
}


#ifdef SIMULATION
// Annoying fixed array sized single string printf funcs
// trying to match software print_hex
#define PRINT_32_BYTES(label, array) \
uint256_t PRINT_32_BYTES_uint = uint8_array32_be(array); \
printf(label \
    "%X%X%X%X%X%X%X%X\n", \
    PRINT_32_BYTES_uint >> (8*28), \
    PRINT_32_BYTES_uint >> (8*24), \
    PRINT_32_BYTES_uint >> (8*20), \
    PRINT_32_BYTES_uint >> (8*16), \
    PRINT_32_BYTES_uint >> (8*12), \
    PRINT_32_BYTES_uint >> (8*8), \
    PRINT_32_BYTES_uint >> (8*4), \
    PRINT_32_BYTES_uint >> (8*0) \
);

#define PRINT_16_BYTES(label, array) \
uint128_t PRINT_16_BYTES_uint = uint8_array16_be(array); \
printf(label \
    "%X%X%X%X\n", \
    PRINT_16_BYTES_uint >> (8*12), \
    PRINT_16_BYTES_uint >> (8*8), \
    PRINT_16_BYTES_uint >> (8*4), \
    PRINT_16_BYTES_uint >> (8*0) \
);

#define PRINT_12_BYTES(label, array) \
uint96_t PRINT_12_BYTES_uint = uint8_array12_be(array); \
printf(label \
    "%X%X%X\n", \
    PRINT_12_BYTES_uint >> (8*8), \
    PRINT_12_BYTES_uint >> (8*4), \
    PRINT_12_BYTES_uint >> (8*0) \
);

/*void print_hex_key(uint8_t key[CHACHA20_KEY_SIZE])
{
    // 32 2-char wide hex bytes
    printf(
        "Key: "
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "\n",
        key[0], key[1], key[2], key[3],
        key[4], key[5], key[6], key[7],
        key[8], key[9], key[10], key[11],
        key[12], key[13], key[14], key[15],
        key[16], key[17], key[18], key[19],
        key[20], key[21], key[22], key[23],
        key[24], key[25], key[26], key[27],
        key[28], key[29], key[30], key[31]
    );
}

void print_hex_nonce(uint8_t nonce[CHACHA20_NONCE_SIZE])
{
    // 12 2-char wide hex bytes
    printf(
        "Nonce: "
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "%02x%02x%02x%02x"
        "\n",
        nonce[0], nonce[1], nonce[2], nonce[3],
        nonce[4], nonce[5], nonce[6], nonce[7],
        nonce[8], nonce[9], nonce[10], nonce[11]
    );
}*/

void print_aad(uint8_t aad[AAD_MAX_LEN], uint32_t aad_len)
{
    // 32 chars
    printf("AAD (%u bytes): "
        "%c%c%c%c"
        "%c%c%c%c"
        "%c%c%c%c"
        "%c%c%c%c"
        "%c%c%c%c"
        "%c%c%c%c"
        "%c%c%c%c"
        "%c%c%c%c"        
        "\n",
        aad_len, 
        aad[0], aad[1], aad[2], aad[3],
        aad[4], aad[5], aad[6], aad[7],
        aad[8], aad[9], aad[10], aad[11],
        aad[12], aad[13], aad[14], aad[15],
        aad[16], aad[17], aad[18], aad[19],
        aad[20], aad[21], aad[22], aad[23],
        aad[24], aad[25], aad[26], aad[27],
        aad[28], aad[29], aad[30], aad[31]
    );
}

#pragma MAIN tb
void tb()
{
    // Test vectors
    //   CSR values available all at once do not need to be static=registers
    //   Streaming inputs data is done as shift register
    uint8_t key[CHACHA20_KEY_SIZE] = {
        0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
        0x88, 0x89, 0x8a, 0x8b, 0x8c, 0x8d, 0x8e, 0x8f,
        0x90, 0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97,
        0x98, 0x99, 0x9a, 0x9b, 0x9c, 0x9d, 0x9e, 0x9f};

    uint8_t nonce[CHACHA20_NONCE_SIZE] = {
        0x07, 0x00, 0x00, 0x00, 0x40, 0x41, 0x42, 0x43,
        0x44, 0x45, 0x46, 0x47};

    #define AAD_TEST_STR "Additional authenticated data"
    uint8_t aad[AAD_MAX_LEN] = AAD_TEST_STR;
    uint32_t aad_len = strlen(AAD_TEST_STR);
    
    // poly1305_key obtained by running test main.c software C code
    uint8_t poly1305_key[POLY1305_KEY_SIZE] = {
        0x7b, 0xac, 0x2b, 0x25, 0x2d, 0xb4, 0x47, 0xaf,
        0x09, 0xb6, 0x7a, 0x55, 0xa4, 0xe9, 0x55, 0x84,
        0x0a, 0xe1, 0xd6, 0x73, 0x10, 0x75, 0xd9, 0xeb,
        0x2a, 0x93, 0x75, 0x78, 0x3e, 0xd5, 0x53, 0xff
    };

    #define PLAINTEXT_TEST_STR "Hello CHILIChips - Wireguard team, let's test this aead!"
    #define PLAINTEXT_TEST_STR_LEN strlen(PLAINTEXT_TEST_STR)
    static char plaintext[PLAINTEXT_TEST_STR_LEN] = PLAINTEXT_TEST_STR;
    static uint32_t plaintext_remaining = PLAINTEXT_TEST_STR_LEN;

    static uint32_t cycle_counter; 
    //printf("Cycle %u:\n", cycle_counter);
    if(cycle_counter == 0)
    {
        printf("=== ChaCha20-Poly1305 AEAD Test ===\n");
        // Print test inputs
        PRINT_32_BYTES("Key: ", key)
        PRINT_12_BYTES("Nonce: ", nonce)
        print_aad(aad, aad_len);
        PRINT_32_BYTES("Poly1305 key: ", poly1305_key)
        printf("Encrypting...\n");
    }

    // Encrypt:

    // Stream plaintext into dut
    chacha20poly1305_encrypt_axis_in.valid = 0;
    // Have valid data if there is more plaintext to send
    if(plaintext_remaining > 0)
    {
        // Up to 16 bytes of plaintext onto axis128
        // padded with zeros if needed
        for(int32_t i=0; i<16; i+=1)
        {
            chacha20poly1305_encrypt_axis_in.data.tkeep[i] = 1;
            chacha20poly1305_encrypt_axis_in.data.tdata[i] = 0;
            if(plaintext_remaining > i)
            {
                chacha20poly1305_encrypt_axis_in.data.tdata[i] = plaintext[i];
            }
        }
        chacha20poly1305_encrypt_axis_in.data.tlast = (plaintext_remaining <= 16);
        chacha20poly1305_encrypt_axis_in.valid = 1;
        if(chacha20poly1305_encrypt_axis_in.valid & chacha20poly1305_encrypt_axis_in_ready)
        {
            PRINT_16_BYTES("Plaintext next 16 bytes: ", chacha20poly1305_encrypt_axis_in.data.tdata)
            if(chacha20poly1305_encrypt_axis_in.data.tlast){
                plaintext_remaining = 0;
            }else{
                plaintext_remaining -= 16;
            }
            ARRAY_SHIFT_DOWN(plaintext, PLAINTEXT_TEST_STR_LEN, 16)
        }
    }
    // Connect other inputs to dut
    chacha20poly1305_encrypt_key = key;
    chacha20poly1305_encrypt_nonce = nonce;
    chacha20poly1305_encrypt_aad = aad;
    chacha20poly1305_encrypt_aad_len = aad_len;
    chacha20poly1305_encrypt_poly1305_key = poly1305_key;

    // Expected ciphertext and auth tag output from running main.c demo
    // Ciphertext: 
    //  d71e85316edd03f2
    //  5caec6b85ee87add
    //  e1eda86860730bb9
    //  a8eba2e375f666c4
    //  23b2eb54c9fa7958
    //  98aed77c8efb2680
    //  1c77920fdb08096e
    #define CIPHERTEXT_SIZE ((7*8) + POLY1305_AUTH_TAG_SIZE)
    static uint32_t ciphertext_remaining = CIPHERTEXT_SIZE;
    static uint8_t expected_ciphertext[CIPHERTEXT_SIZE] = {
        0xd7, 0x1e, 0x85, 0x31, 0x6e, 0xdd, 0x03, 0xf2, 
        0x5c, 0xae, 0xc6, 0xb8, 0x5e, 0xe8, 0x7a, 0xdd,
        0xe1, 0xed, 0xa8, 0x68, 0x60, 0x73, 0x0b, 0xb9,
        0xa8, 0xeb, 0xa2, 0xe3, 0x75, 0xf6, 0x66, 0xc4,
        0x23, 0xb2, 0xeb, 0x54, 0xc9, 0xfa, 0x79, 0x58,
        0x98, 0xae, 0xd7, 0x7c, 0x8e, 0xfb, 0x26, 0x80,
        0x1c, 0x77, 0x92, 0x0f, 0xdb, 0x08, 0x09, 0x6e,
        // Auth Tag: 
        //  5da87d6a2d15036c
        //  a7cb91a8ec3dba7c
        0x5d, 0xa8, 0x7d, 0x6a, 0x2d, 0x15, 0x03, 0x6c,
        0xa7, 0xcb, 0x91, 0xa8, 0xec, 0x3d, 0xba, 0x7c
    };

    // Stream ciphertext out of dut
    chacha20poly1305_encrypt_axis_out_ready = 1;
    if(chacha20poly1305_encrypt_axis_out.valid & chacha20poly1305_encrypt_axis_out_ready)
    {
        // Print ciphertext as it flows out of dut
        PRINT_16_BYTES("Ciphertext next 16 bytes: ", chacha20poly1305_encrypt_axis_out.data.tdata)
        // compare to expected_ciphertext and shift
        for(int32_t i = 0; i<16; i+=1)
        {
            if(ciphertext_remaining > i)
            {
                if(chacha20poly1305_encrypt_axis_out.data.tdata[i] != expected_ciphertext[i])
                {
                    uint32_t ciphertext_pos = (CIPHERTEXT_SIZE-ciphertext_remaining) + i;
                    printf("ERROR: Ciphertext mismatch at byte[%d]. expected 0x%X got 0x%X\n", 
                           ciphertext_pos, expected_ciphertext[i], chacha20poly1305_encrypt_axis_out.data.tdata[i]);
                }
            }
        }
        // Too much data?
        if(ciphertext_remaining == 0){
            printf("ERROR: Extra ciphertext output!\n");
        }
        // Too little data? Or more to come?
        if(chacha20poly1305_encrypt_axis_out.data.tlast){
            if(ciphertext_remaining > 16){
                printf("ERROR: Early end to ciphertext output!\n");
            }else{
                printf("Test DONE\n");
            }
            ciphertext_remaining = 0;
        }else{
            ciphertext_remaining -= 16;
        }
        ARRAY_SHIFT_DOWN(expected_ciphertext, CIPHERTEXT_SIZE, 16)
    }

    cycle_counter += 1;
}
#endif