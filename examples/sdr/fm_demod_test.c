// isolated instance of fm_demodulate for testing

#pragma PART "xc7a100tcsg324-1"

#include "intN_t.h"
#include "uintN_t.h"

// Building blocks for design in header
#include "fm_radio.h"

// The datapath to be pipelined to meet the clock rate
// One sample per clock (maximum), ex. 125MHz = 125MSPS
#pragma MAIN_MHZ fm_radio_datapath 125.0
i16_stream_t fm_radio_datapath(ci16_stream_t in_sample){
  // FM demodulation
  ci16_stream_t fm_demod_in = {
    .data = {.real=in_sample.data.real, .imag=in_sample.data.real},
    .valid = in_sample.valid
  };
  i16_stream_t demod_raw = fm_demodulate(fm_demod_in);

  return demod_raw;
}