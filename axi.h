#pragma once
#include "uintN_t.h"

// 512b AXI-4 bus is bidirectional
// 	Inputs
typedef struct axi512_i_t
{
  // Write Channel
  //  Address
  //    "Write this stream to a location in memory"
  //    Should be valid before data starts
  uint6_t awid;
  uint64_t awaddr;
  uint8_t awlen; // In cycles
  uint3_t awsize; // 2^size = Transfer width in bytes, 8 to 1024 bits supported
  uint1_t awvalid;
  //  Data stream to be written to memory
  uint8_t wdata[64]; // 64 bytes
  uint1_t wstrb[64];
  uint1_t wlast;
  uint1_t wvalid;
  //  Read to receive write responses
  uint1_t bready;

  // Read Channel
  //  Address
  //    "Give me a stream from a place in memory"
  //    Should be valid before data starts
  uint6_t arid;
  uint64_t araddr;
  uint8_t arlen;
  uint3_t arsize; // 2^size = Transfer width in bytes, 8 to 1024 bits supported
  uint1_t arvalid;
  //  Ready to receive read data
  uint1_t rready;
} axi512_i_t;
//	Outputs
typedef struct axi512_o_t
{
  // Write Channel
  //  Write response
  uint6_t bid;
  uint2_t bresp; // Error code
  uint1_t bvalid;
  //  Ready for write address
  uint1_t awready;
	//  Ready for write data 
  uint1_t wready;
  
  // Read Channel
  //  Data stream from memory
  uint6_t rid;
  uint8_t rdata[64];
  uint2_t rresp;
  uint1_t rlast;
  uint1_t rvalid;
  //  Ready for read address
  uint1_t arready;
} axi512_o_t;

