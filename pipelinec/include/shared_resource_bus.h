#include "uintN_t.h"
#include "intN_t.h"
#include "arrays.h"
#include "xstr.h"
#include "compiler.h"
#include "clock_crossing.h"

// WARNING: User cannot use IDs (only used internally by arb), and bursts are not supported yet (1 cycle tlast=1 xfers only)

// Generic AXI-like bus with data,valid,ready ~5 channel read,write req,resp
// Generic 5 channel bus
// 3 write, 2 read
#define id_t uint16_t
#define SHARED_RES_CLK_CROSS_FIFO_DEPTH 16 // min is 16 due to Xilinx XPM FIFO

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

#define SHARED_BUS_TYPE_DEF( \
  name, \
  write_req_data_t, write_data_word_t, write_resp_data_t, \
  read_req_data_t, read_data_resp_word_t \
)\
/* Wrapper struct defs until plain typedefs are supported*/ \
typedef struct PPCAT(name, _write_req_data_t) \
{ \
  write_req_data_t user; \
}PPCAT(name, _write_req_data_t); \
typedef struct PPCAT(name, _write_data_word_t) \
{ \
  write_data_word_t user; \
}PPCAT(name, _write_data_word_t); \
typedef struct PPCAT(name, _write_resp_data_t) \
{ \
  write_resp_data_t user; \
}PPCAT(name, _write_resp_data_t); \
typedef struct PPCAT(name, _read_req_data_t) \
{ \
  read_req_data_t user; \
}PPCAT(name, _read_req_data_t); \
typedef struct PPCAT(name, _read_data_resp_word_t) \
{ \
  read_data_resp_word_t user; \
}PPCAT(name, _read_data_resp_word_t); \
\
/* Bus types*/ \
typedef struct PPCAT(name, _write_req_t) \
{ \
  PPCAT(name, _write_req_data_t) data; \
  id_t id; \
  uint1_t valid; \
}PPCAT(name, _write_req_t); \
\
typedef struct PPCAT(name, _write_burst_word_t) \
{ \
  PPCAT(name, _write_data_word_t) data_word; \
  uint1_t last; \
} PPCAT(name, _write_burst_word_t); \
\
typedef struct PPCAT(name, _write_data_t) \
{ \
  PPCAT(name, _write_burst_word_t) burst; \
  id_t id; /*AXI3 only*/ \
  uint1_t valid; \
} PPCAT(name, _write_data_t); \
\
typedef struct PPCAT(name, _write_resp_t) \
{ \
  PPCAT(name, _write_resp_data_t) data; \
  id_t id; \
  uint1_t valid; \
} PPCAT(name, _write_resp_t); \
\
typedef struct PPCAT(name, _write_host_to_dev_t) \
{ \
  PPCAT(name, _write_req_t) req; \
  PPCAT(name, _write_data_t) data; \
  /*  Read to receive write responses*/\
  uint1_t resp_ready; \
} PPCAT(name, _write_host_to_dev_t); \
\
typedef struct PPCAT(name, _write_dev_to_host_t) \
{ \
  PPCAT(name, _write_resp_t) resp; \
  /*  Ready for write request/address*/\
  uint1_t req_ready; \
	/*  Ready for write data */\
  uint1_t data_ready; \
} PPCAT(name, _write_dev_to_host_t);\
\
typedef struct PPCAT(name, _read_req_t) \
{ \
  PPCAT(name, _read_req_data_t) data; \
  id_t id; \
  uint1_t valid; \
} PPCAT(name, _read_req_t); \
 \
typedef struct PPCAT(name, _read_burst_word_t) \
{ \
  PPCAT(name, _read_data_resp_word_t) data_resp; \
  uint1_t last; \
}PPCAT(name, _read_burst_word_t); \
 \
typedef struct PPCAT(name, _read_data_t) \
{ \
  PPCAT(name, _read_burst_word_t) burst; \
  id_t id; \
  uint1_t valid; \
} PPCAT(name, _read_data_t); \
 \
typedef struct PPCAT(name, _read_host_to_dev_t) \
{ \
  PPCAT(name, _read_req_t) req; \
  /*  Ready to receive read data (bytes+resp)*/ \
  uint1_t data_ready; \
} PPCAT(name, _read_host_to_dev_t); \
 \
typedef struct PPCAT(name, _read_dev_to_host_t) \
{ \
  PPCAT(name, _read_data_t) data; \
  /*  Ready for read address*/ \
  uint1_t req_ready; \
} PPCAT(name, _read_dev_to_host_t); \
 \
typedef struct PPCAT(name,_host_to_dev_t) \
{ \
  /* Write Channel*/ \
  PPCAT(name, _write_host_to_dev_t) write; \
  /* Read Channel*/ \
  PPCAT(name, _read_host_to_dev_t) read; \
} PPCAT(name,_host_to_dev_t); \
 \
typedef struct PPCAT(name, _dev_to_host_t) \
{ \
  /* Write Channel*/ \
  PPCAT(name, _write_dev_to_host_t) write; \
  /* Read Channel */ \
  PPCAT(name, _read_dev_to_host_t) read; \
} PPCAT(name, _dev_to_host_t); \
\
typedef struct PPCAT(name, _buffer_t) \
{ \
  PPCAT(name, _write_req_t) write_req; \
  PPCAT(name, _read_req_t) read_req; \
  PPCAT(name, _read_data_t) read_data; \
  PPCAT(name, _write_data_t) write_data; \
  PPCAT(name, _write_resp_t) write_resp; \
}PPCAT(name, _buffer_t); \
 \
