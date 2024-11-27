// Demo of using stream.h header helpers
// to construct streams like AXI-Stream
#include "arrays.h"
#include "stream/stream.h"

// AXI building blocks are a work in progress
// see ex. axi/axis.h
// But for now just define a little demo 'my' type here
typedef struct my_axis_32_t{
  uint8_t data[4];
  uint1_t keep[4];
  uint1_t last;
  // TODO user field
}my_axis_32_t;

DECL_STREAM_TYPE(my_axis_32_t)
// ^Declares stream(my_axis_32_t) == my_axis_32_t_stream_t
// a type with .data and .valid flag like
//typedef struct my_axis_32_t_stream_t{
//  my_axis_32_t data;
//  uint1_t valid;
//}my_axis_32_t_stream_t;

// Single cycle stateful(static locals) function (a state machine)
// for working with an input and output stream
// Multiple outputs as a struct
typedef struct my_func_out_t{
  // Outputs from module
  //  Output .data and .valid stream
  stream(my_axis_32_t) axis_out;
  //  Output ready for input axis stream
  uint1_t ready_for_axis_in;
}my_func_out_t;
my_func_out_t my_func(
  // Inputs to module
  //  Input .data and .valid stream
  stream(my_axis_32_t) axis_in,
  //  Input ready for output axis stream
  uint1_t ready_for_axis_out
){
  // Demo logic for skid buffer
  // Static = register
  static stream(my_axis_32_t) buff;
  static stream(my_axis_32_t) skid_buff;
  // Idea of skid buffer is to switch between two buffers
  // to skid to a stop while avoiding a comb. path from 
  //  ready_for_axis_out -> ready_for_axis_in
  // loosely like a 2-element FIFO...
  static uint1_t output_is_skid_buff; // aka input_is_buff

  // Output signals
  my_func_out_t o; // Default value all zeros

  // Connect output based on buffer in use
  // ready for input if other buffer is empty(not valid)
  if(output_is_skid_buff){
    o.axis_out = skid_buff;
    o.ready_for_axis_in = ~buff.valid;
  }else{
    o.axis_out = buff;
    o.ready_for_axis_in = ~skid_buff.valid;
  }

  // Input ready writes buffer
  if(o.ready_for_axis_in){
    if(output_is_skid_buff){
      buff = axis_in;
    }else{
      skid_buff = axis_in;
    }
  }

  // Output ready clears buffer
  // and switches to next buffer
  if(ready_for_axis_out){
    if(output_is_skid_buff){
      skid_buff.valid = 0;
    }else{
      buff.valid = 0;
    }
    output_is_skid_buff = ~output_is_skid_buff;
  }

  return o;
}

// Demo flattened top level ports with AXIS style manager/subdorinate naming
// (could also have inputs and outputs of type stream(my_axis_32_t)
//  but ex. Verilog does not support VHDL records...)
DECL_INPUT(uint32_t, s_axis_tdata)
DECL_INPUT(uint4_t, s_axis_tkeep)
DECL_INPUT(uint1_t, s_axis_tlast)
DECL_INPUT(uint1_t, s_axis_tvalid)
DECL_OUTPUT(uint1_t, s_axis_tready)
DECL_OUTPUT(uint32_t, m_axis_tdata)
DECL_OUTPUT(uint4_t, m_axis_tkeep)
DECL_OUTPUT(uint1_t, m_axis_tlast)
DECL_OUTPUT(uint1_t, m_axis_tvalid)
DECL_INPUT(uint1_t, m_axis_tready)

// Demo connecting two my_func's back to back
// Shows how to connect typical feed forward data
// and special FEEDBACK wires unique to hardware ready flow control
#pragma PART "xc7a35ticsg324-1l" // Artix 7 35T (Arty)
#pragma MAIN_MHZ top 100.0
void top(){
  // Connect top level input ports to local stream type variables
  //  Input stream data
  stream(my_axis_32_t) input_axis;
  UINT_TO_BYTE_ARRAY(input_axis.data.data, 4, s_axis_tdata)
  UINT_TO_BIT_ARRAY(input_axis.data.keep, 4, s_axis_tkeep)
  input_axis.data.last = s_axis_tlast;
  input_axis.valid = s_axis_tvalid;
  //  Output stream ready
  uint1_t ready_for_output_axis = m_axis_tready;

  // Input stream into first instance  
  uint1_t ready_for_func0_axis_out;
  // Note: FEEDBACK not assigned a value yet
  #pragma FEEDBACK ready_for_func0_axis_out
  my_func_out_t func0 = my_func(
    input_axis,
    ready_for_func0_axis_out
  );
  uint1_t ready_for_input_axis = func0.ready_for_axis_in;

  // Output of first instance into second
  uint1_t ready_for_func1_axis_out = ready_for_output_axis;
  my_func_out_t func1 = my_func(
    func0.axis_out,
    ready_for_func1_axis_out
  );
  // Note: FEEDBACK assigned here
  ready_for_func0_axis_out = func1.ready_for_axis_in; 

  // Connect top level output ports from local stream type variables
  //  Output stream data
  m_axis_tdata = uint8_array4_le(func1.axis_out.data.data); // Array to uint
  m_axis_tkeep = uint1_array4_le(func1.axis_out.data.keep); // Array to uint
  m_axis_tlast = func1.axis_out.data.last;
  m_axis_tvalid = func1.axis_out.valid;
  //  Input stream ready
  s_axis_tready = ready_for_input_axis;
}

// TODO testbench with printfs?