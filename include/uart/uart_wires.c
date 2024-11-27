#pragma once
#include "compiler.h"

// Separate wires and MAINs so can be different clock domains

// TODO CDC bit on inputs included?

#ifdef UART_TX_OUT_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, UART_TX_OUT_WIRE, uart_tx)
#else
DECL_OUTPUT(uint1_t, uart_tx)
#endif

#ifdef UART_RX_IN_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, uart_rx, UART_RX_IN_WIRE)
#else
DECL_INPUT(uint1_t, uart_rx)
#endif