#include "uintN_t.h"

#pragma PART "xc7a100tcsg324-1"
#pragma MAIN_MHZ main 100.0

/*
// Define a "my_fir" function
#define fir_name my_fir
#define FIR_N_TAPS 4
#define FIR_LOG2_N_TAPS 2 // log2(FIR_N_TAPS)
#define fir_data_t uint16_t
#define fir_coeff_t uint8_t
#define fir_out_t uint26_t // data_width + coeff_width + log2(taps#)
#define FIR_COEFFS {1, 2, 3, 4}
#include "dsp/fir.h"

// Main instantiating a fir pipeline
uint16_t main(uint32_t input)
{
  return my_fir(input);
}
*/


// Define a "my_fir" function
// FIR decimates by dropping samples
#define fir_decim_name my_fir
#define FIR_DECIM_N_TAPS 4
#define FIR_DECIM_LOG2_N_TAPS 2 // log2(FIR_N_TAPS)
#define FIR_DECIM_FACTOR 2
#define fir_decim_data_t uint16_t
#define fir_decim_coeff_t uint8_t
#define fir_decim_out_t uint26_t // data_width + coeff_width + log2(taps#)
#define FIR_DECIM_COEFFS {1, 2, 3, 4}
#include "dsp/fir_decim.h"

// Main instantiating a fir pipeline
// The stream types have .data (the sample) and .valid fields
fir_decim_out_data_stream_type(my_fir) main(fir_decim_in_data_stream_type(my_fir) input)
{
  return my_fir(input);
}
