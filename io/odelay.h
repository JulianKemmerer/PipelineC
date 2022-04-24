#include "uintN_t.h"

uint1_t odelay_variable_clock(
  uint1_t clk_data_in, 
  uint1_t inc, // 0=dec
  uint1_t inc_dec_en
)
{
  __vhdl__(" \n\
    component ODELAYE2 \n\
    generic( \n\
      CINVCTRL_SEL		: string	:= \"FALSE\"; \n\
      DELAY_SRC			: string	:= \"ODATAIN\"; \n\
      HIGH_PERFORMANCE_MODE	: string	:= \"FALSE\"; \n\
      ODELAY_TYPE		: string	:= \"FIXED\"; \n\
      ODELAY_VALUE		: integer	:= 0; \n\
      PIPE_SEL			: string	:= \"FALSE\"; \n\
      REFCLK_FREQUENCY		: real		:= 200.0; \n\
      SIGNAL_PATTERN		: string	:= \"DATA\" \n\
    ); \n\
    port( \n\
      CNTVALUEOUT : out std_logic_vector(4 downto 0); \n\
      DATAOUT	  : out std_ulogic; \n\
      C           : in  std_ulogic; \n\
      CE          : in  std_ulogic; \n\
      CINVCTRL    : in std_ulogic; \n\
      CLKIN       : in std_ulogic; \n\
      CNTVALUEIN  : in std_logic_vector(4 downto 0); \n\
      INC         : in  std_ulogic; \n\
      LD	  : in  std_ulogic; \n\
      LDPIPEEN    : in  std_ulogic; \n\
      ODATAIN     : in  std_ulogic; \n\
      REGRST      : in  std_ulogic \n\
    ); \n\
    end component; \n\
 \n\
  component IDELAYCTRL \n\
   port ( \n\
      RDY : out std_ulogic; \n\
      REFCLK  : in  std_ulogic; \n\
      RST : in  std_ulogic \n\
   ); \n\
  end component;  \n\
 \n\
  begin \n\
    inst : ODELAYE2 \n\
    generic map( \n\
      ODELAY_TYPE => \"VARIABLE\", \n\
      SIGNAL_PATTERN => \"CLOCK\", \n\
      DELAY_SRC => \"CLKIN\" \n\
    ) \n\
    port map( \n\
      CNTVALUEOUT => open, \n\
      DATAOUT => return_output(0), \n\
      C  => clk, \n\
      CE => inc_dec_en(0) and CLOCK_ENABLE(0), \n\
      CINVCTRL => '0', \n\
      CLKIN => clk_data_in(0), \n\
      CNTVALUEIN => (others => '0'), \n\
      INC => inc(0), \n\
      LD => '0', \n\
      LDPIPEEN => '0', \n\
      ODATAIN => '0', \n\
      REGRST => '0' \n\
    ); \n\
\n\
   ctrl : IDELAYCTRL \n\
   port map( \n\
     RDY => open, \n\
     REFCLK => clk, \n\
     RST => '0' \n\
   ); \n\
  ");
}
