#pragma once
#include "uintN_t.h"
#include "compiler.h"
#include "xstr.h"
// Macros for fifos
// Not globally visible variables
// Declares FIFO modules for single function single clock domain use

// FWFT style using pipelinec_fifo_fwft raw VHDL
#define FIFO_FWFT(name, type_t, DEPTH)\
typedef struct PPCAT(name,_t) \
{ \
  type_t data_out; \
  uint1_t data_out_valid; \
  uint1_t data_in_ready; \
  /*Same as not out valid uint1_t empty;*/ \
  /*Same as not in ready uint1_t full*/ \
  /*TODO fifo_count_t count;*/ \
}PPCAT(name,_t); \
PPCAT(name,_t) name(uint1_t ready_for_data_out, type_t data_in, uint1_t data_in_valid) \
{\
__vhdl__("\
constant WIDTH : integer := " xstr(PPCAT(type_t,_SLV_LEN)) ";\n\
constant DEPTH_LOG2 : positive := positive(ieee.math_real.ceil(ieee.math_real.log2(real(" xstr(DEPTH) "))));\n\
signal din_slv : std_logic_vector(WIDTH-1 downto 0);\n\
signal dout_slv : std_logic_vector(WIDTH-1 downto 0);\n\
begin\n\
din_slv <= " xstr(PPCAT(type_t,_to_slv)) "(data_in);\n\
return_output.data_out <= " xstr(PPCAT(slv_to_,type_t)) "(dout_slv);\n\
pipelinec_fifo_fwft_inst : entity work.pipelinec_fifo_fwft\n\
generic map(\n\
  DEPTH_LOG2 => DEPTH_LOG2,\n\
  DATA_WIDTH => WIDTH\n\
)port map(\n\
  clk => clk,\n\
  data_in => din_slv,\n\
  valid_in => data_in_valid(0) and CLOCK_ENABLE(0),\n\
  ready_out => return_output.data_in_ready(0),\n\
  data_out => dout_slv,\n\
  valid_out => return_output.data_out_valid(0),\n\
  ready_in => ready_for_data_out(0) and CLOCK_ENABLE(0)\n\
);\n\
");\
}
