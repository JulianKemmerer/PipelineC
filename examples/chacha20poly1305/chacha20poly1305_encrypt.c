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

// The primary dataflow for single clock domain ChaCha20-Poly1305 encryption
// chacha20 -> prepare auth data -> poly1305
#pragma PART "xc7a200tffg1156-2" // Artix 7 200T
#pragma MAIN_MHZ main 80.0
void main(){
    // Connect chacha20poly1305_encrypt_* input stream to chacha20_encrypt
    chacha20_encrypt_axis_in = chacha20poly1305_encrypt_axis_in;
    chacha20poly1305_encrypt_axis_in_ready = chacha20_encrypt_axis_in_ready;
    chacha20_encrypt_key = chacha20poly1305_encrypt_key;
    chacha20_encrypt_nonce = chacha20poly1305_encrypt_nonce;

    // Connect chacha20_encrypt output to prep_auth_data input
    prep_auth_data_axis_in = chacha20_encrypt_axis_out;
    chacha20_encrypt_axis_out_ready = prep_auth_data_axis_in_ready;
    prep_auth_data_aad = chacha20poly1305_encrypt_aad;
    prep_auth_data_aad_len = chacha20poly1305_encrypt_aad_len;

    // Connect prep_auth_data output to poly1305_mac input
    poly1305_mac_data_in = prep_auth_data_axis_out;
    prep_auth_data_axis_out_ready = poly1305_mac_data_in_ready;
    poly1305_mac_data_key = chacha20poly1305_encrypt_poly1305_key;

    // Connect poly1305_mac output to chacha20poly1305_encrypt_* output
    chacha20poly1305_encrypt_axis_out = poly1305_mac_data_out;
    poly1305_mac_data_out_ready = chacha20poly1305_encrypt_axis_out_ready;
    chacha20poly1305_encrypt_auth_tag = poly1305_mac_auth_tag;
    chacha20poly1305_encrypt_auth_tag_valid = poly1305_mac_auth_tag_valid;
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
    
    // poly1305_key obtained by running test main software C code
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
        ARRAY_COPY(chacha20poly1305_encrypt_axis_in.data.tdata, plaintext, 16)
        for(int32_t i=0; i<16; i+=1)
        {
            chacha20poly1305_encrypt_axis_in.data.tkeep[i] = 0;
            if(plaintext_remaining > i)
            {
                chacha20poly1305_encrypt_axis_in.data.tkeep[i] = 1;
            }
        }
        chacha20poly1305_encrypt_axis_in.data.tlast = (plaintext_remaining <= 16);
        chacha20poly1305_encrypt_axis_in.valid = 1;
        if(chacha20poly1305_encrypt_axis_in.valid & chacha20poly1305_encrypt_axis_in_ready)
        {
            PRINT_16_BYTES("Plaintext next 16 bytes: ", chacha20poly1305_encrypt_axis_in.data.tdata)
            plaintext_remaining -= 16;
            ARRAY_SHIFT_DOWN(plaintext, PLAINTEXT_TEST_STR_LEN, 16)
        }
    }
    // Connect other inputs to dut
    chacha20poly1305_encrypt_key = key;
    chacha20poly1305_encrypt_nonce = nonce;
    chacha20poly1305_encrypt_aad = aad;
    chacha20poly1305_encrypt_aad_len = aad_len;
    chacha20poly1305_encrypt_poly1305_key = poly1305_key;

    // Stream ciphertext out of dut
    chacha20poly1305_encrypt_axis_out_ready = 1;
    if(chacha20poly1305_encrypt_axis_out.valid & chacha20poly1305_encrypt_axis_out_ready)
    {
        // Print ciphertext as it flows out of dut
        PRINT_16_BYTES("Ciphertext next 16 bytes: ", chacha20poly1305_encrypt_axis_out.data.tdata)
        // Print auth tag as it flows out of dut
        if(chacha20poly1305_encrypt_auth_tag_valid)
        {
            PRINT_16_BYTES("Auth tag: ", chacha20poly1305_encrypt_auth_tag)
        }
    }

    cycle_counter += 1;
}
#endif