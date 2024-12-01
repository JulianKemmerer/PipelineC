module top(
  input clk_12p0,
  // RGB LED
  output ICE_39,
  output ICE_40,
  output ICE_41,
  // UART
  output ICE_25,
  input ICE_27,
  // PMOD1 ports for LED demo
  output ICE_28,
  output ICE_43,
  output ICE_32,
  output ICE_31,
  output ICE_38,
  output ICE_36,
  output ICE_42,
  output ICE_34
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
    // PMOD1 ports for LED demo
    .ice_28_return_output(ICE_28),
    .ice_43_return_output(ICE_43),
    .ice_32_return_output(ICE_32),
    .ice_31_return_output(ICE_31),
    .ice_38_return_output(ICE_38),
    .ice_36_return_output(ICE_36),
    .ice_42_return_output(ICE_42),
    .ice_34_return_output(ICE_34)
  );
endmodule
