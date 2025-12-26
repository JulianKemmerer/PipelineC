#pragma PART "xc7a100tcsg324-1" // FMAX ~200 MHz
//#pragma PART "LFE5U-85F-6BG381C" // FMAX ~120 MHz
#define CLOCK_MHZ 120 // Limited by sliding_window stateful function
#include "uintN_t.h"
#include "intN_t.h"
#include "arrays.h"
#include "global_func_inst.h"
#include "fifo.h"

#define WINDOW_HEIGHT 3
#define WINDOW_WIDTH 3
#define WINDOW_CENTER_X (WINDOW_WIDTH / 2)
#define WINDOW_CENTER_Y (WINDOW_HEIGHT / 2)
#define X_INIT ((-WINDOW_CENTER_X) - 1)
#define Y_INIT (-WINDOW_CENTER_Y)
#define LINE_WIDTH 10 // Used to size fifo buffers
#define NUM_LINES 10 // Used to know when test input ends
#define line_w_t int8_t // min: log2 line width +1
#define line_h_t int8_t // min: log2 num lines + 1
#define input_t char
#define EMPTY '.'
#define ROLL '@'
// TODO param for N input chars per cycle

// Window stuff
typedef struct window_t{
  input_t data[WINDOW_WIDTH][WINDOW_HEIGHT];
}window_t;
// Fixed size arrays printf for sim
void print_3x3(char name[16], char data[3][3]){
  // Print null as EMPTY
  for (uint32_t i = 0; i < 3; i+=1)
  {
    for (uint32_t j = 0; j < 3; j+=1)
    {
      if(data[i][j]==0) data[i][j] = EMPTY;
    }
  }
  printf("%s\n%c%c%c\n%c%c%c\n%c%c%c\n",
    name,
    data[0][0],data[1][0],data[2][0],
    data[0][1],data[1][1],data[2][1],
    data[0][2],data[1][2],data[2][2]
  );
}
window_t slide_window(window_t curr, input_t next_input_col[WINDOW_HEIGHT]){
  // Sliding right, shifting columns
  window_t next = curr;
  for(uint32_t x = 0; x < WINDOW_WIDTH; x+=1){
    // Copy column x+1 into x
    for(uint32_t y = 0; y < WINDOW_HEIGHT; y+=1){
      if(x < (WINDOW_WIDTH-1)){
        next.data[x][y] = curr.data[x+1][y];
      }else{
        next.data[x][y] = next_input_col[y];
      }
    }
  }
  return next;
}


// Define type of FIFO for holding a line of input
FIFO_FWFT(line_fifo, input_t, LINE_WIDTH)


