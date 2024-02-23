// See README.md for info on this design

#pragma PART "xc7a200tffg1156-2"
#include "intN_t.h"
#include "uintN_t.h"

// Building blocks for design in header
#include "fm_radio.h"

// The datapath to be pipelined to meet the clock rate
// One sample per clock (maximum), ex. 125MHz = 125MSPS
//#pragma MAIN_MHZ fm_radio_datapath 125.0
i16_stream_t fm_radio_datapath(ci16_stream_t in_sample){
  // First FIR+decimate to reduce frontend radio sample rate down to ~300KSPS
  //  Stage 0
  //    I
  decim_5x_in_t I_decim_5x_in = {.data=in_sample.data.real, .valid=in_sample.valid};
  decim_5x_out_t I_decim_5x_out = decim_5x(I_decim_5x_in);
  //    Q
  decim_5x_in_t Q_decim_5x_in = {.data=in_sample.data.imag, .valid=in_sample.valid};
  decim_5x_out_t Q_decim_5x_out = decim_5x(Q_decim_5x_in);
  //  Stage 1
  //    I
  decim_10x_in_t I_decim_10x_in = {.data=I_decim_5x_out.data, .valid=I_decim_5x_out.valid};
  decim_10x_out_t I_decim_10x_out = decim_10x(I_decim_10x_in);
  //    Q
  decim_10x_in_t Q_decim_10x_in = {.data=Q_decim_5x_out.data, .valid=Q_decim_5x_out.valid};
  decim_10x_out_t Q_decim_10x_out = decim_10x(Q_decim_10x_in);
  //  Stage 2 (same decim func as stage 1)
  //    I
  decim_10x_in_t I_decim_10x_in = {.data=I_decim_10x_out.data, .valid=I_decim_10x_out.valid};
  decim_10x_out_t I_radio_decim = decim_10x(I_decim_10x_in);
  //    Q
  decim_10x_in_t Q_decim_10x_in = {.data=Q_decim_10x_out.data, .valid=Q_decim_10x_out.valid};
  decim_10x_out_t Q_radio_decim = decim_10x(Q_decim_10x_in);

  // FM demodulation
  ci16_stream_t fm_demod_in = {
    .data = {.real=I_radio_decim.data, .imag=Q_radio_decim.data},
    .valid = I_radio_decim.valid & Q_radio_decim.valid
  };
  i16_stream_t demod_raw = fm_demodulate(fm_demod_in);

  // Down sample to audio sample rate with fixed ratio
  // (N times interpolation/M times decimation) resampler
  //  Interpolation:
  interp_24x_in_t audio_interp_in = {.data=demod_raw.data, .valid=demod_raw.valid};
  interp_24x_out_t audio_interp_out = interp_24x(audio_interp_in);
  //  Decimation:
  decim_5x_in_t audio_decim_in = {.data=audio_interp_out.data, .valid=audio_interp_out.valid};
  decim_5x_out_t audio_decim_out = decim_5x(audio_decim_in);
  //
  decim_5x_in_t audio_decim_in = {.data=audio_decim_out.data, .valid=audio_decim_out.valid};
  decim_5x_out_t audio_decim_out = decim_5x(audio_decim_in);
  //
  decim_5x_in_t audio_decim_in = {.data=audio_decim_out.data, .valid=audio_decim_out.valid};
  decim_5x_out_t audio_decim_out = decim_5x(audio_decim_in);

  // SKIPPED FOR NOW // FM deemphasis of audio samples
  i16_stream_t deemph_in = {.data=audio_decim_out.data, .valid=audio_decim_out.valid};
  // SKIPPED FOR NOW i16_stream_t deemph_out = deemphasis_wfm(deemph_in);
  return deemph_in;
}

// Wrap the primary fm_radio_datapath for test SDR platform:
//  Is SystemVerilog design that does NOT support VHDL record ports:
//    So use manually declared top level input and output ports that arent structs
//  Expected two i16 values as u32 output per cycle
//    So also needs extra output buffer
#include "compiler.h"
#include "arrays.h"
typedef struct u32_stream_t{
  uint32_t data;
  uint1_t valid;
} u32_stream_t;
u32_stream_t two_sample_buffer(i16_stream_t in_sample){
  static i16_stream_t samples[2];
  if(in_sample.valid){
    ARRAY_1SHIFT_INTO_TOP(samples, 2, in_sample)
  }
  // Form output of two valid samples
  u32_stream_t rv;
  rv.data = uint16_uint16(samples[1].data, samples[0].data); // Concat
  rv.valid = samples[0].valid & samples[1].valid;
  // Once sent, clear buffer
  if(rv.valid){
    samples[0].valid = 0;
    samples[1].valid = 0;
  }
  return rv;
}
DECL_INPUT(int16_t, i_data)
DECL_INPUT(int16_t, q_data)
DECL_INPUT(uint1_t, iq_valid)
DECL_OUTPUT(uint32_t, audio_samples_data)
DECL_OUTPUT(uint1_t, audio_samples_valid)
#pragma MAIN_MHZ sdr_wrapper 125.0
void sdr_wrapper(){
  ci16_stream_t in_sample = {
    .data = {.real = i_data, .imag = q_data}, 
    .valid = iq_valid
  };
  i16_stream_t out_sample = fm_radio_datapath(in_sample);  
  /* TEMP counter test
  uint32_t RATE_COUNT = 2604; //(125e6 / 48e3)
  static uint32_t rate_counter;
  static i16_stream_t out_sample = {.data = -32768, .valid = 0};
  out_sample.valid = 0;
  rate_counter += 1;
  if(rate_counter==RATE_COUNT){
    out_sample.valid = 1;
    if(out_sample.data==-1){
      out_sample.data = -32768;
    }else{
      out_sample.data += 1;
    }    
    rate_counter = 0;
  }*/
  // Deserializer to 2 samples wide output
  u32_stream_t out_stream = two_sample_buffer(out_sample);
  audio_samples_data = out_stream.data;
  audio_samples_valid = out_stream.valid;
}