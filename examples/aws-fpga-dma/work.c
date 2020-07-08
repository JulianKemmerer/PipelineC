// Hooks for talking to AWS Shell
#include "aws_fpga_dma.c"

// Definition of work related stuff
#include "dma_msg.h"
#include "work.h"
// FIFO modules
#include "../../fifo.h"
// Helper functions to convert DMA bytes to/from 'work' inputs/outputs
// TODO gen all inside work_input_t_bytes_t.h
#include "uint8_t_array_N_t.h" 
#include "uint8_t_bytes_t.h"
#include "int16_t_bytes_t.h"
#include "work_inputs_t_bytes_t.h"
#include "work_outputs_t_bytes_t.h"

// The work pipeline could be massive and we absolutely want it pipelined
// The easiest/clearest way to ensure autopipelining 
// is to isolate the work() logic into its own main function 
// with 'clock crossing'/'message passing' for inputs and outputs

// "Clock crossing" for dma messages from main to work_pipeline
dma_msg_s main_to_work;
#include "main_to_work_clock_crossing.h"
// And reverse for dma messages from work_pipeline to main
dma_msg_s work_to_main;
#include "work_to_main_clock_crossing.h"

// This pipeline does the following:
//    Reads an incoming DMA message from main
//    Converts to work inputs
//    Does work on the work inputs to form the work outputs
//    Work outputs are converted to an outgoing DMA message
//    Writes DMA output message back into main 
#pragma MAIN_MHZ work_pipeline 260.0
void work_pipeline()
{
  // Read incoming msg from main
  dma_msg_s_array_1_t msgs_in = main_to_work_READ();
  dma_msg_t in_msg = msgs_in.data[0].data;
  
  uint32_t i;
  
  // Convert bytes to inputs
  work_inputs_t_bytes_t input_bytes;
  for(i=0; i<sizeof(work_inputs_t); i=i+1)
  {
    input_bytes.data[i] = in_msg.data[i];
  }
  work_inputs_t inputs = bytes_to_work_inputs_t(input_bytes);
  
  // Do work on inputs, get outputs
  work_outputs_t outputs = work(inputs);
  
  // Convert output to bytes
  work_outputs_t_bytes_t output_bytes = work_outputs_t_to_bytes(outputs);
  dma_msg_t out_msg = DMA_MSG_T_NULL();
  for(i=0; i<sizeof(work_outputs_t); i=i+1)
  {
    out_msg.data[i] = output_bytes.data[i];
  }
  
  // Write outgoing msg into main
  dma_msg_s_array_1_t msgs_out;
  msgs_out.data[0].data = out_msg;
  msgs_out.data[0].valid = msgs_in.data[0].valid;
  work_to_main_WRITE(msgs_out);
}

// Multiple work's can be in flight at a time
// However, we can only read them out as fast as the AWS logic allows
// Choose some number to of messages to buffer before not allowing 
// any more messages to come in
#define WORK_MSG_BUF_SIZE 8
#define work_msg_buf_size_t uint4_t // 0-8 , 4 bits
// Define a little FIFO/queue thing to do the buffering
fifo_shift(work_msg_fifo, dma_msg_t, WORK_MSG_BUF_SIZE)

// The main function is used to control the flow of data 
// into and out of the work pipeline
work_msg_buf_size_t work_msgs_in_flight; // Many messages let into the pipeline?
uint1_t work_msg_buf_has_room = 1;
uint1_t overflow; // Should not occur but wanted for debug
#pragma MAIN_MHZ main 260.0
void main(uint1_t rst)
{
	// Read DMA message data from aws_fpga_dma
  dma_msg_s_array_1_t aws_msgs_in = aws_in_msg_READ();
  dma_msg_s aws_msg_in = aws_msgs_in.data[0];
  
  // Signal ready for this message + validate msg_to_work
  // if not too many messages in flight
  dma_msg_s msg_to_work = aws_msg_in;
  msg_to_work.valid = 0;
  // Sanity debug idk wtf is wrong compare to WORK_MSG_BUF_SIZE-1 to be sure?
  // & work_msg_buf_has_room essentially doesnt the 1/2 rate max for slow shift buffer
  uint1_t aws_msg_in_ready = (work_msgs_in_flight < (WORK_MSG_BUF_SIZE-1)) & work_msg_buf_has_room;
  if(aws_msg_in_ready)
  {
    msg_to_work.valid = aws_msg_in.valid;
    // Message into work pipeline increments in flight count
    if(msg_to_work.valid)
    {
      work_msgs_in_flight = work_msgs_in_flight + 1;
    }
  }
  
  // Write ready for input message indicator into aws_fpga_dma
  uint1_t_array_1_t aws_msg_in_readys;
	aws_msg_in_readys.data[0] = aws_msg_in_ready; 
	aws_in_msg_ready_WRITE(aws_msg_in_readys);
  
  // Write the message into the work pipeline
  dma_msg_s_array_1_t msgs_to_work;
  msgs_to_work.data[0] = msg_to_work;
  main_to_work_WRITE(msgs_to_work);
  
  // Read a different message out of the work pipeline
  dma_msg_s_array_1_t msgs_from_work = work_to_main_READ();
  dma_msg_s msg_from_work = msgs_from_work.data[0];
  
  // Read ready for output msg flag from aws_fpga_dma
  uint1_t_array_1_t aws_msg_out_readys = aws_out_msg_ready_READ();
  uint1_t aws_msg_out_ready = aws_msg_out_readys.data[0];
  
  // Write message from work into buffer where it waits for aws_fpga_dma
  // Read from message buffer if aws_fpga_dma is ready
  uint1_t work_msg_buf_read = aws_msg_out_ready;
  work_msg_fifo_t work_msg_fifo_rv = work_msg_fifo(work_msg_buf_read, msg_from_work.data, msg_from_work.valid);
  dma_msg_s aws_msg_out;
  aws_msg_out.data = work_msg_fifo_rv.data_out;
  aws_msg_out.valid = work_msg_fifo_rv.data_out_valid;
  work_msg_buf_has_room = work_msg_fifo_rv.data_in_ready_next;
  
  // Message coming out of buffer decrements in flight count
  if(work_msg_fifo_rv.read_ack) // Same as rd & data_out_valid
  {
    work_msgs_in_flight = work_msgs_in_flight - 1;
  }
  
  // DEBUG
  // Detect overflow
  if(work_msg_fifo_rv.overflow)
  {
    overflow = 1;
  }
  // And put bad data pattern, zeros, into data from now on
  if(overflow)
  {
    // bytes0-3
    aws_msg_out.data.data[0] = 0;
    aws_msg_out.data.data[1] = 0;
    aws_msg_out.data.data[2] = 0;
    aws_msg_out.data.data[3] = 0;
  }
  
  // Write message into aws_fpga_dma
  dma_msg_s_array_1_t aws_msgs_out;
  aws_msgs_out.data[0] = aws_msg_out;
  aws_out_msg_WRITE(aws_msgs_out);
  
  // Reset global state
  if(rst)
  {
    work_msgs_in_flight = 0;
    work_msg_buf_has_room = 1;
    overflow = 0;
    // TODO actuallly wait for pipeline to flush out remaining in flight
  }
}
