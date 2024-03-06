#include "uintN_t.h"
#include "fir_decim_names.h"

// Names for base components
#define base_fir_name   fir_decim_fir_name(fir_decim_name)

// Allow user to provide stream type
// TODO default to stream(data_t etc)
#ifndef fir_decim_data_stream_t
#define fir_decim_data_stream_t fir_in_data_stream_type(base_fir_name)
#endif
#ifndef fir_decim_out_stream_t
#define fir_decim_out_stream_t fir_out_data_stream_type(base_fir_name)
#endif

// Base FIR instance (without decimation)
#define fir_name        base_fir_name
#define FIR_N_TAPS      FIR_DECIM_N_TAPS
#define FIR_LOG2_N_TAPS FIR_DECIM_LOG2_N_TAPS
#define fir_data_t      fir_decim_data_t
#define fir_data_stream_t fir_decim_data_stream_t
#define fir_coeff_t     fir_decim_coeff_t
#define fir_accum_t     fir_decim_accum_t
#define fir_out_t       fir_decim_out_t
#define fir_out_stream_t fir_decim_out_stream_t
#define FIR_POW2_DN_SCALE  FIR_DECIM_POW2_DN_SCALE
#define FIR_COEFFS      FIR_DECIM_COEFFS
#include "dsp/fir.h"

// Count off every N samples
#define fir_decim_counter fir_decim_counter_func(fir_decim_name)
PRAGMA_MESSAGE(FUNC_WIRES fir_decim_counter) // Not worried about delay of this func
uint1_t fir_decim_counter()
{
  static uint5_t counter;
  #if FIR_DECIM_FACTOR > 32
  #error "Need larger decim counter"
  #endif
  uint1_t ellapsed; 
  if(counter==(FIR_DECIM_FACTOR-1)){
    counter = 0;
    ellapsed = 1;
  }else{
    counter += 1;
  }
  return ellapsed;
}

// The FIR filter pipeline that skips every N samples while filtering
#define fir_samples_window_t fir_samples_window_type(base_fir_name)
#define fir_samples_window fir_samples_window_func(base_fir_name)
#define fir fir_func(base_fir_name)
fir_decim_out_stream_t fir_decim_name(fir_decim_data_stream_t input)
{
  // Buffer up samples in shift reg
  fir_samples_window_t sample_window = fir_samples_window(input);

  // Count off every N samples to decimate
  uint1_t decim_count_ellapsed;
  if(input.valid){
    decim_count_ellapsed = fir_decim_counter();
  }

  // If counted N samples, compute FIR func on the sample window
  fir_decim_out_stream_t rv;
  rv.valid = decim_count_ellapsed;
  // IF() not needed in hardware since pure FIR func and have valid flag
  // Can add IF() for efficient CPU implementation
  //if(decim_count_ellapsed){ 
    rv.data = fir(sample_window.data);
  //}

  return rv;
}

#undef base_fir_name
#undef fir_decim_name
#undef FIR_DECIM_N_TAPS
#undef FIR_DECIM_LOG2_N_TAPS
#undef FIR_DECIM_FACTOR
#undef fir_decim_data_t
#undef fir_decim_coeff_t
#undef fir_decim_accum_t
#undef fir_decim_out_t
#undef FIR_DECIM_COEFFS
#undef FIR_DECIM_POW2_DN_SCALE
#undef fir_decim_counter
#undef fir_decim_data_stream_t
#undef fir_decim_out_stream_t
#undef fir_samples_window_t
#undef fir_samples_window
#undef fir
