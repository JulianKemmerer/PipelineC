#include "compiler.h"
#include "uintN_t.h"

#include "fir_names.h"

// Not continuous, only somtimes valid, stream of samples

// Use can optionally supply their own stream types
// TODO if not defined then make default stream(fir_data_t)
// i.e. expect user to have defined stream type always 
#ifndef fir_data_stream_t
#define fir_data_stream_t fir_in_data_stream_type(fir_name)
typedef struct fir_data_stream_t{
  fir_data_t data;
  uint1_t valid;
}fir_data_stream_t;
#endif
// TODO similar make output default type be data_t stream(fir_data_t) 
#ifndef fir_out_stream_t
#define fir_out_stream_t fir_out_data_stream_type(fir_name)
typedef struct fir_out_stream_t{
  fir_out_t data;
  uint1_t valid;
}fir_out_stream_t;
#endif

// Type for array of data
#define fir_samples_window_t fir_samples_window_type(fir_name)
typedef struct fir_samples_window_t{
  fir_data_t data[FIR_N_TAPS];
}fir_samples_window_t;

#define fir_samples_window fir_samples_window_func(fir_name)
PRAGMA_MESSAGE(FUNC_WIRES fir_samples_window) // Not worried about delay of this func
fir_samples_window_t fir_samples_window(fir_data_stream_t input)
{
  static fir_samples_window_t window;
  //fir_samples_window_t rv = window;
  if(input.valid){
    uint32_t i;
    for(i=(FIR_N_TAPS-1); i>0; i=i-1)
    {
      window.data[i] = window.data[i-1];
    }
    window.data[0] = input.data;
  }
  return window;
}

// Declare binary tree of adders for after the sample*coeff
#include "binary_tree.h"
DECL_BINARY_OP_TREE(PPCAT(fir_name,_adder_tree), fir_accum_t, fir_accum_t, fir_accum_t, +, FIR_N_TAPS, FIR_LOG2_N_TAPS)

// The FIR pure function to be pipelined
#define fir fir_func(fir_name)
fir_out_t fir(fir_data_t data[FIR_N_TAPS])
{
  // Constant set of coeffs
  fir_coeff_t coeffs[FIR_N_TAPS] = FIR_COEFFS;

  // Compute product of sample * coeff
  fir_accum_t products[FIR_N_TAPS];
  uint32_t i;
  for(i=0; i < FIR_N_TAPS; i+=1)
  {
    products[i] = data[i] * coeffs[i]; // Apply SCALE here?
  }
   
  // A binary tree of adders is used to sum the results of the coeff*data multiplies
  fir_accum_t rv = PPCAT(fir_name,_adder_tree)(products);

  // TODO apply scale earlier instead?
  #ifdef FIR_OUT_SCALE
  rv = (rv * FIR_OUT_SCALE) >> FIR_POW2_DN_SCALE;
  #else
  rv = rv >> FIR_POW2_DN_SCALE;
  #endif
  return rv;
}

// The FIR filter pipeline
// Always inputting and outputting a sample each cycle
fir_out_stream_t fir_name(fir_data_stream_t input)
{
  // buffer up N datas in shift reg
  fir_samples_window_t sample_window = fir_samples_window(input);
  // compute FIR func on the sample window
  fir_out_stream_t rv;
  rv.valid = input.valid;
  rv.data = fir(sample_window.data);
  return rv;
}


#undef fir_name
#undef FIR_N_TAPS
#undef FIR_LOG2_N_TAPS
#undef fir_data_t
#undef fir_coeff_t
#undef fir_accum_t
#undef fir_out_t
#undef FIR_COEFFS
#ifdef FIR_OUT_SCALE
#undef FIR_OUT_SCALE
#endif
#undef FIR_POW2_DN_SCALE
#undef fir_data_stream_t
#undef fir_out_stream_t
#undef fir_samples_window_t
#undef fir_samples_window
#undef fir


