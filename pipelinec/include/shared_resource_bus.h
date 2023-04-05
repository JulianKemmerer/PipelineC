#include "uintN_t.h"
#include "compiler.h"

// Generic AXI-like bus with data,valid,ready ~5 channel read,write req,resp
// Generic 5 channel bus
// 3 write, 2 read

typedef enum shared_res_bus_write_state_t
{
  REQ_STATE,
  DATA_STATE,
  RESP_STATE
}shared_res_bus_write_state_t;

typedef enum shared_res_bus_read_state_t
{
  REQ_STATE,
  RESP_STATE
}shared_res_bus_read_state_t;

typedef enum shared_res_bus_dev_arb_state_t
{
  REQ,
  RD_DATA,
  WR_DATA,
  WR_RESP_STATE
}shared_res_bus_dev_arb_state_t;

#define SHARED_BUS_DECL( \
  name, \
  NUM_HOST_PORTS, \
  NUM_DEV_PORTS, \
  write_req_data_t, write_data_word_t, write_resp_data_t, \
  read_req_data_t, read_data_resp_word_t \
)\
typedef struct name##_write_req_t \
{ \
  write_req_data_t data; \
  id_t id; \
  uint1_t valid; \
}name##_write_req_t; \
\
typedef struct name##_write_burst_word_t \
{ \
  write_data_word_t data_word; \
  uint1_t last; \
} name##_write_burst_word_t; \
\
typedef struct name##_write_data_t \
{ \
  name##_write_burst_word_t burst; \
  id_t id; /*AXI3 only*/ \
  uint1_t valid; \
} name##_write_data_t; \
\
typedef struct name##_write_resp_t \
{ \
  write_resp_data_t data; \
  id_t id; \
  uint1_t valid; \
} name##_write_resp_t; \
\
typedef struct name##_write_host_to_dev_t \
{ \
  name##_write_req_t req; \
  name##_write_data_t data; \
  /*  Read to receive write responses*/\
  uint1_t resp_ready; \
} name##_write_host_to_dev_t; \
\
typedef struct name##_write_dev_to_host_t \
{ \
  name##_write_resp_t resp; \
  /*  Ready for write request/address*/\
  uint1_t req_ready; \
	/*  Ready for write data */\
  uint1_t data_ready; \
} name##_write_dev_to_host_t;\
\
typedef struct name##_read_req_t \
{ \
  read_req_data_t data; \
  id_t id; \
  uint1_t valid; \
} name##_read_req_t; \
 \
typedef struct name##_read_burst_word_t \
{ \
  read_data_resp_word_t data_resp; \
  uint1_t last; \
}name##_read_burst_word_t; \
 \
typedef struct name##_read_data_t \
{ \
  name##_read_burst_word_t burst; \
  id_t id; \
  uint1_t valid; \
} name##_read_data_t; \
 \
typedef struct name##_read_host_to_dev_t \
{ \
  name##_read_req_t req; \
  /*  Ready to receive read data (bytes+resp)*/ \
  uint1_t data_ready; \
} name##_read_host_to_dev_t; \
 \
typedef struct name##_read_dev_to_host_t \
{ \
  name##_read_data_t data; \
  /*  Ready for read address*/ \
  uint1_t req_ready; \
} name##_read_dev_to_host_t; \
 \
typedef struct name##_host_to_dev_t \
{ \
  /* Write Channel*/ \
  name##_write_host_to_dev_t write; \
  /* Read Channel*/ \
  name##_read_host_to_dev_t read; \
} name##_host_to_dev_t; \
 \
typedef struct name##_dev_to_host_t \
{ \
  /* Write Channel*/ \
  name##_write_dev_to_host_t write; \
  /* Read Channel */ \
  name##_read_dev_to_host_t read; \
} name##_dev_to_host_t; \
 \
