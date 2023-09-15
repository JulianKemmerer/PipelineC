/////////////////// GENERIC AXI-like DUAL PORT RAM ///////////////////////////////////
// Assumes (todo REQUIRE) that output response FIFOs are always ready
// (since didnt implement flow control push back through RAM path yet)

// Declare dual port RAM
// Easiest to match AXI bus width
typedef struct axi_ram_data_t{
  uint8_t data[AXI_BUS_BYTE_WIDTH];
}axi_ram_data_t;

#ifndef AXI_RAM_N_PORTS
#define AXI_RAM_N_PORTS 2
#endif

// The RAM with two ports
#if AXI_RAM_N_PORTS == 2
#include "ram.h"
DECL_RAM_DP_RW_RW_1(
  axi_ram_data_t,
  axi_ram,
  AXI_RAM_DEPTH,
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
  axi_ram_out_ports_t axi_ram_out_ports[AXI_RAM_N_PORTS];
}axi_ram_module_t;
axi_ram_module_t axi_ram_module(axi_ram_in_ports_t axi_ram_in_ports[AXI_RAM_N_PORTS])
{
  axi_ram_module_t o;
  // 1 cycle of delay regs for ID field not included in RAM macro func
  static uint8_t id_reg[AXI_RAM_N_PORTS];

  // Do RAM lookup
  #if AXI_RAM_N_PORTS == 2
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

  #elif AXI_RAM_N_PORTS == 1
  static axi_ram_data_t axi_ram[AXI_RAM_DEPTH];
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
  for (i = 0; i < AXI_RAM_N_PORTS; i+=1)
  {
    id_reg[i] = axi_ram_in_ports[i].id;
  }

  return o;
}
