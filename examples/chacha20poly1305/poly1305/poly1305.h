// Based on https://github.com/chili-chips-ba/wireguard-fpga/blob/main/2.sw/app/chacha20poly1305/poly1305.c

#define BLOCK_SIZE 16

/**
 * @brief 130-bit prime: 2^130 - 5
 */
uint64_t PRIME[3] = {0xFFFFFFFFFFFFFFFB, 0xFFFFFFFFFFFFFFFF, 0x3};

/**
 * @brief Structure to hold a 320-bit unsigned integer for Poly1305 calculations
 */
typedef struct u320_t
{
    uint64_t limbs[5]; // 64-bit limbs
} u320_t;


/**
 * @brief Apply clamping to the 'r' part of the key
 *
 * @param r 16-byte array to clamp
 */
typedef struct u8_16_t{
  uint8_t bytes[16];
} u8_16_t;
// TODO can optimize bit manip
u8_16_t clamp(u8_16_t r)
{
    r.bytes[3] &= 15;
    r.bytes[7] &= 15;
    r.bytes[11] &= 15;
    r.bytes[15] &= 15;
    r.bytes[4] &= 252;
    r.bytes[8] &= 252;
    r.bytes[12] &= 252;
    return r;
}

/**
 * @brief Copy bytes to a u320_t
 *
 * @param dst Destination u320_t
 * @param src Source byte array
 * @param len Number of bytes to copy (max 40)
 */
#include "type_bytes_t.h/u320_t_bytes_t.h/u320_t_bytes_t.h" // for bytes_to_u320_t
u320_t bytes_to_uint320(uint8_t src[sizeof(u320_t)])
{
    return bytes_to_u320_t(src); // pipelinec built in
}

/**
 * @brief Add two u320_t values
 *
 * @param res Result: a + b
 * @param a First operand
 * @param b Second operand
 */
u320_t uint320_add(u320_t a, u320_t b)
{
    // PipelineC built in uint320_t + uint320_t seems better
    uint320_t a_uint = uint64_array5_le(a.limbs);
    uint320_t b_uint = uint64_array5_le(b.limbs);
    uint320_t rv_uint = a_uint + b_uint; 
    u320_t rv;
    for(int32_t i = 0; i < 5; i+=1){
        rv.limbs[i] = rv_uint >> (i*64);
    }
    return rv;/*
    u320_t res = {0};
    uint64_t carry = 0;
    for (int32_t i = 0; i < 5; i+=1)
    {
        uint64_t sum = a.limbs[i] + b.limbs[i] + carry;
        carry = (sum < a.limbs[i]) || (sum == a.limbs[i] && carry);
        res.limbs[i] = sum;
    }
    return res;*/
}

/**
 * @brief Multiply two u320_t values
 *
 * @param res Result: a * b
 * @param a First operand
 * @param b Second operand
 */
u320_t uint320_mul(u320_t a, u320_t b)
{
    u320_t temp = {0};

    // Schoolbook multiplication algorithm
    for (int32_t i = 0; i < 5; i+=1)
    {
        uint64_t carry = 0;
        for (int32_t j = 0; j < 5 - i; j+=1)
        {
            uint64_t high;
            uint64_t low;
            uint64_t product = a.limbs[i] * b.limbs[j];
            uint64_t old_value = temp.limbs[i + j];

            // Add previous value and carry
            low = product + old_value;
            high = (low < product) ? 1 : 0;
            low += carry;
            high += (low < carry) ? 1 : 0;

            temp.limbs[i + j] = low;
            carry = high;
        }
    }

    u320_t res = temp;
    return res;
    /* // Could be implemented as uint320_t * uint320_t 
    // but doesnt actually seem to produce better hardware? 
    uint320_t a_uint = uint64_array5_le(a.limbs);
    uint320_t b_uint = uint64_array5_le(b.limbs);
    uint320_t rv_uint = a_uint * b_uint;
    u320_t rv;
    for(int32_t i = 0; i < 5; i+=1){
        rv.limbs[i] = rv_uint >> (i*64);
    }
    return rv;*/
}

/**
 * @brief Reduce a u320_t modulo 2^130 - 5
 *
 * @param a Value to reduce
 */