/* Write has two channels to begin request: address and data */ \
/* Helper func to write one write_data_word_t requires that inputs are valid/held constant*/ \
/* until data phase done (ready_for_inputs asserted)*/ \
typedef struct name##_write_logic_outputs_t \
{ \
  name##_host_to_dev_t to_dev; \
  write_resp_data_t resp; \
  uint1_t done; \
  uint1_t ready_for_inputs; \
}name##_write_logic_outputs_t; \
name##_write_logic_outputs_t name##_write_logic( \
  write_req_data_t req, /* uint32_t addr,*/ \
  write_data_word_t data, /* uint32_t data,*/ \
  uint1_t ready_for_outputs,  \
  name##_dev_to_host_t from_dev \
){ \
  static shared_res_bus_write_state_t state; \
  name##_write_logic_outputs_t o; \
  if(state==REQ_STATE) \
  { \
    /* Wait device to be ready for write address first*/ \
    if(from_dev.write.req_ready) \
    { \
      /* Use inputs to form valid address*/ \
      o.to_dev.write.req.valid = 1; \
      o.to_dev.write.req.data = req; \
      /* And then data next*/ \
      state = DATA_STATE; \
    } \
  } \
  else if(state==DATA_STATE) \
  { \
    /* Wait device to be ready for write data*/ \
    if(from_dev.write.data_ready) \
    { \
      /* Signal finally ready for inputs since data completes write request*/ \
      o.ready_for_inputs = 1; \
      /* Send valid data transfer*/ \
      o.to_dev.write.data.valid = 1; \
      o.to_dev.write.data.burst.last = 1; \
      o.to_dev.write.data.burst.data_word = data; \
      /* And then begin waiting for response*/ \
      state = RESP_STATE; \
    } \
  } \
  else if(state==RESP_STATE) \
  { \
    /* Wait for this function to be ready for output*/ \
    if(ready_for_outputs) \
    { \
      /* Then signal to device that ready for response*/ \
      o.to_dev.write.resp_ready = 1; \
      /* And wait for valid output response*/ \
      if(from_dev.write.resp.valid) \
      { \
        /* Done (error code not checked, just returned)*/ \
        o.done = 1; \
        o.resp = from_dev.write.resp.data; \
        state = REQ_STATE; \
      } \
    } \
  } \
  return o; \
} \
 \
/* Read of one name##_read_data_t helper func is slightly simpler than write*/ \
typedef struct name##_read_logic_outputs_t \
{ \
  name##_host_to_dev_t to_dev; \
  name##_read_data_t data; /* uint32_t data; Output data uint2_t rresp; Response error code*/ \
  uint1_t done; \
  uint1_t ready_for_inputs; \
}name##_read_logic_outputs_t; \
name##_read_logic_outputs_t name##_read_logic( \
  read_req_data_t req, /* uint32_t addr,*/ \
  uint1_t ready_for_outputs, \
  name##_dev_to_host_t from_dev \
){ \
  static shared_res_bus_read_state_t state; \
  name##_read_logic_outputs_t o; \
  if(state==REQ_STATE) \
  { \
    /* Wait device to be ready for request inputs*/ \
    if(from_dev.read.req_ready) \
    { \
      /* Signal function is ready for inputs*/ \
      o.ready_for_inputs = 1; \
      /* Use inputs to form valid request*/ \
      o.to_dev.read.req.valid = 1; \
      o.to_dev.read.req.data = req; \
      /* And then begin waiting for response*/ \
      state = RESP_STATE; \
    } \
  } \
  else if(state==RESP_STATE) \
  { \
    /* Wait for this function to be ready for output*/ \
    if(ready_for_outputs) \
    { \
      /* Then signal to device that ready for response*/ \
      o.to_dev.read.data_ready = 1; \
      /* And wait for valid output response*/ \
      if(from_dev.read.data.valid) \
      { \
        o.data = from_dev.read.data; \
        if(from_dev.read.data.burst.last) \
        { \
          /* Done on last word of data_resp*/ \
          /* Error code not checked, just returned*/ \
          o.done = 1; \
          state = REQ_STATE; \
        } \
      } \
    } \
  } \
  return o; \
} \
 \
/* ^TODO: condsider making a combined single read_write_logic?*/ \
 \
