//TODO replace with SLOW_
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

// Insert zeros // TODO REPLACE WITH COUNTED OFF AT INTERP RATE VERSION ONCE TESTED SEPARATE
#define slow_fir_interp_insert_n_zeros PPCAT(slow_fir_interp_name,_insert_n_zeros)
PRAGMA_MESSAGE(FUNC_WIRES slow_fir_interp_insert_n_zeros) // Not worried about delay of this func
stream(slow_fir_interp_data_t) slow_fir_interp_insert_n_zeros(stream(slow_fir_interp_data_t) in_sample){
  static uint8_t zero_counter;  // TODO size counter?
  stream(slow_fir_interp_data_t) o;
  o.valid = 0;
  if(in_sample.valid){
    // restart zeros
    zero_counter = SLOW_FIR_INTERP_FACTOR - 1;
    // output real original sample pulse
    o.valid = 1;
    o.data = in_sample.data;
  }else{
    // output zeros
    if(zero_counter > 0){
      o.valid = 1;
      o.data = 0;
      zero_counter -= 1;
    }
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
