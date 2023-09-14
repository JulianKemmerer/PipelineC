#include "compiler.h"
#include "uintN_t.h"
#include "global_func_inst.h"
// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
#include "shared_resource_bus.h"

// Using this file as a hacky macro for looping to declare variable number of async fifos in shared resource bus decl
#define SHARED_RESOURCE_BUS_PIPELINE_TYPE_NAME  PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_bus_t)

// Bus typedef info
#define SHARED_RESOURCE_BUS_TYPE_NAME     SHARED_RESOURCE_BUS_PIPELINE_TYPE_NAME
#define SHARED_RESOURCE_BUS_WR_REQ_TYPE   uint1_t // Dummy write signals
#define SHARED_RESOURCE_BUS_WR_DATA_TYPE  uint1_t
#define SHARED_RESOURCE_BUS_WR_RESP_TYPE  uint1_t
#define SHARED_RESOURCE_BUS_RD_REQ_TYPE   SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE
#define SHARED_RESOURCE_BUS_RD_DATA_TYPE  SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE
SHARED_BUS_TYPE_DEF(
  SHARED_RESOURCE_BUS_TYPE_NAME,
  SHARED_RESOURCE_BUS_WR_REQ_TYPE, SHARED_RESOURCE_BUS_WR_DATA_TYPE, SHARED_RESOURCE_BUS_WR_RESP_TYPE, 
  SHARED_RESOURCE_BUS_RD_REQ_TYPE,
  SHARED_RESOURCE_BUS_RD_DATA_TYPE
)
// Bus instance info and instantiation
#define SHARED_RESOURCE_BUS_NAME          SHARED_RESOURCE_BUS_PIPELINE_NAME
#define SHARED_RESOURCE_BUS_HOST_PORTS    SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS
#define SHARED_RESOURCE_BUS_HOST_CLK_MHZ  SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_DEV_PORTS     1
#define SHARED_RESOURCE_BUS_DEV_CLK_MHZ   SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ
#include "shared_resource_bus_decl.h"

// Declare _pipeline_in/_out wires connected to pipeline instance
GLOBAL_PIPELINE_INST_W_ARB(PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_pipeline), SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE, SHARED_RESOURCE_BUS_PIPELINE_FUNC, SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE, SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS)

// User application uses 5 channel AXI-like shared bus wires for dev control
// How DEV port is 'converted' to shared bus connection
// Multi in flight dev_ctrl
// Always ready for inputs from host
// Relies on host always being ready for output from dev
typedef struct PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_ctrl_t){
  // ex. dev inputs
  SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE dev_inputs;
  uint8_t dev_input_id;
  uint1_t dev_inputs_valid;
  // Bus signals driven to host
  PPCAT(SHARED_RESOURCE_BUS_PIPELINE_TYPE_NAME,_dev_to_host_t) to_host;
}PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_ctrl_t);
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_ctrl_pipelined))
PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_ctrl_t) PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_ctrl_pipelined)(
  // Controller Inputs:
  // Ex. dev outputs
  SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE dev_outputs,
  uint8_t dev_output_id,
  uint1_t dev_outputs_valid,
  // Bus signals from the host
  PPCAT(SHARED_RESOURCE_BUS_PIPELINE_TYPE_NAME,_host_to_dev_t) from_host
)
{
  // Connect selected read signals to dev
  PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_ctrl_t) o;
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
MAIN_MHZ(PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_arb_connect), SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ)
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_arb_connect))
void PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_arb_connect)()
{
  // Arbitrate M hosts to 1 dev - read only use for auto pipelines right now
  SHARED_BUS_MULTI_HOST_READ_ONLY_CONNECT(SHARED_RESOURCE_BUS_PIPELINE_TYPE_NAME, SHARED_RESOURCE_BUS_PIPELINE_NAME, SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS, 1)

  uint32_t j;
  for(j = 0; j < SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS; j+=1)
  { 
    // Connect dev controller to multi host ports
    PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_ctrl_t) dev_ctrl = 
      PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_dev_ctrl_pipelined)(
        PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_pipeline_outs)[j],
        PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_pipeline_out_ids)[j],
        PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_pipeline_out_valids)[j],
        PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_from_hosts)[0][j]
      );
    PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_pipeline_ins)[j] = dev_ctrl.dev_inputs;
    PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_pipeline_in_ids)[j] = dev_ctrl.dev_input_id;
    PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_pipeline_in_valids)[j] = dev_ctrl.dev_inputs_valid;
    PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_to_hosts)[0][j] = dev_ctrl.to_host;
  }
}

// Implement 'SHARED_RESOURCE_BUS_PIPELINE_NAME' function call using shared resource bus
SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE SHARED_RESOURCE_BUS_PIPELINE_NAME(SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE inputs)
{
  SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE outputs = PPCAT(SHARED_RESOURCE_BUS_PIPELINE_NAME,_read)(inputs);
  return outputs;
}


#undef SHARED_RESOURCE_BUS_PIPELINE_NAME
#undef SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE
#undef SHARED_RESOURCE_BUS_PIPELINE_FUNC
#undef SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE
#undef SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS
#undef SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ
#undef SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ
#undef SHARED_RESOURCE_BUS_PIPELINE_TYPE_NAME