/* Global wires*/ \
name##_host_to_dev_t name##_HOST_TO_DEV_NULL; \
name##_host_to_dev_t name##_host_to_dev_wire_on_host_clk; \
name##_dev_to_host_t name##_dev_to_host_wire_on_host_clk; \
/* Wires are used by N thread instances trying to do reads and writes at same time*/ \
/* Resolve multiple drivers with INST_ARRAY arrays of wires*/ \
name##_host_to_dev_t name##_host_to_dev_wires_on_host_clk[NUM_HOST_PORTS]; \
PRAGMA_MESSAGE(INST_ARRAY name##_host_to_dev_wire_on_host_clk name##_host_to_dev_wires_on_host_clk) \
name##_dev_to_host_t name##_dev_to_host_wires_on_host_clk[NUM_HOST_PORTS]; \
PRAGMA_MESSAGE(INST_ARRAY name##_dev_to_host_wire_on_host_clk name##_dev_to_host_wires_on_host_clk) \
/* Only need/want INST_ARRAY on host clock since multiple threads*/ \
/* Dev side needs just plain array use to wire to ports and such*/ \
name##_host_to_dev_t name##_host_to_dev_wires_on_dev_clk[NUM_HOST_PORTS]; \
name##_dev_to_host_t name##_dev_to_host_wires_on_dev_clk[NUM_HOST_PORTS]; \
 \
/* FSM style funcs to do reads and writes*/ \
 \
read_data_resp_word_t name##_read(read_req_data_t req) \
{ \
  read_data_resp_word_t rv; \
  uint1_t done = 0; \
  name##_host_to_dev_wire_on_host_clk = name##_HOST_TO_DEV_NULL; \
  while(!done) \
  { \
    name##_read_logic_outputs_t read_logic_outputs \
      = name##_read_logic(req, 1, name##_dev_to_host_wire_on_host_clk); \
    name##_host_to_dev_wire_on_host_clk = read_logic_outputs.to_dev; \
    done = read_logic_outputs.done; \
    rv = read_logic_outputs.data.burst.data_resp; \
    __clk(); \
  } \
  name##_host_to_dev_wire_on_host_clk = name##_HOST_TO_DEV_NULL; \
  return rv; \
} \
 \
write_resp_data_t name##_write(write_req_data_t req, write_data_word_t data) \
{ \
  write_resp_data_t rv; \
  uint1_t done = 0; \
  name##_host_to_dev_wire_on_host_clk = name##_HOST_TO_DEV_NULL; \
  while(!done) \
  { \
    name##_write_logic_outputs_t write_logic_outputs \
      = name##_write_logic(req, data, 1, name##_dev_to_host_wire_on_host_clk); \
    name##_host_to_dev_wire_on_host_clk = write_logic_outputs.to_dev; \
    done = write_logic_outputs.done; \
    rv = write_logic_outputs.resp; \
    __clk(); \
  } \
  name##_host_to_dev_wire_on_host_clk = name##_HOST_TO_DEV_NULL; \
  return rv; \
} \
 \
/* ^TODO: condsider making a combined single read_write func that uses combined read_write_logic?*/ \
 \
/* Increment with wrap around*/ \
uint8_t name##_host_port_inc(uint8_t selected_host_port) \
{ \
  uint8_t rv = selected_host_port + 1; \
  if(selected_host_port >= (NUM_HOST_PORTS-1)) \
  { \
    rv = 0; \
  } \
  return rv; \
} \
 \
/* Pick next shared bus to arb based on what other ports have chosen*/ \
uint8_t name##_next_host_sel(uint8_t selected_host_port, uint8_t next_dev_to_selected_host[NUM_DEV_PORTS]) \
{ \
  uint1_t found_rv = 0; \
  uint8_t rv = name##_host_port_inc(selected_host_port); \
  int32_t i; \
  /* Backwards loop because 'next' is like a shift, etc*/ \
  for (i = (NUM_DEV_PORTS-1); i >=0; i-=1) \
  { \
    if(next_dev_to_selected_host[i]==rv) \
    { \
      rv = name##_host_port_inc(rv); \
      found_rv = 0; \
    } \
    else \
    { \
      found_rv = 1; \
    } \
  } \
  if(!found_rv) \
  { \
    rv = selected_host_port; \
  } \
  return rv; \
} \
 \
/* SIMPLE ROUND ROBIN, state index can jump (loop back to state, up to only NUM_DEV_PORTS places)*/ \
/* one xfer per host port at a time, does NOT use host ID, DOES use dev IDs*/ \
/* TODO name##_dev_arb DOES NOT NEED read write separation like frame buf multiplexing needed*/ \
/*    just keep req,resp state - now duplicated? for read+write?*/ \
typedef struct name##_dev_arb_t{ \
  name##_host_to_dev_t to_devs[NUM_DEV_PORTS]; \
  name##_dev_to_host_t to_hosts[NUM_HOST_PORTS]; \
}name##_dev_arb_t; \
name##_dev_arb_t name##_dev_arb( \
  name##_dev_to_host_t from_devs[NUM_DEV_PORTS], \
  name##_host_to_dev_t from_hosts[NUM_HOST_PORTS] \
) \
{ \
  /* 5 channels between each host and device*/ \
  /* Request to start*/ \
  /*  Read req (addr)*/ \
  /*  Write req (addr)*/ \
  /* Exchange of data*/ \
  /*  Read data+resp (data+err)*/ \
  /*  Write data (data bytes)*/ \
  /*  Write resp (err code)*/ \
  /* Each channel has a valid+ready handshake buffer*/ \
  static name##_write_req_t write_reqs[NUM_HOST_PORTS]; \
  static name##_read_req_t read_reqs[NUM_HOST_PORTS]; \
  static name##_read_data_t read_datas[NUM_HOST_PORTS]; \
  static name##_write_data_t write_datas[NUM_HOST_PORTS]; \
  static name##_write_resp_t write_resps[NUM_HOST_PORTS]; \
 \
  /* Output signal, static since o.to_frame_buf written to over multiple cycles*/ \
  static name##_dev_arb_t o; \
 \
  uint32_t i; \
  for (i = 0; i < NUM_HOST_PORTS; i+=1) \
  { \
    /* Signal ready for inputs if buffers are empty*/ \
    o.to_hosts[i].write.req_ready = !write_reqs[i].valid; \
    o.to_hosts[i].read.req_ready = !read_reqs[i].valid; \
    o.to_hosts[i].write.data_ready = !write_datas[i].valid; \
 \
    /* Drive outputs from buffers*/ \
    o.to_hosts[i].read.data = read_datas[i]; \
    o.to_hosts[i].write.resp = write_resps[i]; \
 \
    /* Clear output buffers when ready*/ \
    if(from_hosts[i].read.data_ready) \
    { \
      read_datas[i].valid = 0; \
    } \
    if(from_hosts[i].write.resp_ready) \
    { \
      write_resps[i].valid = 0; \
    } \
  } \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    /* Default single cycle high pulse signals to frame buf*/ \
    o.to_devs[i].read.req.valid = 0; \
    o.to_devs[i].read.data_ready = 0; \
     \
    o.to_devs[i].write.req.valid = 0; \
    o.to_devs[i].write.data.valid = 0; \
    o.to_devs[i].write.resp_ready = 0; \
  } \
   \
  /* Each frame bus port prioritizes/selects a specific shared dev host bus*/ \
  static uint8_t dev_to_selected_host[NUM_DEV_PORTS] = {0, 1}/*TODO_FIX_INIT*/; \
  /* Each dev port has a FSM doing req-resp logic*/ \
  /* Allow one req-data-resp in flight at a time per host port:*/ \
  /*  Wait for inputs to arrive in input handshake regs w/ things needed req/data*/ \
  /*  Start operation*/ \
  /*  Wait for outputs to arrive in output handshake regs, wait for handshake to complete*/ \
  static shared_res_bus_dev_arb_state_t host_port_arb_states[NUM_HOST_PORTS]; \
  static uint1_t host_port_read_has_priority[NUM_HOST_PORTS]; /* Toggles for read-write sharing of bus*/ \
 \
  /* INPUT TO DEV SIDE*/ \
 \
  /* Default arb state doesnt change*/ \
  uint8_t next_dev_to_selected_host[NUM_DEV_PORTS] = dev_to_selected_host; \
 \
  /* Loop that finds input req/ wr data for each dev port*/ \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    uint8_t selected_host = dev_to_selected_host[i]; \
    /* Try to start xfer for the current/round robin selected host dev port*/ \
    if(host_port_arb_states[selected_host]==REQ) \
    { \
      /* Wait for a request*/ \
      /* Choose a request to handle, read or write*/ \
      uint1_t do_read; \
      uint1_t do_write; \
      if(host_port_read_has_priority[selected_host]) \
      { \
        /* Read priority*/ \
        if(read_reqs[selected_host].valid) \
        { \
          do_read = 1; \
        } \
        else if(write_reqs[selected_host].valid) \
        { \
          do_write = 1; \
        }  \
      } \
      else \
      { \
        /* Write priority*/ \
        if(write_reqs[selected_host].valid) \
        { \
          do_write = 1; \
        } \
        else if(read_reqs[selected_host].valid) \
        { \
          do_read = 1; \
        }  \
      } \
      if(do_read) \
      { \
        if(from_devs[i].read.req_ready) \
        { \
          o.to_devs[i].read.req = read_reqs[selected_host]; \
          read_reqs[selected_host].valid = 0; /* Done w req now*/ \
          host_port_read_has_priority[selected_host] = 0; /* Writes next*/ \
          o.to_devs[i].read.req.id = selected_host; /* Overides/ignores host value*/ \
          /*FRAME BUF ONLY o.to_frame_bufs[i].valid = 1; addr completes valid inputs, no input read data*/ \
          /* Waiting for output read data next*/ \
          host_port_arb_states[selected_host] = RD_DATA; \
          /* Done with shared bus port inputs, move arb on*/ \
          next_dev_to_selected_host[i] = name##_next_host_sel(selected_host, next_dev_to_selected_host); \
        } \
      } \
      else if(do_write) \
      { \
        if(from_devs[i].write.req_ready) \
        { \
          o.to_devs[i].write.req = write_reqs[selected_host]; \
          write_reqs[selected_host].valid = 0; /* Done w req now*/ \
          host_port_read_has_priority[selected_host] = 1; /* Reads next*/ \
          o.to_devs[i].write.req.id = selected_host; /* Overides/ignores host value*/ \
          /*FRAME BUF ONLY Write stil needs data still before valid input*/ \
          host_port_arb_states[selected_host] = WR_DATA; \
          /* Not done with shared bus port inputs yet, dont change arb*/ \
        } \
      } \
      else \
      { \
        /* No read or write req from this port, move on*/ \
        next_dev_to_selected_host[i] = name##_next_host_sel(selected_host, next_dev_to_selected_host); \
      } \
    } \
    /* TODO pass through write req and data*/ \
    else if(host_port_arb_states[selected_host]==WR_DATA) /* Write data into dev*/ \
    { \
      /* Wait until valid write data*/ \
      if(write_datas[selected_host].valid) \
      { \
        if(from_devs[i].write.data_ready) \
        { \
          o.to_devs[i].write.data = write_datas[selected_host]; \
          o.to_devs[i].write.data.id = selected_host; /* Overides/ignores host value*/ \
          write_datas[selected_host].valid = 0; /* Done w data now*/ \
          host_port_arb_states[selected_host] = WR_RESP_STATE; \
          /* Done with shared bus port inputs, move arb on*/ \
          next_dev_to_selected_host[i] = name##_next_host_sel(selected_host, next_dev_to_selected_host); \
        } \
      } \
    }   \
  } \
  /* Update arb state*/ \
  dev_to_selected_host = next_dev_to_selected_host; \
 \
  /* DEV WAS HERE*/ \
 \
  /* Outputs from DEV flow into output handshake buffers*/ \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    /* Output write resp, err code unused*/ \
    if(from_devs[i].write.resp.valid) \
    { \
      uint8_t selected_host = from_devs[i].write.resp.id; \
      o.to_devs[i].write.resp_ready = !write_resps[selected_host].valid; \
      if(o.to_devs[i].write.resp_ready) \
      { \
        write_resps[selected_host] = from_devs[i].write.resp; \
      } \
    } \
    /* Output read data*/ \
    if(from_devs[i].read.data.valid) \
    { \
      uint8_t selected_host = from_devs[i].read.data.id; \
      o.to_devs[i].read.data_ready = !read_datas[selected_host].valid; \
      if(o.to_devs[i].read.data_ready) \
      { \
        read_datas[selected_host] = from_devs[i].read.data; \
      } \
    } \
  } \
 \
  for (i = 0; i < NUM_HOST_PORTS; i+=1) \
  { \
    /* State machine logic dealing with ram output signals handshake*/ \
    if(host_port_arb_states[i]==RD_DATA) /* Read data out of RAM*/ \
    { \
      /* Wait for last valid read data outgoing to host*/ \
      if(o.to_hosts[i].read.data.valid & o.to_hosts[i].read.data.burst.last & from_hosts[i].read.data_ready)  \
      { \
        host_port_arb_states[i] = REQ; \
      } \
    } \
    else if(host_port_arb_states[i]==WR_RESP_STATE) \
    { \
      /* Wait for valid write resp outgoing to host*/ \
      if(o.to_hosts[i].write.resp.valid & from_hosts[i].write.resp_ready)  \
      { \
        host_port_arb_states[i] = REQ; \
      } \
    } \
 \
    /* Save data into input buffers if signalling ready in handshake*/ \
    if(o.to_hosts[i].write.req_ready) \
    { \
      write_reqs[i] = from_hosts[i].write.req; \
    } \
    if(o.to_hosts[i].read.req_ready) \
    { \
      read_reqs[i] = from_hosts[i].read.req; \
    } \
    if(o.to_hosts[i].write.data_ready) \
    { \
      write_datas[i] = from_hosts[i].write.data; \
    } \
  } \
 \
  return o; \
}