/* Write has two channels to begin request: address and data */ \
/* Helper func to write one PPCAT(name, _write_data_word_t) requires that inputs are valid/held constant*/ \
/* until data phase done (ready_for_inputs asserted)*/ \
typedef struct PPCAT(name, _write_start_logic_outputs_t) \
{ \
  PPCAT(name, _write_host_to_dev_t) to_dev; \
  uint1_t done; \
  uint1_t ready_for_inputs; \
}PPCAT(name, _write_start_logic_outputs_t); \
PPCAT(name, _write_start_logic_outputs_t) PPCAT(name, _write_start_logic)( \
  write_req_data_t req, /* uint32_t addr,*/ \
  write_data_word_t data, /* uint32_t data,*/ \
  uint1_t ready_for_outputs,  \
  PPCAT(name, _write_dev_to_host_t) from_dev \
){ \
  static shared_res_bus_write_state_t state; \
  PPCAT(name, _write_start_logic_outputs_t) o; \
  if(state==REQ_STATE) \
  { \
    /* Wait device to be ready for write address first*/ \
    if(from_dev.req_ready) \
    { \
      /* Use inputs to form valid address*/ \
      o.to_dev.req.valid = 1; \
      o.to_dev.req.data.user = req; \
      /* And then data next*/ \
      state = DATA_STATE; \
    } \
  } \
  /* pass through states */ \
  if(state==DATA_STATE) \
  { \
    /* Wait for this function to be ready for output*/ \
    if(ready_for_outputs) \
    { \
      /* Wait device to be ready for write data*/ \
      if(from_dev.data_ready) \
      { \
        /* Signal finally ready for inputs since data completes write request*/ \
        o.ready_for_inputs = 1; \
        /* Send valid data transfer*/ \
        o.to_dev.data.valid = 1; \
        o.to_dev.data.burst.last = 1; \
        o.to_dev.data.burst.data_word.user = data; \
        /* Done */ \
        o.done = 1; \
        state = REQ_STATE; \
      } \
    } \
  } \
  return o; \
} \
typedef struct PPCAT(name, _write_finish_logic_outputs_t) \
{ \
  PPCAT(name, _write_host_to_dev_t) to_dev; \
  write_resp_data_t resp; \
  uint1_t done; \
}PPCAT(name, _write_finish_logic_outputs_t); \
PPCAT(name, _write_finish_logic_outputs_t) PPCAT(name, _write_finish_logic)( \
  uint1_t ready_for_outputs,  \
  PPCAT(name, _write_dev_to_host_t) from_dev \
){ \
  PPCAT(name, _write_finish_logic_outputs_t) o; \
  /* Wait for this function to be ready for output*/ \
  if(ready_for_outputs) \
  { \
    /* Then signal to device that ready for response*/ \
    o.to_dev.resp_ready = 1; \
    /* And wait for valid output response*/ \
    if(from_dev.resp.valid) \
    { \
      /* Done (error code not checked, just returned)*/ \
      o.done = 1; \
      o.resp = from_dev.resp.data.user; \
      state = REQ_STATE; \
    } \
  } \
  return o; \
} \
/* TODO make write_logic use write_start_logic and write_finish_logic*/ \
typedef struct PPCAT(name, _write_logic_outputs_t) \
{ \
  PPCAT(name, _write_host_to_dev_t) to_dev; \
  write_resp_data_t resp; \
  uint1_t done; \
  uint1_t ready_for_inputs; \
}PPCAT(name, _write_logic_outputs_t); \
PPCAT(name, _write_logic_outputs_t) PPCAT(name, _write_logic)( \
  write_req_data_t req, /* uint32_t addr,*/ \
  write_data_word_t data, /* uint32_t data,*/ \
  uint1_t ready_for_outputs,  \
  PPCAT(name, _write_dev_to_host_t) from_dev \
){ \
  static shared_res_bus_write_state_t state; \
  PPCAT(name, _write_logic_outputs_t) o; \
  if(state==REQ_STATE) \
  { \
    /* Wait device to be ready for write address first*/ \
    if(from_dev.req_ready) \
    { \
      /* Use inputs to form valid address*/ \
      o.to_dev.req.valid = 1; \
      o.to_dev.req.data.user = req; \
      /* And then data next*/ \
      state = DATA_STATE; \
    } \
  } \
  else if(state==DATA_STATE) \
  { \
    /* Wait device to be ready for write data*/ \
    if(from_dev.data_ready) \
    { \
      /* Signal finally ready for inputs since data completes write request*/ \
      o.ready_for_inputs = 1; \
      /* Send valid data transfer*/ \
      o.to_dev.data.valid = 1; \
      o.to_dev.data.burst.last = 1; \
      o.to_dev.data.burst.data_word.user = data; \
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
      o.to_dev.resp_ready = 1; \
      /* And wait for valid output response*/ \
      if(from_dev.resp.valid) \
      { \
        /* Done (error code not checked, just returned)*/ \
        o.done = 1; \
        o.resp = from_dev.resp.data.user; \
        state = REQ_STATE; \
      } \
    } \
  } \
  return o; \
} \
 \
