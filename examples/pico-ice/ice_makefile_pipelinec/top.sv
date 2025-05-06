module top(
  `include "top_pins.svh"
);
  // No 12M input for PICO2_ICE
  // High frequency oscillator
  //  CLKHF_DIV
  //  0b00 = 48 MHz, 0b01 = 24 MHz,
  //  0b10 = 12 MHz, 0b11 = 6 MHz
  // This config needs to match micropython fpga = ice.fpga(frequency= argument?
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
    // The pipelinec port names exactly match wires in this top level .sv
    // so can use wildcard .* implicit port connection to automatically connect them
    .*
  );
endmodule