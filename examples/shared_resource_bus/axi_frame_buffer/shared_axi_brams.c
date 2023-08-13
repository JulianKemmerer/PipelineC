// Code for a single frame buffer
#include "axi_dual_port_bram.c"

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
