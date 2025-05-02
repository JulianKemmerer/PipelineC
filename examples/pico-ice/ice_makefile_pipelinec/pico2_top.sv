module top(
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
    // RGB LED
    .ice_39_return_output(ICE_39),
    .ice_40_return_output(ICE_40),
    .ice_41_return_output(ICE_41),
    // UART
    .ice_11_return_output(ICE_11),
    .ice_9_val_input(ICE_9),
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
