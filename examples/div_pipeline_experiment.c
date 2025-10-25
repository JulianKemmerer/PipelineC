#include "uintN_t.h"
#pragma PART "xc7a35ticsg324-1l" 
#pragma MAIN div0_pipelinec

/*Source:                 div0_0CLK_b45f1687_y_input_reg_reg[0]/C
  Destination:            div0_0CLK_b45f1687_return_output_output_reg_reg[0]/D
  Data Path Delay:        76.371ns  (logic 57.187ns (74.880%)  route 19.184ns (25.120%))
  Logic Levels:           290  (CARRY4=288 LUT2=1 LUT3=1)
  FMAX ~13MHz*/
uint32_t div0(uint32_t x, uint32_t y){
  __vhdl__("begin\n\
    return_output <= x / y;\
  ");
}

// No autopipelining, 0 clocks
/*Source:                 div0_pipelinec_0CLK_ccfc15c6_x_input_reg_reg[31]/C
  Destination:            div0_pipelinec_0CLK_ccfc15c6_return_output_output_reg_reg[0]/D
  Data Path Delay:        91.712ns  (logic 42.781ns (46.647%)  route 48.931ns (53.353%))
  Logic Levels:           279  (CARRY4=247 LUT2=1 LUT4=1 LUT5=27 LUT6=3)
  FMAX ~10MHz */
uint32_t div0_pipelinec(uint32_t x, uint32_t y){
  return x / y;
}

/*Source:                 div1_in_reg_0CLK_b45f1687/y_r0_reg[14]_fret__462/C
  Destination:            div1_in_reg_0CLK_b45f1687_return_output_output_reg_reg[0]/D
  Data Path Delay:        38.681ns  (logic 28.737ns (74.292%)  route 9.944ns (25.708%))
  Logic Levels:           145  (CARRY4=144 LUT3=1)
  FMAX ~25MHz*/
uint32_t div1_in_reg(uint32_t x, uint32_t y){
  __vhdl__("\n\
   signal x_r0 : unsigned(31 downto 0);\n\
   signal y_r0 : unsigned(31 downto 0);\n\
  begin\n\
    x_r0 <= x when rising_edge(clk);\n\
    y_r0 <= y when rising_edge(clk);\n\
    return_output <= x_r0 / y_r0;\n\
  ");
}

/*Source:                 div1_out_reg_0CLK_b45f1687_y_input_reg_reg[0]/C
  Destination:            div1_out_reg_0CLK_b45f1687/out_r0_reg[0]_bret_bret_bret_bret_bret_bret_bret_bret_bret_bret__99_bret__0/D
  Data Path Delay:        51.288ns  (logic 38.115ns (74.316%)  route 13.173ns (25.684%))
  Logic Levels:           192  (CARRY4=189 LUT2=2 LUT3=1)
  FMAX ~19MHz*/
uint32_t div1_out_reg(uint32_t x, uint32_t y){
  __vhdl__("\n\
   signal out_r0 : unsigned(31 downto 0);\n\
  begin\n\
    out_r0 <= x / y when rising_edge(clk);\n\
    return_output <= out_r0;\n\
  ");
}

/*Source:                 div2_0CLK_b45f1687/y_r0_reg[5]_fret/C
  Destination:            div2_0CLK_b45f1687/out_r0_reg[0]_bret_bret_bret_bret_bret_bret_bret_bret_bret_bret__99_bret__0/D
  Data Path Delay:        49.186ns  (logic 36.125ns (73.446%)  route 13.061ns (26.554%))
  Logic Levels:           182  (CARRY4=180 LUT2=1 LUT3=1)
  FMAX ~20MHz*/
uint32_t div2(uint32_t x, uint32_t y){
  __vhdl__("\n\
   signal x_r0 : unsigned(31 downto 0);\n\
   signal y_r0 : unsigned(31 downto 0);\n\
   signal out_r0 : unsigned(31 downto 0);\n\
  begin\n\
    x_r0 <= x when rising_edge(clk);\n\
    y_r0 <= y when rising_edge(clk);\n\
    out_r0 <= x_r0 / y_r0 when rising_edge(clk);\n\
    return_output <= out_r0;\n\
  ");
}

/*Source:                 div4_0CLK_b45f1687/y_r1_reg[5]_fret/C
  Destination:            div4_0CLK_b45f1687/out_r0_reg[0]_bret_bret_bret_bret_bret_bret_bret_bret_bret_bret__99_bret__0/D
  Data Path Delay:        49.186ns  (logic 36.125ns (73.446%)  route 13.061ns (26.554%))
  Logic Levels:           182  (CARRY4=180 LUT2=1 LUT3=1)
  FMAX ~20MHz*/
uint32_t div4(uint32_t x, uint32_t y){
  __vhdl__("\n\
   signal x_r0 : unsigned(31 downto 0);\n\
   signal y_r0 : unsigned(31 downto 0);\n\
   signal x_r1 : unsigned(31 downto 0);\n\
   signal y_r1 : unsigned(31 downto 0);\n\
   signal out_r0 : unsigned(31 downto 0);\n\
   signal out_r1 : unsigned(31 downto 0);\n\
  begin\n\
    x_r0 <= x when rising_edge(clk);\n\
    y_r0 <= y when rising_edge(clk);\n\
    x_r1 <= x_r0 when rising_edge(clk);\n\
    y_r1 <= y_r0 when rising_edge(clk);\n\
    out_r0 <= x_r1 / y_r1 when rising_edge(clk);\n\
    out_r1 <= out_r0 when rising_edge(clk);\n\
    return_output <= out_r1;\n\
  ");
}

