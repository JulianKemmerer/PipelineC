// Code wrapping AXI4 (FPGA) hardware to a common 'DMA message' 

#include "../../axi.h"
#include "dma_msg.h"

// !!!!!!!  WARNING: !!!!!!!!!!!
//		THIS IMPLEMENTATION DOES NOT HAVE FLOW CONTROL LOGIC.
//		ASSUMES ALWAYS READY FOR INPUT AND OUTPUT.

#define DMA_WORD_SIZE 64 
#define LOG2_DMA_WORD_SIZE 6
#define DMA_MSG_WORDS (DMA_MSG_SIZE/DMA_WORD_SIZE)

// Need valid bit per word since words could come out of order apparently? (never seen?)
typedef struct deserializer_word_buffer_t
{
   uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
   uint1_t valids[DMA_MSG_WORDS];
} deserializer_word_buffer_t;

// Unpack word array into byte array
dma_msg_t deserializer_unpack(deserializer_word_buffer_t word_buffer)
{
  // Unpack 2D byte array word buffer into long 1D output byte array
	dma_msg_t msg;
	uint32_t word_i;
	uint32_t byte_i;
	for(word_i=0;word_i<DMA_MSG_WORDS;word_i=word_i+1)
	{
		for(byte_i=0;byte_i<DMA_WORD_SIZE;byte_i=byte_i+1)
		{
			msg.data[(word_i*DMA_WORD_SIZE)+byte_i] = word_buffer.words[word_i][byte_i];
		}
	}
	return msg;
}

// Parse input AXI-4 to a wide lower duty cycle message stream
// Keep track of pos in buffer
dma_msg_size_t deserializer_byte_pos;
deserializer_word_buffer_t deserializer_msg_buffer;
dma_msg_s deserializer(axi512_i_t axi)
{
	// Update address if new one incoming
	if(axi.awvalid)
	{
		deserializer_byte_pos = axi.awaddr;
	}
	dma_msg_size_t word_pos;
	word_pos = deserializer_byte_pos >> LOG2_DMA_WORD_SIZE; // / DMA_WORD_SIZE
	
	// Read the current word at that address
	uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
	words = deserializer_msg_buffer.words;
	uint8_t word[DMA_WORD_SIZE];
	word = words[word_pos];
	
	// Write incoming data into upper/lower/both parts of word
	// Experimentally determined that AXI write comes in 32byte or 64byte chunks
	// Dont need byte specific write strobe, just certain bits of it
	uint1_t keep_lower;
	keep_lower = axi.wstrb[0];
	uint1_t keep_upper;
	keep_upper = axi.wstrb[DMA_WORD_SIZE/2];
	uint32_t byte_i;
	byte_i = 0;
	// Lower
	if(keep_lower)
	{
		for(byte_i=0; byte_i<DMA_WORD_SIZE/2; byte_i=byte_i+1)
		{
			word[byte_i] = axi.wdata[byte_i];
		}
	}
	// Upper
	if(keep_upper)
	{
		for(byte_i=DMA_WORD_SIZE/2; byte_i<DMA_WORD_SIZE; byte_i=byte_i+1)
		{
			word[byte_i] = axi.wdata[byte_i];
		}
	}
	
	// If the write data was valid, write the modified word back into buffer
	if(axi.wvalid)
	{
		// Write word
		uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
		words = deserializer_msg_buffer.words;
		words[word_pos] = word;
		deserializer_msg_buffer.words = words;
		// Write valid
		// This entire word is valid if upper part was written (assume lower already was)
		uint1_t valids[DMA_MSG_WORDS];
		valids = deserializer_msg_buffer.valids;
		valids[word_pos] = keep_upper;
		deserializer_msg_buffer.valids = valids;
		// Increment byte pos
		if(keep_lower & keep_upper)
		{
			deserializer_byte_pos = deserializer_byte_pos + 64;
		}
		else if(keep_lower | keep_upper)
		{
			deserializer_byte_pos = deserializer_byte_pos + 32;
		}
	}
	
	// Unpack message data from word buffer
	dma_msg_s msg;
	msg.data = deserializer_unpack(deserializer_msg_buffer);
	
	// Message done/valid?
	// If all the words are now valid then msg valid + do reset
	uint1_t all_words_done;
	all_words_done = uint1_array_and64(deserializer_msg_buffer.valids);
	msg.valid = all_words_done;
	if(all_words_done)
	{
		// Reset word valids
		uint32_t word_i;
		for(word_i=0; word_i<DMA_MSG_WORDS; word_i = word_i + 1)
		{
			deserializer_msg_buffer.valids[word_i] = 0;
		}
	}

  return msg;
}

// Pack byte array into word array buffer
typedef struct serializer_word_buffer_t
{
   uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
} serializer_word_buffer_t;
serializer_word_buffer_t serializer_pack(dma_msg_t msg)
{
	serializer_word_buffer_t word_buffer;
	uint32_t word_i;
	uint32_t byte_i;
	for(word_i=0;word_i<DMA_MSG_WORDS;word_i=word_i+1)
	{
		for(byte_i=0;byte_i<DMA_WORD_SIZE;byte_i=byte_i+1)
		{
			word_buffer.words[word_i][byte_i] = msg.data[(word_i*DMA_WORD_SIZE)+byte_i];
		}
	}
	return word_buffer;
}