/* Read of one PPCAT(name, _read_data_t) helper func is slightly simpler than write*/ \
typedef struct PPCAT(name, _read_start_logic_outputs_t) \
{ \
  PPCAT(name, _read_req_t) req; \
  uint1_t done; \
  uint1_t ready_for_inputs; \
}PPCAT(name, _read_start_logic_outputs_t); \
PPCAT(name, _read_start_logic_outputs_t) PPCAT(name, _read_start_logic)( \
  read_req_data_t req, /* uint32_t addr,*/ \
  uint1_t ready_for_outputs, \
  uint1_t req_ready \
){ \
  PPCAT(name, _read_start_logic_outputs_t) o; \
  /* Wait for this function to be ready for output*/ \
  if(ready_for_outputs) \
  { \
    /* Wait device to be ready for request inputs*/ \
    if(req_ready) \
    { \
      /* Signal function is ready for inputs*/ \
      o.ready_for_inputs = 1; \
      /* Use inputs to form valid request*/ \
      o.req.valid = 1; \
      o.req.data.user = req; \
      o.done = 1; \
    } \
  }\
  return o; \
} \
typedef struct PPCAT(name, _read_finish_logic_outputs_t) \
{ \
  uint1_t data_ready; \
  read_data_resp_word_t data; \
  uint1_t done; \
}PPCAT(name, _read_finish_logic_outputs_t); \
PPCAT(name, _read_finish_logic_outputs_t) PPCAT(name, _read_finish_logic)( \
  uint1_t ready_for_outputs, \
  PPCAT(name, _read_data_t) data \
){ \
  PPCAT(name, _read_finish_logic_outputs_t) o; \
  /* Wait for this function to be ready for output*/ \
  if(ready_for_outputs) \
  { \
    /* Then signal to device that ready for response*/ \
    o.data_ready = 1; \
    /* And wait for valid output response*/ \
    if(data.valid) \
    { \
      o.data = data.burst.data_resp.user; \
      if(data.burst.last) \
      { \
        /* Done on last word of data_resp*/ \
        /* Error code not checked, just returned*/ \
        o.done = 1; \
      } \
    } \
  } \
  return o; \
} \
/* TODO make read_logic use read_start_logic and read_finish_logic*/ \
typedef struct PPCAT(name, _read_logic_outputs_t) \
{ \
  PPCAT(name, _read_host_to_dev_t) to_dev; \
  read_data_resp_word_t data; \
  uint1_t done; \
  uint1_t ready_for_inputs; \
}PPCAT(name, _read_logic_outputs_t); \
PPCAT(name, _read_logic_outputs_t) PPCAT(name, _read_logic)( \
  read_req_data_t req, /* uint32_t addr,*/ \
  uint1_t ready_for_outputs, \
  PPCAT(name, _read_dev_to_host_t) from_dev \
){ \
  static shared_res_bus_read_state_t state; \
  PPCAT(name, _read_logic_outputs_t) o; \
  if(state==REQ_STATE) \
  { \
    /* Wait device to be ready for request inputs*/ \
    if(from_dev.req_ready) \
    { \
      /* Signal function is ready for inputs*/ \
      o.ready_for_inputs = 1; \
      /* Use inputs to form valid request*/ \
      o.to_dev.req.valid = 1; \
      o.to_dev.req.data.user = req; \
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
      o.to_dev.data_ready = 1; \
      /* And wait for valid output response*/ \
      if(from_dev.data.valid) \
      { \
        o.data = from_dev.data.burst.data_resp.user; \
        if(from_dev.data.burst.last) \
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
/* ^TODO: condsider making a combined single read_write_logic?*/ \
 \
PPCAT(name, _host_to_dev_t) PPCAT(name, _HOST_TO_DEV_NULL); \
PPCAT(name, _read_host_to_dev_t) PPCAT(name, _READ_HOST_TO_DEV_NULL); \
PPCAT(name, _write_host_to_dev_t) PPCAT(name, _WRITE_HOST_TO_DEV_NULL);

#define SHARED_BUS_READ_START_FINISH_DECL(\
type, \
read_req_data_t, read_data_resp_word_t, \
name, \
host_to_dev_wire_on_host_clk_read_req, \
dev_to_host_wire_on_host_clk_read_req_ready, \
dev_to_host_wire_on_host_clk_read_data, \
host_to_dev_wire_on_host_clk_read_data_ready \
) \
void PPCAT(name, _read_start)(read_req_data_t req) \
{ \
  uint1_t done = 0; \
  host_to_dev_wire_on_host_clk_read_req.valid = 0; \
  do \
  { \
    PPCAT(type, _read_start_logic_outputs_t) read_logic_outputs \
      = PPCAT(type, _read_start_logic)(req, 1, dev_to_host_wire_on_host_clk_read_req_ready); \
    host_to_dev_wire_on_host_clk_read_req = read_logic_outputs.req; \
    done = read_logic_outputs.done; \
    __clk(); \
  } \
  while(!done); \
  host_to_dev_wire_on_host_clk_read_req.valid = 0; \
} \
read_data_resp_word_t PPCAT(name, _read_finish)() \
{ \
  read_data_resp_word_t rv; \
  uint1_t done = 0; \
  host_to_dev_wire_on_host_clk_read_data_ready = 0; \
  do \
  { \
    PPCAT(type, _read_finish_logic_outputs_t) read_logic_outputs \
      = PPCAT(type, _read_finish_logic)(1, dev_to_host_wire_on_host_clk_read_data); \
    host_to_dev_wire_on_host_clk_read_data_ready = read_logic_outputs.data_ready; \
    done = read_logic_outputs.done; \
    rv = read_logic_outputs.data; \
    __clk(); \
  } \
  while(!done); \
  host_to_dev_wire_on_host_clk_read_data_ready = 0; \
  return rv; \
} \
typedef struct PPCAT(name, _read_finish_nonblocking_t){ \
  read_data_resp_word_t data; \
  uint1_t valid; \
}PPCAT(name, _read_finish_nonblocking_t); \
PPCAT(name, _read_finish_nonblocking_t) PPCAT(name, _read_finish_nonblocking)() \
{ \
  PPCAT(name, _read_finish_nonblocking_t) rv; \
  PPCAT(type, _read_finish_logic_outputs_t) read_logic_outputs \
    = PPCAT(type, _read_finish_logic)(1, dev_to_host_wire_on_host_clk_read_data); \
  host_to_dev_wire_on_host_clk_read_data_ready = read_logic_outputs.data_ready; \
  rv.data = read_logic_outputs.data; \
  rv.valid = read_logic_outputs.done; \
  __clk(); \
  host_to_dev_wire_on_host_clk_read_data_ready = 0; \
  return rv; \
}


#define SHARED_BUS_DECL(\
type, \
write_req_data_t, write_data_word_t, write_resp_data_t, \
read_req_data_t, read_data_resp_word_t, \
name, NUM_HOST_PORTS, NUM_DEV_PORTS \
) \
/* Global wires*/ \
PPCAT(type, _host_to_dev_t) PPCAT(name, _host_to_dev_wire_on_host_clk); \
PPCAT(type, _dev_to_host_t) PPCAT(name, _dev_to_host_wire_on_host_clk); \
/* Wires are used by N thread instances trying to do reads and writes at same time*/ \
/* Resolve multiple drivers with INST_ARRAY arrays of wires*/ \
PPCAT(type, _host_to_dev_t) PPCAT(name, _host_to_dev_wires_on_host_clk)[NUM_HOST_PORTS]; \
PRAGMA_MESSAGE(INST_ARRAY PPCAT(name, _host_to_dev_wire_on_host_clk) PPCAT(name, _host_to_dev_wires_on_host_clk)) \
PPCAT(type, _dev_to_host_t) PPCAT(name, _dev_to_host_wires_on_host_clk)[NUM_HOST_PORTS]; \
PRAGMA_MESSAGE(INST_ARRAY PPCAT(name, _dev_to_host_wire_on_host_clk) PPCAT(name, _dev_to_host_wires_on_host_clk)) \
/* Only need/want INST_ARRAY on host clock since multiple threads*/ \
/* Dev side needs just plain array use to wire to ports and such*/ \
PPCAT(type, _host_to_dev_t) PPCAT(name, _host_to_dev_wires_on_dev_clk)[NUM_HOST_PORTS]; \
PPCAT(type, _dev_to_host_t) PPCAT(name, _dev_to_host_wires_on_dev_clk)[NUM_HOST_PORTS]; \
 \
/* FSM style funcs to do reads and writes*/ \
SHARED_BUS_READ_START_FINISH_DECL(\
type, \
read_req_data_t, read_data_resp_word_t, \
name, \
PPCAT(name, _host_to_dev_wire_on_host_clk).read.req, \
PPCAT(name, _dev_to_host_wire_on_host_clk).read.req_ready, \
PPCAT(name, _dev_to_host_wire_on_host_clk).read.data, \
PPCAT(name, _host_to_dev_wire_on_host_clk).read.data_ready \
) \
read_data_resp_word_t PPCAT(name, _read)(read_req_data_t req) \
{ \
  read_data_resp_word_t rv; \
  uint1_t done = 0; \
  PPCAT(name, _host_to_dev_wire_on_host_clk).read = PPCAT(type, _READ_HOST_TO_DEV_NULL); \
  do \
  { \
    PPCAT(type, _read_logic_outputs_t) read_logic_outputs \
      = PPCAT(type, _read_logic)(req, 1, PPCAT(name, _dev_to_host_wire_on_host_clk).read); \
    PPCAT(name, _host_to_dev_wire_on_host_clk).read = read_logic_outputs.to_dev; \
    done = read_logic_outputs.done; \
    rv = read_logic_outputs.data; \
    __clk(); \
  } \
  while(!done); \
  PPCAT(name, _host_to_dev_wire_on_host_clk).read = PPCAT(type, _READ_HOST_TO_DEV_NULL); \
  return rv; \
} \
\
void PPCAT(name, _write_start)(write_req_data_t req, write_data_word_t data) \
{ \
  uint1_t done = 0; \
  PPCAT(name, _host_to_dev_wire_on_host_clk).write = PPCAT(type, _WRITE_HOST_TO_DEV_NULL); \
  do \
  { \
    PPCAT(type, _write_start_logic_outputs_t) write_logic_outputs \
      = PPCAT(type, _write_start_logic)(req, data, 1, PPCAT(name, _dev_to_host_wire_on_host_clk).write); \
    PPCAT(name, _host_to_dev_wire_on_host_clk).write = write_logic_outputs.to_dev; \
    done = write_logic_outputs.done; \
    __clk(); \
  } \
  while(!done); \
  PPCAT(name, _host_to_dev_wire_on_host_clk).write = PPCAT(type, _WRITE_HOST_TO_DEV_NULL); \
  return rv; \
} \
write_resp_data_t PPCAT(name, _write_finish)() \
{ \
  write_resp_data_t rv; \
  uint1_t done = 0; \
  PPCAT(name, _host_to_dev_wire_on_host_clk).write = PPCAT(type, _WRITE_HOST_TO_DEV_NULL); \
  do \
  { \
    PPCAT(type, _write_finish_logic_outputs_t) write_logic_outputs \
      = PPCAT(type, _write_finish_logic)(1, PPCAT(name, _dev_to_host_wire_on_host_clk).write); \
    PPCAT(name, _host_to_dev_wire_on_host_clk).write = write_logic_outputs.to_dev; \
    done = write_logic_outputs.done; \
    rv = write_logic_outputs.resp; \
    __clk(); \
  } \
  while(!done); \
  PPCAT(name, _host_to_dev_wire_on_host_clk).write = PPCAT(type, _WRITE_HOST_TO_DEV_NULL); \
  return rv; \
} \
write_resp_data_t PPCAT(name, _write)(write_req_data_t req, write_data_word_t data) \
{ \
  write_resp_data_t rv; \
  uint1_t done = 0; \
  PPCAT(name, _host_to_dev_wire_on_host_clk).write = PPCAT(type, _WRITE_HOST_TO_DEV_NULL); \
  do \
  { \
    PPCAT(type, _write_logic_outputs_t) write_logic_outputs \
      = PPCAT(type, _write_logic)(req, data, 1, PPCAT(name, _dev_to_host_wire_on_host_clk).write); \
    PPCAT(name, _host_to_dev_wire_on_host_clk).write = write_logic_outputs.to_dev; \
    done = write_logic_outputs.done; \
    rv = write_logic_outputs.resp; \
    __clk(); \
  } \
  while(!done); \
  PPCAT(name, _host_to_dev_wire_on_host_clk).write = PPCAT(type, _WRITE_HOST_TO_DEV_NULL); \
  return rv; \
} \
 \
/* ^TODO: condsider making a combined single read_write func that uses combined read_write_logic?*/ \
/* ^ TODO maybe implement full read/write using start and finish?*/ \
 \
/* Increment with wrap around*/ \
uint8_t PPCAT(name, _host_port_inc)(uint8_t selected_host_port) \
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
uint8_t PPCAT(name, _next_host_sel)(uint8_t selected_host_port, uint8_t next_dev_to_selected_host[NUM_DEV_PORTS]) \
{ \
  uint8_t rv = PPCAT(name, _host_port_inc)(selected_host_port); \
  int32_t i; \
  /* Backwards loop because 'next' is like a shift, etc*/ \
  for (i = (NUM_DEV_PORTS-1); i >=0; i-=1) \
  { \
    if(next_dev_to_selected_host[i]==rv) \
    { \
      rv = PPCAT(name, _host_port_inc)(rv); \
    } \
  } \
  return rv; \
} \
 \
/* SIMPLE ROUND ROBIN, state index can jump (loop back to state, up to only NUM_DEV_PORTS places)*/ \
/* one xfer per host port at a time, does NOT use host ID, DOES use dev IDs*/ \
/* TODO PPCAT(name, _dev_arb) DOES NOT NEED read write separation like frame buf multiplexing needed*/ \
/*    just keep req,resp state - now duplicated? for read+write?*/ \
/*    helps async start complete from one channel, mixing reads and writes*/ \
typedef struct PPCAT(name, _dev_arb_t){ \
  PPCAT(type, _host_to_dev_t) to_devs[NUM_DEV_PORTS]; \
  PPCAT(type, _dev_to_host_t) to_hosts[NUM_HOST_PORTS]; \
}PPCAT(name, _dev_arb_t); \
PPCAT(name, _dev_arb_t) PPCAT(name, _dev_arb)( \
  PPCAT(type, _dev_to_host_t) from_devs[NUM_DEV_PORTS], \
  PPCAT(type, _host_to_dev_t) from_hosts[NUM_HOST_PORTS] \
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
  static PPCAT(type, _write_req_t) write_reqs[NUM_HOST_PORTS]; \
  static PPCAT(type, _read_req_t) read_reqs[NUM_HOST_PORTS]; \
  static PPCAT(type, _read_data_t) read_datas[NUM_HOST_PORTS]; \
  static PPCAT(type, _write_data_t) write_datas[NUM_HOST_PORTS]; \
  static PPCAT(type, _write_resp_t) write_resps[NUM_HOST_PORTS]; \
 \
  /* Output signal, static since o.to_frame_buf written to over multiple cycles*/ \
  static PPCAT(name, _dev_arb_t) o; \
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
  static uint8_t dev_to_selected_host[NUM_DEV_PORTS]; /* See reset below {0, 1}*/ \
  static uint1_t power_on_reset = 1; \
  if(power_on_reset) \
  { \
    for (i = 0; i < NUM_DEV_PORTS; i+=1) \
    { \
      dev_to_selected_host[i] = i; \
    } \
  } \
  power_on_reset = 0;\
 \
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
  /* Default state doesnt change*/ \
  uint8_t next_dev_to_selected_host[NUM_DEV_PORTS] = dev_to_selected_host; \
  shared_res_bus_dev_arb_state_t next_host_port_arb_states[NUM_HOST_PORTS] = host_port_arb_states; \
  PPCAT(type, _read_req_t) next_read_reqs[NUM_HOST_PORTS] = read_reqs; \
  PPCAT(type, _write_req_t) next_write_reqs[NUM_HOST_PORTS] = write_reqs; \
  PPCAT(type, _read_req_t) next_read_reqs[NUM_HOST_PORTS] = read_reqs; \
  PPCAT(type, _write_data_t) next_write_datas[NUM_HOST_PORTS] = write_datas; \
  uint1_t next_host_port_read_has_priority[NUM_HOST_PORTS] = host_port_read_has_priority; \
 \
  /* Loop that finds input req/ wr data for each dev port*/ \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    uint8_t selected_host = dev_to_selected_host[i]; \
    shared_res_bus_dev_arb_state_t state = host_port_arb_states[selected_host]; \
    PPCAT(type, _read_req_t) read_req = read_reqs[selected_host]; \
    PPCAT(type, _write_req_t) write_req = write_reqs[selected_host]; \
    PPCAT(type, _write_data_t) write_data = write_datas[selected_host]; \
    uint1_t read_priority = host_port_read_has_priority[selected_host]; \
    /* Try to start xfer for the current/round robin selected host dev port*/ \
    if(state==REQ) \
    { \
      /* Wait for a request*/ \
      /* Choose a request to handle, read or write*/ \
      uint1_t do_read; \
      uint1_t do_write; \
      if(read_priority) \
      { \
        /* Read priority*/ \
        if(read_req.valid) \
        { \
          do_read = 1; \
        } \
        else if(write_req.valid) \
        { \
          do_write = 1; \
        }  \
      } \
      else \
      { \
        /* Write priority*/ \
        if(write_req.valid) \
        { \
          do_write = 1; \
        } \
        else if(read_req.valid) \
        { \
          do_read = 1; \
        }  \
      } \
      if(do_read) \
      { \
        if(from_devs[i].read.req_ready) \
        { \
          o.to_devs[i].read.req = read_req; \
          next_read_reqs[selected_host].valid = 0; /* Done w req now*/ \
          read_priority = 0; /* Writes next*/ \
          o.to_devs[i].read.req.id = selected_host; /* Overides/ignores host value*/ \
          /*FRAME BUF ONLY o.to_frame_bufs[i].valid = 1; addr completes valid inputs, no input read data*/ \
          /* Waiting for output read data next*/ \
          state = RD_DATA; \
          /* Done with shared bus port inputs, move arb on*/ \
          next_dev_to_selected_host[i] = PPCAT(name, _next_host_sel)(selected_host, next_dev_to_selected_host); \
        } \
      } \
      else if(do_write) \
      { \
        if(from_devs[i].write.req_ready) \
        { \
          o.to_devs[i].write.req = write_req; \
          next_write_reqs[selected_host].valid = 0; /* Done w req now*/ \
          read_priority = 1; /* Reads next*/ \
          o.to_devs[i].write.req.id = selected_host; /* Overides/ignores host value*/ \
          /*FRAME BUF ONLY Write stil needs data still before valid input*/ \
          state = WR_DATA; \
          /* Not done with shared bus port inputs yet, dont change arb*/ \
        } \
      } \
      else \
      { \
        /* No read or write req from this port, move on*/ \
        next_dev_to_selected_host[i] = PPCAT(name, _next_host_sel)(selected_host, next_dev_to_selected_host); \
      } \
    } \
    /* TODO pass through write req and data*/ \
    else if(state==WR_DATA) /* Write data into dev*/ \
    { \
      /* Wait until valid write data*/ \
      if(write_data.valid) \
      { \
        if(from_devs[i].write.data_ready) \
        { \
          o.to_devs[i].write.data = write_data; \
          o.to_devs[i].write.data.id = selected_host; /* Overides/ignores host value*/ \
          next_write_datas[selected_host].valid = 0; /* Done w data now*/ \
          state = WR_RESP_STATE; \
          /* Done with shared bus port inputs, move arb on*/ \
          next_dev_to_selected_host[i] = PPCAT(name, _next_host_sel)(selected_host, next_dev_to_selected_host); \
        } \
      } \
    } \
    /* Update next reg values */ \
    next_host_port_arb_states[selected_host] = state; \
    /*Req and data assigned directly to next[*]. few items only above */ \
    /*next_read_reqs[selected_host] = read_req;*/ \
    /*next_write_reqs[selected_host] = write_req;*/ \
    /*next_write_datas[selected_host] = write_data;*/ \
    next_host_port_read_has_priority[selected_host] = read_priority; \
  } \
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
        next_host_port_arb_states[i] = REQ; \
      } \
    } \
    else if(host_port_arb_states[i]==WR_RESP_STATE) \
    { \
      /* Wait for valid write resp outgoing to host*/ \
      if(o.to_hosts[i].write.resp.valid & from_hosts[i].write.resp_ready)  \
      { \
        next_host_port_arb_states[i] = REQ; \
      } \
    } \
 \
    /* Save data into input buffers if signalling ready in handshake*/ \
    if(o.to_hosts[i].write.req_ready) \
    { \
      next_write_reqs[i] = from_hosts[i].write.req; \
    } \
    if(o.to_hosts[i].read.req_ready) \
    { \
      next_read_reqs[i] = from_hosts[i].read.req; \
    } \
    if(o.to_hosts[i].write.data_ready) \
    { \
      next_write_datas[i] = from_hosts[i].write.data; \
    } \
  } \
 \
  /* Update regs with next values*/ \
  dev_to_selected_host = next_dev_to_selected_host; \
  host_port_arb_states = next_host_port_arb_states; \
  read_reqs = next_read_reqs; \
  write_reqs = next_write_reqs; \
  write_datas = next_write_datas; \
  host_port_read_has_priority = next_host_port_read_has_priority; \
  \
  return o; \
}\
/* Multiple in flight 'pipelined' round robin arb*/ \
typedef struct PPCAT(name, _dev_arb_pipelined_t){ \
  PPCAT(type, _host_to_dev_t) to_devs[NUM_DEV_PORTS]; \
  PPCAT(type, _dev_to_host_t) to_hosts[NUM_HOST_PORTS]; \
}PPCAT(name, _dev_arb_pipelined_t); \
PPCAT(name, _dev_arb_pipelined_t) PPCAT(name, _dev_arb_pipelined)( \
  PPCAT(type, _dev_to_host_t) from_devs[NUM_DEV_PORTS], \
  PPCAT(type, _host_to_dev_t) from_hosts[NUM_HOST_PORTS] \
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
  /* Each channel has a valid+ready handshake */ \
 \
  /* Output signal*/ \
  PPCAT(name, _dev_arb_pipelined_t) o; /*Default all zeros single cycle pulses*/ \
   \
  /* Each dev port prioritizes/selects a specific host bus for input into device*/ \
  uint32_t i; \
  static uint8_t dev_to_selected_host[NUM_DEV_PORTS]; /* See reset below {0, 1}*/ \
  static uint1_t power_on_reset = 1; \
  if(power_on_reset) \
  { \
    for (i = 0; i < NUM_DEV_PORTS; i+=1) \
    { \
      dev_to_selected_host[i] = i; \
    } \
  } \
  power_on_reset = 0;\
 \
  /* Each dev port has FIFOs so will allow 'streaming' multiple read/write in flight*/ \
 \
  /* INPUT TO DEV SIDE*/ \
 \
  /* Default state doesnt change*/ \
  uint8_t next_dev_to_selected_host[NUM_DEV_PORTS] = dev_to_selected_host; \
 \
  /* Loop that muxes requests/inputs into the selected host bus for each dev port*/ \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    uint8_t selected_host = dev_to_selected_host[i]; \
    /* Connect the selected requests/inputs host to dev[i] handshakes */ \
    o.to_devs[i].read.req = from_hosts[selected_host].read.req; \
    o.to_devs[i].read.req.id = selected_host; /* Overides/ignores host value*/ \
    o.to_devs[i].write.req = from_hosts[selected_host].write.req; \
    o.to_devs[i].write.req.id = selected_host; /* Overides/ignores host value*/ \
    o.to_devs[i].write.data = from_hosts[selected_host].write.data; \
    o.to_devs[i].write.data.id = selected_host; /* Overides/ignores host value*/ \
    o.to_hosts[selected_host].read.req_ready = from_devs[i].read.req_ready; \
    o.to_hosts[selected_host].write.req_ready = from_devs[i].write.req_ready; \
    o.to_hosts[selected_host].write.data_ready = from_devs[i].write.data_ready; \
    /* Done with host inputs, move arb on*/ \
    next_dev_to_selected_host[i] = PPCAT(name, _next_host_sel)(selected_host, next_dev_to_selected_host); \
  } \
 \
  /* DEV WAS HERE*/ \
 \
  /* Outputs from DEV is muxed into output fifos based on ID=host port*/ \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    /* Output write resp, err code unused*/ \
    if(from_devs[i].write.resp.valid) \
    { \
      uint8_t selected_host = from_devs[i].write.resp.id; \
      o.to_hosts[selected_host].write.resp = from_devs[i].write.resp; \
      o.to_devs[i].write.resp_ready = from_hosts[selected_host].write.resp_ready; \
    } \
    /* Output read data*/ \
    if(from_devs[i].read.data.valid) \
    { \
      uint8_t selected_host = from_devs[i].read.data.id; \
      o.to_hosts[selected_host].read.data = from_devs[i].read.data; \
      o.to_devs[i].read.data_ready = from_hosts[selected_host].read.data_ready; \
    } \
  } \
 \
  /* Update regs with next values*/ \
  dev_to_selected_host = next_dev_to_selected_host; \
  return o; \
} \
\
/* Multiple in flight */ \
/*'pipelined' round robin */ \
/*connection (not arb, no muxing)*/ \
/* ONE HOT STATE! */ \
typedef struct PPCAT(name, _dev_multi_host_connect_t){ \
  PPCAT(type, _host_to_dev_t) to_devs[NUM_DEV_PORTS][NUM_HOST_PORTS]; \
  PPCAT(type, _dev_to_host_t) to_hosts[NUM_HOST_PORTS]; \
}PPCAT(name, _dev_multi_host_connect_t); \
PPCAT(name, _dev_multi_host_connect_t) PPCAT(name, _dev_multi_host_connect)( \
  PPCAT(type, _dev_to_host_t) from_devs[NUM_DEV_PORTS][NUM_HOST_PORTS], \
  PPCAT(type, _host_to_dev_t) from_hosts[NUM_HOST_PORTS] \
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
  /* Each channel has a valid+ready handshake */ \
 \
  /* Output signal*/ \
  PPCAT(name, _dev_multi_host_connect_t) o; /*Default all zeros single cycle pulses*/ \
   \
  /* Each dev port prioritizes/selects a specific host bus for input into device*/ \
  uint32_t i, j; \
  static uint1_t dev_to_selected_host[NUM_DEV_PORTS][NUM_HOST_PORTS]; /* See one hot reset below */ \
  static uint1_t power_on_reset = 1; \
  if(power_on_reset) \
  { \
    for (i = 0; i < NUM_DEV_PORTS; i+=1) \
    { \
      dev_to_selected_host[i][i] = 1; \
    } \
  } \
  power_on_reset = 0;\
 \
  /* Each dev port has FIFOs so will allow 'streaming' multiple read/write in flight*/ \
 \
  /* INPUT TO DEV SIDE*/ \
 \
  /* Loop that connects requests/inputs to output host bus for each dev port*/ \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    for (j = 0; j < NUM_HOST_PORTS; j+=1) \
    { \
      /* Connect data lines directly*/ \
      o.to_devs[i][j].read.req.data = from_hosts[j].read.req.data; \
      o.to_devs[i][j].read.req.id = from_hosts[j].read.req.id; \
      o.to_devs[i][j].write.req.data = from_hosts[j].write.req.data; \
      o.to_devs[i][j].write.req.id = from_hosts[j].write.req.id; \
      o.to_devs[i][j].write.data.burst = from_hosts[j].write.data.burst; \
      o.to_devs[i][j].write.data.id = from_hosts[j].write.data.id; \
      /* Small one hot logic for handshake*/ \
      /* ZEROS IMPLIED */ \
      if(dev_to_selected_host[i][j]) \
      { \
        o.to_devs[i][j].read.req.valid = from_hosts[j].read.req.valid; \
        o.to_hosts[j].read.req_ready = from_devs[i][j].read.req_ready; \
        o.to_devs[i][j].write.req.valid = from_hosts[j].write.req.valid; \
        o.to_hosts[j].write.req_ready = from_devs[i][j].write.req_ready; \
        o.to_devs[i][j].write.data.valid = from_hosts[j].write.data.valid; \
        o.to_hosts[j].write.data_ready = from_devs[i][j].write.data_ready; \
      } \
    } \
    /* Rotate one hot dev_to_selected_host[i] */ \
    uint1_t top_selected_host_bit = dev_to_selected_host[i][NUM_HOST_PORTS-1]; \
    ARRAY_1SHIFT_INTO_BOTTOM(dev_to_selected_host[i], NUM_HOST_PORTS, top_selected_host_bit) \
  } \
 \
  /* DEV WAS HERE*/ \
 \
  /* NEED TO ASSUME OUTPUT IS READY */ \
  /* DIRECTLY CONNECT multiple host outputs from dev */ \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    for (j = 0; j < NUM_HOST_PORTS; j+=1) \
    { \
      /* Zeros to valid and ready implied */ \
      /* Output write resp, err code unused*/ \
      if(from_devs[i][j].write.resp.valid) \
      { \
        o.to_hosts[j].write.resp = from_devs[i][j].write.resp; \
        o.to_devs[i][j].write.resp_ready = from_hosts[j].write.resp_ready; \
      } \
      /* Output read data*/ \
      if(from_devs[i][j].read.data.valid) \
      { \
        o.to_hosts[j].read.data = from_devs[i][j].read.data; \
        o.to_devs[i][j].read.data_ready = from_hosts[j].read.data_ready; \
      } \
    } \
  } \
  return o; \
} \
 \
