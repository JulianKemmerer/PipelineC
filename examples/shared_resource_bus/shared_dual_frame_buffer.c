// Code for a single frame buffer
#include "frame_buffer.c"

// Dual frame buffers
#define N_FRAME_BUFFERS 2
// Frame buffer RAM application/user global wires for use once anywhere in code
frame_buffer_in_ports_t frame_buffers_in_ports[N_FRAME_BUFFERS][N_FRAME_BUF_PORTS];
frame_buffer_out_ports_t frame_buffers_out_ports[N_FRAME_BUFFERS][N_FRAME_BUF_PORTS];
// Frame buffer RAMs wired to global wires
MAIN_MHZ(frame_buffer_rams, DEV_CLK_MHZ)
void frame_buffer_rams()
{
  uint32_t i;
  for (i = 0; i < N_FRAME_BUFFERS; i+=1)
  {
    frame_buf_ram_module_t frame_buf_ram_o = frame_buf_ram_module(frame_buffers_in_ports[i]);
    frame_buffers_out_ports[i] = frame_buf_ram_o.frame_buffer_out_ports;
  }
}

//////////////// EXPOSE DUAL FRAME BUFFERS AS SHARED RESOURCES //////////////////////
// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
#include "shared_resource_bus.h"

// Will be two instances of same type of shared resource
SHARED_BUS_TYPE_DEF(
  frame_buf_bus_t,
  uint32_t, n_pixels_t, uint1_t,
  uint32_t, n_pixels_t
)

// Each device is a dual port RAM used by host threads
#define NUM_DEV_PORTS N_FRAME_BUF_PORTS
#define NUM_HOST_PORTS (NUM_TOTAL_THREADS+1) // User threads + one VGA display reader thread
// First frame buffer
SHARED_BUS_DECL(
  frame_buf_bus_t,
  uint32_t, n_pixels_t, uint1_t,
  uint32_t, n_pixels_t,
  frame_buf0_shared_bus,
  NUM_HOST_PORTS,
  NUM_DEV_PORTS
)
// Second frame buffer
SHARED_BUS_DECL(
  frame_buf_bus_t,
  uint32_t, n_pixels_t, uint1_t,
  uint32_t, n_pixels_t,
  frame_buf1_shared_bus,
  NUM_HOST_PORTS,
  NUM_DEV_PORTS
)

// TODO           #include "shared_res_fifos/fifo0.h"
// When generates   #include "clock_crossing/write_req_fifo0.h"
//                  #include "clock_crossing/write_data_fifo0.h" , etc
//  COULD EVEN DO whole 'arrays' 
//  #include "shared_res_fifos/fifo[0:4].h"

// First frame buffer fifos
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 0)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 1)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 2)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 3)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 4)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 5)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 6)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 7)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 8)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 9)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 10)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 11)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 12)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 13)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 14)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 15)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf0_shared_bus, 16)
// Second frame buffer fifos
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 0)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 1)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 2)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 3)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 4)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 5)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 6)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 7)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 8)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 9)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 10)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 11)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 12)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 13)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 14)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 15)
SHARED_BUS_ASYNC_FIFO_DECL(frame_buf_bus_t, frame_buf1_shared_bus, 16)
// Wire ASYNC FIFOs to dev-host wires
MAIN_MHZ(host_side_fifo_wiring, HOST_CLK_MHZ)
void host_side_fifo_wiring()
{
  // First frame buffer
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 0)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 1)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 2)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 3)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 4)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 5)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 6)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 7)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 8)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 9)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 10)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 11)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 12)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 13)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 14)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 15)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 16)
  // Second frame buffer
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 0)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 1)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 2)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 3)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 4)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 5)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 6)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 7)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 8)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 9)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 10)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 11)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 12)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 13)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 14)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 15)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 16)
}
MAIN_MHZ(dev_side_fifo_wiring, DEV_CLK_MHZ)
void dev_side_fifo_wiring()
{
  // First frame buffer
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 0)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 1)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 2)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 3)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 4)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 5)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 6)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 7)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 8)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 9)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 10)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 11)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 12)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 13)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 14)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 15)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf0_shared_bus, 16)
  // Second frame buffer
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 0)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 1)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 2)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 3)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 4)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 5)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 6)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 7)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 8)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 9)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 10)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 11)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 12)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 13)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 14)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 15)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(frame_buf_bus_t, frame_buf1_shared_bus, 16)
}

