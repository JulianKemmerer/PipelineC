#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"

#define MNIST_IMAGE_WIDTH 28
#define MNIST_IMAGE_HEIGHT 28
#define MNIST_IMAGE_SIZE MNIST_IMAGE_WIDTH * MNIST_IMAGE_HEIGHT
#define MNIST_LABELS 10
#define pixel_t uint8_t
#define FLOAT_MIN -9999999.0 // Fake but works

uint32_t inference_fsm_basic()
{
  static uint32_t i; // Label
  static uint32_t j; // Per image pixel
  static float weight[MNIST_LABELS*MNIST_IMAGE_SIZE] = 
    #include "trained/weights.c"
  ;
  static float bias[MNIST_LABELS] = 
    #include "trained/biases.c"
  ;
  static pixel_t pixel[MNIST_IMAGE_SIZE] = 
    #include "trained/test_image_0_pixels.c"
  ;
  static float activation[MNIST_LABELS]; // init to zeros
  
  // Loop computing activation for each label
  for(i = 0; i < MNIST_LABELS; i+=1) 
  {
      float b = bias_RAM_SP_RF_0(i, 0.0, 0); // ROM lookup
      activation[i] = b; // Array write
      for(j = 0; j < MNIST_IMAGE_SIZE; j+=1)
      {
        __clk(); // Combinatorial logic dividing marker
        pixel_t p = pixel_RAM_SP_RF_0(j, 0, 0); // ROM lookup
        float scaled_pixel = (float)p * (1.0/255.0); // FP mul
        float w = weight_RAM_SP_RF_0(i*MNIST_IMAGE_SIZE + j, 0.0, 0); // ROM lookup
        float act_inc = w * scaled_pixel; // FP mul
        activation[i] = activation[i] + act_inc; // Array RMW (FP add)
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
#include "inference_fsm_basic_FSM.h"
// Wrap up inference FSM as top level
MAIN_MHZ(inference_fsm_basic_wrapper, 25.0)
uint32_t inference_fsm_basic_wrapper()
{
  inference_fsm_basic_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  inference_fsm_basic_OUTPUT_t o = inference_fsm_basic_FSM(i);
  return o.return_output;
}

