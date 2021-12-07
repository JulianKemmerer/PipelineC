#include "uintN_t.h"
#include "wire.h"
//#include "neural_network.h"
#define MNIST_IMAGE_WIDTH 28
#define MNIST_IMAGE_HEIGHT 28
#define MNIST_IMAGE_SIZE MNIST_IMAGE_WIDTH * MNIST_IMAGE_HEIGHT
#define MNIST_LABELS 10
#define pixel_t uint8_t

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
// Keep host memory loading / communication separate from computation NN core

pixel_t get_pixel(uint32_t j)
{
  static pixel_t pixel[MNIST_IMAGE_SIZE] = 
    #include "random_pixels.c"
  ;
  pixel_t unused_write_data;
  return pixel_RAM_SP_RF_0(j, unused_write_data, 0);
  //return pixel[j];
}

float scale_pixel(pixel_t p)
{
  return (float)p / 255.0;
}

float get_bias(uint32_t i)
{
  static float bias[MNIST_LABELS] = 
    #include "random_biases.c"
  ;
  return bias[i];
}

float get_weight(uint32_t i, uint32_t j)
{
  // Flatten two indicies into one dimensional array
  uint32_t addr = i*MNIST_IMAGE_SIZE + j;
  
  static float weight[MNIST_LABELS*MNIST_IMAGE_SIZE] = 
    #include "random_weights.c"
  ;
  float unused_write_data;
  return weight_RAM_SP_RF_0(addr, unused_write_data, 0);
  //static float weight[MNIST_LABELS][MNIST_IMAGE_SIZE] = RANDOM_WEIGHTS;
  //return weight[i][j];
}

float weight_mul(float weight, float pixel)
{
  return weight * pixel;
}

uint1_t act_gt(float lhs, float rhs)
{
  return lhs > rhs;
} 

float rw_act(uint32_t i, float write_data, uint1_t write_enable)
{
  static float act[MNIST_LABELS]; // init to zeros
  return act_RAM_SP_RF_0(i, write_data, write_enable);
  //float rv = act[i];
  //if(write_enable)
  //{
  //  act[i] = val;
  //}
  //return rv;
}
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

uint32_t find_max_act()
{
  float max = -9999999.0;
  uint32_t max_i;
  uint32_t i;
  for(i=0; i<MNIST_LABELS; i+=1)
  {
    float act_i = get_act(i);
    if(act_gt(act_i, max))
    {
      max = act_i;
      max_i = i;
    }
  }
  return max_i;
}

void inc_act(uint32_t i, float inc)
{
  float act = get_act(i);
  act += inc;
  set_act(i, act);
}

uint32_t inference()
{
  static uint32_t i; // Label
  static uint32_t j; // Per image pixel
  
  for(i = 0; i < MNIST_LABELS; i+=1) 
  {
      float bias = get_bias(i); // Memory lookup
      set_act(i, bias); // Memory write 
      for(j = 0; j < MNIST_IMAGE_SIZE; j+=1)
      {
        pixel_t pixel = get_pixel(j); // Memory lookup
        float scaled_pixel = scale_pixel(pixel); // FP divide
        float weight = get_weight(i, j); // Memory lookup
        float act_inc = weight_mul(weight, scaled_pixel); // FP mul weight * scaled_pixel
        inc_act(i, act_inc); // Memory RMW act[i] += weight * scaled_pixel;
      }
  }
  
  uint32_t max_act_label = find_max_act();
  
  return max_act_label;
}
// Derived fsm from inference func
#include "inference_FSM.h"

// Wrap up inference FSM as top level
MAIN_MHZ(inference_wrapper, 10.0) // UART_CLK_MHZUse uart clock for main
uint32_t inference_wrapper()
{
  inference_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  inference_OUTPUT_t o = inference_FSM(i);
  return o.return_output;
}

// Oh shit a pair of two single instance functions is need
// A start and finish async kind of thing?
// Need way to check out/lock a piece of memory


