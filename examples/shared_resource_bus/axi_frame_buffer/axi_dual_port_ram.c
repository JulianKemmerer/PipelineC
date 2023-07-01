/////////////////// GENERIC AXI-like DUAL PORT RAM ///////////////////////////////////
// Assumes (todo REQUIRE) that output response FIFOs are always ready
// (since didnt implement flow control push back through RAM path yet)
#include "uintN_t.h"

#define AXI_BUS_BYTE_WIDTH 4 // 32b
#define axi_addr_t uint32_t
#define axi_id_t uint1_t // Not used
typedef struct axi_write_req_t
{
  // Address
  //  "Write this stream to a location in memory"
  //  Must be valid before data starts
  axi_id_t awid;
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
  uint1_t wlast;
}axi_write_data_t;
typedef struct axi_write_resp_t
{
  // Write response
  axi_id_t bid;
  uint2_t bresp; // Error code
} axi_write_resp_t;
typedef struct axi_read_req_t
{
  // Address
  //   "Give me a stream from a place in memory"
  //   Must be valid before data starts
  axi_id_t arid;
  axi_addr_t araddr;
  uint8_t arlen; // Number of transfer cycles minus one
  uint3_t arsize; // 2^size = Transfer width in bytes
  uint2_t arburst;
} axi_read_req_t;
typedef struct axi_read_resp_t
{
  // Read response
  axi_id_t rid;
  uint2_t rresp;
} axi_read_resp_t;
typedef struct axi_read_data_t
{
  // Data stream from memory
  uint8_t rdata[AXI_BUS_BYTE_WIDTH]; // 4 bytes, 32b
  uint1_t rlast;
} axi_read_data_t;

// Declare dual port RAM
// Easiest to match AXI bus width
typedef struct axi_ram_data_t{
  uint8_t data[AXI_BUS_BYTE_WIDTH];
}axi_ram_data_t;

// The RAM with two ports
#include "ram.h"
#define AXI_RAM_N_PORTS 2
DECL_RAM_DP_RW_RW_1(
  axi_ram_data_t,
  axi_ram,
  AXI_RAM_DEPTH,
  "(others => (others => (others => (others => '0'))))"
)
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
  axi_ram_out_ports_t axi_ram_out_ports[AXI_RAM_N_PORTS];
}axi_ram_module_t;
axi_ram_module_t axi_ram_module(axi_ram_in_ports_t axi_ram_in_ports[AXI_RAM_N_PORTS])
{
  axi_ram_module_t o;
  // 1 cycle of delay regs for ID field not included in RAM macro func
  static uint8_t id_reg[AXI_RAM_N_PORTS];

  // Do RAM lookup
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

  // ID delay reg
  uint32_t i;
  for (i = 0; i < AXI_RAM_N_PORTS; i+=1)
  {
    id_reg[i] = axi_ram_in_ports[i].id;
  }

  return o;
}
