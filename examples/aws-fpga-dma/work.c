#pragma once
#include "dma_msg.c"

// Convert 64 bytes into 16 floats (32b/4B)
// Sum using built in Pipeline C array 16 sum func

// Helper function to convert DMA bytes to 'work' inputs
typedef struct work_inputs_t
{
  float values[16];
} work_inputs_t;
work_inputs_t bytes_to_inputs(dma_msg_t msg_in)
{
  // Convert 64 bytes into 16 floats (32b/4B each)
  work_inputs_t work_inputs;
  // Loop over entire buffer 4 bytes at a time
  uint4_t byte_i;
  for(byte_i=0; byte_i < 64; byte_i = byte_i + 4)
  {
		// Assemble 4 byte buffer
		uint8_t buffer[4];
		uint3_t buff_pos;
		for(buff_pos=0;buff_pos<4;buff_pos=buff_pos+1)
		{
			buffer[buff_pos] = msg_in.data[byte_i+buff_pos];
		}
		// Convert to uint32_t
		uint32_t val_unsigned;
		val_unsigned = uint8_array4_le(buffer);
		// Convert uint32_t to float
		work_inputs.values[byte_i/4] = float_uint32(val_unsigned);
	}
	return work_inputs;
}

// Helper function to convert 'work' outputs into DMA bytes
typedef struct work_outputs_t
{
  float sum;
} work_outputs_t;
dma_msg_t outputs_to_bytes(work_outputs_t outputs)
{
	// Convert float sum into 4 bytes
	dma_msg_t dma_msg;
	dma_msg.length = 4;
	dma_msg.data[0] = float_7_0(outputs.sum);
	dma_msg.data[1] = float_15_8(outputs.sum);
	dma_msg.data[2] = float_23_16(outputs.sum);
	dma_msg.data[3] = float_31_24(outputs.sum);
	
	// Zero out the rest
	uint7_t i;
	for(i=4; i<64; i=i+1)
	{
		dma_msg.data[i] = 0;
	}
	
	return dma_msg;
}

// Do work on an incoming message to form an output one
work_outputs_t work(work_inputs_t inputs)
{
	// Sum those values using built in binary tree function:
	// 		8 sums in parallel
	//    4 sums in parallel
	//    2 sums in parallel
	//    1 final sum
  work_outputs_t outputs;
  outputs.sum = float_array_sum16(inputs.values);

	return outputs;
}
