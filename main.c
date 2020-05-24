
#include "examples/fosix/hello_world.c"


/*
#include "examples/aws-fpga-dma/work_hw.c"
#include "examples/aws-fpga-dma/aws_fpga_dma.c"

// Wraps work() function 
// with data read and written back into aws_fpga_dma
#pragma MAIN_MHZ work_wrapper 150.0
void work_wrapper()
{
	// Read ready for output msg flag from aws_fpga_dma
  uint1_t_array_1_t out_readys;
  out_readys = out_msg_ready_READ();
  uint1_t out_ready;
  out_ready = out_readys.data[0];

	// Read DMA message bytes from aws_fpga_dma
  dma_msg_s_array_1_t msgs_in;
  msgs_in = in_msg_READ();
  dma_msg_s msg_in;
  msg_in = msgs_in.data[0];
  */
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
  /*
  // Write ready for input message indicator into aws_fpga_dma
  uint1_t_array_1_t in_readys;
	in_readys.data[0] = out_ready; // Loopback
	in_msg_ready_WRITE(in_readys);
  
  // Write DMA message bytes into aws_fpga_dma
	dma_msg_s_array_1_t msgs_out;
	msgs_out.data[0] = msg_in; //msg_out;
	out_msg_WRITE(msgs_out);
  
}
*/

/*
#include "uintN_t.h"

typedef struct point { 
  uint8_t x;
  uint8_t y;
} point;
//#define OFFSET_NULL { .y = 0, .x = 1 }
point OFFSET_NULL()
{
  point rv;
  rv.y = 0;
  rv.x = 1;
  return rv;
}

typedef struct point2 { 
  point a;
  point b;
} point2;
//#define POINT2_NULL { .a = OFFSET_NULL, .b = OFFSET_NULL }
point2 POINT2_NULL()
{
  point2 rv;
  rv.a = OFFSET_NULL();
  rv.b = OFFSET_NULL();
  return rv;
}

#pragma MAIN_MHZ main 100.0
uint10_t main(point2 p2)
{
  //point2 p2_null = POINT2_NULL;
  point2 p2_null = POINT2_NULL();
  uint10_t rv = (p2.a.x + p2.a.y) + (p2.b.x + p2.b.y) + (p2_null.a.x + p2_null.a.y) + (p2_null.b.x + p2_null.b.y);
  return rv;
}
*/
