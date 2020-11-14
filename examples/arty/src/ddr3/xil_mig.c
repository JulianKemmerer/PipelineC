#pragma once
// https://www.xilinx.com/support/documentation/ip_documentation/ug586_7Series_MIS.pdf
// https://forum.digilentinc.com/topic/18555-arty-a7-and-mig/
// Controller Clock = 3000ps|333.33 MHz
// System / Input Clock = 6000ps|166.66MHz 
// Reference clock = which only accepts a 200MHz clock (common knowledge apparently)
// UI Clock output = Locked to 1/4 of controller clock = 83.33 MHz
// Memory Interface Generator (MIG) component

#include "compiler.h"
#include "wire.h"
#include "uintN_t.h"

// Use debug leds
#include "../leds/led0_3.c"

#define XIL_MIG_MHZ 83.33 // UI CLK
#define xil_mig_addr_t uint28_t
#define xil_mig_size_t uint29_t // Extra bit for counting over
#define XIL_MIG_MEM_SIZE 268435456 // 2^28 , 256MB DDR3 = 28b address
#define XIL_MIG_ADDR_MAX (XIL_MIG_MEM_SIZE-1) //268435455 //4095 //268435455 // 2^28-1 // 256MB DDR3 = 28b address
#define XIL_MIG_CMD_WRITE 0
#define XIL_MIG_CMD_READ 1
#define XIL_MIG_DATA_SIZE 16
typedef struct xil_app_to_mig_t
{
      xil_mig_addr_t  addr            ;
      uint3_t         cmd             ;
      uint1_t         en              ;
      uint8_t         wdf_data[XIL_MIG_DATA_SIZE];
      uint1_t         wdf_end         ;
      uint1_t         wdf_mask[XIL_MIG_DATA_SIZE];
      uint1_t         wdf_wren        ;
      uint1_t         sr_req          ;
      uint1_t         ref_req         ;
      uint1_t         zq_req          ;
}xil_app_to_mig_t;

xil_app_to_mig_t XIL_APP_TO_MIG_T_NULL()
{
  uint32_t i;
  xil_app_to_mig_t rv;
  rv.addr = 0;
  rv.cmd  = 0;
  rv.en = 0;
  for(i=0;i<XIL_MIG_DATA_SIZE;i+=1)
  {
    rv.wdf_data[i] = 0;
  }
  rv.wdf_end = 0;
  for(i=0;i<XIL_MIG_DATA_SIZE;i+=1)
  {
    rv.wdf_mask[i] = 0; // All bytes written
  }
  rv.wdf_wren = 0;
  rv.sr_req = 0;
  rv.ref_req = 0;
  rv.zq_req = 0;
  return rv;
}

typedef struct xil_mig_to_app_t
{
      uint8_t   rd_data[XIL_MIG_DATA_SIZE];
      uint1_t   rd_data_end           ;
      uint1_t   rd_data_valid         ;
      uint1_t   rdy                   ;
      uint1_t   wdf_rdy               ;
      uint1_t   sr_active             ;
      uint1_t   ref_ack               ;
      uint1_t   zq_ack                ;
      uint1_t   ui_clk_sync_rst       ;
      uint1_t   init_calib_complete   ;
}xil_mig_to_app_t;

// Internal globally visible 'ports' / 'wires' (a subset of clock domain crossing)
// Input
xil_app_to_mig_t xil_app_to_mig;
#include "xil_app_to_mig_t_array_N_t.h"
#include "xil_app_to_mig_clock_crossing.h"
// Output
xil_mig_to_app_t xil_mig_to_app;
#include "xil_mig_to_app_t_array_N_t.h"
#include "xil_mig_to_app_clock_crossing.h"

// Top level io connection to board generated memory interface
MAIN_MHZ(xil_mig_module,XIL_MIG_MHZ) // Set clock freq
xil_app_to_mig_t xil_mig_module(xil_mig_to_app_t mig_to_app)
{
  xil_app_to_mig_t app_to_mig;
  WIRE_READ(xil_app_to_mig_t, app_to_mig, xil_app_to_mig)
  WIRE_WRITE(xil_mig_to_app_t, xil_mig_to_app, mig_to_app)
  return app_to_mig;
}

// Helper FSMs
// Not written using global wires since isnt meant to be instantiated as
// only owner of above single instance to/from app wires
// Buffer is not included in module as static since is typically 'shared' memory owned by another module

// TODO MAKE MACROS

