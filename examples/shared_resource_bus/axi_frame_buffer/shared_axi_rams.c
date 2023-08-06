// Code for a single frame buffer
#include "axi_dual_port_ram.c"

// Dual frame buffers
#define N_AXI_RAMS 2
// Frame buffer RAM application/user global wires for use once anywhere in code
axi_ram_in_ports_t axi_rams_in_ports[N_AXI_RAMS][AXI_RAM_N_PORTS];
axi_ram_out_ports_t axi_rams_out_ports[N_AXI_RAMS][AXI_RAM_N_PORTS];
// Frame buffer RAMs wired to global wires
MAIN_MHZ(axi_rams, DEV_CLK_MHZ)
void axi_rams()
{
  uint32_t i;
  for (i = 0; i < N_AXI_RAMS; i+=1)
  {
    axi_ram_module_t axi_ram_o = axi_ram_module(axi_rams_in_ports[i]);
    axi_rams_out_ports[i] = axi_ram_o.axi_ram_out_ports;
  }
}

//////////////// EXPOSE DUAL FRAME BUFFERS AS SHARED RESOURCES //////////////////////
// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
#include "shared_resource_bus.h"

// Will be two instances of same type of shared resource
SHARED_BUS_TYPE_DEF(
  axi_ram_bus_t,
  axi_write_req_t,
  axi_write_data_t,
  axi_write_resp_t,
  axi_read_req_t,
  axi_read_data_t
)

// Each device is a dual port RAM used by host threads
#define NUM_DEV_PORTS AXI_RAM_N_PORTS
#define NUM_HOST_PORTS (NUM_USER_THREADS+1) // +1 for vga port display read port

// First frame buffer bus
#define SHARED_RESOURCE_BUS_NAME          axi_ram0_shared_bus
#define SHARED_RESOURCE_BUS_TYPE_NAME     axi_ram_bus_t    
#define SHARED_RESOURCE_BUS_WR_REQ_TYPE   axi_write_req_t 
#define SHARED_RESOURCE_BUS_WR_DATA_TYPE  axi_write_data_t
#define SHARED_RESOURCE_BUS_WR_RESP_TYPE  axi_write_resp_t
#define SHARED_RESOURCE_BUS_RD_REQ_TYPE   axi_read_req_t
#define SHARED_RESOURCE_BUS_RD_DATA_TYPE  axi_read_data_t   
#define SHARED_RESOURCE_BUS_HOST_PORTS    NUM_HOST_PORTS
#define SHARED_RESOURCE_BUS_HOST_CLK_MHZ  HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_DEV_PORTS     NUM_DEV_PORTS
#define SHARED_RESOURCE_BUS_DEV_CLK_MHZ   DEV_CLK_MHZ
#include "shared_resource_bus_decl.h"
// Second frame buffer bus
#define SHARED_RESOURCE_BUS_NAME          axi_ram1_shared_bus
#define SHARED_RESOURCE_BUS_TYPE_NAME     axi_ram_bus_t    
#define SHARED_RESOURCE_BUS_WR_REQ_TYPE   axi_write_req_t 
#define SHARED_RESOURCE_BUS_WR_DATA_TYPE  axi_write_data_t
#define SHARED_RESOURCE_BUS_WR_RESP_TYPE  axi_write_resp_t
#define SHARED_RESOURCE_BUS_RD_REQ_TYPE   axi_read_req_t
#define SHARED_RESOURCE_BUS_RD_DATA_TYPE  axi_read_data_t   
#define SHARED_RESOURCE_BUS_HOST_PORTS    NUM_HOST_PORTS
#define SHARED_RESOURCE_BUS_HOST_CLK_MHZ  HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_DEV_PORTS     NUM_DEV_PORTS
#define SHARED_RESOURCE_BUS_DEV_CLK_MHZ   DEV_CLK_MHZ
#include "shared_resource_bus_decl.h"

// User application uses 5 channel AXI-like shared bus wires for frame buffer control

