#pragma PART "xc7a100tcsg324-1" // FMAX ~235 MHz
//#pragma PART "LFE5U-85F-6BG381C" // FMAX ~85 MHz (not inferring RAM right?)
#define CLOCK_MHZ 235 // Limited by ctrl_fsm stateful function
#include "uintN_t.h"
#include "intN_t.h"
#include "arrays.h"
#include "global_func_inst.h"
#include "ram.h"

// https://adventofcode.com/2025/day/5

#define N_RANGES_PER_CYCLE 2
#define N_IDS_PER_CYCLE 3
#define sum_is_fresh_flags uint1_array_sum3
#define uint_t uint50_t // id type
#define N_TEST_RANGES 4 // should be muliple of ranges per cycle for now
#define RAM_DEPTH 128 // min (N_TEST_RANGES/N_RANGES_PER_CYCLE)
#define N_TEST_IDS 6 // should be multiple of ids per cycle for now

typedef struct range_t{
  uint_t lo;
  uint_t hi;
}range_t;

// Inputs to dataflow

// Global wires connect this process into ctrl FSM
range_t input_ranges[N_RANGES_PER_CYCLE];
uint1_t last_input_ranges;
uint1_t input_ranges_valid;
uint1_t ready_for_input_ranges;
MAIN_MHZ(input_ranges_process, CLOCK_MHZ) // Other MAIN funcs absorb this clock domain
void input_ranges_process()
{
  // Hard code inputs for sim for now...
  static range_t inputs[N_TEST_RANGES] = {
    {3,5},
    {10,14},
    {16,20},
    {12,18}
  };
  static uint32_t test_counter;
  static uint1_t test_running = 1;
  uint1_t is_last_cycle = test_counter >= (N_TEST_RANGES-N_RANGES_PER_CYCLE);
  ARRAY_COPY(input_ranges, inputs, N_RANGES_PER_CYCLE) 
  last_input_ranges = is_last_cycle;
  input_ranges_valid = test_running;
  if(input_ranges_valid & ready_for_input_ranges){
    for(uint32_t i = 0; i<N_RANGES_PER_CYCLE; i+=1){
      printf("Input range[%d] = %d,%d\n", test_counter+i, input_ranges[i].lo, input_ranges[i].hi);
    }
    ARRAY_SHIFT_DOWN(inputs, N_TEST_RANGES, N_RANGES_PER_CYCLE)
    test_counter += N_RANGES_PER_CYCLE;
    test_running = ~is_last_cycle;
  }
}

// Global wires connect this process into ctrl FSM
uint_t input_ids[N_IDS_PER_CYCLE];
uint1_t last_input_ids;
uint1_t input_ids_valid;
uint1_t ready_for_input_ids;
MAIN_MHZ(input_ids_process, CLOCK_MHZ) // Other MAIN funcs absorb this clock domain
void input_ids_process()
{
  // Hard code inputs for sim for now...
  static uint_t inputs[N_TEST_IDS] = {
    1,
    5,
    8,
    11,
    17,
    32
  };
  static uint32_t test_counter;
  static uint1_t test_running = 1;
  uint1_t is_last_cycle = test_counter >= (N_TEST_IDS-N_IDS_PER_CYCLE);
  ARRAY_COPY(input_ids, inputs, N_IDS_PER_CYCLE) 
  last_input_ids = is_last_cycle;
  input_ids_valid = test_running;
  if(input_ids_valid & ready_for_input_ids){
    for(uint32_t i = 0; i<N_IDS_PER_CYCLE; i+=1){
      printf("Input id[%d] = %d\n", test_counter+i, input_ids[i]);
    }
    ARRAY_SHIFT_DOWN(inputs, N_TEST_IDS, N_IDS_PER_CYCLE)
    test_counter += N_IDS_PER_CYCLE;
    test_running = ~is_last_cycle;
  }
}

// Freshness function
typedef struct fresh_req_t{
  uint_t ids[N_IDS_PER_CYCLE];
  range_t ranges[N_RANGES_PER_CYCLE];
  uint1_t is_last_ranges;
}fresh_req_t;
typedef struct fresh_result_t{
  uint1_t id_is_fresh[N_IDS_PER_CYCLE];
  uint1_t is_last_ranges;
}fresh_result_t;
fresh_result_t is_fresh(fresh_req_t req){
  fresh_result_t rv;
  rv.is_last_ranges = req.is_last_ranges;
  // For each ID check if is any of the ranges
  for(uint32_t i = 0; i < N_IDS_PER_CYCLE; i+=1)
  {
    for(uint32_t j = 0; j < N_RANGES_PER_CYCLE; j+=1)
    {
      uint1_t in_range = 
        (req.ids[i] >= req.ranges[j].lo) &
        (req.ids[i] <= req.ranges[j].hi);
      rv.id_is_fresh[i] |= in_range;
    }
    if(rv.id_is_fresh[i]) printf("ID %d is fresh\n", req.ids[i]);
  }
  return rv;
}
// is_fresh_pipeline : fresh_result_t is_fresh(fresh_req_t)
//  instance of pipeline without handshaking but does include stream valid bit
//  delcares global variable wires as ports to connect to, named like is_fresh_pipeline _in/_out...
GLOBAL_PIPELINE_INST_W_VALID_ID(is_fresh_pipeline, fresh_result_t, is_fresh, fresh_req_t)


// Define a type of RAM that holds groups of N ranges
// Dual port, one write port, one read range, one cycle latency (BRAM)
typedef struct n_ranges_t{
  range_t ranges[N_RANGES_PER_CYCLE];
}n_ranges_t;
DECL_STREAM_RAM_DP_W_R_1(n_ranges_t, n_ranges_ram_func, RAM_DEPTH, "(others => (others => (others => (others => (others => '0')))))")


