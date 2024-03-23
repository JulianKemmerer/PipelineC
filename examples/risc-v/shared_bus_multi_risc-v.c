#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
#include "intN_t.h"

#define CPU_CLK_MHZ 40.0
#define NUM_CORES 1

// Include instance of Xilinx DDR memory with AXI-lite compatible shared bus
#define SHARED_AXI_XIL_MEM_HOST_CLK_MHZ CPU_CLK_MHZ
#define SHARED_AXI_XIL_MEM_NUM_THREADS NUM_CORES
#include "examples/shared_resource_bus/axi_ddr/axi_xil_mem.c"

// RISC-V components
#include "risc-v.h"

// Include test gcc compiled program
#include "gcc_test/mem_init.h" // MEM_INIT,MEM_INIT_SIZE

// Declare memory map information
// Starts with shared with software memory map info
#include "gcc_test/mem_map.h" 

// Define MMIO inputs and outputs
typedef struct my_mmio_in_t{
  uint1_t button;
}my_mmio_in_t;
typedef struct my_mmio_out_t{
  uint32_t return_value;
  uint1_t halt; // return value valid
  uint1_t led;
}my_mmio_out_t;
// Define the hardware memory for those IO
RISCV_DECL_MEM_MAP_MOD_OUT_T(my_mmio_out_t)
riscv_mem_map_mod_out_t(my_mmio_out_t) my_mem_map_module(
  RISCV_MEM_MAP_MOD_INPUTS(my_mmio_in_t)
){
  // Outputs
  static riscv_mem_map_mod_out_t(my_mmio_out_t) o;
  o.addr_is_mapped = 0; // since o is static regs

  // Handshake regs
  static riscv_ram_write_req_t ram_write_req_reg;
  riscv_ram_write_req_t ram_write_req = ram_write_req_reg;
  static riscv_ram_write_resp_t ram_write_resp_reg;
  riscv_ram_write_resp_t ram_write_resp = ram_write_resp_reg;
  static riscv_ram_read_req_t ram_read_req_reg;
  riscv_ram_read_req_t ram_read_req = ram_read_req_reg;
  static riscv_ram_read_resp_t ram_read_resp_reg;
  riscv_ram_read_resp_t ram_read_resp = ram_read_resp_reg;

  // Memory muxing/select logic
  // Uses helper comparing word address and driving a variable
  WORD_MM_ENTRY(o, RETURN_OUTPUT_ADDR, o.outputs.return_value)
  o.outputs.halt = wr_byte_ens[0] & (addr==RETURN_OUTPUT_ADDR);
  WORD_MM_ENTRY(o, LED_ADDR, o.outputs.led)

  // Mem map the handshake regs
  STRUCT_MM_ENTRY(o, RAM_WR_REQ_ADDR, riscv_ram_write_req_t, ram_write_req_reg)
  STRUCT_MM_ENTRY(o, RAM_WR_RESP_ADDR, riscv_ram_write_resp_t, ram_write_resp_reg)
  STRUCT_MM_ENTRY(o, RAM_RD_REQ_ADDR, riscv_ram_read_req_t, ram_read_req_reg)
  STRUCT_MM_ENTRY(o, RAM_RD_RESP_ADDR, riscv_ram_read_resp_t, ram_read_resp_reg)

  // Handshake logic using signals from regs

  // Write start
  if(ram_write_req.valid){
    axi_write_req_t wr_req;
    wr_req.awaddr = ram_write_req.addr;
    wr_req.awlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
    wr_req.awsize = 2; // 2^2=4 bytes per transfer
    wr_req.awburst = BURST_FIXED; // Not a burst, single fixed address per transfer 
    axi_write_data_t wr_data_word;
    // All 4 bytes are being transfered (uint to array)
    uint32_t i;
    for(i=0; i<4; i+=1)
    {
      wr_data_word.wdata[i] = ram_write_req.data >> (i*8);
      wr_data_word.wstrb[i] = 1;
    }
    axi_shared_bus_t_write_start_logic_outputs_t write_start = axi_shared_bus_t_write_start_logic(
      wr_req,
      wr_data_word,
      1, // TODO always ready?
      axi_xil_mem_dev_to_host_wire_on_host_clk.write
    );
    axi_xil_mem_host_to_dev_wire_on_host_clk.write = write_start.to_dev;
    if(write_start.done){
      ram_write_req_reg.valid = 0;
    }
  }
  // Read start
  if(ram_read_req.valid){
    axi_read_req_t rd_req;
    rd_req.araddr = ram_read_req.addr;
    rd_req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
    rd_req.arsize = 2; // 2^2=4 bytes per transfer
    rd_req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
    axi_shared_bus_t_read_start_logic_outputs_t read_start = axi_shared_bus_t_read_start_logic(
      rd_req,
      1, // TODO always ready?
      axi_xil_mem_dev_to_host_wire_on_host_clk.read.req_ready
    );
    axi_xil_mem_host_to_dev_wire_on_host_clk.read.req = read_start.req;
    if(read_start.done){
      ram_read_req_reg.valid = 0;
    }
  }

  // Write Finish
  if(ram_write_resp.valid){
    if(rd_en & ADDR_IS_VALID_FLAG(addr, RAM_WR_RESP_ADDR, riscv_ram_write_resp_t)){
      ram_write_resp_reg.valid = 0;
    }
  }else{
    axi_shared_bus_t_write_finish_logic_outputs_t write_finish = axi_shared_bus_t_write_finish_logic(
      1,
      axi_xil_mem_dev_to_host_wire_on_host_clk.write
    );
    axi_xil_mem_host_to_dev_wire_on_host_clk.write = write_finish.to_dev;
    if(write_finish.done){
      ram_write_resp_reg.valid = 1;
    }
  }
  // Read finish
  if(ram_read_resp.valid){
    if(rd_en & ADDR_IS_VALID_FLAG(addr, RAM_RD_RESP_ADDR, riscv_ram_read_resp_t)){
      ram_read_resp_reg.valid = 0;
    }
  }else{
    axi_shared_bus_t_read_finish_logic_outputs_t read_finish = axi_shared_bus_t_read_finish_logic(
      1,
      axi_xil_mem_dev_to_host_wire_on_host_clk.read.data
    );
    axi_xil_mem_host_to_dev_wire_on_host_clk.read.data_ready = read_finish.data_ready;
    if(read_finish.done){
      ram_read_resp_reg.data = uint8_array4_le(read_finish.data.rdata);
      ram_read_resp_reg.valid = 1;
    }
  }
  
  return o;
}

