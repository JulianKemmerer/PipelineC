// Decimate N streams by N
#include "intN_t.h"
#include "uintN_t.h"
#include "multi_fir_decim_names.h"

// Names for base components
#define base_fir_decim_name   multi_fir_decim_fir_decim_name(multi_fir_decim_name)

// Base decimation FIR
#define fir_decim_name          base_fir_decim_name
#define FIR_DECIM_N_TAPS        MULTI_FIR_DECIM_N_TAPS
#define FIR_DECIM_LOG2_N_TAPS   MULTI_FIR_DECIM_LOG2_N_TAPS
#define FIR_DECIM_FACTOR        MULTI_FIR_DECIM_FACTOR
#define fir_decim_data_t        multi_fir_decim_data_t
#define fir_decim_data_stream_t multi_fir_decim_data_stream_t
#define fir_decim_coeff_t       multi_fir_decim_coeff_t
#define fir_decim_accum_t       multi_fir_decim_accum_t // data_width + coeff_width + log2(taps#)
#define fir_decim_out_t         multi_fir_decim_out_t
#define fir_decim_out_stream_t  multi_fir_decim_out_stream_t
#define FIR_DECIM_POW2_DN_SCALE MULTI_FIR_DECIM_POW2_DN_SCALE // data_width + coeff_width - out_width - 1
#define FIR_DECIM_COEFFS        MULTI_FIR_DECIM_COEFFS
#include "dsp/fir_decim.h"
// Names for base components
#define fir_decim_counter     fir_decim_counter_func(base_fir_decim_name)
#define base_fir_name         fir_decim_fir_name(base_fir_decim_name)
#define fir_samples_window_t  fir_samples_window_type(base_fir_name)
#define fir_samples_window    fir_samples_window_func(base_fir_name)
#define fir                   fir_func(base_fir_name)

// Round robin between multiple streams
#if MULTI_FIR_DECIM_FACTOR > 32
#error "Need larger multi decim counter"
#endif
// N streams must be <= decim factor
#if MULTI_FIR_DECIM_N_STREAMS > MULTI_FIR_DECIM_FACTOR
#error "Too many streams to decimate OR Too low decimation factor"
#endif
#define multi_fir_decim_round_robin_samples_t multi_fir_decim_round_robin_type(multi_fir_decim_name)
#define round_robin_samples multi_fir_decim_round_robin_func(multi_fir_decim_name)
typedef struct multi_fir_decim_round_robin_samples_t{
  fir_samples_window_t sample_window[MULTI_FIR_DECIM_N_STREAMS];
  uint1_t decim_count_ellapsed[MULTI_FIR_DECIM_N_STREAMS];
  uint5_t stream_sel;
}multi_fir_decim_round_robin_samples_t;
multi_fir_decim_round_robin_samples_t round_robin_samples(multi_fir_decim_data_stream_t in_stream[MULTI_FIR_DECIM_N_STREAMS])
{
  // Maintain window of samples for each input stream
  fir_samples_window_t sample_window[MULTI_FIR_DECIM_N_STREAMS];
  // Count off every N samples to decimate
  uint1_t decim_count_ellapsed[MULTI_FIR_DECIM_N_STREAMS];
  uint32_t i;
  for (i = 0; i < MULTI_FIR_DECIM_N_STREAMS; i+=1)
  {
    sample_window[i] = fir_samples_window(in_stream[i]);
    if(in_stream[i].valid){
      decim_count_ellapsed[i] = fir_decim_counter();
    }
  }
  
  // Register holding which stream is selected now
  static uint5_t stream_sel; // TODO add one hot version to use for reset logic?
  // Register to hold count elapsed flag in case not currently selected
  static uint1_t decim_count_ellapsed_reg[MULTI_FIR_DECIM_N_STREAMS];
  // Register entire sample window at time of output
  static fir_samples_window_t sample_window_reg[MULTI_FIR_DECIM_N_STREAMS];
  multi_fir_decim_round_robin_samples_t o;
  for (i = 0; i < MULTI_FIR_DECIM_N_STREAMS; i+=1)
  {
    // Drive output from regs
    o.sample_window[i] = sample_window_reg[i];
    o.decim_count_ellapsed[i] = decim_count_ellapsed_reg[i];
    o.stream_sel = stream_sel;
    // Handel setting and reseting regs
    if(stream_sel==i){
      decim_count_ellapsed_reg[i] = 0;
    }
    if(decim_count_ellapsed[i]){
      decim_count_ellapsed_reg[i] = 1;
      sample_window_reg[i] = sample_window[i];
    }
  }

  // Increment select for next round robin
  if(stream_sel==(MULTI_FIR_DECIM_N_STREAMS-1)){
    stream_sel = 0;
  }else{
    stream_sel += 1;
  }

  return o;
}


#define multi_fir_decim_t multi_fir_decim_type(multi_fir_decim_name)
typedef struct multi_fir_decim_t
{
  multi_fir_decim_out_stream_t out_stream[MULTI_FIR_DECIM_N_STREAMS];
}multi_fir_decim_t;
multi_fir_decim_t multi_fir_decim_name(multi_fir_decim_data_stream_t in_stream[MULTI_FIR_DECIM_N_STREAMS])
{
  // Round robin across n streams of samples
  multi_fir_decim_round_robin_samples_t round_robin = round_robin_samples(in_stream);

  // Select the FIR window of data to use based on the current round robin state
  // TODO make into shift instead of mux random select?
  fir_samples_window_t sample_window = round_robin.sample_window[round_robin.stream_sel];
  //uint1_t decim_count_elapsed = round_robin.decim_count_ellapsed[round_robin.stream_sel];

  // Apply FIR to selected sample window
  int16_t out_data = fir(sample_window.data);

  multi_fir_decim_t rv;
  uint32_t i;
  for (i = 0; i < MULTI_FIR_DECIM_N_STREAMS; i+=1)
  {
    // Output data is only valid for the selected output
    // (if decim counter elapsed too)
    rv.out_stream[i].data = out_data;
    if(round_robin.stream_sel==i){
      rv.out_stream[i].valid = round_robin.decim_count_ellapsed[i];
    }else{
      rv.out_stream[i].valid = 0;
    }
  }
  
  return rv;
}


#undef base_fir_decim_name
#undef base_fir_name
#undef multi_fir_decim_name
#undef MULTI_FIR_DECIM_N_STREAMS
#undef MULTI_FIR_DECIM_N_TAPS
#undef MULTI_FIR_DECIM_LOG2_N_TAPS
#undef MULTI_FIR_DECIM_FACTOR
#undef multi_fir_decim_data_t
#undef multi_fir_decim_coeff_t
#undef multi_fir_decim_accum_t
#undef multi_fir_decim_out_t
#undef MULTI_FIR_DECIM_COEFFS
#undef MULTI_FIR_DECIM_POW2_DN_SCALE
#undef multi_fir_decim_round_robin_samples_t
#undef multi_fir_decim_t
#undef round_robin_samples
#undef fir_decim_counter
#undef multi_fir_decim_data_stream_t
#undef multi_fir_decim_out_stream_t
#undef fir_samples_window_t
#undef fir_samples_window
#undef fir