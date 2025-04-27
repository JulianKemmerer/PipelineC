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

typedef struct axis16_t
{
  uint8_t tdata[2];
  uint1_t tkeep[2];
  uint1_t tlast;
} axis16_t;
DECL_STREAM_TYPE(axis16_t)

typedef struct axis32_t
{
  uint8_t tdata[4];
  uint1_t tkeep[4];
	uint1_t tlast;
} axis32_t;
DECL_STREAM_TYPE(axis32_t)

typedef struct axis64_t
{
  uint8_t tdata[8];
  uint1_t tkeep[8];
	uint1_t tlast;
} axis64_t;
DECL_STREAM_TYPE(axis64_t)

typedef struct axis128_t
{
  uint8_t tdata[16];
  uint1_t tkeep[16];
	uint1_t tlast;
} axis128_t;
DECL_STREAM_TYPE(axis128_t)

typedef struct axis256_t
{
  uint8_t tdata[32];
  uint1_t tkeep[32];
	uint1_t tlast;
} axis256_t;
DECL_STREAM_TYPE(axis256_t)

typedef struct axis512_t
{
  uint8_t tdata[64];
  uint1_t tkeep[64];
	uint1_t tlast;
} axis512_t;
DECL_STREAM_TYPE(axis512_t)

/* How useful is this?
typedef struct axis32_sized16_t
{
	axis32_t axis;
	uint16_t length;
} axis32_sized16_t;*/



// TODO make this into macro for all axis widths
uint1_t axis8_keep_count(stream(axis8_t) s){
  return s.valid; // & s.data.tkeep[0];
}

// Convert to funcs taking ex. an axis16_t instead of just the .keep?

uint5_t axis128_keep_count(axis128_t axis){
  uint5_t rv = 0;
  for(uint32_t i=0; i<16; i+=1){
    rv += axis.tkeep[i];
  }
  return rv;
}

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

// TODO make this example axis128 to/from axis512 into macros for any axis size

#define axis128_to_axis512_RATIO (512/128)
#define axis512_to_axis128_RATIO (512/128)

// Convert from axis512 to chunks of size axis128
typedef struct axis512_to_axis128_array_t{
  stream(axis128_t) axis_chunks[axis512_to_axis128_RATIO];
}axis512_to_axis128_array_t;
axis512_to_axis128_array_t axis512_to_axis128_array(axis512_t axis)
{
  axis512_to_axis128_array_t o;
  uint32_t CHUNK_SIZE = 128/8;
  for(uint32_t c=0; c<axis512_to_axis128_RATIO; c+=1)
  {
    // Chunks are valid based on tkeep parts of whole 512b
    // only need to check b=0 bottom tkeep bit for this chunk since assumed aligned
    o.axis_chunks[c].valid = axis.tkeep[(c*CHUNK_SIZE)];
    for(uint32_t b=0; b<CHUNK_SIZE; b+=1)
    {
      o.axis_chunks[c].data.tdata[b] = axis.tdata[(c*CHUNK_SIZE)+b];
      o.axis_chunks[c].data.tkeep[b] = axis.tkeep[(c*CHUNK_SIZE)+b];
    }
  }
  // tlast is only for the last chunk 
  // But might be applied to an earlier chunk if a partial valid chunks cycle
  // can tell a chunk is partially last, if next chunk is empty/invalid
  // (fine to set even if chunk not .valid)
  o.axis_chunks[(axis512_to_axis128_RATIO-1)].data.tlast = axis.tlast;
  for(uint32_t c=0; c<(axis512_to_axis128_RATIO-1); c+=1)
  {
    uint1_t next_chunk_is_empty = ~o.axis_chunks[c+1].valid;
    o.axis_chunks[c].data.tlast = next_chunk_is_empty;
  }
  return o;
}

// Convert from chunks of size axis128 to axis512
axis512_t axis128_array_to_axis512(stream(axis128_t) axis_chunks[axis128_to_axis512_RATIO])
{
  uint32_t CHUNK_SIZE = 128/8;
  axis512_t axis;
  // output is last word if any of chunks were last
  axis.tlast = 0;
  for(uint32_t c=0; c<axis128_to_axis512_RATIO; c+=1)
  {
    // last flag only used if valid
    axis.tlast |= (axis_chunks[c].valid & axis_chunks[c].data.tlast);
    for(uint32_t b=0; b<CHUNK_SIZE; b+=1)
    {
      axis.tdata[(c*CHUNK_SIZE)+b] = axis_chunks[c].data.tdata[b];
      // keep flag only used if valid
      axis.tkeep[(c*CHUNK_SIZE)+b] = (axis_chunks[c].valid & axis_chunks[c].data.tkeep[b]);
    }
  }
  return axis;
}

