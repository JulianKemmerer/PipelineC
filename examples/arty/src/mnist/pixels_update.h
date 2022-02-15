// Define how many pixels at a time can write/read from memory/be sent in a buffer

// N should be something that evenly divides MNIST_IMAGE_SIZE
#define N_PIXELS_PER_UPDATE 16
#define pixel_t uint8_t
typedef struct pixels_update_t
{
    pixel_t pixels[N_PIXELS_PER_UPDATE];
    uint16_t addr;
    uint8_t pad19; // Temp must be >=4 bytes and mult of 4 bytes in size
    uint8_t pad20;
}pixels_update_t;

// Size pixels per iter to match size of update data over ethernet since share pixel memory
#define N_PIXELS_PER_ITER N_PIXELS_PER_UPDATE
#define per_iter_float_array_sum float_array_sum16 // Built in binary tree function
// Also change 'by_N.c' constants includes in neural_network_eth_app.c
// see helper script trained/c_gen.py to generate
typedef struct n_floats_t
{
  float data[N_PIXELS_PER_ITER];
}n_floats_t;
typedef struct n_pixels_t
{
  pixel_t data[N_PIXELS_PER_ITER];
}n_pixels_t;