// See README.md for info on this design

#pragma PART "xc7a100tcsg324-1"
#include "intN_t.h"
#include "uintN_t.h"

// int16_t w/ valid flag
typedef struct i16_stream_t{
  int16_t data;
  uint1_t valid;
} i16_stream_t;

// complex int16_t struct
typedef struct ci16_t{
  int16_t real;
  int16_t imag;
} ci16_t;

// complex int16_t struct w/ valid flag
typedef struct ci16_stream_t{
  ci16_t data;
  uint1_t valid;
} ci16_stream_t;

// Primary decimation to bring sample rate down from 
// radio front end to single FM radio channel ~300KSPS
// Decimation ratio is large and so is split into 3 decimation stages
// TODO ADJUST FIR PARAMS, taps etc
// Stage 0
#define fir_decim_name radio_decim0
#define FIR_DECIM_N_TAPS 128
#define FIR_DECIM_LOG2_N_TAPS 7
#define FIR_DECIM_FACTOR 5
#define fir_decim_data_t int16_t
#define fir_decim_coeff_t int16_t
#define fir_decim_out_t int16_t
#define FIR_DECIM_COEFFS {2, 6, 9, 7, 0, -12, -24, -29, -22, 0, 31, 59, 69, 49, 0, -65, -121, -138, -96, 0, 123, 223, 249, 171, 0, -211, -378, -417, -284, 0, 342, 606, 663, 447, 0, -532, -937, -1019, -684, 0, 807, 1418, 1539, 1032, 0, -1218, -2144, -2336, -1575, 0, 1888, 3361, 3713, 2549, 0, -3213, -5924, -6848, -4985, 0, 7588, 16449, 24754, 30647, 32760, 30597, 24674, 16370, 7539, 0, -4937, -6771, -5848, -3166, 0, 2503, 3641, 3290, 1845, 0, -1534, -2271, -2081, -1180, 0, 996, 1482, 1363, 774, 0, -654, -972, -892, -505, 0, 423, 625, 570, 321, 0, -265, -388, -351, -195, 0, 157, 228, 203, 111, 0, -87, -124, -108, -58, 0, 43, 60, 51, 26, 0, -18, -24, -19, -9, 0, 5, 6, 4}
#include "dsp/fir_decim.h"
#define radio_decim0_out_t fir_decim_out_data_stream_type(radio_decim0)
#define radio_decim0_in_t fir_decim_in_data_stream_type(radio_decim0)
// Stage 1
#define fir_decim_name radio_decim1
#define FIR_DECIM_N_TAPS 128
#define FIR_DECIM_LOG2_N_TAPS 7
#define FIR_DECIM_FACTOR 10
#define fir_decim_data_t int16_t
#define fir_decim_coeff_t int16_t
#define fir_decim_out_t int16_t
#define FIR_DECIM_COEFFS {2, 6, 9, 7, 0, -12, -24, -29, -22, 0, 31, 59, 69, 49, 0, -65, -121, -138, -96, 0, 123, 223, 249, 171, 0, -211, -378, -417, -284, 0, 342, 606, 663, 447, 0, -532, -937, -1019, -684, 0, 807, 1418, 1539, 1032, 0, -1218, -2144, -2336, -1575, 0, 1888, 3361, 3713, 2549, 0, -3213, -5924, -6848, -4985, 0, 7588, 16449, 24754, 30647, 32760, 30597, 24674, 16370, 7539, 0, -4937, -6771, -5848, -3166, 0, 2503, 3641, 3290, 1845, 0, -1534, -2271, -2081, -1180, 0, 996, 1482, 1363, 774, 0, -654, -972, -892, -505, 0, 423, 625, 570, 321, 0, -265, -388, -351, -195, 0, 157, 228, 203, 111, 0, -87, -124, -108, -58, 0, 43, 60, 51, 26, 0, -18, -24, -19, -9, 0, 5, 6, 4}
#include "dsp/fir_decim.h"
#define radio_decim1_out_t fir_decim_out_data_stream_type(radio_decim1)
#define radio_decim1_in_t fir_decim_in_data_stream_type(radio_decim1)
// Stage 2
#define fir_decim_name radio_decim2
#define FIR_DECIM_N_TAPS 128
#define FIR_DECIM_LOG2_N_TAPS 7
#define FIR_DECIM_FACTOR 10
#define fir_decim_data_t int16_t
#define fir_decim_coeff_t int16_t
#define fir_decim_out_t int16_t
#define FIR_DECIM_COEFFS {2, 6, 9, 7, 0, -12, -24, -29, -22, 0, 31, 59, 69, 49, 0, -65, -121, -138, -96, 0, 123, 223, 249, 171, 0, -211, -378, -417, -284, 0, 342, 606, 663, 447, 0, -532, -937, -1019, -684, 0, 807, 1418, 1539, 1032, 0, -1218, -2144, -2336, -1575, 0, 1888, 3361, 3713, 2549, 0, -3213, -5924, -6848, -4985, 0, 7588, 16449, 24754, 30647, 32760, 30597, 24674, 16370, 7539, 0, -4937, -6771, -5848, -3166, 0, 2503, 3641, 3290, 1845, 0, -1534, -2271, -2081, -1180, 0, 996, 1482, 1363, 774, 0, -654, -972, -892, -505, 0, 423, 625, 570, 321, 0, -265, -388, -351, -195, 0, 157, 228, 203, 111, 0, -87, -124, -108, -58, 0, 43, 60, 51, 26, 0, -18, -24, -19, -9, 0, 5, 6, 4}
#include "dsp/fir_decim.h"
#define radio_decim2_out_t fir_decim_out_data_stream_type(radio_decim2)
#define radio_decim2_in_t fir_decim_in_data_stream_type(radio_decim2)

