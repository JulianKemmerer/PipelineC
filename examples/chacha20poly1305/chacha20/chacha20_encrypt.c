// Instance of chacha20_encrypt_loop_body
// requires data width converters to-from 512b wide blocks 128b bus
// use axis128/512 stream types
#include "axi/axis.h"
#include "global_func_inst.h"
#include "chacha20.h"

// Globally visible ports
uint32_t chacha20_encrypt_key[CHACHA20_KEY_NWORDS]; // input
uint32_t chacha20_encrypt_nonce[CHACHA20_NONCE_NWORDS]; // input
uint32_t chacha20_encrypt_counter; // input
stream(axis128_t) chacha20_encrypt_axis_in; // input
uint1_t chacha20_encrypt_axis_in_ready; // output
stream(axis128_t) chacha20_encrypt_axis_out; // output
uint1_t chacha20_encrypt_axis_out_ready; // input

// Global instance of the chacha20_encrypt_loop_body pipeline
GLOBAL_VALID_READY_PIPELINE_INST(chacha20_encrypt_pipeline, axis512_t, chacha20_encrypt_loop_body, chacha20_encrypt_loop_body_in_t, 64)

// Main data flow for ChaCha20 encryption
#pragma MAIN chacha20_encrypt
void chacha20_encrypt()
{
  // Convert input axis to 512b
  uint1_t block_in_ready;
  #pragma FEEDBACK block_in_ready
  axis128_to_axis512_t in_to_block = axis128_to_axis512(chacha20_encrypt_axis_in, block_in_ready);
  stream(axis512_t) block_in_stream = in_to_block.axis_out;
  chacha20_encrypt_axis_in_ready = in_to_block.axis_in_ready;

  // Connect input 512b block into pipeline
  chacha20_encrypt_pipeline_in.data.key = chacha20_encrypt_key;
  chacha20_encrypt_pipeline_in.data.nonce = chacha20_encrypt_nonce;
  chacha20_encrypt_pipeline_in.data.counter = chacha20_encrypt_counter;
  chacha20_encrypt_pipeline_in.data.axis_in = block_in_stream.data;
  chacha20_encrypt_pipeline_in.valid = block_in_stream.valid;
  block_in_ready = chacha20_encrypt_pipeline_in_ready; // FEEDBACK

  // Convert pipeline output 512b block stream to 128b
  axis512_to_axis128_t block_to_out = axis512_to_axis128(chacha20_encrypt_pipeline_out, chacha20_encrypt_axis_out_ready);
  chacha20_encrypt_axis_out = block_to_out.axis_out;
  chacha20_encrypt_pipeline_out_ready = block_to_out.axis_in_ready;
}


/* Test synthesis for chacha20_encrypt
#include "arrays.h"
DECL_INPUT(uint1024_t, key_in)
DECL_INPUT(uint384_t, nonce_in)
DECL_INPUT(uint32_t, counter_in)
DECL_INPUT(stream(axis128_t), data_in)
DECL_OUTPUT(uint1_t, data_in_ready)
DECL_OUTPUT(stream(axis128_t), data_out)
DECL_OUTPUT(uint1_t, data_out_ready)
#pragma PART "xc7a200tffg1156-2" // Artix 7 200T
#pragma MAIN_MHZ chacha20_encrypt_connect 80.0
void chacha20_encrypt_connect(){
  TODO
}*/