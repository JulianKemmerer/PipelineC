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
  uint1_t read_ack;\
  uint1_t overflow;\
  uint1_t underflow;\
} name##_t;\
name##_t name(uint1_t rd, type data_in, uint1_t wr)\
{\
  /* Shift buffer thing, shift an element forward if possible*/\
  /* as elements are read out from front*/\
  name##_t rv;\
  /* Read from front, fwft */\
  rv.data_out = name##_data_buf[0];\
  rv.data_out_valid = name##_valid_buf[0];\
  rv.underflow = 0;\
  rv.read_ack = 0;\
  /* Read clears output buffer to allow for shifting forward*/\
  if(rd)\
  {\
    name##_valid_buf[0] = 0;\
    rv.underflow = !rv.data_out_valid;\
    rv.read_ack = rv.data_out_valid;\
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
  rv.overflow = 0;\
  if(rv.data_in_ready)\
  {\
    name##_data_buf[size-1] = data_in;\
    name##_valid_buf[size-1] = wr;\
    rv.write_ack = wr;\
  }\
  else\
  {\
    rv.overflow = wr;\
  }\
  /* Ready for data next iteration if back of queue is empty still */\
  rv.data_in_ready_next = !name##_valid_buf[size-1];\
  return rv;\
}

// FWFT style using RAM prim
// Has latency issues: https://github.com/JulianKemmerer/PipelineC/issues/142
// TODO rewrite based on pipelinec_fifo_fwft VHDL
#define FIFO_FWFT_EXTRA_STOP_LATENCY 2 
#define FIFO_FWFT_MIN_LEVEL 6 // 2 cycle latency buffer + 2 cycles latency through ram + 2 cycles to extra to restart per issue
#define FIFO_FWFT_MIN_PROG_FULL (FIFO_FWFT_MIN_LEVEL + FIFO_FWFT_EXTRA_STOP_LATENCY)
#define FIFO_FWFT(name, type_t, DEPTH) FIFO_FWFT_DEPTH_ADDR_COUNT(name, type_t, DEPTH, uint28_t, uint28_t)
#define FIFO_FWFT_DEPTH_ADDR_COUNT(name, type_t, DEPTH, fifo_ram_addr_t, fifo_count_t) \
typedef struct name##_t \
{ \
  type_t data_out; \
  uint1_t data_out_valid; \
  uint1_t data_in_ready; \
  uint1_t empty; \
  uint1_t full; \
  fifo_count_t count; \
}name##_t; \
name##_t name(uint1_t rd, type_t data_in, uint1_t wr) \
{ \
  /* Count of elements in fifo */ \
  static fifo_count_t count; \
   \
  /* Read and write pointers into RAM */ \
  static fifo_ram_addr_t raddr; \
  static fifo_ram_addr_t waddr; \
  /* Actual read from RAM is up to two elements in advance for FWFT */ \
  static fifo_ram_addr_t raddr_fwft; \
   \
  /* Delay/shift regs alongside RAM for read enable/data out valid flag */ \
  static uint1_t ram_rd_valid_delay[2]; \
     \
  /* FWFT output regs, two to cover two clock bram delay */ \
  static type_t out_data[2]; \
  static uint1_t out_data_valid[2]; \
   \
  /* Incremented w/ wrap around read and write ptr values */ \
  fifo_ram_addr_t waddr_next = 0; \
  if(waddr < (DEPTH-1)) \
  { \
    waddr_next = waddr + 1;  \
  } \
  fifo_ram_addr_t raddr_next = 0; \
  if(raddr < (DEPTH-1)) \
  { \
    raddr_next = raddr + 1;  \
  } \
  fifo_ram_addr_t raddr_fwft_next = 0; \
  if(raddr_fwft < (DEPTH-1)) \
  { \
    raddr_fwft_next = raddr_fwft + 1; \
  } \
  /* FWFT advance read offset w/ wrap around */ \
  fifo_ram_addr_t fwft_offset; \
  if(raddr_fwft >= raddr) \
  { \
    fwft_offset = raddr_fwft - raddr; \
  } \
  else \
  { \
    fwft_offset = DEPTH - (raddr - raddr_fwft); \
  } \
   \
  /* Output signals */ \
  name##_t rv; \
  rv.count = count; \
   \
  /* Input write side into RAM */ \
  uint1_t has_data = count>0; \
  rv.full = (waddr==raddr) & has_data; \
  rv.data_in_ready = !rv.full; \
  /* Allow write to RAM if not full/are ready */ \
  uint1_t ram_wr_en = 0; \
  if(rv.data_in_ready) \
  { \
    ram_wr_en = wr; \
  } \
   \
  /* Output read side from two element buffer */ \
  rv.data_out = out_data[1]; \
  rv.data_out_valid = out_data_valid[1]; \
  rv.empty = !has_data; \
  /* Count reads, increment read pointer  */ \
  if(rd) \
  { \
    if(out_data_valid[1]==1) \
    { \
      count -= 1; \
      raddr = raddr_next; \
    } \
    /* Clear output regs */ \
    out_data_valid[1] = 0; \
  } \
  /* Shift output reg forward if next spot empty */ \
  if(out_data_valid[1]==0) \
  { \
    out_data[1] = out_data[0]; \
    out_data_valid[1] = out_data_valid[0]; \
    out_data_valid[0] = 0; \
  } \
   \
  /* FWFT reads as far in advance as possible */ \
  uint1_t ram_rd_en = 0; \
  uint1_t use_raddr_fwft_next = 0; /* Aka when read incrementing or resetting */ \
  if(has_data & (fwft_offset < count)) \
  { \
    /* Do read of valid in advance fwft data */ \
    ram_rd_en = 1; \
    use_raddr_fwft_next = 1; \
  } \
  /* Advance reads going too far results in read data from RAM being output */ \
  /* when no space in output buffer is available (already valid) */ \
  if((ram_rd_valid_delay[1]==1) & (out_data_valid[0]==1)) \
  { \
    /* Need to drop this bad read (or maybe two) */ \
    /* Calculate reset value for raddr_fwft_next */ \
    use_raddr_fwft_next = 1; \
    if(ram_rd_valid_delay[0]==1) \
    { \
      /* Two reads in flight to drop (w/ wrap around) */ \
      raddr_fwft_next = raddr_fwft - 2; \
      if(raddr_fwft==1) \
      { \
        raddr_fwft_next = DEPTH-1; \
      } \
      else if(raddr_fwft==0) \
      { \
        raddr_fwft_next = DEPTH-2; \
      } \
    } \
    else \
    { \
      /* One read in flight to drop (w/ wrap around) */ \
      raddr_fwft_next = raddr_fwft - 1; \
      if(raddr_fwft==0) \
      { \
        raddr_fwft_next = DEPTH-1; \
      }  \
    } \
    /* Reset all in flight reads*/ \
    ram_rd_en = 0; \
    ram_rd_valid_delay[0] = 0; \
  }   \
   \
  /* The RAM primitive */ \
  static type_t the_ram[DEPTH]; \
  type_t rd_data = the_ram_RAM_DP_RF_2(raddr_fwft, waddr, data_in, ram_wr_en); \
  /* Shift/delay reg valid flag along side read delay */ \
  /* Output of RAM into output regs when output regs ready(not having valid data) */ \
  if(out_data_valid[0]==0) \
  { \
    out_data_valid[0] = ram_rd_valid_delay[1]; \
    out_data[0] = rd_data; \
  } \
  /* Delay ram_rd_en two cycles to be output valid */ \
  ram_rd_valid_delay[1] = ram_rd_valid_delay[0]; \
  ram_rd_valid_delay[0] = ram_rd_en; \
   \
  /* Increment/reset fwft read pointer */ \
  if(use_raddr_fwft_next) \
  {   \
    raddr_fwft = raddr_fwft_next; \
    /* Reads counted, raddr incremented at output regs */ \
  } \
   \
  /* Increment write pointer */ \
  if(ram_wr_en) \
  {     \
    waddr = waddr_next; \
    /* Count writes here as well */ \
    count += 1; \
  } \
   \
  return rv; \
}
