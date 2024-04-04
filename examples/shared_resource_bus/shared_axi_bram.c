// TODO can this header be made into a library for making BRAMs on shared resource buses?

// Common AXI shared bus code
#include "axi_shared_bus.h"

/////////////////// GENERIC AXI-like RAM ///////////////////////////////////
// Assumes (todo REQUIRE) that shared resource bus output response FIFOs are used and always ready
// (since didnt implement flow control push back through RAM path yet)
#define SHARED_AXI_RAM_N_DEV_PORTS 1

// Declare dual port RAM
// Easiest to match AXI bus width
typedef struct axi_ram_data_t{
  uint8_t data[AXI_BUS_BYTE_WIDTH];
}axi_ram_data_t;

// The RAM with two ports
#if SHARED_AXI_RAM_N_DEV_PORTS == 2
#include "ram.h"
DECL_RAM_DP_RW_RW_1(
  axi_ram_data_t,
  axi_ram,
  SHARED_AXI_RAM_DEPTH,
  "(others => (others => (others => (others => '0'))))"
)
#endif
//  Inputs
typedef struct axi_ram_in_ports_t{
  axi_ram_data_t wr_data;
  uint32_t addr;
  uint1_t wr_enable; // 0=read
  uint8_t id;
  uint1_t valid;
}axi_ram_in_ports_t;
//  Outputs
typedef struct axi_ram_out_ports_t{
  axi_ram_data_t rd_data;
  uint1_t wr_enable; // 0=read
  uint8_t id;
  uint1_t valid;
}axi_ram_out_ports_t;

typedef struct axi_ram_module_t
{
  axi_ram_out_ports_t axi_ram_out_ports[SHARED_AXI_RAM_N_DEV_PORTS];
}axi_ram_module_t;
axi_ram_module_t axi_ram_module(axi_ram_in_ports_t axi_ram_in_ports[SHARED_AXI_RAM_N_DEV_PORTS])
{
  axi_ram_module_t o;
  // 1 cycle of delay regs for ID field not included in RAM macro func
  static uint8_t id_reg[SHARED_AXI_RAM_N_DEV_PORTS];

  // Do RAM lookup
  #if SHARED_AXI_RAM_N_DEV_PORTS == 2
  axi_ram_outputs_t axi_ram_outputs = axi_ram(
    axi_ram_in_ports[0].addr, axi_ram_in_ports[0].wr_data, axi_ram_in_ports[0].wr_enable, axi_ram_in_ports[0].valid,
    axi_ram_in_ports[1].addr, axi_ram_in_ports[1].wr_data, axi_ram_in_ports[1].wr_enable, axi_ram_in_ports[1].valid
  );
  // User output signals
  o.axi_ram_out_ports[0].rd_data = axi_ram_outputs.rd_data0;
  o.axi_ram_out_ports[0].wr_enable = axi_ram_outputs.wr_en0;
  o.axi_ram_out_ports[0].id = id_reg[0];
  o.axi_ram_out_ports[0].valid = axi_ram_outputs.valid0;
  //
  o.axi_ram_out_ports[1].rd_data = axi_ram_outputs.rd_data1;
  o.axi_ram_out_ports[1].wr_enable = axi_ram_outputs.wr_en1;
  o.axi_ram_out_ports[1].id = id_reg[1];
  o.axi_ram_out_ports[1].valid = axi_ram_outputs.valid1;

  #elif SHARED_AXI_RAM_N_DEV_PORTS == 1
  static axi_ram_data_t axi_ram[SHARED_AXI_RAM_DEPTH];
  static uint1_t valid_reg;
  static uint1_t we_reg;
  axi_ram_data_t rdata = axi_ram_RAM_SP_RF_1(axi_ram_in_ports[0].addr, axi_ram_in_ports[0].wr_data, axi_ram_in_ports[0].valid & axi_ram_in_ports[0].wr_enable);
  // output signals
  o.axi_ram_out_ports[0].rd_data = rdata;
  o.axi_ram_out_ports[0].wr_enable = we_reg;
  o.axi_ram_out_ports[0].id = id_reg[0];
  o.axi_ram_out_ports[0].valid = valid_reg;
  // regs
  valid_reg = axi_ram_in_ports[0].valid;
  we_reg = axi_ram_in_ports[0].wr_enable;
  #endif

  // ID delay reg
  uint32_t i;
  for (i = 0; i < SHARED_AXI_RAM_N_DEV_PORTS; i+=1)
  {
    id_reg[i] = axi_ram_in_ports[i].id;
  }

  return o;
}


// Instance of the RAM
// RAM application/user global wires for use once anywhere in code
axi_ram_in_ports_t axi_rams_in_ports[SHARED_AXI_RAM_N_DEV_PORTS];
axi_ram_out_ports_t axi_rams_out_ports[SHARED_AXI_RAM_N_DEV_PORTS];
// Frame buffer RAMs wired to global wires
MAIN_MHZ(axi_rams, SHARED_AXI_RAM_DEV_CLK_MHZ)
void axi_rams()
{
  axi_ram_module_t axi_ram_o = axi_ram_module(axi_rams_in_ports);
  axi_rams_out_ports = axi_ram_o.axi_ram_out_ports;
}


// Bus to share the RAM instance
#define SHARED_RESOURCE_BUS_NAME          shared_axi_ram
#define SHARED_RESOURCE_BUS_TYPE_NAME     axi_shared_bus_t    
#define SHARED_RESOURCE_BUS_WR_REQ_TYPE   axi_write_req_t 
#define SHARED_RESOURCE_BUS_WR_DATA_TYPE  axi_write_data_t
#define SHARED_RESOURCE_BUS_WR_RESP_TYPE  axi_write_resp_t
#define SHARED_RESOURCE_BUS_RD_REQ_TYPE   axi_read_req_t
#define SHARED_RESOURCE_BUS_RD_DATA_TYPE  axi_read_data_t   
#define SHARED_RESOURCE_BUS_HOST_PORTS    SHARED_AXI_RAM_NUM_HOST_PORTS
#define SHARED_RESOURCE_BUS_HOST_CLK_MHZ  SHARED_AXI_RAM_HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_DEV_PORTS     SHARED_AXI_RAM_N_DEV_PORTS
#define SHARED_RESOURCE_BUS_DEV_CLK_MHZ   SHARED_AXI_RAM_DEV_CLK_MHZ
#include "shared_resource_bus_decl.h"

// User application uses 5 channel AXI-like shared bus wires for RAM control

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

  // Avoid timing loop of write shared req+data ready logic forcing simultaneous req+data with input regs  
  // TODO CHANGED ARB SO SHOULDNT NEED WRITE INPUT REGS ANYMORE
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


// Connect RAM instance to shared bus via arbitration modules
MAIN_MHZ(axi_ram_dev_arb_connect, SHARED_AXI_RAM_DEV_CLK_MHZ)
void axi_ram_dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  SHARED_BUS_ARB_PIPELINED(axi_shared_bus_t, shared_axi_ram, SHARED_AXI_RAM_N_DEV_PORTS)

  // Each device/RAM port gets a ctrl module
  uint32_t i;
  for (i = 0; i < SHARED_AXI_RAM_N_DEV_PORTS; i+=1)
  {
    axi_ram_port_dev_ctrl_t port_ctrl
      = axi_ram_port_dev_ctrl_pipelined(axi_rams_out_ports[i], shared_axi_ram_from_host[i]);
    axi_rams_in_ports[i] = port_ctrl.to_axi_ram;
    shared_axi_ram_to_host[i] = port_ctrl.to_host;
  }
}