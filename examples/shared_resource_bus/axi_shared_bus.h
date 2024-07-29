#pragma once
#include "uintN_t.h"
#include "stream/stream.h"

// Use AXI bus ports from the Xilinx Memory controller example
#include "axi/axi.h"
// TODO combine/merged parts of #include "axi/axi.h" in this
// use axi32 types, here could select bit widths?
//#define axi_addr_t uint32_t
//#define axi_id_t uint16_t
#define AXI_BUS_BYTE_WIDTH 4 // 32b
#define AXI_BUS_BYTE_WIDTH_LOG2 2

typedef struct axi_write_req_t
{
  // Address
  //  "Write this stream to a location in memory"
  //  Must be valid before data starts
  // USE shared bus id, axi_id_t awid;
  axi_addr_t awaddr; 
  uint8_t awlen; // Number of transfer cycles minus one
  uint3_t awsize; // 2^size = Transfer width in bytes
  uint2_t awburst;
}axi_write_req_t;
typedef struct axi_write_data_t
{
  // Data stream to be written to memory
  uint8_t wdata[AXI_BUS_BYTE_WIDTH]; // 4 bytes, 32b
  uint1_t wstrb[AXI_BUS_BYTE_WIDTH];
  // USE shared bus last, uint1_t wlast;
}axi_write_data_t;
typedef struct axi_write_resp_t
{
  // Write response
  // USE shared bus id, axi_id_t bid;
  uint2_t bresp; // Error code
} axi_write_resp_t;
typedef struct axi_read_req_t
{
  // Address
  //   "Give me a stream from a place in memory"
  //   Must be valid before data starts
  // USE shared bus id, axi_id_t arid;
  axi_addr_t araddr;
  uint8_t arlen; // Number of transfer cycles minus one
  uint3_t arsize; // 2^size = Transfer width in bytes
  uint2_t arburst;
} axi_read_req_t;
/*typedef struct axi_read_resp_t
{
  // Read response
  // USE shared bus id, axi_id_t rid;
  uint2_t rresp;
} axi_read_resp_t;*/
typedef struct axi_read_data_t
{
  // Data stream from memory
  uint8_t rdata[AXI_BUS_BYTE_WIDTH]; // 4 bytes, 32b
  uint2_t rresp;
  // USE shared bus last, uint1_t rlast;
} axi_read_data_t;

// Helpers to fill in single word requests and responses
axi_read_req_t axi_addr_to_read(uint32_t addr)
{
  axi_read_req_t req;
  req.araddr = addr;
  req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  req.arsize = 2; // 2^2=4 bytes per transfer
  req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
  return req;
}
uint32_t axi_read_to_data(axi_read_data_t resp)
{
  uint32_t rv = uint8_array4_le(resp.rdata);
  return rv;
}
typedef struct axi_write_t{
  axi_write_req_t req;
  axi_write_data_t data;
}axi_write_t;
axi_write_t axi_addr_data_to_write(uint32_t addr, uint32_t data)
{
  axi_write_t rv;
  axi_write_req_t req;
  req.awaddr = addr;
  req.awlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  req.awsize = 2; // 2^2=4 bytes per transfer
  req.awburst = BURST_FIXED; // Not a burst, single fixed address per transfer 
  axi_write_data_t wr_data;
  // All 4 bytes are being transfered (uint to array)
  uint32_t i;
  for(i=0; i<4; i+=1)
  {
    wr_data.wdata[i] = data >> (i*8);
    wr_data.wstrb[i] = 1;
  }
  rv.req = req;
  rv.data = wr_data;
  return rv;
}


// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
#include "shared_resource_bus.h"
SHARED_BUS_TYPE_DEF(
  axi_shared_bus_t,
  axi_write_req_t,
  axi_write_data_t,
  axi_write_resp_t,
  axi_read_req_t,
  axi_read_data_t
)

