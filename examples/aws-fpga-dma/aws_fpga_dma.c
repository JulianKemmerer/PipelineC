#pragma once
#include "../../axi.h"
#include "dma_msg.h"

// Do work on an incoming message to form an output one
dma_msg_s work(dma_msg_s msg_in)
{
  dma_msg_s msg_out;
  msg_out.valid = msg_in.valid;
  
  // For now just copy data
  dma_msg_t msg_data;
  msg_data = msg_in.data;

  msg_out.data = msg_data;
  return msg_out;
}

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
  // Pull messages out of incoming DMA data
  dma_msg_s msg_in;
  msg_in = deserialize(i.pcis);
  
  // Do some work on said message to form output message
  dma_msg_s msg_out;
  msg_out = work(msg_in);
  
  // Put output message into outgoing DMA data
  aws_fpga_dma_outputs_t o;
  o.pcis = serialize(msg_out);
  
  return o;
}
