// See README.md for info on this design

#pragma PART "xc7a200tffg1156-2"
#include "intN_t.h"
#include "uintN_t.h"

// Building blocks for design in header
#include "fm_radio.h"

// The datapath to be pipelined to meet the clock rate
// One sample per clock (maximum), ex. 125MHz = 125MSPS
#pragma MAIN_MHZ fm_radio_datapath 125.0
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