// How RAM port is 'converted' to shared bus connection
// Multi in flight dev_ctrl
// Always ready for inputs from host
// Relies on host always being ready for output from dev
typedef struct axi_shared_bus_dev_ctrl_t{
  // ex. dev inputs
  axi32_host_to_dev_t to_axi32_dev;
  // Bus signals driven to host
  axi_shared_bus_t_dev_to_host_t to_host;
}axi_shared_bus_dev_ctrl_t;
axi_shared_bus_dev_ctrl_t axi_shared_bus_dev_ctrl_pipelined(
  // Controller Inputs:
  // Ex. dev outputs
  axi32_dev_to_host_t from_axi32_dev,
  // Bus signals from the host
  axi_shared_bus_t_host_to_dev_t from_host
)
{
  // Is same bus just renaming struct fields/types, pass through
  axi_shared_bus_dev_ctrl_t o;
  // DATA, ID, VALID, READY
  // Read req
  o.to_axi32_dev.read.req.araddr = from_host.read.req.data.user.araddr;
  o.to_axi32_dev.read.req.arlen = from_host.read.req.data.user.arlen;
  o.to_axi32_dev.read.req.arsize = from_host.read.req.data.user.arsize;
  o.to_axi32_dev.read.req.arburst = from_host.read.req.data.user.arburst;
  o.to_axi32_dev.read.req.arid = from_host.read.req.id;
  o.to_axi32_dev.read.req.arvalid = from_host.read.req.valid;
  o.to_host.read.req_ready = from_axi32_dev.read.arready;
  // Read data/resp
  o.to_host.read.data.burst.data_resp.user.rdata = from_axi32_dev.read.data.rdata;
  o.to_host.read.data.burst.data_resp.user.rresp =  from_axi32_dev.read.resp.rresp;
  o.to_host.read.data.burst.last = from_axi32_dev.read.data.rlast;
  o.to_host.read.data.id = from_axi32_dev.read.resp.rid;
  o.to_host.read.data.valid = from_axi32_dev.read.data.rvalid;
  o.to_axi32_dev.read.rready = from_host.read.data_ready;
  // Write req
  o.to_axi32_dev.write.req.awaddr = from_host.write.req.data.user.awaddr;
  o.to_axi32_dev.write.req.awlen = from_host.write.req.data.user.awlen;
  o.to_axi32_dev.write.req.awsize = from_host.write.req.data.user.awsize;
  o.to_axi32_dev.write.req.awburst = from_host.write.req.data.user.awburst;
  o.to_axi32_dev.write.req.awid = from_host.write.req.id;
  o.to_axi32_dev.write.req.awvalid = from_host.write.req.valid;
  o.to_host.write.req_ready = from_axi32_dev.write.awready;
  // Write data
  o.to_axi32_dev.write.data.wdata = from_host.write.data.burst.data_word.user.wdata;
  o.to_axi32_dev.write.data.wstrb = from_host.write.data.burst.data_word.user.wstrb;
  o.to_axi32_dev.write.data.wlast = from_host.write.data.burst.last;
  o.to_axi32_dev.write.data.wvalid = from_host.write.data.valid;
  o.to_host.write.data_ready = from_axi32_dev.write.wready;
  // Write resp
  o.to_host.write.resp.data.user.bresp = from_axi32_dev.write.resp.bresp;
  o.to_host.write.resp.id = from_axi32_dev.write.resp.bid;
  o.to_host.write.resp.valid = from_axi32_dev.write.resp.bvalid;
  o.to_axi32_dev.write.bready = from_host.write.resp_ready;

  return o;
}

// Logic for read priority arbitration
typedef struct rd_pri_port_arb_t{
  axi_shared_bus_t_dev_to_host_t to_other_host;
  axi_shared_bus_t_dev_to_host_t to_rd_pri_host;
  axi_shared_bus_t_host_to_dev_t to_dev;
}rd_pri_port_arb_t;
rd_pri_port_arb_t rd_pri_port_arb(
  axi_shared_bus_t_host_to_dev_t other_from_host,
  axi_shared_bus_t_host_to_dev_t rd_pri_from_host,
  axi_shared_bus_t_dev_to_host_t from_dev
){
  // Special case adapted from dev_arb_pipelined() func from shared_resource_bus.h
  
  /* 5 channels between each host and device*/
  /* Request to start*/
  /*  Read req (addr)*/
  /*  Write req (addr)*/
  /* Exchange of data*/
  /*  Read data+resp (data+err)*/
  /*  Write data (data bytes)*/
  /*  Write resp (err code)*/
  /* Each channel has a valid+ready handshake */

  /* Output signal*/
  rd_pri_port_arb_t o; /*Default all zeros single cycle pulses*/
  
  /* Each dev port prioritizes/selects a specific host bus for input into device*/
  static uint1_t read_req_sel_pri_host = 1;

  /* Each dev port has FIFOs so will allow 'streaming' multiple read/write in flight*/

  /* INPUT TO DEV SIDE*/

  // Read side muxing
  if(read_req_sel_pri_host)
  {
    o.to_dev.read.req = rd_pri_from_host.read.req;
    // Priority ID one more than regular ids used by axi_xil_mem 
    o.to_dev.read.req.id = 0xFF; //SHARED_AXI_XIL_MEM_NUM_THREADS; /* Overides/ignores priority host ID value*/
    o.to_rd_pri_host.read.req_ready = from_dev.read.req_ready;
    // Switch to non priority port if run out priority requests
    if(!rd_pri_from_host.read.req.valid)
    {
      read_req_sel_pri_host = 0;
    }
  }
  else
  {
    // Uses req w ID from upstream other host
    o.to_dev.read.req = other_from_host.read.req;
    o.to_other_host.read.req_ready = from_dev.read.req_ready;
    // Switch to priority port if it makes any requests
    if(rd_pri_from_host.read.req.valid)
    {
      read_req_sel_pri_host = 1;
    }
  }
  // Write input side is always connected to other host (priority port is read only)
  o.to_dev.write.req = other_from_host.write.req;
  o.to_other_host.write.req_ready = from_dev.write.req_ready;
  //
  o.to_dev.write.data = other_from_host.write.data;
  o.to_other_host.write.data_ready = from_dev.write.data_ready;

  /* DEV WAS HERE*/

  /* Outputs from DEV is muxed into output fifos based on ID=host port*/
  // ONLY FOR READ SIDE
  /* Output read data*/
  if(from_dev.read.data.valid)
  {
    if(from_dev.read.data.id == 0xFF) //SHARED_AXI_XIL_MEM_NUM_THREADS)
    {
      // Priority read
      o.to_rd_pri_host.read.data = from_dev.read.data;
      o.to_dev.read.data_ready = rd_pri_from_host.read.data_ready;
    }
    else
    {
      // Other
      o.to_other_host.read.data = from_dev.read.data;
      o.to_dev.read.data_ready = other_from_host.read.data_ready;
    }
  }
  /* Output write resp, err code unused*/
  // WRITE SIDE DIRECTLY CONNECTED
  o.to_other_host.write.resp = from_dev.write.resp;
  o.to_dev.write.resp_ready = other_from_host.write.resp_ready;
  
  return o;
}


