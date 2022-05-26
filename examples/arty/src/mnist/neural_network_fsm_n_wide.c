#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"
#define MNIST_IMAGE_WIDTH 28
#define MNIST_IMAGE_HEIGHT 28
#define MNIST_IMAGE_SIZE MNIST_IMAGE_WIDTH * MNIST_IMAGE_HEIGHT
#define MNIST_LABELS 10
#define pixel_t uint8_t
#define FLOAT_MIN -9999999.0 // Fake but works

// N should be something that evenly divides MNIST_IMAGE_SIZE
//MNIST_IMAGE_WIDTH 28
//MAGE_HEIGHT 28
//MNIST_LABELS=10
//MNIST_IMAGE_WIDTH * MNIST_IMAGE_HEIGHT=784
//  ^*MNIST_LABELS =7840
#define N_PIXELS_PER_ITER 16
#define float_array_sum float_array_sum16 // Built in binary tree function
// Also change 'by_N.c' constants includes below, see helper scripts to generate

typedef struct n_floats_t
{
  float data[N_PIXELS_PER_ITER];
}n_floats_t;
typedef struct n_pixels_t
{
  pixel_t data[N_PIXELS_PER_ITER];
}n_pixels_t;

uint32_t inference_fsm_n_wide()
{
  static uint32_t i; // Label
  static uint32_t j; // Per N image pixels
  static n_floats_t weight[MNIST_LABELS*(MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER)] = 
    #include "random/random_weights_by_16.c"
    ;
  static float bias[MNIST_LABELS] = 
    #include "random/random_biases.c"
  ;
  static n_pixels_t pixel[(MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER)] = 
    #include "random/random_pixels_by_16.c"
  ;
  static float activation[MNIST_LABELS]; // init to zeros
  
  // Null consts for unused write data ports on RAMs
  n_floats_t null_floats;
  n_pixels_t null_pixels;
  
  // Loop computing activation for each label
  for(i = 0; i < MNIST_LABELS; i+=1) 
  {
      float b = bias_RAM_SP_RF_0(i, 0.0, 0); // ROM lookup
      activation[i] = b; // Array write
      for(j = 0; j < (MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER); j+=1)
      {
        __clk(); // Combinatorial logic dividing marker
        n_pixels_t pixels = pixel_RAM_SP_RF_0(j, null_pixels, 0); // ROM lookup
        // ROM lookup
        n_floats_t weights = weight_RAM_SP_RF_0(i*(MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER) + j, null_floats, 0); 
        // Compute N activation increments, W*Pixel in parallel
        float act_increments[N_PIXELS_PER_ITER];
        uint32_t n_iter;
        for(n_iter=0; n_iter<N_PIXELS_PER_ITER; n_iter+=1)
        {
          float scaled_pixel = (float)pixels.data[n_iter] * (1.0/255.0); // FP mul
          float act_inc = weights.data[n_iter] * scaled_pixel; // FP mul
          act_increments[n_iter] = act_inc;
        }
        // Sum the increments (built in binary tree function)
        float act_inc_total = float_array_sum(act_increments);
        // And do the final Array RMW (FP add)
        activation[i] = activation[i] + act_inc_total;
      }
  }
  
  __clk(); // Combinatorial logic dividing marker
  // Find maximally activated neuron
  uint32_t max_act_label;
  float max_act = FLOAT_MIN;
  uint32_t i;
  for(i=0; i<MNIST_LABELS; i+=1)
  {
    float act_i = activation[i]; // Array lookup
    if(act_i > max_act) // FP compare
    {
      max_act = act_i;
      max_act_label = i;
    }
  }  
  return max_act_label;
}
// Derived fsm from inference func
#include "inference_fsm_n_wide_FSM.h"
// Wrap up inference FSM as top level
MAIN_MHZ(inference_fsm_n_wide_wrapper, 25.0)
uint32_t inference_fsm_n_wide_wrapper()
{
  inference_fsm_n_wide_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  inference_fsm_n_wide_OUTPUT_t o = inference_fsm_n_wide_FSM(i);
  return o.return_output;
}

