#pragma once
#include "uintN_t.h"

// No generic sizes for now... :(
// Woah AXIS spec is little endian - who knew?

// Flow control signaling for AXIS
typedef struct axis_fc_t
{
  uint1_t ready;
}axis_fc_t;

// TODO all convert to using arrays

typedef struct axis8_t
{
	uint8_t data[1];
	uint1_t valid;
	uint1_t last;
} axis8_t;

typedef struct axis32_t
{
	uint32_t data;
	uint1_t valid;
	uint1_t last;
	uint4_t keep;
} axis32_t;

// How useful is this?
typedef struct axis32_sized16_t
{
	axis32_t axis;
	uint16_t length;
} axis32_sized16_t;

typedef struct axis16_t
{
	uint16_t data;
	uint1_t valid;
	uint1_t last;
	uint2_t keep;
} axis16_t;

// Convert to funcs taking ex. an axis16_t instead of just the .keep?

uint2_t axis16_keep_bytes(uint2_t keep)
{
	uint2_t rv;
	// Default invalid keep / zero
	rv = 0;
	if(keep == 1) // 01
	{
		rv = 1;
	}
	else if(keep == 3) // 11
	{
		rv = 2;
	}
	return rv;
}

uint3_t axis32_keep_bytes(uint4_t keep)
{
	uint3_t rv;
	// Default invalid keep / zero
	rv = 0;
	if(keep == 1) // 0001
	{
		rv = 1;
	}
	else if(keep == 3) // 0011
	{
		rv = 2;
	}
	else if(keep == 7) // 0111
	{
		rv = 3;
	}
	else if(keep == 15) // 1111
	{
		rv = 4;
	}
	return rv;
}


uint2_t axis16_bytes_keep(uint2_t num_bytes)
{
	uint2_t rv;
	// Default invalid keep / zero
	rv = 0;
	if(num_bytes == 1)
	{
		rv = 1; // 01
	}
	else if(num_bytes == 2)
	{
		rv = 3; // 11
	}
	return rv;	
}

uint4_t axis32_bytes_keep(uint3_t num_bytes) 
{
	uint4_t rv;
	// Default invalid keep / zero
	rv = 0;
	if(num_bytes == 1)
	{
		rv = 1; // 0001
	}
	else if(num_bytes == 2)
	{
		rv = 3; // 0011
	}
	else if(num_bytes == 3)
	{
		rv = 7; // 0111
	}
	else if(num_bytes == 4)
	{
		rv = 15; // 1111
	}
	return rv;	
}


// Convert axis8 to/from axis32
typedef struct axis8_to_axis32_t
{
  axis32_t axis_out;
  uint1_t axis_in_ready;
}axis8_to_axis32_t;
#pragma FUNC_BLACKBOX axis8_to_axis32  // Has no (known) timing delay (like wires) and doesnt even have real internal logic - is black, (just io regs is all we assume)
axis8_to_axis32_t axis8_to_axis32(axis8_t axis_in, uint1_t axis_out_ready)
{
  __vhdl__("\n\
    COMPONENT axis_dwidth_converter_1_to_4 \n\
    PORT ( \n\
      aclk : IN STD_LOGIC; \n\
      aresetn : IN STD_LOGIC; \n\
      s_axis_tvalid : IN STD_LOGIC; \n\
      s_axis_tready : OUT STD_LOGIC; \n\
      s_axis_tdata : IN STD_LOGIC_VECTOR(7 DOWNTO 0); \n\
      s_axis_tkeep : IN STD_LOGIC_VECTOR(0 DOWNTO 0); \n\
      s_axis_tlast : IN STD_LOGIC; \n\
      m_axis_tvalid : OUT STD_LOGIC; \n\
      m_axis_tready : IN STD_LOGIC; \n\
      m_axis_tdata : OUT STD_LOGIC_VECTOR(31 DOWNTO 0); \n\
      m_axis_tkeep : OUT STD_LOGIC_VECTOR(3 DOWNTO 0); \n\
      m_axis_tlast : OUT STD_LOGIC \n\
    ); \n\
    END COMPONENT; \n\
    \n\
    begin   \n\
      \n\
    inst : axis_dwidth_converter_1_to_4  \n\
    PORT MAP (  \n\
      aclk => clk,  \n\
      aresetn => '1',  \n\
      s_axis_tvalid => axis_in.valid(0),  \n\
      s_axis_tready => return_output.axis_in_ready(0),  \n\
      s_axis_tdata => std_logic_vector(axis_in.data(0)),  \n\
      s_axis_tkeep => std_logic_vector(axis_in.valid),  \n\
      s_axis_tlast => axis_in.last(0),  \n\
      m_axis_tvalid => return_output.axis_out.valid(0),  \n\
      m_axis_tready => axis_out_ready(0),  \n\
      unsigned(m_axis_tdata) => return_output.axis_out.data,  \n\
      unsigned(m_axis_tkeep) => return_output.axis_out.keep,  \n\
      m_axis_tlast => return_output.axis_out.last(0)  \n\
    );  \n\
  ");
}

typedef struct axis32_to_axis8_t
{
  axis8_t axis_out;
  uint1_t axis_in_ready;
}axis32_to_axis8_t;
#pragma FUNC_BLACKBOX axis32_to_axis8  // Has no (known) timing delay (like wires) and doesnt even have real internal logic - is black, (just io regs is all we assume)
axis32_to_axis8_t axis32_to_axis8(axis32_t axis_in, uint1_t axis_out_ready)
{
  __vhdl__("\n\
    COMPONENT axis_dwidth_converter_4_to_1 \n\
      PORT ( \n\
        aclk : IN STD_LOGIC; \n\
        aresetn : IN STD_LOGIC; \n\
        s_axis_tvalid : IN STD_LOGIC; \n\
        s_axis_tready : OUT STD_LOGIC; \n\
        s_axis_tdata : IN STD_LOGIC_VECTOR(31 DOWNTO 0); \n\
        s_axis_tkeep : IN STD_LOGIC_VECTOR(3 DOWNTO 0); \n\
        s_axis_tlast : IN STD_LOGIC; \n\
        m_axis_tvalid : OUT STD_LOGIC; \n\
        m_axis_tready : IN STD_LOGIC; \n\
        m_axis_tdata : OUT STD_LOGIC_VECTOR(7 DOWNTO 0); \n\
        m_axis_tkeep : OUT STD_LOGIC_VECTOR(0 DOWNTO 0); \n\
        m_axis_tlast : OUT STD_LOGIC \n\
      ); \n\
    END COMPONENT; \n\
    \n\
    begin   \n\
      \n\
    inst : axis_dwidth_converter_4_to_1  \n\
    PORT MAP (  \n\
      aclk => clk,  \n\
      aresetn => '1',  \n\
      s_axis_tvalid => axis_in.valid(0),  \n\
      s_axis_tready => return_output.axis_in_ready(0),  \n\
      s_axis_tdata => std_logic_vector(axis_in.data),  \n\
      s_axis_tkeep => std_logic_vector(axis_in.keep),  \n\
      s_axis_tlast => axis_in.last(0),  \n\
      m_axis_tvalid => return_output.axis_out.valid(0),  \n\
      m_axis_tready => axis_out_ready(0),  \n\
      unsigned(m_axis_tdata) => return_output.axis_out.data,  \n\
      --unsigned(m_axis_tkeep) => return_output.axis_out.keep,  \n\
      m_axis_tlast => return_output.axis_out.last(0)  \n\
    );  \n\
  ");
}

