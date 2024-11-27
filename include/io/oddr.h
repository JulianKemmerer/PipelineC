#include "uintN_t.h"

#pragma FUNC_WIRES oddr_same_edge // Dont care about delay through ODDR
uint1_t oddr_same_edge(uint1_t d1, uint1_t d2)
{
  __vhdl__(" \n\
    component ODDR \n\
    generic( \n\
      DDR_CLK_EDGE : string := \"OPPOSITE_EDGE\"; \n\
      INIT         : bit    := '0'; \n\
      SRTYPE       : string := \"SYNC\" \n\
    ); \n\
    port( \n\
      Q           : out std_ulogic; \n\
      C           : in  std_ulogic; \n\
      CE          : in  std_ulogic; \n\
      D1          : in  std_ulogic; \n\
      D2          : in  std_ulogic; \n\
      R           : in  std_ulogic := 'L'; \n\
      S           : in  std_ulogic := 'L' \n\
    ); \n\
    end component; \n\
  begin \n\
    inst : ODDR \n\
    generic map( \n\
      DDR_CLK_EDGE => \"SAME_EDGE\", \n\
      INIT         => '0', \n\
      SRTYPE       => \"SYNC\" \n\
    ) \n\
    port map( \n\
      Q  => return_output(0), \n\
      C  => clk, \n\
      CE => CLOCK_ENABLE(0), \n\
      D1 => d1(0), \n\
      D2 => d2(0), \n\
      R => '0', \n\
      S => '0' \n\
    ); \n\
  ");
}