// Serialize messages as AXI
// 1. Respond to writes immediately 
// 2. Buffer incoming DMA messages to serialize
// 3. Since no flow control 
//		N reads can show up back to back repsenting 
//    the software read of the enitre DMA_MSG_SIZE bytes
//    Store/fifo these and respond to each correctly
typedef struct serializer_read_request_t
{
   dma_msg_size_t byte_addr;
   dma_msg_size_t burst_words;
   uint1_t valid;
} serializer_read_request_t;
typedef enum serializer_state_t {
	GET_READ_REQ,
	SERIALIZE
} serializer_state_t;
#define SER_READ_REQ_BUFF_SIZE 4 // Back to back reads to buffer
serializer_read_request_t serializer_read_request_buffer[SER_READ_REQ_BUFF_SIZE];
serializer_word_buffer_t serializer_msg_buffer;
uint1_t serializer_msg_buffer_valid;
serializer_state_t serializer_state;
serializer_read_request_t serializer_curr_read_request;
axi512_o_t serializer(dma_msg_s msg, axi512_i_t axi_in)
{	
	// Start by outputing axi_out defaults
	axi512_o_t axi_out;
	// Can't really do good flow control - yet.
  // This is hacky
  // Ready for write address
  axi_out.awready = 1;
	//  Ready for write data 
  axi_out.wready = 1;
  //  Ready for read address
  axi_out.arready = 1;
	axi_out.bvalid = 0; // Invalid write response
	axi_out.bid = 0;
	axi_out.bresp = 0; // Error code
	axi_out.rvalid = 0; // Invalid read response
	axi_out.rid = 0;
	axi_out.rresp = 0;
	axi_out.rlast = 0;
	uint8_t byte_i;
	for(byte_i=0; byte_i<DMA_WORD_SIZE; byte_i=byte_i+1)
	{
		axi_out.rdata[byte_i] = 0;
	}
	
	// Respond to DMA writes immediately
	if(axi_in.wvalid & axi_in.wlast)
	{
		axi_out.bvalid = 1;
	}
	
	// DMA writes eventually produce an incoming message, buffer it
	if(msg.valid)
	{
		serializer_msg_buffer = serializer_pack(msg.data); // Stored by word
		serializer_msg_buffer_valid = 1;
	}
		
	// Buffer up to N read requests as they come in
	if(axi_in.arvalid)
	{
		// Form new request
		serializer_read_request_t new_read_request;
		new_read_request.byte_addr = axi_in.araddr;
		// The burst length for AXI4 is defined as,
	  // Burst_Length = AxLEN[7:0] + 1,
		new_read_request.burst_words = axi_in.arlen + 1;
		new_read_request.valid = 1;
		// Put at the end of the shiftreg/buffer (assume empty)
		serializer_read_request_buffer[SER_READ_REQ_BUFF_SIZE-1] = new_read_request;	
	}
	
	// What entry is at the front of the buffer?
	serializer_read_request_t next_read_request;
	next_read_request = serializer_read_request_buffer[0];
	
	// Shift out that next request to make room in buffer?
	uint1_t front_empty;
	front_empty = next_read_request.valid == 0;
	// Have msg to serialize and read req buffered?
	uint1_t have_buffers;
	have_buffers = serializer_msg_buffer_valid & next_read_request.valid;
	// And trying to read those buffers?
	uint1_t trying_read_buffers;
	trying_read_buffers = (serializer_state == GET_READ_REQ);
	// Shift if empty or successfully pulling entry from front
	uint1_t do_shift;
	do_shift = front_empty | (have_buffers & trying_read_buffers);
	if(do_shift)
	{
		uint32_t buff_i;
		for(buff_i=0; buff_i < SER_READ_REQ_BUFF_SIZE-1; buff_i = buff_i + 1)
		{
			serializer_read_request_buffer[buff_i] = serializer_read_request_buffer[buff_i+1];
		}
	}
	
	// Do functionality to respond to reads based on state
	if(serializer_state == GET_READ_REQ)
	{
		// Have a buffers ready?
		if(have_buffers)
		{
			// Then start serializing
			serializer_curr_read_request = next_read_request;
			serializer_state = SERIALIZE;
		}
	}
	else if(serializer_state == SERIALIZE)
	{
		// Select the word to go on the bus
		dma_msg_size_t serializer_word_pos;
		serializer_word_pos = serializer_curr_read_request.byte_addr >> LOG2_DMA_WORD_SIZE; // /DMA_WORD_SIZE
		uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
		words = serializer_msg_buffer.words;
		uint8_t word[DMA_WORD_SIZE];
		word = words[serializer_word_pos];
		
		// Put it on the bus
		axi_out.rdata = word;
		axi_out.rvalid = 1;
		
		// Increment pos
		serializer_curr_read_request.byte_addr = serializer_curr_read_request.byte_addr + 64;
		serializer_curr_read_request.burst_words = serializer_curr_read_request.burst_words - 1;
		
		// End this serialization?
		if(serializer_curr_read_request.burst_words==0)
		{
			// End the stream and reset
			axi_out.rlast = 1;
			serializer_curr_read_request.valid = 0;
			serializer_state = GET_READ_REQ;
		}
		
		// Done with the whole message message?
		if(serializer_curr_read_request.byte_addr==DMA_MSG_SIZE)
		{
			serializer_msg_buffer_valid = 0;
		}
	}  
  
  return axi_out;
}
