// Code wrapping AXI4 (FPGA) hardware to a common 'DMA message'
// Message buffer is a shift register of AXI-4 words
// (i.e. memory 'seek time' is 1 clk per word position difference from last word)
// There is a message buffer for deserializing and another for serializing

#include "../../axi.h"
#include "../../xstr.h"
#include "dma_msg.h"
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
// Written as raw vhdl for faster compile time
#pragma FUNC_WIRES dma_word_buffer_unpack
dma_msg_t dma_word_buffer_unpack(dma_word_buffer_t word_buffer)
{
__vhdl__("\
begin \n\
  -- Unpack 2D byte array word buffer into long 1D output byte array \n\
  word_i_gen : for word_i in 0 to (" xstr(DMA_MSG_WORDS) "-1) generate  \n\
    byte_i_gen : for byte_i in 0 to (" xstr(DMA_WORD_SIZE) "-1) generate  \n\
      return_output.data((word_i*" xstr(DMA_WORD_SIZE) ")+byte_i) <= word_buffer.words(word_i)(byte_i);  \n\
    end generate; \n\
  end generate; \n\
  ");
}
// Pack byte array into word array buffer
// Written as raw vhdl for faster compile time
#pragma FUNC_WIRES dma_msg_pack
dma_word_buffer_t dma_msg_pack(dma_msg_t msg)
{
__vhdl__("\
begin \n\
  word_i_gen : for word_i in 0 to (" xstr(DMA_MSG_WORDS) "-1) generate \n\
    byte_i_gen : for byte_i in 0 to (" xstr(DMA_WORD_SIZE) "-1) generate \n\
      return_output.words(word_i)(byte_i) <= msg.data((word_i*" xstr(DMA_WORD_SIZE) ")+byte_i);  \n\
    end generate; \n\
  end generate; \n\
  ");
}

// Pre mimicing serializer and increasing latency to meet timing:
//    aws_deserializer Path delay (ns): 1.967 = 508.388408744 MHz
// Post:
//    aws_deserializer Path delay (ns): 1.643 = 608.642726719 MHz

