#pragma PART "xc7a35ticsg324-1l" 
#define HOST_CLK_MHZ 100.0
#define DEV_CLK_MHZ 25.0
#define NUM_DEV 1
#define NUM_X_THREADS 2
#define NUM_Y_THREADS 2
#define NUM_HOST (NUM_X_THREADS*NUM_Y_THREADS)

// break apart shared bus read and write impl into start and finish
// redo arb to count and enforce number in flight==fifo depth, new args to macro
// and remove buffers in arb, maybe can re-add buffers for timing later
// stateful, flow controlled fan-in muxing valid into dev as dev is ready
// Output is muxed ready from host based on dev id - want library arb to follow flow control
//   todo should be able to drive as constant ready/not looking at ready from dev output

//DO SIM w one device and four 4x faster hosts
// TODO can current SHARED_BUS built in arb do one input per cycle into pipeline?
//  test with fast host clock many threads one in flight
//   and few slow clock devs
//   that should push back and form constant input stream


// TODO GET JUST ONE IN FLIGHT WORKING TO START
// SHARED_BUS_ASYNC_FIFO_DECL size is how many in flight
/*
SUCCESS is autopipeline at device fmax filled by lower fmax threads
    Will eventually need fan-in and fan-out from pipeline to be autopipelined too
How to async stop start?
Using shared resource bus
which has req, resp
need mroe ID support for multi in flight?
AXI read vs write? doesnt matter if single words
  Prefer reads if doesnt matter to extra imply order doesnt matter etc
  If burst then write has input data burst, read has output data burst
    Burst data has ~header/id
  Burst IN+OUT needs to be two operations (write, then read)

Ex. fp_add func

uint32_t id = fp_add_input(uint64_t x, uint64_t y)
uint64_t out = fp_add_output(uint32_t id)

if dont call out w id in same  order and input might stall
*/
#include "intN_t.h"
#include "uintN_t.h"
#include "shared_resource_bus.h"

typedef struct pipeline_input_t
{
  uint64_t x;
  uint64_t y;
}pipeline_input_t;
#define pipeline_output_t uint64_t
pipeline_output_t the_dev_pipeline(pipeline_input_t i)
{
  return i.x + i.y;
}


// TODO bus defs for only one half read/write used?
SHARED_BUS_TYPE_DEF(
  dev_bus, // Bus 'type' name
  uint1_t, // DUMMY Write request type (ex. RAM address)
  uint1_t, // DUMMY Write data type (ex. RAM data)
  uint1_t, // DUMMY Write response type
  pipeline_input_t, // Read request type (ex. RAM address)
  pipeline_output_t // Read data type (ex. RAM data)
)

/*N FP adder devices
and M threads using them*/

SHARED_BUS_DECL(
  dev_bus, // Bus 'type' name
  uint1_t, // DUMMY Write request type (ex. RAM address)
  uint1_t, // DUMMY Write data type (ex. RAM data)
  uint1_t, // DUMMY Write response type
  pipeline_input_t, // Read request type (ex. RAM address)
  pipeline_output_t, // Read data type (ex. RAM data)
  the_bus_name, // Instance name
  NUM_HOST,
  NUM_DEV
)

typedef struct dev_inputs_t{
  pipeline_input_t user;
  id_t id;
  uint1_t valid;
}dev_inputs_t;

typedef struct dev_outputs_t{
  pipeline_output_t user;
  id_t id;
  uint1_t valid;
}dev_outputs_t;

