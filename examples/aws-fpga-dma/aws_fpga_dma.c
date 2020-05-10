// The top level 'main' function for the AWS FPGA DMA example

#include "../../axi.h"
#include "dma_msg_hw.c"
#include "work_hw.c"

// AWS HDK shell I/O
// Only interface supported is PCIS AXI-4 bus for now
typedef struct aws_fpga_dma_inputs_t
{
  axi512_i_t pcis;
} aws_fpga_dma_inputs_t;
typedef struct aws_fpga_dma_outputs_t
{
  axi512_o_t pcis;
} aws_fpga_dma_outputs_t;

// Clock cross into the work() pipeline
volatile dma_msg_hw_s in_msg;
#include "in_msg_clock_crossing.h"
// Clock cross out of the work() pipeline
volatile dma_msg_hw_s out_msg;
#include "out_msg_clock_crossing.h"

aws_fpga_dma_outputs_t aws_fpga_dma(aws_fpga_dma_inputs_t i)
{
  aws_fpga_dma_outputs_t o;
  
  // Pull messages out of incoming DMA write requests
  deserializer_outputs_t deser_output;
  deser_output = deserializer(i.pcis.write.req);
  // Deserializer says when ready for more writes
  o.pcis.write.ready = deser_output.ready;
  
  // Write the input message stream into work() for processing
	dma_msg_hw_s_array_1_t msgs_in;
	msgs_in.data[0] = deser_output.msg_stream;
	in_msg_WRITE(msgs_in);
	
	// Read output message stream from work()
	dma_msg_hw_s_array_1_t msgs_out;
	msgs_out = out_msg_READ();
  dma_msg_hw_s msg_out;
  msg_out = msgs_out.data[0];
  
  // Put output message into outgoing DMA read data
  // when requested and ready
  serializer_outputs_t serializer_output;
  serializer_output = serializer(msg_out, i.pcis);
  o.pcis.read = serializer_output.read;
  o.pcis.write.resp = serializer_output.write_resp;
  
  return o;
}

// Wraps work() function 
// with data read and written back into main
void work_wrapper()
{
	// Read DMA message bytes from main
  dma_msg_hw_s_array_1_t msgs_in;
  msgs_in = in_msg_READ();
  dma_msg_hw_s msg_in;
  msg_in = msgs_in.data[0];
  
  // TEMP LOOPBACK TEST
  /*
	// Convert incoming DMA message bytes to 'work' inputs
	work_inputs_t work_inputs;
	work_inputs = bytes_to_inputs(msg_in.data);

  // Do some work
  work_outputs_t work_outputs;
  work_outputs = work(work_inputs);

  // Convert 'work' outputs into outgoing DMA message bytes
  dma_msg_s msg_out;
  msg_out.data = outputs_to_bytes(work_outputs);
  msg_out.valid = msg_in.valid;
  */
  // Write DMA message bytes into main
	dma_msg_hw_s_array_1_t msgs_out;
	msgs_out.data[0] = msg_in; //msg_out;
	out_msg_WRITE(msgs_out);
}
