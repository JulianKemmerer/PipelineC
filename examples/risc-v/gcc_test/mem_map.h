#pragma once

// Hardware memory address mappings for PipelineC and software C code

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#endif

#define MEM_MAP_BASE_ADDR 0x10000000

#define N_THREADS_PER_BARREL 5
#define N_BARRELS 4
#define NUM_THREADS 20
// Read: Thread ID, Write: output/stop/halt peripheral
#define THREAD_ID_RETURN_OUTPUT_ADDR (MEM_MAP_BASE_ADDR+0)
static volatile uint32_t* RETURN_OUTPUT = (uint32_t*)THREAD_ID_RETURN_OUTPUT_ADDR;
static volatile uint32_t* THREAD_ID = (uint32_t*)THREAD_ID_RETURN_OUTPUT_ADDR;

// LED
#define LED_ADDR (THREAD_ID_RETURN_OUTPUT_ADDR + sizeof(uint32_t))
static volatile uint32_t* LED = (uint32_t*)LED_ADDR;

// Re: memory mapped structs
//__attribute__((packed)) increases code size bringing in memcpy
// Not actually needed to pack for ~memory savings
// when memory mapped padding regs will optimize away if unused
// So manually add padding fields for 32b|4B alignment (otherwise need packed)
// (if not PipelineC built in to-from bytes functions won't work)

// // For now use separate input and output structs for accelerators
// // that have special input and output valid flags
// #include "gcc_test/gol/hw_config.h"

// Types that PipelineC and CPU share to talk to hardware ram RAM
#define riscv_valid_flag_t int32_t // TODO single bit packing
#define RISCV_RAM_NUM_BURST_WORDS 1
typedef struct riscv_ram_read_req_t
{
  uint32_t addr;
  uint32_t num_words;
  riscv_valid_flag_t valid;
}riscv_ram_read_req_t;
typedef struct riscv_ram_read_resp_t
{
  uint32_t data[RISCV_RAM_NUM_BURST_WORDS];
  uint32_t num_words;
  riscv_valid_flag_t valid;
}riscv_ram_read_resp_t;
typedef struct riscv_ram_write_req_t
{
  uint32_t addr;
  uint32_t data[RISCV_RAM_NUM_BURST_WORDS];
  uint32_t num_words;
  riscv_valid_flag_t valid;
}riscv_ram_write_req_t;
typedef struct riscv_ram_write_resp_t
{
  uint32_t num_words;
  riscv_valid_flag_t valid;
}riscv_ram_write_resp_t;

// Assumes valid is last bytes of type
#define ADDR_IS_VALID_FLAG(addr, ADDR, type_t)\
( (addr >= ((ADDR+sizeof(type_t))-sizeof(riscv_valid_flag_t))) & (addr < (ADDR+sizeof(type_t))) )

// To-from bytes conversion funcs
#ifdef __PIPELINEC__
#include "riscv_ram_read_req_t_bytes_t.h"
#include "riscv_ram_read_resp_t_bytes_t.h"
#include "riscv_ram_write_req_t_bytes_t.h"
#include "riscv_ram_write_resp_t_bytes_t.h"
#endif

#define RAM_WR_REQ_ADDR (LED_ADDR+sizeof(uint32_t))
static volatile riscv_ram_write_req_t* RAM_WR_REQ = (riscv_ram_write_req_t*)RAM_WR_REQ_ADDR;

#define RAM_WR_RESP_ADDR (RAM_WR_REQ_ADDR + sizeof(riscv_ram_write_req_t))
static volatile riscv_ram_write_resp_t* RAM_WR_RESP = (riscv_ram_write_resp_t*)RAM_WR_RESP_ADDR;

#define RAM_RD_REQ_ADDR (RAM_WR_RESP_ADDR + sizeof(riscv_ram_write_resp_t))
static volatile riscv_ram_read_req_t* RAM_RD_REQ = (riscv_ram_read_req_t*)RAM_RD_REQ_ADDR;

#define RAM_RD_RESP_ADDR (RAM_RD_REQ_ADDR + sizeof(riscv_ram_read_req_t))
static volatile riscv_ram_read_resp_t* RAM_RD_RESP = (riscv_ram_read_resp_t*)RAM_RD_RESP_ADDR;



