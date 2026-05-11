// Basic AXI-Lite control and status registers demo for status buttons

// PipelineC library for AXI-lite like shared bus
#include "axi/axi_shared_bus.h" 

// Device specific memory map types etc
#include "../mem_map.h"

// Top level button input
DECL_INPUT(uint4_t, btn)

// Globally visible wires for SoC to connect to
axi_shared_bus_t_dev_to_host_t buttons_axi_lite_to_host;
axi_shared_bus_t_host_to_dev_t buttons_axi_lite_from_host;

// Declare shared axi csr device
DECL_AXI_SHARED_BUS_CSR_DEV(uint32_t, buttons_axi_dev)

#pragma MAIN buttons_axi_lite_main
void buttons_axi_lite_main()
{
  // Some user axi lite memory mapped regs
  static uint32_t mm_regs;
  // Use control registers here
  // The device instance
  buttons_axi_dev_t dev = buttons_axi_dev(buttons_axi_lite_from_host, mm_regs);
  buttons_axi_lite_to_host = dev.to_host;
  mm_regs = dev.mm_regs_out;
  // Drive status registers here
  mm_regs = btn;
}