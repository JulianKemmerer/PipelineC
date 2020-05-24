// Code wrapping AXI4 (FPGA) hardware to a common 'DMA message'
// Message buffer is a shift register of AXI-4 words
// (i.e. memory 'seek time' is 1 clk per word position difference from last word)
// There is a message buffer for deserializing and another for serializing

#include "../../axi.h"
#include "dma_msg.h"

// Stream version of message
typedef struct dma_msg_s
{
  dma_msg_t data; // The message
  uint1_t valid;
} dma_msg_s;
dma_msg_s DMA_MSG_S_NULL()
{
  dma_msg_s rv;
  rv.data = DMA_MSG_T_NULL();
  rv.valid = 0;
  return rv;
}
#include "dma_msg_s_array_N_t.h"

// DMA data comes in word chunks of 64B
#define DMA_WORD_SIZE 64
#define LOG2_DMA_WORD_SIZE 6
#define DMA_MSG_WORDS (DMA_MSG_SIZE/DMA_WORD_SIZE)
typedef struct dma_word_buffer_t
{
   uint8_t words[DMA_MSG_WORDS][DMA_WORD_SIZE];
} dma_word_buffer_t;

// Unpack word array into byte array
dma_msg_t deserializer_unpack(dma_word_buffer_t word_buffer)
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

// Parse input AXI-4 to a wider lower duty cycle message stream
// Deserializer state
typedef enum deserializer_state_t {
	ALIGN_WORD_POS,
	DESERIALIZE
} deserializer_state_t;
deserializer_state_t deserializer_state;
// AXI-4 burst begin with address
dma_msg_size_t deserializer_start_word_pos;
uint1_t deserializer_start_word_pos_valid;
// Mesg buffer / output reg
dma_word_buffer_t deserializer_msg_buffer;
uint1_t deserializer_msg_buffer_valid;
// Word position at the front of msg_buffer
dma_msg_size_t deserializer_word_pos;
// Number of pending write responses
dma_msg_size_t deserializer_axi_bursts_num_resp;
// Output
typedef struct deserializer_outputs_t
{
  axi512_write_o_t axi; // Write flow control/response
	dma_msg_s msg_stream; // Outgoing messages
} deserializer_outputs_t;
deserializer_outputs_t deserializer(axi512_write_i_t axi, uint1_t msg_out_ready)
{
  // Output message from register (immediately read global reg to return later)
  deserializer_outputs_t o;
  o.msg_stream.data = deserializer_unpack(deserializer_msg_buffer);
  o.msg_stream.valid = deserializer_msg_buffer_valid;
  // Default not ready for input addr+data yet
  o.axi.ready.awready = 0;
  o.axi.ready.wready = 0;
  // No output write responses yet
  o.axi.resp.bid = 0; // Only ever seen one id?
  o.axi.resp.bresp = 0; // No err
  o.axi.resp.bvalid = 0;
  
  // Respond to write bursts if have pending responses
  if(deserializer_axi_bursts_num_resp > 0)
  {
		o.axi.resp.bvalid = 1;
		// Decrement count if downstream was ready to receive
		if(axi.bready)
		{
			deserializer_axi_bursts_num_resp = deserializer_axi_bursts_num_resp - 1;
		}
  }
  
  // Ready for new address if dont have addr
  if(!deserializer_start_word_pos_valid)
  {
    o.axi.ready.awready = 1;
    deserializer_start_word_pos = axi.req.awaddr >> LOG2_DMA_WORD_SIZE; // / DMA_WORD_SIZE
    deserializer_start_word_pos_valid = axi.req.awvalid;
  }
  
  // Only clear output msg valid if downstream ready
  if(msg_out_ready)
  {
    deserializer_msg_buffer_valid = 0;
  }
  // Can modify the buffer if not trying to output it as valid next iter
  uint1_t can_modify_msg_buffer;
  can_modify_msg_buffer = !deserializer_msg_buffer_valid;
  
  // Dont bother doing anything deserializing write data 
  // unless can write new data into msg buffer
  if(can_modify_msg_buffer)
  {
    // Flag to cause shift buffer to rotate, default not shifting
    uint1_t do_shift_buff_increment_pos;
    do_shift_buff_increment_pos = 0;
    
    // What deserializing state are we actually in?
    
    // Aligning buffer
    if(deserializer_state == ALIGN_WORD_POS)
    {
      // Buffer word pos needs to match 
      // starting axi word addr before leaving this state
      if(deserializer_start_word_pos_valid)
      {
        // Only thing we can do is shift buffer by one if pos doesnt match
        if(deserializer_start_word_pos != deserializer_word_pos)
        {
          do_shift_buff_increment_pos = 1;
        }
        else 
        {
          // No shifting required, done
          deserializer_state = DESERIALIZE;
          // No longer need to hold onto start addr
          deserializer_start_word_pos_valid = 0;
        }
      }
    }
    
    // Last word in message?
    uint1_t at_end_word;
    at_end_word = deserializer_word_pos==DMA_MSG_WORDS-1;
    
    // Deserializing into buffer
    if(deserializer_state == DESERIALIZE)
    {
      // Default ready for more data
      o.axi.ready.wready = 1;
      
      // Read copy of word from front/top (upper addr word) of circular buff
      uint8_t word[DMA_WORD_SIZE];
      word = deserializer_msg_buffer.words[DMA_MSG_WORDS-1];

      // Write incoming data to byte location in word
      uint32_t byte_i;
      byte_i = 0;
      for(byte_i=0; byte_i<DMA_WORD_SIZE; byte_i=byte_i+1)
      {
        if(axi.req.wstrb[byte_i])
        {
          word[byte_i] = axi.req.wdata[byte_i];
        }
      }

      // Handle that write data in word if valid
      // Maybe write incoming data into circular buffer
      if(axi.req.wvalid)
      {
        // Write modified word back into buffer
        deserializer_msg_buffer.words[DMA_MSG_WORDS-1] = word;
        // If current word high bytes written 
        // then next bytes will be for next word, shift buffer
        if(axi.req.wstrb[DMA_WORD_SIZE-1])
        {
          do_shift_buff_increment_pos = 1;
        }
        // Dont shift the buffer if this was the last word in the message
        // (need to keep buffer in place to act as output reg)
        if(at_end_word)
        {
          // Dont shift
          do_shift_buff_increment_pos = 0;
          // Validate output message buffer
          deserializer_msg_buffer_valid = 1;
        }
        
        // Last incoming word of this burst? 
        if(axi.req.wlast)
        {
          // Increment burst count to respond to
          deserializer_axi_bursts_num_resp = deserializer_axi_bursts_num_resp + 1;
          
          // Might need to align pos for next burst
          // Since states are written as pass-through (if,if not if,elseif)
          // can always go to align state and 
          // will pass through back to deser if possible
          deserializer_state = ALIGN_WORD_POS;   
        }
      }
    }
    
    // Shift buffer logic
    if(do_shift_buff_increment_pos)
    {
      // Increment pos for next word with wrap around
      if(at_end_word)
      {
        deserializer_word_pos = 0;
      }
      else
      {
        deserializer_word_pos = deserializer_word_pos + 1;
      }
      
      // Circular buffer
      uint8_t word0[DMA_WORD_SIZE];
      word0 = deserializer_msg_buffer.words[0];
      uint32_t word_i;
      for(word_i=0; word_i<DMA_MSG_WORDS-1; word_i=word_i+1)
      {
        deserializer_msg_buffer.words[word_i] = deserializer_msg_buffer.words[word_i+1];
      }
      deserializer_msg_buffer.words[DMA_MSG_WORDS-1] = word0;
    }
  }

  return o;
}

