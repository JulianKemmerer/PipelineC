#include "compiler.h"
#include "uintN_t.h"
#include "arrays.h"
#include "slow_binary_op.h"
#include "slow_binary_tree.h"

// FIR that is slow II > 1

// Composed of slow multiplier for sample*coeff
#define slow_mult_func PPCAT(slow_fir_name,_slow_mult)
DECL_SLOW_BINARY_OP(
  slow_mult_func,
  SLOW_FIR_II,
  slow_fir_accum_t, *,
  slow_fir_data_t, slow_fir_coeff_t,
  SLOW_FIR_N_TAPS
)
// followed by slow binary adder tree for output sum
// slow binary tree must be declared in advance
// #define slow_fir_binary_tree_func

// Type for array of data
#define slow_fir_samples_window_t PPCAT(slow_fir_name,_samples_window_t)
typedef struct slow_fir_samples_window_t{
  slow_fir_data_t data[SLOW_FIR_N_TAPS];
}slow_fir_samples_window_t;

#define slow_fir_samples_window PPCAT(slow_fir_name,_samples_window)
PRAGMA_MESSAGE(FUNC_WIRES slow_fir_samples_window) // Not worried about delay of this func
slow_fir_samples_window_t slow_fir_samples_window(stream(slow_fir_data_t) input)
{
  static slow_fir_samples_window_t window;
  if(input.valid){
    ARRAY_1SHIFT_INTO_BOTTOM(window.data, SLOW_FIR_N_TAPS, input.data)
  }
  return window;
}

// The FIR filter pipeline
// Always inputting and outputting a sample each cycle
stream(slow_fir_out_t) slow_fir_name(stream(slow_fir_data_t) input)
{
  // Constant set of coeffs
  slow_fir_coeff_t coeffs[SLOW_FIR_N_TAPS] = SLOW_FIR_COEFFS;
  // buffer up N datas in shift reg
  slow_fir_samples_window_t sample_window = slow_fir_samples_window(input);

  // Slow multiply samples*coeffs
  PPCAT(slow_mult_func,_out_t) slow_mult = slow_mult_func(sample_window.data, coeffs, input.valid);
  // Then slow binary tree sum those results
  stream(slow_fir_accum_t) sum_stream = slow_fir_binary_tree_func(slow_mult.data, slow_mult.valid);

  // Output scaling
  slow_fir_accum_t sum = sum_stream.data;
  #ifdef SLOW_FIR_OUT_SCALE
  sum = (sum * SLOW_FIR_OUT_SCALE) >> SLOW_FIR_POW2_DN_SCALE;
  #else
  sum = sum >> SLOW_FIR_POW2_DN_SCALE;
  #endif

  stream(slow_fir_out_t) out_stream;
  out_stream.data = sum;
  out_stream.valid = sum_stream.valid;
  return out_stream;
}


#undef slow_fir_name
#undef SLOW_FIR_N_TAPS
#undef SLOW_FIR_II
#undef slow_fir_data_t
#undef slow_fir_coeff_t
#undef slow_fir_accum_t
#undef slow_fir_out_t
#undef SLOW_FIR_COEFFS
#undef slow_fir_binary_tree_func
#undef slow_mult_func
#ifdef SLOW_FIR_OUT_SCALE
#undef SLOW_FIR_OUT_SCALE
#endif
#undef SLOW_FIR_POW2_DN_SCALE
#undef slow_fir_samples_window_t
#undef slow_fir_samples_window


