#include "uintN_t.h"

#pragma MAIN_MHZ main 100.0
//#pragma FUNC_MULT_STYLE main fabric

// Define a "my_fir" function
#define fir_name my_fir
#define FIR_N_TAPS 4
#define FIR_LOG2_N_TAPS 2 // log2(FIR_N_TAPS)
#define fir_data_t uint32_t
#define fir_coeff_t uint8_t
#define fir_out_t uint16_t // data_width + coeff_width + log2(taps#)
#define FIR_COEFFS {1, 2, 3, 4}
#include "dsp/fir.h"

// Main instantiating a fir pipeline
uint16_t main(uint32_t input)
{
  return my_fir(input);
}
