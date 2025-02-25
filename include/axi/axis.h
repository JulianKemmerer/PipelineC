#pragma once
#include "uintN_t.h"
#include "stream/stream.h"
#include "stream/serializer.h"
#include "stream/deserializer.h"

// No generic sizes for now... :(

typedef struct axis8_t
{
	uint8_t tdata[1];
  uint1_t tkeep[1];
	uint1_t tlast;
} axis8_t;
DECL_STREAM_TYPE(axis8_t)

typedef struct axis32_t
{
  uint8_t tdata[4];
  uint1_t tkeep[4];
	uint1_t tlast;
} axis32_t;
DECL_STREAM_TYPE(axis32_t)

/* How useful is this?
typedef struct axis32_sized16_t
{
	axis32_t axis;
	uint16_t length;
} axis32_sized16_t;*/

typedef struct axis16_t
{
  uint8_t tdata[2];
  uint1_t tkeep[2];
  uint1_t tlast;
} axis16_t;
DECL_STREAM_TYPE(axis16_t)

// TODO make this into macro for all axis widths
uint1_t axis8_keep_count(stream(axis8_t) s){
  return s.valid; // & s.data.tkeep[0];
}

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
  stream(axis32_t) axis_out;
  uint1_t axis_in_ready;
}axis8_to_axis32_t;
#pragma FUNC_BLACKBOX axis8_to_axis32  // Has no (known) timing delay (like wires) and doesnt even have real internal logic - is black, (just io regs is all we assume)
axis8_to_axis32_t axis8_to_axis32(stream(axis8_t) axis_in, uint1_t axis_out_ready)
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
    signal m_axis_tdata : STD_LOGIC_VECTOR(31 DOWNTO 0); \n\
    signal m_axis_tkeep : STD_LOGIC_VECTOR(3 DOWNTO 0); \n\
    \n\
    begin   \n\
      \n\
    inst : axis_dwidth_converter_1_to_4  \n\
    PORT MAP (  \n\
      aclk => clk,  \n\
      aresetn => '1',  \n\
      s_axis_tvalid => axis_in.valid(0),  \n\
      s_axis_tready => return_output.axis_in_ready(0),  \n\
      s_axis_tdata => std_logic_vector(axis_in.data.tdata(0)),  \n\
      s_axis_tkeep => std_logic_vector(axis_in.data.tkeep(0)),  \n\
      s_axis_tlast => axis_in.data.tlast(0),  \n\
      m_axis_tvalid => return_output.axis_out.valid(0),  \n\
      m_axis_tready => axis_out_ready(0),  \n\
      m_axis_tdata => m_axis_tdata, \n\
      m_axis_tkeep => m_axis_tkeep, \n\
      m_axis_tlast => return_output.axis_out.data.tlast(0)  \n\
    );  \n\
    return_output.axis_out.data.tdata(0) <= unsigned(m_axis_tdata(7 downto 0)); \n\
    return_output.axis_out.data.tdata(1) <= unsigned(m_axis_tdata(15 downto 8)); \n\
    return_output.axis_out.data.tdata(2) <= unsigned(m_axis_tdata(23 downto 16)); \n\
    return_output.axis_out.data.tdata(3) <= unsigned(m_axis_tdata(31 downto 24)); \n\
    return_output.axis_out.data.tkeep(0)(0) <= m_axis_tkeep(0); \n\
    return_output.axis_out.data.tkeep(1)(0) <= m_axis_tkeep(1); \n\
    return_output.axis_out.data.tkeep(2)(0) <= m_axis_tkeep(2); \n\
    return_output.axis_out.data.tkeep(3)(0) <= m_axis_tkeep(3); \n\
  ");
}