// FSM that iterates over all ranges in groups of N ranges at a time
typedef enum state_t{
  // Stream input ranges into RAM, recording runtime variable number of ranges
  WRITE_INPUTS_INTO_RAM,
  // Register next group of IDs to check
  NEXT_IDS_INPUT,
  // One iteration of streaming ranges from RAM
  // and IDs through is fresh evaluating pipeline
  READ_FROM_RAM_INTO_PIPELINE
}state_t;
MAIN_MHZ(ctrl_fsm, CLOCK_MHZ)
void ctrl_fsm(){
  // State regs
  static state_t state;
  static uint8_t total_range_groups;
  static uint8_t reqs_counter;
  static uint8_t resp_counter;
  static uint_t curr_ids[N_IDS_PER_CYCLE];
  static uint1_t is_last_ids;

  // Instance of RAM holding groups of N ranges with valid ready handshaking interface
  // delcares local variable wires as ports to connect to, named like n_ranges_ram _rd_addr_in/_wr_data_in...
  RAM_DP_W_R_1_STREAM(n_ranges_t, n_ranges_ram_func, n_ranges_ram)

  // Default not ready for inputs
  ready_for_input_ranges = 0;
  ready_for_input_ids = 0;
  // Default not writing to RAM
  n_ranges_ram_wr_in_valid = 0;
  // Default write data values into RAM
  n_ranges_ram_wr_addr_in = reqs_counter;
  n_ranges_ram_wr_data_in.ranges = input_ranges;
  // Default drain write responses from RAM, not waiting for them
  n_ranges_ram_wr_out_ready = 1;
  // Default not reading from RAM
  n_ranges_ram_rd_in_valid = 0;
  // Default read addr value into RAM
  n_ranges_ram_rd_addr_in = reqs_counter;
  // Default not ready for read resp from RAM
  n_ranges_ram_rd_out_ready = 0;
  // Default no data into pipeline
  is_fresh_pipeline_in_valid = 0;
  // Default data values into pipeline
  is_fresh_pipeline_in.ids = curr_ids;
  is_fresh_pipeline_in.ranges = n_ranges_ram_rd_data_out.ranges;
  is_fresh_pipeline_in.is_last_ranges = resp_counter==(total_range_groups-1);

  if(state==WRITE_INPUTS_INTO_RAM){
    // Inputs stream into RAM
    n_ranges_ram_wr_in_valid = input_ranges_valid;
    ready_for_input_ranges = n_ranges_ram_wr_in_ready;
    if(n_ranges_ram_wr_in_valid & n_ranges_ram_wr_in_ready){
      reqs_counter += 1;
      if(last_input_ranges){
        total_range_groups = reqs_counter;
        state = NEXT_IDS_INPUT;
      }
    }
  }else if(state==NEXT_IDS_INPUT){
    ready_for_input_ids = 1;
    if(input_ids_valid & ready_for_input_ids){
      curr_ids = input_ids;
      state = READ_FROM_RAM_INTO_PIPELINE;
      reqs_counter = 0;
      resp_counter = 0;
    }  
  }else /*if(state==READ_FROM_RAM_INTO_PIPELINE)*/{
    // Iterate over start -> end ranges groups
    // starting read requests with address
    if(reqs_counter < total_range_groups){
      n_ranges_ram_rd_in_valid = 1;
      if(n_ranges_ram_rd_in_valid & n_ranges_ram_rd_in_ready){
        reqs_counter += 1;
      }
    }
    // Finish read with response data into pipeline
    if(resp_counter < total_range_groups){
      n_ranges_ram_rd_out_ready = 1; // is_fresh_pipeline_in_ready
      // Send corner range and 
      // other group of N ranges from RAM into area maximize function
      is_fresh_pipeline_in_valid = n_ranges_ram_rd_out_valid;
      if(is_fresh_pipeline_in_valid /*& is_fresh_pipeline_in_ready*/){
        for(uint32_t i = 0; i<N_RANGES_PER_CYCLE; i+=1){
          printf("Checking range: %d -> %d\n",
            n_ranges_ram_rd_data_out.ranges[i].lo, n_ranges_ram_rd_data_out.ranges[i].hi);
        }
        for(uint32_t i = 0; i<N_IDS_PER_CYCLE; i+=1){
          printf("Checking id: %d\n", curr_ids[i]);
        }
        resp_counter += 1;
        if(is_fresh_pipeline_in.is_last_ranges){
          // Got final response for this iteration, reset for next
          state = NEXT_IDS_INPUT;
        }
      }
    }
  }
}


// Accum the freshness flags coming out of pipeline
#pragma MAIN get_fresh_ids_count
uint32_t get_fresh_ids_count(){
  static uint16_t fresh_count;
  static uint1_t id_is_fresh[N_IDS_PER_CYCLE];
  static uint16_t increment_reg;
  fresh_count += increment_reg;
  increment_reg = 0;
  if(is_fresh_pipeline_out_valid){
    for(uint32_t i = 0; i < N_IDS_PER_CYCLE; i+=1){
      id_is_fresh[i] |= is_fresh_pipeline_out.id_is_fresh[i];
    }
    if(is_fresh_pipeline_out.is_last_ranges){
      increment_reg = sum_is_fresh_flags(id_is_fresh);
      printf("Found %d fresh IDs...\n", increment_reg);
      uint1_t NULL_FLAGS[N_IDS_PER_CYCLE];
      id_is_fresh = NULL_FLAGS;
    }
  }
  // Return so doesnt synthesize away
  printf("Total fresh IDs: %d\n", fresh_count);
  return fresh_count;
}