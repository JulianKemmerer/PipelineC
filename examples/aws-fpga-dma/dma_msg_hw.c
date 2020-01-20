// Code wrapping AXI4 (FPGA) hardware to a common 'DMA message' 

#pragma once
#include "../../axi.h"
#include "dma_msg.h"

// !!!!!!!  WARNING: !!!!!!!!!!!
//		THIS IMPLEMENTATION DOES NOT HAVE FLOW CONTROL LOGIC.
//		ASSUMES ALWAYS READY FOR INPUT AND OUTPUT.

// Simple example only looks at a single cycle of AXI data
// Small DMA message (max 512b/64B)
// Outputs/reads are limited to 64B so inputs/writes are hard coded to match

// Parse input AXI-4 to a message stream
dma_msg_s deserialize(axi512_i_t axi)
{
	// Only paying attention to write request channel data (not address)
  // since we are only using one buffer in host memory address = 0
  // And a write is always followed by a read of the same size
	
	// Message is just the 64B of AXI4 data
  dma_msg_t msg_data;
  msg_data.data = axi.wdata;
  
  // Only looking at a single cycle so must be last cycle of transfer to be valid
  dma_msg_s msg;
  msg.data = msg_data;
  msg.valid = axi.wvalid & axi.wlast;
  return msg;
}

// Global/0Clk implementation:
// 1. Accept incoming DMA messages ('write data')
// 2. Issue a write response immediately
// 3. Respond with message as 'read data' when requested later
dma_msg_t serializer_msg_buffer;
axi512_o_t serializer(dma_msg_s msg, uint1_t read_request)
{
	// Buffer messages as they come in
	if(msg.valid)
	{
		serializer_msg_buffer = msg.data;
	}
	
	// Output the message later
	axi512_o_t axi;
  // Message incoming is produced from DMA write
  //  DMA write needs write response immediately
  axi.bid = 0;
  axi.bresp = 0; // Error code
  axi.bvalid = msg.valid;
  // 	Respond with read data when requested
  axi.rid = 0;
  axi.rdata = serializer_msg_buffer.data;
  axi.rresp = 0;
  axi.rlast = 1;
  axi.rvalid = read_request;

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
