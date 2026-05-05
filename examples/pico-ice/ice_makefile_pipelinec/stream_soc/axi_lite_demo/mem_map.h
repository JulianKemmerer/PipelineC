#pragma once
#define AXIL_DEMO_NWORDS 4
typedef struct axil_demo_regs_t{
  uint8_t word_bytes[AXIL_DEMO_NWORDS][4];
}axil_demo_regs_t;
#ifdef __PIPELINEC__
#include "axil_demo_regs_t_bytes_t.h"
#endif