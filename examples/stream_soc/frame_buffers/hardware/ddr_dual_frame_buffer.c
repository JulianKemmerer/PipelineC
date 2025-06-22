#include "cdc.h"
// Code for AXI xilinx memory controller shared bus resource
#include "../../shared_ddr/hardware/axi_xil_mem.c"

// Div by 2 since dual frame buffer
#if AXI_RAM_DEPTH > (XIL_MEM_32b_SIZE/2)
#error "Two AXI_RAM_DEPTH larger than XIL_MEM_32b_SIZE"
#endif

// Use upper half of addr space to look like second ram
uint32_t dual_ram_to_addr(uint1_t ram_sel, uint32_t addr)
{
  uint32_t ram_addr = addr;
  if(ram_sel){
    ram_addr = addr | ((uint32_t)1<<(XIL_MEM_ADDR_WIDTH-1)); // Set top addr bit
  }
  return ram_addr;
}
uint32_t dual_axi_ram_read(uint1_t ram_sel, uint32_t addr)
{
  uint32_t ram_addr = dual_ram_to_addr(ram_sel, addr);
  uint32_t data = axi_read(ram_addr);
  return data;
}
void dual_axi_ram_write(uint1_t ram_sel, uint32_t addr, uint32_t data)
{
  uint32_t ram_addr = dual_ram_to_addr(ram_sel, addr);
  axi_write(ram_addr, data);
}

pixel_t frame_buf_read(uint16_t x, uint16_t y)
{
  uint32_t addr = pos_to_addr(x, y);
  uint32_t data = dual_axi_ram_read(frame_buffer_read_port_sel, addr);
  pixel_t pixel;
  pixel.a = data >> (0*8);
  pixel.b = data >> (1*8);
  pixel.g = data >> (2*8);
  pixel.r = data >> (3*8);
  return pixel;
}
void frame_buf_write(uint16_t x, uint16_t y, pixel_t pixel)
{
  uint32_t data = 0;
  data |= (uint32_t)pixel.a << (0*8);
  data |= (uint32_t)pixel.b << (1*8);
  data |= (uint32_t)pixel.g << (2*8);
  data |= (uint32_t)pixel.r << (3*8);
  uint32_t addr = pos_to_addr(x, y);
  dual_axi_ram_write(!frame_buffer_read_port_sel, addr, data);
}


// Async multi in flight logic to read pixels for VGA display

// Have ~skid like FIFO to prevent DDR controller blocking front of line when flow control asserted
#include "fifo.h"
#define DDR_VGA_FIFO_DEPTH 512
FIFO_FWFT(ddr_vga_fifo, pixel_t, DDR_VGA_FIFO_DEPTH)

// Version using read priority port
MAIN_MHZ(host_vga_reader, XIL_MEM_MHZ)
void host_vga_reader()
{
  static uint1_t frame_buffer_read_port_sel_reg;

  // READ REQUEST SIDE
  // Increment VGA counters and do read for each position
  static vga_pos_t vga_pos;
  static uint16_t reads_in_flight;
  // Read and increment pos if room in fifos (cant be greedy since will 100% hog priority port)
  /* // Want to give room for all other threads * burst size  (sigh *2 sing axi ddr reads starrt eveyr other cycle)
  // So little fsm to turn off on reads in that chunk size==DDR FIFO depth
  static uint1_t reads_enabled = 1;
  uint1_t reads_enabled_next = reads_enabled;
  if(reads_in_flight >= (DDR_VGA_FIFO_DEPTH-2)){ // Sanity leave room for off by 1 or 2
    // If ~full turn off
    reads_enabled_next = 0;
  }else if(reads_in_flight==0){
    // If ~empty turn on
    reads_enabled_next = 1;
  }*/

  // Read from the current read frame buffer addr
  uint32_t addr = pos_to_addr(vga_pos.x, vga_pos.y);
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.data.user.araddr = dual_ram_to_addr(frame_buffer_read_port_sel_reg, addr);
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.data.user.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.data.user.arsize = 2; // 2^2=4 bytes per transfer
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.data.user.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.valid = (reads_in_flight <= (DDR_VGA_FIFO_DEPTH-2)); //reads_enabled;
  uint1_t do_increment = axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.valid & axi_xil_rd_pri_port_mem_dev_to_host_wire.read.req_ready;
  vga_pos = vga_frame_pos_increment(vga_pos, do_increment);
  if(do_increment){
    reads_in_flight += 1;
  }

  // READ RESPONSE SIDE
  // Get read data from the AXI RAM bus
  uint8_t data[4];
  uint1_t data_valid = 0;
  data = axi_xil_rd_pri_port_mem_dev_to_host_wire.read.data.burst.data_resp.user.rdata;
  data_valid = axi_xil_rd_pri_port_mem_dev_to_host_wire.read.data.valid;
  // Write pixel data into sync fifo
  pixel_t pixel;
  pixel.a = data[0];
  pixel.b = data[1];
  pixel.g = data[2];
  pixel.r = data[3];  
  uint1_t async_fifo_ready;
  #pragma FEEDBACK async_fifo_ready
  ddr_vga_fifo_t sync_fifo_out = ddr_vga_fifo(
    async_fifo_ready,
    pixel,
    data_valid
  );
  // Expect ready to be =1 always while running since reads_in_flight<DDR_VGA_FIFO_DEPTH
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.data_ready = sync_fifo_out.data_in_ready;
  
  
  // Pixels are read from sync fifo into async fifo
  pixel_t async_fifo_pixels[1];
  async_fifo_pixels[0] = sync_fifo_out.data_out; 
  async_fifo_ready = pmod_async_fifo_write_logic(async_fifo_pixels, sync_fifo_out.data_out_valid);
  if(async_fifo_ready & sync_fifo_out.data_out_valid){
    reads_in_flight -= 1;
  }

  // Registers
  frame_buffer_read_port_sel_reg = xil_cdc2_bit(frame_buffer_read_port_sel);
  //reads_enabled = reads_enabled_next;
}

