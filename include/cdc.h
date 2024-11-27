#pragma once
#include "uintN_t.h"

#define CDC(type, name, num_regs, lhs, rhs) \
static type name##_registers[num_regs];\
uint8_t name##_i;\
lhs = name##_registers[0];\
for(name##_i=0;name##_i<(num_regs-1);name##_i+=1)\
{\
  name##_registers[name##_i] = name##_registers[name##_i+1];\
}\
name##_registers[num_regs-1] = rhs;

#define CDC2(type, name, lhs, rhs) CDC(type, name, 2, lhs, rhs)

// TODO HOWTO LIBRARIES IN RAW VHDL?
//library xpm;
//use xpm.vcomponents.all;
// Seems can get away with just matching component def?
#pragma FUNC_WIRES xil_cdc2_bit
uint1_t xil_cdc2_bit(uint1_t src_in){
  __vhdl__("\n\
  component xpm_cdc_array_single is \n\
  generic ( \n\
    -- Common module generics \n\
    DEST_SYNC_FF   : integer := 4; \n\
    INIT_SYNC_FF   : integer := 0; \n\
    SIM_ASSERT_CHK : integer := 0; \n\
    SRC_INPUT_REG  : integer := 1; \n\
    WIDTH          : integer := 2 \n\
  ); \n\
  port ( \n\
    src_clk  : in std_logic; \n\
    src_in   : in std_logic_vector(WIDTH-1 downto 0); \n\
    dest_clk : in std_logic; \n\
    dest_out : out std_logic_vector(WIDTH-1 downto 0) \n\
  ); \n\
  end component xpm_cdc_array_single; \n\
  begin \n\
  xpm_cdc_array_single_inst : xpm_cdc_array_single\n\
  generic map (\n\
    DEST_SYNC_FF => 2,   -- DECIMAL; range: 2-10\n\
    INIT_SYNC_FF => 1,   -- DECIMAL; 0=disable simulation init values, 1=enable simulation init values\n\
    SIM_ASSERT_CHK => 1, -- DECIMAL; 0=disable simulation messages, 1=enable simulation messages\n\
    SRC_INPUT_REG => 0,  -- DECIMAL; 0=do not register input, 1=register input\n\
    WIDTH => 1           -- DECIMAL; range: 1-1024\n\
  )\n\
  port map (\n\
    unsigned(dest_out) => return_output, -- WIDTH-bit output: src_in synchronized to the destination clock domain. This\n\
                          -- output is registered.\n\
    dest_clk => clk, -- 1-bit input: Clock signal for the destination clock domain.\n\
    src_clk => '0',   -- 1-bit input: optional; required when SRC_INPUT_REG = 1\n\
    src_in => std_logic_vector(src_in)      -- WIDTH-bit input: Input single-bit array to be synchronized to destination clock\n\
                          -- domain. It is assumed that each bit of the array is unrelated to the others.\n\
                          -- This is reflected in the constraints applied to this macro. To transfer a binary\n\
                          -- value losslessly across the two clock domains, use the XPM_CDC_GRAY macro\n\
                          -- instead.\n\
  );\n\
  ");
}

// TODO ADD CDC handshake , implement using pipelinec async fifos for data and ready bit xfer