// How RAM port is 'converted' to shared bus connection
// Multi in flight dev_ctrl
// Always ready for inputs from host
// Relies on host always being ready for output from dev
typedef struct axi_ram_port_dev_ctrl_t{
  // ex. dev inputs
  axi_ram_in_ports_t to_axi_ram;
  // Bus signals driven to host
  axi_ram_bus_t_dev_to_host_t to_host;
}axi_ram_port_dev_ctrl_t;
axi_ram_port_dev_ctrl_t axi_ram_port_dev_ctrl_pipelined(
  // Controller Inputs:
  // Ex. dev outputs
  axi_ram_out_ports_t from_axi_ram,
  // Bus signals from the host
  axi_ram_bus_t_host_to_dev_t from_host
)
{
  static uint1_t read_has_priority;
  // Choose to connect read or write sides?
  uint1_t write_start = from_host.write.req.valid & from_host.write.data.valid;
  uint1_t read_start = from_host.read.req.valid;
  uint1_t do_read;
  uint1_t do_write;
  if(read_has_priority){
    if(read_start){
      do_read = 1;
    }else if(write_start){
      do_write = 1;
    }
  }else{
    // Write has priority
    if(write_start){
      do_write = 1;
    }else if(read_start){
      do_read = 1;
    }
  }

  // Connect selected read or write signals to dev
  axi_ram_port_dev_ctrl_t o;
  if(do_read){
    // Signal ready for inputs
    o.to_host.read.req_ready = 1;
    // Drive inputs into dev
    o.to_axi_ram.addr = from_host.read.req.data.user.araddr;
    o.to_axi_ram.id = from_host.read.req.id;
    o.to_axi_ram.valid = 1;
    read_has_priority = 0;
  }else if(do_write){
    // Signal ready for inputs
    o.to_host.write.req_ready = 1;
    o.to_host.write.data_ready = 1;
    // Drive inputs into dev
    o.to_axi_ram.addr = from_host.write.req.data.user.awaddr;
    o.to_axi_ram.wr_data.data = from_host.write.data.burst.data_word.user.wdata;
    o.to_axi_ram.wr_enable = 1;
    o.to_axi_ram.id = from_host.write.req.id;
    o.to_axi_ram.valid = 1;
    read_has_priority = 1;
  }

  // Drive read and write outputs from dev
  // no flow control ready to push back on into RAM pipeline device
  // Read output data
  o.to_host.read.data.burst.data_resp.user.rdata = from_axi_ram.rd_data.data;
  o.to_host.read.data.burst.last = 1;
  o.to_host.read.data.id = from_axi_ram.id;
  o.to_host.read.data.valid = from_axi_ram.valid & !from_axi_ram.wr_enable;
  // Write output resp
  o.to_host.write.resp.data.user.bresp = 0; // Unused, TODO whatever OK is
  o.to_host.write.resp.id = from_axi_ram.id;
  o.to_host.write.resp.valid = from_axi_ram.valid & from_axi_ram.wr_enable;

  return o;
}

MAIN_MHZ(axi_ram_dev_arb_connect, DEV_CLK_MHZ)
void axi_ram_dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  SHARED_BUS_ARB_PIPELINED(axi_ram_bus_t, axi_ram0_shared_bus, NUM_DEV_PORTS)
  SHARED_BUS_ARB_PIPELINED(axi_ram_bus_t, axi_ram1_shared_bus, NUM_DEV_PORTS)

  // Connect devs to frame buffer ports
  uint32_t i;
  for (i = 0; i < NUM_DEV_PORTS; i+=1)
  {
    // First frame buffer
    axi_ram_port_dev_ctrl_t port_ctrl
      = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[0][i], axi_ram0_shared_bus_from_host[i]);
    axi_rams_in_ports[0][i] = port_ctrl.to_axi_ram;
    axi_ram0_shared_bus_to_host[i] = port_ctrl.to_host;
    // Second frame buffer
    axi_ram_port_dev_ctrl_t port_ctrl
      = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[1][i], axi_ram1_shared_bus_from_host[i]);
    axi_rams_in_ports[1][i] = port_ctrl.to_axi_ram;
    axi_ram1_shared_bus_to_host[i] = port_ctrl.to_host;
  }
}

// axi_ram_read and write
// wrappers around shared_resource_bus.h read() and write() dealing with request types etc
// Dual frame buffer is writing to one buffer while other is for reading
// These are not pipelined versions that wait for the result
axi_ram_data_t dual_axi_ram_read(uint1_t ram_sel, uint32_t addr)
{
  axi_read_req_t req;
  req.araddr = addr;
  // TODO other real axi signals
  axi_read_data_t resp;
  if(ram_sel){
   resp = axi_ram1_shared_bus_read(req);
  }else{
   resp = axi_ram0_shared_bus_read(req);
  }
  axi_ram_data_t rv;
  rv.data = resp.rdata;
  return rv;
}
void dual_axi_ram_write(uint1_t ram_sel, uint32_t addr, axi_ram_data_t data)
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