/*
// Async multi in flight two thread with start and finish versions:
axi_shared_bus_t_read_req_t axi_xil_mem_read_only_req;
uint1_t axi_xil_mem_read_only_req_ready;
axi_shared_bus_t_read_data_t axi_xil_mem_read_only_data;
uint1_t axi_xil_mem_read_only_data_ready;
SHARED_BUS_READ_START_FINISH_DECL(
  axi_shared_bus_t,
  axi_read_req_t,
  axi_read_data_t,
  axi_xil_mem_read_only,
  axi_xil_mem_read_only_req,
  axi_xil_mem_read_only_req_ready,
  axi_xil_mem_read_only_data,
  axi_xil_mem_read_only_data_ready
)

// Wire together the separate FSMs doing start and finish
// together to look like a single host shared bus thread
#pragma MAIN read_start_finish_one_bus_connection
void read_start_finish_one_bus_connection()
{
  // TODO MACROS SHARED_BUS_READ_WIRES_CONNECT()?
  // ram0
  // Start/req
  axi_xil_mem_host_to_dev_wire_on_host_clk.read.req = axi_xil_mem_read_only_req;
  axi_xil_mem_read_only_req_ready = axi_xil_mem_dev_to_host_wire_on_host_clk.read.req_ready;
  // Finish/data
  axi_xil_mem_read_only_data = axi_xil_mem_dev_to_host_wire_on_host_clk.read.data;
  axi_xil_mem_host_to_dev_wire_on_host_clk.read.data_ready = axi_xil_mem_read_only_data_ready;
}

// HDL style version of VGA read start and finish (simple not derived FSM)
// TODO wrap into helper functions defined in shared_axi_TODO_rams.c
MAIN_MHZ(host_vga_read_starter, HOST_CLK_MHZ)
void host_vga_read_starter()
{
  // Increment VGA counters and do read for each position
  static vga_pos_t vga_pos;
  
  // Read from the current read frame buffer addr
  uint32_t addr = pos_to_addr(vga_pos.x, vga_pos.y);
  axi_xil_mem_read_only_req.data.user.araddr = dual_ram_to_addr(frame_buffer_read_port_sel, addr);
  axi_xil_mem_read_only_req.data.user.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  axi_xil_mem_read_only_req.data.user.arsize = 2; // 2^2=4 bytes per transfer
  axi_xil_mem_read_only_req.data.user.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
  axi_xil_mem_read_only_req.valid = 1;
  uint1_t do_increment = axi_xil_mem_read_only_req_ready;
  vga_pos = vga_frame_pos_increment(vga_pos, do_increment);
}
MAIN_MHZ(host_vga_read_finisher, HOST_CLK_MHZ)
void host_vga_read_finisher()
{
  // Get read data from the AXI RAM bus
  uint8_t data[4];
  uint1_t data_valid = 0;
  data = axi_xil_mem_read_only_data.burst.data_resp.user.rdata;
  data_valid = axi_xil_mem_read_only_data.valid;
  // Write pixel data into fifo
  pixel_t pixel;
  pixel.a = data[0];
  pixel.b = data[1];
  pixel.g = data[2];
  pixel.r = data[3]; 
  pixel_t pixels[1];
  pixels[0] = pixel;
  uint1_t fifo_ready = pmod_async_fifo_write_logic(pixels, data_valid);
  axi_xil_mem_read_only_data_ready = fifo_ready;
}

*/