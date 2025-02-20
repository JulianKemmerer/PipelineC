#pragma once
// Hardware and software shared definition of some user debug probes

// use pattern of naming _t,_print or manually
// #define probe0_print
// #define probe0_t

// The user type of registers to transfer
#define PAYLOAD_DEBUG_SAMPLES 4
typedef struct payload_debug_t{
  uint8_t tdata[PAYLOAD_DEBUG_SAMPLES];
  uint8_t tlast[PAYLOAD_DEBUG_SAMPLES];
}payload_debug_t;
// And what to do with the bytes in software
void payload_debug_print(payload_debug_t p){
  // See plot_probes.py helper script for text csv format
  printf("payload_debug: ");
  printf("tdata,tlast\n");
  for(int i=0; i<PAYLOAD_DEBUG_SAMPLES; i+=1) \
  {
    printf("%u,", p.tdata[i]);
    printf("%u\n", p.tlast[i]);
  }
}
// With generated helper funcs in headers
#ifdef __PIPELINEC__
#include "payload_debug_t_bytes_t.h"
#else
#include "type_bytes_t.h/payload_debug_t_bytes_t.h/payload_debug_t_bytes.h"
#endif


typedef struct mac_debug_t{
  uint32_t mac_lsb;
  uint16_t mac_msb;
}mac_debug_t;
void mac_debug_print(mac_debug_t dbg){
  printf("mac_msb mac_lsb 0x%04x%08x\n", dbg.mac_msb, dbg.mac_lsb);
}
#ifdef __PIPELINEC__
#include "mac_debug_t_bytes_t.h"
#else
#include "type_bytes_t.h/mac_debug_t_bytes_t.h/mac_debug_t_bytes.h"
#endif