// Logic for how to start and finish a write of some words to RAM
/* TODO dont use logic like if(ready) valid=1 in places! */
// Start
typedef struct axi_shared_bus_write_stream_start_t{
  uint1_t done;
  uint1_t ready_for_word;
  axi_shared_bus_t_write_host_to_dev_t to_dev;
}axi_shared_bus_write_stream_start_t;
axi_shared_bus_write_stream_start_t axi_shared_bus_write_stream_start(
  uint1_t ready_for_outputs,
  uint32_t addr,
  uint32_t num_words,
  uint32_t word_in,
  uint1_t word_in_valid,  
  axi_shared_bus_t_write_dev_to_host_t from_dev
){
  /* Start N u32 writes using bus helper FSM */ 
  static uint32_t word_counter = (uint32_t)1 << 31; 
  static uint32_t bus_addr; 
  static uint1_t done; 
  axi_shared_bus_write_stream_start_t rv; 
  rv.done = done; 
  rv.ready_for_word = 0; 
  /* Active state*/
  if(word_counter < num_words){ 
    /* Accept words */
    if(word_counter==0){
      bus_addr = addr; 
    }
    /* Try to start a u32 write*/
    if(word_in_valid){
      axi_write_t axi_write_info = axi_addr_data_to_write(bus_addr, word_in); 
      axi_shared_bus_t_write_start_logic_outputs_t write_start =  
        axi_shared_bus_t_write_start_logic(
          axi_write_info.req,
          axi_write_info.data, 
          1, 
          from_dev 
        ); 
      rv.to_dev = write_start.to_dev;
      if(write_start.done){ 
        /* Next word */
        rv.ready_for_word = 1;
        /* Last word?*/
        if(word_counter==(num_words-1)){ 
          done = 1; 
        }       
        word_counter += 1; 
        bus_addr += sizeof(uint32_t);
      } 
    }
  }else{ 
    /* IDLE/DONE state*/
    /* Ready for output clears done*/
    if(ready_for_outputs){ 
      done = 0; 
    } 
    /* Restart resets word counter*/
    if(~done){ 
      word_counter = 0; 
    } 
  } 
  return rv; 
}
typedef struct axi_shared_bus_write_start_t{
  uint1_t done;
  uint1_t ready_for_words;
  axi_shared_bus_t_write_host_to_dev_t to_dev;
}axi_shared_bus_write_start_t;
#define axi_shared_bus_write_start(NUM_WORDS)\
PPCAT(PPCAT(axi_shared_bus_,NUM_WORDS),words_write_start)
#define DECL_AXI_SHARED_BUS_WRITE_START(NUM_WORDS) \
axi_shared_bus_write_start_t axi_shared_bus_write_start(NUM_WORDS)(\
  uint1_t ready_for_outputs,\
  uint32_t addr,\
  uint32_t words_in[NUM_WORDS],\
  uint8_t num_words,\
  axi_shared_bus_t_write_dev_to_host_t from_dev\
){\
  /* Start N u32 writes using bus helper FSM */ \
  static uint8_t word_counter = 0xFF; \
  static uint32_t words[NUM_WORDS]; \
  static uint32_t bus_addr; \
  static uint1_t done; \
  axi_shared_bus_write_start_t rv; \
  rv.done = done; \
  rv.ready_for_words = 0; \
  /* Active state*/\
  if(word_counter < num_words){ \
    /* Accept words */\
    if(word_counter==0){\
      rv.ready_for_words = 1;\
      words = words_in;\
      bus_addr = addr; \
    }\
    /* Try to start a u32 write*/\
    axi_write_t axi_write_info = axi_addr_data_to_write(bus_addr, words[0]); \
    axi_shared_bus_t_write_start_logic_outputs_t write_start =  \
      axi_shared_bus_t_write_start_logic(\
        axi_write_info.req,\
        axi_write_info.data, \
        1, \
        from_dev \
      ); \
    rv.to_dev = write_start.to_dev;\
    if(write_start.done){ \
      /* Shift to next word u32 data into buffer[0]*/\
      ARRAY_SHIFT_DOWN(words, NUM_WORDS, 1)\
      /* Last word?*/\
      if(word_counter==(num_words-1)){ \
        done = 1; \
      }       \
      word_counter += 1; \
      bus_addr += sizeof(uint32_t);\
    } \
  }else{ \
    /* IDLE/DONE state*/\
    /* Ready for output clears done*/\
    if(ready_for_outputs){ \
      done = 0; \
    } \
    /* Restart resets word counter*/\
    if(~done){ \
      word_counter = 0; \
    } \
  } \
  return rv; \
}
// Finish
typedef struct axi_shared_bus_sized_write_finish_t{
  uint1_t ready_for_inputs;
  uint1_t done;
  uint1_t bus_resp_ready;
}axi_shared_bus_sized_write_finish_t;
axi_shared_bus_sized_write_finish_t axi_shared_bus_sized_write_finish(
  uint32_t num_words,
  uint1_t ready_for_outputs,
 axi_shared_bus_t_write_dev_to_host_t from_dev
){
  // Finish N u32 writes using bus helper FSM
  static uint32_t word_counter = ((uint32_t)1<<31);
  axi_shared_bus_sized_write_finish_t rv;
  rv.ready_for_inputs = 0;
  rv.done = 0;
  if(ready_for_outputs)
  {
    // Active state
    if(word_counter < num_words){
      // Try to finish a u32 write
      axi_shared_bus_t_write_finish_logic_outputs_t write_finish = 
        axi_shared_bus_t_write_finish_logic(
          1,
          from_dev
        );
      rv.bus_resp_ready = write_finish.resp_ready;
      // Move to next u32 when done
      if(write_finish.done){
        // Last word?
        if(word_counter==(num_words-1)){
          rv.done = 1;
        }      
        word_counter += 1;
      }
    }else{
      // IDLE state, wait for valid input
      rv.ready_for_inputs = 1;
      word_counter = 0;
    }
  }
  return rv;
}
typedef struct axi_shared_bus_write_stream_t
{
  axi_shared_bus_t_write_host_to_dev_t to_dev;
  // Outputs
  //  WR
  uint1_t wr_stream_ready;
  uint1_t wr_done;
}axi_shared_bus_write_stream_t;
axi_shared_bus_write_stream_t
axi_shared_bus_write_stream(
  axi_shared_bus_t_write_dev_to_host_t from_dev,
  // Inputs
  //  WR
  uint32_t wr_start_addr,
  uint32_t wr_num_words,
  uint32_t wr_stream_data,
  uint1_t wr_stream_valid
){
  axi_shared_bus_write_stream_t o;
  // Write start
  static uint1_t wr_start_done;
  if(~wr_start_done){
    axi_shared_bus_write_stream_start_t write_start = axi_shared_bus_write_stream_start(
      1, wr_start_addr, wr_num_words, wr_stream_data, wr_stream_valid, from_dev
    );
    o.to_dev = write_start.to_dev;
    o.wr_stream_ready = write_start.ready_for_word;
    if(write_start.done){
      wr_start_done = 1;
    }
  }
  // Write finish (no stream bus)
  axi_shared_bus_sized_write_finish_t write_finish = axi_shared_bus_sized_write_finish(
    wr_num_words, 1, from_dev
  );
  o.to_dev.resp_ready = write_finish.bus_resp_ready;
  if(write_finish.done){
    o.wr_done = 1;
  }
  if(o.wr_done){
    wr_start_done = 0;
  }
  return o;
}


