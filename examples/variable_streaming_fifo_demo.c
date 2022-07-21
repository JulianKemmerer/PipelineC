#pragma PART "xc7a35ticsg324"

#include "uintN_t.h"
#include "intN_t.h"

// Hacky manual ~'parameterized types'
#define MAX_WORDS 128
#define IN_DATA_WIDTH 16
#define IN_DATA_WORD_WIDTH 8
#define word_in_t uint8_t
#define IN_DATA_WORDS (IN_DATA_WIDTH / IN_DATA_WORD_WIDTH) // =2 TODO $min
#define countones uint1_array_sum2 // Built in func, count up to IN_DATA_WORDS ones
#define SR_DEPTH (MAX_WORDS * IN_DATA_WORDS) // =256
//#define SR_ADDR_WIDTH = 8 //TODO $clog2(SR_DEPTH);
#define sr_count_t uint9_t // For holding 0->256
#define OUT_DATA_WIDTH 64
#define word_out_t uint64_t
#define out_array_to_word uint1_array64_le // Built in func, converts 64 element bit array to a u64
//define OUT_DATA_WIDTH_LOG2 //TODO $clog2(OUT_DATA_WIDTH);
#define out_data_count_t uint7_t // For holding 0->64

// Helper function to read output word from variable positon in shift reg
// TODO optimize, is roughly ~ 64 instances of 256->1 muxes... seems big?
// Would normally be a RAM in a FIFO situation I think?
word_out_t read_out_word_from_sr(uint1_t sr[SR_DEPTH], sr_count_t pos)
{
  uint1_t out_data_array[OUT_DATA_WIDTH];
  uint32_t out_i;
  // OUT_DATA_WIDTH=64 unrolled loop iterations
  for(out_i=0; out_i<OUT_DATA_WIDTH; out_i+=1) 
  {
    // Each instantiating a SR_DEPTH=256 -> 1 mux with 'pos + out_i' as select
    out_data_array[out_i] = sr[pos + out_i];
  }  
  return out_array_to_word(out_data_array);
}

// Outputs (could do another struct for inputs too if you like)
typedef struct variable_streaming_fifo_t
{
  // Flow interface in, flow control
  uint1_t flow_in_ready;
  // Flow interface out
  uint1_t flow_out_valid;
  uint1_t flow_out_last;
  word_out_t flow_out_data;
  uint1_t flow_out_data_bitmask[OUT_DATA_WIDTH];
  // FIFO control interface
  uint1_t full;
  uint1_t almost_full;
  uint1_t empty;
}variable_streaming_fifo_t;

// The module definition, marked as top level MAIN for test
#pragma MAIN variable_streaming_fifo
variable_streaming_fifo_t variable_streaming_fifo(
  uint1_t reset,
  // Flow interface in
  uint1_t flow_in_valid,
  uint1_t flow_in_last,
  word_in_t flow_in_data[IN_DATA_WORDS],
  uint1_t flow_in_data_word_valid[IN_DATA_WORDS],
  // Flow interface out, flow control
  uint1_t flow_out_ready,
  // FIFO control interface
  out_data_count_t bits_requested,
  uint1_t bits_requested_valid
)
{
  // Static registers
  static sr_count_t bits_available;
  static sr_count_t sr_head;
  static sr_count_t sr_tail;
  static uint1_t sr[SR_DEPTH];

  // Comb logic
  uint1_t full = (bits_available==SR_DEPTH);
  uint1_t almost_full = (bits_available >= (SR_DEPTH - IN_DATA_WIDTH*2));
  uint1_t empty = (bits_available==0);
  variable_streaming_fifo_t o; // Output port values
  o.flow_in_ready = flow_out_ready & !full;
  o.flow_out_valid = (bits_requested_valid & (bits_available > bits_requested));
  sr_count_t sr_head_next =
    (flow_in_valid & o.flow_in_ready) ? sr_head + countones(flow_in_data_word_valid) : sr_head;
  sr_count_t sr_tail_next =
    (flow_out_ready & o.flow_out_valid) ? sr_tail + bits_requested : sr_tail;
  o.flow_out_last = 1;
  // flow_out_data = sr[sr_tail+OUT_DATA_WIDTH:sr_tail]; via helper function
  o.flow_out_data = read_out_word_from_sr(sr, sr_tail);
  uint32_t i;
  for(i=0; i<OUT_DATA_WIDTH; i+=1) 
  {
    if(i < bits_requested)// Limit loop range
    {
      o.flow_out_data_bitmask[i] = (i <= bits_requested);
    }
  }

  // Assigning next values to registers (w/ some more comb logic)
  bits_available = sr_head_next - sr_tail_next;
  sr_head = sr_head_next;
  sr_tail = sr_tail_next;  

  // Reset some static registers
  if(reset)
  {
    sr_head = 0;
    sr_tail = 0;
  }

  return o;
}
