// Common AXI shared bus types
#include "../axi_shared_bus.h"

// Code for a single frame buffer
#define AXI_RAM_N_PORTS 1
#include "axi_dual_port_bram.c"

// Dual frame buffers
#define N_AXI_RAMS 2
// Frame buffer RAM application/user global wires for use once anywhere in code
axi_ram_in_ports_t axi_rams_in_ports[N_AXI_RAMS][AXI_RAM_N_PORTS];
axi_ram_out_ports_t axi_rams_out_ports[N_AXI_RAMS][AXI_RAM_N_PORTS];
// Frame buffer RAMs wired to global wires
MAIN_MHZ(axi_rams, BRAM_DEV_CLK_MHZ)
void axi_rams()
{
  uint32_t i;
  for (i = 0; i < N_AXI_RAMS; i+=1)
  {
    axi_ram_module_t axi_ram_o = axi_ram_module(axi_rams_in_ports[i]);
    axi_rams_out_ports[i] = axi_ram_o.axi_ram_out_ports;
  }
}

// Each device is a dual port RAM used by host threads
#define BRAM_NUM_DEV_PORTS AXI_RAM_N_PORTS
#define BRAM_NUM_HOST_PORTS NUM_USER_THREADS

// First frame buffer bus
#define SHARED_RESOURCE_BUS_NAME          axi_ram0_shared_bus
#define SHARED_RESOURCE_BUS_TYPE_NAME     axi_shared_bus_t    
#define SHARED_RESOURCE_BUS_WR_REQ_TYPE   axi_write_req_t 
#define SHARED_RESOURCE_BUS_WR_DATA_TYPE  axi_write_data_t
#define SHARED_RESOURCE_BUS_WR_RESP_TYPE  axi_write_resp_t
#define SHARED_RESOURCE_BUS_RD_REQ_TYPE   axi_read_req_t
#define SHARED_RESOURCE_BUS_RD_DATA_TYPE  axi_read_data_t   
#define SHARED_RESOURCE_BUS_HOST_PORTS    BRAM_NUM_HOST_PORTS
#define SHARED_RESOURCE_BUS_HOST_CLK_MHZ  HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_DEV_PORTS     BRAM_NUM_DEV_PORTS
#define SHARED_RESOURCE_BUS_DEV_CLK_MHZ   BRAM_DEV_CLK_MHZ
#include "shared_resource_bus_decl.h"
// Second frame buffer bus
#define SHARED_RESOURCE_BUS_NAME          axi_ram1_shared_bus
#define SHARED_RESOURCE_BUS_TYPE_NAME     axi_shared_bus_t    
#define SHARED_RESOURCE_BUS_WR_REQ_TYPE   axi_write_req_t 
#define SHARED_RESOURCE_BUS_WR_DATA_TYPE  axi_write_data_t
#define SHARED_RESOURCE_BUS_WR_RESP_TYPE  axi_write_resp_t
#define SHARED_RESOURCE_BUS_RD_REQ_TYPE   axi_read_req_t
#define SHARED_RESOURCE_BUS_RD_DATA_TYPE  axi_read_data_t   
#define SHARED_RESOURCE_BUS_HOST_PORTS    BRAM_NUM_HOST_PORTS
#define SHARED_RESOURCE_BUS_HOST_CLK_MHZ  HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_DEV_PORTS     BRAM_NUM_DEV_PORTS
#define SHARED_RESOURCE_BUS_DEV_CLK_MHZ   BRAM_DEV_CLK_MHZ
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
  axi_shared_bus_t_dev_to_host_t to_host;
}axi_ram_port_dev_ctrl_t;
axi_ram_port_dev_ctrl_t axi_ram_port_dev_ctrl_pipelined(
  // Controller Inputs:
  // Ex. dev outputs
  axi_ram_out_ports_t from_axi_ram,
  // Bus signals from the host
  axi_shared_bus_t_host_to_dev_t from_host
)
{
  axi_ram_port_dev_ctrl_t o;

  // Avoid timing loop of write shared req+data ready logic forcing simultaneous req+data  
  // with input regs
  static axi_shared_bus_t_write_req_t wr_req;
  o.to_host.write.req_ready = !wr_req.valid;
  if(o.to_host.write.req_ready){
    wr_req = from_host.write.req;
  }
  static axi_shared_bus_t_write_data_t wr_data;
  o.to_host.write.data_ready = !wr_data.valid;
  if(o.to_host.write.data_ready){
    wr_data = from_host.write.data;
  }

  static uint1_t read_has_priority;
  // Choose to connect read or write sides?
  uint1_t write_start = wr_req.valid & wr_data.valid;
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
  if(do_read){
    // Signal ready for inputs
    o.to_host.read.req_ready = 1;
    // Drive inputs into dev
    // AXI addr is byte address, each pixel is 4 bytes
    o.to_axi_ram.addr = from_host.read.req.data.user.araddr >> AXI_BUS_BYTE_WIDTH_LOG2;
    o.to_axi_ram.id = from_host.read.req.id;
    o.to_axi_ram.valid = 1;
    read_has_priority = 0;
  }else if(do_write){
    // Ready handled via input regs
    // Drive inputs into dev
    // AXI addr is byte address, each pixel is 4 bytes
    o.to_axi_ram.addr = wr_req.data.user.awaddr >> AXI_BUS_BYTE_WIDTH_LOG2;
    o.to_axi_ram.wr_data.data = wr_data.burst.data_word.user.wdata;
    o.to_axi_ram.wr_enable = 1;
    o.to_axi_ram.id = wr_req.id;
    o.to_axi_ram.valid = 1;
    read_has_priority = 1;
    // Clear input regs now done with contents
    wr_req.valid = 0;
    wr_data.valid = 0;
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


// One read only priority port on each frame buffer RAM
// (other dev port is used normally without extra read-only arb)
// RAM0
axi_shared_bus_t_host_to_dev_t axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire;
axi_shared_bus_t_dev_to_host_t axi_ram0_shared_bus_rd_pri_port_dev_to_host_wire;
// RAM1
axi_shared_bus_t_host_to_dev_t axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire;
axi_shared_bus_t_dev_to_host_t axi_ram1_shared_bus_rd_pri_port_dev_to_host_wire;
MAIN_MHZ(axi_ram_dev_arb_connect, BRAM_DEV_CLK_MHZ)
void axi_ram_dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  SHARED_BUS_ARB_PIPELINED(axi_shared_bus_t, axi_ram0_shared_bus, BRAM_NUM_DEV_PORTS)
  SHARED_BUS_ARB_PIPELINED(axi_shared_bus_t, axi_ram1_shared_bus, BRAM_NUM_DEV_PORTS)

  // Hard coded ports for now 
  // todo reduce duplicate code by making dev port[0] always the read priority port
  #if BRAM_NUM_DEV_PORTS == 1
  // ONE DEV PORT - IT HAS READ PRIORITY MUXING
  // Connect devs to frame buffer ports
  // With special 2->1 arb with priority for reads
  
  // First frame buffer 2->1 mux
  axi_shared_bus_t_dev_to_host_t ram0_rd_pri_port_arb_dev_to_host_in;
  #pragma FEEDBACK ram0_rd_pri_port_arb_dev_to_host_in
  rd_pri_port_arb_t ram0_rd_pri_arb = rd_pri_port_arb(
    axi_ram0_shared_bus_from_host[0], axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire,
    ram0_rd_pri_port_arb_dev_to_host_in
  );
  axi_ram0_shared_bus_to_host[0] = ram0_rd_pri_arb.to_other_host;
  axi_ram0_shared_bus_rd_pri_port_dev_to_host_wire = ram0_rd_pri_arb.to_rd_pri_host;
  // First frame buffer ctrl
  axi_ram_port_dev_ctrl_t port_ctrl
    = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[0][0], ram0_rd_pri_arb.to_dev);
  axi_rams_in_ports[0][0] = port_ctrl.to_axi_ram;
  ram0_rd_pri_port_arb_dev_to_host_in = port_ctrl.to_host;
  // Second frame buffer 2->1 mux
  axi_shared_bus_t_dev_to_host_t ram1_rd_pri_port_arb_dev_to_host_in;
  #pragma FEEDBACK ram1_rd_pri_port_arb_dev_to_host_in
  rd_pri_port_arb_t ram1_rd_pri_arb = rd_pri_port_arb(
    axi_ram1_shared_bus_from_host[0], axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire,
    ram1_rd_pri_port_arb_dev_to_host_in
  );
  axi_ram1_shared_bus_to_host[0] = ram1_rd_pri_arb.to_other_host;
  axi_ram1_shared_bus_rd_pri_port_dev_to_host_wire = ram1_rd_pri_arb.to_rd_pri_host;
  // Second frame buffer
  axi_ram_port_dev_ctrl_t port_ctrl
    = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[1][0], ram1_rd_pri_arb.to_dev);
  axi_rams_in_ports[1][0] = port_ctrl.to_axi_ram;
  ram1_rd_pri_port_arb_dev_to_host_in = port_ctrl.to_host;

  #elif BRAM_NUM_DEV_PORTS == 2
  // FIRST DEV PORTs (NORMAL)
  // First frame buffer
  axi_ram_port_dev_ctrl_t port_ctrl
    = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[0][0], axi_ram0_shared_bus_from_host[0]);
  axi_rams_in_ports[0][0] = port_ctrl.to_axi_ram;
  axi_ram0_shared_bus_to_host[0] = port_ctrl.to_host;
  // Second frame buffer
  axi_ram_port_dev_ctrl_t port_ctrl
    = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[1][0], axi_ram1_shared_bus_from_host[0]);
  axi_rams_in_ports[1][0] = port_ctrl.to_axi_ram;
  axi_ram1_shared_bus_to_host[0] = port_ctrl.to_host;
  // SECOND DEV PORTs (HAS READ PRIORITY MUXING)
  // Connect devs to frame buffer ports
  // With special 2->1 arb with priority for reads
  // First frame buffer 2->1 mux
  axi_shared_bus_t_dev_to_host_t ram0_rd_pri_port_arb_dev_to_host_in;
  #pragma FEEDBACK ram0_rd_pri_port_arb_dev_to_host_in
  rd_pri_port_arb_t ram0_rd_pri_arb = rd_pri_port_arb(
    axi_ram0_shared_bus_from_host[1], axi_ram0_shared_bus_rd_pri_port_host_to_dev_wire,
    ram0_rd_pri_port_arb_dev_to_host_in
  );
  axi_ram0_shared_bus_to_host[1] = ram0_rd_pri_arb.to_other_host;
  axi_ram0_shared_bus_rd_pri_port_dev_to_host_wire = ram0_rd_pri_arb.to_rd_pri_host;
  // First frame buffer ctrl
  axi_ram_port_dev_ctrl_t port_ctrl
    = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[0][1], ram0_rd_pri_arb.to_dev);
  axi_rams_in_ports[0][1] = port_ctrl.to_axi_ram;
  ram0_rd_pri_port_arb_dev_to_host_in = port_ctrl.to_host;
  // Second frame buffer 2->1 mux
  axi_shared_bus_t_dev_to_host_t ram1_rd_pri_port_arb_dev_to_host_in;
  #pragma FEEDBACK ram1_rd_pri_port_arb_dev_to_host_in
  rd_pri_port_arb_t ram1_rd_pri_arb = rd_pri_port_arb(
    axi_ram1_shared_bus_from_host[1], axi_ram1_shared_bus_rd_pri_port_host_to_dev_wire,
    ram1_rd_pri_port_arb_dev_to_host_in
  );
  axi_ram1_shared_bus_to_host[1] = ram1_rd_pri_arb.to_other_host;
  axi_ram1_shared_bus_rd_pri_port_dev_to_host_wire = ram1_rd_pri_arb.to_rd_pri_host;
  // Second frame buffer
  axi_ram_port_dev_ctrl_t port_ctrl
    = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[1][1], ram1_rd_pri_arb.to_dev);
  axi_rams_in_ports[1][1] = port_ctrl.to_axi_ram;
  ram1_rd_pri_port_arb_dev_to_host_in = port_ctrl.to_host;
  #endif
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
