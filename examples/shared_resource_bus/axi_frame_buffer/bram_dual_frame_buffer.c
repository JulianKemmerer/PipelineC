#include "shared_axi_brams.c"

#define DEV_CLK_MHZ 150.0

/* // Async pipelined start separate from finish
void frame_buf_read_start(uint16_t x, uint16_t y)
{
  uint32_t addr = pos_to_addr(x, y);
  dual_axi_ram_read_start(frame_buffer_read_port_sel, addr);
}
pixel_t frame_buf_read_finish()
{
  axi_ram_data_t read = dual_axi_ram_read_finish(frame_buffer_read_port_sel);
  pixel_t pixel;
  pixel.a = read.data[3];
  pixel.r = read.data[2];
  pixel.g = read.data[1];
  pixel.b = read.data[0];
  return pixel;
} */
/* // Read only versions for VGA port
void frame_buf_read_only_start(uint16_t x, uint16_t y)
{
  uint32_t addr = pos_to_addr(x, y);
  dual_axi_read_only_ram_read_start(frame_buffer_read_port_sel, addr);
}
pixel_t frame_buf_read_only_finish()
{
  axi_ram_data_t read = dual_axi_read_only_ram_read_finish(frame_buffer_read_port_sel);
  pixel_t pixel;
  pixel.a = read.data[3];
  pixel.r = read.data[2];
  pixel.g = read.data[1];
  pixel.b = read.data[0];
  return pixel;
}*/
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
/* Version using start then finish funcs - does work
pixel_t frame_buf_read(uint16_t x, uint16_t y)
{
  uint32_t addr = pos_to_addr(x, y);
  dual_axi_ram_read_start(frame_buffer_read_port_sel, addr);
  axi_ram_data_t read = dual_axi_ram_read_finish(frame_buffer_read_port_sel);
  pixel_t pixel;
  pixel.a = read.data[3];
  pixel.r = read.data[2];
  pixel.g = read.data[1];
  pixel.b = read.data[0];
  return pixel;
}*/
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



// Async multi in flight two thread with start and finish versions:

axi_ram_bus_t_read_req_t axi_ram0_read_req;
uint1_t axi_ram0_read_req_ready;
axi_ram_bus_t_read_data_t axi_ram0_read_data;
uint1_t axi_ram0_read_data_ready;
SHARED_BUS_READ_START_FINISH_DECL(
  axi_ram_bus_t,
  axi_read_req_t,
  axi_read_data_t,
  axi_ram0_read_only,
  axi_ram0_read_req,
  axi_ram0_read_req_ready,
  axi_ram0_read_data,
  axi_ram0_read_data_ready
)
//
axi_ram_bus_t_read_req_t axi_ram1_read_req;
uint1_t axi_ram1_read_req_ready;
axi_ram_bus_t_read_data_t axi_ram1_read_data;
uint1_t axi_ram1_read_data_ready;
SHARED_BUS_READ_START_FINISH_DECL(
  axi_ram_bus_t,
  axi_read_req_t,
  axi_read_data_t,
  axi_ram1_read_only,
  axi_ram1_read_req,
  axi_ram1_read_req_ready,
  axi_ram1_read_data,
  axi_ram1_read_data_ready
)

// Wire together the separate FSMs doing start and finish
// together to look like a single host shared bus thread
#pragma MAIN read_start_finish_one_bus_connection
void read_start_finish_one_bus_connection()
{
  // TODO MACROS SHARED_BUS_READ_WIRES_CONNECT()?
  // ram0
  // Start/req
  axi_ram0_shared_bus_host_to_dev_wire_on_host_clk.read.req = axi_ram0_read_req;
  axi_ram0_read_req_ready = axi_ram0_shared_bus_dev_to_host_wire_on_host_clk.read.req_ready;
  // Finish/data
  axi_ram0_read_data = axi_ram0_shared_bus_dev_to_host_wire_on_host_clk.read.data;
  axi_ram0_shared_bus_host_to_dev_wire_on_host_clk.read.data_ready = axi_ram0_read_data_ready;
  // ram1
  // Start/req
  axi_ram1_shared_bus_host_to_dev_wire_on_host_clk.read.req = axi_ram1_read_req;
  axi_ram1_read_req_ready = axi_ram1_shared_bus_dev_to_host_wire_on_host_clk.read.req_ready;
  // Finish/data
  axi_ram1_read_data = axi_ram1_shared_bus_dev_to_host_wire_on_host_clk.read.data;
  axi_ram1_shared_bus_host_to_dev_wire_on_host_clk.read.data_ready = axi_ram1_read_data_ready;
}

