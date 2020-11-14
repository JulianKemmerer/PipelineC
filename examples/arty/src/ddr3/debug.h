#pragma once
// Project specific debug info to be included in hardware and software

typedef enum mem_test_state_t
{
  WAIT_RESET,
  WRITES,
  READ_REQ,
  READ_RESP,
  FAILED
}mem_test_state_t;

// Debug time domain samples capture
#define DEBUG_SAMPLES 32
typedef struct app_debug_t
{
  mem_test_state_t state[DEBUG_SAMPLES];
  uint32_t test_addr[DEBUG_SAMPLES];
  uint8_t test_data[DEBUG_SAMPLES];
}app_debug_t;
