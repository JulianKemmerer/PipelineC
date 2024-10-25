#pragma once
#include "fixed/q0_23.h"
#define SAMPLE_BITWIDTH 24
#define i2s_data_t q0_23_t
#define bits_to_i2s_data uint1_array24_le

// I2S stereo sample types
typedef struct i2s_samples_t
{
  i2s_data_t l_data;
  i2s_data_t r_data;
}i2s_samples_t;
DECL_STREAM_TYPE(i2s_samples_t)