/* Multiple in flight 'pipelined' round robin arb*/ \
/* GREEDY avoiding nothing periods of round robin waiting when possible */ \
/* Pick next shared bus to arb based on what other ports have chosen*/ \
typedef struct PPCAT(name, _dev_arb_pipelined_greedy_t){ \
  PPCAT(type, _host_to_dev_t) to_devs[NUM_DEV_PORTS]; \
  PPCAT(type, _dev_to_host_t) to_hosts[NUM_HOST_PORTS]; \
}PPCAT(name, _dev_arb_pipelined_greedy_t); \
PPCAT(name, _dev_arb_pipelined_greedy_t) PPCAT(name, _dev_arb_pipelined_greedy)( \
  PPCAT(type, _dev_to_host_t) from_devs[NUM_DEV_PORTS], \
  PPCAT(type, _host_to_dev_t) from_hosts[NUM_HOST_PORTS] \
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
  /* Each channel has a valid+ready handshake */ \
 \
  /* Output signal*/ \
  PPCAT(name, _dev_arb_pipelined_greedy_t) o; /*Default all zeros single cycle pulses*/ \
   \
  /* Each dev port prioritizes/selects a specific host bus for input into device*/ \
  int32_t i, j; \
  static uint8_t dev_to_selected_host[NUM_DEV_PORTS]; /* See reset below {0, 1}*/ \
  static uint1_t power_on_reset = 1; \
  if(power_on_reset) \
  { \
    for (i = 0; i < NUM_DEV_PORTS; i+=1) \
    { \
      dev_to_selected_host[i] = i; \
    } \
  } \
  power_on_reset = 0;\
 \
  /* Each dev port has FIFOs so will allow 'streaming' multiple read/write in flight*/ \
 \
  /* INPUT TO DEV SIDE*/ \
 \
  /* Default state doesnt change*/ \
  uint8_t next_dev_to_selected_host[NUM_DEV_PORTS] = dev_to_selected_host; \
 \
  /* Loop that muxes requests/inputs into the selected host bus for each dev port*/ \
  /* What hosts have requests pending? */ \
  uint1_t host_has_req_now[NUM_HOST_PORTS]; \
  for (j = 0; j < NUM_HOST_PORTS; j+=1) \
  { \
    host_has_req_now[j] =  \
      from_hosts[j].read.req.valid |  \
      from_hosts[j].write.req.valid | \
      from_hosts[j].write.data.valid; \
  } \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    uint8_t selected_host = dev_to_selected_host[i]; \
    /* Connect the selected requests/inputs host to dev[i] handshakes */ \
    o.to_devs[i].read.req = from_hosts[selected_host].read.req; \
    o.to_devs[i].read.req.id = selected_host; /* Overides/ignores host value*/ \
    o.to_devs[i].write.req = from_hosts[selected_host].write.req; \
    o.to_devs[i].write.req.id = selected_host; /* Overides/ignores host value*/ \
    o.to_devs[i].write.data = from_hosts[selected_host].write.data; \
    o.to_devs[i].write.data.id = selected_host; /* Overides/ignores host value*/ \
    o.to_hosts[selected_host].read.req_ready = from_devs[i].read.req_ready; \
    o.to_hosts[selected_host].write.req_ready = from_devs[i].write.req_ready; \
    o.to_hosts[selected_host].write.data_ready = from_devs[i].write.data_ready; \
    /* Default arb state doesnt change so not valid to use this host again next*/ \
    host_has_req_now[selected_host] = 0; \
  } \
  \
  /* Greedy logic to determine next arb state */ \
  /* Allow same host to continue to be selected if others inactive*/ \
  /* Jump to next='round robin order' host that has a request */ \
  /* Backwards loop because 'next' is like a shift, etc*/ \
  for (i = (NUM_DEV_PORTS-1); i >=0; i-=1) \
  { \
    /* find_next_host_req(dev_to_selected_host[i], host_has_req_now); */ \
    uint8_t maybe_next_host = dev_to_selected_host[i]; \
    uint1_t found_next_host = 0; \
    for (j = 0; j < (NUM_HOST_PORTS-1); j+=1) \
    {  \
      /* If not found a next host yet, increment and check if has req */ \
      if(!found_next_host){ \
        maybe_next_host = PPCAT(name, _host_port_inc)(maybe_next_host); \
        if(host_has_req_now[maybe_next_host]){ \
          found_next_host = 1; \
          next_dev_to_selected_host[i] = maybe_next_host; \
          /* Clear so isnt resused by other dev */ \
          host_has_req_now[maybe_next_host] = 0; \
        } \
      } \
    } \
  } \
  /* Update regs with next values*/ \
  dev_to_selected_host = next_dev_to_selected_host; \
 \
  /* DEV WAS HERE*/ \
 \
  /* Outputs from DEV is muxed into output fifos based on ID=host port*/ \
  for (i = 0; i < NUM_DEV_PORTS; i+=1) \
  { \
    /* Output write resp, err code unused*/ \
    if(from_devs[i].write.resp.valid) \
    { \
      uint8_t selected_host = from_devs[i].write.resp.id; \
      o.to_hosts[selected_host].write.resp = from_devs[i].write.resp; \
      o.to_devs[i].write.resp_ready = from_hosts[selected_host].write.resp_ready; \
    } \
    /* Output read data*/ \
    if(from_devs[i].read.data.valid) \
    { \
      uint8_t selected_host = from_devs[i].read.data.id; \
      o.to_hosts[selected_host].read.data = from_devs[i].read.data; \
      o.to_devs[i].read.data_ready = from_hosts[selected_host].read.data_ready; \
    } \
  } \
 \
  return o; \
}