// TODO temp wrapper struct typedef (since cant do plain typedef) for name#_ types
// TODO convert macros to use constant literal interger

// Each channel of 5 channels host<->dev link needs async fifo
// 3 write, 2 read
// INST_ARRAY doesnt support async fifos
#define SHARED_BUS_ASYNC_FIFO_DECL(name, bus_name, DEPTH, \
write_req_data_t, write_resp_data_t, \
read_req_data_t \
) \
write_req_data_t name##_write_req[DEPTH];\
bus_name##_write_burst_word_t name##_write_data[DEPTH];\
write_resp_data_t name##_write_resp[DEPTH];\
read_req_data_t name##_read_req[DEPTH];\
bus_name##_read_burst_word_t name##_read_data[DEPTH];

#define SHARED_BUS_ASYNC_FIFO_HOST_WIRING( \
  name, bus_name, \
  dev_to_host_wire, \
  host_to_dev_wire, \
  write_req_data_t, \
  write_resp_data_t, \
  read_req_data_t \
)\
/* Write into fifo (to dev) <= host_to_dev_wire*/ \
/* dev_to_host_wire <= Read from fifo (from dev)*/ \
/* FIFO is one of the channels...*/ \
/**/ \
/* Write request data into fifo*/ \
/* Write request ready out of fifo*/ \
write_req_data_t name##_write_req_write_req_data[1]; \
name##_write_req_write_req_data[0] = host_to_dev_wire.write.req.data; \
name##_write_req_write_t name##_write_req_write_req_write = \
  name##_write_req_WRITE_1(name##_write_req_write_req_data, host_to_dev_wire.write.req.valid); \
