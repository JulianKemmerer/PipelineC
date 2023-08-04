#pragma PART "xc7a100tcsg324-1" 
#include "compiler.h"
#include "debug_port.h"
#include "arrays.h"
#include "intN_t.h"
#include "uintN_t.h"
//#include "float_e_m_t.h"
//#define float float_8_11_t
#include "global_func_inst.h"
// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
#include "shared_resource_bus.h"

#define DEV_CLK_MHZ 270.0
#define HOST_CLK_MHZ 40.0
#define NUM_THREADS 16

// The pipeline
typedef struct demo_pipeline_in_t{
  float x;
  float y;
}demo_pipeline_in_t;
typedef struct demo_pipeline_out_t{
  float result;
}demo_pipeline_out_t;
demo_pipeline_out_t demo_pipeline_func(demo_pipeline_in_t inputs)
{
  demo_pipeline_out_t rv;
  rv.result = inputs.x + inputs.y;
  return rv;
}


// The shared bus
SHARED_BUS_TYPE_DEF(
  demo_pipeline_bus_t,
  uint1_t, uint1_t, uint1_t, // Dummy write signals
  demo_pipeline_in_t,
  demo_pipeline_out_t
)
SHARED_BUS_DECL(
  demo_pipeline_bus_t,
  uint1_t, uint1_t, uint1_t, // Dummy write signals
  demo_pipeline_in_t,
  demo_pipeline_out_t,
  demo_pipeline_bus,
  NUM_THREADS,
  1
)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 0)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 1)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 2)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 3)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 4)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 5)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 6)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 7)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 8)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 9)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 10)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 11)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 12)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 13)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 14)
SHARED_BUS_ASYNC_FIFO_DECL(demo_pipeline_bus_t, demo_pipeline_bus, 15)
// Wire ASYNC FIFOs to dev-host wires
MAIN_MHZ(demo_pipeline_host_side_fifo_wiring, HOST_CLK_MHZ)
void demo_pipeline_host_side_fifo_wiring()
{
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 0)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 1)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 2)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 3)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 4)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 5)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 6)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 7)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 8)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 9)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 10)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 11)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 12)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 13)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 14)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(demo_pipeline_bus_t, demo_pipeline_bus, 15)
}
MAIN_MHZ(demo_pipeline_dev_side_fifo_wiring, DEV_CLK_MHZ)
void demo_pipeline_dev_side_fifo_wiring()
{
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 0)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 1)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 2)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 3)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 4)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 5)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 6)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 7)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 8)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 9)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 10)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 11)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 12)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 13)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 14)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(demo_pipeline_bus_t, demo_pipeline_bus, 15)
}
// Declare demo_pipeline_pipeline_in/_out wires connected to pipeline instance
GLOBAL_PIPELINE_INST_W_ARB(demo_pipeline_pipeline, demo_pipeline_out_t, demo_pipeline_func, demo_pipeline_in_t, NUM_THREADS)
// User application uses 5 channel AXI-like shared bus wires for dev control
// How DEV port is 'converted' to shared bus connection
// Multi in flight dev_ctrl
// Always ready for inputs from host
// Relies on host always being ready for output from dev
typedef struct demo_pipeline_dev_ctrl_t{
  // ex. dev inputs
  demo_pipeline_in_t dev_inputs;
  uint8_t dev_input_id;
  uint1_t dev_inputs_valid;
  // Bus signals driven to host
  demo_pipeline_bus_t_dev_to_host_t to_host;
}demo_pipeline_dev_ctrl_t;
demo_pipeline_dev_ctrl_t demo_pipeline_dev_ctrl_pipelined(
  // Controller Inputs:
  // Ex. dev outputs
  demo_pipeline_out_t dev_outputs,
  uint8_t dev_output_id,
  uint1_t dev_outputs_valid,
  // Bus signals from the host
  demo_pipeline_bus_t_host_to_dev_t from_host
)
{
  // Connect selected read signals to dev
  demo_pipeline_dev_ctrl_t o;
  // Signal ready for inputs
  o.to_host.read.req_ready = 1;
  // Drive inputs into dev
  o.dev_inputs = from_host.read.req.data.user;
  o.dev_input_id = from_host.read.req.id;
  o.dev_inputs_valid = from_host.read.req.valid;

  // Drive read outputs from dev
  // no flow control ready to push back on into DEV pipeline device
  // Read output data
  o.to_host.read.data.burst.data_resp.user = dev_outputs;
  o.to_host.read.data.burst.last = 1;
  o.to_host.read.data.id = dev_output_id;
  o.to_host.read.data.valid = dev_outputs_valid;
  return o;
}
// Connect hosts to devices
MAIN_MHZ(demo_pipeline_dev_arb_connect, DEV_CLK_MHZ)
void demo_pipeline_dev_arb_connect()
{
  // Arbitrate M hosts to 1 dev
  SHARED_BUS_MULTI_HOST_CONNECT(demo_pipeline_bus_t, demo_pipeline_bus, NUM_THREADS, 1)

  uint32_t j;
  for(j = 0; j < NUM_THREADS; j+=1)
  { 
    // Connect dev controller to multi host ports
    demo_pipeline_dev_ctrl_t dev_ctrl = 
      demo_pipeline_dev_ctrl_pipelined(
        demo_pipeline_pipeline_outs[j],
        demo_pipeline_pipeline_out_ids[j],
        demo_pipeline_pipeline_out_valids[j],
        demo_pipeline_bus_from_hosts[0][j]
      );
    demo_pipeline_pipeline_ins[j] = dev_ctrl.dev_inputs;
    demo_pipeline_pipeline_in_ids[j] = dev_ctrl.dev_input_id;
    demo_pipeline_pipeline_in_valids[j] = dev_ctrl.dev_inputs_valid;
    demo_pipeline_bus_to_hosts[0][j] = dev_ctrl.to_host;
  }
}
// Implement 'demo_pipeline' function call using shared resource bus
demo_pipeline_out_t demo_pipeline(demo_pipeline_in_t inputs)
{
  demo_pipeline_out_t outputs = demo_pipeline_bus_read(inputs);
  return outputs;
}