typedef struct axis128_to_axis512_t
{
  stream(axis512_t) axis_out;
  uint1_t axis_in_ready;
}axis128_to_axis512_t;
axis128_to_axis512_t axis128_to_axis512(
  stream(axis128_t) axis_in,
  uint1_t axis_out_ready
){
  uint32_t IN_SIZE = 128/8;
  uint32_t OUT_SIZE = 512/8;
  
  // Output wires
  axis128_to_axis512_t o;
  // IO regs for data+valid signals (not for ready, not skid buffer)
  static stream(axis128_t) axis_in_reg;
  static stream(axis512_t) axis_out_reg;

  // Output data+valid comes from reg
  o.axis_out = axis_out_reg;
  // if outgoing transfer then output reg can be cleared now
  if(o.axis_out.valid & axis_out_ready)
  {
    // all except tdata needs reset
    axis_out_reg.valid = 0;
    ARRAY_SET(axis_out_reg.data.tkeep, 0, OUT_SIZE)
    axis_out_reg.data.tlast = 0;
  }

  // Move one chunk of data from input to output
  // if have input valid chunk and
  // output reg is ready to accumulate data = not yet valid with full output
  uint1_t out_reg_ready = ~axis_out_reg.valid;
  if(axis_in_reg.valid & out_reg_ready)
  {
    // Existing chunks start off as some aligned axis data in output reg
    stream(axis128_t) axis_out_as_chunks[axis128_to_axis512_RATIO];
    axis512_to_axis128_array_t to_array = axis512_to_axis128_array(axis_out_reg.data);
    axis_out_as_chunks = to_array.axis_chunks;

    // Move the new input data chunk into the top/input part of output reg
    // Doing so might be an unaligned axis word depending on partial tkeep in tlast cycle
    ARRAY_1SHIFT_INTO_TOP(axis_out_as_chunks, axis128_to_axis512_RATIO, axis_in_reg)
    uint1_t last_cycle = axis_in_reg.data.tlast;
    // having taken the input reg contents, clear the input reg now
    // all except tdata needs reset
    axis_in_reg.valid = 0;
    ARRAY_SET(axis_in_reg.data.tkeep, 0, IN_SIZE)
    axis_in_reg.data.tlast = 0;

    // Finally re-align any partial cycles if this last cycle of input data
    if(last_cycle)
    {
      // Need to keep shifting the array chunks down towards bottom [0]
      // until a valid chunk is there, properly aligning everything
      for(uint32_t i=0; i<(axis128_to_axis512_RATIO-1); i+=1)
      {
        // If bottom spot is empty, shift down one
        // by shifting zeros into top
        if(~axis_out_as_chunks[0].valid)
        {
          stream(axis128_t) NULL_CHUNK = {0}; // Dont actually need to clear tdata too
          ARRAY_1SHIFT_INTO_TOP(axis_out_as_chunks, axis128_to_axis512_RATIO, NULL_CHUNK)
        }
      }
    }

    // Assemble aligned chunks into output reg
    axis_out_reg.data = axis128_array_to_axis512(axis_out_as_chunks);
    // Full output word is valid if bottom [0] spot has a valid chunk
    // (full and/or aligned partial data ends with that spot valid)
    axis_out_reg.valid = axis_out_as_chunks[0].valid;
  }

  // Ready for input if input reg is empty/
  // (dont need to check axis_in.valid actually)
  o.axis_in_ready = ~axis_in_reg.valid;
  if(axis_in.valid & o.axis_in_ready){
    axis_in_reg = axis_in;
  }

  return o;
}

typedef struct axis512_to_axis128_t
{
  stream(axis128_t) axis_out;
  uint1_t axis_in_ready;
}axis512_to_axis128_t;
axis512_to_axis128_t axis512_to_axis128(
  stream(axis512_t) axis_in,
  uint1_t axis_out_ready
){
  uint32_t IN_SIZE = 512/8;
  uint32_t OUT_SIZE = 128/8;

  // Output wires
  axis512_to_axis128_t o;
  
  // IO regs for data+valid signals (not for ready, not skid buffer)
  static stream(axis512_t) axis_in_reg;
  static stream(axis128_t) axis_out_reg;
  
  // Output data+valid comes from reg
  o.axis_out = axis_out_reg;
  // if outgoing transfer then output reg can be cleared now
  if(o.axis_out.valid & axis_out_ready)
  {
    // all except tdata needs reset
    axis_out_reg.valid = 0;
    ARRAY_SET(axis_out_reg.data.tkeep, 0, OUT_SIZE)
    axis_out_reg.data.tlast = 0;
  }

  // Move one chunk of data from input to output
  // if have input valid chunk and
  // output reg is ready to accumulate data = not yet valid with full output
  uint1_t out_reg_ready = ~axis_out_reg.valid;
  if(axis_in_reg.valid & out_reg_ready)
  {
    // Existing chunks start off as some aligned axis data in input reg
    stream(axis128_t) axis_in_as_chunks[axis512_to_axis128_RATIO];
    axis512_to_axis128_array_t to_array = axis512_to_axis128_array(axis_in_reg.data);
    axis_in_as_chunks = to_array.axis_chunks;

    // Move one chunk of input data (from bottom/[0] end) into output reg
    axis_out_reg = axis_in_as_chunks[0];
    // Shift the rest of the chunks down
    // by shifting zeros into top
    stream(axis128_t) NULL_CHUNK = {0}; // Dont actually need to clear tdata too
    ARRAY_1SHIFT_INTO_TOP(axis_in_as_chunks, axis512_to_axis128_RATIO, NULL_CHUNK)

    // Assemble and store the shifting chunks in the input reg
    axis_in_reg.data = axis128_array_to_axis512(axis_in_as_chunks);
    
    // Having taken a chunk of the input reg it might be fully empty now
    // can just check the first/bottom chunk and clear the whole input reg if so
    if(~axis_in_as_chunks[0].valid)
    {
      // all except tdata needs reset
      axis_in_reg.valid = 0;
      ARRAY_SET(axis_in_reg.data.tkeep, 0, IN_SIZE)
      axis_in_reg.data.tlast = 0;
    }

    // No alignment or assembly into multi chunk output is needed
  }

  // Ready for input if input reg is empty/invalid
  // (dont need to check axis_in.valid actually)
  o.axis_in_ready = ~axis_in_reg.valid;
  if(axis_in.valid & o.axis_in_ready){
    axis_in_reg = axis_in;
  }

  return o;
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