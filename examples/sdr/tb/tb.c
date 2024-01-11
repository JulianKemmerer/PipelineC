#include "arrays.h"
#include "intN_t.h"
#include "uintN_t.h"

#pragma PART "xc7a100tcsg324-1"

// Example FIR from https://scipy-cookbook.readthedocs.io/items/FIRFilter.html
#define TAPS_SIZE 74
#define TAPS {\
-5,\
-3,\
4,\
14,\
23,\
24,\
11,\
-14,\
-46,\
-69,\
-67,\
-30,\
36,\
110,\
158,\
149,\
66,\
-75,\
-226,\
-320,\
-295,\
-128,\
146,\
435,\
612,\
565,\
247,\
-284,\
-862,\
-1246,\
-1196,\
-553,\
689,\
2354,\
4121,\
5599,\
6441,\
6441,\
5599,\
4121,\
2354,\
689,\
-553,\
-1196,\
-1246,\
-862,\
-284,\
247,\
565,\
612,\
435,\
146,\
-128,\
-295,\
-320,\
-226,\
-75,\
66,\
149,\
158,\
110,\
36,\
-30,\
-67,\
-69,\
-46,\
-14,\
11,\
24,\
23,\
14,\
4,\
-3,\
-5\
}


// Define a "my_fir" function
// FIR decimates by dropping samples
#define fir_decim_name my_fir
#define FIR_DECIM_N_TAPS TAPS_SIZE
#define FIR_DECIM_LOG2_N_TAPS 7 // log2(FIR_N_TAPS)
#define FIR_DECIM_FACTOR 1 
#define fir_decim_data_t int16_t
#define fir_decim_coeff_t int16_t
#define fir_decim_accum_t int39_t // data_width + coeff_width + log2(taps#)
#define fir_decim_out_t int16_t
#define FIR_DECIM_POW2_SCALE 15 // data_width + coeff_width - out_width - 1
#define FIR_DECIM_COEFFS TAPS
#include "dsp/fir_decim.h"

/*// Main instantiating a fir pipeline
// The stream types have .data (the sample) and .valid fields
#pragma MAIN_MHZ main 100.0
fir_decim_out_data_stream_type(my_fir) main(fir_decim_in_data_stream_type(my_fir) input)
{
  return my_fir(input);
}*/

//#pragma MAIN_MHZ my_fir 100.0

// Test bench
#include "samples.h"
#pragma MAIN tb
void tb()
{
  static uint32_t cycle_counter;
  static int16_t i_samples[I_SAMPLES_SIZE] = I_SAMPLES;
  static int16_t q_samples[Q_SAMPLES_SIZE] = Q_SAMPLES;

  // Prepare input sample into FIR
  fir_decim_in_data_stream_type(my_fir) i_input;
  i_input.data = i_samples[0];
  i_input.valid = 1;
  fir_decim_in_data_stream_type(my_fir) q_input;
  q_input.data = q_samples[0];
  q_input.valid = 1;

  // Do one clock cycle, input valid and get output
  fir_decim_out_data_stream_type(my_fir) i_output;
  i_output = my_fir(i_input);
  fir_decim_out_data_stream_type(my_fir) q_output;
  q_output = my_fir(q_input);

  // Print valid output samples
  if(i_output.valid&q_output.valid){
    printf("Cycle %d,Sample IQ =,%d,%d\n", cycle_counter, i_output.data, q_output.data);
  }

  // Prepare for next sample
  ARRAY_SHIFT_DOWN(i_samples, I_SAMPLES_SIZE, 1)
  ARRAY_SHIFT_DOWN(q_samples, Q_SAMPLES_SIZE, 1)
  cycle_counter+=1;
}