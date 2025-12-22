#pragma PART "xc7a100tcsg324-1" // FMAX ~150 MHz
//#pragma PART "LFE5U-85F-6BG381C" // FMAX ~80 MHz
#define CLOCK_MHZ 80 // Limited by ctrl_fsm stateful function
#include "uintN_t.h"
#include "intN_t.h"
#include "arrays.h"
#include "global_func_inst.h"
#include "ram.h"

// https://adventofcode.com/2025/day/9

#define uint_t uint17_t // x,y value position types
#define int_t int18_t
#define abs int18_abs
#define area_t uint34_t // type for resulting area
#define N_POINTS_PER_CYCLE 4 // Scale resources+bandwidth, min 2
#define group_len_t uint3_t // log2 points per cycle group size + 1
#define N_TEST_POINTS 8 // total should be muliple of points per cycle for now
#define RAM_DEPTH 128 // min (N_TEST_POINTS/N_POINTS_PER_CYCLE)
#define group_counter_t uint8_t // min log2 (N_TEST_POINTS/N_POINTS_PER_CYCLE) + 1

typedef struct point_t{
  uint_t x;
  uint_t y;
}point_t;
typedef struct n_points_t{
  point_t points[N_POINTS_PER_CYCLE];
}n_points_t;

// Inputs to dataflow
// Global wires connect this process into ctrl FSM
n_points_t input_points;
uint1_t last_input_points;
uint1_t input_points_valid;
uint1_t ready_for_input_points;
#pragma MAIN inputs_process
MAIN_MHZ(inputs_process, CLOCK_MHZ) // Other MAIN funcs absorb this clock domain
void inputs_process()
{
  // Hard code inputs for sim for now...
  static point_t inputs[N_TEST_POINTS] = {
    {7,1},
    {11,1},
    {11,7},
    {9,7},
    {9,5},
    {2,5},
    {2,3},
    {7,3}
  };
  static uint32_t test_counter;
  static uint1_t test_running = 1;
  uint1_t is_last_cycle = test_counter >= (N_TEST_POINTS-N_POINTS_PER_CYCLE);
  ARRAY_COPY(input_points.points, inputs, N_POINTS_PER_CYCLE) 
  last_input_points = is_last_cycle;
  input_points_valid = test_running;
  if(input_points_valid & ready_for_input_points){
    for(uint32_t i = 0; i<N_POINTS_PER_CYCLE; i+=1){
      printf("Input point[%d] = %d,%d\n", test_counter+i, input_points.points[i].x, input_points.points[i].y);
    }
    ARRAY_SHIFT_DOWN(inputs, N_TEST_POINTS, N_POINTS_PER_CYCLE)
    test_counter += N_POINTS_PER_CYCLE;
    test_running = ~is_last_cycle;
  }
}


// Pipeline to maximize area
area_t area(point_t p1, point_t p2){
  area_t rv;
  uint_t width = abs((int_t)p2.x - (int_t)p1.x) + 1;
  uint_t height = abs((int_t)p2.y - (int_t)p1.y) + 1;
  rv = width * height;
  printf("%d,%d -> %d,%d: width %d height %d area %d\n",
    p1.x,p1.y,p2.x,p2.y,width,height,rv);
  return rv;
}
typedef struct area_max_req_t{
  point_t corner;
  n_points_t poss_other_corners;
}area_max_req_t;
area_t area_maximize(area_max_req_t area_req){
  area_t rv;
  for(uint32_t i = 0; i < N_POINTS_PER_CYCLE; i+=1)
  {
    area_t area_i = area(area_req.corner, area_req.poss_other_corners.points[i]);
    if(area_i > rv){
      rv = area_i;
    }
  }
  printf("Next group max area: %d\n", rv);
  return rv;
}
// area_maximize_pipeline : area_t area_maximize(area_max_req_t)
//  instance of pipeline without handshaking but does include stream valid bit
//  delcares global variable wires as ports to connect to, named like area_maximize_pipeline _in/_out...
GLOBAL_PIPELINE_INST_W_VALID_ID(area_maximize_pipeline, area_t, area_maximize, area_max_req_t)


// Define a type of RAM that holds groups of N points
// Dual port, one write port, one read point, one cycle latency (BRAM)
DECL_STREAM_RAM_DP_W_R_1(n_points_t, n_points_ram_func, RAM_DEPTH, "(others => (others => (others => (others => (others => '0')))))")


