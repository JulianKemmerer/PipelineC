#include "aws_fpga_dma.c"

#pragma MAIN_MHZ main_wrapper 150.0
void main_wrapper(uint1_t rst)
{
	// Read ready for output msg flag from aws_fpga_dma
  uint1_t_array_1_t out_readys;
  out_readys = aws_out_msg_ready_READ();
  uint1_t out_ready;
  out_ready = out_readys.data[0];

	// Read DMA message bytes from aws_fpga_dma
  dma_msg_s_array_1_t msgs_in;
  msgs_in = aws_in_msg_READ();
  dma_msg_s msg_in;
  msg_in = msgs_in.data[0];

  // Write ready for input message indicator into aws_fpga_dma
  uint1_t_array_1_t in_readys;
	in_readys.data[0] = out_ready; // Loopback
	aws_in_msg_ready_WRITE(in_readys);
  
  // Write DMA message bytes into aws_fpga_dma
	dma_msg_s_array_1_t msgs_out;
	msgs_out.data[0] = msg_in; // Loopback
	aws_out_msg_WRITE(msgs_out);
}