typedef struct axis32_to_axis8_t
{
  stream(axis8_t) axis_out;
  uint1_t axis_in_ready;
}axis32_to_axis8_t;
#pragma FUNC_BLACKBOX axis32_to_axis8  // Has no (known) timing delay (like wires) and doesnt even have real internal logic - is black, (just io regs is all we assume)
axis32_to_axis8_t axis32_to_axis8(stream(axis32_t) axis_in, uint1_t axis_out_ready)
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
    signal s_axis_tdata : STD_LOGIC_VECTOR(31 DOWNTO 0);\n\
    signal s_axis_tkeep : STD_LOGIC_VECTOR(3 DOWNTO 0);\n\
    begin   \n\
      \n\
    inst : axis_dwidth_converter_4_to_1  \n\
    PORT MAP (  \n\
      aclk => clk,  \n\
      aresetn => '1',  \n\
      s_axis_tvalid => axis_in.valid(0),  \n\
      s_axis_tready => return_output.axis_in_ready(0),  \n\
      s_axis_tdata => s_axis_tdata,  \n\
      s_axis_tkeep => s_axis_tkeep,  \n\
      s_axis_tlast => axis_in.data.tlast(0),  \n\
      m_axis_tvalid => return_output.axis_out.valid(0),  \n\
      m_axis_tready => axis_out_ready(0),  \n\
      unsigned(m_axis_tdata) => return_output.axis_out.data.tdata(0),  \n\
      unsigned(m_axis_tkeep) => return_output.axis_out.data.tkeep(0),  \n\
      m_axis_tlast => return_output.axis_out.data.tlast(0)  \n\
    );  \n\
    s_axis_tdata(31 downto 24) <= std_logic_vector(axis_in.data.tdata(3)); \n\
    s_axis_tdata(23 downto 16) <= std_logic_vector(axis_in.data.tdata(2)); \n\
    s_axis_tdata(15 downto 8) <= std_logic_vector(axis_in.data.tdata(1)); \n\
    s_axis_tdata(7 downto 0) <= std_logic_vector(axis_in.data.tdata(0)); \n\
    s_axis_tkeep(3) <= axis_in.data.tkeep(3)(0); \n\
    s_axis_tkeep(2) <= axis_in.data.tkeep(2)(0); \n\
    s_axis_tkeep(1) <= axis_in.data.tkeep(1)(0); \n\
    s_axis_tkeep(0) <= axis_in.data.tkeep(0)(0); \n\
  ");
}