// Logic for how to start and finish a read of some words from RAM
// Start
typedef struct axi_shared_bus_sized_read_start_t{
  uint1_t ready_for_inputs;
  uint1_t done;
  axi_shared_bus_t_read_req_t bus_req;
}axi_shared_bus_sized_read_start_t;
axi_shared_bus_sized_read_start_t axi_shared_bus_sized_read_start(
  uint32_t addr,
  uint32_t num_words,
  uint1_t ready_for_outputs,
  uint1_t bus_req_ready
){
  // Begin N u32 reads using bus helper FSM
  static uint32_t word_counter = ((uint32_t)1<<31);
  static uint32_t bus_addr;
  axi_shared_bus_sized_read_start_t rv;
  rv.ready_for_inputs = 0;
  rv.done = 0;
  if(ready_for_outputs)
  {
    // Active state
    if(word_counter < num_words){
      // Try to start a u32 read
      axi_read_req_t req = axi_addr_to_read(bus_addr);
      axi_shared_bus_t_read_start_logic_outputs_t read_start = 
        axi_shared_bus_t_read_start_logic(
          req,
          1,
          bus_req_ready
        );
      rv.bus_req = read_start.req;
      // Move to next u32 when done
      if(read_start.done){
        // Last word?
        if(word_counter==(num_words-1)){
          rv.done = 1;
        }      
        bus_addr += sizeof(uint32_t);
        word_counter += 1;
      }
    }else{
      // IDLE state, wait for valid input
      rv.ready_for_inputs = 1;
      //if(rd_valid){
        word_counter = 0;
        bus_addr = addr; //bus_base_addr + (rd_index * rd_size);
      //}
    }
  }
  return rv;
}
// Finish
typedef struct axi_shared_bus_read_stream_finish_t{
  uint32_t word;
  uint1_t word_valid;
  uint1_t done;
  uint1_t bus_data_ready;
}axi_shared_bus_read_stream_finish_t;
axi_shared_bus_read_stream_finish_t axi_shared_bus_read_stream_finish(
  uint32_t num_words,
  uint1_t ready_for_outputs,
  uint1_t word_output_ready,
  axi_shared_bus_t_read_data_t bus_read_data
){
  /* End N u32 reads using bus helper FSM */ 
  /* Assemble read responses into output data */ 
  static uint32_t word_counter = (uint32_t)1 << 31;
  static uint1_t done; 
  axi_shared_bus_read_stream_finish_t rv; 
  rv.done = done; 
  rv.bus_data_ready = 0; 
  /* Active state*/
  if(word_counter < num_words){ 
    /* Try to finish a u32 read*/
    axi_shared_bus_t_read_finish_logic_outputs_t read_finish =  
      axi_shared_bus_t_read_finish_logic( 
        word_output_ready, 
        bus_read_data 
      ); 
    rv.bus_data_ready = read_finish.data_ready; 
    if(read_finish.done){ 
      /* Output u32 data */
      uint32_t rd_data = axi_read_to_data(read_finish.data); 
      rv.word = rd_data;
      rv.word_valid = 1;
      /* Last word?*/
      if(word_counter==(num_words-1)){ 
        done = 1; 
      }       
      word_counter += 1; 
    } 
  }else{ 
    /* IDLE/DONE state*/
    /* Ready for output clears done*/
    if(ready_for_outputs){ 
      done = 0; 
    } 
    /* Restart resets word counter*/
    if(~done){ 
      word_counter = 0; 
    } 
  } 
  return rv;
}
typedef struct axi_shared_bus_read_stream_t
{
  axi_shared_bus_t_read_host_to_dev_t to_dev;
  // Outputs
  //  RD
  uint32_t rd_stream_data;
  uint1_t rd_stream_valid;
  uint1_t rd_done;
}axi_shared_bus_read_stream_t;
axi_shared_bus_read_stream_t
axi_shared_bus_read_stream(
  axi_shared_bus_t_read_dev_to_host_t from_dev,
  // Inputs
  //  RD
  uint32_t rd_start_addr,
  uint32_t rd_num_words,
  uint1_t rd_stream_ready
){
  axi_shared_bus_read_stream_t o;
  // Read start (no stream bus)
  static uint1_t rd_start_done;
  if(~rd_start_done){
    axi_shared_bus_sized_read_start_t read_start = axi_shared_bus_sized_read_start(
      rd_start_addr, rd_num_words, 1, from_dev.req_ready
    );
    o.to_dev.req = read_start.bus_req;
    if(read_start.done){
      rd_start_done = 1;
    }
  }
  // Read finish
  axi_shared_bus_read_stream_finish_t read_finish = axi_shared_bus_read_stream_finish(
    rd_num_words, 1, rd_stream_ready, from_dev.data
  );
  o.to_dev.data_ready = read_finish.bus_data_ready;
  o.rd_stream_data = read_finish.word;
  o.rd_stream_valid = read_finish.word_valid;
  if(read_finish.done){
    o.rd_done = 1;
  }
  if(o.rd_done){
    rd_start_done = 0;
  }
  return o;
}
#define axi_shared_bus_read_finish_t(NUM_WORDS)\
PPCAT(PPCAT(axi_shared_bus_,NUM_WORDS),words_read_finish_t)
#define axi_shared_bus_read_finish(NUM_WORDS)\
PPCAT(PPCAT(axi_shared_bus_,NUM_WORDS),words_read_finish)
#define DECL_AXI_SHARED_BUS_READ_FINISH(NUM_WORDS) \
typedef struct axi_shared_bus_read_finish_t(NUM_WORDS){\
  uint32_t words[NUM_WORDS];\
  uint1_t done;\
  uint1_t bus_data_ready;\
}axi_shared_bus_read_finish_t(NUM_WORDS);\
axi_shared_bus_read_finish_t(NUM_WORDS) axi_shared_bus_read_finish(NUM_WORDS)(\
  uint8_t num_words,\
  uint1_t ready_for_outputs,\
  axi_shared_bus_t_read_data_t bus_read_data\
){\
  /* End N u32 reads using bus helper FSM */ \
  /* Assemble read responses into output data */ \
  static uint8_t word_counter = 0xFF; \
  static uint32_t words[NUM_WORDS]; \
  static uint1_t done; \
  axi_shared_bus_read_finish_t(NUM_WORDS) rv; \
  rv.done = done; \
  rv.words = words; \
  rv.bus_data_ready = 0; \
  /* Active state*/\
  if(word_counter < num_words){ \
    /* Try to finish a u32 read*/\
    axi_shared_bus_t_read_finish_logic_outputs_t read_finish =  \
      axi_shared_bus_t_read_finish_logic( \
        1, \
        bus_read_data \
      ); \
    rv.bus_data_ready = read_finish.data_ready; \
    if(read_finish.done){ \
      /* Put u32 data into byte buffer*/\
      uint32_t rd_data = axi_read_to_data(read_finish.data); \
      ARRAY_1SHIFT_INTO_TOP(words, NUM_WORDS, rd_data) \
      /* Last word?*/\
      if(word_counter==(num_words-1)){ \
        /* Shift for if user asked for less words than buffer size*/\
        uint32_t req_words;\
        for(req_words = 1; req_words < NUM_WORDS; req_words+=1)\
        {\
          if(num_words==req_words){\
            ARRAY_SHIFT_DOWN(words, NUM_WORDS, (NUM_WORDS-req_words))\
          }\
        }\
        done = 1; \
      }       \
      word_counter += 1; \
    } \
  }else{ \
    /* IDLE/DONE state*/\
    /* Ready for output clears done*/\
    if(ready_for_outputs){ \
      done = 0; \
    } \
    /* Restart resets word counter*/\
    if(~done){ \
      word_counter = 0; \
    } \
  } \
  return rv; \
}

