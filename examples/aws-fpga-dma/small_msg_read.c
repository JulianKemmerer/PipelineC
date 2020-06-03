#include "aws_fpga_dma.c"

#define SMALL DMA_MSG_SIZE  // BUFSIZE = 128,  DMA_MSG_SIZE 256
dma_msg_t small_msg;
uint1_t small_msg_valid = 1;

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
  
  // Write DMA message bytes into aws_fpga_dma
	dma_msg_s_array_1_t msgs_out;
	msgs_out.data[0].data = small_msg; // Small message
  msgs_out.data[0].valid = small_msg_valid; // Small message
	aws_out_msg_WRITE(msgs_out);
  
  // Clear valid if was ready for msg
  if(out_ready)
  {
    small_msg_valid = 0;
  }
  
  // Ready for input message if dont have valid msg
  // Ready for input message if dont have valid msg
  // Accept input message if current message invalid
  uint1_t msg_in_ready = !small_msg_valid;
  if(msg_in_ready)
  {
    // Small is only 16 bytes in example
    uint8_t i;
    for(i=0;i<SMALL;i=i+1)
    {
      small_msg.data[i] = msg_in.data.data[i];
    }
    small_msg_valid = msg_in.valid;
  }
  
  // Write ready for input message indicator into aws_fpga_dma
  uint1_t_array_1_t in_readys;
	in_readys.data[0] = msg_in_ready; 
	aws_in_msg_ready_WRITE(in_readys);
  
  // Reset revalidates message of zeros to read
  if(rst)
  {
    small_msg = DMA_MSG_T_NULL(); // Zeros data
    small_msg_valid = 1;
  }
}
