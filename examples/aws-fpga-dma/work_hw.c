// This file desribes the hardware-side (little endian) conversion 
// of the DMA message struct to/from work input/output types 

#include "dma_msg.h"
#include "work.h"

// Helper functions to convert DMA bytes to/from 'work' inputs/outputs

work_inputs_t bytes_to_inputs(dma_msg_t msg_in)
{
  // Convert 64 bytes into 16 floats (32b/4B each)
  work_inputs_t work_inputs;
  // Loop over entire buffer 4 bytes at a time
  uint4_t byte_i;
  for(byte_i=0; byte_i < DMA_MSG_SIZE; byte_i = byte_i + 4)
  {
		// Assemble 4 byte buffer
		uint8_t buff[4];
		uint3_t buff_pos;
		for(buff_pos=0;buff_pos<4;buff_pos=buff_pos+1)
		{
			buff[buff_pos] = msg_in.data[byte_i+buff_pos];
		}
		// Convert as little endian to uint32_t
		uint32_t val_unsigned;
		val_unsigned = uint8_array4_le(buff);
		// Convert uint32_t to float
		work_inputs.values[byte_i/4] = float_uint32(val_unsigned);
	}
	return work_inputs;
}

dma_msg_t outputs_to_bytes(work_outputs_t outputs)
{
	// Convert float sum into 4 little endian bytes
	dma_msg_t dma_msg;
	dma_msg.data[0] = float_7_0(outputs.sum);
	dma_msg.data[1] = float_15_8(outputs.sum);
	dma_msg.data[2] = float_23_16(outputs.sum);
	dma_msg.data[3] = float_31_24(outputs.sum);
	
	// Zero out the rest
	uint7_t i;
	for(i=4; i<DMA_MSG_SIZE; i=i+1)
	{
		dma_msg.data[i] = 0;
	}
	
	return dma_msg;
}
