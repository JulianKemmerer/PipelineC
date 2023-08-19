#pragma once

// Use AXI bus ports from the Xilinx Memory controller example
#include "examples/axi/axi_xil_mem.c"

// Include types for axi shared bus axi_shared_bus_t
#include "../axi_shared_bus.h"
#ifndef SHARED_AXI_XIL_MEM_HOST_CLK_MHZ
#define SHARED_AXI_XIL_MEM_HOST_CLK_MHZ   XIL_MEM_MHZ
#endif
#ifndef SHARED_AXI_XIL_MEM_NUM_THREADS
#define SHARED_AXI_XIL_MEM_NUM_THREADS   1
#endif
// Decl instance of shared bus axi_shared_bus_t
#define SHARED_RESOURCE_BUS_NAME          axi_xil_mem
#define SHARED_RESOURCE_BUS_TYPE_NAME     axi_shared_bus_t  
#define SHARED_RESOURCE_BUS_WR_REQ_TYPE   axi_write_req_t 
#define SHARED_RESOURCE_BUS_WR_DATA_TYPE  axi_write_data_t
#define SHARED_RESOURCE_BUS_WR_RESP_TYPE  axi_write_resp_t
#define SHARED_RESOURCE_BUS_RD_REQ_TYPE   axi_read_req_t
#define SHARED_RESOURCE_BUS_RD_DATA_TYPE  axi_read_data_t   
#define SHARED_RESOURCE_BUS_HOST_PORTS    SHARED_AXI_XIL_MEM_NUM_THREADS
#define SHARED_RESOURCE_BUS_HOST_CLK_MHZ  SHARED_AXI_XIL_MEM_HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_DEV_PORTS     1
#define SHARED_RESOURCE_BUS_DEV_CLK_MHZ   XIL_MEM_MHZ
#include "shared_resource_bus_decl.h" // TODO make helper axi_shared_resource_bus_decl.h?

// Connect Xilinx MIG example AXI types to shared bus AXI types

// Sometimes you want an special priority port, typically for reading
// ex. for streaming read data meeting a frame buffer display rate
#ifdef AXI_XIL_MEM_RD_PRI_PORT
// Logic for read priority arbitration
typedef struct rd_pri_port_arb_t{
  axi_shared_bus_t_dev_to_host_t to_other_host;
  axi_shared_bus_t_dev_to_host_t to_rd_pri_host;
  axi_shared_bus_t_host_to_dev_t to_dev;
}rd_pri_port_arb_t;
rd_pri_port_arb_t rd_pri_port_arb(
  axi_shared_bus_t_host_to_dev_t other_from_host,
  axi_shared_bus_t_host_to_dev_t rd_pri_from_host,
  axi_shared_bus_t_dev_to_host_t from_dev
){
  // Special case adapted from dev_arb_pipelined() func from shared_resource_bus.h
  
  /* 5 channels between each host and device*/
  /* Request to start*/
  /*  Read req (addr)*/
  /*  Write req (addr)*/
  /* Exchange of data*/
  /*  Read data+resp (data+err)*/
  /*  Write data (data bytes)*/
  /*  Write resp (err code)*/
  /* Each channel has a valid+ready handshake */

  /* Output signal*/
  rd_pri_port_arb_t o; /*Default all zeros single cycle pulses*/
  
  /* Each dev port prioritizes/selects a specific host bus for input into device*/
  static uint1_t read_req_sel_pri_host = 1;

  /* Each dev port has FIFOs so will allow 'streaming' multiple read/write in flight*/

  /* INPUT TO DEV SIDE*/

  // Read side muxing
  if(read_req_sel_pri_host)
  {
    o.to_dev.read.req = rd_pri_from_host.read.req;
    // Priority ID one more than regular ids used by axi_xil_mem 
    o.to_dev.read.req.id = SHARED_AXI_XIL_MEM_NUM_THREADS; /* Overides/ignores priority host ID value*/
    o.to_rd_pri_host.read.req_ready = from_dev.read.req_ready;
    // Switch to non priority port if run out priority requests
    if(!rd_pri_from_host.read.req.valid)
    {
      read_req_sel_pri_host = 0;
    }
  }
  else
  {
    // Uses while req w ID from upstream other host
    o.to_dev.read.req = other_from_host.read.req;
    o.to_other_host.read.req_ready = from_dev.read.req_ready;
    // Switch to priority port if it requests
    if(rd_pri_from_host.read.req.valid)
    {
      read_req_sel_pri_host = 1;
    }
  }
  // Write input side is always connected to other host (priority port is read only)
  o.to_dev.write.req = other_from_host.write.req;
  o.to_other_host.write.req_ready = from_dev.write.req_ready;
  //
  o.to_dev.write.data = other_from_host.write.data;
  o.to_other_host.write.data_ready = from_dev.write.data_ready;

  /* DEV WAS HERE*/

  /* Outputs from DEV is muxed into output fifos based on ID=host port*/
  // ONLY FOR READ SIDE
  /* Output read data*/
  if(from_dev.read.data.valid)
  {
    if(from_dev.read.data.id == SHARED_AXI_XIL_MEM_NUM_THREADS)
    {
      // Priority read
      o.to_rd_pri_host.read.data = from_dev.read.data;
      o.to_dev.read.data_ready = rd_pri_from_host.read.data_ready;
    }
    else
    {
      // Other
      o.to_other_host.read.data = from_dev.read.data;
      o.to_dev.read.data_ready = other_from_host.read.data_ready;
    }
  }
  /* Output write resp, err code unused*/
  // WRITE SIDE DIRECTLY CONNECTED
  o.to_other_host.write.resp = from_dev.write.resp;
  o.to_dev.write.resp_ready = other_from_host.write.resp_ready;
  
  return o;
}
// Global wires for the priority read port
axi_shared_bus_t_host_to_dev_t axi_xil_rd_pri_port_mem_host_to_dev_wire;
axi_shared_bus_t_dev_to_host_t axi_xil_rd_pri_port_mem_dev_to_host_wire;
MAIN_MHZ(axi_shared_bus_dev_arb_connect, XIL_MEM_MHZ)
void axi_shared_bus_dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  SHARED_BUS_ARB_PIPELINED(axi_shared_bus_t, axi_xil_mem, 1) // Not greedy

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
#else
// Regular greedy arb to allow VGA read port to be greedy
void axi_shared_bus_dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  SHARED_BUS_ARB_PIPELINED_GREEDY(axi_shared_bus_t, axi_xil_mem, 1)
  // Connect devs to frame buffer ports
  axi_shared_bus_dev_ctrl_t port_ctrl
    = axi_shared_bus_dev_ctrl_pipelined(xil_mem_to_app.axi_dev_to_host, axi_xil_mem_from_host[0]);
  app_to_xil_mem.axi_host_to_dev = port_ctrl.to_axi32_dev;
  axi_xil_mem_to_host[0] = port_ctrl.to_host;
}
#endif

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