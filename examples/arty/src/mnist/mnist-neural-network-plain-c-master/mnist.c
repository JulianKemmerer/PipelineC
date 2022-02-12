#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <math.h>

#include "include/mnist_file.h"
#include "include/neural_network.h"

#define STEPS 1000
#define BATCH_SIZE 100

/**
 * Downloaded from: http://yann.lecun.com/exdb/mnist/
 */
const char * train_images_file = "data/train-images-idx3-ubyte";
const char * train_labels_file = "data/train-labels-idx1-ubyte";
const char * test_images_file = "data/t10k-images-idx3-ubyte";
const char * test_labels_file = "data/t10k-labels-idx1-ubyte";

/**
 * Calculate the accuracy of the predictions of a neural network on a dataset.
 */
float calculate_accuracy(mnist_dataset_t * dataset, neural_network_t * network)
{
    float activations[MNIST_LABELS], max_activation;
    int i, j, correct, predict;

    // Loop through the dataset
    for (i = 0, correct = 0; i < dataset->size; i++) {
        // Calculate the activations for each image using the neural network
        neural_network_hypothesis(&dataset->images[i], network, activations);

        // Set predict to the index of the greatest activation
        for (j = 0, predict = 0, max_activation = activations[0]; j < MNIST_LABELS; j++) {
            if (max_activation < activations[j]) {
                max_activation = activations[j];
                predict = j;
            }
        }

        // Increment the correct count if we predicted the right label
        if (predict == dataset->labels[i]) {
            correct++;
        }
    }

    // Return the percentage we predicted correctly as the accuracy
    return ((float) correct) / ((float) dataset->size);
}

int main(int argc, char *argv[])
{
    mnist_dataset_t * train_dataset, * test_dataset;
    mnist_dataset_t batch;
    neural_network_t network;
    float loss, accuracy;
    int i, j, batches;

    // Read the datasets from the files
    train_dataset = mnist_get_dataset(train_images_file, train_labels_file);
    test_dataset = mnist_get_dataset(test_images_file, test_labels_file);

    // Initialise weights and biases with random values
    neural_network_random_weights(&network);

    // Calculate how many batches (so we know when to wrap around)
    batches = train_dataset->size / BATCH_SIZE;

    for (i = 0; i < STEPS; i++) {
        // Initialise a new batch
        mnist_batch(train_dataset, &batch, 100, i % batches);

        // Run one step of gradient descent and calculate the loss
        loss = neural_network_training_step(&batch, &network, 0.5);

        // Calculate the accuracy using the whole test dataset
        accuracy = calculate_accuracy(test_dataset, &network);

        printf("Step %04d\tAverage Loss: %.2f\tAccuracy: %.3f\n", i, loss / batch.size, accuracy);
    }

    // Print trained values for hacky import elsewhere
    printf("# Trained weights:\n");
    printf("weights = dict()\n");
    for (i = 0; i < MNIST_LABELS; i++) {
        printf("weights[%d] = dict();\n");
        for (j = 0; j < MNIST_IMAGE_SIZE; j++) {
            float w = network.W[i][j];
            printf("weights[%d][%d] = %f\n", i, j, w);
        }
    }
    printf("\n");
    printf("# Trained biases:\n");
    printf("biases = [\n");
    for (i = 0; i < MNIST_LABELS; i++) {
        float b = network.b[i];
        printf("%f, ", b);
    }
    printf("\n]\n");
    printf("\n");
    mnist_image_t test_image = test_dataset->images[0];
    uint8_t test_label = test_dataset->labels[0];
    printf("# Pixels for test image labeled as: %d\n", test_label);
    printf("pixels = [\n");
    for (i = 0; i < MNIST_IMAGE_SIZE; i++) {
        uint8_t p = test_image.pixels[i];
        printf("%d, ", p);
    }
    printf("\n]\n");
    printf("\n");
    float activations[MNIST_LABELS];
    neural_network_hypothesis(&test_image, &network, activations);
    int predict = 0;
    float max_activation = activations[0];
    for (j = 0; j < MNIST_LABELS; j++) {
        if (max_activation < activations[j]) {
            max_activation = activations[j];
            predict = j;
        }
    }
    printf("# Inference predicts: %d\n", predict);
    printf("activations = [\n");
    for (i = 0; i < MNIST_LABELS; i++) {
        float a = activations[i];
        printf("%f, ", a);
    }
    printf("\n]\n");
    printf("\n");

    // Cleanup
    mnist_free_dataset(train_dataset);
    mnist_free_dataset(test_dataset);

    return 0;
}