// Declare a RISCV core type using memory info
#define riscv_name              my_riscv
#define RISCV_MEM_INIT          MEM_INIT // from gcc_test
#define RISCV_MEM_SIZE_BYTES    MEM_INIT_SIZE // from gcc_test
#define riscv_mem_map           my_mem_map_module
#define riscv_mem_map_inputs_t  my_mmio_in_t
#define riscv_mem_map_outputs_t my_mmio_out_t
#include "risc-v_decl.h"

// Set clock of CPU instances
MAIN_MHZ(risc_v_cores, CPU_CLK_MHZ)

// LEDs for demo
#include "leds/leds_port.c"

void risc_v_cores()
{
  // CPU instances
  uint32_t i;
  my_riscv_out_t out[NUM_CORES];
  for (i = 0; i < NUM_CORES; i+=1)
  {
    my_mmio_in_t in; // Disconnected for now
    out[i] = my_riscv(in);
  }

  // Temp leds from core 0 only
  static uint1_t unknown_op;
  unknown_op = unknown_op | out[0].unknown_op; // Sticky
  static uint1_t mem_out_of_range;
  mem_out_of_range = mem_out_of_range | out[0].mem_out_of_range; // Sticky
  static uint1_t halt;
  halt = halt | out[0].halt; // Sticky
  leds = 0;
  leds |= ((uint4_t)out[0].mem_map_outputs.led << 0);
  leds |= ((uint4_t)unknown_op << 1);
  leds |= ((uint4_t)mem_out_of_range << 2);
  leds |= ((uint4_t)halt << 3);
}