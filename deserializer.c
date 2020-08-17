
#define deserializer(name, in_data_t, OUT_SIZE) \
in_data_t name##_out_buffer[OUT_SIZE]; \
uint1_t name##_out_buffer_valid; \
uint32_t name##_out_counter; /*TODO: reduce bits?*/ \
typedef struct name##_o_t \
{ \
  in_data_t out_data[OUT_SIZE]; \
  uint1_t out_data_valid; \
  uint1_t in_data_ready; \
  uint1_t overflow; \
}name##_o_t; \
name##_o_t name(in_data_t in_data, uint1_t in_data_valid, uint1_t out_data_ready) \
{ \
  name##_o_t rv; \
  /* Overflow if no room for incoming data*/  \
  rv.overflow = in_data_valid & name##_out_buffer_valid; \
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
