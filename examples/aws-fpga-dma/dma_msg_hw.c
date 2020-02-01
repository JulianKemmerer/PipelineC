// Code wrapping AXI4 (FPGA) hardware to a common 'DMA message' 

#include "../../axi.h"
#include "dma_msg.h"

// !!!!!!!  WARNING: !!!!!!!!!!!
//		THIS IMPLEMENTATION DOES NOT HAVE FLOW CONTROL LOGIC.
//		ASSUMES ALWAYS READY FOR INPUT AND OUTPUT.

// Parse input AXI-4 to a wide lower duty cycle message stream
dma_msg_t deserializer_msg_buffer;
// Keep track of pos in buffer
#define DMA_WORD_SIZE 64 
#define DMA_MSG_WORDS (DMA_MSG_SIZE/DMA_WORD_SIZE)
dma_msg_size_t deserializer_word_pos;
dma_msg_s deserializer(axi512_i_t axi)
{
	// Only paying attention to write request channel data (not address)
  // since we are only using one buffer in host memory address = 0
  // And a write is always followed by a read of the same size
	
	// Copy the existing buffer into shorter length array
	// (as opposed to wasting resources writing into a byte-index)
	uint8_t data_words[DMA_MSG_WORDS][DMA_WORD_SIZE];
	uint32_t word_i;
	uint32_t byte_i;
	for(word_i=0;word_i<DMA_MSG_WORDS;word_i=word_i+1)
	{
		for(byte_i=0;byte_i<DMA_WORD_SIZE;byte_i=byte_i+1)
		{
			data_words[word_i][byte_i] = deserializer_msg_buffer.data[(word_i*DMA_WORD_SIZE)+byte_i];
		}
	}
	
	// Write into location in word buffer, resetting as needed
	if(axi.wvalid)
	{
		data_words[deserializer_word_pos] = axi.wdata;
		deserializer_word_pos = deserializer_word_pos + 1;
		if(axi.wlast)
		{
				deserializer_word_pos = 0;
		}
	}
	
	// Copy back into byte buffer
	for(word_i=0;word_i<DMA_MSG_WORDS;word_i=word_i+1)
	{
		for(byte_i=0;byte_i<DMA_WORD_SIZE;byte_i=byte_i+1)
		{
			deserializer_msg_buffer.data[(word_i*DMA_WORD_SIZE)+byte_i] = data_words[word_i][byte_i];
		}
	}
	
  // Msg is valid when we have the last word of data
  dma_msg_s msg;
  msg.data = deserializer_msg_buffer;
  msg.valid = axi.wvalid & axi.wlast;
  return msg;
}

// Serialize messages as AXI
// 1. Accept incoming DMA messages ('write data')
// 2. Issue a write response immediately
// 3. Respond with message as 'read data' when requested later
dma_msg_s serializer_msg_buffer;
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
	
	// Message incoming is produced from DMA write
	if(msg.valid)
	{
		// Buffer messages as they come in
		serializer_msg_buffer = msg;
		// Doing so resets serialization
		serializer_word_pos = 0;
		// DMA write needs write response immediately
		axi.bvalid = 1;
	}	
  
  // Only begin serializing response data once requested
  if(read_request)
  {
		serializing = 1;
	}
  
  // Do serializing
  if(serializing)
  {
		// Copy the existing buffer into shorter array
		// (as opposed to wasting resources reading from an byte-index)
		uint8_t data_words[DMA_MSG_WORDS][DMA_WORD_SIZE];
		uint32_t word_i;
		uint32_t byte_i;
		for(word_i=0;word_i<DMA_MSG_WORDS;word_i=word_i+1)
		{
			for(byte_i=0;byte_i<DMA_WORD_SIZE;byte_i=byte_i+1)
			{
				data_words[word_i][byte_i] = serializer_msg_buffer.data.data[(word_i*DMA_WORD_SIZE)+byte_i];
			}
		}
		
		// Select the word to go on the bus 
		uint8_t word[DMA_WORD_SIZE];
		word = data_words[serializer_word_pos];
		
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