// User application uses 5 channel AXI-like shared bus wires for frame buffer control
// Need to wire up RAM with AXI style req,resp which uses valid ready
// resp/req/data channels are independent

// TODO what kind of helper funcs are good for generic support connecting to bus?

// How frame buffer port is 'converted' to shared bus connection
typedef enum frame_buf_ram_port_dev_ctrl_state_t
{
  REQ,
  DATA,
  WR_RESP
}frame_buf_ram_port_dev_ctrl_state_t;
typedef struct frame_buf_ram_port_dev_ctrl_t{
  frame_buffer_in_ports_t to_frame_buf;
  frame_buf_bus_t_dev_to_host_t to_host;
}frame_buf_ram_port_dev_ctrl_t;
frame_buf_ram_port_dev_ctrl_t frame_buf_ram_port_dev_ctrl(
  frame_buffer_out_ports_t from_frame_buf,
  frame_buf_bus_t_host_to_dev_t from_host
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
  static frame_buf_bus_t_buffer_t bus_buffer;
  // Allow one req-data-resp in flight at a time:
  //  Wait for inputs to arrive in input handshake regs w/ things needed req/data
  //  Start operation
  //  Wait for outputs to arrive in output handshake regs, wait for handshake to complete
  static frame_buf_ram_port_dev_ctrl_state_t state;
  static uint1_t op_is_read;
  static uint1_t read_has_priority; // Toggles for read-write sharing of bus

  // Signal ready for inputs if buffers are empty
  // Static since o.to_frame_buf written to over multiple cycles
  static frame_buf_ram_port_dev_ctrl_t o;
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
  o.to_frame_buf.wr_data = bus_buffer.write_data.burst.data_word.user;
  o.to_frame_buf.wr_enable = 0;
  o.to_frame_buf.valid = 0;
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
      o.to_frame_buf.addr = bus_buffer.read_req.data.user;
      bus_buffer.read_req.valid = 0; // Done w req now
      read_has_priority = 0; // Writes next
      o.to_frame_buf.valid = 1; // addr completes valid inputs, no input read data
      o.to_frame_buf.id = bus_buffer.read_req.id;
      // Waiting for output read data next
      state = DATA;
    }
    else if(do_write)
    {
      op_is_read = 0;
      o.to_frame_buf.addr = bus_buffer.write_req.data.user;
      o.to_frame_buf.id = bus_buffer.write_req.id;
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
      o.to_frame_buf.wr_enable = 1;
      o.to_frame_buf.valid = 1;
      // AXI3-like interleaved writes only o.to_frame_buf.id = bus_buffer.write_data.id;
      bus_buffer.write_data.valid = 0; // Done w data now
      state = WR_RESP;
    }
  }

  // RAM WAS HERE

  // Outputs from RAM flow into output handshake buffers
  if(from_frame_buf.valid)
  {
    // Have valid output, read or write?
    if(from_frame_buf.wr_enable)
    {
      // Output write resp, err code unused
      bus_buffer.write_resp.valid = 1;
      bus_buffer.write_resp.id = from_frame_buf.id;
    }
    else
    {
      // Output read data
      bus_buffer.read_data.valid = 1;
      bus_buffer.read_data.id = from_frame_buf.id;
      bus_buffer.read_data.burst.last = 1;
      bus_buffer.read_data.burst.data_resp.user = from_frame_buf.rd_data;
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
}

MAIN_MHZ(frame_buf_ram_dev_arb_connect, DEV_CLK_MHZ)
void frame_buf_ram_dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  SHARED_BUS_ARB(frame_buf_bus_t, frame_buf0_shared_bus, NUM_DEV_PORTS)
  SHARED_BUS_ARB(frame_buf_bus_t, frame_buf1_shared_bus, NUM_DEV_PORTS)

  // Connect devs to frame buffer ports
  uint32_t i;
  for (i = 0; i < NUM_DEV_PORTS; i+=1)
  {
    // First frame buffer
    frame_buf_ram_port_dev_ctrl_t port_ctrl
      = frame_buf_ram_port_dev_ctrl(frame_buffers_out_ports[0][i], frame_buf0_shared_bus_from_host[i]);
    frame_buffers_in_ports[0][i] = port_ctrl.to_frame_buf;
    frame_buf0_shared_bus_to_host[i] = port_ctrl.to_host;
    // Second frame buffer
    frame_buf_ram_port_dev_ctrl_t port_ctrl
      = frame_buf_ram_port_dev_ctrl(frame_buffers_out_ports[1][i], frame_buf1_shared_bus_from_host[i]);
    frame_buffers_in_ports[1][i] = port_ctrl.to_frame_buf;
    frame_buf1_shared_bus_to_host[i] = port_ctrl.to_host;
  }
}

