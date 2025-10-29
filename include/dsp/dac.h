// Delta Sigma Converters, thanks discord user @Darkknight512 for the help and the code!
#include "intN_t.h"
#include "uintN_t.h"

const int24_t i16max = (1 << 15);

typedef struct bp_state_t
{
  int24_t stage_0;
  int24_t stage_1;
  uint1_t last_bit;
}bp_state_t;


bp_state_t sigma_delta_bp_math(int16_t input, bp_state_t state){
  int24_t dac_in_extended = (int24_t)input;

  bp_state_t new_state = state;

  int24_t ressonator = state.stage_1;
  if (state.last_bit){
    new_state.stage_1 = (int24_t)(state.stage_0 + (int24_t)(dac_in_extended - i16max));
  } else {
    new_state.stage_1 = (int24_t)(state.stage_0 + (int24_t)(dac_in_extended + i16max));
  }
  new_state.stage_0 = -ressonator;
  int24_t stage0 = new_state.stage_0;
  new_state.last_bit = !stage0(23);
  return new_state;
}

uint1_t sigma_delta_bandpass_dac(int16_t dac_in){
  static bp_state_t state = {.stage_0 = 0, .stage_1 = 0, .last_bit = 1};

  bp_state_t newstate = sigma_delta_bp_math(dac_in, state);
  state = newstate;
  return newstate.last_bit;
}

uint1_t sigma_delta_bandpass_dac_we(int16_t dac_in, uint1_t enable){
  static bp_state_t state = {.stage_0 = 0, .stage_1 = 0, .last_bit = 1};

  if(enable){
    state = sigma_delta_bp_math(dac_in, state);
  }
  return state.last_bit;
}

typedef struct lp_state_t
{
  int24_t accum_0;
  uint1_t last_bit;
}lp_state_t;

lp_state_t sigma_delta_lp_math(int16_t input, lp_state_t state){
  int24_t dac_in_extended = (int24_t)input;

  lp_state_t new_state = state;

  if (state.last_bit){
    new_state.accum_0 = (int24_t)(state.accum_0 + (int24_t)(dac_in_extended - i16max));
  } else {
    new_state.accum_0 = (int24_t)(state.accum_0 + (int24_t)(dac_in_extended + i16max));
  }
  int24_t new_accum_0 = new_state.accum_0;
  new_state.last_bit = !new_accum_0(23);
  return new_state;
}

uint1_t sigma_delta_lowpass_dac(int16_t dac_in){
  //static vars
  static lp_state_t state = {.accum_0 = 0, .last_bit = 1};

  // math 
  lp_state_t new_state = sigma_delta_lp_math(dac_in, state);

  // update static & return
  state = new_state;
  return new_state.last_bit;
}


typedef struct lp_2nd_state_t
{
  int24_t accum_0;
  int32_t accum_1;
  uint1_t last_bit;
}lp_2nd_state_t;

lp_2nd_state_t sigma_delta_lp_2nd_ord_math(int16_t input, lp_2nd_state_t state){
  int24_t dac_in_extended = (int24_t)input;

  lp_2nd_state_t new_state = state;
  int24_t dac_in_ext_m16 = (int24_t)(dac_in_extended - i16max);
  int24_t dac_in_ext_p16 = (int24_t)(dac_in_extended + i16max);

  if (state.last_bit){
    int24_t integ0 = (int24_t)(state.accum_0 + dac_in_ext_m16);
    int32_t integ1 = (int32_t)(state.accum_1 + (int32_t)(integ0 - i16max));
    new_state.accum_0 = integ0;
    new_state.accum_1 = integ1;
  } else {
    int24_t integ0 = (int24_t)(state.accum_0 + dac_in_ext_p16);
    int32_t integ1 = (int32_t)(state.accum_1 + (int32_t)(integ0 + i16max));
    new_state.accum_0 = integ0;
    new_state.accum_1 = integ1;
  }
  int32_t new_accum_1 = new_state.accum_1;
  new_state.last_bit = !new_accum_1(31);
  return new_state;
}

uint1_t sigma_delta_lowpass_2nd_ord_dac(int16_t dac_in){
  //static vars
  static lp_2nd_state_t state = {.accum_0 = 0, .accum_1 = 0, .last_bit = 1};

  // math 
  lp_2nd_state_t new_state = sigma_delta_lp_2nd_ord_math(dac_in, state);

  // update static & return
  state = new_state;
  return new_state.last_bit;
}

uint1_t sigma_delta_lowpass_2nd_ord_dac_we(int16_t dac_in, uint1_t enable){
  //static vars
  static lp_2nd_state_t state = {.accum_0 = 0, .accum_1 = 0, .last_bit = 1};

  // math 
  if(enable){
    state = sigma_delta_lp_2nd_ord_math(dac_in, state);
  }
  return state.last_bit;
}


typedef struct lp_3rd_state_t
{
  int24_t accum_0;
  int32_t accum_1;
  int40_t accum_2;
  uint1_t last_bit;
}lp_3rd_state_t;

lp_3rd_state_t sigma_delta_lp_3rd_ord_math(int16_t input, lp_3rd_state_t state){
  int24_t dac_in_extended = (int24_t)input;

  lp_3rd_state_t new_state = state;

  if (state.last_bit){
    int24_t integ0 = (int24_t)(state.accum_0 + (int24_t)(dac_in_extended - i16max));
    int32_t integ1 = (int32_t)(state.accum_1 + (int32_t)(integ0 - i16max));
    int40_t integ2 = (int40_t)(state.accum_2 + (int40_t)(integ1 - i16max));
    new_state.accum_0 = integ0;
    new_state.accum_1 = integ1;
    new_state.accum_2 = integ2;
  } else {
    int24_t integ0 = (int24_t)(state.accum_0 + (int24_t)(dac_in_extended + i16max));
    int32_t integ1 = (int32_t)(state.accum_1 + (int32_t)(integ0 + i16max));
    int40_t integ2 = (int40_t)(state.accum_2 + (int40_t)(integ1 + i16max));
    new_state.accum_0 = integ0;
    new_state.accum_1 = integ1;
    new_state.accum_2 = integ2;
  }
  int40_t new_accum_2 = new_state.accum_2;
  new_state.last_bit = !new_accum_2(39);
  return new_state;
}

uint1_t sigma_delta_lowpass_3rd_ord_dac(int16_t dac_in){
  //static vars
  static lp_3rd_state_t state = {.accum_0 = 0, .accum_1 = 0, .accum_2 = 0, .last_bit = 1};

  // math 
  lp_3rd_state_t new_state = sigma_delta_lp_3rd_ord_math(dac_in, state);

  // update static & return
  state = new_state;
  return new_state.last_bit;
}