#pragma once
#include "compiler.h"

/*typedef struct i2s_to_app_t
{
  uint1_t rx_data;
}i2s_to_app_t;
typedef struct app_to_i2s_t
{
  uint1_t tx_lrck;
  uint1_t tx_sclk;
  uint1_t tx_data;
  uint1_t rx_lrck;
  uint1_t rx_sclk;
}app_to_i2s_t;*/

// Separate wires and MAINs so can be different clock domains

#ifdef I2S_TX_MCLK_WIRE
GLOBAL_OUT_WIRE_CONNECT(uint1_t, I2S_TX_MCLK_WIRE, i2s_tx_mclk)
#else
DECL_OUTPUT(uint1_t, i2s_tx_mclk)
#endif

#ifdef I2S_RX_MCLK_WIRE
GLOBAL_OUT_WIRE_CONNECT(uint1_t, I2S_RX_MCLK_WIRE, i2s_rx_mclk)
#else
DECL_OUTPUT(uint1_t, i2s_rx_mclk)
#endif

#ifdef I2S_RX_DATA_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, i2s_rx_data, I2S_RX_DATA_WIRE)
#else
DECL_INPUT_REG(uint1_t, i2s_rx_data)
#endif

#ifdef I2S_TX_LRCK_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, I2S_TX_LRCK_WIRE, i2s_tx_lrck)
#else
DECL_OUTPUT_REG(uint1_t, i2s_tx_lrck)
#endif

#ifdef I2S_TX_SCLK_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, I2S_TX_SCLK_WIRE, i2s_tx_sclk)
#else
DECL_OUTPUT_REG(uint1_t, i2s_tx_sclk)
#endif

#ifdef I2S_TX_DATA_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, I2S_TX_DATA_WIRE, i2s_tx_data)
#else
DECL_OUTPUT_REG(uint1_t, i2s_tx_data)
#endif

#ifdef I2S_RX_LRCK_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, I2S_RX_LRCK_WIRE, i2s_rx_lrck)
#else
DECL_OUTPUT_REG(uint1_t, i2s_rx_lrck)
#endif

#ifdef I2S_RX_SCLK_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, I2S_RX_SCLK_WIRE, i2s_rx_sclk)
#else
DECL_OUTPUT_REG(uint1_t, i2s_rx_sclk)
#endif
