#include <hls_stream.h>

extern "C"
void stream_to_maxi(
    hls::stream<unsigned int> &input,
    unsigned int *output,
    unsigned int number_of_elements
) {
    for (unsigned int i = 0; i < number_of_elements; ++i) {
        output[i] = input.read();
    }
}