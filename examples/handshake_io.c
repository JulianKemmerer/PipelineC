// Demo of using handshake and stream header helpers
// to construct handshaked modules like AXI-Stream
// TODO summarize in wiki write up based on Discord talk?
#include "arrays.h"
#include "handshake/handshake.h"

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
DECL_HANDSHAKE_TYPE(my_axis_32_t)
DECL_HANDSHAKE_INST_TYPE(my_axis_32_t, my_axis_32_t) // out type, in type 
// ^ Declares hs_in(my_axis_32_t) and hs_out(my_axis_32_t)
// struct specific to a 1 output = func(1 input) setup
// with ready signals included
//typedef struct my_axis_32_t_hs_in_t
//{
//  stream(my_axis_32_t) stream_in;
//  uint1_t ready_for_stream_out;
//}my_axis_32_t_hs_in_t;
//typedef my_axis_32_t_hs_out_t
//{
//  stream(my_axis_32_t) stream_out;
//  uint1_t ready_for_stream_in;
//}my_axis_32_t_hs_out_t;

// Single cycle stateful(static locals) function (a state machine)
// for working with an input and output handshake
hs_out(my_axis_32_t) my_func(
  hs_in(my_axis_32_t) inputs
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

  hs_out(my_axis_32_t) outputs; // Default value all zeros

  // Connect output based on buffer in use
  // ready for input if other buffer is empty(not valid)
  if(output_is_skid_buff){
    outputs.stream_out = skid_buff;
    outputs.ready_for_stream_in = ~buff.valid;
  }else{
    outputs.stream_out = buff;
    outputs.ready_for_stream_in = ~skid_buff.valid;
  }

  // Input ready writes buffer
  if(outputs.ready_for_stream_in){
    if(output_is_skid_buff){
      buff = inputs.stream_in;
    }else{
      skid_buff = inputs.stream_in;
    }
  }

  // Output ready clears buffer
  // and switches to next buffer
  if(inputs.ready_for_stream_out){
    if(output_is_skid_buff){
      skid_buff.valid = 0;
    }else{
      buff.valid = 0;
    }
    output_is_skid_buff = ~output_is_skid_buff;
  }

  return outputs;
}

// Demo flattened top level ports with AXIS style manager/subordinate naming
// (could also have inputs and outputs of type hs_in,hs_out,stream
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
// Shows how to use new HANDSHAKE macros and such
// that include handling the strange to software 'FEEDBACK' mechanism
#pragma PART "xc7a35ticsg324-1l" // Artix 7 35T (Arty)
#pragma MAIN_MHZ top 100.0
void top(){
  // Handshake style code with helper macros etc
  // Requires instantiating the modules to be used first at start of func
  // func0: my_axis_32_t my_func(my_axis_32_t)
  DECL_HANDSHAKE_INST(func0, my_axis_32_t, my_func, my_axis_32_t)
  // func1: my_axis_32_t my_func(my_axis_32_t)
  DECL_HANDSHAKE_INST(func1, my_axis_32_t, my_func, my_axis_32_t)

  // Connect flattened top level input ports to local stream variables
  stream(my_axis_32_t) input_axis;
  UINT_TO_BYTE_ARRAY(input_axis.data.data, 4, s_axis_tdata)
  UINT_TO_BIT_ARRAY(input_axis.data.keep, 4, s_axis_tkeep)
  input_axis.data.last = s_axis_tlast;
  input_axis.valid = s_axis_tvalid;

  // Input stream into first instance
  // func0 input handshake = input_axis, s_axis_tready
  HANDSHAKE_FROM_STREAM(func0, input_axis, s_axis_tready) 

  // Output of first instance into second
  // func1 input handshake = func0 output handshake
  HANDSHAKE_CONNECT(func1, func0)

  // Output stream from second instance
  stream(my_axis_32_t) output_axis;
  // output_axis, m_axis_tready = func1 output handshake
  STREAM_FROM_HANDSHAKE(output_axis, m_axis_tready, func1)
  
  // Connect flattened top level output ports from local stream type variables
  m_axis_tdata = uint8_array4_le(output_axis.data.data); // Array to uint
  m_axis_tkeep = uint1_array4_le(output_axis.data.keep); // Array to uint
  m_axis_tlast = output_axis.data.last;
  m_axis_tvalid = output_axis.valid;
}

// TODO testbench with printfs?
