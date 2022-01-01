#pragma MAIN inference_comb_logic_zero_clocks
uint32_t inference_comb_logic_zero_clocks()
{
  uint32_t i; // Label
  uint32_t j; // Per image pixel
  // Flatten two indicies of weight lookup into one dimensional array
  float weight[MNIST_LABELS][MNIST_IMAGE_SIZE]; // TODO INIT BEFORE SYNTHESIZING
  float bias[MNIST_LABELS] = 
    #include "random_biases.c"
  ;
  pixel_t pixel[MNIST_IMAGE_SIZE] = 
    #include "random_pixels.c"
  ;
  float activation[MNIST_LABELS]; // init to zeros
  
  // Loop computing activation for each label
  for(i = 0; i < MNIST_LABELS; i+=1) 
  {
      float b = bias[i]; // Array lookup
      activation[i] = b; // Array write
      for(j = 0; j < MNIST_IMAGE_SIZE; j+=1)
      {
        pixel_t p = pixel[j]; // Array lookup
        float scaled_pixel = (float)p * (1.0/255.0); // FP mul
        float w = weight[i][j]; // Array lookup
        float act_inc = w * scaled_pixel; // FP mul
        activation[i] += act_inc; // Array RMW (FP add)
      }
  }
  
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
