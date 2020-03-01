// The top level 'main' function for the AWS FPGA DMA example

#include "../../axi.h"
#include "dma_msg_hw.c"
#include "work_hw.c"

// IO is the PCIS AXI-4 bus
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
  msg_in = deserializer(i.pcis);
  
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
  o.pcis = serializer(msg_out, i.pcis);
  
  return o;
}



/* Multi read reg sketch?
// Writer of i reg
// 0 clk func
i_r
in(i)
{
	i_r = i
}

read_i_r()
{
	return i_r
}

// Writer of out_r
o_r
write_o_r(o)
{
	o_r = 0;
}

// N clock pipeline function
work()
{
	i = read_i_r() // 0 clk global func
	
	// Piplined logic
	o = ..something with i ...
	
	write_o_r(o) // 0 clk global func

}

// Reader of out_r
out()
{
	return o_r
}


main(i) // 0 clk
{
	in(i);
	
	return out();
}
*/
