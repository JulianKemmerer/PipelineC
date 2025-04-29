/**
 * based on code from
 * https://github.com/chili-chips-ba/wireguard-fpga/blob/main/2.sw/app/chacha20poly1305/
*/
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


// TODO Try to copy software test code demo inputs and outputs
#ifdef SIMULATION
int main(void)
{
    // Test vectors
    uint8_t key[32] = {
        0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
        0x88, 0x89, 0x8a, 0x8b, 0x8c, 0x8d, 0x8e, 0x8f,
        0x90, 0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97,
        0x98, 0x99, 0x9a, 0x9b, 0x9c, 0x9d, 0x9e, 0x9f};

    uint8_t nonce[12] = {
        0x07, 0x00, 0x00, 0x00, 0x40, 0x41, 0x42, 0x43,
        0x44, 0x45, 0x46, 0x47};

    const char *aad_str = "Additional authenticated data";
    uint8_t *aad = (uint8_t *)aad_str;
    size_t aad_len = strlen(aad_str);

    const char *plaintext_str = "Hello CHILIChips - Wireguard team, let's test this aead!";
    uint8_t *plaintext = (uint8_t *)plaintext_str;
    size_t plaintext_len = strlen(plaintext_str);

    // Use stack allocation instead of malloc
    uint8_t ciphertext[256]; // Buffer large enough for the plaintext
    uint8_t decrypted[256];  // Buffer large enough for the plaintext
    uint8_t auth_tag[16];

    printf("=== ChaCha20-Poly1305 AEAD Test ===\n\n");

    // Print test inputs
    print_hex("Key", key, sizeof(key));
    print_hex("Nonce", nonce, sizeof(nonce));
    printf("AAD (%zu bytes): \"%s\"\n", aad_len, aad_str);
    printf("Plaintext (%zu bytes): \"%s\"\n\n", plaintext_len, plaintext_str);

    // Encrypt
    printf("Encrypting...\n");
    int ret = chacha20poly1305_encrypt(
        ciphertext, auth_tag, key, nonce,
        plaintext, plaintext_len, aad, aad_len);

    if (ret != 0)
    {
        printf("Encryption failed with error %d\n", ret);
        return -1;
    }

    print_hex("Ciphertext", ciphertext, plaintext_len);
    print_hex("Auth Tag", auth_tag, sizeof(auth_tag));
    printf("\n");

    // Decrypt
    printf("Decrypting...\n");
    ret = chacha20poly1305_decrypt(
        decrypted, key, nonce, ciphertext, plaintext_len,
        auth_tag, aad, aad_len);

    if (ret != 0)
    {
        printf("Decryption failed with error %d\n", ret);
        return -1;
    }

    // Verify
    decrypted[plaintext_len] = '\0'; // Null-terminate for printing
    printf("Decrypted (%zu bytes): \"%s\"\n\n", plaintext_len, decrypted);

    int success = (memcmp(plaintext, decrypted, plaintext_len) == 0);
    printf("Test %s\n", success ? "PASSED" : "FAILED");
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
#endif