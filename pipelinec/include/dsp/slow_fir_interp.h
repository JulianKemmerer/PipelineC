#include "compiler.h"
#include "stream/stream.h"
#include "uintN_t.h"

// Names for base components
#define base_slow_fir_name   PPCAT(slow_fir_interp_name, _base_slow_fir)

// Declare FIR for after inserting zeros to smooth interpolate
// Base FIR instance
#define slow_fir_name        base_slow_fir_name
#define SLOW_FIR_N_TAPS      SLOW_FIR_INTERP_N_TAPS
#define slow_fir_data_t      slow_fir_interp_data_t
#define slow_fir_coeff_t     slow_fir_interp_coeff_t
#define slow_fir_accum_t     slow_fir_interp_accum_t
#define slow_fir_out_t       slow_fir_interp_out_t
#define SLOW_FIR_OUT_SCALE   SLOW_FIR_INTERP_OUT_SCALE
#define SLOW_FIR_POW2_DN_SCALE  SLOW_FIR_INTERP_POW2_DN_SCALE
#define SLOW_FIR_COEFFS      SLOW_FIR_INTERP_COEFFS
#define SLOW_FIR_II           FLOOR_DIV(SLOW_FIR_INTERP_II_IN, SLOW_FIR_INTERP_FACTOR)
#define slow_fir_binary_tree_func slow_fir_interp_binary_tree_func
#include "dsp/slow_fir.h"

// Insert N-1 zeros
// TODO: THIS WAS JUST COPIED FROM fir_interp.h, share better
#define slow_fir_interp_insert_n_zeros PPCAT(slow_fir_interp_name,_insert_n_zeros)
stream(slow_fir_interp_data_t) slow_fir_interp_insert_n_zeros(stream(slow_fir_interp_data_t) in_sample)
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
  uint1_t interp_ratio_elapsed = interp_ratio_counter==(SLOW_FIR_INTERP_FACTOR-1);
  if(in_sample.valid){
    interp_ratio_counter = 1;
  }else if(interp_ratio_elapsed){
    interp_ratio_counter = 0;
  }else{
    interp_ratio_counter += 1;
  }

  // Buffer one sample to output it with gap between it and next sample
  static stream(slow_fir_interp_data_t) sample_buf;
  stream(slow_fir_interp_data_t) sample_from_buf;
  
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
  stream(slow_fir_interp_data_t) o;
  o.valid = 0;
  if(sample_from_buf.valid){
    // restart zeros
    zero_counter = SLOW_FIR_INTERP_FACTOR - 1;
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
stream(slow_fir_interp_out_t) slow_fir_interp_name(stream(slow_fir_interp_data_t) in_sample){
  // Insert zeros between samples per interp ratio
  stream(slow_fir_interp_data_t) samples_w_zeros = slow_fir_interp_insert_n_zeros(in_sample);

  // Smooth the samples pulses with FIR
  stream(slow_fir_interp_out_t) interp_out = base_slow_fir_name(samples_w_zeros);

  return interp_out;
}

#undef base_slow_fir_name
#undef slow_fir_interp_name
#undef SLOW_FIR_INTERP_N_TAPS
#undef SLOW_FIR_INTERP_FACTOR
#undef slow_fir_interp_data_t
#undef slow_fir_interp_coeff_t
#undef slow_fir_interp_accum_t
#undef slow_fir_interp_out_t
#ifdef SLOW_FIR_INTERP_OUT_SCALE
#undef SLOW_FIR_INTERP_OUT_SCALE
#endif
#undef SLOW_FIR_INTERP_POW2_DN_SCALE
#undef SLOW_FIR_INTERP_COEFFS
#undef slow_fir_interp_insert_n_zeros
#undef slow_fir_interp_data_t
#undef slow_fir_interp_binary_tree_func
#undef SLOW_FIR_INTERP_II_IN
#undef SLOW_FIR_INTERP_II_OUT