dev_to_host_wire.write.req_ready = name##_write_req_write_req_write.ready; \
/* Write data data into fifo*/ \
/* Write data ready out of fifo*/ \
bus_name##_write_burst_word_t name##_write_data_write_data_data[1]; \
name##_write_data_write_data_data[0] = host_to_dev_wire.write.data.burst; \
name##_write_data_write_t name##_write_data_write_data_write = \
  name##_write_data_WRITE_1(name##_write_data_write_data_data, host_to_dev_wire.write.data.valid); \
dev_to_host_wire.write.data_ready = name##_write_data_write_data_write.ready; \
/* Write resp data out of fifo*/ \
/* Write resp ready into fifo*/ \
name##_write_resp_read_t name##_write_resp_write_resp_read = \
  name##_write_resp_READ_1(host_to_dev_wire.write.resp_ready); \
dev_to_host_wire.write.resp.data = name##_write_resp_write_resp_read.data[0]; \
dev_to_host_wire.write.resp.valid = name##_write_resp_write_resp_read.valid; \
/* Read req data into fifo*/ \
/* Read req ready out of fifo*/ \
read_req_data_t name##_read_req_read_req_data[1]; \
name##_read_req_read_req_data[0] = host_to_dev_wire.read.req.data; \
name##_read_req_write_t name##_read_req_read_req_write = \
  name##_read_req_WRITE_1(name##_read_req_read_req_data, host_to_dev_wire.read.req.valid); \