// Finish read of some words assembled into a struct type TODO REUSE 32b word version above somehow?
#if 0
#define DECL_AXI_SHARED_BUS_TYPE_READ_FINISH(type) \
typedef struct PPCAT(type,_axi_shared_bus_read_finish_t){\
  type data;\
  uint1_t done;\
  uint1_t bus_data_ready;\
}PPCAT(type,_axi_shared_bus_read_finish_t);\
PPCAT(type,_axi_shared_bus_read_finish_t) PPCAT(type,_axi_shared_bus_read_finish)(\
  uint1_t ready_for_outputs,\
  axi_shared_bus_t_read_data_t bus_read_data\
){\
  /* End N u32 reads using bus helper FSM */ \
  /* Assemble read responses into output data */ \
  static uint8_t word_counter; \
  static uint8_t bytes[sizeof(type)]; \
  static uint1_t done; \
  uint8_t NUM_WORDS = sizeof(type) / sizeof(uint32_t); \
  PPCAT(type,_axi_shared_bus_read_finish_t) rv; \
  rv.done = done; \
  rv.data = PPCAT(bytes_to_,type)(bytes); \
  rv.bus_data_ready = 0; \
  /* Active state*/\
  if(word_counter < NUM_WORDS){ \
    /* Try to finish a u32 read*/\
    axi_shared_bus_t_read_finish_logic_outputs_t read_finish =  \
      axi_shared_bus_t_read_finish_logic( \
        1, \
        bus_read_data \
      ); \
    rv.bus_data_ready = read_finish.data_ready; \
    if(read_finish.done){ \
      /* Put u32 data into byte buffer*/\
      uint32_t rd_data = axi_read_to_data(read_finish.data); \
      uint8_t rd_bytes[sizeof(uint32_t)]; \
      uint32_t i; \
      for(i = 0; i < sizeof(uint32_t); i+=1) \
      { \
        rd_bytes[i] = rd_data >> (i*8); \
      } \
      ARRAY_SHIFT_INTO_TOP(bytes, sizeof(type), rd_bytes, sizeof(uint32_t)) \
      /* Last word?*/\
      if(word_counter==(NUM_WORDS-1)){ \
        done = 1; \
      }       \
      word_counter += 1; \
    } \
  }else{ \
    /* IDLE/DONE state*/\
    /* Ready for output clears done*/\
    if(ready_for_outputs){ \
      done = 0; \
    } \
    /* Restart resets word counter*/\
    if(~done){ \
      word_counter = 0; \
    } \
  } \
  return rv; \
}
#endif


