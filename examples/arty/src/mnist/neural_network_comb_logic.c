#include "uintN_t.h"

#define MNIST_LABELS 10
#define MNIST_IMAGE_WIDTH 8
#define MNIST_IMAGE_HEIGHT 8
#define MNIST_IMAGE_SIZE (MNIST_IMAGE_WIDTH * MNIST_IMAGE_HEIGHT)
typedef struct mnist_image_t
{
    uint8_t pixels[MNIST_IMAGE_SIZE];
} mnist_image_t;

// Convert a pixel value from 0-255 to one from 0 to 1
#define PIXEL_SCALE(x) (((float) (x)) / 255.0)

// Returns a random value between 0 and 1
#define RAND_FLOAT() (((float) rand()) / ((float) RAND_MAX))

typedef struct neural_network_t 
{
    float b[MNIST_LABELS];
    float W[MNIST_LABELS][MNIST_IMAGE_SIZE];
} neural_network_t;

typedef struct neural_network_activations_t
{
   float activations[MNIST_LABELS];
} neural_network_activations_t;

/**
 * Use the weights and bias vector to forward propogate through the neural
 * network and calculate the activations.
 */
#pragma MAIN_MHZ neural_network_hypothesis 100.0
uint8_t neural_network_hypothesis(mnist_image_t image)
{
  neural_network_activations_t a;
  neural_network_t network;
  #include "rand_net.c" // Randomized network values for synthesis estimate  
  uint32_t i, j;
  for (i = 0; i < MNIST_LABELS; i+=1) 
  {
      a.activations[i] = network.b[i];

      for (j = 0; j < MNIST_IMAGE_SIZE; j+=1) 
      {
          a.activations[i] += network.W[i][j] * PIXEL_SCALE(image.pixels[j]);
      }
  }

  // Find the max activation and return its index
  float max_act = -99999.9; //?
  uint8_t max_act_i = 0;
  for (i = 0; i < MNIST_LABELS; i+=1) 
  {
      if(a.activations[i] > max_act)
      {
        max_act = a.activations[i];
        max_act_i = i;
      }
  }
  return max_act_i;
}
