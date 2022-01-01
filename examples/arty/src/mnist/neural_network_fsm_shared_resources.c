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

float get_weight(uint32_t i, uint32_t j)
{
  // Flatten two indicies into one dimensional array
  uint32_t addr = i*MNIST_IMAGE_SIZE + j;
  
  static float weight[MNIST_LABELS*MNIST_IMAGE_SIZE] = 
    #include "random_weights.c"
  ;
  // RAM built in function
  float unused_write_data;
  return weight_RAM_SP_RF_0(addr, unused_write_data, 0);
  //return weight[i][j];
}
#include "get_weight_SINGLE_INST.h"

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

pixel_t get_pixel(uint32_t j)
{
  static pixel_t pixel[MNIST_IMAGE_SIZE] = 
    #include "random_pixels.c"
  ;
  // RAM built in function
  pixel_t unused_write_data;
  return pixel_RAM_SP_RF_0(j, unused_write_data, 0);
  //return pixel[j];
}
#include "get_pixel_SINGLE_INST.h"

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
  act += inc; // FP Add
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
  return max_i;
}

uint32_t inference_fsm_shared(
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
      for(j = j_start; j < j_end; j+=1)
      {
        pixel_t pixel = get_pixel(j); // Memory lookup
        float scaled_pixel = (float)pixel * (1.0/255.0); // FP mult
        float weight = get_weight(i, j); // Memory lookup
        float act_inc = weight * scaled_pixel; // FP mul weight * scaled_pixel
        inc_act(i, act_inc); // Memory RMW act[i] += weight * scaled_pixel;
      }
  }

  // Only first thread returns activated neuron
  uint32_t max_act_label;
  if(thread_id==0)
  {
    max_act_label = find_max_act();
  }

  return max_act_label;
}
// Derived fsm from inference func
#include "inference_fsm_shared_FSM.h"
// Wrap up inference FSM as top level
MAIN_MHZ(inference_fsm_shared_wrapper, 50.0)
#define N_THREADS 2
#define uint1_array_or uint1_array_or2
uint32_t inference_fsm_shared_wrapper()
{
  static uint1_t thread_dones[N_THREADS];
  uint32_t max_act_label;
  uint32_t tid;
  for(tid=0;tid<N_THREADS;tid+=1)
  {
    inference_fsm_shared_INPUT_t thread_input;
    thread_input.thread_id = tid;
    thread_input.i_start = tid*(MNIST_LABELS/N_THREADS);
    thread_input.i_end = (tid+1)*(MNIST_LABELS/N_THREADS);
    thread_input.j_start = 0;
    thread_input.j_end = MNIST_IMAGE_SIZE;
    thread_input.input_valid = !thread_dones[tid];
    thread_input.output_ready = 1;
    inference_fsm_shared_OUTPUT_t thread_output = inference_fsm_shared_FSM(thread_input);
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