// State machine that serializes byte array into ddr at certain byte address
typedef struct mig_write_256_t
{
  uint1_t ready; // ready to start
  xil_app_to_mig_t to_mem;
  uint8_t data[256];
  uint1_t done;
}mig_write_256_t;
mig_write_256_t mig_write_256(uint1_t start, xil_mig_addr_t addr, uint8_t data[256], xil_mig_to_app_t from_mem)
{
  // Registers
  static xil_mig_size_t req_addr;
  static uint1_t started;
  
  // Output wire
  mig_write_256_t o;
  o.ready = !started;
  o.data = data;
  o.to_mem = XIL_APP_TO_MIG_T_NULL();
  o.done = 0;
  
  // Default write data is from front/bottom of data
  uint32_t i;
  for(i=0;i<XIL_MIG_DATA_SIZE;i+=1)
  {
    o.to_mem.wdf_data[i] = o.data[i];
  }
  o.to_mem.cmd = XIL_MIG_CMD_WRITE;
  o.to_mem.addr = req_addr;
  o.to_mem.wdf_end = 1; // TODO bursts later?
  
  // Get started
  if(o.ready)
  {
    started = start;
    req_addr = addr;
  }
  
  if(started)
  {
    // Writes process
    if(req_addr<(addr + 256))
    {
      // If mem controller was ready, then prepare for next data
      uint1_t mem_rdy = from_mem.rdy & from_mem.wdf_rdy;
      if(mem_rdy)
      {
        // Enable the write only if ready //TODO not good practice?
        o.to_mem.en = 1;
        o.to_mem.wdf_wren = 1;
        
        // Shift data down to replace bottom bytes just written out
        for(i=XIL_MIG_DATA_SIZE;i<256;i+=1)
        {
          o.data[i-XIL_MIG_DATA_SIZE] = o.data[i];
        }
        req_addr += XIL_MIG_DATA_SIZE;
        
        // Done?
        if(req_addr >= (addr + 256))
        {
          o.done = 1;
        }
      }
    }
  }

  // Finish
  if(o.done)
  {
    started = 0;
  }

  return o;
}

// State machine that deserializes bytes from memory at a certain address
typedef struct mig_read_256_t{
  uint1_t ready; // ready to start
  xil_app_to_mig_t to_mem;
  uint8_t data[256];
  uint1_t done;
}mig_read_256_t;
mig_read_256_t mig_read_256(uint1_t start, xil_mig_addr_t addr, uint8_t data[256], xil_mig_to_app_t from_mem)
{
  // Registers
  static xil_mig_size_t req_addr;
  static uint9_t resp_pos; // Sized for 256
  static uint1_t started;
  
  // Drive leds
  WIRE_WRITE(uint1_t, led2, started)
  
  // Output wire
  mig_read_256_t o;
  o.data = data;
  o.ready = !started;
  o.to_mem = XIL_APP_TO_MIG_T_NULL();
  o.done = 0;
  
  // Get started
  if(o.ready)
  {
    started = start;
    req_addr = addr;
    resp_pos = 0;
  }
  
  // Default outputs
  o.to_mem.addr = req_addr;
  o.to_mem.cmd = XIL_MIG_CMD_READ;
  
  if(started)
  {
    // Requests reads process
    if(req_addr<(addr + 256))
    {
      // Try to make read reqest
      o.to_mem.en = 1;
      // if ready then next addr
      if(from_mem.rdy)
      {  
         req_addr += XIL_MIG_DATA_SIZE;
      }
    }
    
    // Receive responses process
    if(resp_pos<256)
    {
      // Wait for read response
      if(from_mem.rd_data_valid)
      {
        // Shift the data down to make room for incoming data at top
        uint32_t i;
        for(i=XIL_MIG_DATA_SIZE;i<256;i+=1)
        {
          o.data[i-XIL_MIG_DATA_SIZE] = o.data[i];
        }
        // Write incoming data into top bytes
        for(i=0; i<XIL_MIG_DATA_SIZE; i+=1)
        {
          o.data[(256-1)-i] = from_mem.rd_data[(XIL_MIG_DATA_SIZE-1)-i];
        }
        resp_pos += XIL_MIG_DATA_SIZE;
        
        // Done?
        if(resp_pos >= 256)
        {
          o.done = 1;
        }
      }
    }
  }
  
  // Finish
  if(o.done)
  {
    started = 0;
  }
  
  return o;
}
