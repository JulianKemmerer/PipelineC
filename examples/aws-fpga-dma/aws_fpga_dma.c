// The top level 'main' function for the AWS FPGA DMA example

#include "../../axi.h"
#include "dma_msg_hw.c"

// AWS HDK shell I/O
// Only interface supported is PCIS AXI-4 bus for now
typedef struct aws_fpga_dma_inputs_t
{
  axi512_i_t pcis;
} aws_fpga_dma_inputs_t;
typedef struct aws_fpga_dma_outputs_t
{
  axi512_o_t pcis;
} aws_fpga_dma_outputs_t;

// Clock cross into work_wrapper
dma_msg_s in_msg; // Input message
#include "in_msg_clock_crossing.h"
uint1_t out_msg_ready; // Output flow control
#include "uint1_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "out_msg_ready_clock_crossing.h"

// Clock cross out of work_wrapper
dma_msg_s out_msg; // Output message
#include "out_msg_clock_crossing.h"
uint1_t in_msg_ready; // Input flow control
#include "uint1_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "in_msg_ready_clock_crossing.h"

// AWS example runs at 125
// However, experiments show we might need margin to meet timing at scalez
#pragma MAIN_MHZ aws_fpga_dma 150.0
aws_fpga_dma_outputs_t aws_fpga_dma(aws_fpga_dma_inputs_t i)
{
  aws_fpga_dma_outputs_t o;
  
  // Read work input msg ready flag from work function wrapper
  uint1_t_array_1_t work_readys;
  work_readys = in_msg_ready_READ();
  uint1_t work_ready;
  work_ready = work_readys.data[0];
  
  // Deserializer handles write side
  // Pull messages out of incoming DMA write requests
  deserializer_outputs_t deser_output;
  deser_output = deserializer(i.pcis.write, work_ready);
  o.pcis.write = deser_output.axi;
  
  // Write the input message stream into work function wrapper for processing
	dma_msg_s_array_1_t msgs_in;
	msgs_in.data[0] = deser_output.msg_stream;
	in_msg_WRITE(msgs_in);
	
	// Read output message stream from work function wrapper
	dma_msg_s_array_1_t msgs_out;
	msgs_out = out_msg_READ();
  dma_msg_s msg_out;
  msg_out = msgs_out.data[0];
  
  // Serializer handles read side
  // Put output message into outgoing DMA read requests
  serializer_outputs_t serializer_output;
  serializer_output = serializer(msg_out, i.pcis.read);
  o.pcis.read = serializer_output.axi;
  
  // Write ready for work output msg flag into work function wrapper
  uint1_t_array_1_t dma_out_msg_readys;
  dma_out_msg_readys.data[0] = serializer_output.msg_in_ready;
  out_msg_ready_WRITE(dma_out_msg_readys);
  
  return o;
}