// Input stream -> sliding window output using fifos
typedef struct sliding_window_t{
  window_t window;
  uint1_t window_valid;
  uint1_t ready_for_data_in;
}sliding_window_t;
sliding_window_t sliding_window(
  input_t data,
  uint1_t data_valid
  // TODO output flow control uint1_t ready_for_window_out
){
  sliding_window_t o;

  // Window output single cycle valid from regs
  static window_t window;
  static uint1_t window_valid;
  o.window = window;
  o.window_valid = window_valid;
  window_valid = 0;

  // Number of line buffer fifos matching height of window
  // FIFO outputs feed into next fifo as window slides
  // Re: #pragma FEEDBACK
  //  All fifo output signals are only available after the line_fifo() func call
  //  to uses those output values on the input side of func call before invocation
  //  they are declared as FEEDBACK, final assigned value becomes first read value
  uint1_t fifo_output_xfer_enable[WINDOW_HEIGHT];
  #pragma FEEDBACK fifo_output_xfer_enable
  // Write side of fifos
  input_t fifo_inputs[WINDOW_HEIGHT];
  uint1_t fifo_input_valids[WINDOW_HEIGHT];
  uint1_t fifo_readys_for_input[WINDOW_HEIGHT];
  #pragma FEEDBACK fifo_readys_for_input
  // Read side of fifos
  input_t fifo_outputs[WINDOW_HEIGHT];
  #pragma FEEDBACK fifo_outputs
  uint1_t fifo_output_valids[WINDOW_HEIGHT];
  #pragma FEEDBACK fifo_output_valids
  uint1_t fifo_readys_for_output[WINDOW_HEIGHT];

  // Input stream goes into first fifo
  fifo_inputs[0] = data;
  fifo_input_valids[0] = data_valid;
  o.ready_for_data_in = fifo_readys_for_input[0];

  // Instances of fifo with output[i] into next[i+1] input wiring
  for(uint32_t i=0; i<WINDOW_HEIGHT; i+=1){
    // FIFO input is from previous line, default disconnected
    fifo_readys_for_output[i] = 0;
    if(fifo_output_xfer_enable[i]){
      if(i<(WINDOW_HEIGHT-1)){
        // FIFO[i] outputs feed into next fifo[i+1] as window slides
        fifo_inputs[i+1] = fifo_outputs[i];
        fifo_input_valids[i+1] = fifo_output_valids[i];
        fifo_readys_for_output[i] = fifo_readys_for_input[i+1];
      }else{
        // Last fifo just drains to nowhere as window slides
        fifo_readys_for_output[i] = 1;
      }
    }
    // The fifo itself
    line_fifo_t fifo_out = line_fifo(
      fifo_readys_for_output[i],
      fifo_inputs[i],
      fifo_input_valids[i]
    );
    // FIFO output feedback connections
    fifo_readys_for_input[i] = fifo_out.data_in_ready;
    fifo_outputs[i] = fifo_out.data_out;
    fifo_output_valids[i] = fifo_out.data_out_valid;
  }

  // Window center begins outside of frame
  static line_w_t window_x_pos = X_INIT;
  static line_h_t window_y_pos = Y_INIT;
  // When is more data needed from which fifos?
  uint1_t want_data_from_fifo[WINDOW_HEIGHT];
  // X range applies to all fifos
  if(window_x_pos < (LINE_WIDTH-2)){
    // Y range is specific to each fifo, annoying magic number ranges
    for(uint32_t i=0; i<WINDOW_HEIGHT; i+=1){
      want_data_from_fifo[i] = (window_y_pos >= (i-WINDOW_CENTER_Y)) & (window_y_pos <= (NUM_LINES-WINDOW_CENTER_Y-1+i));
    }
  }
  
  // Want to slide window if not yet done frame
  uint1_t window_sliding = window_y_pos < NUM_LINES;
  // But only will slide if have data from all needed fifos
  for(uint32_t i=0; i<WINDOW_HEIGHT; i+=1){
    if(want_data_from_fifo[i]){
      window_sliding &= fifo_output_valids[i];
    }
  }

  // Actually reading from fifo if sliding window
  for(uint32_t i=0; i<WINDOW_HEIGHT; i+=1){
    fifo_output_xfer_enable[i] = 0;
    if(window_sliding){
      fifo_output_xfer_enable[i] = want_data_from_fifo[i];
    }
  }

  // Input column values into sliding window have reversed indexing
  // relative to input stream into fifo[i=0] indexing above
  input_t next_input_col[WINDOW_HEIGHT];
  for(uint32_t i=0; i<WINDOW_HEIGHT; i+=1){
    uint32_t y = WINDOW_HEIGHT - 1 - i;
    next_input_col[y] = EMPTY;
    if(fifo_output_valids[i] & fifo_readys_for_output[i]){
      next_input_col[y] = fifo_outputs[i];
    }
  }
  
  // Do window sliding along current row/clearing as needed for next row
  if(window_sliding){
    printf("Current window center pos: %d,%d (valid=%d)\n", window_x_pos, window_y_pos, o.window_valid);
    print_3x3("Current:", window.data);
    // Next window is valid?
    if(window_x_pos < (LINE_WIDTH-1)){
      //printf("Sliding right...\n");
      window_x_pos += 1;
      window = slide_window(window, next_input_col);
      window_valid = (window_x_pos >= 0) & (window_y_pos >= 0) & (window_y_pos < NUM_LINES);
    }else{
      //printf("End of line reset...\n");
      window_x_pos = X_INIT;
      window_y_pos += 1;
      window_t empty_window;
      window = empty_window;
    }
    // TODO last line end of frame reset
  }

  return o;
}