// Pack byte array into word array buffer
dma_word_buffer_t serializer_pack(dma_msg_t msg)
{
	dma_word_buffer_t word_buffer;
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

// Repsond to reads with serialized messages
// Message buffer / input reg
dma_word_buffer_t serializer_msg;
uint1_t serializer_msg_valid; // Cleared when done serializing msg
// Word position at the front of msg_buffer
dma_msg_size_t serializer_word_pos;
// AXI-4 burst begin with address+size
dma_msg_size_t serializer_start_word_pos;
dma_msg_size_t serializer_start_burst_words;
uint1_t serializer_start_valid;
// General state regs
typedef enum serializer_state_t {
	ALIGN_WORD_POS,
	SERIALIZE
} serializer_state_t;
serializer_state_t serializer_state;
dma_msg_size_t serializer_remaining_burst_words;
// Output
typedef struct serializer_outputs_t
{
  axi512_read_o_t axi; // Read flow control/response
	uint1_t msg_in_ready; // Incoming msg flow control
} serializer_outputs_t;
serializer_outputs_t serializer(dma_msg_s msg_stream, axi512_read_i_t axi)
{	
	// Default output values
  serializer_outputs_t o;
  // Not ready for input messages
  o.msg_in_ready = 0;
  // Not yet ready for read addr
  o.axi.arready = 0;
  // No output read data
  o.axi.resp.rid = 0;
	o.axi.resp.rresp = 0;
	o.axi.resp.rvalid = 0;
	o.axi.resp.rlast = 0;
	uint8_t byte_i;
	for(byte_i=0; byte_i<DMA_WORD_SIZE; byte_i=byte_i+1)
	{
		o.axi.resp.rdata[byte_i] = 0;
	}
  
  // Ready for input msg if dont have one to serialize
  if(!serializer_msg_valid)
  {
    // Input registers at end of function
    // Just signal ready here
    o.msg_in_ready = 1;
  }

  // Ready for new read address+size if dont have one
  if(!serializer_start_valid)
  {
    o.axi.arready = 1;
    serializer_start_word_pos = axi.req.araddr >> LOG2_DMA_WORD_SIZE; // / DMA_WORD_SIZE
    // The burst length for AXI4 is defined as,
	  // Burst_Length = AxLEN[7:0] + 1,
		serializer_start_burst_words = axi.req.arlen + 1;
    serializer_start_valid = axi.req.arvalid;
  }
  
  // Flag to cause shift buffer to rotate, default not shifting
  uint1_t do_shift_buff_increment_pos;
  do_shift_buff_increment_pos = 0;
  
  // What serializing state are we actually in?
	
	// Align shift buffer as needed to output next read burst
	if(serializer_state == ALIGN_WORD_POS)
	{
		// Buffer needs to be valid and word pos needs to match 
    // starting axi word addr before leaving this state
    if(serializer_msg_valid & serializer_start_valid)
    {
      // Only thing we can do is shift buffer by one if pos doesnt match
      if(serializer_word_pos != serializer_start_word_pos)
      {
        do_shift_buff_increment_pos = 1;
      }
      else 
      {
        // No shifting required, done with this state
        serializer_state = SERIALIZE;
        // No longer need to hold onto start info
        serializer_remaining_burst_words = serializer_start_burst_words;
        serializer_start_valid = 0;
      }
    }
	}
	
  // Last word of dma message?
  uint1_t at_end_word;
	at_end_word = serializer_word_pos==DMA_MSG_WORDS-1;
  // Calc next pos with rollover
  dma_msg_size_t next_serializer_word_pos;
  if(at_end_word)
  {
    next_serializer_word_pos = 0;
  }
  else
  {
    next_serializer_word_pos = serializer_word_pos + 1;
  }
  
  // Select the next word from front of buffer
  uint8_t word[DMA_WORD_SIZE];
  word = serializer_msg.words[0];
  
	// Output the data on the bus
	if(serializer_state == SERIALIZE)
	{    
		// Put word on the bus
		o.axi.resp.rdata = word;
		o.axi.resp.rvalid = 1;
    // Last word of this read burst serialization?
		if(serializer_remaining_burst_words==1)
		{
			// End the stream
			o.axi.resp.rlast = 1;
    }
    
		// Increment/next state if downstream was ready to receive 
    if(axi.rready)
    {
      // Record outputting this word
      serializer_remaining_burst_words = serializer_remaining_burst_words - 1;
      // Shift buffer to next word
      do_shift_buff_increment_pos = 1;
      
      // If this is the last word of burst then only part 
      // of the word may have been actually accepted
      // 			DO NOT HAVE A READ STROBE INPUT TO KNOW LIKE WRITE SIDE
      // So instead try to look ahead to next read addr
			if(o.axi.resp.rlast)
			{
				// Default assume dont shift buffer at rlast
				do_shift_buff_increment_pos = 0;
				// Only shift buffer if 
				// we know the next starting addr
				// And that addr would be next
				if(serializer_start_valid)
				{
					if(serializer_start_word_pos == next_serializer_word_pos)
					{
						do_shift_buff_increment_pos = 1;
					}
				}
				
				// Most of the time the next burst starts at next pos
				// and thus doesnt need additional alignment
				// Since states are written as pass-through (if,if not if,elseif)
				// can always go to align state and 
				// will pass through back to serialize if possible
				serializer_state = ALIGN_WORD_POS;
			}
    }
	}
	
	// Do circular buffer shift and wrapping increment when requested
	if(do_shift_buff_increment_pos)
	{
		// Increment pos, w roll over
		serializer_word_pos = next_serializer_word_pos;
    // If rolling over to start then done with this msg
    if(at_end_word)
    {
      serializer_msg_valid = 0;
    }

		// Shift circular buffer
		uint32_t word_i;
		for(word_i=0; word_i<DMA_MSG_WORDS-1; word_i=word_i+1)
		{
			serializer_msg.words[word_i] = serializer_msg.words[word_i+1];
		}
		serializer_msg.words[DMA_MSG_WORDS-1] = word;
	}
	
	// Input regs (assign to global for next iteration)
	// 	Accept message buffer stream if valid and ready to receive
	if(msg_stream.valid & o.msg_in_ready)
	{
		serializer_msg = serializer_pack(msg_stream.data); // Stored by word
		serializer_msg_valid = 1;
		serializer_word_pos = 0; // Resets what address is at front of buffer
	}
  
  return o;
}
