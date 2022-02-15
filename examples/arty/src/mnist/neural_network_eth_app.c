// Modified version of N-pixels wide MNIST example to support 
// pixel memory being shared/loaded over ethernet 
// and predicitions being sent back over ethernet

uint32_t inference_fsm_basic()
{
  static uint32_t i; // Label
  static uint32_t j; // Per image pixel
  // Pixels are shared with logic to load over ethernet
  // Weights, biases, activations
  static n_floats_t weight[MNIST_LABELS*(MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER)] = 
    #include "trained/weights_by_16.c"
  ;
  static float bias[MNIST_LABELS] = 
    #include "trained/biases.c"
  ;
  static float activation[MNIST_LABELS]; // init to zeros

  // Null consts for unused write data ports on RAMs
  n_floats_t null_floats;
  
  // Loop computing activation for each label
  for(i = 0; i < MNIST_LABELS; i+=1) 
  {
      float b = bias_RAM_SP_RF_0(i, 0.0, 0); // ROM lookup
      activation[i] = b; // Array write
      for(j = 0; j < (MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER); j+=1)
      {
        __clk(); // Combinatorial logic dividing marker
        n_pixels_t pixels = pixel_mem_read(j); // RAM lookup
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
        float act_inc_total = per_iter_float_array_sum(act_increments);
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
#include "inference_fsm_basic_FSM.h"
// Wrap up inference FSM as top level
MAIN_MHZ(inference_fsm_basic_wrapper, NN_CLOCK_MHZ)
void inference_fsm_basic_wrapper()
{
  inference_fsm_basic_INPUT_t i;
  // Run repeatedly
  i.input_valid = 1; 
  i.output_ready = 1;
  inference_fsm_basic_OUTPUT_t o = inference_fsm_basic_FSM(i);

  // Assemble output prediction to write into fifo
  pred_resp_t resp[1];
  resp[0].pred = o.return_output;
  
  // Get count of how many nanosec between predictions
  static uint32_t nanosec_counter;
  resp[0].nanosec_since = nanosec_counter;
  nanosec_counter += (uint32_t)(1000.0/NN_CLOCK_MHZ);
  if(o.output_valid)
  {
    nanosec_counter = 0;
  }

  // Write output predictions into fifo
  outputs_fifo_write_t output_write = outputs_fifo_WRITE_1(resp, o.output_valid);
}
