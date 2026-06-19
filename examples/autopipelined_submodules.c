
// "Autopipelined submodule instances"
// MAYBE just need way to #pragma PIPELINE a function call in otherwise reg and feedback state machine etc
// PYpelione Bonus? allow that pragma to produce local var constant place holder for autopipeline depth

/*implement new pragma tagging instance names with autopipeline
Just need new rules for if can slice into submodule instance
  by default traverse down through all submodules?
  not just dependent on func def, is dependent on context w/ parent regs/feedback
    and if submodule has been marked as autopipeline
    BODY_CAN_BE_SLICED vs CAN_BE_SLICED, slice down hier etc see all uses
    probably want helper for if func def has autopipeline in hier check

then make sure dont render actual latency of autopipeline in reg/feedback func


*/

#pragma PART "LFE5U-85F-6BG381C" 

#include "intN_t.h"
#include "uintN_t.h"
#include "stream/stream.h"
#include "fifo.h"
#define data_t uint8_t
DECL_STREAM_TYPE(data_t)
#define MAX_IN_FLIGHT 16

/*Define FIFO to use for handshake test_fifo*/
FIFO_FWFT(test_fifo, data_t, MAX_IN_FLIGHT)


// Test pipeline func
stream(data_t) test_pipeline(stream(data_t) x){
  stream(data_t) rv = x;
  rv.data = x.data / ~x.data;
  return rv;
}


typedef struct valid_ready_pipeline_test_t{
  uint1_t pipeline_in_ready;
  stream(data_t) pipeline_out;
}valid_ready_pipeline_test_t;
valid_ready_pipeline_test_t valid_ready_pipeline_test(
  stream(data_t) pipeline_in,
  uint1_t pipeline_out_ready
){
  valid_ready_pipeline_test_t o;
  /* Keep count of how many words in FIFO*/
  static uint16_t fifo_count;
  /* Signal ready for input if room in fifo*/
  static uint1_t in_ready_reg;
  o.pipeline_in_ready = in_ready_reg;
  /* Logic for input side of pipeline without handshake*/
  /* Gate valid with ready signal*/
  stream(data_t) pipeline_no_handshake_in;
  pipeline_no_handshake_in.valid = pipeline_in.valid & o.pipeline_in_ready;
  pipeline_no_handshake_in.data = pipeline_in.data;
  // The new autopipelined submodule
  stream(data_t) pipeline_no_handshake_out;
  #pragma AUTOPIPELINE //<optional int depth>
  pipeline_no_handshake_out = test_pipeline(pipeline_no_handshake_in);
  /* Free flow of data out of pipeline into fifo*/
  uint1_t fifo_wr_en = pipeline_no_handshake_out.valid;
  data_t fifo_wr_data = pipeline_no_handshake_out.data;
  /* Dont need to check for not full/overflow since count used for ready*/
  /* Read side of FIFO connected to top level outputs*/
  uint1_t fifo_rd_en = pipeline_out_ready;
  /* The FIFO instance connected to outputs*/
  test_fifo_t fifo_o = test_fifo(fifo_rd_en, fifo_wr_data, fifo_wr_en);
  o.pipeline_out.valid = fifo_o.data_out_valid;
  o.pipeline_out.data = fifo_o.data_out;
  /* Count input writes and output reads from fifo*/
  uint1_t fifo_count_plus_1 = pipeline_in.valid & o.pipeline_in_ready;
  uint1_t fifo_count_minus_1 = o.pipeline_out.valid & pipeline_out_ready;
  in_ready_reg = fifo_count < MAX_IN_FLIGHT;
  if(fifo_count_plus_1 & ~fifo_count_minus_1){
    in_ready_reg = (fifo_count < (MAX_IN_FLIGHT-1));
    fifo_count += 1;
  }else if(fifo_count_minus_1 & ~fifo_count_plus_1){
    in_ready_reg = 1;
    fifo_count -= 1;
  }
  return o;
}

#pragma MAIN_MHZ main 150.0
valid_ready_pipeline_test_t main(
  stream(data_t) pipeline_in,
  uint1_t pipeline_out_ready
){
  static uint1_t test_reg;
  valid_ready_pipeline_test_t rv = valid_ready_pipeline_test(
    pipeline_in,
    pipeline_out_ready
  );
  test_reg = test_reg ^ rv.pipeline_in_ready;
  return rv;
}


/*
#pragma MAIN_MHZ main_test_no_pipeline 150.0
stream(data_t) main_test_no_pipeline(stream(data_t) x){
  static stream(data_t) test_reg;
  stream(data_t) rv = test_reg;
  test_reg = test_pipeline(x);
  return rv;
}
*/