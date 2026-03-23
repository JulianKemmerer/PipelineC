
#include "stream/stream.h"
#include "fifo.h"

// Define FIFO to instantiate later
#define SCALE_MAX_IN_WIDTH 1024
FIFO_FWFT(scale_line_fifo, video_t, SCALE_MAX_IN_WIDTH) 

// Scaler is little two state FSM with counters
typedef enum scale_state_t{
  LOAD_PIXELS,
  //  enqueue entire line of input pixels
  OUTPUT_PIXELS
  //   output single pixel N times for width*n
  //   recirculate fifo N times for lines*n
}scale_state_t;

typedef struct scale2d_t{
  // Module outputs
  stream(video_t) video_out;
  uint1_t ready_for_video_in;
}scale2d_t;
scale2d_t scale2d(
  // Module inputs
  scale2d_params_t params_in,
  stream(video_t) video_in,
  uint1_t ready_for_video_out
){
  // The line fifo instance
  // Input into fifo are driven after the instance later by FSM
  // so are declared here as FEEDBACK to be used as now
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_fifo_out)
  DECL_FEEDBACK_WIRE(video_t, fifo_data_in)
  DECL_FEEDBACK_WIRE(uint1_t, fifo_data_in_valid)
  scale_line_fifo_t fifo = scale_line_fifo(
    ready_for_fifo_out,
    fifo_data_in,
    fifo_data_in_valid
  );

  // FSM regs
  static scale_state_t state;
  static uint8_t width_counter;
  static uint8_t height_counter;
  static uint1_t is_last_input_line;
  // Reg for params, only take new input at frame bounds (SOF)
  static uint1_t starting_new_frame = 1;
  static scale2d_params_t params_reg;
  scale2d_params_t params = params_reg;
  // Output wires (default zeros)
  scale2d_t o;
  // Default no xfers in or out of fifo
  ready_for_fifo_out = 0;
  video_t NULL_PIXELS;
  fifo_data_in = NULL_PIXELS;
  fifo_data_in_valid = 0;
  if(state==LOAD_PIXELS){
    // Connect input stream of pixels into fifo
    fifo_data_in = video_in.data;
    fifo_data_in_valid = video_in.valid;
    o.ready_for_video_in = fifo.data_in_ready;
    if(video_in.valid & o.ready_for_video_in){
      // Accept params at SOF
      if(starting_new_frame){
        params_reg = params_in;
        starting_new_frame = 0;
      }
      // Until end of line goes into fifo
      if(video_in.data.eod[0]){
        // Then begin outputting duplicate pixels
        state = OUTPUT_PIXELS;
        width_counter = 0;
        height_counter = 0;
        is_last_input_line = video_in.data.eod[1];
      }
    }
  }else{/*state==OUTPUT_PIXELS*/
    // Outputting pixel value from fifo read side
    o.video_out.data = fifo.data_out;
    o.video_out.valid = fifo.data_out_valid;
    ready_for_fifo_out = ready_for_video_out;
    // Only actually reading from fifo during last repeat in this line
    ready_for_fifo_out &= (width_counter==(params.scale-1));

    // New end of line/end of frame flags based on counters
    o.video_out.data.eod[0] = fifo.data_out.eod[0] & (width_counter==(params.scale-1));
    o.video_out.data.eod[1] = is_last_input_line & (height_counter==(params.scale-1));

    // Pixels are recycled back into fifo if not last repeat of line
    // Assumes fifo write side is ready
    if(height_counter < (params.scale-1)){
      //ready_for_fifo_out &= fifo.data_in_ready;
      fifo_data_in = fifo.data_out;
      fifo_data_in_valid = fifo.data_out_valid & ready_for_fifo_out;
    }

    // Update width and height repeat counters
    // maybe resetting back to load state for next line
    if(o.video_out.valid & ready_for_video_out){
      if(width_counter==(params.scale-1)){
        // Last repeat of this pixel
        width_counter = 0;
        // Last pixel of line?
        if(fifo.data_out.eod[0]){
          // Last repeat of current line?
          if(height_counter==(params.scale-1)){
            // Next line
            state = LOAD_PIXELS;
            // Was this last line EOF?
            starting_new_frame = is_last_input_line;
          }else{
            // More repeats of current line
            height_counter += 1;
          }
        }
      }else{
        // More repeats of pixel in this line
        width_counter += 1;
      }
    }
  }
  
  return o;
}

// Globally visible video bus for SoC
stream(video_t) scale_video_in; // input
uint1_t scale_video_in_ready; // output
stream(video_t) scale_video_out; // output
uint1_t scale_video_out_ready; // input
scale2d_params_t scale_params;

// FIFO to avoid overflow due to scaling outputting more pixels than input
GLOBAL_STREAM_FIFO(video_t, scale_fifo, 65536) // TODO down size

DECL_OUTPUT(uint1_t, scale_overflow)

#pragma MAIN scale_main
void scale_main(){
  scale_fifo_in = scale_video_in;
  scale_video_in_ready = scale_fifo_in_ready;

  scale2d_t scale = scale2d(
    scale_params,
    scale_fifo_out,
    scale_video_out_ready
  );
  scale_fifo_out_ready = scale.ready_for_video_in;
  scale_video_out = scale.video_out;

  static uint1_t overflow_reg;
  scale_overflow = overflow_reg;
  overflow_reg |= scale_fifo_in.valid & ~scale_fifo_in_ready;
}