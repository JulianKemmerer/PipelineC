module ethernet_top(
  `include "top_pins.svh"
);
  // No 12M input for PICO2_ICE
  // High frequency oscillator
  //  CLKHF_DIV
  //  0b00 = 48 MHz, 0b01 = 24 MHz,
  //  0b10 = 12 MHz, 0b11 = 6 MHz
  wire clk_12p0;
  SB_HFOSC#(.CLKHF_DIV("0b10")) u_hfosc (
    .CLKHFPU(1'b1),
    .CLKHFEN(1'b1),
    .CLKHF(clk_12p0)
  );
  // PLL instance to make a clock based on 12MHz
  wire pll_clk;
  pll pll_inst(
    .clock_in(clk_12p0),
    .clock_out(pll_clk),
    .locked()
  );

  // PipelineC output HDL instance
  pipelinec_top pipelinec_inst(
    .pll_clk_val_input(pll_clk),
    // UART
    .ice_25_return_output(ICE_25),
    .ice_27_val_input(ICE_27),
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
