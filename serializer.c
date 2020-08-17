#define serializer(name, out_data_t, IN_SIZE) \
out_data_t name##_in_buffer[IN_SIZE]; \
uint1_t name##_in_buffer_valid; \
uint32_t name##_out_counter; \
typedef struct name##_o_t \
{ \
  out_data_t out_data; \
  uint1_t out_data_valid; \
  uint1_t in_data_ready; \
  uint1_t overflow; \
}name##_o_t; \
name##_o_t name(out_data_t in_data[IN_SIZE], uint1_t in_data_valid, uint1_t out_data_ready) \
{ \
  name##_o_t rv; \
  /* Default outputs from front of shift buffer */ \
  rv.out_data = name##_in_buffer[0]; \
  rv.out_data_valid = name##_in_buffer_valid; \
  /* Overflow if no room for incoming data */ \
  rv.overflow = in_data_valid & name##_in_buffer_valid; \
  rv.in_data_ready = !name##_in_buffer_valid; \
  \
  /* Only shift buffer if output ready */ \
  if(out_data_ready) \
  { \
    /* Shift buffer to bring next elem to front */ \
    uint32_t i; \
    for(i=0;i<(IN_SIZE-1);i=i+1) \
    { \
      name##_in_buffer[i] = name##_in_buffer[i+1]; \
    } \
    name##_out_counter += 1; \
    \
    /* If output all the elems then clear buffer */ \
    if(name##_out_counter==IN_SIZE) \
    { \
      name##_in_buffer_valid = 0; \
    } \
  } \
  \
  /* Input registers */ \
  if(rv.in_data_ready) \
  { \
    name##_in_buffer = in_data; \
    name##_in_buffer_valid = in_data_valid; \
    name##_out_counter = 0; \
  } \
  \
  return rv; \
} 
