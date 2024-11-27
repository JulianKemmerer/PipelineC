#pragma once
#include "uintN_t.h"

// https://developer.arm.com/documentation/102202/0300/Channel-signals

#define axi_id_t uint16_t // Max size=16b?
#define axi_addr_t uint32_t // Max size=64b?

#define BURST_FIXED 0 // Fixed byte lanes only defined by start address and size.
#define BURST_INCR  1 // Incrementing burst.
#define BURST_WRAP  2 // If an upper address limit is reached, the address wraps around to a lower address.

typedef struct axi32_write_req_t
{
  // Address
  //  "Write this stream to a location in memory"
  //  Must be valid before data starts
  axi_id_t awid;
  axi_addr_t awaddr; 
  uint8_t awlen; // Number of transfer cycles minus one
  uint3_t awsize; // 2^size = Transfer width in bytes
  uint2_t awburst;
  uint1_t awvalid;
}axi32_write_req_t;

typedef struct axi32_write_data_t
{
  // Data stream to be written to memory
  uint8_t wdata[4]; // 4 bytes, 32b
  uint1_t wstrb[4];
  uint1_t wlast;
  uint1_t wvalid;
}axi32_write_data_t;

typedef struct axi32_write_resp_t
{
  // Write response
  axi_id_t bid;
  uint2_t bresp; // Error code
  uint1_t bvalid;
} axi32_write_resp_t;

typedef struct axi32_write_host_to_dev_t
{
  axi32_write_req_t req;
  axi32_write_data_t data;
  //  Read to receive write responses
  uint1_t bready;
} axi32_write_host_to_dev_t;

typedef struct axi32_write_dev_to_host_t
{
  axi32_write_resp_t resp;
  //  Ready for write address
  uint1_t awready;
	//  Ready for write data 
  uint1_t wready;
} axi32_write_dev_to_host_t;

typedef struct axi32_read_req_t
{
  // Address
  //   "Give me a stream from a place in memory"
  //   Must be valid before data starts
  axi_id_t arid;
  axi_addr_t araddr;
  uint8_t arlen; // Number of transfer cycles minus one
  uint3_t arsize; // 2^size = Transfer width in bytes
  uint2_t arburst;
  uint1_t arvalid;
} axi32_read_req_t;

typedef struct axi32_read_resp_t
{
  // Read response
  axi_id_t rid;
  uint2_t rresp;
} axi32_read_resp_t;

typedef struct axi32_read_data_t
{
  // Data stream from memory
  uint8_t rdata[4]; // 4 bytes, 32b
  uint1_t rlast;
  uint1_t rvalid;
} axi32_read_data_t;

typedef struct axi32_read_host_to_dev_t
{
  axi32_read_req_t req;
  //  Ready to receive read data
  uint1_t rready;
} axi32_read_host_to_dev_t;

typedef struct axi32_read_dev_to_host_t
{
  axi32_read_resp_t resp;
  axi32_read_data_t data;
  //  Ready for read address
  uint1_t arready;
} axi32_read_dev_to_host_t;

typedef struct axi32_host_to_dev_t
{
  // Write Channel
  axi32_write_host_to_dev_t write;
  // Read Channel
  axi32_read_host_to_dev_t read;
} axi32_host_to_dev_t;

typedef struct axi32_dev_to_host_t
{
  // Write Channel
  axi32_write_dev_to_host_t write;
  // Read Channel
  axi32_read_dev_to_host_t read;
} axi32_dev_to_host_t;

// Write has two channels to begin request: address and data
// Helpr func requires that inputs are valid/held constant
// until data phase done (ready_for_inputs asserted)
typedef enum axi32_write_state_t
{
  ADDR_REQ,
  DATA_REQ,
  RESP,
}axi32_write_state_t;
typedef struct axi32_write_logic_outputs_t
{
  axi32_host_to_dev_t to_dev;
  uint2_t bresp; // Response error code
  uint1_t done;
  uint1_t ready_for_inputs;
}axi32_write_logic_outputs_t;
axi32_write_logic_outputs_t axi32_write_logic(
  uint32_t addr,
  uint32_t data,
  uint1_t ready_for_outputs,
  axi32_dev_to_host_t from_dev
){
  static axi32_write_state_t state;
  axi32_write_logic_outputs_t o;
  if(state==ADDR_REQ)
  {
    // Wait device to be ready for write address first
    if(from_dev.write.awready)
    {
      // Use inputs to form valid address
      o.to_dev.write.req.awvalid = 1;
      o.to_dev.write.req.awaddr = addr;
      o.to_dev.write.req.awid = 0; // Just one constant AXI ID for now
      o.to_dev.write.req.awlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
      o.to_dev.write.req.awsize = 2; // 2^2=4 bytes per transfer
      o.to_dev.write.req.awburst = BURST_FIXED; // Not a burst, single fixed address per transfer 
      // And then data next
      state = DATA_REQ;
    }
  }
  else if(state==DATA_REQ)
  {
    // Wait device to be ready for write data
    if(from_dev.write.wready)
    {
      // Signal finally ready for inputs since data completes write request
      o.ready_for_inputs = 1;
      // Send valid data transfer
      o.to_dev.write.data.wvalid = 1;
      // All 4 bytes are being transfered (uint to array)
      uint32_t i;
      for(i=0; i<4; i+=1)
      {
        o.to_dev.write.data.wdata[i] = data >> (i*8);
        o.to_dev.write.data.wstrb[i] = 1;
      }
      o.to_dev.write.data.wlast = 1; // 1 transfer is last one
      // And then begin waiting for response
      state = RESP;
    }
  }
  else if(state==RESP)
  {
    // Wait for this function to be ready for output
    if(ready_for_outputs)
    {
      // Then signal to device that ready for response
      o.to_dev.write.bready = 1;
      // And wait for valid output response
      if(from_dev.write.resp.bvalid)
      {
        // Done (error code not checked, just returned)
        o.done = 1;
        o.bresp = from_dev.write.resp.bresp;
        state = ADDR_REQ;
      }
    }
  }
  return o;
}

