module top(
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
    // UART
    .ice_25_return_output(ICE_25),
    .ice_27_val_input(ICE_27),
    // PMODs for VGA demo
    // PMOD0A
    .ice_45_return_output(ICE_45),
    .ice_47_return_output(ICE_47),
    .ice_2_return_output(ICE_2),
    .ice_4_return_output(ICE_4),
    // PMOD0B
    .ice_44_return_output(ICE_44),
    .ice_46_return_output(ICE_46),
    .ice_48_return_output(ICE_48),
    .ice_3_return_output(ICE_3),
    // PMOD1A
    .ice_31_return_output(ICE_31),
    .ice_34_return_output(ICE_34),
    .ice_38_return_output(ICE_38),
    .ice_43_return_output(ICE_43),
    // PMOD1B
    // UNUSED for VGA PMOD .ice_28_return_output(ICE_28),
    // UNUSED for VGA PMOD .ice_32_return_output(ICE_32),
    .ice_36_return_output(ICE_36),
    .ice_42_return_output(ICE_42)
  );
endmodule
