#ifndef NEURAL_NETWORK_H_
#define NEURAL_NETWORK_H_

#include "mnist_file.h"

typedef struct neural_network_t_ {
    float b[MNIST_LABELS];
    float W[MNIST_LABELS][MNIST_IMAGE_SIZE];
} neural_network_t;

typedef struct neural_network_gradient_t_ {
    float b_grad[MNIST_LABELS];
    float W_grad[MNIST_LABELS][MNIST_IMAGE_SIZE];
} neural_network_gradient_t;

void neural_network_random_weights(neural_network_t * network);
void neural_network_hypothesis(mnist_image_t * image, neural_network_t * network, float activations[MNIST_LABELS]);
float neural_network_gradient_update(mnist_image_t * image, neural_network_t * network, neural_network_gradient_t * gradient, uint8_t label);
float neural_network_training_step(mnist_dataset_t * dataset, neural_network_t * network, float learning_rate);

#endif
