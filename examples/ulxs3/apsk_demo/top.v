`include "pll.v"

module top(clk_25p0, leds_return_output, gp_return_output);
  input clk_25p0;
  wire clk_30p72;
  wire locked;
  pll pll_i(clk_25p0, clk_30p72, locked);
  output [27:0] gp_return_output;
  wire [27:0] gp_return_output;
  output [7:0] leds_return_output;
  wire [7:0] leds_return_output;
  pipelinec_top mytop (.clk_30p72(clk_30p72), .leds_REG(leds_return_output), .gp_REG(gp_return_output));
endmodule