// TODO use maybe use new pieces axi_shared_bus_write_stream and axi_shared_bus_read_stream?
typedef struct axi_shared_bus_to_stream_source_sink_t
{
  axi_shared_bus_t_host_to_dev_t to_dev;
  // Outputs
  //  WR
  uint1_t wr_stream_ready;
  uint1_t wr_done;
  //  RD
  uint32_t rd_stream_data;
  uint1_t rd_stream_valid;
  uint1_t rd_done;
}axi_shared_bus_to_stream_source_sink_t;
axi_shared_bus_to_stream_source_sink_t
axi_shared_bus_to_stream_source_sink(
  axi_shared_bus_t_dev_to_host_t from_dev,
  // Inputs
  //  WR
  uint32_t wr_start_addr,
  uint32_t wr_num_words,
  uint1_t wr_req_valid,
  uint32_t wr_stream_data,
  uint1_t wr_stream_valid,
  //  RD
  uint32_t rd_start_addr,
  uint32_t rd_num_words,
  uint1_t rd_req_valid,
  uint1_t rd_stream_ready
){
  axi_shared_bus_to_stream_source_sink_t o;

  // Shared bus library FSMs are written as to auto restart, done is a pulse not stable
  // (meant for composing with other FSMs, not CPU control)
  // Need to manually wrap in sticky reg and use to get further execution

  // Read start (no stream bus)
  static uint1_t rd_start_done;
  if(~rd_start_done & rd_req_valid){
    axi_shared_bus_sized_read_start_t read_start = axi_shared_bus_sized_read_start(
      rd_start_addr, rd_num_words, 1, from_dev.read.req_ready
    );
    o.to_dev.read.req = read_start.bus_req;
    if(read_start.done){
      rd_start_done = 1;
    }
  }
  if(~rd_req_valid){
    rd_start_done = 0;
  }
  // Read finish
  static uint1_t rd_finish_done;
  o.rd_done = rd_finish_done;
  if(~rd_finish_done & rd_req_valid){
    axi_shared_bus_read_stream_finish_t read_finish = axi_shared_bus_read_stream_finish(
      rd_num_words, 1, rd_stream_ready, from_dev.read.data
    );
    o.to_dev.read.data_ready = read_finish.bus_data_ready;
    o.rd_stream_data = read_finish.word;
    o.rd_stream_valid = read_finish.word_valid;
    if(read_finish.done){
      rd_finish_done = 1;
    }
  }
  if(~rd_req_valid){
    rd_finish_done = 0;
  }

  // Write start
  static uint1_t wr_start_done;
  if(~wr_start_done & wr_req_valid){
    axi_shared_bus_write_stream_start_t write_start = axi_shared_bus_write_stream_start(
      1, wr_start_addr, wr_num_words, wr_stream_data, wr_stream_valid, from_dev.write
    );
    o.to_dev.write = write_start.to_dev;
    o.wr_stream_ready = write_start.ready_for_word;
    if(write_start.done){
      wr_start_done = 1;
    }
  }
  if(~wr_req_valid){
    wr_start_done = 0;
  }
  // Write finish (no stream bus)
  static uint1_t wr_finish_done;
  o.wr_done = wr_finish_done;
  if(~wr_finish_done & wr_req_valid){
    axi_shared_bus_sized_write_finish_t write_finish = axi_shared_bus_sized_write_finish(
      wr_num_words, 1, from_dev.write
    );
    o.to_dev.write.resp_ready = write_finish.bus_resp_ready;
    if(write_finish.done){
      wr_finish_done = 1;
    }
  }
  if(~wr_req_valid){
    wr_finish_done = 0;
  }

  return o;
}