// Parse input AXI-4 to a wider lower duty cycle message stream
// Deserializer state
typedef enum aws_deserializer_state_t {
  ALIGN_WORD_POS,
  DESERIALIZE
} aws_deserializer_state_t;
aws_deserializer_state_t aws_deserializer_state;
// AXI-4 burst begin with address and id
dma_msg_size_t aws_deserializer_start_word_pos;
axi_id_t aws_deserializer_start_id;
uint1_t aws_deserializer_start_valid;
// Mesg buffer / output reg
dma_word_buffer_t aws_deserializer_msg_buffer;
uint1_t aws_deserializer_msg_buffer_valid;
// Word position at the front of msg_buffer
dma_msg_size_t aws_deserializer_word_pos;
// The pending write response
uint1_t aws_deserializer_resp_pending;
axi_id_t aws_deserializer_resp_id;
uint1_t aws_deserializer_resp_id_valid;
// Output
typedef struct aws_deserializer_outputs_t
{
  axi512_write_o_t axi; // Write flow control/response
  dma_msg_s msg_stream; // Outgoing messages
} aws_deserializer_outputs_t;
aws_deserializer_outputs_t aws_deserializer(axi512_write_i_t axi, uint1_t msg_out_ready, uint1_t rst)
{
  // Output message from register (immediately read global reg to return later)
  aws_deserializer_outputs_t o;
  o.msg_stream.data = dma_word_buffer_unpack(aws_deserializer_msg_buffer);
  o.msg_stream.valid = aws_deserializer_msg_buffer_valid;
  // Default not ready for input addr+data yet
  o.axi.ready.awready = 0;
  o.axi.ready.wready = 0;
  // No output write responses yet
  o.axi.resp.bid = 0;
  o.axi.resp.bresp = 0; // No err
  o.axi.resp.bvalid = 0;
  
  // Ready for new start info if dont have valid info yet
  o.axi.ready.awready = !aws_deserializer_start_valid;
  
  // Can modify the buffer if not trying to output it as valid
  uint1_t can_modify_msg_buffer;
  can_modify_msg_buffer = !aws_deserializer_msg_buffer_valid;
  // Only clear output msg valid if downstream ready
  if(msg_out_ready)
  {
    aws_deserializer_msg_buffer_valid = 0;
  }
  
  // Form response of pending response id
  uint1_t resp_pending = aws_deserializer_resp_pending;
  o.axi.resp.bvalid = aws_deserializer_resp_id_valid;
  o.axi.resp.bid = aws_deserializer_resp_id;
  // Clear response if was ready for response, no longer needed
  if(axi.bready)
  {
    aws_deserializer_resp_id_valid = 0;
    // No longer pending if was valid
    if(o.axi.resp.bvalid)
    {
      aws_deserializer_resp_pending = 0;
    }
  }
  
  // Dont bother doing anything deserializing write data 
  // unless can write new data into msg buffer
  if(can_modify_msg_buffer)
  {
    // Flag to cause shift buffer to rotate, default not shifting
    uint1_t do_shift_buff_increment_pos;
    do_shift_buff_increment_pos = 0;
    
    // Last word in message?
    uint1_t at_end_word;
    at_end_word = aws_deserializer_word_pos==DMA_MSG_WORDS-1;
    
    // What deserializing state are we actually in?
    
    // Aligning buffer
    if(aws_deserializer_state == ALIGN_WORD_POS)
    {
      // Buffer word pos needs to match 
      // starting axi word addr before leaving this state
      if(aws_deserializer_start_valid)
      {
        // Only thing we can do is shift buffer by one if pos doesnt match
        if(aws_deserializer_start_word_pos != aws_deserializer_word_pos)
        {
          do_shift_buff_increment_pos = 1;
        }
        else 
        {
          // No more shifting required
          // Final check that not waiting on prev pending response
          if(!resp_pending)
          {
            // Ready to begin deserializing data
            aws_deserializer_state = DESERIALIZE;
            // No longer need to hold onto start info
            aws_deserializer_resp_id = aws_deserializer_start_id;
            aws_deserializer_start_valid = 0;
            // Resp ID not validated until end of data stream
            // But is 'pending' starting now
            aws_deserializer_resp_pending = 1;
          }
        }
      }
    }
    // Deserializing into buffer
    else if(aws_deserializer_state == DESERIALIZE)
    {
      // Default ready for more data
      o.axi.ready.wready = 1;
      
      // Read copy of word from front/top (upper addr word) of circular buff
      uint8_t word[DMA_WORD_SIZE];
      word = aws_deserializer_msg_buffer.words[DMA_MSG_WORDS-1];

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
        aws_deserializer_msg_buffer.words[DMA_MSG_WORDS-1] = word;
        // If current word high bytes written 
        // then next bytes will be for next word, shift buffer
        if(axi.req.wstrb[DMA_WORD_SIZE-1])
        {
          do_shift_buff_increment_pos = 1;
          // Dont shift the buffer if this was the last word in the message
          // (need to keep buffer in place to act as output reg)
          if(at_end_word)
          {
            // Dont shift
            do_shift_buff_increment_pos = 0;
            // Validate output message buffer
            aws_deserializer_msg_buffer_valid = 1;
          }
        }
        
        // Last incoming word of this burst? 
        if(axi.req.wlast)
        {
          // Validate the resp id now so it can be used
          aws_deserializer_resp_id_valid = 1;
          
          // Might need to align pos for next burst
          // If low latency needed can do look ahead
          aws_deserializer_state = ALIGN_WORD_POS;   
        }
      }
    }
    
    // Shift buffer logic
    if(do_shift_buff_increment_pos)
    {
      // Increment pos for next word with wrap around
      if(at_end_word)
      {
        aws_deserializer_word_pos = 0;
      }
      else
      {
        aws_deserializer_word_pos = aws_deserializer_word_pos + 1;
      }
      
      // Circular buffer
      uint8_t word0[DMA_WORD_SIZE];
      word0 = aws_deserializer_msg_buffer.words[0];
      uint32_t word_i;
      for(word_i=0; word_i<DMA_MSG_WORDS-1; word_i=word_i+1)
      {
        aws_deserializer_msg_buffer.words[word_i] = aws_deserializer_msg_buffer.words[word_i+1];
      }
      aws_deserializer_msg_buffer.words[DMA_MSG_WORDS-1] = word0;
    }
  }
  
  // Accept new start info if ready
  if(o.axi.ready.awready)
  {
    aws_deserializer_start_word_pos = axi.req.awaddr >> LOG2_DMA_WORD_SIZE; // / DMA_WORD_SIZE
    aws_deserializer_start_id = axi.req.awid;
    aws_deserializer_start_valid = axi.req.awvalid;
  }
  
  // Reset
  if(rst)
  {
    aws_deserializer_state = ALIGN_WORD_POS;
    aws_deserializer_start_valid = 0;
    aws_deserializer_msg_buffer_valid = 0;
    aws_deserializer_word_pos = 0;
    aws_deserializer_resp_pending = 0;
    aws_deserializer_resp_id_valid = 0;
  }

  return o;
}