// FM demodulation using differentiator
i16_stream_t fm_demodulate(ci16_stream_t iq_sample){
  static ci16_t iq_history[3];
  static ci16_t iq_dot;
  static int16_t output;
  if(iq_sample.valid){
    // scale input
    iq_history[0].real = iq_sample.data.real >> 11;
    iq_history[0].imag = iq_sample.data.imag >> 11;

    // Calculate derivative
    iq_dot.real = iq_history[0].real - iq_history[2].real;
    iq_dot.imag = iq_history[0].imag - iq_history[2].imag;

    // Calculate output (I[1] * Q') - (Q[1] * I')
    output = (iq_history[1].real * iq_dot.imag);
    output -= (iq_history[1].imag * iq_dot.real);

    // update history & return
    iq_history[1] = iq_history[0];
    iq_history[2] = iq_history[1];
  }
  i16_stream_t output_stream = {.data = output, .valid = iq_sample.valid};
  return output_stream;
}

// Interpolation Part of (24/125) sample rate change
// TODO ADJUST FIR PARAMS, taps etc
#define fir_interp_name audio_interp_fir
#define FIR_INTERP_N_TAPS 4
#define FIR_INTERP_LOG2_N_TAPS 2
#define FIR_INTERP_FACTOR 24 
#define fir_interp_data_t int16_t
#define fir_interp_coeff_t int16_t
#define fir_interp_out_t int16_t
#define FIR_INTERP_COEFFS {2, 6, 9, 7}
#include "dsp/fir_interp.h"
#define audio_interp_fir_out_t fir_interp_out_data_stream_type(audio_interp_fir)
#define audio_interp_fir_in_t fir_interp_in_data_stream_type(audio_interp_fir)

// Decimation Part of (24/125) sample rate change
// TODO ADJUST FIR PARAMS, taps etc
#define fir_decim_name audio_decim_fir
#define FIR_DECIM_N_TAPS 4
#define FIR_DECIM_LOG2_N_TAPS 2
#define FIR_DECIM_FACTOR 125 
#define fir_decim_data_t int16_t
#define fir_decim_coeff_t int16_t
#define fir_decim_out_t int16_t
#define FIR_DECIM_COEFFS {2, 6, 9, 7}
#include "dsp/fir_decim.h"
#define audio_decim_fir_out_t fir_decim_out_data_stream_type(audio_decim_fir)
#define audio_decim_fir_in_t fir_decim_in_data_stream_type(audio_decim_fir)

