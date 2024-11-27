#include "uintN_t.h"
#include "fir_interp_names.h"

// Names for base components
#define base_fir_name   fir_interp_fir_name(fir_interp_name)

// Allow user to provide stream type
// TODO default to stream(data_t etc)
#ifndef fir_interp_data_stream_t
#define fir_interp_data_stream_t fir_in_data_stream_type(base_fir_name)
#endif
#ifndef fir_interp_out_stream_t
#define fir_interp_out_stream_t fir_out_data_stream_type(base_fir_name)
#endif

// Declare FIR for after inserting zeros to smooth interpolate
// Base FIR instance
#define fir_name        base_fir_name
#define FIR_N_TAPS      FIR_INTERP_N_TAPS
#define FIR_LOG2_N_TAPS FIR_INTERP_LOG2_N_TAPS
#define fir_data_t      fir_interp_data_t
#define fir_data_stream_t fir_interp_data_stream_t
#define fir_coeff_t     fir_interp_coeff_t
#define fir_accum_t     fir_interp_accum_t
#define fir_out_t       fir_interp_out_t
#define fir_out_stream_t fir_interp_out_stream_t
#define FIR_OUT_SCALE   FIR_INTERP_OUT_SCALE
#define FIR_POW2_DN_SCALE  FIR_INTERP_POW2_DN_SCALE
#define FIR_COEFFS      FIR_INTERP_COEFFS
#include "dsp/fir.h"

// Insert N-1 zeros
#define fir_interp_insert_n_zeros fir_interp_insert_n_zeros_func(fir_interp_name)
fir_interp_data_stream_t fir_interp_insert_n_zeros(fir_interp_data_stream_t in_sample)
{
  // Keep counting up to interp ratio
  // Resets to align with new samples
  // cautious to count current input cycle as 0 by resetting to 1 for next cycle
  // this is critical for ~rounding to a faster output II
  // at input II=interp factor:
  // interp_ratio_elapsed occurs a cycle before next input and periods_since_sample_count=1
  // also ex. II=5 interp by 4x yields II=1 output bursts
  // expected to compare period count with zeros_interp_period_cycles_counter=0, so '-1' exists below
  static uint8_t interp_ratio_counter;
  uint1_t interp_ratio_elapsed = interp_ratio_counter==(FIR_INTERP_FACTOR-1);
  if(in_sample.valid){
    interp_ratio_counter = 1;
  }else if(interp_ratio_elapsed){
    interp_ratio_counter = 0;
  }else{
    interp_ratio_counter += 1;
  }

  // Buffer one sample to output it with gap between it and next sample
  static fir_interp_data_stream_t sample_buf;
  fir_interp_data_stream_t sample_from_buf;
  
  // Output buffer contents once new next sample arrives
  if(in_sample.valid){
    // Output
    sample_from_buf = sample_buf;
    // Input
    sample_buf = in_sample;
  }

  // Insert N-1 zeros at slower rate
  static uint8_t zero_counter;
  static uint16_t sample_periods_count;
  static uint16_t zeros_interp_period_cycles_counter;
  fir_interp_data_stream_t o;
  o.valid = 0;
  if(sample_from_buf.valid){
    // restart zeros
    zero_counter = FIR_INTERP_FACTOR - 1;
    zeros_interp_period_cycles_counter = 0;
    // output real original sample pulse
    o.valid = 1;
    o.data = sample_from_buf.data;
  }else{
    // output several zeros at counted off rate
    if(zeros_interp_period_cycles_counter>=(sample_periods_count)){ // Removed -1 here
      zeros_interp_period_cycles_counter = 0;
      if(zero_counter > 0){
        o.valid = 1;
        o.data = 0;
        zero_counter -= 1;
      }
    }else{
      zeros_interp_period_cycles_counter += 1;
    }
  }

  // Counting how many periods
  // Increment period counter or
  // set output reg + reset when sample arrive
  static uint16_t periods_since_sample_count;
  if(in_sample.valid){
    // New sample uses period count if had good prev sample in buffer
    if(sample_from_buf.valid){
      sample_periods_count = periods_since_sample_count - 1; // Extra minus 1 done here
    }
    periods_since_sample_count = 0;
  }else if(interp_ratio_elapsed){
    periods_since_sample_count += 1;
  }
  return o;
}

// The FIR pipeline
fir_interp_out_stream_t fir_interp_name(fir_interp_data_stream_t in_sample){
  // Insert zeros between samples per interp ratio
  fir_interp_data_stream_t samples_w_zeros = fir_interp_insert_n_zeros(in_sample);

  // Smooth the samples pulses with FIR
  fir_interp_out_stream_t interp_out = base_fir_name(samples_w_zeros);

  return interp_out;
}

#undef base_fir_name
#undef fir_interp_name
#undef FIR_INTERP_N_TAPS
#undef FIR_INTERP_LOG2_N_TAPS
#undef FIR_INTERP_FACTOR
#undef fir_interp_data_t
#undef fir_interp_coeff_t
#undef fir_interp_accum_t
#undef fir_interp_out_t
#ifdef FIR_INTERP_OUT_SCALE
#undef FIR_INTERP_OUT_SCALE
#endif
#undef FIR_INTERP_POW2_DN_SCALE
#undef FIR_INTERP_COEFFS
#undef fir_interp_insert_n_zeros
#undef fir_interp_data_t
#undef fir_interp_out_stream_t
