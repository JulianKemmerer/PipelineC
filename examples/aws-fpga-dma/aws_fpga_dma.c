#pragma once
#include "../../axi.h"

// Simple example only looks at a single cycle of AXI data
// Small DMA message (max 512b/64B)
typedef struct dma_msg_t
{
  uint8_t data[64];
  uint7_t length;
} dma_msg_t;
// Stream version for buffering
typedef struct dma_msg_s
{
  dma_msg_t data;
  uint1_t valid;
} dma_msg_s;

// Parse input AXI-4 to a message stream
dma_msg_s deserialize(axi512_i_t axi)
{
  // Init return data
  dma_msg_t msg_data;
  msg_data.length = 0;
  uint7_t i;
  for(i = 0; i < 64; i = i + 1)
  {
    msg_data.data[i] = 0;
  }
  
  // Only paying attention to write request channel (not read)
  // Also, only paying attention to data (not address)
  // since we are only using one buffer in host memory address = 0
  // And a write is always followed by a read of the same size
  
  // Convert strobe bitfield to integer length
  // And put data into output array
  
  // Writing the loop like this is the easiest to code but is slow
  // (high latency, and pretty high resource usage)
  for(i = 0; i < 64; i = i + 1)
  {
    if(axi.wstrb[i])
    {
      msg_data.data[msg_data.length] = axi.wdata[i];
      msg_data.length = msg_data.length + 1;
    }
  }
  
  // Can only look at a single cycle so must be last cycle of tranfer
  dma_msg_s msg;
  msg.data = msg_data;
  msg.valid = axi.wvalid & axi.wlast;
  return msg; 
}

// Form AXI-4 from a message stream
axi512_o_t serialize(dma_msg_s msg)
{
  axi512_o_t axi;
  
  // Message incoming is produced from DMA write
  //  DMA write needs write response
  axi.bid = 0;
  axi.bresp = 0; // Error code
  axi.bvalid = msg.valid;
  // And is output as a DMA read 
  axi.rid = 0;
  axi.rdata = msg.data.data;
  axi.rresp = 0;
  axi.rlast = 1;
  axi.rvalid = msg.valid;

  // Can't really do good flow control - yet.
  // This is hacky
  // Ready for write address
  axi.awready = 1;
	//  Ready for write data 
  axi.wready = 1;
  //  Ready for read address
  axi.arready = 1;
  
  return axi;
}

// Do work on an incoming message to form an output one
dma_msg_s work(dma_msg_s msg_in)
{
  dma_msg_s msg_out;
  msg_out.valid = msg_in.valid;
  
  // For now just copy data
  dma_msg_t msg_data;
  msg_data = msg_in.data;

  msg_out.data = msg_data;
  return msg_out;
}

// IO is mostly the PCIS AXI-4 bus
typedef struct aws_fpga_dma_inputs_t
{
  axi512_i_t pcis;
} aws_fpga_dma_inputs_t;
typedef struct aws_fpga_dma_outputs_t
{
  axi512_o_t pcis;
  uint1_t dma_wr_full; // Stop additional write transaction requests from the XDMA
  uint1_t dma_rd_full; // Stop additional read transaction requests from the XDMA
} aws_fpga_dma_outputs_t;
aws_fpga_dma_outputs_t aws_fpga_dma(aws_fpga_dma_inputs_t i)
{
  // Pull messages out of incoming DMA data
  dma_msg_s msg_in;
  msg_in = deserialize(i.pcis);
  
  // Do some work on said message to form output message
  dma_msg_s msg_out;
  msg_out = work(msg_in);
  
  // Put output message into outgoing DMA data
  aws_fpga_dma_outputs_t o;
  o.pcis = serialize(msg_out);

  // Can't really do good flow control - yet.
  // This is hacky
  // XDMA controls
  o.dma_wr_full = 0;
  o.dma_rd_full = 0;
  
  return o;
}