// FSM that iterates over all pairs of points in groups of N points at a time
typedef enum state_t{
  // Stream input points into RAM, recording runtime variable number of points
  WRITE_INPUTS_INTO_RAM,
  // One iteration of streaming points from RAM
  // through area maximizing pipeline
  // state repeats to iterate over every pair of points
  // TODO break apart iteration logic so isnt all one big state/transition?
  READ_FROM_RAM_INTO_PIPELINE,
  // Do nothing
  DONE
}state_t;
MAIN_MHZ(ctrl_fsm, CLOCK_MHZ)
void ctrl_fsm(){
  // State regs
  static state_t state;
  static group_counter_t total_point_groups;
  static group_counter_t curr_point_group; // aka current point group starting from
  static group_len_t curr_group_pos; // which of N points in this group is starting corner
  static point_t corner_point; // selected corner point paired with all other points
  static group_counter_t reqs_counter; // aka addresses for read/write request/resp
  static group_counter_t resp_counter;

  // Instance of RAM holding groups of N points with valid ready handshaking interface
  // delcares local variable wires as ports to connect to, named like n_points_ram _rd_addr_in/_wr_data_in...
  RAM_DP_W_R_1_STREAM(n_points_t, n_points_ram_func, n_points_ram)

  // Default not ready for inputs
  ready_for_input_points = 0;
  // Default not writing to RAM
  n_points_ram_wr_in_valid = 0;
  // Default drain write responses from RAM, not waiting for them
  n_points_ram_wr_out_ready = 1;
  // Default not reading from RAM
  n_points_ram_rd_in_valid = 0;
  // Default not ready for read resp from RAM
  n_points_ram_rd_out_ready = 0;
  // Default no data into pipeline
  area_maximize_pipeline_in_valid = 0;

  if(state==WRITE_INPUTS_INTO_RAM){
    // Inputs stream into RAM
    n_points_ram_wr_addr_in = reqs_counter;
    n_points_ram_wr_data_in = input_points;
    n_points_ram_wr_in_valid = input_points_valid;
    ready_for_input_points = n_points_ram_wr_in_ready;
    if(n_points_ram_wr_in_valid & n_points_ram_wr_in_ready){
      reqs_counter += 1;
      if(last_input_points){
        total_point_groups = reqs_counter;
        state = READ_FROM_RAM_INTO_PIPELINE;
        reqs_counter = 0;
      }
    }
  }else if(state==READ_FROM_RAM_INTO_PIPELINE){
    // Iterate over start -> end points groups
    // starting read requests with address
    if(reqs_counter < total_point_groups){
      n_points_ram_rd_addr_in = reqs_counter;
      n_points_ram_rd_in_valid = 1;
      if(n_points_ram_rd_in_valid & n_points_ram_rd_in_ready){
        reqs_counter += 1;
      }
    }

    // Finish read with response data into pipeline
    if(resp_counter < total_point_groups){
      n_points_ram_rd_out_ready = 1; // area_maximize_pipeline_in_ready
      // First response is special first group of points from RAM 
      // that also contains the starting corner point
      if(resp_counter == curr_point_group){
        corner_point = n_points_ram_rd_data_out.points[curr_group_pos];
      }

      // Send corner point and 
      // other group of N points from RAM into area maximize function
      area_maximize_pipeline_in.corner = corner_point;
      area_maximize_pipeline_in.poss_other_corners = n_points_ram_rd_data_out;
      area_maximize_pipeline_in_valid = n_points_ram_rd_out_valid;
      if(area_maximize_pipeline_in_valid /*& area_maximize_pipeline_in_ready*/){
        for(uint32_t i = 0; i<N_POINTS_PER_CYCLE; i+=1){
          printf("Testing area for start %d,%d -> %d,%d\n",
            corner_point.x, corner_point.y,
            n_points_ram_rd_data_out.points[i].x, n_points_ram_rd_data_out.points[i].y);
        }
        resp_counter += 1;
        if(resp_counter==total_point_groups){
          // Got final response for this iteration, reset for next
          // prepare for next starting corner point which might be in current group or next
          if(curr_group_pos==(N_POINTS_PER_CYCLE-1)){
            curr_point_group += 1;
            curr_group_pos = 0;
          }else{
            curr_group_pos += 1;
          }
          reqs_counter = curr_point_group;
          resp_counter = curr_point_group;
        }
      }
    }

    // Done when iterated starting from each point
    if(curr_point_group>=total_point_groups){
      printf("Done.\n");
      state = DONE;
    }
  }
}


// Get max area that comes out of area maximizing pipeline
#pragma MAIN get_max_area
area_t get_max_area(){
  static area_t max_area;
  if(area_maximize_pipeline_out_valid){
    if(area_maximize_pipeline_out > max_area){
      max_area = area_maximize_pipeline_out;
      printf("Maximum area so far: %d\n", max_area);
    }
  }
  // Return so doesnt synthesize away
  return max_area;
}