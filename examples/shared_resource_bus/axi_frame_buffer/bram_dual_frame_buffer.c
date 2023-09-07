#define BRAM_DEV_CLK_MHZ 100.0

#include "shared_axi_brams.c"

// Blocking sync start a read and wait for it to finish
pixel_t frame_buf_read(uint16_t x, uint16_t y)
{
  uint32_t addr = pos_to_addr(x, y);
  axi_ram_data_t read = dual_axi_ram_read(0/*frame_buffer_read_port_sel*/, addr);
  pixel_t pixel;
  pixel.a = read.data[3];
  pixel.r = read.data[2];
  pixel.g = read.data[1];
  pixel.b = read.data[0];
  return pixel;
}
void frame_buf_write(uint16_t x, uint16_t y, pixel_t pixel)
{
  axi_ram_data_t write;
  write.data[3] = pixel.a;
  write.data[2] = pixel.r;
  write.data[1] = pixel.g;
  write.data[0] = pixel.b;
  uint32_t addr = pos_to_addr(x, y);
  dual_axi_ram_write(0/*!frame_buffer_read_port_sel*/, addr, write);
}

// Async multi in flight logic to read pixels for VGA display

// Version using read priority port
MAIN_MHZ(host_vga_reader, BRAM_DEV_CLK_MHZ)
void host_vga_reader()
{
  //static uint1_t frame_buffer_read_port_sel_reg;

  // Special case for BRAM
  //  Cant push back into BRAM like can push back into DDR controller
  // So have limit, vga fifo ready means can have 1 pixel in flight
  // (1clk bram latency means 2 cycles per read, requires BRAM clock > 2*PIXEL CLOCK?)
  static uint1_t has_read_in_flight;

  // READ REQUEST SIDE
  // Increment VGA counters and do read for each position
  static vga_pos_t vga_pos;
  // Read and increment pos if room in fifos (cant be greedy since will 100% hog priority port)
  uint1_t fifo_ready;
  #pragma FEEDBACK fifo_ready
  uint32_t addr = pos_to_addr(vga_pos.x, vga_pos.y);
  axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.req.data.user.araddr = addr;
  axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.req.valid = 0;
  axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.req.data.user.araddr = addr;
  axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.req.valid = 0;
  uint1_t do_increment = 0;
  uint1_t rd_req_valid = fifo_ready & !has_read_in_flight;
  /*if(frame_buffer_read_port_sel){
    axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.req.valid = rd_req_valid;
    do_increment = rd_req_valid & axi_ram1_shared_bus_rd_pri_port_dev_to_host_wire.read.req_ready;
  }else{*/
    axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.req.valid = rd_req_valid;
    do_increment = rd_req_valid & axi_ram0_shared_bus_rd_pri_port_dev_to_host_wire.read.req_ready;
  //}
  vga_pos = vga_frame_pos_increment(vga_pos, do_increment);
  if(do_increment){
    has_read_in_flight = 1;
  }
  

  // READ RESPONSE SIDE
  // Get read data from one of the AXI RAM busses
  axi_read_data_t rd_data;
  uint1_t rd_data_valid = 0;
  uint1_t read_port_sel;
  if(axi_ram1_shared_bus_rd_pri_port_dev_to_host_wire.read.data.valid){
    rd_data = axi_ram1_shared_bus_rd_pri_port_dev_to_host_wire.read.data.burst.data_resp.user;
    rd_data_valid = 1;
    read_port_sel = 1;
  }else if(axi_ram0_shared_bus_rd_pri_port_dev_to_host_wire.read.data.valid){
    rd_data = axi_ram0_shared_bus_rd_pri_port_dev_to_host_wire.read.data.burst.data_resp.user;
    rd_data_valid = 1;
    read_port_sel = 0;
  }
  if(rd_data_valid){
    has_read_in_flight = 0;
  }

  // Write pixel data into fifo
  pixel_t pixel;
  pixel.a = rd_data.rdata[3];
  pixel.r = rd_data.rdata[2];
  pixel.g = rd_data.rdata[1];
  pixel.b = rd_data.rdata[0];
  pixel_t pixels[1];
  pixels[0] = pixel;
  uint1_t fifo_ready = pmod_async_fifo_write_logic(pixels, rd_data_valid);
  axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.data_ready = 0;
  axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.data_ready = 0;
  if(rd_data_valid){
    if(read_port_sel){
      axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.data_ready = fifo_ready;
    }else{
      axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.data_ready = fifo_ready;
    }
  }

  //frame_buffer_read_port_sel_reg = frame_buffer_read_port_sel;
}
