/*  // 3. Prepare the authenticated data for Poly1305
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
*/
#include "prep_auth_data.h"

// TODO add aad port when data type/size determined

stream(axis128_t) prep_auth_data_axis_in; // input
uint1_t prep_auth_data_axis_in_ready; // output
stream(axis128_t) prep_auth_data_axis_out; // output
uint1_t prep_auth_data_axis_out_ready; // input

#pragma MAIN prep_auth_data
void prep_auth_data()
{
  #warning "TODO prep auth data"
  // pass through for now
  prep_auth_data_axis_out = prep_auth_data_axis_in;
  prep_auth_data_axis_in_ready = prep_auth_data_axis_out_ready;
}