typedef struct axi_descriptor_t
{
  uint32_t addr;
  uint32_t num_words;
}axi_descriptor_t;
DECL_STREAM_TYPE(axi_descriptor_t)
typedef enum u32_to_from_axi_state_t{
  DESCRIPTOR_IN, // What address to write/read incoming/outgoing stream words to/from?
  DO_TRANSFER, // Do the AXI writes/reads of stream words
  DESCRIPTOR_OUT // Output what memory space was just used
}u32_to_from_axi_state_t;

// Data mover like module for stream input to AXI writes
// Outputs are mainly stream of descriptors written to
typedef struct axi_stream_to_writes_t{
  stream(axi_descriptor_t) descriptors_out_stream;
  axi_shared_bus_t_write_host_to_dev_t to_dev; // AXI signals to device
  uint1_t ready_for_descriptors_in;
  uint1_t ready_for_data_stream;
}axi_stream_to_writes_t;
axi_stream_to_writes_t u32_stream_to_axi_writes(
  // Inputs are mainly stream of descriptors to write and stream of data
  stream(axi_descriptor_t) descriptors_in_stream,
  stream(uint32_t) data_stream,
  uint1_t ready_for_descriptors_out,
  axi_shared_bus_t_write_dev_to_host_t from_dev // AXI signals from device
){
  // State registers
  static u32_to_from_axi_state_t state;
  static axi_descriptor_t descriptor;
  
  // Output 'o' default zeros
  axi_stream_to_writes_t o;
  
  // FSM:
  if(state==DESCRIPTOR_IN){
    // Ready for next desciptor now
    o.ready_for_descriptors_in = 1;
    // Wait for valid descriptor
    if(descriptors_in_stream.valid){
      // Save copy of valid descriptor data
      descriptor = descriptors_in_stream.data;
      // And begin transfer next
      state = DO_TRANSFER;
    } 
  }else if(state==DO_TRANSFER){
    // Use helper fsm to write stream until its done
    axi_shared_bus_write_stream_t bus_xfer = axi_shared_bus_write_stream(
      from_dev,
      descriptor.addr,
      descriptor.num_words,
      data_stream.data,
      data_stream.valid
    );
    o.to_dev = bus_xfer.to_dev;
    o.ready_for_data_stream = bus_xfer.wr_stream_ready;
    if(bus_xfer.wr_done){
      state = DESCRIPTOR_OUT;
    }
  }else/*if(state==DESCRIPTOR_OUT)*/{
    // Have valid descriptor to output
    o.descriptors_out_stream.data = descriptor;
    o.descriptors_out_stream.valid = 1;
    // Wait for it to be ready to be accepted
    if(ready_for_descriptors_out){
      // Start over
      state = DESCRIPTOR_IN;
    }
  }

  return o;
}