/*void dual_axi_read_only_ram_read_start(uint1_t ram_sel, uint32_t addr)
{
  axi_read_req_t req;
  req.araddr = addr;
  // TODO other real axi signals
  if(ram_sel){
    axi_ram1_read_only_read_start(req);
  }else{
    axi_ram0_read_only_read_start(req);
  }
}
axi_ram_data_t dual_axi_read_only_ram_read_finish(uint1_t first_ram_sel)
{
  // Ram select might have changed by the time the read is finished
  // doesnt matter, want the data either way
  // Keep toggling reading both busses until get response from one
  uint1_t ram_sel = first_ram_sel;
  uint1_t got_read_resp = 0;
  axi_read_data_t read_word;
  do
  {
    if(ram_sel){
      axi_ram1_read_only_read_finish_nonblocking_t 
        resp1 = axi_ram1_read_only_read_finish_nonblocking();
      read_word = resp1.data;
      got_read_resp = resp1.valid;
    }else{
      axi_ram0_read_only_read_finish_nonblocking_t
        resp0 = axi_ram0_read_only_read_finish_nonblocking();
      read_word = resp0.data;
      got_read_resp = resp0.valid;
    }
    ram_sel = !ram_sel;
  }while(!got_read_resp);
  axi_ram_data_t rv;
  rv.data = read_word.rdata;
  return rv;
}*/


/* // Pipelined versions of read and write that use 'same host thread' start and finish funcs
void dual_axi_ram_read_start(uint1_t ram_sel, uint32_t addr)
{
  axi_read_req_t req;
  req.araddr = addr;
  // TODO other real axi signals
  if(ram_sel){
    axi_ram1_shared_bus_read_start(req);
  }else{
    axi_ram0_shared_bus_read_start(req);
  }
}
axi_ram_data_t dual_axi_ram_read_finish(uint1_t first_ram_sel)
{
  // Ram select might have changed by the time the read is finished
  // doesnt matter, want the data either way
  // Keep toggling reading both busses until get response from one
  uint1_t ram_sel = first_ram_sel;
  uint1_t got_read_resp = 0;
  axi_read_data_t read_word;
  while(!got_read_resp)
  {
    if(ram_sel){
      axi_ram1_shared_bus_read_finish_nonblocking_t 
        resp1 = axi_ram1_shared_bus_read_finish_nonblocking();
      read_word = resp1.data;
      got_read_resp = resp1.valid;
    }else{
      axi_ram0_shared_bus_read_finish_nonblocking_t
        resp0 = axi_ram0_shared_bus_read_finish_nonblocking();
      read_word = resp0.data;
      got_read_resp = resp0.valid;
    }
    ram_sel = !ram_sel;
  }
  axi_ram_data_t rv;
  rv.data = read_word.rdata;
  return rv;
}*/

/*TODO WRITE START, FINISH_nonblocking
void dual_axi_ram_write_start(uint1_t ram_sel, uint32_t addr, axi_ram_data_t data)
{
  axi_write_req_t req;
  req.awaddr = addr;
  axi_write_data_t wr_data;
  wr_data.wdata = data.data;
  axi_write_resp_t resp; // dummy return resp val
  if(ram_sel){
    resp = axi_ram1_shared_bus_write(req, wr_data); 
  }else{
    resp = axi_ram0_shared_bus_write(req, wr_data);
  }
}
void dual_axi_ram_write_finish(uint1_t ram_sel, uint32_t addr, axi_ram_data_t data)
{
  axi_write_req_t req;
  req.awaddr = addr;
  axi_write_data_t wr_data;
  wr_data.wdata = data.data;
  axi_write_resp_t resp; // dummy return resp val
  if(ram_sel){
    resp = axi_ram1_shared_bus_write(req, wr_data); 
  }else{
    resp = axi_ram0_shared_bus_write(req, wr_data);
  }
}*/



