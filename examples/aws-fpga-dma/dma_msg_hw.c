// Code wrapping AXI4 (FPGA) hardware to a common 'DMA message' 

#include "../../axi.h"
#include "dma_msg.h"

// !!!!!!!  WARNING: !!!!!!!!!!!
//		THIS IMPLEMENTATION DOES NOT HAVE FLOW CONTROL LOGIC.
//		ASSUMES ALWAYS READY FOR INPUT AND OUTPUT.

#define DMA_WORD_SIZE 64 
#define DMA_MSG_WORDS (DMA_MSG_SIZE/DMA_WORD_SIZE)

// Word array as struct for returning from functions
typedef struct dma_word_buffer_t
{
  uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
} dma_word_buffer_t;

// Unpack word array into byte array
dma_msg_t deserializer_unpack(dma_word_buffer_t msg_word_buffer)
{
  // Unpack 2D byte array word buffer into long 1D output byte array
	dma_msg_t msg;
	uint32_t word_i;
	uint32_t byte_i;
	for(word_i=0;word_i<DMA_MSG_WORDS;word_i=word_i+1)
	{
		for(byte_i=0;byte_i<DMA_WORD_SIZE;byte_i=byte_i+1)
		{
			msg.data[(word_i*DMA_WORD_SIZE)+byte_i] = msg_word_buffer.words[word_i][byte_i];
		}
	}
	return msg;
}

// Parse input AXI-4 to a wide lower duty cycle message stream
// Keep track of pos in buffer
dma_msg_size_t deserializer_word_pos;
dma_word_buffer_t deserializer_msg_word_buffer;
dma_msg_s deserializer(axi512_i_t axi)
{
	// Only paying attention to write request channel data (not address)
  // since we are only using one buffer in host memory address = 0
  // And a write is always followed by a read of the same size
	
	// Write into location in buffer, resetting as needed
	uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
	words = deserializer_msg_word_buffer.words;
	if(axi.wvalid)
	{
		words[deserializer_word_pos] = axi.wdata;
		deserializer_word_pos = deserializer_word_pos + 1;
		if(axi.wlast)
		{
			deserializer_word_pos = 0;
		}
	}
	deserializer_msg_word_buffer.words = words;

	dma_msg_s msg;
	msg.data = deserializer_unpack(deserializer_msg_word_buffer);
	
	// Msg is valid when we have the last word of data
	msg.valid = axi.wvalid & axi.wlast;
  return msg;
}

// Pack byte array into word array buffer
dma_word_buffer_t serializer_pack(dma_msg_t msg)
{
	dma_word_buffer_t msg_word_buffer;
	uint32_t word_i;
	uint32_t byte_i;
	for(word_i=0;word_i<DMA_MSG_WORDS;word_i=word_i+1)
	{
		for(byte_i=0;byte_i<DMA_WORD_SIZE;byte_i=byte_i+1)
		{
			msg_word_buffer.words[word_i][byte_i] = msg.data[(word_i*DMA_WORD_SIZE)+byte_i];
		}
	}
	return msg_word_buffer;
}

// Serialize messages as AXI
// 1. Accept incoming DMA messages ('write data')
// 2. Issue a write response immediately
// 3. Respond with message as 'read data' when requested later
dma_word_buffer_t serializer_msg_word_buffer;
dma_msg_size_t serializer_word_pos;
uint1_t serializing;
axi512_o_t serializer(dma_msg_s msg, uint1_t read_request)
{
	// Output axi defaults
	axi512_o_t axi;
	axi.bvalid = 0; // Invalid write response
	axi.bid = 0;
	axi.bresp = 0; // Error code
	axi.rvalid = 0; // Invalid read response
	axi.rid = 0;
	axi.rresp = 0;
	axi.rlast = 0;
	uint8_t i;
	for(i=0; i<DMA_WORD_SIZE; i=i+1)
	{
		axi.rdata[i] = 0;
	}
	
	// Message incoming is produced by DMA write
	if(msg.valid)
	{
		// DMA write needs write response immediately
		axi.bvalid = 1;
		// Buffer messages as they come in, stored by word
		serializer_msg_word_buffer = serializer_pack(msg.data);
		// Doing so resets serialization
		serializer_word_pos = 0;
	}	
  
  // Only begin serializing response data once requested
  if(read_request)
  {
		serializing = 1;
	}
  
  // Do serializing
  if(serializing)
  {
		// Select the word to go on the bus
		uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
		words = serializer_msg_word_buffer.words;
		uint8_t word[DMA_WORD_SIZE];
		word = words[serializer_word_pos];
		
		// Put it on the bus
		axi.rdata = word;
		axi.rvalid = 1;
		serializer_word_pos = serializer_word_pos + 1;
		
		// End of serialization?
		if(serializer_word_pos==DMA_MSG_WORDS)
		{
			axi.rlast = 1;
			serializer_word_pos = 0;
			serializing = 0;
		}
	}

  // Can't really do good flow control - yet.
  // This is hacky
  // Ready for write address
  axi.awready = 1;
	//  Ready for write data 
  axi.wready = 1;
  //  Ready for read address
  axi.arready = 1;
  
  return axi;
}
