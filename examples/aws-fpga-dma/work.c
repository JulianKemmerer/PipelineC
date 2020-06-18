// Hooks for talking to AWS Shell
#include "aws_fpga_dma.c"

// Definition of work related stuff
#include "work_hw.c"

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
#pragma MAIN_MHZ work_pipeline 150.0
void work_pipeline()
{
  // Read incoming msg from main
  dma_msg_s_array_1_t msgs_in = main_to_work_READ();
  dma_msg_t in_msg = msgs_in.data[0].data;
  
  // Convert bytes to inputs
  work_inputs_t inputs = bytes_to_inputs(in_msg);
  
  // Do work on inputs, get outputs
  work_outputs_t outputs = work(inputs);
  
  // Convert output to bytes
  dma_msg_t out_msg = outputs_to_bytes(outputs);
  
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
#define WORK_MSG_BUF_SIZE 4
#define work_msg_buf_size_t uint3_t // 0-4 , 3 bits

// Define a little FIFO/queue thing to do the buffering
// (no overflow check needed since 
// keeping limit on in flight to buffer size)
dma_msg_s work_msg_buf[WORK_MSG_BUF_SIZE];
dma_msg_s work_msg_buf_func(dma_msg_s in_msg, uint1_t read)
{
  // Shift buffer thing, shift an element forward if possible
  // as elements are read out from front
  
  // Read from front
  dma_msg_s out_msg = work_msg_buf[0];
  // Not validated until read requested
  out_msg.valid = 0;
  if(read)
  {
    out_msg.valid = work_msg_buf[0].valid;
    // Read clears output buffer to allow for shifting forward
    work_msg_buf[0].valid = 0;
  }
  
  // Shift array elements forward if possible
  // Which positions should shift?
  uint1_t pos_do_shift[WORK_MSG_BUF_SIZE];
  pos_do_shift[0] = 0; // Nothing ot left of 0
  work_msg_buf_size_t i;
  for(i=1;i<WORK_MSG_BUF_SIZE;i=i+1)
  {
    // Can shift if next pos is empty
    pos_do_shift[i] = !work_msg_buf[i-1].valid;
  }
  // Do the shifting
  for(i=1;i<WORK_MSG_BUF_SIZE;i=i+1)
  {
    if(pos_do_shift[i])
    {
      work_msg_buf[i-1] = work_msg_buf[i];
      work_msg_buf[i].valid = 0;
    }
  }
  
  // No overflow check, input goes into back of queue, assumed empty
  work_msg_buf[WORK_MSG_BUF_SIZE-1] = in_msg;
  
  return out_msg;  
}

// The main function is used to control the flow of data 
// into and out of the work pipeline
work_msg_buf_size_t work_msgs_in_flight; // Many messages let into the pipeline?
#pragma MAIN_MHZ main 150.0
void main(uint1_t rst)
{
	// Read DMA message data from aws_fpga_dma
  dma_msg_s_array_1_t aws_msgs_in = aws_in_msg_READ();
  dma_msg_s aws_msg_in = aws_msgs_in.data[0];
  
  // Signal ready for this message + validate to msg_to_work
  // if not too many messages in flight
  dma_msg_s msg_to_work = aws_msg_in;
  msg_to_work.valid = 0;
  uint1_t aws_msg_in_ready = 0;
  if(work_msgs_in_flight < WORK_MSG_BUF_SIZE)
  {
    msg_to_work.valid = aws_msg_in.valid;
    aws_msg_in_ready = 1;
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
  dma_msg_s aws_msg_out = work_msg_buf_func(msg_from_work, work_msg_buf_read);
  
  // Message coming out of buffer decrements in flight count
  if(aws_msg_out.valid)
  {
    work_msgs_in_flight = work_msgs_in_flight - 1;
  }
  
  // Write message into aws_fpga_dma
	dma_msg_s_array_1_t aws_msgs_out;
	aws_msgs_out.data[0] = aws_msg_out;
	aws_out_msg_WRITE(aws_msgs_out);
  
  // Reset global state
  if(rst)
  {
    work_msgs_in_flight = 0;
    // TODO actuallly wait for pipeline to flush out remaining in flight
  }
}
