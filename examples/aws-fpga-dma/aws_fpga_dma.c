// The top level 'main' function for the AWS FPGA DMA example

#include "../../axi.h"
#include "dma_msg_hw.c"
#include "work_hw.c"

// IO is mostly the PCIS AXI-4 bus
typedef struct aws_fpga_dma_inputs_t
{
  axi512_i_t pcis;
} aws_fpga_dma_inputs_t;
typedef struct aws_fpga_dma_outputs_t
{
  axi512_o_t pcis;
} aws_fpga_dma_outputs_t;
aws_fpga_dma_outputs_t aws_fpga_dma(aws_fpga_dma_inputs_t i)
{
  // Pull messages out of incoming DMA write data
  dma_msg_s msg_in;
  msg_in = deserialize(i.pcis);
  
  // Convert incoming DMA message bytes to 'work' inputs
  work_inputs_t work_inputs;
  work_inputs = bytes_to_inputs(msg_in.data);
  
  // Do some work
  work_outputs_t work_outputs;
  work_outputs = work(work_inputs);
  
  // Convert 'work' outputs into outgoing DMA message bytes
  dma_msg_s msg_out;
  msg_out.data = outputs_to_bytes(work_outputs);
  msg_out.valid = msg_in.valid;
  
  // Put output message into outgoing DMA read data when requested
  aws_fpga_dma_outputs_t o;
  o.pcis = serializer(msg_out, i.pcis.arvalid);
  
  return o;
}