dev_to_host_wire.read.req_ready = name##_read_req_read_req_write.ready; \
/* Read data data out of fifo*/ \
/* Read data ready into fifo*/ \
name##_read_data_read_t name##_read_data_read_data_read = \
  name##_read_data_READ_1(host_to_dev_wire.read.data_ready); \
dev_to_host_wire.read.data.burst = name##_read_data_read_data_read.data[0]; \
dev_to_host_wire.read.data.valid = name##_read_data_read_data_read.valid;

#define SHARED_BUS_ASYNC_FIFO_DEV_WIRING( \
  name, bus_name, \
  host_to_dev_wire, \
  dev_to_host_wire, \
  write_req_data_t, \
  write_resp_data_t, \
  read_req_data_t \
)\
/* Write into fifo (to host) <= dev_to_host_wire */ \
/* host_to_dev_wire <= Read from fifo (from host)*/ \
/* FIFO is one of the channels...
/**/ \
/* Write request data out of fifo*/ \
/* Write request ready back into fifo*/ \
name##_write_req_read_t name##_write_req_write_req_read = \
  name##_write_req_READ_1(dev_to_host_wire.write.req_ready); \
host_to_dev_wire.write.req.data = name##_write_req_write_req_read.data[0]; \
host_to_dev_wire.write.req.valid = name##_write_req_write_req_read.valid; \
/* Write data data out of fifo*/ \
/* Write data ready back into fifo*/ \
name##_write_data_read_t name##_write_data_write_data_read =  \
  name##_write_data_READ_1(dev_to_host_wire.write.data_ready); \
