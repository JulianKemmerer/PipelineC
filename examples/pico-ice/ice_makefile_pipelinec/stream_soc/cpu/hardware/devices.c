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

  // What kind of memory mapped storage?
  //static uint1_t word_wr_en;
  //static uint1_t word_rd_en;
  
  //USE WITH my_mm_entry_t and my_mm_entry_type_t and make loop over all entries (AXI unused, then add axi)
  // 'is type' is register, set in START and held until end (based on addr only valid during input)
  //  TODO make decoding type / comparing addrs into separate state with regs etc?
  // Signals and default values for storage types
  uint1_t mm_regs_enabled;
  //  REGISTERS
  static my_mm_entry_type_t mm_type_reg;
  my_mm_entry_type_t mm_type = mm_type_reg;
  static uint32_t entry_index;
  static uint32_t regs_rd_data_out_reg;
  uint32_t regs_rd_data_out = regs_rd_data_out_reg;

  // MM registers
  my_mm_regs_t my_mm_regs = mm_regs_in; // input 'current' value for user memory mapped regs
  // Device specfic use of those registers
  //#include "device/mm_regs.c"

  // Start MM operation
  if(is_START_state_reg){
    // Wait for valid input start signal 
    if(valid){
      // Write or read helper flags
      //word_wr_en = 0;
      //word_rd_en = 0;
      //uint32_t i;
      //for(i=0;i<4;i+=1){
      //  word_wr_en |= wr_byte_ens[i];
      //  word_rd_en |= rd_byte_ens[i];
      //}
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
        // Not needed during input cycles? o.addr_is_mapped = 1;
      }
      // Goto end state once ready for input
      if(o.ready_for_inputs){
        is_START_state = 0;
      }
    }
  }

  // Memory muxing/select logic for control and status registers
  if(mm_regs_enabled){
    STRUCT_MM_ENTRY_NEW(MY_MM_ENTRIES[0].start_addr, my_mm_regs_t, my_mm_regs, my_mm_regs, relative_addr, o.addr_is_mapped, regs_rd_data_out)
  }

  // End MMIO operation
  if(~is_START_state_reg){
    o.addr_is_mapped = 1;
    // Ending regs operation
    if(mm_type_reg==REGS){
      o.rd_data = regs_rd_data_out_reg;
      o.valid = 1;
    }
    // Start over when done
    if(o.valid & ready_for_outputs){
      is_START_state = 1;
    }
  }

  // Other regs
  is_START_state_reg = is_START_state;
  mm_type_reg = mm_type;
  regs_rd_data_out_reg = regs_rd_data_out;

  // output the 'next' value for user memory mapped regs
  o.mm_regs_out = my_mm_regs; 
  return o;
}