u320_t uint320_mod_prime(u320_t a)
{
    // First, handle the high bits (greater than or equal to 2^130)
    uint64_t mask = 0x3FFFFFFFFFF; // 2^130 - 1
    uint64_t high_bits = a.limbs[2] & ~mask;
    if (high_bits || a.limbs[3] || a.limbs[4])
    {
        // We have bits above 2^130, need to reduce

        // Clear high bits
        a.limbs[2] &= mask;
        a.limbs[3] = 0;
        a.limbs[4] = 0;

        // Multiply high bits by 5 and add to low bits
        u320_t mul5 = {0};

        // high_bits * 5
        mul5.limbs[0] = (high_bits >> 2) * 5;

        // Add to original value
        a = uint320_add(a, mul5);
    }

    // Check if result is still >= 2^130 - 5
    if ((a.limbs[2] & mask) == mask &&
        a.limbs[1] == 0xFFFFFFFFFFFFFFFF &&
        a.limbs[0] >= 0xFFFFFFFFFFFFFFFB)
    {

        // Subtract 2^130 - 5
        uint64_t borrow = 0;
        uint64_t diff;

        diff = a.limbs[0] - 0xFFFFFFFFFFFFFFFB;
        borrow = (diff > a.limbs[0]) ? 1 : 0;
        a.limbs[0] = diff;

        diff = a.limbs[1] - 0xFFFFFFFFFFFFFFFF - borrow;
        borrow = (diff > a.limbs[1]) || (diff == a.limbs[1] && borrow);
        a.limbs[1] = diff;

        a.limbs[2] -= borrow;
        a.limbs[2] &= mask; // Ensure top bits are zero
    }
    return a;
}

/**
 * @brief Compute Poly1305 MAC for a message
 *
 * @param auth_tag Output buffer for the 16-byte authentication tag
 * @param key 32-byte key (r || s)
 * @param message Input message buffer
 * @param message_length Length of the message in bytes
 */
/*
void poly1305_mac(uint8_t *auth_tag, const uint8_t *key, const uint8_t *message, size_t message_length)
{
    uint8_t r_bytes[16]; // r part of the key
    uint8_t s_bytes[16]; // s part of the key

    // Split key into r and s components
    memcpy(r_bytes, key, 16);
    memcpy(s_bytes, key + 16, 16);

    // Clamp r according to the spec
    clamp(r_bytes);

    // Convert r and s to u320_t
    u320_t r, s, a;
    memset(&a, 0, sizeof(a)); // Initialize accumulator to 0
    bytes_to_uint320(&r, r_bytes, 16);
    bytes_to_uint320(&s, s_bytes, 16);

    // Process message in 16-byte blocks
    size_t blocks = message_length / BLOCK_SIZE;
    size_t remain = message_length % BLOCK_SIZE;

    // Process full blocks
    for (size_t i = 0; i < blocks; i++)
    {
        u320_t n;
        bytes_to_uint320(&n, message + (i * BLOCK_SIZE), BLOCK_SIZE);

        // Set the high bit (2^128)
        n.limbs[2] |= 0x1;

        // a += n
        uint320_add(&a, &a, &n);

        // a *= r
        u320_t temp = a;
        uint320_mul(&a, &temp, &r);

        // a %= p
        uint320_mod_prime(&a);
    }

    // Process remaining bytes
    if (remain > 0)
    {
        uint8_t last_block[BLOCK_SIZE] = {0};
        memcpy(last_block, message + (blocks * BLOCK_SIZE), remain);

        // Add the padding byte
        last_block[remain] = 0x01;

        u320_t n;
        bytes_to_uint320(&n, last_block, BLOCK_SIZE);

        // a += n
        uint320_add(&a, &a, &n);

        // a *= r
        u320_t temp = a;
        uint320_mul(&a, &temp, &r);

        // a %= p
        uint320_mod_prime(&a);
    }

    // a += s
    uint320_add(&a, &a, &s);

    // Copy the first 16 bytes to output
    memcpy(auth_tag, &a, 16);
}
*/
/*
Pass by value version of body part of per-block loop:
    want in form: output_t func_name(input_t)
*/
typedef struct poly1305_mac_loop_body_in_t{
    uint8_t block_bytes[BLOCK_SIZE];
    u320_t r;
    u320_t a;
} poly1305_mac_loop_body_in_t;
u320_t poly1305_mac_loop_body(
    poly1305_mac_loop_body_in_t inputs
){  
    uint8_t block_bytes[BLOCK_SIZE] = inputs.block_bytes;
    u320_t r = inputs.r;
    u320_t a = inputs.a;

    uint8_t n_bytes[sizeof(u320_t)] = {0};
    for(uint32_t i = 0; i < BLOCK_SIZE; i+=1){
        n_bytes[i] = block_bytes[i];
    }
    u320_t n = bytes_to_uint320(n_bytes);

    // Set the high bit (2^128)
    n.limbs[2] |= 0x1;

    // a += n
    a = uint320_add(a, n);

    // a *= r
    u320_t temp = a;
    a = uint320_mul(temp, r);

    // a %= p
    a = uint320_mod_prime(a);

    return a;
}

/**
 * @brief Verify if two Poly1305 tags match
 *
 * @param tag1 First tag to compare
 * @param tag2 Second tag to compare
 * @return 1 if tags match, 0 otherwise
 */
#define TAG_SIZE 16
int32_t poly1305_verify(uint8_t tag1[TAG_SIZE], uint8_t tag2[TAG_SIZE])
{
    return tag1==tag2; // pipelinec built in
}