// Data mover like module for AXI reads to stream output
// Outputs are mainly stream of descriptors read from and stream of data
typedef struct axi_reads_to_u32_stream_t{
  stream(axi_descriptor_t) descriptors_out_stream;
  stream(uint32_t) data_stream;
  axi_shared_bus_t_read_host_to_dev_t to_dev; // AXI signals to device
  uint1_t ready_for_descriptors_in;
}axi_reads_to_u32_stream_t;
axi_reads_to_u32_stream_t axi_reads_to_u32_stream(
  // Inputs are mainly stream of descriptors to read from
  stream(axi_descriptor_t) descriptors_in_stream,
  uint1_t ready_for_descriptors_out,
  uint1_t ready_for_data_stream,
  axi_shared_bus_t_read_dev_to_host_t from_dev // AXI signals from device
){
  // State registers
  static u32_to_from_axi_state_t state;
  static axi_descriptor_t descriptor;
  
  // Output 'o' default zeros
  axi_reads_to_u32_stream_t o;
  
  // FSM:
  if(state==DESCRIPTOR_IN){
    // Ready for next desciptor now
    o.ready_for_descriptors_in = 1;
    // Wait for valid descriptor
    if(descriptors_in_stream.valid){
      // Save copy of valid descriptor data
      descriptor = descriptors_in_stream.data;
      // And begin transfer next
      state = DO_TRANSFER;
    } 
  }else if(state==DO_TRANSFER){
    // Use helper fsm to read stream until its done
    axi_shared_bus_read_stream_t bus_xfer = axi_shared_bus_read_stream(
      from_dev,
      descriptor.addr,
      descriptor.num_words,
      ready_for_data_stream
    );
    o.to_dev = bus_xfer.to_dev;
    o.data_stream.data = bus_xfer.rd_stream_data;
    o.data_stream.valid = bus_xfer.rd_stream_valid;
    if(bus_xfer.rd_done){
      state = DESCRIPTOR_OUT;
    }
  }else/*if(state==DESCRIPTOR_OUT)*/{
    // Have valid descriptor to output
    o.descriptors_out_stream.data = descriptor;
    o.descriptors_out_stream.valid = 1;
    // Wait for it to be ready to be accepted
    if(ready_for_descriptors_out){
      // Start over
      state = DESCRIPTOR_IN;
    }
  }

  return o;
}

