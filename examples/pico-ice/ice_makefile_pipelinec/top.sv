module top(
  // These pins should all exist in ice40.pcf
  // Pin 35 12MHz clock in pico-ice default RP firmware
  // Cannot be used if HFOSC and PLL are being used in top.sv
  //inout ICE_35,
  inout ICE_39,
  inout ICE_40,
  inout ICE_41,
  inout ICE_25,
  inout ICE_27,
  inout ICE_11,
  inout ICE_9,
  inout ICE_45,
  inout ICE_47,
  inout ICE_2,
  inout ICE_4,
  inout ICE_44,
  inout ICE_46,
  inout ICE_48,
  inout ICE_3,
  inout ICE_31,
  inout ICE_34,
  inout ICE_38,
  inout ICE_43,
  inout ICE_28,
  inout ICE_32,
  inout ICE_36,
  inout ICE_42,
  inout ICE_23,
  inout ICE_26
);
  // No 12M input for PICO2_ICE
  // High frequency oscillator
  //  CLKHF_DIV
  //  0b00 = 48 MHz, 0b01 = 24 MHz,
  //  0b10 = 12 MHz, 0b11 = 6 MHz
  // This config needs to match micropython fpga = ice.fpga(frequency= argument?
  wire clk_48p0;
  SB_HFOSC#(.CLKHF_DIV("0b00")) u_hfosc (
    .CLKHFPU(1'b1),
    .CLKHFEN(1'b1),
    .CLKHF(clk_48p0)
  );
  // PLL instance to make a clock based on 12MHz
  wire pll_clk;
  pll pll_inst(
    .clock_in(clk_48p0),
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