// Multiple in flight versions:
static inline __attribute__((always_inline)) riscv_valid_flag_t try_start_ram_write(
  uint32_t addr, uint32_t* data, uint8_t num_words
){
  // If the request flag is valid from a previous req
  // then done now, couldnt start
  if(RAM_WR_REQ->valid){
    return 0;
  }
  // Start
  RAM_WR_REQ->addr = addr;
  RAM_WR_REQ->num_words = num_words;
  // TODO skip copy is data pointer if mmio regs already
  for(uint32_t i = 0; i < num_words; i++)
  {
    RAM_WR_REQ->data[i] = data[i];
  }
  RAM_WR_REQ->valid = 1;
  return 1;
}
static inline __attribute__((always_inline)) void start_ram_write(
  uint32_t addr, uint32_t* data, uint8_t num_words
){
  while(!try_start_ram_write(addr, data, num_words)){}
}

static inline __attribute__((always_inline)) riscv_valid_flag_t try_start_ram_read(
  uint32_t addr, uint32_t num_words
){
  // If the request flag is valid from a previous req
  // then done now, couldnt start
  if(RAM_RD_REQ->valid){
    return 0;
  }
  // Start
  RAM_RD_REQ->addr = addr;
  RAM_RD_REQ->num_words = num_words;
  RAM_RD_REQ->valid = 1;
  return 1;
}
static inline __attribute__((always_inline)) void start_ram_read(uint32_t addr, uint32_t num_words){
  while(!try_start_ram_read(addr, num_words)){}
}


static inline __attribute__((always_inline)) riscv_valid_flag_t try_finish_ram_write(uint32_t num_words){
  // No write response data
  // Simply read and return response valid bit
  // Hardware automatically clears valid bit + num words on read of valid=1
  RAM_WR_RESP->num_words = num_words; // Requested num of words
  return RAM_WR_RESP->valid;
}
static inline __attribute__((always_inline)) void finish_ram_write(uint32_t num_words){
  RAM_WR_RESP->num_words = num_words;
  while(!RAM_WR_RESP->valid){}
}
// Caution trying for different num_words might not make sense?
/*static inline __attribute__((always_inline)) riscv_valid_flag_t try_finish_ram_read(uint32_t* data, uint8_t num_words){
  // Have valid read response data?
  RAM_RD_RESP->num_words = num_words; // Requested num of words
  riscv_valid_flag_t rv = RAM_RD_RESP->valid;
  // If not then done now
  if(!rv){
    return rv;
  }
  // Valid is not auto cleared by hardware
  // Save the valid data
  // TODO skip copy if data pointer is mmio regs already
  for(uint32_t i = 0; i < num_words; i++)
  {
    data[i] = RAM_RD_RESP->data[i];
  }
  // Manually clear the valid buffer
  RAM_RD_RESP->num_words = 0;
  RAM_RD_RESP->valid = 0;
  // Done
  return rv;
}*/
static inline __attribute__((always_inline)) void finish_ram_read(uint32_t* data, uint8_t num_words){
  // Wait for finish
  RAM_RD_RESP->num_words = num_words; // Requested num of words
  while(!RAM_RD_RESP->valid){}
  // Valid is not auto cleared by hardware
  // Save the valid data
  // TODO skip copy if data pointer is mmio regs already?
  for(uint32_t i = 0; i < num_words; i++)
  {
    data[i] = RAM_RD_RESP->data[i];
  }
  // Manually clear the valid buffer
  RAM_RD_RESP->num_words = 0;
  RAM_RD_RESP->valid = 0;
  // Done
}

// One in flight, start one and finishes one
// Does not need to check before starting next xfer
static inline __attribute__((always_inline)) void ram_write(uint32_t addr, uint32_t* data, uint8_t num_words){
  // Start
  // Dont need try_ logic to check if valid been cleared, just set
  // Start
  RAM_WR_REQ->addr = addr;
  RAM_WR_REQ->num_words = num_words;
  // TODO skip copy if data pointer is mmio regs already?
  for(uint32_t i = 0; i < num_words; i++)
  {
    RAM_WR_REQ->data[i] = data[i];
  }
  RAM_WR_REQ->valid = 1;
  // Finish
  finish_ram_write(num_words);
}
static inline __attribute__((always_inline)) void ram_read(uint32_t addr, uint32_t* data, uint8_t num_words){
  // Start
  // Dont need try_ logic to check if valid been cleared, just set
  RAM_RD_REQ->addr = addr;
  RAM_RD_REQ->num_words = num_words;
  RAM_RD_REQ->valid = 1;
  // Wait for finish
  finish_ram_read(data, num_words);
}


// Frame sync
#define FRAME_SIGNAL_ADDR (RAM_RD_RESP_ADDR + sizeof(riscv_ram_read_resp_t))
static volatile int32_t* FRAME_SIGNAL = (int32_t*)FRAME_SIGNAL_ADDR;