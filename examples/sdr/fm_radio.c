// See README.md for info on this design

#pragma PART "xc7a200tffg1156-2"
#include "intN_t.h"
#include "uintN_t.h"

// Building blocks for design in header
#include "fm_radio.h"

// Declare debug ports as secondary output channel
DECL_OUTPUT_REG(uint32_t, debug_data)
DECL_OUTPUT_REG(uint1_t, debug_data_valid)

// The datapath to be pipelined to meet the clock rate
// One sample per clock (maximum), ex. 125MHz = 125MSPS
//#pragma MAIN_MHZ fm_radio_datapath 125.0 // Datapath can be synthesized alone
stream(int16_t) fm_radio_datapath(stream(ci16_t) in_sample){
  // FIR+decimate to reduce sample rate down to ~300KSPS, 3 stages
  in_sample = iq_decim_5x(in_sample);
  in_sample = iq_decim_10x(in_sample);
  in_sample = iq_decim_10x(in_sample);

  // AGC after decim
  in_sample = iq_agc_hack(in_sample);
  
  // Connect debug output to be after decim, before demod
  debug_data = uint16_uint16(in_sample.data.imag, in_sample.data.real); // Concat
  debug_data_valid = in_sample.valid;

  // FM demodulation
  stream(int16_t) out_sample = fm_demodulate(in_sample);

  // Down sample to audio sample rate with fixed ratio
  // (N times interpolation/M times decimation) resampler
  //  Interpolation:
  out_sample = slow_interp_24x(out_sample);
  //  Decimation: 3 stages
  //    Last decimation stage is configured with extra audio low pass 15Khz
  out_sample = decim_5x(out_sample);
  out_sample = decim_5x(out_sample);
  out_sample = decim_5x_audio(out_sample);

  // FM deemphasis of audio samples
  out_sample = deemphasis(out_sample);

  // AGC on final output
  out_sample = agc_hack(out_sample);

  return out_sample;
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
u32_stream_t two_sample_buffer(stream(int16_t) in_sample){
  static stream(int16_t) samples[2];
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
DECL_INPUT_REG(int16_t, i_data)
DECL_INPUT_REG(int16_t, q_data)
DECL_INPUT_REG(uint1_t, iq_valid)
DECL_OUTPUT_REG(uint32_t, audio_samples_data)
DECL_OUTPUT_REG(uint1_t, audio_samples_valid)
#pragma MAIN_MHZ sdr_wrapper 125.0
// Meet timing by a larger margin in synthesis to aid place and route
#pragma MAIN_SYN_MHZ sdr_wrapper 147.0
void sdr_wrapper(){
  stream(ci16_t) in_sample = {
    .data = {.real = i_data, .imag = q_data}, 
    .valid = iq_valid
  };
  stream(int16_t) out_sample = fm_radio_datapath(in_sample);
  // Deserializer to 2 samples wide output
  u32_stream_t out_stream = two_sample_buffer(out_sample);
  audio_samples_data = out_stream.data;
  audio_samples_valid = out_stream.valid;
}