// Main loop demoing pipeline
uint32_t host_clk_counter;
void main(uint8_t tid)
{
  uint32_t start_time;
  uint32_t end_time;
  demo_pipeline_in_t inputs;
  inputs.x = 1.23;
  inputs.y = 4.56;
  while(inputs.x != 0.0) // So doesnt synth away, need to make execution depend on FP stuff
  {
    // First step in rendering is reset debug counter
    start_time = host_clk_counter;

    // TEST
    printf("Thread %d: Time %d: adding %f + %f\n", tid, start_time, inputs.x, inputs.y);
    demo_pipeline_out_t outputs = demo_pipeline(inputs);
    end_time = host_clk_counter;
    printf("Thread %d: Time %d: %d cycles for result %f + %f = %f\n", tid, end_time, end_time-start_time, inputs.x, inputs.y, outputs.result);
    inputs.y = inputs.x;
    inputs.x = outputs.result;
  }
}
// Wrap up main FSM as top level
#include "main_FSM.h"
MAIN_MHZ(main_wrapper, HOST_CLK_MHZ)
uint1_t main_wrapper()
{
  // Counter lives here on ticking host clock
  static uint32_t host_clk_counter_reg;
  host_clk_counter = host_clk_counter_reg;
  host_clk_counter_reg += 1;
  // Threads of main()
  uint1_t valid_out = 1;
  uint8_t tid;
  for(tid = 0; tid < NUM_THREADS; tid+=1)
  {
    main_INPUT_t i;
    i.input_valid = 1;
    i.tid = tid;
    i.output_ready = 1;
    main_OUTPUT_t o = main_FSM(i);
    valid_out &= o.output_valid;
  }
  return valid_out;
}