dev_inputs_t dev_input_wires[NUM_DEV];
dev_outputs_t dev_output_wires[NUM_DEV];
#pragma MAIN the_dev_pipelines
void the_dev_pipelines()
{
  // TEMP 1 cycle delay not actually pipelined
  static dev_inputs_t dev_input_regs[NUM_DEV];

  uint32_t i;
  for(i = 0; i < NUM_DEV; i+=1)
  {
    dev_output_wires[i].id = dev_input_regs[i].id;
    dev_output_wires[i].valid = dev_input_regs[i].valid;
    dev_output_wires[i].user = the_dev_pipeline(dev_input_regs[i].user);
  }
  dev_input_regs = dev_input_wires;
}
/*ONE IN FLIGHT dev_ctrl
typedef enum dev_bus_dev_ctrl_state_t
{
  DEV_REQ,
  DEV_RESP
}dev_bus_dev_ctrl_state_t;
typedef struct dev_ctrl_t{
  // ex. dev inputs
  dev_inputs_t dev_inputs;
  // Bus signals driven to host
  dev_bus_dev_to_host_t to_host;
}dev_ctrl_t;
dev_ctrl_t dev_ctrl(
  // Controller Inputs:
  // Ex. dev outputs
  dev_outputs_t dev_outputs,
  // Bus signals from the host
  dev_bus_host_to_dev_t from_host
)
{
  // 5 channels between host and device
  // ONLY USING READ SIGNALS FOR FP ADD
  // TODO make this decl area into macro?
  static dev_ctrl_t o;
  o.to_host.write.req_ready = 0;  // Required since 'o' is static
  o.to_host.write.data_ready = 0; // Required since 'o' is static
  // Input Read req 
  // Output Read resp 
  // Each has a valid+ready handshake buffer
  static dev_bus_read_req_t req;
  static dev_bus_read_data_t resp;
  // Allow one req-data-resp in flight at a time:
  //  Wait for inputs to arrive in input handshake regs w/ things needed req/data
  //  Start operation
  //  Wait for outputs to arrive in output handshake regs, wait for handshake to complete
  static dev_bus_dev_ctrl_state_t state;
  ///////////////////////////////////////////////

  // Signal ready for inputs if buffers are empty
  // Static since o.to_frame_buf written to over multiple cycles
  o.to_host.read.req_ready = !req.valid;

  // Drive outputs from buffers
  o.to_host.read.data = resp;

  // Clear output buffers when ready
  if(from_host.read.data_ready)
  {
    resp.valid = 0;
  }

  // State machine logic feeding signals into dev
  o.dev_inputs.user = req.data.user;
  o.dev_inputs.id = req.id;
  o.dev_inputs.valid = 0;
  if(state==DEV_REQ)
  {
    // Wait for a request
    if(req.valid)
    {
      req.valid = 0; // Done w req now
      o.dev_inputs.valid = 1;
      // Waiting for output read data next
      state = DEV_RESP;
    }
  }

  // PRETEND DEV IS HERE DATAFLOW WISE

  // Outputs from dev flow into output handshake buffers
  if(dev_outputs.valid)
  {
    // Output data single word
    resp.valid = 1;
    resp.id = dev_outputs.id;
    resp.burst.last = 1;
    resp.burst.data_resp.user = dev_outputs.user;
  }

  // State machine logic dealing with ram output signals
  if(state==DEV_RESP) // Read data out of RAM
  {
    // Wait for last valid read data outgoing to host
    if(o.to_host.read.data.valid & o.to_host.read.data.burst.last & from_host.read.data_ready) 
    {
      state = DEV_REQ;
    }
  }

  // Save data into input buffers if signalling ready
  if(o.to_host.read.req_ready)
  {
    req = from_host.read.req;
  }

  return o;
}*/
// Multi in flight dev_ctrl
// Always ready for inputs from host
// Relies on host always being ready for output from dev
typedef struct dev_ctrl_t{
  // ex. dev inputs
  dev_inputs_t dev_inputs;
  // Bus signals driven to host
  dev_bus_dev_to_host_t to_host;
}dev_ctrl_t;
dev_ctrl_t dev_ctrl(
  // Controller Inputs:
  // Ex. dev outputs
  dev_outputs_t dev_outputs,
  // Bus signals from the host
  dev_bus_host_to_dev_t from_host
)
{
  // ONLY USING READ SIGNALS FOR FP ADD
  dev_ctrl_t o;

  // Signal always ready for inputs
  o.to_host.read.req_ready = 1;

  // Drive inputs into dev
  o.dev_inputs.user = from_host.read.req.data.user;
  o.dev_inputs.id = from_host.read.req.id;
  o.dev_inputs.valid = from_host.read.req.valid;

  // Drive outputs from dev
  o.to_host.read.data.burst.data_resp.user = dev_outputs.user;
  o.to_host.read.data.burst.last = 1;
  o.to_host.read.data.id = dev_outputs.id;
  o.to_host.read.data.valid = dev_outputs.valid;

  return o;
}