// Read is slightly simpler than write
typedef enum axi32_read_state_t
{
  REQ,
  RESP,
}axi32_read_state_t;
typedef struct axi32_read_logic_outputs_t
{
  axi32_host_to_dev_t to_dev;
  uint32_t data; // Output data
  uint2_t rresp; // Response error code
  uint1_t done;
  uint1_t ready_for_inputs;
}axi32_read_logic_outputs_t;
axi32_read_logic_outputs_t axi32_read_logic(
  uint32_t addr,
  uint1_t ready_for_outputs,
  axi32_dev_to_host_t from_dev
){
  static axi32_read_state_t state;
  axi32_read_logic_outputs_t o;
  if(state==REQ)
  {
    // Wait device to be ready for request inputs
    if(from_dev.read.arready)
    {
      // Signal function is ready for inputs
      o.ready_for_inputs = 1;
      // Use inputs to form valid request
      o.to_dev.read.req.arvalid = 1;
      o.to_dev.read.req.araddr = addr;
      o.to_dev.read.req.arid = 0; // Just one constant AXI ID for now
      o.to_dev.read.req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
      o.to_dev.read.req.arsize = 2; // 2^2=4 bytes per transfer
      o.to_dev.read.req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
      // And then begin waiting for response
      state = RESP;
    }
  }
  else if(state==RESP)
  {
    // Wait for this function to be ready for output
    if(ready_for_outputs)
    {
      // Then signal to device that ready for response
      o.to_dev.read.rready = 1;
      // And wait for valid output response
      if(from_dev.read.data.rvalid)
      {
        // Done
        // Assumed last, error code not checked, just returned
        o.done = 1;
        o.data = uint8_array4_le(from_dev.read.data.rdata); // Array to uint
        o.rresp = from_dev.read.resp.rresp;
        state = REQ;
      }
    }
  }
  return o;
}


/*
typedef struct axi512_write_resp_t
{
  //  Write response
  axi_id_t bid;
  uint2_t bresp; // Error code
  uint1_t bvalid;
} axi512_write_resp_t;

typedef struct axi512_write_ready_t
{
  //  Ready for write address
  uint1_t awready;
	//  Ready for write data 
  uint1_t wready;
} axi512_write_ready_t;

typedef struct axi512_write_o_t
{
  axi512_write_resp_t resp;
  axi512_write_ready_t ready;
} axi512_write_o_t;

typedef struct axi512_read_resp_t
{
  //  Data stream from memory
  axi_id_t rid;
  uint8_t rdata[64];
  uint2_t rresp;
  uint1_t rlast;
  uint1_t rvalid;
} axi512_read_resp_t;

typedef struct axi512_read_o_t
{
  axi512_read_resp_t resp;
  //  Ready for read address
  uint1_t arready;
} axi512_read_o_t;

//	Outputs
typedef struct axi512_o_t
{
  // Write Channel
  axi512_write_o_t write;
  
  // Read Channel
  axi512_read_o_t read;
  
} axi512_o_t;

typedef struct axi512_write_req_t
{
  //  Address
  //    "Write this stream to a location in memory"
  //    Should be valid before data starts
  axi_id_t awid;
  uint64_t awaddr;
  uint8_t awlen; // In cycles
  uint3_t awsize; // 2^size = Transfer width in bytes, 8 to 1024 bits supported
  uint1_t awvalid;
  //  Data stream to be written to memory
  uint8_t wdata[64]; // 64 bytes
  uint1_t wstrb[64];
  uint1_t wlast;
  uint1_t wvalid;
} axi512_write_req_t;

typedef struct axi512_write_i_t
{
  axi512_write_req_t req;
  //  Read to receive write responses
  uint1_t bready;
} axi512_write_i_t;

typedef struct axi512_read_req_t
{
  //  Address
  //    "Give me a stream from a place in memory"
  //    Should be valid before data starts
  axi_id_t arid;
  uint64_t araddr;
  uint8_t arlen;
  uint3_t arsize; // 2^size = Transfer width in bytes, 8 to 1024 bits supported
  uint1_t arvalid;
} axi512_read_req_t;

typedef struct axi512_read_i_t
{
  axi512_read_req_t req;
  //  Ready to receive read data
  uint1_t rready;
} axi512_read_i_t;

// 	Inputs
typedef struct axi512_i_t
{
  // Write Channel
  axi512_write_i_t write;

  // Read Channel
  axi512_read_i_t read;
  
} axi512_i_t;
*/