/* Old not pipelined controller
typedef enum axi_ram_port_dev_ctrl_state_t
{
  REQ,
  DATA,
  WR_RESP
}axi_ram_port_dev_ctrl_state_t;
typedef struct axi_ram_port_dev_ctrl_t{
  axi_ram_in_ports_t to_axi_ram;
  axi_ram_bus_t_dev_to_host_t to_host;
}axi_ram_port_dev_ctrl_t;
axi_ram_port_dev_ctrl_t axi_ram_port_dev_ctrl(
  axi_ram_out_ports_t from_axi_ram,
  axi_ram_bus_t_host_to_dev_t from_host
)
{
  // 5 channels between host and device
  // Request to start
  //  Read req (addr)
  //  Write req (addr)
  // Exchange of data
  //  Read data+resp (data+err)
  //  Write data (data bytes)
  //  Write resp (err code)
  // Each channel has a valid+ready handshake buffer
  static axi_ram_bus_t_buffer_t bus_buffer;
  // Allow one req-data-resp in flight at a time:
  //  Wait for inputs to arrive in input handshake regs w/ things needed req/data
  //  Start operation
  //  Wait for outputs to arrive in output handshake regs, wait for handshake to complete
  static axi_ram_port_dev_ctrl_state_t state;
  static uint1_t op_is_read;
  static uint1_t read_has_priority; // Toggles for read-write sharing of bus

  // Signal ready for inputs if buffers are empty
  // Static since o.to_axi_ram written to over multiple cycles
  static axi_ram_port_dev_ctrl_t o;
  o.to_host.write.req_ready = !bus_buffer.write_req.valid;
  o.to_host.read.req_ready = !bus_buffer.read_req.valid;
  o.to_host.write.data_ready = !bus_buffer.write_data.valid;

  // Drive outputs from buffers
  o.to_host.read.data = bus_buffer.read_data;
  o.to_host.write.resp = bus_buffer.write_resp;

  // Clear output buffers when ready
  if(from_host.read.data_ready)
  {
    bus_buffer.read_data.valid = 0;
  }
  if(from_host.write.resp_ready)
  {
    bus_buffer.write_resp.valid = 0;
  }

  // State machine logic feeding signals into ram
  o.to_axi_ram.wr_data.data = bus_buffer.write_data.burst.data_word.user.wdata;
  o.to_axi_ram.wr_enable = 0;
  o.to_axi_ram.valid = 0;
  if(state==REQ)
  {
    // Wait for a request
    // Choose a request to handle, read or write
    uint1_t do_read;
    uint1_t do_write;
    if(read_has_priority)
    {
      // Read priority
      if(bus_buffer.read_req.valid)
      {
        do_read = 1;
      }
      else if(bus_buffer.write_req.valid)
      {
        do_write = 1;
      } 
    }
    else
    {
      // Write priority
      if(bus_buffer.write_req.valid)
      {
        do_write = 1;
      }
      else if(bus_buffer.read_req.valid)
      {
        do_read = 1;
      } 
    }
    if(do_read)
    {
      op_is_read = 1;
      o.to_axi_ram.addr = bus_buffer.read_req.data.user.araddr;
      bus_buffer.read_req.valid = 0; // Done w req now
      read_has_priority = 0; // Writes next
      o.to_axi_ram.valid = 1; // addr completes valid inputs, no input read data
      o.to_axi_ram.id = bus_buffer.read_req.id;
      // Waiting for output read data next
      state = DATA;
    }
    else if(do_write)
    {
      op_is_read = 0;
      o.to_axi_ram.addr = bus_buffer.write_req.data.user.awaddr;
      o.to_axi_ram.id = bus_buffer.write_req.id;
      bus_buffer.write_req.valid = 0; // Done w req now
      read_has_priority = 1; // Reads next
      // Write stil needs data still before valid input to frame buf
      state = DATA;
    }
  }
  // TODO pass through write req and data
  else if((state==DATA) & !op_is_read) // Write data into RAM
  {
    // Wait until valid write data
    if(bus_buffer.write_data.valid)
    {
      o.to_axi_ram.wr_enable = 1;
      o.to_axi_ram.valid = 1;
      // AXI3-like interleaved writes only o.to_axi_ram.id = bus_buffer.write_data.id;
      bus_buffer.write_data.valid = 0; // Done w data now
      state = WR_RESP;
    }
  }

  // RAM WAS HERE

  // Outputs from RAM flow into output handshake buffers
  if(from_axi_ram.valid)
  {
    // Have valid output, read or write?
    if(from_axi_ram.wr_enable)
    {
      // Output write resp, err code unused
      bus_buffer.write_resp.valid = 1;
      bus_buffer.write_resp.id = from_axi_ram.id;
    }
    else
    {
      // Output read data
      bus_buffer.read_data.valid = 1;
      bus_buffer.read_data.id = from_axi_ram.id;
      bus_buffer.read_data.burst.last = 1;
      bus_buffer.read_data.burst.data_resp.user.rdata = from_axi_ram.rd_data.data;
    }
  }

  // State machine logic dealing with ram output signals
  if((state==DATA) & op_is_read) // Read data out of RAM
  {
    // Wait for last valid read data outgoing to host
    if(o.to_host.read.data.valid & o.to_host.read.data.burst.last & from_host.read.data_ready) 
    {
      state = REQ;
    }
  }
  else if(state==WR_RESP)
  {
    // Wait for valid write resp outgoing to host
    if(o.to_host.write.resp.valid & from_host.write.resp_ready) 
    {
      state = REQ;
    }
  }

  // Save data into input buffers if signalling ready
  if(o.to_host.write.req_ready)
  {
    bus_buffer.write_req = from_host.write.req;
  }
  if(o.to_host.read.req_ready)
  {
    bus_buffer.read_req = from_host.read.req;
  }
  if(o.to_host.write.data_ready)
  {
    bus_buffer.write_data = from_host.write.data;
  }

  return o;
}*/