// Instantiate the arb module with to-from wires for user
#define SHARED_BUS_ARB(type, bus_name, NUM_DEV_PORTS) \
PPCAT(type, _dev_to_host_t) PPCAT(bus_name, _to_host)[NUM_DEV_PORTS]; \
PRAGMA_MESSAGE(FEEDBACK PPCAT(bus_name, _to_host)) /* Value from last assignment*/ \
PPCAT(bus_name, _dev_arb_t) PPCAT(bus_name, _arb) = PPCAT(bus_name, _dev_arb)(PPCAT(bus_name, _to_host), PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)); \
PPCAT(type, _host_to_dev_t) PPCAT(bus_name, _from_host)[NUM_DEV_PORTS]; \
PPCAT(bus_name, _from_host) = PPCAT(bus_name, _arb).to_devs; \
PPCAT(bus_name, _dev_to_host_wires_on_dev_clk) = PPCAT(bus_name, _arb).to_hosts;
//
#define SHARED_BUS_ARB_PIPELINED(type, bus_name, NUM_DEV_PORTS) \
PPCAT(type, _dev_to_host_t) PPCAT(bus_name, _to_host)[NUM_DEV_PORTS]; \
PRAGMA_MESSAGE(FEEDBACK PPCAT(bus_name, _to_host)) /* Value from last assignment*/ \
PPCAT(bus_name, _dev_arb_pipelined_t) PPCAT(bus_name, _arb) = PPCAT(bus_name, _dev_arb_pipelined)(PPCAT(bus_name, _to_host), PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)); \
PPCAT(type, _host_to_dev_t) PPCAT(bus_name, _from_host)[NUM_DEV_PORTS]; \
PPCAT(bus_name, _from_host) = PPCAT(bus_name, _arb).to_devs; \
PPCAT(bus_name, _dev_to_host_wires_on_dev_clk) = PPCAT(bus_name, _arb).to_hosts;
//
#define SHARED_BUS_MULTI_HOST_CONNECT(type, bus_name, NUM_HOST_PORTS, NUM_DEV_PORTS) \
PPCAT(type, _dev_to_host_t) PPCAT(bus_name, _to_hosts)[NUM_DEV_PORTS][NUM_HOST_PORTS]; \
PRAGMA_MESSAGE(FEEDBACK PPCAT(bus_name,_to_hosts)) /* Value from last assignment (by user)*/ \
PPCAT(bus_name, _dev_multi_host_connect_t) PPCAT(bus_name, _connect) = PPCAT(bus_name, _dev_multi_host_connect)(PPCAT(bus_name, _to_hosts), PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)); \
PPCAT(type, _host_to_dev_t) PPCAT(bus_name, _from_hosts)[NUM_DEV_PORTS][NUM_HOST_PORTS]; \
PPCAT(bus_name, _from_hosts) = PPCAT(bus_name, _connect).to_devs; \
PPCAT(bus_name, _dev_to_host_wires_on_dev_clk) = PPCAT(bus_name, _connect).to_hosts;
//
#define SHARED_BUS_ARB_PIPELINED_GREEDY(type, bus_name, NUM_DEV_PORTS) \
PPCAT(type, _dev_to_host_t) PPCAT(bus_name, _to_host)[NUM_DEV_PORTS]; \
PRAGMA_MESSAGE(FEEDBACK PPCAT(bus_name, _to_host)) /* Value from last assignment*/ \
PPCAT(bus_name, _dev_arb_pipelined_greedy_t) PPCAT(bus_name, _arb) = PPCAT(bus_name, _dev_arb_pipelined_greedy)(PPCAT(bus_name, _to_host), PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)); \
PPCAT(type, _host_to_dev_t) PPCAT(bus_name, _from_host)[NUM_DEV_PORTS]; \
PPCAT(bus_name, _from_host) = PPCAT(bus_name, _arb).to_devs; \
PPCAT(bus_name, _dev_to_host_wires_on_dev_clk) = PPCAT(bus_name, _arb).to_hosts;


