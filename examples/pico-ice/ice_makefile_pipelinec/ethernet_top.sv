module ethernet_top(
  `include "top_pins.svh"
);
  // PLL instance to make a clock based on 12MHz input
  wire pll_clk;
  pll pll_inst(
    .clock_in(clk_12p0),
    .clock_out(pll_clk),
    .locked()
	);

  // PipelineC output HDL instance
  pipelinec_top pipelinec_inst(
    .pll_clk_val_input(pll_clk),
    // RGB LED
    .ice_39_return_output(ICE_39),
    .ice_40_return_output(ICE_40),
    .ice_41_return_output(ICE_41),
    // PMOD0A
    .ice_45_return_output(ICE_45),
    .ice_47_return_output(ICE_47),
    .ice_2_val_input(ICE_2),
    .ice_4_val_input(ICE_4),
    // PMOD0B
    .ice_46_return_output(ICE_46),
    .ice_48_val_input(ICE_48),
    .ice_3_val_input(ICE_3)
  );
endmodule
