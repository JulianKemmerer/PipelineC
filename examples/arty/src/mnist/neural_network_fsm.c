#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"
#define MNIST_IMAGE_WIDTH 28
#define MNIST_IMAGE_HEIGHT 28
#define MNIST_IMAGE_SIZE MNIST_IMAGE_WIDTH * MNIST_IMAGE_HEIGHT
#define MNIST_LABELS 10
#define pixel_t uint8_t
#define FLOAT_MIN -9999999.0 // Fake but works

/*
for (i = 0; i < MNIST_LABELS; i+=1) 
{
    a.activations[i] = network.b[i];
    for (j = 0; j < MNIST_IMAGE_SIZE; j+=1) 
    {
        a.activations[i] += network.W[i][j] * PIXEL_SCALE(image.pixels[j]);
    }
}
*/

// Threads
#define N_THREADS 2
#define uint1_array_or uint1_array_or2
// Pixels per thread loop iter
#define N_PIXELS_PER_ITER 8
#define float_array_sum float_array_sum8 // Built in binary tree function
#define float_array_sum_half float_array_sum4
#define float_array_sum_quarter float_array_sum2
// Also change 'by_N.c' RAM init includes below, see helper scripts to generate

typedef struct n_floats_t
{
  float data[N_PIXELS_PER_ITER];
}n_floats_t;
typedef struct n_pixels_t
{
  pixel_t data[N_PIXELS_PER_ITER];
}n_pixels_t;

typedef struct n_floats_and_pixels_t
{
  n_floats_t floats;
  n_pixels_t pixels;
}n_floats_and_pixels_t;
n_floats_and_pixels_t get_weights_and_pixels(uint32_t i, uint32_t j)
{
  n_floats_and_pixels_t rv;
  
  // Weights lookup
  // Flatten two indicies into one dimensional array
  uint32_t addr = i*(MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER) + j;
  static n_floats_t weight[MNIST_LABELS*(MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER)] = 
    #include "random_weights_by_8.c"
  ;
  // RAM built in function
  n_floats_t unused_float_write_data;
  rv.floats = weight_RAM_SP_RF_0(addr, unused_float_write_data, 0);
  //return weight[i][j];
  
  // Pixel lookup
  static n_pixels_t pixel[(MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER)] = 
    #include "random_pixels_by_8.c"
  ;
  // RAM built in function
  n_pixels_t unused_pixel_write_data;
  rv.pixels = pixel_RAM_SP_RF_0(j, unused_pixel_write_data, 0);
  //return pixel[j];
  
  return rv;
}
#include "get_weights_and_pixels_SINGLE_INST.h"

float get_bias(uint32_t i)
{
  static float bias[MNIST_LABELS] = 
    #include "random_biases.c"
  ;
  // RAM built in function
  float unused_write_data;
  return bias_RAM_SP_RF_0(i, unused_write_data, 0);
  //return bias[i];
}
#include "get_bias_SINGLE_INST.h"

float rw_act(uint32_t i, float write_data, uint1_t write_enable)
{
  static float act[MNIST_LABELS]; // init to zeros
  // RAM built in function
  return act_RAM_SP_RF_0(i, write_data, write_enable);
  //float rv = act[i];
  //if(write_enable)
  //{
  //  act[i] = val;
  //}
  //return rv;
}
// Only one fsm can run this func at a time
// (only a single rw_act module will exist)
#include "rw_act_SINGLE_INST.h"

float get_act(uint32_t i)
{
  float unused_write_val;
  float act = rw_act(i, unused_write_val, 0);
  return act;
}

void set_act(uint32_t i, float val)
{
  rw_act(i, val, 1);
}

void inc_act(uint32_t i, float inc)
{
  float act = get_act(i); // rw_act RAM read
  //__clk();
  act += inc; // FP Add
  //__clk();
  set_act(i, act); // rw_act RAM write
}

uint32_t find_max_act()
{
  float max = -9999999.0;
  uint32_t max_i;
  uint32_t i;
  for(i=0; i<MNIST_LABELS; i+=1)
  {
    float act_i = get_act(i);
    if(act_i > max)
    {
      max = act_i;
      max_i = i;
    }
  }
  __clk();
  return max_i;
}
//#include "find_max_act_SINGLE_INST.h"

float two_clock_array_sum8_pre(float act_increments[8])
{
  float partial_sums[4];
  partial_sums[0] = act_increments[0] + act_increments[1];
  partial_sums[1] = act_increments[2] + act_increments[3];
  partial_sums[2] = act_increments[4] + act_increments[5];
  partial_sums[3] = act_increments[6] + act_increments[7];
  __clk();
  float next_partial_sums[2];
  next_partial_sums[0] = partial_sums[0] + partial_sums[1];
  next_partial_sums[1] = partial_sums[2] + partial_sums[3];
  float rv = next_partial_sums[0] + next_partial_sums[1];
  return rv;
}

