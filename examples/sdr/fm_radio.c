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

// Declare decimation FIR modules to use
// radio front end to single FM radio channel ~300KSPS
// 5x Decim
#define fir_decim_name decim_5x
#define FIR_DECIM_N_TAPS 49
#define FIR_DECIM_LOG2_N_TAPS 6
#define FIR_DECIM_FACTOR 5
#define fir_decim_data_t int16_t
#define fir_decim_coeff_t int16_t
#define fir_decim_accum_t int38_t // data_width + coeff_width + log2(taps#)
#define fir_decim_out_t int16_t
#define FIR_DECIM_COEFFS { \
  -165, \
  -284, \
  -219, \
  -303, \
  -190, \
  -102, \
  98,   \
  268,  \
  430,  \
  482,  \
  420,  \
  207,  \
  -117, \
  -498, \
  -835, \
  -1022,\
  -957, \
  -576, \
  135,  \
  1122, \
  2272, \
  3429, \
  4419, \
  5086, \
  5321, \
  5086, \
  4419, \
  3429, \
  2272, \
  1122, \
  135,  \
  -576, \
  -957, \
  -1022,\
  -835, \
  -498, \
  -117, \
  207,  \
  420,  \
  482,  \
  430,  \
  268,  \
  98,   \
  -102, \
  -190, \
  -303, \
  -219, \
  -284, \
  -165  \
}            
#include "dsp/fir_decim.h"
#define decim_5x_out_t fir_decim_out_data_stream_type(decim_5x)
#define decim_5x_in_t fir_decim_in_data_stream_type(decim_5x)
// 10x decim
#define fir_decim_name decim_10x
#define FIR_DECIM_N_TAPS 95
#define FIR_DECIM_LOG2_N_TAPS 7
#define FIR_DECIM_FACTOR 10
#define fir_decim_data_t int16_t
#define fir_decim_coeff_t int16_t
#define fir_decim_accum_t int39_t // data_width + coeff_width + log2(taps#)
#define fir_decim_out_t int16_t
#define FIR_DECIM_COEFFS { \
  -199,\
  -90, \
  -103,\
  -113,\
  -116,\
  -113,\
  -101,\
  -82, \
  -54, \
  -19, \
  22,  \
  68,  \
  115, \
  161, \
  202, \
  235, \
  257, \
  265, \
  257, \
  231, \
  187, \
  126, \
  50,  \
  -37, \
  -132,\
  -227,\
  -318,\
  -396,\
  -456,\
  -490,\
  -493,\
  -459,\
  -385,\
  -269,\
  -111,\
  86,  \
  318, \
  579, \
  860, \
  1154,\
  1448,\
  1732,\
  1995,\
  2227,\
  2418,\
  2560,\
  2648,\
  2678,\
  2648,\
  2560,\
  2418,\
  2227,\
  1995,\
  1732,\
  1448,\
  1154,\
  860, \
  579, \
  318, \
  86,  \
  -111,\
  -269,\
  -385,\
  -459,\
  -493,\
  -490,\
  -456,\
  -396,\
  -318,\
  -227,\
  -132,\
  -37, \
  50,  \
  126, \
  187, \
  231, \
  257, \
  265, \
  257, \
  235, \
  202, \
  161, \
  115, \
  68,  \
  22,  \
  -19, \
  -54, \
  -82, \
  -101,\
  -113,\
  -116,\
  -113,\
  -103,\
  -90, \
  -199 \
}
#include "dsp/fir_decim.h"
#define decim_10x_out_t fir_decim_out_data_stream_type(decim_10x)
#define decim_10x_in_t fir_decim_in_data_stream_type(decim_10x)

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
/* you need a 125 kHz cutoff or lower 
The zero insertion causes aliasing
You essentially get 23 aliases 
You then have to remove them*/
#define fir_interp_name interp_24x
#define FIR_INTERP_N_TAPS 227
#define FIR_INTERP_LOG2_N_TAPS 8
#define FIR_INTERP_FACTOR 24 
#define fir_interp_data_t int16_t
#define fir_interp_coeff_t int16_t
#define fir_interp_accum_t int40_t // data_width + coeff_width + log2(taps#)
#define fir_interp_out_t int16_t
#define FIR_INTERP_COEFFS { \
  -173, \
  -34,  \
  -36,  \
  -39,  \
  -41,  \
  -44,  \
  -45,  \
  -47,  \
  -48,  \
  -49,  \
  -49,  \
  -49,  \
  -48,  \
  -46,  \
  -44,  \
  -42,  \
  -38,  \
  -35,  \
  -30,  \
  -25,  \
  -20,  \
  -13,  \
  -7,   \
  0,    \
  7,    \
  15,   \
  23,   \
  31,   \
  39,   \
  48,   \
  56,   \
  64,   \
  71,   \
  78,   \
  85,   \
  91,   \
  97,   \
  101,  \
  105,  \
  108,  \
  110,  \
  110,  \
  110,  \
  108,  \
  105,  \
  100,  \
  95,   \
  88,   \
  79,   \
  70,   \
  59,   \
  47,   \
  34,   \
  20,   \
  6,    \
  -10,  \
  -26,  \
  -42,  \
  -59,  \
  -75,  \
  -92,  \
  -108, \
  -124, \
  -139, \
  -153, \
  -166, \
  -177, \
  -187, \
  -195, \
  -201, \
  -205, \
  -207, \
  -206, \
  -203, \
  -197, \
  -188, \
  -176, \
  -161, \
  -143, \
  -122, \
  -97,  \
  -70,  \
  -40,  \
  -8,   \
  28,   \
  66,   \
  107,  \
  150,  \
  194,  \
  241,  \
  289,  \
  338,  \
  389,  \
  440,  \
  491,  \
  542,  \
  593,  \
  643,  \
  693,  \
  741,  \
  787,  \
  831,  \
  873,  \
  913,  \
  949,  \
  983,  \
  1013, \
  1040, \
  1063, \
  1082, \
  1096, \
  1107, \
  1114, \
  1116, \
  1114, \
  1107, \
  1096, \
  1082, \
  1063, \
  1040, \
  1013, \
  983,  \
  949,  \
  913,  \
  873,  \
  831,  \
  787,  \
  741,  \
  693,  \
  643,  \
  593,  \
  542,  \
  491,  \
  440,  \
  389,  \
  338,  \
  289,  \
  241,  \
  194,  \
  150,  \
  107,  \
  66,   \
  28,   \
  -8,   \
  -40,  \
  -70,  \
  -97,  \
  -122, \
  -143, \
  -161, \
  -176, \
  -188, \
  -197, \
  -203, \
  -206, \
  -207, \
  -205, \
  -201, \
  -195, \
  -187, \
  -177, \
  -166, \
  -153, \
  -139, \
  -124, \
  -108, \
  -92,  \
  -75,  \
  -59,  \
  -42,  \
  -26,  \
  -10,  \
  6,    \
  20,   \
  34,   \
  47,   \
  59,   \
  70,   \
  79,   \
  88,   \
  95,   \
  100,  \
  105,  \
  108,  \
  110,  \
  110,  \
  110,  \
  108,  \
  105,  \
  101,  \
  97,   \
  91,   \
  85,   \
  78,   \
  71,   \
  64,   \
  56,   \
  48,   \
  39,   \
  31,   \
  23,   \
  15,   \
  7,    \
  0,    \
  -7,   \
  -13,  \
  -20,  \
  -25,  \
  -30,  \
  -35,  \
  -38,  \
  -42,  \
  -44,  \
  -46,  \
  -48,  \
  -49,  \
  -49,  \
  -49,  \
  -48,  \
  -47,  \
  -45,  \
  -44,  \
  -41,  \
  -39,  \
  -36,  \
  -34,  \
  -173  \
}
#include "dsp/fir_interp.h"
#define interp_24x_out_t fir_interp_out_data_stream_type(interp_24x)
#define interp_24x_in_t fir_interp_in_data_stream_type(interp_24x)

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

  // FM deemphasis of audio samples
  i16_stream_t deemph_in = {.data=audio_decim_out.data, .valid=audio_decim_out.valid};
  i16_stream_t deemph_out = deemphasis_wfm(deemph_in);

  return deemph_out;
}