// HDL style version of VGA read start and finish (simple not derived FSM)
// TODO wrap into helper functions defined in shared_axi_rams.c
MAIN_MHZ(host_vga_read_starter, HOST_CLK_MHZ)
void host_vga_read_starter()
{
  // Increment VGA counters and do read for each position
  static vga_pos_t vga_pos;
  uint32_t addr = pos_to_addr(vga_pos.x, vga_pos.y);
  axi_ram0_read_req.data.user.araddr = addr;
  axi_ram1_read_req.data.user.araddr = addr;
  uint1_t do_increment = 0;
  // Read from the current read frame buffer
  axi_ram0_read_req.valid = 0;
  axi_ram1_read_req.valid = 0;
  if(frame_buffer_read_port_sel){
    axi_ram1_read_req.valid = 1;
    if(axi_ram1_read_req_ready){
      do_increment = 1;
    }
  }else{
    axi_ram0_read_req.valid = 1;
    if(axi_ram0_read_req_ready){
      do_increment = 1;
    }
  }
  vga_pos = vga_frame_pos_increment(vga_pos, do_increment);
}
MAIN_MHZ(host_vga_read_finisher, HOST_CLK_MHZ)
void host_vga_read_finisher()
{
  // Get read data from one of the AXI RAM busses
  static uint1_t read_port_sel;
  axi_read_data_t rd_data;
  uint1_t rd_data_valid = 0;
  if(read_port_sel){
    if(axi_ram1_read_data.valid){
      rd_data = axi_ram1_read_data.burst.data_resp.user;
      rd_data_valid = 1;
    }else{
      read_port_sel = !read_port_sel;
    }
  }else{
    if(axi_ram0_read_data.valid){
      rd_data = axi_ram0_read_data.burst.data_resp.user;
      rd_data_valid = 1;
    }else{
      read_port_sel = !read_port_sel;
    }
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
  axi_ram0_read_data_ready = 0;
  axi_ram1_read_data_ready = 0;
  if(read_port_sel){
    axi_ram1_read_data_ready = fifo_ready;
  }else{
    axi_ram0_read_data_ready = fifo_ready;
  }
}


