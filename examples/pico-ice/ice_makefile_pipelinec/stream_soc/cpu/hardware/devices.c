// Code implementing devices and their memory map attached to the CPU

// Helpers macros for building mmio modules
#include "risc-v/mem_map.h"
// Include memory map to implement in hardware
#include "../mem_map.h"

// Devices attached to the CPU
// Simple clock for software wait()
#include "../../clock/hardware/device.c"
// GPIO
#include "../../led_g/hardware/device.c"
// Shared AXI-Lite test module
#include "../../axi_lite_demo/hardware/device.c"
// AXI-Lite test module for blue LED control
#include "../../led_b_axi_lite/hardware/device.c"

// MULTI CLOCK VERSION LAST, should see not meet timing first...
/*typedef enum my_mm_state_t{
  DECODE_ADDR,
  START_OP,
  END_OP
}my_mm_state_t; TODO USE WITH my_mm_entry_t and my_mm_entry_type_t*/

// Define MMIO inputs and outputs
// Define the hardware memory for those IO
// See typedefs for valid and ready handshake used on input and output
RISCV_DECL_MEM_MAP_MOD_OUT_T(my_mm_regs_t)
riscv_mem_map_mod_out_t(my_mm_regs_t) my_mm_module(
  RISCV_MEM_MAP_MOD_INPUTS(my_mm_regs_t)
){
  riscv_mem_map_mod_out_t(my_mm_regs_t) o;

  // Adjust address for MY_MEM_MAP_BASE_ADDR|MY_MEM_MAP_ADDR_BIT_CHECK=31
  uint31_t relative_addr = addr;
  
  // Two states like CPU, minimum 1 cycle for MMIO operations
  static uint1_t is_START_state_reg = 1; // Otherwise is END
  uint1_t is_START_state = is_START_state_reg;
  // START, END: 
  //  1 cycle for regs and BRAM (output registers), variable wait for AXI RAMs etc
  //  TODO make decoding type / comparing addrs into separate state with regs etc?

  // Signals and default values for storage types
  uint1_t mm_regs_enabled;
  //  REGISTERS
  static my_mm_entry_type_t mm_type_reg;
  my_mm_entry_type_t mm_type = mm_type_reg;
  static uint32_t entry_index_reg;
  uint32_t entry_index = entry_index_reg;
  static uint32_t regs_rd_data_out_reg;
  uint32_t regs_rd_data_out = regs_rd_data_out_reg;

  // MM registers
  my_mm_regs_t my_mm_regs = mm_regs_in; // input 'current' value for user memory mapped regs
  // Device specfic use of those registers
  //#include "device/mm_regs.c"

  // MM Shared AXI
  // TODO make this cleaner and easier to scale?
  // Default no mem op
  axi_lite_demo_from_host = axi_shared_bus_t_HOST_TO_DEV_NULL; 
  led_b_axi_lite_from_host = axi_shared_bus_t_HOST_TO_DEV_NULL;
  // AXI write addr + data setup
  axi_write_req_t axi_wr_req;
  axi_wr_req.awaddr = relative_addr;
  axi_wr_req.awlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  axi_wr_req.awsize = 2; // 2^2=4 bytes per transfer
  axi_wr_req.awburst = BURST_FIXED; // Not a burst, single fixed address per transfer 
  axi_write_data_t axi_wr_data;
  //  Which of 4 bytes are being written?
  uint32_t i;
  for(i=0; i<4; i+=1)
  {
    axi_wr_data.wdata[i] = wr_data >> (i*8);
    axi_wr_data.wstrb[i] = wr_byte_ens[i];
  }
  // AXI read setup
  axi_read_req_t axi_rd_req;
  axi_rd_req.araddr = relative_addr;
  axi_rd_req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  axi_rd_req.arsize = 2; // 2^2=4 bytes per transfer
  axi_rd_req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer

  // Start MM operation
  if(is_START_state_reg){
    // Wait for valid input start signal 
    if(valid){
      // Write or read helper flags
      uint1_t word_wr_en = 0;
      uint1_t word_rd_en = 0;
      for(uint32_t i=0;i<4;i+=1){
        word_wr_en |= wr_byte_ens[i];
        word_rd_en |= rd_byte_ens[i];
      }
      // Starting what kind of operation?
      mm_type = UNMAPPED;
      entry_index = 0;
      for (uint32_t i = 0; i < N_MM_ENTRIES; i+=1)
      {
        if(
          (relative_addr >= MY_MM_ENTRIES[i].start_addr) &
          (relative_addr < MY_MM_ENTRIES[i].end_addr)
        ){
          mm_type = MY_MM_ENTRIES[i].dev_type;
          entry_index = i;
        }
      }
      mm_regs_enabled = 1; // Dont need addr check, MM ENTRY includes
      if(mm_type==REGS){
        // Regs always ready now
        o.ready_for_inputs = 1;
      }else if(mm_type==SHARED_AXI){
        // Which AXI dev to host bus to connect to?
        axi_shared_bus_t_dev_to_host_t selected_dev_to_host;
        if(entry_index==AXIL_TEST_MM_ENTRY_INDEX) selected_dev_to_host = axi_lite_demo_to_host;
        if(entry_index==LED_B_MM_ENTRY_INDEX) selected_dev_to_host = led_b_axi_lite_to_host;
        axi_shared_bus_t_host_to_dev_t selected_host_to_dev;
        // Start a write
        if(word_wr_en){
          // Invoke helper FSM
          axi_shared_bus_t_write_start_logic_outputs_t write_start =  
            axi_shared_bus_t_write_start_logic(
              axi_wr_req,
              axi_wr_data, 
              1,
              axi_lite_demo_to_host.write
            ); 
          selected_host_to_dev.write = write_start.to_dev;
          // Finally ready and done with inputs when start finished
          if(write_start.done){ 
            o.ready_for_inputs = 1;
          }
        }
        // Start a read
        if(word_rd_en){
          // Invoke helper FSM
          axi_shared_bus_t_read_start_logic_outputs_t read_start =  
            axi_shared_bus_t_read_start_logic(
              axi_rd_req,
              1,
              axi_lite_demo_to_host.read.req_ready
            ); 
          selected_host_to_dev.read.req = read_start.req;
          // Finally ready and done with inputs when start finished
          if(read_start.done){ 
            o.ready_for_inputs = 1;
          }
        }
        // Which AXI host to dev bus to connect to?
        if(entry_index==AXIL_TEST_MM_ENTRY_INDEX) axi_lite_demo_from_host = selected_host_to_dev;
        if(entry_index==LED_B_MM_ENTRY_INDEX) led_b_axi_lite_from_host = selected_host_to_dev;
      }
      // Goto end state once ready for input
      if(o.ready_for_inputs){
        is_START_state = 0;
      }
    }
  }

  // Memory muxing/select logic for control and status registers
  if(mm_regs_enabled){
    STRUCT_MM_ENTRY_NEW(MY_MM_ENTRIES[REGS_MM_ENTRY_INDEX].start_addr, my_mm_regs_t, my_mm_regs, my_mm_regs, relative_addr, o.addr_is_mapped, regs_rd_data_out)
  }

  // End MMIO operation
  if(~is_START_state_reg){
    o.addr_is_mapped = 1;
    // Ending regs operation
    if(mm_type_reg==REGS){
      o.rd_data = regs_rd_data_out_reg;
      o.valid = 1;
    }else if(mm_type_reg==SHARED_AXI){
      // Which AXI dev to host bus to connect to?
      axi_shared_bus_t_dev_to_host_t selected_dev_to_host;
      if(entry_index_reg==AXIL_TEST_MM_ENTRY_INDEX) selected_dev_to_host = axi_lite_demo_to_host;
      if(entry_index_reg==LED_B_MM_ENTRY_INDEX) selected_dev_to_host = led_b_axi_lite_to_host;
      axi_shared_bus_t_host_to_dev_t selected_host_to_dev;
      // Normal wait for mem to properly finish both reads or writes
      // Signal ready for both read and write responses
      // (only one in use)
      selected_host_to_dev.read.data_ready = ready_for_outputs;
      selected_host_to_dev.write.resp_ready = ready_for_outputs;
      // Either write or read resp is valid done signal
      o.valid = selected_dev_to_host.read.data.valid | 
                selected_dev_to_host.write.resp.valid;
      // Read data is 4 bytes into u32
      o.rd_data = axi_read_to_data(selected_dev_to_host.read.data.burst.data_resp.user);
      // Which AXI host to dev bus to connect to?
      if(entry_index_reg==AXIL_TEST_MM_ENTRY_INDEX) axi_lite_demo_from_host = selected_host_to_dev;
      if(entry_index_reg==LED_B_MM_ENTRY_INDEX) led_b_axi_lite_from_host = selected_host_to_dev;
    }
    // Start over when done
    if(o.valid & ready_for_outputs){
      is_START_state = 1;
    }
  }

  // Other regs
  is_START_state_reg = is_START_state;
  mm_type_reg = mm_type;
  entry_index_reg = entry_index;
  regs_rd_data_out_reg = regs_rd_data_out;

  // output the 'next' value for user memory mapped regs
  o.mm_regs_out = my_mm_regs; 
  return o;
}

