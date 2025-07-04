// Helpers macros for building mmio modules
#include "risc-v/mem_map.h"

// Include memory map to implement in hardware
#include "../software/mem_map.h"

// AXI buses as specified by user memory mappings
// Include code for Xilinx DDR AXI shared resource bus as frame buffer example
// Declares AXI shared resource bus wires
//   host_clk_to_dev(axi_xil_mem) and dev_to_host_clk(axi_xil_mem)
#define AXI_RAM_MODE_DDR // Configure frame buffer to use Xilinx AXI DDR RAM (not bram)
#include "../../frame_buffers/hardware/dual_frame_buffer.c"

// Connect I2S to AXI bus (in I2S clock domain)
#pragma MAIN i2s_axi_connect
void i2s_axi_connect(){
  host_to_dev(axi_xil_mem, i2s) = i2s_axi_host_to_dev;
  i2s_axi_host_from_dev = dev_to_host(axi_xil_mem, i2s);
}

// Connect FFT to AXI bus (in CPU clock domain)
#pragma MAIN fft_axi_connect
void fft_axi_connect(){
  host_to_dev(axi_xil_mem, cpu) = fft_axi_host_to_dev;
  fft_axi_host_from_dev = dev_to_host(axi_xil_mem, cpu);
}

// Define MMIO inputs and outputs
typedef struct my_mmio_in_t{
  mm_status_regs_t status;
}my_mmio_in_t;
typedef struct my_mmio_out_t{
  mm_ctrl_regs_t ctrl;
}my_mmio_out_t;
// Define the hardware memory for those IO
// See typedefs for valid and ready handshake used on input and output
RISCV_DECL_MEM_MAP_MOD_OUT_T(my_mmio_out_t)
riscv_mem_map_mod_out_t(my_mmio_out_t) my_mem_map_module(
  RISCV_MEM_MAP_MOD_INPUTS(my_mmio_in_t)
){
  riscv_mem_map_mod_out_t(my_mmio_out_t) o;
  
  // Two states like CPU
  static uint1_t is_START_state = 1; // Otherwise is END
  // START, END: 
  //  same cycle for regs, 1 cycle delay for BRAM, variable wait for AXI RAMs etc

  // What kind of memory mapped storage?
  static uint1_t word_wr_en;
  static uint1_t word_rd_en;
  // 'is type' is register, set in START and held until end (based on addr only valid during input)
  // Signals and default values for storage types
  //  REGISTERS
  static uint1_t mm_type_is_regs; 
  uint1_t mm_regs_enabled; // Default no reg op
  //  AXI RAMs // TODO MACROs to easily map multiple AXI buses? shared resource buses in general?
  static uint1_t mmio_type_is_axi0;
  uint32_t axi0_addr = addr - MMIO_AXI0_ADDR; // Account for offset in memory
  host_to_dev(axi_xil_mem, cpu) = axi_shared_bus_t_HOST_TO_DEV_NULL; // Default no mem op

  // MM Control+status registers
  static mm_ctrl_regs_t ctrl;
  o.outputs.ctrl = ctrl; // output reg
  static mm_status_regs_t status;
  // MM Handshake regs start off looking like regular ctrl+status MM regs
  static mm_handshake_data_t handshake_data;
  static mm_handshake_valid_t handshake_valid;

  // Start MM operation
  if(is_START_state){
    // Wait for valid input start signal 
    if(valid){
      // Write or read helper flags
      word_wr_en = 0;
      word_rd_en = 0;
      uint32_t i;
      for(i=0;i<4;i+=1){
        word_wr_en |= wr_byte_ens[i];
        word_rd_en |= rd_byte_ens[i];
      }
      // Starting regs operation?
      mm_type_is_regs = (
        ( (addr>=MM_CTRL_REGS_ADDR)   & (addr<(MM_CTRL_REGS_ADDR+sizeof(mm_ctrl_regs_t))) ) |
        ( (addr>=MM_STATUS_REGS_ADDR) & (addr<(MM_STATUS_REGS_ADDR+sizeof(mm_status_regs_t))) ) |
        ( (addr>=MM_HANDSHAKE_DATA_ADDR) & (addr<(MM_HANDSHAKE_DATA_ADDR+sizeof(mm_handshake_data_t))) ) |
        ( (addr>=MM_HANDSHAKE_VALID_ADDR) & (addr<(MM_HANDSHAKE_VALID_ADDR+sizeof(mm_handshake_valid_t))) )
      );
      if(mm_type_is_regs){
        // Regs always ready now, i.e. if output was ready
        o.ready_for_inputs = ready_for_outputs;
        o.addr_is_mapped = 1;
        // Valid pulse to do reg op this cycle when ready
        mm_regs_enabled = o.ready_for_inputs;
      }
      // AXI0 start/request signaling (direct global wiring for now)
      // Use helper axi shared resource bus fsm funcs to do the AXI stuff and signal when done
      mmio_type_is_axi0 = (addr>=MMIO_AXI0_ADDR) & (addr<(MMIO_AXI0_ADDR+MMIO_AXI0_SIZE));
      if(mmio_type_is_axi0){
        // Start a write
        o.addr_is_mapped = 1;
        if(word_wr_en){
          // AXI write addr + data setup
          axi_write_req_t axi_wr_req;
          axi_wr_req.awaddr = axi0_addr;
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
          // Invoke helper FSM
          axi_shared_bus_t_write_start_logic_outputs_t write_start =  
            axi_shared_bus_t_write_start_logic(
              axi_wr_req,
              axi_wr_data, 
              1,
              dev_to_host(axi_xil_mem, cpu).write
            ); 
          host_to_dev(axi_xil_mem, cpu).write = write_start.to_dev;
          // Finally ready and done with inputs when start finished
          if(write_start.done){ 
            o.ready_for_inputs = 1;
          }
        }
        // Start a read
        if(word_rd_en){
          // AXI read setup
          axi_read_req_t axi_rd_req;
          axi_rd_req.araddr = axi0_addr;
          axi_rd_req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
          axi_rd_req.arsize = 2; // 2^2=4 bytes per transfer
          axi_rd_req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
          // Invoke helper FSM
          axi_shared_bus_t_read_start_logic_outputs_t read_start =  
            axi_shared_bus_t_read_start_logic(
              axi_rd_req,
              1,
              dev_to_host(axi_xil_mem, cpu).read.req_ready
            ); 
          host_to_dev(axi_xil_mem, cpu).read.req = read_start.req;
          // Finally ready and done with inputs when start finished
          if(read_start.done){ 
            o.ready_for_inputs = 1;
          }
        }
      }
      // Goto end state once ready for input
      if(o.ready_for_inputs){
        is_START_state = 0;
      }
    }
  }

  // Handshakes

  // FFT output descriptors read from handshake into registers
  // fft_out_desc_written handshake = fft_desc_written stream
  HANDSHAKE_MM_READ(handshake_data, handshake_valid, fft_desc_written, fft_out_desc_written, fft_out_desc_written_ready)
  // FFT descriptors to write stream written by handshake registers
  // fft_in_desc_to_write stream = fft_desc_to_write handshake
  HANDSHAKE_MM_WRITE(fft_in_desc_to_write, fft_in_desc_to_write_ready, handshake_data, handshake_valid, fft_desc_to_write)

  // I2S samples descriptors read from handshake into registers
  HANDSHAKE_MM_READ(handshake_data, handshake_valid, i2s_rx_desc_written, i2s_rx_descriptors_monitor_fifo_out, i2s_rx_descriptors_monitor_fifo_out_ready)
  // I2S descriptors stream written from regs, i2s_rx_desc_to_write
  HANDSHAKE_MM_WRITE(i2s_rx_desc_to_write_fifo_in, i2s_rx_desc_to_write_fifo_in_ready, handshake_data, handshake_valid, i2s_rx_desc_to_write)

  // Memory muxing/select logic for control and status registers
  if(mm_regs_enabled){
    STRUCT_MM_ENTRY_NEW(MM_CTRL_REGS_ADDR, mm_ctrl_regs_t, ctrl, ctrl, addr, o.addr_is_mapped, o.rd_data)
    STRUCT_MM_ENTRY_NEW(MM_STATUS_REGS_ADDR, mm_status_regs_t, status, status, addr, o.addr_is_mapped, o.rd_data)
    STRUCT_MM_ENTRY_NEW(MM_HANDSHAKE_DATA_ADDR, mm_handshake_data_t, handshake_data, handshake_data, addr, o.addr_is_mapped, o.rd_data)
    STRUCT_MM_ENTRY_NEW(MM_HANDSHAKE_VALID_ADDR, mm_handshake_valid_t, handshake_valid, handshake_valid, addr, o.addr_is_mapped, o.rd_data)
  }

  // End MMIO operation
  if(~is_START_state){
    o.addr_is_mapped = 1;
    // Ending regs operation
    if(mm_type_is_regs){
      // No ready to connect since is same cycle op, known ready from earlier
      // Done in same cycle, get ready to start next cycle
      o.valid = 1;
      // rd_data and addr_is_mapped handled in STRUCT_MM helper macro
    }
    // End AXI0 operation
    #ifdef MMIO_AXI0_RAW_HAZZARD
    // Hazzard doesnt wait for writes to finish. Ignores/drains responses
    host_to_dev(axi_xil_mem, cpu).write.resp_ready = 1;
    #endif
    if(mmio_type_is_axi0){
      #ifdef MMIO_AXI0_RAW_HAZZARD
      if(word_wr_en){
        // Hazzard dont wait for writes to finish (see ready=1 always above)
        o.valid = 1;
      }else{
        // Regular read wait for valid response
        host_to_dev(axi_xil_mem, cpu).read.data_ready = ready_for_outputs;
        o.valid = dev_to_host(axi_xil_mem, cpu).read.data.valid;
      }
      #else // Normal wait for mem to properly finish both reads or writes
      // Signal ready for both read and write responses
      // (only one in use)
      host_to_dev(axi_xil_mem, cpu).read.data_ready = ready_for_outputs;
      host_to_dev(axi_xil_mem, cpu).write.resp_ready = ready_for_outputs;
      // Either write or read resp is valid done signal
      o.valid = dev_to_host(axi_xil_mem, cpu).read.data.valid | 
                dev_to_host(axi_xil_mem, cpu).write.resp.valid;
      #endif
      // Read data is 4 bytes into u32
      o.rd_data = axi_read_to_data(dev_to_host(axi_xil_mem, cpu).read.data.burst.data_resp.user);
    }
    // Start over when done
    if(o.valid & ready_for_outputs){
      is_START_state = 1;
    }
  }

  // Input regs
  status = inputs.status;

  return o;
}
