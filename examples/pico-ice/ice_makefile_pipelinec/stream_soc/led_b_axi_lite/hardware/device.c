// Basic AXI-Lite control and status registers demo for control of blue LED

// PipelineC library for AXI-lite like shared bus
#include "axi/axi_shared_bus.h" 

// Device specific memory map types etc
#include "../mem_map.h"

// Globally visible wires for SoC to connect to
axi_shared_bus_t_dev_to_host_t led_b_axi_lite_to_host;
axi_shared_bus_t_host_to_dev_t led_b_axi_lite_from_host;

// Declare shared axi csr device
DECL_AXI_SHARED_BUS_CSR_DEV(led_b_mm_regs_t, led_b_axi_dev)

#pragma MAIN led_b_axi_lite_main
void led_b_axi_lite_main()
{
  // Some user axi lite memory mapped regs
  static led_b_mm_regs_t mm_regs;
  // Use control registers here
  led_b = ~mm_regs.led_on; // Active low right?
  // The device instance
  led_b_axi_dev_t dev = led_b_axi_dev(led_b_axi_lite_from_host, mm_regs);
  led_b_axi_lite_to_host = dev.to_host;
  // Drive status registers here
  mm_regs = dev.mm_regs_out;
}

