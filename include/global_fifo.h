
#include "compiler.h"

// Trying to replace autogenerated header syntax like
//  #include "clock_crossing/fast_to_slow.h" // Auto generated

#define GLOBAL_FIFO_WIDTH_DEPTH(data_t, name, WIDTH_STR, DEPTH) \
data_t name[DEPTH]; \
typedef struct name##_write_t \
{ \
  uint1_t ready; \
}name##_write_t; \
typedef struct name##_read_t \
{ \
data_t data[WIDTH_STR]; \
uint1_t valid; \
}name##_read_t; \
name##_write_t PPCAT(name##_WRITE_, WIDTH_STR)(data_t write_data[WIDTH_STR], uint1_t write_enable) \
{ \
  name##_write_t unused; \
  return unused; \
} \
name##_read_t PPCAT(name##_READ_, WIDTH_STR)(uint1_t read_enable) \
{ \
  name##_read_t unused; \
  return unused; \
}

#define GLOBAL_FIFO(data_t, name, DEPTH) \
GLOBAL_FIFO_WIDTH_DEPTH(data_t, name, 1, DEPTH)

// Exposes global stream wires version of global fifo
#define GLOBAL_STREAM_FIFO(data_t, name, DEPTH) \
GLOBAL_FIFO(data_t, PPCAT(name,_FIFO), DEPTH)\
stream(data_t) PPCAT(name,_in);\
uint1_t PPCAT(name,_in_ready);\
stream(data_t) PPCAT(name,_out);\
uint1_t PPCAT(name,_out_ready);\
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(name,_wr_stream_in))\
MAIN(PPCAT(name,_wr_stream_in)) \
void PPCAT(name,_wr_stream_in)(){\
  data_t din[1] = { PPCAT(name,_in).data };\
  PPCAT(PPCAT(name,_FIFO),_write_t) wr = PPCAT(name,_FIFO_WRITE_1)(din, PPCAT(name,_in).valid);\
  PPCAT(name,_in_ready) = wr.ready;\
}\
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(name,_rd_stream_out))\
MAIN(PPCAT(name,_rd_stream_out)) \
void PPCAT(name,_rd_stream_out)(){\
  PPCAT(name,_FIFO_read_t) rd = PPCAT(name,_FIFO_READ_1)(PPCAT(name,_out_ready));\
  PPCAT(name,_out).data = rd.data[0];\
  PPCAT(name,_out).valid = rd.valid;\
}