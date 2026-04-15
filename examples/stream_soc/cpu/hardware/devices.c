// Helpers macros for building mmio modules
#include "risc-v/mem_map.h"

// Include memory map to implement in hardware
#include "../mem_map.h"

// Devices attached to the CPU

// TODO group collections of includes into larger logical devices?

// Simple clock for software wait()
#include "../../clock/hardware/device.c"

// GPIO
#include "../../led/hardware/device.c"
#include "../../buttons/hardware/device.c"
#include "../../switches/hardware/device.c"

// DDR memory controller IO and shared AXI bus
#include "../../ddr/hardware/device.c"
#include "../../shared_ddr/hardware/device.c"

// VGA display from frame buffer in DDR
#include "../../vga/hardware/device.c"

// I2S RX + TX code
//#include "../../i2s/hardware/i2s.c"
// Instead get I2S samples over ethernet (from other dev board)
#include "../../eth_to_i2s/hardware/device.c"

// Hardware for doing the full FFT power spectrum
#define FFT_CLK_MHZ 110.0
#define FFT_CLK_2X_MHZ 220.0
#include "../../fft/hardware/device.c"
#include "../../power/hardware/device.c"

// OV2640 SCCB+DVP camera
#include "../../cam/ov2640/hardware/device.c"
#include "../../video/crop/hardware/device.c"
#include "../../video/scale/hardware/device.c"
#include "../../video/fb_pos/hardware/device.c"

// Basic proto-GPU thing
#include "../../gpu/hardware/device.c"

// Code implementing memory map for devices attached to the CPU

// Define MMIO inputs and outputs
// Define the hardware memory for those IO
// See typedefs for valid and ready handshake used on input and output
RISCV_DECL_MEM_MAP_MOD_OUT_T(mm_regs_t)
riscv_mem_map_mod_out_t(mm_regs_t) my_mem_map_module(
  RISCV_MEM_MAP_MOD_INPUTS(mm_regs_t)
){
  riscv_mem_map_mod_out_t(mm_regs_t) o;
  
  // Two states like CPU, minimum 1 cycle for MMIO operations
  static uint1_t is_START_state_reg = 1; // Otherwise is END
  uint1_t is_START_state = is_START_state_reg;
  // START, END: 
  //  1 cycle for regs and BRAM (output registers), variable wait for AXI RAMs etc

  // What kind of memory mapped storage?
  static uint1_t word_wr_en;
  static uint1_t word_rd_en;
  // 'is type' is register, set in START and held until end (based on addr only valid during input)
  //  TODO make decoding type / comparing addrs into separate state with regs etc?
  // Signals and default values for storage types
  //  REGISTERS
  static uint1_t mm_type_is_regs_reg;
  uint1_t mm_type_is_regs = mm_type_is_regs_reg;
  uint1_t mm_regs_enabled; // Default no reg op
  static uint32_t regs_rd_data_out_reg;
  uint32_t regs_rd_data_out = regs_rd_data_out_reg;
  //  AXI RAMs // TODO MACROs to easily map multiple AXI buses? shared resource buses in general?
  static uint1_t mmio_type_is_axi0_reg;
  uint1_t mmio_type_is_axi0 = mmio_type_is_axi0_reg;
  uint32_t axi0_addr = addr - MMIO_AXI0_ADDR; // Account for offset in memory
  host_to_dev(axi_xil_mem, cpu) = axi_shared_bus_t_HOST_TO_DEV_NULL; // Default no mem op
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
  // AXI read setup
  axi_read_req_t axi_rd_req;
  axi_rd_req.araddr = axi0_addr;
  axi_rd_req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  axi_rd_req.arsize = 2; // 2^2=4 bytes per transfer
  axi_rd_req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer

  // MM registers
  mm_regs_t mm_regs = mm_regs_in; // input 'current' value for user memory mapped regs
  // Device specfic use of those registers
  #include "../../i2s/hardware/i2s_mm_regs.c"
  #include "../../power/hardware/power_mm_regs.c"
  #include "../../sccb/hardware/sccb_mm_regs.c"
  #include "../../dvp/hardware/mm_regs.c"
  #include "../../video/hardware/mm_regs.c"
  #include "../../gpu/hardware/mm_regs.c"

  // Start MM operation
  if(is_START_state_reg){
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
      mm_regs_enabled = 1; // Dont need addr check, MM ENTRY includes
      // Regs are contiguous so single check will work...
      // 60MHz to check >=?
      //mmio_type_is_axi0 = addr>=MMIO_AXI0_ADDR; // AXI0 assumed all upper
      //mm_type_is_regs = ~mmio_type_is_axi0; // regs assumed all lower than AXI0
      // 65+MHz for < ?
      mm_type_is_regs = addr<MM_REGS_END_ADDR; // regs assumed all lower than AXI0
      mmio_type_is_axi0 = ~mm_type_is_regs; // AXI0 assumed all upper
      if(mm_type_is_regs){
        // Regs always ready now
        o.ready_for_inputs = 1;
        // Not needed during input cycles? o.addr_is_mapped = 1;
      }
      if(mmio_type_is_axi0){ // TODO else if better?
        // Start a write
        // Not needed during input cycles? o.addr_is_mapped = 1;
        if(word_wr_en){
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

  // Memory muxing/select logic for control and status registers
  if(mm_regs_enabled){
    STRUCT_MM_ENTRY_NEW(MM_REGS_ADDR, mm_regs_t, mm_regs, mm_regs, addr, o.addr_is_mapped, regs_rd_data_out)
  }

  // End MMIO operation
  if(~is_START_state_reg){
    o.addr_is_mapped = 1;
    // Ending regs operation
    if(mm_type_is_regs_reg){
      o.rd_data = regs_rd_data_out_reg;
      o.valid = 1;
    }
    // End AXI0 operation
    #ifdef MMIO_AXI0_RAW_HAZZARD
    // Hazzard doesnt wait for writes to finish. Ignores/drains responses
    host_to_dev(axi_xil_mem, cpu).write.resp_ready = 1;
    #endif
    if(mmio_type_is_axi0_reg){ // TODO else if better?
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

  // Other regs
  is_START_state_reg = is_START_state;
  regs_rd_data_out_reg = regs_rd_data_out;
  mm_type_is_regs_reg = mm_type_is_regs;
  mmio_type_is_axi0_reg = mmio_type_is_axi0;

  // output the 'next' value for user memory mapped regs
  o.mm_regs_out = mm_regs;
  return o;
}

// Devices attached to the CPU interconnected in a dataflow network
// Different dataflow MAINs are needed for different clock domains

#pragma MAIN i2s_dataflow
void i2s_dataflow()
{
  // TODO bytes into byte-to-samples eth to i2c module

  // For now simple dataflow
  // RX audio samples coming out of the I2S block
  // are connected to the FFT block samples input
  samples_fifo_in = i2s_rx_samples_monitor_stream;
  // No ready, just overflows
}

#pragma MAIN fft_dataflow
void fft_dataflow()
{
  // FFT output into power computer pipeline
  sample_power_pipeline_in = output_fifo_out;
  output_fifo_out_ready = sample_power_pipeline_in_ready;
}

#pragma MAIN video_dataflow
void video_dataflow(){
  // Camera video into crop
  crop_video_in = cam_input_video_fifo_out;
  cam_input_video_fifo_out_ready = crop_video_in_ready;

  // Crop output into scale input
  scale_video_in = crop_video_out;
  crop_video_out_ready = scale_video_in_ready;

  // Scale output into position input
  fb_pos_video_in = scale_video_out;
  scale_video_out_ready = fb_pos_video_in_ready;
}
