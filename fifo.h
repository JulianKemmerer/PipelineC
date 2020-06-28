#pragma once
#include "uintN_t.h"
// Macros for fifos

// A simple, low throughput, scalable in registers, fwft, shifting fifo
#define fifo_shift(name, type, size) \
type name##_data_buf[size];\
uint1_t name##_valid_buf[size];\
/* Wish C could return tuples...*/\
typedef struct name##_t\
{\
  type data_out;\
  uint1_t data_out_valid;\
  uint1_t data_in_ready;\
  uint1_t data_in_ready_next;\
  uint1_t write_ack;\
} name##_t;\
name##_t name##_func(uint1_t rd, type data_in, uint1_t wr)\
{\
  /* Shift buffer thing, shift an element forward if possible*/\
  /* as elements are read out from front*/\
  name##_t rv;\
  /* Read from front, fwft */\
  rv.data_out = name##_data_buf[0];\
  rv.data_out_valid = name##_valid_buf[0];\
  /* Read clears output buffer to allow for shifting forward*/\
  if(rd)\
  {\
    name##_valid_buf[0] = 0;\
  }\
  \
  /* Shift array elements forward if possible*/\
  /* Which positions should shift?*/\
  uint1_t pos_do_shift[size];\
  pos_do_shift[0] = 0; /* Nothing ot left of 0*/\
  uint64_t i;\
  for(i=1;i<size;i=i+1)\
  {\
    /* Can shift to next pos/left if empty */\
    pos_do_shift[i] = !name##_valid_buf[i-1];\
  }\
  /* Do the shifting*/\
  for(i=1;i<size;i=i+1)\
  {\
    if(pos_do_shift[i])\
    {\
      /* Shift to left, and invalidate source on right */\
      name##_data_buf[i-1] = name##_data_buf[i];\
      name##_valid_buf[i-1] = name##_valid_buf[i];\
      name##_valid_buf[i] = 0;\
    }\
  }\
  /* Signal if ready for input */\
  rv.data_in_ready = !name##_valid_buf[size-1];\
  /* Input write goes into back of queue if ready*/\
  rv.write_ack = 0;\
  if(rv.data_in_ready)\
  {\
    name##_data_buf[size-1] = data_in;\
    name##_valid_buf[size-1] = wr;\
    rv.write_ack = wr;\
  }\
  /* Ready for data next iteration if back of queue is empty still */\
  rv.data_in_ready_next = !name##_valid_buf[size-1];\
  return rv;\
}
