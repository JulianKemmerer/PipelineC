#pragma once
// Hardware and software shared definition of some user debug probes

// use pattern of naming _t,_print or manually
// #define probe0_print
// #define probe0_t

// The user type of registers to transfer
#define PAYLOAD_DEBUG_SAMPLES 4
typedef struct axis_frame_samples_t{
  uint8_t tdata[PAYLOAD_DEBUG_SAMPLES];
  uint8_t tlast[PAYLOAD_DEBUG_SAMPLES];
}axis_frame_samples_t;
typedef struct payload_debug_t
{
  axis_frame_samples_t frame[2];
}payload_debug_t;
// And what to do with the bytes in software
void payload_debug_print(payload_debug_t p){
  // See plot_probes.py helper script for text csv format
  printf("payload_debug: ");
  printf("tdata,tlast\n");
  for(int f = 0; f < 2; f++){
    printf("frame %d\n", f);
    for(int i=0; i<PAYLOAD_DEBUG_SAMPLES; i+=1)
    {
      printf("0x%x,", p.frame[f].tdata[i]);
      printf("0x%x\n", p.frame[f].tlast[i]);
    }
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

typedef struct u32_debug_t{
  uint32_t u32[3];
}u32_debug_t;
void u32_debug_print(u32_debug_t dbg){
  for(int i=0; i<3; i+=1){
    printf("u32[%d] 0x%08x = %d\n", i, dbg.u32[i], dbg.u32[i]);
  }
}
#ifdef __PIPELINEC__
#include "u32_debug_t_bytes_t.h"
#else
#include "type_bytes_t.h/u32_debug_t_bytes_t.h/u32_debug_t_bytes.h"
#endif

#include "examples/net/work.h"
typedef struct work_out_dbg_t{
  work_outputs_t data;
}work_out_dbg_t;
void work_out_dbg_print(work_out_dbg_t dbg){
  int i, j; 
  for (i = 0; i < DIM; i++) 
  { 
      for (j = 0; j < DIM; j++) 
      { 
        printf("work_out_dbg [%d][%d] 0x%x\n", i, j, dbg.data.result[i][j]);
      }
  }
}
#ifdef __PIPELINEC__
#include "work_out_dbg_t_bytes_t.h"
#else
#include "type_bytes_t.h/work_out_dbg_t_bytes_t.h/work_out_dbg_t_bytes.h"
#endif

typedef struct work_in_dbg_t{
  work_inputs_t data;
}work_in_dbg_t;
void work_in_dbg_print(work_in_dbg_t dbg){
  int i, j; 
  for (i = 0; i < DIM; i++) 
  { 
      for (j = 0; j < DIM; j++) 
      { 
        printf("work_in_dbg mat0 [%d][%d] 0x%x\n", i, j, dbg.data.matrix0[i][j]);
        printf("work_in_dbg mat1 [%d][%d] 0x%x\n", i, j, dbg.data.matrix1[i][j]);
      }
  }
}
#ifdef __PIPELINEC__
#include "work_in_dbg_t_bytes_t.h"
#else
#include "type_bytes_t.h/work_in_dbg_t_bytes_t.h/work_in_dbg_t_bytes.h"
#endif
