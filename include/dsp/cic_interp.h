#include "arrays.h"
#include "intN_t.h"
#include "uintN_t.h"
#include "handshake/handshake.h"

// Generated names for cics
#include "compiler.h"

#ifndef CIC_N_STAGES
  #define CIC_N_STAGES 1
#endif

/* Interpolation */
#define cic_interp_insert_n_copies_func(cic_name) PPCAT(cic_name,_interp_insert_n_copies)
#define cic_interp_comb_func(cic_name) PPCAT(cic_name,_interp_comb)
#define cic_interp_integ_func(cic_name) PPCAT(cic_name,_interp_integ)

DECL_HANDSHAKE_TYPE(cic_accum_t)

// Insert copies
#define cic_interp_insert_n_copies cic_interp_insert_n_copies_func(cic_name)

hs_out(cic_accum_t) cic_interp_insert_n_copies(stream(cic_accum_t) in_sample)
{
  static uint16_t copy_counter = 0;
  static stream(cic_accum_t) buf;
  hs_out(cic_accum_t) o;
  o.stream_out.valid = 0;
  o.ready_for_stream_in = copy_counter == 0;
  if(in_sample.valid){
    o.stream_out = in_sample;
    buf = in_sample;
    copy_counter = CIC_INTERP_FACTOR - 1;
  }else{
    if(copy_counter > 0)
    {
      o.stream_out = buf;
      copy_counter -= 1;
    }
  }
  return o;
}


#define cic_interp_comb cic_interp_comb_func(cic_name)
stream(cic_accum_t) cic_interp_comb(stream(cic_data_t) in_sample){
  //static cic_accum_t delay[CIC_N_STAGES] = {0};
  //cic_accum_t comb = in_sample.data;
  //uint16_t i;
  //for (i = 0; i < CIC_N_STAGES; i+=1)
  //{
  //  cic_accum_t newcomb = (cic_accum_t)(comb - delay[i]);
  //  delay[i] = comb;
  //  comb = newcomb;
  //}
  //stream(cic_accum_t) o = {.data = comb, .valid = in_sample.valid};
  static cic_accum_t in_prev = 0;
  cic_accum_t comb = in_sample.data - in_prev;
  stream(cic_accum_t) o;
  if(in_sample.valid){
    o.data = comb;
    o.valid = 1;
    in_prev = in_sample.data;
  }else{
    o.data = 0;
    o.valid = 0;
  }
  return o;
}

#define cic_interp_integ cic_interp_integ_func(cic_name)
hs_out(cic_accum_t) cic_interp_integ(hs_out(cic_accum_t) in_sample){
  //static cic_accum_t integ[CIC_N_STAGES] = {0};
  //cic_accum_t accum = in_sample.data;
  //uint16_t i;
  //for (i = 0; i < CIC_N_STAGES; i+=1)
  //{
  //  integ[i] = (cic_accum_t)(integ[i] + accum);
  //  accum = integ[i];
  //}
  //stream(cic_accum_t) o = {.data = accum, .valid = in_sample.valid};
  static cic_accum_t integ = 0;
  hs_out(cic_accum_t) o;
  o.ready_for_stream_in = in_sample.ready_for_stream_in;
  if(in_sample.stream_out.valid){
    integ += in_sample.stream_out.data;
    o.stream_out.data = integ;
    o.stream_out.valid = 1;
  }else{
    o.stream_out.data = 0;
    o.stream_out.valid = 0;
  }
  return o;
}

// main pipeline
hs_out(cic_accum_t) cic_name(stream(cic_data_t) input){

  // Comb stages at Fs / N
  stream(cic_accum_t) comb_out = cic_interp_comb(input);

  // Insert copies (oversample to Fs)
  hs_out(cic_accum_t) comb_with_copies = cic_interp_insert_n_copies(comb_out);

  // Integ stages at Fs
  hs_out(cic_accum_t) integ_out = cic_interp_integ(comb_with_copies);

  return integ_out;
}

#undef cic_name
#undef CIC_INTERP_FACTOR
#undef CIC_LOG2_N
#undef CIC_N_STAGES
#undef CIC_SHIFT
#undef cic_data_t
#undef cic_accum_t
#undef cic_interp_insert_n_copies
#undef cic_interp_integ
#undef cic_interp_comb