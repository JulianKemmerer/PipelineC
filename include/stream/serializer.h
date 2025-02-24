#pragma once
#include "arrays.h"

#define serializer_counter_t uint16_t

// INSIZE must be divisible by OUTSIZE
#define serializer_in_to_out(name, data_t, IN_SIZE, OUT_SIZE) \
typedef struct name##_t \
{ \
  data_t out_data[OUT_SIZE]; \
  uint1_t out_last; \
  uint1_t out_data_valid; \
  uint1_t in_data_ready; \
}name##_t; \
name##_t name(data_t in_data[IN_SIZE], uint1_t in_data_valid, uint1_t out_data_ready) \
{ \
  static data_t in_buffer[IN_SIZE]; \
  static uint1_t in_buffer_valid; \
  static serializer_counter_t out_counter;\
  name##_t rv; \
  uint32_t i; \
  /* Default outputs from front/bottom of shift buffer */ \
  for(i=0;i<OUT_SIZE;i+=1) \
  { \
    rv.out_data[i] = in_buffer[i]; \
  } \
  rv.out_data_valid = in_buffer_valid; \
  /* Is last elements outgoing now? */ \
  rv.out_last = (out_counter==(IN_SIZE-OUT_SIZE));\
  uint1_t last_outgoing = out_data_ready & rv.out_last; \
  /* Read if buffer empty or being emptied*/ \
  rv.in_data_ready = !in_buffer_valid | last_outgoing; \
  \
  /* Only shift buffer if output ready */ \
  if(out_data_ready) \
  { \
    /* Shift buffer down to bring next elems to front */ \
    ARRAY_SHIFT_DOWN(in_buffer,IN_SIZE,OUT_SIZE) \
    out_counter += OUT_SIZE; \
    \
    /* If output all the elems then clear buffer */ \
    if(out_counter==IN_SIZE) \
    { \
      in_buffer_valid = 0; \
    } \
  } \
  \
  /* Input registers */ \
  if(rv.in_data_ready) \
  { \
    in_buffer = in_data; \
    in_buffer_valid = in_data_valid; \
    out_counter = 0; \
  } \
  \
  return rv; \
}


#define type_byte_serializer(name, in_t, OUT_BYTES) \
/* Need to ser from byte array*/ \
serializer_in_to_out(name##_serializer_in_to_out, uint8_t, sizeof(in_t), OUT_BYTES) \
typedef struct name##_t \
{ \
  uint8_t out_data[OUT_BYTES]; \
  uint1_t valid; \
  uint1_t last; \
  uint1_t in_data_ready; \
} name##_t; \
name##_t name(in_t in_data, uint1_t in_data_valid, uint1_t out_data_ready) \
{ \
  /* Convert type to byte array */ \
  in_t##_bytes_t input_bytes = in_t##_to_bytes(in_data); \
  /* Serialize byte array */ \
  name##_t o; \
  name##_serializer_in_to_out_t to_bytes = name##_serializer_in_to_out(input_bytes.data, in_data_valid, out_data_ready); \
  o.out_data = to_bytes.out_data; \
  o.valid = to_bytes.out_data_valid; \
  o.last = to_bytes.out_last; \
  o.in_data_ready = to_bytes.in_data_ready; \
  return o; \
}


#define serializer(name, data_t, IN_SIZE) \
serializer_in_to_out(name##_serializer_in_to_out, data_t, IN_SIZE, 1) \
typedef struct name##_o_t \
{ \
  data_t out_data; \
  uint1_t out_data_valid; \
  uint1_t out_last; \
  uint1_t in_data_ready; \
}name##_o_t; \
name##_o_t name(data_t in_data[IN_SIZE], uint1_t in_data_valid, uint1_t out_data_ready) \
{ \
  name##_o_t o; \
  name##_serializer_in_to_out_t ser_in_to_out = name##_serializer_in_to_out(in_data, in_data_valid, out_data_ready); \
  o.out_data = ser_in_to_out.out_data[0]; \
  o.out_data_valid = ser_in_to_out.out_data_valid; \
  o.out_last = ser_in_to_out.out_last; \
  o.in_data_ready = ser_in_to_out.in_data_ready; \
  return o; \
} 