// Pre moving aws_serializer_start_valid 
//  to be more like input reg and not pass through data
//  and not pass-through ALIGN->SERIALIZE
//    aws_serializer Path delay (ns): 2.256 = 443.262411348 MHz
// Post: 
//    aws_serializer Path delay (ns): 1.479 = 676.132521974 MHz

// Repsond to reads with serialized messages
// Message buffer / input reg
dma_word_buffer_t aws_serializer_msg;
uint1_t aws_serializer_msg_valid; // Cleared when done serializing msg
// Word position at the front of msg_buffer
dma_msg_size_t aws_serializer_word_pos;
// Current read id being serialized out
axi_id_t aws_serializer_id;
// AXI-4 burst begin with address+size+id
dma_msg_size_t aws_serializer_start_word_pos;
dma_msg_size_t aws_serializer_start_burst_words;
axi_id_t aws_serializer_start_id;
uint1_t aws_serializer_start_valid;
// General state regs
typedef enum aws_serializer_state_t {
  ALIGN_WORD_POS,
  SERIALIZE
} aws_serializer_state_t;
aws_serializer_state_t aws_serializer_state;
dma_msg_size_t aws_serializer_remaining_burst_words;
// Output
typedef struct aws_serializer_outputs_t
{
  axi512_read_o_t axi; // Read flow control/response
  uint1_t msg_in_ready; // Incoming msg flow control
} aws_serializer_outputs_t;
aws_serializer_outputs_t aws_serializer(dma_msg_s msg_stream, axi512_read_i_t axi, uint1_t rst)
{ 
  // Default output values
  aws_serializer_outputs_t o;
  // Not ready for input messages
  o.msg_in_ready = 0;
  // Not yet ready for read addr
  o.axi.arready = 0;
  // No output read data
  o.axi.resp.rid = aws_serializer_id;
  o.axi.resp.rresp = 0; // No err
  o.axi.resp.rvalid = 0;
  o.axi.resp.rlast = 0;
  // Default data bytes are just whatever is at front of buffer
  // Select the next word from front of buffer
  uint8_t word[DMA_WORD_SIZE];
  word = aws_serializer_msg.words[0];
  o.axi.resp.rdata = word;
  
  // Ready for new read address+size if dont have it now
  o.axi.arready = !aws_serializer_start_valid;
  
  // Ready for new msg if dont have one
  o.msg_in_ready = !aws_serializer_msg_valid;
  
  // Flag to cause shift buffer to rotate, default not shifting
  uint1_t do_shift_buff_increment_pos = 0;
  
  // Last word of dma message?
  uint1_t at_end_word = aws_serializer_word_pos==DMA_MSG_WORDS-1;
  // Calc next pos with rollover
  dma_msg_size_t next_serializer_word_pos;
  if(at_end_word)
  {
    next_serializer_word_pos = 0;
  }
  else
  {
    next_serializer_word_pos = aws_serializer_word_pos + 1;
  }
  
  // What serializing state are we actually in?
  
  // Align shift buffer as needed to output next read burst
  if(aws_serializer_state == ALIGN_WORD_POS)
  {
    // TODO BUG!?:
    // aws_serializer_msg_valid might be prev message keeping valid
    //    in case of reading end word again
    // We clear aws_serializer_msg_valid when rolling over for next addr
    // BUT MIGHT NOT HAVE NEXT starting ADDR EVER, might need to 
    // accept another input message for control logic flow to continue
    // This module could/will? get stuck in never ready state when from SW
    // it appears that all data was read and should be ready for new MSG
    // Not being ready for more input data when software isnt asking for more
    // isnt necessarily bad but feels weird...
    
    // Buffer needs to be valid and word pos needs to match 
    // starting axi word addr before leaving this state
    if(aws_serializer_msg_valid & aws_serializer_start_valid)
    {
      // Only thing we can do is shift buffer by one if pos doesnt match
      if(aws_serializer_word_pos != aws_serializer_start_word_pos)
      {
        do_shift_buff_increment_pos = 1;
      }
      else 
      {
        // No shifting required, done with this state
        aws_serializer_state = SERIALIZE;
        // No longer need to hold onto start info
        aws_serializer_remaining_burst_words = aws_serializer_start_burst_words;
        aws_serializer_id = aws_serializer_start_id;
        aws_serializer_start_valid = 0;
      }
    }
  }
  // Output the data on the bus
  else if(aws_serializer_state == SERIALIZE)
  {    
    // Put word on the bus
    //o.axi.resp.rdata = word; // Already default
    //o.axi.resp.rid = aws_serializer_id; // Already default
    o.axi.resp.rvalid = 1;
    // Last word of this read burst serialization?
    o.axi.resp.rlast = aws_serializer_remaining_burst_words==1;
    
    // Increment/next state if downstream was ready to receive 
    if(axi.rready)
    {
      // Record outputting this word
      aws_serializer_remaining_burst_words = aws_serializer_remaining_burst_words - 1;
      // Shift buffer to next word
      do_shift_buff_increment_pos = 1;
      
      // If this is the last word of burst then only part 
      // of the word may have been actually accepted
      //      DO NOT HAVE A READ STROBE INPUT TO KNOW LIKE WRITE SIDE
      // So instead try to look ahead to next read addr
      if(o.axi.resp.rlast)
      {
        // Default assume dont shift buffer at rlast
        do_shift_buff_increment_pos = 0;
        
        // Below look ahead is unecessary - 
        //  can add back inalong with pass through ALIGN->SERIAL if low latency is needed
        // Only shift buffer if 
        // we know the next starting addr
        // And that addr would be next
        //if(aws_serializer_start_valid)
        //{
        //  if(aws_serializer_start_word_pos == next_serializer_word_pos)
        //  {
        //    do_shift_buff_increment_pos = 1;
        //  }
        //}
        
        // Most of the time the next burst starts at next pos
        // and thus doesnt need additional alignment
        // Since states are written as pass-through (if,if not if,elseif)
        // can always go to align state and 
        // will pass through back to serialize if possible
        aws_serializer_state = ALIGN_WORD_POS;
      }
    }
  }
  
  // Do circular buffer shift and wrapping increment when requested
  if(do_shift_buff_increment_pos)
  {
    // Increment pos, w roll over
    aws_serializer_word_pos = next_serializer_word_pos;
    // Shifting and at end word = rolling over to start
    // ---If while outputing valid data then done with this msg
    // --- Ex. & aws_serializer_state == SERIALIZE, in case was stuck in ALIGN_WORD_POS?
    // CANT DO THIS ^^^---
    // if next start burst addr is not known yet but is start of new msg
    // then does not shift buffer in SERIALIZE, does not hit this if
    // Would roll over to new message start in ALIGN_WORD_POS
    // 
    // This simple logic makes alot of sense, if the buffer is rolling over
    // then whatever above logic knows we want to get rid of msg valid
    if(at_end_word) //& o.axi.resp.rvalid) 
    {
      aws_serializer_msg_valid = 0;
    }

    // Shift circular buffer
    uint32_t word_i;
    for(word_i=0; word_i<DMA_MSG_WORDS-1; word_i=word_i+1)
    {
      aws_serializer_msg.words[word_i] = aws_serializer_msg.words[word_i+1];
    }
    aws_serializer_msg.words[DMA_MSG_WORDS-1] = word;
  }
  
  // INPUT REGS (assign to global for next iteration)
  //  START INFO
  //  Accept start addr,len,etc if ready
  if(o.axi.arready)
  {
    aws_serializer_start_word_pos = axi.req.araddr >> LOG2_DMA_WORD_SIZE; // / DMA_WORD_SIZE
    // The burst length for AXI4 is defined as,
    // Burst_Length = AxLEN[7:0] + 1,
    aws_serializer_start_burst_words = axi.req.arlen + 1;
    aws_serializer_start_id = axi.req.arid;
    aws_serializer_start_valid = axi.req.arvalid;
  }
  //  DMA MSG
  //  Accept message buffer stream if valid and ready to receive
  if(msg_stream.valid & o.msg_in_ready)
  {
    aws_serializer_msg = dma_msg_pack(msg_stream.data); // Stored by word
    aws_serializer_msg_valid = 1;
    aws_serializer_word_pos = 0; // Resets what address is at front of buffer
  }
  
  // Reset
  if(rst)
  {
    aws_serializer_msg_valid = 0;
    aws_serializer_start_valid = 0;
    aws_serializer_state = ALIGN_WORD_POS;
  }
  
  return o;
}
