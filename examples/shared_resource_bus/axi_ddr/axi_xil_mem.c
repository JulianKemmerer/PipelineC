#pragma once

// Use AXI bus ports from the Xilinx Memory controller example
#include "examples/axi/axi_xil_mem.c"

// Include types for axi shared bus axi_shared_bus_t
#include "../axi_shared_bus.h"

// Decl multi host clock domain instance of shared bus axi_shared_bus_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_NAME          axi_xil_mem
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_TYPE_NAME     axi_shared_bus_t  
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_WR_REQ_TYPE   axi_write_req_t 
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_WR_DATA_TYPE  axi_write_data_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_WR_RESP_TYPE  axi_write_resp_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_RD_REQ_TYPE   axi_read_req_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_RD_DATA_TYPE  axi_read_data_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_DEV_PORTS     1
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_DEV_CLK_MHZ   XIL_MEM_MHZ
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_TOTAL_HOST_PORTS 2
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST0_NAME     cpu
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST0_PORTS    1
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST0_CLK_MHZ  6.25
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST1_NAME     i2s
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST1_PORTS    1
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST1_CLK_MHZ  22.579
#include "multi_host_clk_shared_resource_bus_decl.h"

// Connect Xilinx MIG example AXI types to shared bus AXI types
MAIN_MHZ(axi_shared_bus_dev_arb_connect, XIL_MEM_MHZ)

// Sometimes you want an special priority port, typically for reading
// ex. for streaming read data meeting a frame buffer display rate
// Global wires for the priority read port
axi_shared_bus_t_host_to_dev_t axi_xil_rd_pri_port_mem_host_to_dev_wire;
axi_shared_bus_t_dev_to_host_t axi_xil_rd_pri_port_mem_dev_to_host_wire;
void axi_shared_bus_dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  SHARED_BUS_ARB_PIPELINED(axi_shared_bus_t, axi_xil_mem, 1)

  // Middle special 2->1 arb with priority for reads on one port
  axi_shared_bus_t_dev_to_host_t rd_pri_port_arb_dev_to_host_in;
  #pragma FEEDBACK rd_pri_port_arb_dev_to_host_in
  rd_pri_port_arb_t rd_pri_arb = rd_pri_port_arb(
    axi_xil_mem_from_host[0], axi_xil_rd_pri_port_mem_host_to_dev_wire,
    rd_pri_port_arb_dev_to_host_in
  );
  axi_xil_mem_to_host[0] = rd_pri_arb.to_other_host;
  axi_xil_rd_pri_port_mem_dev_to_host_wire = rd_pri_arb.to_rd_pri_host;

  // Connect devs to frame buffer ports
  axi_shared_bus_dev_ctrl_t port_ctrl
    = axi_shared_bus_dev_ctrl_pipelined(xil_mem_to_app.axi_dev_to_host, rd_pri_arb.to_dev);
  app_to_xil_mem.axi_host_to_dev = port_ctrl.to_axi32_dev;
  rd_pri_port_arb_dev_to_host_in = port_ctrl.to_host;
}

// wrappers around shared_resource_bus.h read() and write() dealing with not-burst request types etc
uint32_t axi_read(uint32_t addr)
{
  axi_read_req_t req;
  req.araddr = addr;
  req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  req.arsize = 2; // 2^2=4 bytes per transfer
  req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
  axi_read_data_t resp;
  resp = axi_xil_mem_read(req);
  uint32_t rv = uint8_array4_le(resp.rdata);
  return rv;
}
void axi_write(uint32_t addr, uint32_t data)
{
  axi_write_req_t req;
  req.awaddr = addr;
  req.awlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  req.awsize = 2; // 2^2=4 bytes per transfer
  req.awburst = BURST_FIXED; // Not a burst, single fixed address per transfer 
  axi_write_data_t wr_data;
  // All 4 bytes are being transfered (uint to array)
  uint32_t i;
  for(i=0; i<4; i+=1)
  {
    wr_data.wdata[i] = data >> (i*8);
    wr_data.wstrb[i] = 1;
  }
  axi_write_resp_t resp; // dummy return resp val
  resp = axi_xil_mem_write(req, wr_data);
}