// Pure function pipeline counting neighbors around the center paper roll location
uint1_t center_roll_accessible(window_t window){
  uint4_t neighbor_count;
  input_t center;
  for (uint32_t i = 0; i < WINDOW_WIDTH; i+=1)
  {
    for (uint32_t j = 0; j < WINDOW_HEIGHT; j+=1)
    {
      if((i==WINDOW_CENTER_X)&(j==WINDOW_CENTER_Y)){
        center = window.data[i][j];
      }else{
        neighbor_count += (window.data[i][j]==ROLL);
      }
    }
  }
  return (center==ROLL) & (neighbor_count < 4);
}
// center_roll_accessible_pipeline : uint1_t center_roll_accessible(window_t)
//  instance of pipeline without handshaking but does include stream valid bit
//  delcares global variable wires as ports to connect to, named like center_roll_accessible_pipeline _in/_out...
GLOBAL_PIPELINE_INST_W_VALID_ID(center_roll_accessible_pipeline, uint1_t, center_roll_accessible, window_t)


// Inputs to dataflow
// Global wires connect this process into rest of design
input_t input_data;
uint1_t input_valid;
uint1_t ready_for_input;
#pragma MAIN inputs_process
MAIN_MHZ(inputs_process, CLOCK_MHZ) // Other MAIN funcs absorb this clock domain
void inputs_process()
{
  // Hard code inputs for sim for now...
  static input_t inputs[NUM_LINES][LINE_WIDTH] = {
    "..@@.@@@@.",
    "@@@.@.@.@@",
    "@@@@@.@.@@",
    "@.@@@@..@.",
    "@@.@@@@.@@",
    ".@@@@@@@.@",
    ".@.@.@.@@@",
    "@.@@@.@@@@",
    ".@@@@@@@@.",
    "@.@.@@@.@."
  };
  static uint16_t y_counter;
  static uint16_t x_counter;
  static uint1_t test_running = 1;
  uint1_t is_end_of_line = x_counter >= (LINE_WIDTH-1);
  uint1_t is_last_line = y_counter >= (NUM_LINES-1);
  input_data = inputs[0][0];
  input_valid = test_running;
  if(input_valid & ready_for_input){
    //printf("Input line %d char[%d]: %c\n", y_counter, x_counter, input_data);
    // End of line?
    if(is_end_of_line){
      // next line
      ARRAY_SHIFT_DOWN(inputs, NUM_LINES, 1)
      y_counter += 1;
      x_counter = 0;
    }else{
      // next char in line
      ARRAY_SHIFT_DOWN(inputs[0], LINE_WIDTH, 1)
      x_counter += 1;
    }
    test_running = ~(is_end_of_line & is_last_line);
  }
}


#pragma MAIN sliding_window_process
void sliding_window_process(){
  // Input stream into instance of sliding window
  sliding_window_t sw = sliding_window(
    input_data,
    input_valid
    //1 // Pipeline always ready_for_window_out
  );
  // Sliding window output into compute pipeline
  ready_for_input = sw.ready_for_data_in;
  center_roll_accessible_pipeline_in = sw.window;
  center_roll_accessible_pipeline_in_valid = sw.window_valid;
}


// Accumulate how many paper roll locations can be accessed by forklift
#pragma MAIN accum_pipeline_output
uint32_t accum_pipeline_output(){
  static uint32_t total;
  if(center_roll_accessible_pipeline_out_valid & center_roll_accessible_pipeline_out){
    total += 1;
    printf("Current total roll locations accessible: %d\n", total);
  }
  // Return so doesnt synthesize away
  return total;
}