#pragma once
#include "uintN_t.h"

// Non FSM style AXI code as base
#include "axi.h"

// Temp hard coded to use AXI bus from the Xilinx Memory controller example
#include "examples/axi/axi_xil_mem.c"
#define AXI_DEV_TO_HOST_WIRE xil_mem_to_app.axi_dev_to_host
#define AXI_HOST_TO_DEV_WIRE app_to_xil_mem.axi_host_to_dev
#define AXI_SET_NULL app_to_xil_mem=NULL_APP_TO_XIL_MEM

// TODO: condsider making a combined single axi32_read_write_logic
uint32_t axi_read_write(uint32_t addr, uint32_t data, uint1_t write_en)
{
  uint32_t rv;
  uint1_t done = 0;
  AXI_SET_NULL;
  while(!done)
  {
    if(write_en)
    {
      axi32_write_logic_outputs_t axi32_write_logic_outputs
        = axi32_write_logic(addr, data, 1, AXI_DEV_TO_HOST_WIRE);
      AXI_HOST_TO_DEV_WIRE = axi32_write_logic_outputs.to_dev;
      done = axi32_write_logic_outputs.done;
    }
    else
    {
      axi32_read_logic_outputs_t axi32_read_logic_outputs
        = axi32_read_logic(addr, 1, AXI_DEV_TO_HOST_WIRE);
      AXI_HOST_TO_DEV_WIRE = axi32_read_logic_outputs.to_dev;
      done = axi32_read_logic_outputs.done;
      rv = axi32_read_logic_outputs.data;
    }
    __clk();
  }
  AXI_SET_NULL;
  return rv;
}
// Derived fsm from func, there can only be a single instance of it
#include "axi_read_write_SINGLE_INST.h"
// Use macros to help avoid nested multiple instances of function by inlining
#define axi_read(addr) axi_read_write(addr, 0, 0)
#define axi_write(addr, data) axi_read_write(addr, data, 1)