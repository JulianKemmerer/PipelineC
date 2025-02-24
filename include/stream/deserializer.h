#pragma once
#include "arrays.h"

#define deserializer_counter_t uint16_t

// OUTSIZE must be ?= or divisible by INSIZE ??
#define deserializer_in_to_out(name, data_t, IN_SIZE, OUT_SIZE) \
typedef struct name##_t \
{ \
  data_t out_data[OUT_SIZE]; \
  uint1_t out_data_valid; \
  uint1_t in_data_ready; \
}name##_t; \
name##_t name(data_t in_data[IN_SIZE], uint1_t in_data_valid, uint1_t out_data_ready) \
{ \
  static data_t out_buffer[OUT_SIZE]; \
  static uint1_t out_buffer_valid; \
  static deserializer_counter_t out_counter;\
  name##_t rv; \
  /* Read if buffer empty*/  \
  rv.in_data_ready = !out_buffer_valid; \
  /* Output registers*/ \
  rv.out_data = out_buffer; \
  rv.out_data_valid = out_buffer_valid; \
  /* Read from buffer and clear(invalidate) if ready*/ \
  if(out_data_ready & out_buffer_valid) \
  { \
    out_buffer_valid = 0; \
    out_counter = 0; \
  } \
  \
  /* Only shift input data into the output buffer if its not full(valid)*/ \
  /* Buffer N elements in a shifting buffer*/ \
  if(rv.in_data_ready & in_data_valid) \
  { \
    /* Shift buffer down to make room for last incoming element in upper indices*/ \
    ARRAY_SHIFT_INTO_TOP(out_buffer, OUT_SIZE, in_data, IN_SIZE)\
    out_counter += IN_SIZE; \
    \
    /* If the out buffer now has all data then valid/full*/ \
    if(out_counter==OUT_SIZE) \
    { \
      out_buffer_valid = 1; \
    } \
  } \
  \
  return rv; \
}

// Sizeof(out_t) needs be ?= or divislbe by in bytes? 
#define type_byte_deserializer(name,IN_BYTES,out_t)\
/* Need to deser to byte array*/ \
deserializer_in_to_out(name##_deserializer_in_to_out, uint8_t, IN_BYTES, sizeof(out_t)) \
typedef struct name##_t \
{ \
  out_t data; \
  uint1_t valid; \
  uint1_t in_data_ready; \
}name##_t; \
name##_t name(uint8_t in_data[IN_BYTES], uint1_t in_data_valid, uint1_t out_data_ready) \
{ \
  /* Deserialize to byte array*/ \
  name##_t o; \
  name##_deserializer_in_to_out_t to_type_bytes = name##_deserializer_in_to_out(in_data, in_data_valid, out_data_ready); \
  /* Byte array to type */ \
  out_t##_bytes_t output_bytes; \
  output_bytes.data = to_type_bytes.out_data; \
  o.data = bytes_to_##out_t(output_bytes); \
  o.valid = to_type_bytes.out_data_valid;\
  o.in_data_ready = to_type_bytes.in_data_ready; \
  return o; \
}


// TODO replace with in to out version? always use array args?
#define deserializer(name, data_t, OUT_SIZE) \
data_t name##_out_buffer[OUT_SIZE]; \
uint1_t name##_out_buffer_valid; \
uint32_t name##_out_counter; /*TODO: reduce bits?*/ \
typedef struct name##_o_t \
{ \
  data_t out_data[OUT_SIZE]; \
  uint1_t out_data_valid; \
  uint1_t in_data_ready; \
}name##_o_t; \
name##_o_t name(data_t in_data, uint1_t in_data_valid, uint1_t out_data_ready) \
{ \
  name##_o_t rv; \
  /* Read if buffer empty*/  \
  rv.in_data_ready = !name##_out_buffer_valid; \
  /* Output registers*/ \
  rv.out_data = name##_out_buffer; \
  rv.out_data_valid = name##_out_buffer_valid; \
  /* Read from buffer and clear(invalidate) if ready*/ \
  if(out_data_ready & name##_out_buffer_valid) \
  { \
    name##_out_buffer_valid = 0; \
    name##_out_counter = 0; \
  } \
  \
  /* Only shift input data into the output buffer if its not full(valid)*/ \
  /* Buffer N elements in a shifting buffer*/ \
  if(rv.in_data_ready & in_data_valid) \
  { \
    /* Shift buffer to make room for incoming element*/ \
    uint32_t i; \
    for(i=0;i<(OUT_SIZE-1);i=i+1) \
    { \
      name##_out_buffer[i] = name##_out_buffer[i+1]; \
    } \
    \
    /* Incoming data into back of buffer*/ \
    name##_out_buffer[OUT_SIZE-1] = in_data; \
    name##_out_counter += 1; \
    \
    /* If the out buffer now has all data then valid/full*/ \
    if(name##_out_counter==OUT_SIZE) \
    { \
      name##_out_buffer_valid = 1; \
    } \
  } \
  \
  return rv; \
}