// Each channel of 5 channels host<->dev link needs async fifo
// 3 write, 2 read
// INST_ARRAY doesnt support async fifos
#define SHARED_BUS_ASYNC_FIFO_DECL(type, bus_name, NUM_STR) \
ASYNC_CLK_CROSSING(PPCAT(type, _write_req_data_t), PPCAT(bus_name,_fifo##NUM_STR##_write_req), SHARED_RES_CLK_CROSS_FIFO_DEPTH) \
ASYNC_CLK_CROSSING(PPCAT(type, _write_burst_word_t), PPCAT(bus_name,_fifo##NUM_STR##_write_data), SHARED_RES_CLK_CROSS_FIFO_DEPTH) \
ASYNC_CLK_CROSSING(PPCAT(type, _write_resp_data_t), PPCAT(bus_name,_fifo##NUM_STR##_write_resp), SHARED_RES_CLK_CROSS_FIFO_DEPTH) \
ASYNC_CLK_CROSSING(PPCAT(type, _read_req_data_t), PPCAT(bus_name,_fifo##NUM_STR##_read_req), SHARED_RES_CLK_CROSS_FIFO_DEPTH) \
ASYNC_CLK_CROSSING(PPCAT(type, _read_burst_word_t), PPCAT(bus_name,_fifo##NUM_STR##_read_data), SHARED_RES_CLK_CROSS_FIFO_DEPTH)


#define SHARED_BUS_ASYNC_FIFO_HOST_WIRING(type, bus_name, NUM_STR)\
/* Write into fifo (to dev) <= PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR]*/ \
/* PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR] <= Read from fifo (from dev)*/ \
/* FIFO is one of the channels...*/ \
/**/ \
/* Write request data into fifo*/ \
/* Write request ready out of fifo*/ \
PPCAT(type, _write_req_data_t) PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_req_write_req_data))[1]; \
PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_req_write_req_data))[0] = PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.req.data; \
PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_req_write_t)) PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_req_write_req_write)) = \
  PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_req_WRITE_1))(PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_req_write_req_data)), PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.req.valid); \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].write.req_ready = PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_req_write_req_write)).ready; \