// frame_buf_read and write
// wrappers around shared_resource_bus.h read() and write() dealing with request types etc
// Dual frame buffer is writing to one buffer while other is for reading
uint1_t frame_buffer_read_port_sel;
n_pixels_t dual_frame_buf_read(uint16_t x_buffer_index, uint16_t y)
{
  //__clk();
  uint32_t addr = pos_to_addr(x_buffer_index, y);
  n_pixels_t resp;
  if(frame_buffer_read_port_sel){
    resp = frame_buf1_shared_bus_read(addr);
  }else{
    resp = frame_buf0_shared_bus_read(addr);
  }
  return resp;
}
void dual_frame_buf_write(uint16_t x_buffer_index, uint16_t y, n_pixels_t wr_data)
{
  //__clk();
  uint32_t addr = pos_to_addr(x_buffer_index, y);
  uint1_t resp; // dummy return resp val
  if(!frame_buffer_read_port_sel){
    resp = frame_buf1_shared_bus_write(addr, wr_data); 
  }else{
    resp = frame_buf0_shared_bus_write(addr, wr_data);
  } 
}

// Always-reading logic to drive VGA signal into pmod_async_fifo_write
void host_vga_reader()
{
  vga_pos_t vga_pos;
  while(1)
  {
    // Read the pixels at x,y pos
    uint16_t x_buffer_index = vga_pos.x >> RAM_PIXEL_BUFFER_SIZE_LOG2;
    n_pixels_t pixels = dual_frame_buf_read(x_buffer_index, vga_pos.y);
    
    // Default black=0 unless pixel is white=1
    pixel_t colors[RAM_PIXEL_BUFFER_SIZE];
    uint32_t i;
    for(i = 0; i < RAM_PIXEL_BUFFER_SIZE; i+=1)
    {
      if(pixels.data[i])
      {
        colors[i].r = 255;
        colors[i].g = 255;
        colors[i].b = 255;
      }
      else
      {
        colors[i].r = 0;
        colors[i].g = 0;
        colors[i].b = 0;
      }
    }
   
    // Write it into async fifo feeding vga pmod for display
    pmod_async_fifo_write(colors);

    // Execute a cycle of vga timing to get x,y and increment for next time
    vga_pos = vga_frame_pos_increment(vga_pos, RAM_PIXEL_BUFFER_SIZE);
  }
}
// Wrap up FSM as top level
#include "host_vga_reader_FSM.h"
MAIN_MHZ(host_vga_reader_wrapper, HOST_CLK_MHZ)
void host_vga_reader_wrapper()
{
  host_vga_reader_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  host_vga_reader_OUTPUT_t o = host_vga_reader_FSM(i);
}