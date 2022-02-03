#pragma once
#include "uintN_t.h"

#define axi_id_t uint6_t

// 512b AXI-4 bus is bidirectional

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

