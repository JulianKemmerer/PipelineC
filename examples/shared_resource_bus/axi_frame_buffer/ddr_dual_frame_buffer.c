// Code for AXI xilinx memory controller shared bus resource

// Use a read priority port on arbiter (ifndef then use slow greedy arb where vga port can be greedy)
#define AXI_XIL_MEM_RD_PRI_PORT

/* VGA prot is priority read port*/
/* +1 for vga port display read port if including in greedy arb*/
#ifdef AXI_XIL_MEM_RD_PRI_PORT
#define NUM_HOST_PORTS                  NUM_USER_THREADS 
#else
#define NUM_HOST_PORTS                  (NUM_USER_THREADS+1) 
#endif
#define SHARED_AXI_XIL_MEM_NUM_THREADS  NUM_HOST_PORTS 
#define SHARED_AXI_XIL_MEM_HOST_CLK_MHZ HOST_CLK_MHZ
#include "examples/shared_resource_bus/axi_ddr/axi_xil_mem.c"

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
  pixel.r = data >> (1*8);
  pixel.g = data >> (2*8);
  pixel.b = data >> (3*8);
  return pixel;
}
void frame_buf_write(uint16_t x, uint16_t y, pixel_t pixel)
{
  uint32_t data = 0;
  data |= (uint32_t)pixel.a << (0*8);
  data |= (uint32_t)pixel.r << (1*8);
  data |= (uint32_t)pixel.g << (2*8);
  data |= (uint32_t)pixel.b << (3*8);
  uint32_t addr = pos_to_addr(x, y);
  dual_axi_ram_write(!frame_buffer_read_port_sel, addr, data);
}


// Async multi in flight logic to read pixels for VGA display

#ifdef AXI_XIL_MEM_RD_PRI_PORT
// Version using read priority port
MAIN_MHZ(host_vga_reader, XIL_MEM_MHZ)
void host_vga_reader()
{
  static uint1_t frame_buffer_read_port_sel_reg;

  // READ REQUEST SIDE
  // Increment VGA counters and do read for each position
  static vga_pos_t vga_pos;
  // Read and increment pos if room in fifos (cant be greedy since will 100% hog priority port)
  uint1_t fifo_ready;
  #pragma FEEDBACK fifo_ready
  // Read from the current read frame buffer addr
  uint32_t addr = pos_to_addr(vga_pos.x, vga_pos.y);
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.data.user.araddr = dual_ram_to_addr(frame_buffer_read_port_sel_reg, addr);
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.data.user.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.data.user.arsize = 2; // 2^2=4 bytes per transfer
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.data.user.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.req.valid = fifo_ready;
  uint1_t do_increment = fifo_ready & axi_xil_rd_pri_port_mem_dev_to_host_wire.read.req_ready;
  vga_pos = vga_frame_pos_increment(vga_pos, do_increment);

  // READ RESPONSE SIDE
  // Get read data from the AXI RAM bus
  uint8_t data[4];
  uint1_t data_valid = 0;
  data = axi_xil_rd_pri_port_mem_dev_to_host_wire.read.data.burst.data_resp.user.rdata;
  data_valid = axi_xil_rd_pri_port_mem_dev_to_host_wire.read.data.valid;
  // Write pixel data into fifo
  pixel_t pixel;
  pixel.a = data[0];
  pixel.r = data[1];
  pixel.g = data[2];
  pixel.b = data[3];
  pixel_t pixels[1];
  pixels[0] = pixel;
  fifo_ready = pmod_async_fifo_write_logic(pixels, data_valid);
  axi_xil_rd_pri_port_mem_host_to_dev_wire.read.data_ready = fifo_ready;

  frame_buffer_read_port_sel_reg = frame_buffer_read_port_sel;
}
#else
// Version trying to act as a greedy host among the others 
MAIN_MHZ(host_vga_reader, HOST_CLK_MHZ)
void host_vga_reader()
{
  // READ REQUEST SIDE
  // Increment VGA counters and do read for each position
  static vga_pos_t vga_pos;
  // Read from the current read frame buffer addr
  uint32_t addr = pos_to_addr(vga_pos.x, vga_pos.y);
  axi_xil_mem_host_to_dev_wire_on_host_clk.read.req.data.user.araddr = dual_ram_to_addr(frame_buffer_read_port_sel, addr);
  axi_xil_mem_host_to_dev_wire_on_host_clk.read.req.data.user.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  axi_xil_mem_host_to_dev_wire_on_host_clk.read.req.data.user.arsize = 2; // 2^2=4 bytes per transfer
  axi_xil_mem_host_to_dev_wire_on_host_clk.read.req.data.user.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
  axi_xil_mem_host_to_dev_wire_on_host_clk.read.req.valid = 1;
  uint1_t do_increment = axi_xil_mem_dev_to_host_wire_on_host_clk.read.req_ready;
  vga_pos = vga_frame_pos_increment(vga_pos, do_increment);

  // READ RESPONSE SIDE
  // Get read data from the AXI RAM bus
  uint8_t data[4];
  uint1_t data_valid = 0;
  data = axi_xil_mem_dev_to_host_wire_on_host_clk.read.data.burst.data_resp.user.rdata;
  data_valid = axi_xil_mem_dev_to_host_wire_on_host_clk.read.data.valid;
  // Write pixel data into fifo
  pixel_t pixel;
  pixel.a = data[0];
  pixel.r = data[1];
  pixel.g = data[2];
  pixel.b = data[3];
  pixel_t pixels[1];
  pixels[0] = pixel;
  uint1_t fifo_ready = pmod_async_fifo_write_logic(pixels, data_valid);
  axi_xil_mem_host_to_dev_wire_on_host_clk.read.data_ready = fifo_ready;
}
#endif

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
  pixel.r = data[1];
  pixel.g = data[2];
  pixel.b = data[3];
  pixel_t pixels[1];
  pixels[0] = pixel;
  uint1_t fifo_ready = pmod_async_fifo_write_logic(pixels, data_valid);
  axi_xil_mem_read_only_data_ready = fifo_ready;
}

*/