MAIN_MHZ(dev_arb_connect, DEV_CLK_MHZ)
void dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  // Macro declares the_bus_name_from_host and the_bus_name_to_host
  //SHARED_BUS_ARB(dev_bus, the_bus_name, NUM_DEV)
  SHARED_BUS_ARB_PIPELINED(dev_bus, the_bus_name, NUM_DEV)

  // Connect devs to arbiter ports
  uint32_t i;
  for (i = 0; i < NUM_DEV; i+=1)
  {
    dev_ctrl_t ctrl
      = dev_ctrl(dev_output_wires[i], the_bus_name_from_host[i]);
    dev_input_wires[i] = ctrl.dev_inputs;
    the_bus_name_to_host[i] = ctrl.to_host;
  }
}

SHARED_BUS_ASYNC_FIFO_DECL(dev_bus, the_bus_name, 0)
SHARED_BUS_ASYNC_FIFO_DECL(dev_bus, the_bus_name, 1)
SHARED_BUS_ASYNC_FIFO_DECL(dev_bus, the_bus_name, 2)
SHARED_BUS_ASYNC_FIFO_DECL(dev_bus, the_bus_name, 3)

// Wire ASYNC FIFOs to dev-host wires
MAIN_MHZ(host_side_fifo_wiring, HOST_CLK_MHZ)
void host_side_fifo_wiring()
{
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(dev_bus, the_bus_name, 0)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(dev_bus, the_bus_name, 1)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(dev_bus, the_bus_name, 2)
  SHARED_BUS_ASYNC_FIFO_HOST_WIRING(dev_bus, the_bus_name, 3)
}
MAIN_MHZ(dev_side_fifo_wiring, DEV_CLK_MHZ)
void dev_side_fifo_wiring()
{
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(dev_bus, the_bus_name, 0)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(dev_bus, the_bus_name, 1)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(dev_bus, the_bus_name, 2)
  SHARED_BUS_ASYNC_FIFO_DEV_WIRING(dev_bus, the_bus_name, 3)
}

#define TEST_N_FLIGHT 8
void accum_test()
{
  // Keep adding the sum to itself, 1+1,2+2,4+4,etc
  pipeline_output_t test_val = 1;
  while(1){
    uint32_t i;
    // Start N device operations
    for (i = 0; i < TEST_N_FLIGHT; i+=1)
    {
      pipeline_input_t ins;
      ins.x = test_val;
      ins.y = test_val;
      the_bus_name_read_start(ins);
      test_val += 1;
    }
    // Finish N device operations
    for (i = 0; i < TEST_N_FLIGHT; i+=1)
    {
      test_val = the_bus_name_read_finish();
    }
  }
}
#include "accum_test_FSM.h"


// Module instantiating multiple simultaneous 'threads'
void threads()
{
  // Wire up N parallel instances
  uint1_t thread_done[NUM_X_THREADS][NUM_Y_THREADS];
  uint32_t i,j;
  uint1_t all_threads_done;
  while(!all_threads_done)
  {
    accum_test_INPUT_t fsm_in[NUM_X_THREADS][NUM_Y_THREADS];
    accum_test_OUTPUT_t fsm_out[NUM_X_THREADS][NUM_Y_THREADS];
    all_threads_done = 1;
    for (i = 0; i < NUM_X_THREADS; i+=1)
    {
      for (j = 0; j < NUM_Y_THREADS; j+=1)
      {
        all_threads_done &= thread_done[i][j];
      }
    }
    
    for (i = 0; i < NUM_X_THREADS; i+=1)
    {
      for (j = 0; j < NUM_Y_THREADS; j+=1)
      {
        if(!thread_done[i][j])
        {
          fsm_in[i][j].input_valid = 1;
          fsm_in[i][j].output_ready = 1;
          fsm_out[i][j] = accum_test_FSM(fsm_in[i][j]);
          thread_done[i][j] = fsm_out[i][j].output_valid;
        }
        //all_threads_done &= thread_done[i][j]; // Longer path
      }
    }
    __clk(); // REQUIRED
  }
}
// Wrap up FSM as top level
#include "threads_FSM.h"
MAIN_MHZ(threads_wrapper, HOST_CLK_MHZ)
void threads_wrapper()
{
  threads_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  threads_OUTPUT_t o = threads_FSM(i);
}