// Module to limit the max size/length of AXIS frames by dropping excess data
#define axis_max_len_limiter_count_t uint16_t
#define axis_max_len_limiter(axis_bits) \
typedef struct axis##axis_bits##_max_len_limiter_t \
{ \
  stream(axis##axis_bits##_t) out_stream; \
  uint1_t ready_for_in_stream; \
} axis##axis_bits##_max_len_limiter_t; \
axis##axis_bits##_max_len_limiter_t axis##axis_bits##_max_len_limiter(axis_max_len_limiter_count_t max_byte_len, stream(axis##axis_bits##_t) in_stream, uint1_t ready_for_out_stream) \
{ \
  static axis_max_len_limiter_count_t counter;\
  /* Allow passthrough if below limit*/\
  axis##axis_bits##_max_len_limiter_t o; \
  axis_max_len_limiter_count_t last_word_limit = (max_byte_len-(axis_bits/8));\
  uint1_t last = counter == last_word_limit;\
  uint1_t below = counter <= last_word_limit;\
  if(below){\
    o.out_stream = in_stream;\
    o.ready_for_in_stream = ready_for_out_stream;\
  }else{\
    /* All incoming data above limit is dropped*/\
    o.out_stream.valid = 0;\
    o.ready_for_in_stream = 1;\
  }\
  /* Force tlast if at the limit */\
  if(last){\
    o.out_stream.data.tlast = 1;\
  }\
  /* Count as transfers happen*/\
  if(o.out_stream.valid & ready_for_out_stream){\
    if(below){/*Dont need check?*/\
      counter += axis##axis_bits##_keep_count(in_stream);\
    }\
  }\
  /*Reset counter at last of input stream*/\
  if(in_stream.data.tlast & in_stream.valid & o.ready_for_in_stream){\
    counter = 0;\
  }\
  return o; \
}
// Decls for various widths TODO more
axis_max_len_limiter(8)

// Mostly a deser instance with added size limiter for one struct per packet
// sizeof(out_t) must be >= or divisble by axis_bits?
#define axis_packet_to_type(name,axis_bits,out_t) \
type_byte_deserializer(name##_type_byte_deserializer, (axis_bits/8), out_t) \
typedef struct name##_t \
{ \
  out_t data; \
  uint1_t valid; \
  uint1_t packet_ready; \
} name##_t; \
name##_t name(stream(axis##axis_bits##_t) packet, uint1_t output_ready) \
{ \
  /* Limit size of packet to sizeof(out_t) into normal deserializer*/\
  name##_t o; \
  uint1_t ready_for_limter_out;\
  FEEDBACK(ready_for_limter_out)\
  axis##axis_bits##_max_len_limiter_t limiter = axis##axis_bits##_max_len_limiter(\
    sizeof(out_t),\
    packet,\
    ready_for_limter_out\
  );\
  o.packet_ready = limiter.ready_for_in_stream;\
  stream(axis##axis_bits##_t) limited_packet = limiter.out_stream;\
  /* AXIS to byte stream */ \
  uint8_t input_data[(axis_bits/8)]; \
  uint32_t i; \
  for(i=0;i<(axis_bits/8);i+=1) \
  { \
    input_data[i] = limited_packet.data.tdata[i]; \
  } \
  /* Deserialize byte stream to type */ \
  name##_type_byte_deserializer_t to_type = name##_type_byte_deserializer(input_data, limited_packet.valid, output_ready); \
  o.data = to_type.data; \
  o.valid = to_type.valid; \
  ready_for_limter_out = to_type.in_data_ready; /*FEEDBACK*/ \
  return o; \
}


#if 0 // TODO TEST payload tdata packing
// sizeof(out_t) must be >= or divisble by axis_bits?
#define axis_to_type(name,axis_bits,out_t) \
/* Mostly just a deser instance */ \
type_byte_deserializer(name##_type_byte_deserializer, (axis_bits/8), out_t) \
typedef struct name##_t \
{ \
  out_t data; \
  uint1_t valid; \
  uint1_t payload_ready; \
} name##_t; \
name##_t name(axis##axis_bits##_t payload, uint1_t output_ready) \
{ \
  /* AXIS to byte stream */ \
  name##_t o; \
  uint8_t input_data[(axis_bits/8)]; \
  uint32_t i; \
  for(i=0;i<(axis_bits/8);i+=1) \
  { \
    input_data[i] = payload.data.tdata[i]; \
  } \
  /* Deserialize byte stream to type */ \
  name##_type_byte_deserializer_t to_type = name##_type_byte_deserializer(input_data, payload.valid, output_ready); \
  o.data = to_type.data; \
  o.valid = to_type.valid; \
  o.payload_ready = to_type.in_data_ready; \
  return o; \
}


/* AXIS32 only right now...*/
#define type_to_axis(name,in_t,axis_bits) \
/* Mostly just a ser instance */ \
type_byte_serializer(name##type_byte_serializer, in_t, (axis_bits/8)) \
typedef struct name##_t \
{ \
  axis##axis_bits##_t payload; \
  uint1_t input_data_ready; \
}name##_t; \
name##_t name(in_t data, uint1_t valid, uint1_t output_ready) \
{ \
  name##_t o; \
  \
  /* Serialize type to byte stream */ \
  name##type_byte_serializer_t from_type = name##type_byte_serializer(data, valid, output_ready); \
  o.input_data_ready = from_type.in_data_ready; \
  \
  /* Byte stream to axis */ \
  uint32_t i; \
  for(i=0;i<(axis_bits/8);i+=1) \
  {  \
    /* AXIS32 only right now...*/ \
    uint##axis_bits##_t out_data_bits = from_type.out_data[i]; /* Temp avoid not implemented cast */ \
    o.payload.data.tdata[i] = (out_data_bits<<(i*8)); \
  } \
  o.payload.keep = 0xF; /* AXIS32 only right now...*/ \
  o.payload.valid = from_type.valid; \
  o.payload.last = 0; \
  /* Counter for last assertion */ \
  static uint32_t last_counter; /* TODO smaller counter? */ \
  if(o.payload.valid & output_ready) \
  {\
    if(last_counter >= (sizeof(in_t)-(axis_bits/8))) \
    { \
      o.payload.last = 1; \
      last_counter = 0; \
    } \
    else \
    { \
      last_counter = last_counter+(axis_bits/8); \
    } \
  } \
  return o; \
}
#endif