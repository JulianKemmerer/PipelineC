// This file desribes the software-side (big endian?) conversion 
// of the DMA message struct to/from work input/output types

#include "dma_msg.h"
#include "work.h"

// Helper functions to convert DMA bytes to/from 'work' inputs/outputs

dma_msg_t inputs_to_bytes(work_inputs_t inputs)
{
	// Convert floats into bytes 
	dma_msg_t msg;
  // Loop over entire buffer 4 bytes at a time
  dma_msg_size_t byte_i;
  for(byte_i=0; byte_i < DMA_MSG_SIZE; byte_i = byte_i + FLOAT_SIZE)
  {
		uint8_t b[FLOAT_SIZE];
		memcpy(&b, &(inputs.values[byte_i/FLOAT_SIZE]), sizeof(float));
		// Convert from big endian? float to little endian? bytes
		msg.data[byte_i+0] = b[0];
		msg.data[byte_i+1] = b[1];
		msg.data[byte_i+2] = b[2];
		msg.data[byte_i+3] = b[3];
	}
	return msg;
}

work_outputs_t bytes_to_outputs(dma_msg_t msg)
{
	// Assemble single float output from first 4 bytes
	work_outputs_t outputs;
	// Convert from little endian? bytes to big endian? float
	uint8_t b[] = {msg.data[0], msg.data[1], msg.data[2], msg.data[3]};
	memcpy(&(outputs.sum), &b, sizeof(float));
	return outputs;
}




