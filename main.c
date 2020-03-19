#include "examples/aws-fpga-dma/aws_fpga_dma.c"

aws_fpga_dma_outputs_t main(aws_fpga_dma_inputs_t i)
{
	return aws_fpga_dma(i);
}

/*
#include "uintN_t.h"
uint8_t i_r;
uint8_t o_r;
uint8_t main(uint8_t i)
{
	// Output reg
	uint8_t o;
	o = o_r;
	
	// Work between regs
	o_r = !i_r;
	//o_r = o_r + 1;
	
	// Input reg
	i_r = i;
	//i_r = i_r + 1;
	
	return o;
}
*/