/* Write data data into fifo*/ \
/* Write data ready out of fifo*/ \
PPCAT(type, _write_burst_word_t) PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_data_write_data_data))[1]; \
PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_data_write_data_data))[0] = PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.data.burst; \
PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_data_write_t)) PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_data_write_data_write)) = \
  PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_data_WRITE_1))(PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_data_write_data_data)), PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.data.valid); \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].write.data_ready = PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _write_data_write_data_write)).ready; \
/* Write resp data out of fifo*/ \
/* Write resp ready into fifo*/ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_read_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_write_resp_read) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_READ_1)(bus_name##_host_to_dev_wires_on_host_clk[NUM_STR].write.resp_ready); \
bus_name##_dev_to_host_wires_on_host_clk[NUM_STR].write.resp.data = PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_write_resp_read).data[0]; \
bus_name##_dev_to_host_wires_on_host_clk[NUM_STR].write.resp.valid = PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_write_resp_read).valid; \
/* Read req data into fifo*/ \
/* Read req ready out of fifo*/ \
PPCAT(type, _read_req_data_t) PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _read_req_read_req_data))[1]; \
PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _read_req_read_req_data))[0] = PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].read.req.data; \
PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _read_req_write_t)) PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _read_req_read_req_write)) = \
  PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _read_req_WRITE_1))(PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _read_req_read_req_data)), PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].read.req.valid); \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].read.req_ready = PPCAT(PPCAT(bus_name, _fifo), PPCAT(NUM_STR, _read_req_read_req_write)).ready; \
