#include "intN_t.h"
#include "uintN_t.h"

// stream types have .data (the sample) and .valid fields
#include "stream/stream.h" 

#pragma PART "xc7a100tcsg324-1"
#pragma MAIN_MHZ main 100.0

// Define stream type to use
DECL_STREAM_TYPE(int16_t) // stream(int16_t) or int16_t_stream_t

/*
// Define a "my_fir" function
#define fir_name my_fir
#define FIR_N_TAPS 4
#define FIR_LOG2_N_TAPS 2 // log2(FIR_N_TAPS)
#define fir_data_t int16_t
#define fir_data_stream_t stream(fir_data_t)
#define fir_coeff_t int16_t
#define fir_accum_t int34_t // data_width + coeff_width + log2(taps#)
#define fir_out_t int16_t
#define fir_out_stream_t stream(fir_data_t)
#define FIR_POW2_DN_SCALE 15 // data_width + coeff_width - out_width - 1
#define FIR_COEFFS {1, -2, 3, -4}
#include "dsp/fir.h"

// Main instantiating a fir pipeline
stream(int16_t) main(stream(int16_t) input)
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
#define fir_decim_data_t int16_t
#define fir_decim_data_stream_t stream(fir_decim_data_t)
#define fir_decim_coeff_t int16_t
#define fir_decim_accum_t int34_t // data_width + coeff_width + log2(taps#)
#define fir_decim_out_t int16_t // data_width + coeff_width + log2(taps#)
#define fir_decim_out_stream_t stream(fir_decim_data_t)
#define FIR_DECIM_POW2_DN_SCALE 15 // data_width + coeff_width - out_width - 1
#define FIR_DECIM_COEFFS {1, -2, 3, -4}
#include "dsp/fir_decim.h"

// Main instantiating a fir pipeline
stream(int16_t) main(stream(int16_t) input)
{
  return my_fir(input);
}