// Deemphasis
// 75e-6 Tau (USA)
// 50e-6 Tau (EU)
#define USA
#if defined(USA)
#define fm_alpha (int16_t)(7123)
#else
#define fm_alpha (int16_t)(9637)
#endif // TAU
i16_stream_t deemphasis_wfm(i16_stream_t input){
  /*
      Sample rate: 48000Hz
      typical time constant (tau) values:
      WFM transmission in USA: 75 us -> tau = 75e-6
      WFM transmission in EU:  50 us -> tau = 50e-6
      More info at: http://www.cliftonlaboratories.com/fm_receivers_and_de-emphasis.htm
      Simulate in octave: tau=75e-6; dt=1/48000; alpha = dt/(tau+dt); freqz([alpha],[1 -(1-alpha)])
  */
  // variables
  static int16_t last_output = 0;
  static int16_t output = 0;
  if(input.valid){
    // process
    output = (fm_alpha*input.data) >> 15;
    output += ((32767-fm_alpha)*last_output) >> 15;

    // save last & return
    last_output = output;
  }
  i16_stream_t output_stream = {.data = output, .valid = input.valid};
  return output_stream;
}

// The datapath to be pipelined to meet the clock rate
// One sample per clock (maximum), ex. 125MHz = 125MSPS
#pragma MAIN_MHZ fm_radio_datapath 125.0
i16_stream_t fm_radio_datapath(ci16_stream_t in_sample){
  // First FIR+decimate to reduce frontend radio sample rate down to ~300KSPS
  //  Stage 0
  //    I
  radio_decim0_in_t I_radio_decim0_in = {.data=in_sample.data.real, .valid=in_sample.valid};
  radio_decim0_out_t I_radio_decim0_out = radio_decim0(I_radio_decim0_in);
  //    Q
  radio_decim0_in_t Q_radio_decim0_in = {.data=in_sample.data.imag, .valid=in_sample.valid};
  radio_decim0_out_t Q_radio_decim0_out = radio_decim0(Q_radio_decim0_in);
  //  Stage 1
  //    I
  radio_decim1_in_t I_radio_decim1_in = {.data=I_radio_decim0_out.data, .valid=I_radio_decim0_out.valid};
  radio_decim1_out_t I_radio_decim1_out = radio_decim1(I_radio_decim1_in);
  //    Q
  radio_decim1_in_t Q_radio_decim1_in = {.data=Q_radio_decim0_out.data, .valid=Q_radio_decim0_out.valid};
  radio_decim1_out_t Q_radio_decim1_out = radio_decim1(Q_radio_decim1_in);
  //  Stage 2
  //    I
  radio_decim2_in_t I_radio_decim2_in = {.data=I_radio_decim1_out.data, .valid=I_radio_decim1_out.valid};
  radio_decim2_out_t I_radio_decim2_out = radio_decim2(I_radio_decim2_in);
  //    Q
  radio_decim2_in_t Q_radio_decim2_in = {.data=Q_radio_decim1_out.data, .valid=Q_radio_decim1_out.valid};
  radio_decim2_out_t Q_radio_decim2_out = radio_decim2(Q_radio_decim2_in);

  // FM demodulation
  ci16_stream_t fm_demod_in = {
    .data = {.real=I_radio_decim2_out.data, .imag=Q_radio_decim2_out.data},
    .valid = I_radio_decim2_out.valid & Q_radio_decim2_out.valid
  };
  i16_stream_t demod_raw = fm_demodulate(fm_demod_in);

  // Down sample to audio sample rate with fixed ratio
  // (N times interpolation/M times decimation) resampler
  // applies FIR low pass for ~15KHz? band
  audio_interp_fir_in_t audio_interp_in = {.data=demod_raw.data, .valid=demod_raw.valid};
  audio_interp_fir_out_t audio_interp_out = audio_interp_fir(audio_interp_in);
  audio_decim_fir_in_t audio_decim_in = {.data=audio_interp_out.data, .valid=audio_interp_out.valid};
  audio_decim_fir_out_t audio_decim_out = audio_decim_fir(audio_decim_in);

  // FM deemphasis of audio samples
  i16_stream_t deemph_in = {.data=audio_decim_out.data, .valid=audio_decim_out.valid};
  i16_stream_t deemph_out = deemphasis_wfm(deemph_in);

  return deemph_out;
}