/* Read data data out of fifo*/ \
/* Read data ready into fifo*/ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_data_read) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_READ_1)(bus_name##_host_to_dev_wires_on_host_clk[NUM_STR].read.data_ready); \
bus_name##_dev_to_host_wires_on_host_clk[NUM_STR].read.data.burst = PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_data_read).data[0]; \
bus_name##_dev_to_host_wires_on_host_clk[NUM_STR].read.data.valid = PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_data_read).valid;


#define SHARED_BUS_ASYNC_FIFO_HOST_WIRING_PIPELINED(type, bus_name, NUM_STR)\
/* This version gates valid ready handshake based on limited number in flight*/ \
static uint8_t PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_in_flight); \
uint1_t PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_gate_open) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_in_flight) < SHARED_RES_CLK_CROSS_FIFO_DEPTH; \
static uint8_t PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_in_flight); \
uint1_t PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_gate_open) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_in_flight) < SHARED_RES_CLK_CROSS_FIFO_DEPTH; \
static uint8_t PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_in_flight); \
uint1_t PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_gate_open) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_in_flight) < SHARED_RES_CLK_CROSS_FIFO_DEPTH; \
/* Write into fifo (to dev) <= PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR]*/ \
/* PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR] <= Read from fifo (from dev)*/ \
/* FIFO is one of the channels...*/ \
/**/ \
/* Write request data into fifo*/ \
/* Write request ready out of fifo*/ \
PPCAT(type, _write_req_data_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_write_req_data)[1]; \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_write_req_data)[0] = PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.req.data; \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_write_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_write_req_write) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_WRITE_1)(PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_write_req_data), \
  PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.req.valid & PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_gate_open)); \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].write.req_ready = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_write_req_write).ready & PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_gate_open); \
/* Write req increments in flight counter */ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_in_flight) +=  \
  (PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_gate_open) & \
   PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.req.valid & \
   PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_write_req_write).ready); \
/* Write data data into fifo*/ \
/* Write data ready out of fifo*/ \
PPCAT(type, _write_burst_word_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_write_data_data)[1]; \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_write_data_data)[0] = PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.data.burst; \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_write_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_write_data_write) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_WRITE_1)(PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_write_data_data), \
  PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.data.valid & PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_gate_open)); \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].write.data_ready = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_write_data_write).ready & PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_gate_open); \
/* Write data increments in flight counter */ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_in_flight) += \
  (PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_gate_open) & \
   PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.data.valid & \
   PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_write_data_write).ready); \
/* Write resp data out of fifo*/ \
/* Write resp ready into fifo*/ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_read_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_write_resp_read) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_READ_1)(PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.resp_ready); \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].write.resp.data = PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_write_resp_read).data[0]; \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].write.resp.valid = PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_write_resp_read).valid; \
/* Write resp decrements in flight counters*/ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_req_in_flight) -= \
  (PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_write_resp_read).valid & PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.resp_ready); \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_data_in_flight) -= \
  (PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_write_resp_write_resp_read).valid & PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].write.resp_ready); \
/* Read req data into fifo*/ \
/* Read req ready out of fifo*/ \
PPCAT(type, _read_req_data_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_read_req_data)[1]; \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_read_req_data)[0] = PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].read.req.data; \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_write_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_read_req_write) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_WRITE_1)(PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_read_req_data), \
  PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].read.req.valid & PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_gate_open)); \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].read.req_ready = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_read_req_write).ready & PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_gate_open); \
/* Read req increments in flight counter */ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_in_flight) += \
  (PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_gate_open) & \
   PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].read.req.valid & \
   PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_read_req_write).ready); \
/* Read data data out of fifo*/ \
/* Read data ready into fifo*/ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_t) PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_data_read) = \
  PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_READ_1)(PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].read.data_ready); \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].read.data.burst = PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_data_read).data[0]; \
PPCAT(bus_name, _dev_to_host_wires_on_host_clk)[NUM_STR].read.data.valid = PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_data_read).valid; \
/* Read data resp decrements in flight counter */ \
PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_req_in_flight) -= \
  (PPCAT(PPCAT(PPCAT(bus_name,_fifo),NUM_STR),_read_data_read_data_read).valid & PPCAT(bus_name, _host_to_dev_wires_on_host_clk)[NUM_STR].read.data_ready);


#define SHARED_BUS_ASYNC_FIFO_DEV_WIRING(type, bus_name, NUM_STR) \
/* Write into fifo (to host) <= PPCAT(bus_name, _dev_to_host_wires_on_dev_clk)[NUM_STR] */ \
/* PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR] <= Read from fifo (from host) */ \
/* FIFO is one of the channels... */ \
/**/ \
/* Write request data out of fifo */ \
/* Write request ready back into fifo */ \
PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_req_read_t) PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_req_write_req_read) = \
  PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_req_READ_1)(PPCAT(bus_name, _dev_to_host_wires_on_dev_clk)[NUM_STR].write.req_ready); \
PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR].write.req.data = PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_req_write_req_read).data[0]; \
PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR].write.req.valid = PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_req_write_req_read).valid; \
/* Write data data out of fifo */ \
/* Write data ready back into fifo */ \
PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_data_read_t) PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_data_write_data_read) = \
  PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_data_READ_1)(PPCAT(bus_name, _dev_to_host_wires_on_dev_clk)[NUM_STR].write.data_ready); \
PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR].write.data.burst = PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_data_write_data_read).data[0]; \
PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR].write.data.valid = PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_data_write_data_read).valid; \
/* Write resp data into fifo */ \
/* Write resp ready out of fifo */ \
PPCAT(type, _write_resp_data_t) PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_resp_write_resp_data)[1]; \
PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_resp_write_resp_data)[0] = PPCAT(bus_name, _dev_to_host_wires_on_dev_clk)[NUM_STR].write.resp.data; \
PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_resp_write_t) PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_resp_write_resp_write) = \
  PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_resp_WRITE_1)(PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_resp_write_resp_data), PPCAT(bus_name, _dev_to_host_wires_on_dev_clk)[NUM_STR].write.resp.valid); \
PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR].write.resp_ready = PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_write_resp_write_resp_write).ready; \
/* Read req data out of fifo */ \
/* Read req ready back into fifo */ \
PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_req_read_t) PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_req_read_req_read) = \
  PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_req_READ_1)(PPCAT(bus_name, _dev_to_host_wires_on_dev_clk)[NUM_STR].read.req_ready); \
PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR].read.req.data = PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_req_read_req_read).data[0]; \
PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR].read.req.valid = PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_req_read_req_read).valid; \
/* Read data data into fifo */ \
/* Read data ready out of fifo */ \
PPCAT(type, _read_burst_word_t) PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_data_read_data_data)[1]; \
PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_data_read_data_data)[0] = PPCAT(bus_name, _dev_to_host_wires_on_dev_clk)[NUM_STR].read.data.burst; \
PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_data_write_t) PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_data_read_data_write) = \
  PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_data_WRITE_1)(PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_data_read_data_data), PPCAT(bus_name, _dev_to_host_wires_on_dev_clk)[NUM_STR].read.data.valid); \
PPCAT(bus_name, _host_to_dev_wires_on_dev_clk)[NUM_STR].read.data_ready = PPCAT(PPCAT(bus_name,_fifo), NUM_STR##_read_data_read_data_write).ready;