host_to_dev_wire.write.data.burst = name##_write_data_write_data_read.data[0]; \
host_to_dev_wire.write.data.valid = name##_write_data_write_data_read.valid; \
/* Write resp data into fifo*/ \
/* Write resp ready out of fifo*/ \
write_resp_data_t name##_write_resp_write_resp_data[1]; \
name##_write_resp_write_resp_data[0] = dev_to_host_wire.write.resp.data; \
name##_write_resp_write_t name##_write_resp_write_resp_write = \
  name##_write_resp_WRITE_1(name##_write_resp_write_resp_data, dev_to_host_wire.write.resp.valid); \
host_to_dev_wire.write.resp_ready = name##_write_resp_write_resp_write.ready; \
/* Read req data out of fifo*/ \
/* Read req ready back into fifo*/ \
name##_read_req_read_t name##_read_req_read_req_read =  \
  name##_read_req_READ_1(dev_to_host_wire.read.req_ready); \
host_to_dev_wire.read.req.data = name##_read_req_read_req_read.data[0]; \
host_to_dev_wire.read.req.valid = name##_read_req_read_req_read.valid; \
/* Read data data into fifo*/ \
/* Read data ready out of fifo*/ \
bus_name##_read_burst_word_t name##_read_data_read_data_data[1]; \
name##_read_data_read_data_data[0] = dev_to_host_wire.read.data.burst; \
name##_read_data_write_t name##_read_data_read_data_write = \
  name##_read_data_WRITE_1(name##_read_data_read_data_data, dev_to_host_wire.read.data.valid); \
host_to_dev_wire.read.data_ready = name##_read_data_read_data_write.ready;