float two_clock_array_sum8_post(float act_increments[8])
{
  float partial_sums[4];
  partial_sums[0] = act_increments[0] + act_increments[1];
  partial_sums[1] = act_increments[2] + act_increments[3];
  partial_sums[2] = act_increments[4] + act_increments[5];
  partial_sums[3] = act_increments[6] + act_increments[7];
  float next_partial_sums[2];
  next_partial_sums[0] = partial_sums[0] + partial_sums[1];
  next_partial_sums[1] = partial_sums[2] + partial_sums[3];
  __clk();
  float rv = next_partial_sums[0] + next_partial_sums[1];
  return rv;
}

float three_clock_array_sum8(float act_increments[8])
{
  float partial_sums[4];
  partial_sums[0] = act_increments[0] + act_increments[1];
  partial_sums[1] = act_increments[2] + act_increments[3];
  partial_sums[2] = act_increments[4] + act_increments[5];
  partial_sums[3] = act_increments[6] + act_increments[7];
  __clk();
  float next_partial_sums[2];
  next_partial_sums[0] = partial_sums[0] + partial_sums[1];
  next_partial_sums[1] = partial_sums[2] + partial_sums[3];
  __clk();
  float rv = next_partial_sums[0] + next_partial_sums[1];
  return rv;
}

uint32_t inference_fsm_shared_nwide(
  uint32_t thread_id,
  uint32_t i_start, uint32_t i_end,
  uint32_t j_start, uint32_t j_end
)
{
  static uint32_t i; // Label
  static uint32_t j; // Per image pixel

  for(i = i_start; i < i_end; i+=1) 
  {
      float bias = get_bias(i); // Memory lookup
      set_act(i, bias); // Memory write
      __clk();
      for(j = j_start; j < j_end; j+=1)
      {
        // Memory lookups
        n_floats_and_pixels_t weight_and_pixels = 
          get_weights_and_pixels(i, j);
        n_floats_t weights = weight_and_pixels.floats;
        n_pixels_t pixels = weight_and_pixels.pixels;
        // Compute N activation increments, W*Pixel in parallel
        float act_increments[N_PIXELS_PER_ITER];
        uint32_t n_iter;
        for(n_iter=0; n_iter<N_PIXELS_PER_ITER; n_iter+=1)
        {
          float scaled_pixel = (float)pixels.data[n_iter] * (1.0/255.0); // FP mul
          float act_inc = weights.data[n_iter] * scaled_pixel; // FP mul
          act_increments[n_iter] = act_inc;
        }
        // Sum the increments
        float act_inc_total = float_array_sum(act_increments);
        // Memory RMW
        inc_act(i, act_inc_total);
      }
      __clk();
  }

  __clk();
  
  // Only first thread returns most activated neuron
  uint32_t max_act_label;
  if(thread_id==0)
  {
    max_act_label = find_max_act();
  }
  

  return max_act_label;
}
// Derived fsm from inference func
#include "inference_fsm_shared_nwide_FSM.h"
// Wrap up inference FSM as top level
MAIN_MHZ(inference_fsm_shared_nwide_wrapper, 50.0)
uint32_t inference_fsm_shared_nwide_wrapper()
{
  static uint1_t thread_dones[N_THREADS];
  uint32_t max_act_label;
  uint32_t tid;
  for(tid=0;tid<N_THREADS;tid+=1)
  {
    inference_fsm_shared_nwide_INPUT_t thread_input;
    thread_input.thread_id = tid;
    thread_input.i_start = tid*(MNIST_LABELS/N_THREADS);
    thread_input.i_end = (tid+1)*(MNIST_LABELS/N_THREADS);
    thread_input.j_start = 0;
    thread_input.j_end = MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER;
    thread_input.input_valid = !thread_dones[tid];
    thread_input.output_ready = 1;
    inference_fsm_shared_nwide_OUTPUT_t thread_output = inference_fsm_shared_nwide_FSM(thread_input);
    if(thread_output.output_valid)
    {
      thread_dones[tid] = 1;
      if(tid==0)
      {
        max_act_label = thread_output.return_output;
      }
    }
  }
  return max_act_label;
}

// No 

// Oh shit a pair of two single instance functions is need
// A start and finish async kind of thing?
// Need way to check out/lock a piece of memory


/*
todo even simpler inference loop
neuron function version?
then atomic memory version?
*/
