#pragma once
#include "uintN_t.h"

// Use AXI bus ports from the Xilinx Memory controller example
#include "axi/axi.h"
//#define axi_addr_t uint32_t
//#define axi_id_t uint16_t
#define AXI_BUS_BYTE_WIDTH 4 // 32b
#define AXI_BUS_BYTE_WIDTH_LOG2 2

// TODO combine/merged parts of #include "axi/axi.h" in this
typedef struct axi_write_req_t
{
  // Address
  //  "Write this stream to a location in memory"
  //  Must be valid before data starts
  // USE shared bus id, axi_id_t awid;
  axi_addr_t awaddr; 
  uint8_t awlen; // Number of transfer cycles minus one
  uint3_t awsize; // 2^size = Transfer width in bytes
  uint2_t awburst;
}axi_write_req_t;
typedef struct axi_write_data_t
{
  // Data stream to be written to memory
  uint8_t wdata[AXI_BUS_BYTE_WIDTH]; // 4 bytes, 32b
  uint1_t wstrb[AXI_BUS_BYTE_WIDTH];
  // USE shared bus last, uint1_t wlast;
}axi_write_data_t;
typedef struct axi_write_resp_t
{
  // Write response
  // USE shared bus id, axi_id_t bid;
  uint2_t bresp; // Error code
} axi_write_resp_t;
typedef struct axi_read_req_t
{
  // Address
  //   "Give me a stream from a place in memory"
  //   Must be valid before data starts
  // USE shared bus id, axi_id_t arid;
  axi_addr_t araddr;
  uint8_t arlen; // Number of transfer cycles minus one
  uint3_t arsize; // 2^size = Transfer width in bytes
  uint2_t arburst;
} axi_read_req_t;
/*typedef struct axi_read_resp_t
{
  // Read response
  // USE shared bus id, axi_id_t rid;
  uint2_t rresp;
} axi_read_resp_t;*/
typedef struct axi_read_data_t
{
  // Data stream from memory
  uint8_t rdata[AXI_BUS_BYTE_WIDTH]; // 4 bytes, 32b
  uint2_t rresp;
  // USE shared bus last, uint1_t rlast;
} axi_read_data_t;


// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
#include "shared_resource_bus.h"
SHARED_BUS_TYPE_DEF(
  axi_shared_bus_t,
  axi_write_req_t,
  axi_write_data_t,
  axi_write_resp_t,
  axi_read_req_t,
  axi_read_data_t
)

// How RAM port is 'converted' to shared bus connection
// Multi in flight dev_ctrl
// Always ready for inputs from host
// Relies on host always being ready for output from dev
typedef struct axi_shared_bus_dev_ctrl_t{
  // ex. dev inputs
  axi32_host_to_dev_t to_axi32_dev;
  // Bus signals driven to host
  axi_shared_bus_t_dev_to_host_t to_host;
}axi_shared_bus_dev_ctrl_t;
axi_shared_bus_dev_ctrl_t axi_shared_bus_dev_ctrl_pipelined(
  // Controller Inputs:
  // Ex. dev outputs
  axi32_dev_to_host_t from_axi32_dev,
  // Bus signals from the host
  axi_shared_bus_t_host_to_dev_t from_host
)
{
  // Is same bus just renaming struct fields/types, pass through
  axi_shared_bus_dev_ctrl_t o;
  // DATA, ID, VALID, READY
  // Read req
  o.to_axi32_dev.read.req.araddr = from_host.read.req.data.user.araddr;
  o.to_axi32_dev.read.req.arlen = from_host.read.req.data.user.arlen;
  o.to_axi32_dev.read.req.arsize = from_host.read.req.data.user.arsize;
  o.to_axi32_dev.read.req.arburst = from_host.read.req.data.user.arburst;
  o.to_axi32_dev.read.req.arid = from_host.read.req.id;
  o.to_axi32_dev.read.req.arvalid = from_host.read.req.valid;
  o.to_host.read.req_ready = from_axi32_dev.read.arready;
  // Read data/resp
  o.to_host.read.data.burst.data_resp.user.rdata = from_axi32_dev.read.data.rdata;
  o.to_host.read.data.burst.data_resp.user.rresp =  from_axi32_dev.read.resp.rresp;
  o.to_host.read.data.burst.last = from_axi32_dev.read.data.rlast;
  o.to_host.read.data.id = from_axi32_dev.read.resp.rid;
  o.to_host.read.data.valid = from_axi32_dev.read.data.rvalid;
  o.to_axi32_dev.read.rready = from_host.read.data_ready;
  // Write req
  o.to_axi32_dev.write.req.awaddr = from_host.write.req.data.user.awaddr;
  o.to_axi32_dev.write.req.awlen = from_host.write.req.data.user.awlen;
  o.to_axi32_dev.write.req.awsize = from_host.write.req.data.user.awsize;
  o.to_axi32_dev.write.req.awburst = from_host.write.req.data.user.awburst;
  o.to_axi32_dev.write.req.awid = from_host.write.req.id;
  o.to_axi32_dev.write.req.awvalid = from_host.write.req.valid;
  o.to_host.write.req_ready = from_axi32_dev.write.awready;
  // Write data
  o.to_axi32_dev.write.data.wdata = from_host.write.data.burst.data_word.user.wdata;
  o.to_axi32_dev.write.data.wstrb = from_host.write.data.burst.data_word.user.wstrb;
  o.to_axi32_dev.write.data.wlast = from_host.write.data.burst.last;
  o.to_axi32_dev.write.data.wvalid = from_host.write.data.valid;
  o.to_host.write.data_ready = from_axi32_dev.write.wready;
  // Write resp
  o.to_host.write.resp.data.user.bresp = from_axi32_dev.write.resp.bresp;
  o.to_host.write.resp.id = from_axi32_dev.write.resp.bid;
  o.to_host.write.resp.valid = from_axi32_dev.write.resp.bvalid;
  o.to_axi32_dev.write.bready = from_host.write.resp_ready;

  return o;
}

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
    o.to_dev.read.req.id = 0xFF; //SHARED_AXI_XIL_MEM_NUM_THREADS; /* Overides/ignores priority host ID value*/
    o.to_rd_pri_host.read.req_ready = from_dev.read.req_ready;
    // Switch to non priority port if run out priority requests
    // and non-priority port has pending valid req
    if(!rd_pri_from_host.read.req.valid & other_from_host.read.req.valid)
    {
      read_req_sel_pri_host = 0;
    }
  }
  else
  {
    // Uses req w ID from upstream other host
    o.to_dev.read.req = other_from_host.read.req;
    o.to_other_host.read.req_ready = from_dev.read.req_ready;
    // Switch to priority port if it requests
    // or if no more non-priority reqs
    if(rd_pri_from_host.read.req.valid | !other_from_host.read.req.valid)
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
    if(from_dev.read.data.id == 0xFF) //SHARED_AXI_XIL_MEM_NUM_THREADS)
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