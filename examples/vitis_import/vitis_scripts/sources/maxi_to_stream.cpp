#include <hls_stream.h>

extern "C"
void maxi_to_stream(
    unsigned int *input,
    hls::stream<unsigned int> &output,
    unsigned int number_of_elements
) {
    for (unsigned int i = 0; i < number_of_elements; ++i) {
        output.write(input[i]);
    }
}