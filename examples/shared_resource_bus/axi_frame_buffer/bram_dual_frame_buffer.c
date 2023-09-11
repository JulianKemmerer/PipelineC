#define BRAM_DEV_CLK_MHZ 25.0 //100.0

#include "shared_axi_brams.c"

// Blocking sync start a read and wait for it to finish
pixel_t frame_buf_read(uint16_t x, uint16_t y)
{
  uint32_t addr = pos_to_addr(x, y);
  axi_ram_data_t read = dual_axi_ram_read(frame_buffer_read_port_sel, addr);
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
  dual_axi_ram_write(!frame_buffer_read_port_sel, addr, write);
}

// Async multi in flight logic to read pixels for VGA display

// Version using read priority port
MAIN_MHZ(host_vga_reader, BRAM_DEV_CLK_MHZ)
void host_vga_reader()
{
  static uint1_t frame_buffer_read_port_sel_reg;

  // Feedback from async pixel fifo if ready for data
  uint1_t fifo_ready;
  #pragma FEEDBACK fifo_ready

  // Special case for BRAM 1 clock pipeline without buffers or feedback built in
  //  Cant push back into BRAM like can push back into DDR controller
  //  Could add but is more complex than:
  //  A skid buffer reg to cover latency with extra buffer space
  static axi_read_data_t skid_reg;
  static uint1_t skid_reg_valid;

  // READ REQUEST SIDE
  // Increment VGA counters and do read for each position
  static vga_pos_t vga_pos;
  // Read and increment pos if room in fifos (cant be greedy since will 100% hog priority port)
  uint32_t addr = pos_to_addr(vga_pos.x, vga_pos.y);
  axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.req.data.user.araddr = addr;
  axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.req.valid = 0;
  axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.req.data.user.araddr = addr;
  axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.req.valid = 0;
  uint1_t do_increment = 0;
  uint1_t rd_req_valid = fifo_ready & !skid_reg_valid;
  if(frame_buffer_read_port_sel_reg){
    axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.req.valid = rd_req_valid;
    do_increment = rd_req_valid & axi_ram1_shared_bus_rd_pri_port_dev_to_host_wire.read.req_ready;
  }else{
    axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.req.valid = rd_req_valid;
    do_increment = rd_req_valid & axi_ram0_shared_bus_rd_pri_port_dev_to_host_wire.read.req_ready;
  }
  vga_pos = vga_frame_pos_increment(vga_pos, do_increment);
  

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

  // Data into fifo is skid data or fresh from buffer
  axi_read_data_t rd_data_into_fifo;
  uint1_t rd_data_into_fifo_valid;

  // Data from buffer?
  if(rd_data_valid)
  {
    rd_data_into_fifo = rd_data;
    rd_data_into_fifo_valid = 1;
  }
  // Skid data priority
  uint1_t data_into_fifo_is_skid;
  if(skid_reg_valid)
  {
    rd_data_into_fifo = skid_reg;
    rd_data_into_fifo_valid = 1;
    data_into_fifo_is_skid = 1;
  }

  // Write pixel data into fifo
  pixel_t pixel;
  pixel.a = rd_data_into_fifo.rdata[3];
  pixel.r = rd_data_into_fifo.rdata[2];
  pixel.g = rd_data_into_fifo.rdata[1];
  pixel.b = rd_data_into_fifo.rdata[0];
  pixel_t pixels[1];
  pixels[0] = pixel;
  uint1_t fifo_ready = pmod_async_fifo_write_logic(pixels, rd_data_into_fifo_valid);
  // Handle if and where to signal ready (clearing skid buf too)
  axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.data_ready = 0;
  axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.data_ready = 0;
  if(data_into_fifo_is_skid)
  {
    // Clear skid buf if fifo was ready for data
    if(fifo_ready){
      skid_reg_valid = 0;
    }
  }
  else
  {
    // Data coming from one of RAM ports
    // Since relying on skid buf, makes sense to always signal ready as opposed to fifo_ready
    // Since if !fifo_ready is taken in skid buffer anyway
    if(read_port_sel){
      axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire.read.data_ready = 1; //fifo_ready;
    }else{
      axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire.read.data_ready = 1; //fifo_ready;
    }
    // If fifo not ready put valid data in skid buf
    if(!fifo_ready)
    {
      skid_reg = rd_data;
      skid_reg_valid = rd_data_valid;
    }
  }
  
  frame_buffer_read_port_sel_reg = frame_buffer_read_port_sel;
}
