
#include "examples/aws-fpga-dma/aws_fpga_dma.c"


aws_fpga_dma_outputs_t main(aws_fpga_dma_inputs_t i)
{
	return aws_fpga_dma(i);
}

/*
dma_msg_s main(axi512_i_t axi)
{
	return deserializer(axi);
	
}
*/
