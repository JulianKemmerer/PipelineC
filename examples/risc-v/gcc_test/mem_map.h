#pragma once

// Hardware memory address mappings for PipelineC and software C code

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#endif

#define MEM_MAP_BASE_ADDR 0x10000000

#define N_THREADS_PER_BARREL 5
#define N_BARRELS 1
#define NUM_THREADS 5
// Read: Thread ID, Write: output/stop/halt peripheral
#define THREAD_ID_RETURN_OUTPUT_ADDR (MEM_MAP_BASE_ADDR+0)
static volatile uint32_t* RETURN_OUTPUT = (uint32_t*)THREAD_ID_RETURN_OUTPUT_ADDR;
static volatile uint32_t* THREAD_ID = (uint32_t*)THREAD_ID_RETURN_OUTPUT_ADDR;

// LED
#define LED_ADDR (THREAD_ID_RETURN_OUTPUT_ADDR + sizeof(uint32_t))
static volatile uint32_t* LED = (uint32_t*)LED_ADDR;

// Re: memory mapped structs
//__attribute__((packed)) increases code size bringing in memcpy
// Not actually needed to pack for ~memory savings
// when memory mapped padding regs will optimize away if unused
// So manually add padding fields for 32b|4B alignment (otherwise need packed)
// (if not PipelineC built in to-from bytes functions won't work)

// // For now use separate input and output structs for accelerators
// // that have special input and output valid flags
// #include "gcc_test/gol/hw_config.h"

// Types that PipelineC and CPU share to talk to hardware ram RAM
#define riscv_valid_flag_t int32_t // TODO single bit packing
#define RISCV_RAM_NUM_BURST_WORDS 1
typedef struct riscv_ram_read_req_t
{
  uint32_t addr;
  uint32_t num_words;
  riscv_valid_flag_t valid;
}riscv_ram_read_req_t;
typedef struct riscv_ram_read_resp_t
{
  uint32_t data[RISCV_RAM_NUM_BURST_WORDS];
  uint32_t num_words;
  riscv_valid_flag_t valid;
}riscv_ram_read_resp_t;
typedef struct riscv_ram_write_req_t
{
  uint32_t addr;
  uint32_t data[RISCV_RAM_NUM_BURST_WORDS];
  uint32_t num_words;
  riscv_valid_flag_t valid;
}riscv_ram_write_req_t;
typedef struct riscv_ram_write_resp_t
{
  uint32_t num_words;
  riscv_valid_flag_t valid;
}riscv_ram_write_resp_t;

// Assumes valid is last bytes of type
#define ADDR_IS_VALID_FLAG(addr, ADDR, type_t)\
( (addr >= ((ADDR+sizeof(type_t))-sizeof(riscv_valid_flag_t))) & (addr < (ADDR+sizeof(type_t))) )

// To-from bytes conversion funcs
#ifdef __PIPELINEC__
#include "riscv_ram_read_req_t_bytes_t.h"
#include "riscv_ram_read_resp_t_bytes_t.h"
#include "riscv_ram_write_req_t_bytes_t.h"
#include "riscv_ram_write_resp_t_bytes_t.h"
#endif

#define RAM_WR_REQ_ADDR (LED_ADDR+sizeof(uint32_t))
static volatile riscv_ram_write_req_t* RAM_WR_REQ = (riscv_ram_write_req_t*)RAM_WR_REQ_ADDR;

#define RAM_WR_RESP_ADDR (RAM_WR_REQ_ADDR + sizeof(riscv_ram_write_req_t))
static volatile riscv_ram_write_resp_t* RAM_WR_RESP = (riscv_ram_write_resp_t*)RAM_WR_RESP_ADDR;

#define RAM_RD_REQ_ADDR (RAM_WR_RESP_ADDR + sizeof(riscv_ram_write_resp_t))
static volatile riscv_ram_read_req_t* RAM_RD_REQ = (riscv_ram_read_req_t*)RAM_RD_REQ_ADDR;

#define RAM_RD_RESP_ADDR (RAM_RD_REQ_ADDR + sizeof(riscv_ram_read_req_t))
static volatile riscv_ram_read_resp_t* RAM_RD_RESP = (riscv_ram_read_resp_t*)RAM_RD_RESP_ADDR;



// Multiple in flight versions:
static inline __attribute__((always_inline)) riscv_valid_flag_t try_start_ram_write(
  uint32_t addr, uint32_t* data, uint8_t num_words
){
  // If the request flag is valid from a previous req
  // then done now, couldnt start
  if(RAM_WR_REQ->valid){
    return 0;
  }
  // Start
  RAM_WR_REQ->addr = addr;
  RAM_WR_REQ->num_words = num_words;
  // TODO skip copy is data pointer if mmio regs already
  for(uint32_t i = 0; i < num_words; i++)
  {
    RAM_WR_REQ->data[i] = data[i];
  }
  RAM_WR_REQ->valid = 1;
  return 1;
}
static inline __attribute__((always_inline)) void start_ram_write(
  uint32_t addr, uint32_t* data, uint8_t num_words
){
  while(!try_start_ram_write(addr, data, num_words)){}
}

static inline __attribute__((always_inline)) riscv_valid_flag_t try_start_ram_read(
  uint32_t addr, uint32_t num_words
){
  // If the request flag is valid from a previous req
  // then done now, couldnt start
  if(RAM_RD_REQ->valid){
    return 0;
  }
  // Start
  RAM_RD_REQ->addr = addr;
  RAM_RD_REQ->num_words = num_words;
  RAM_RD_REQ->valid = 1;
  return 1;
}
static inline __attribute__((always_inline)) void start_ram_read(uint32_t addr, uint32_t num_words){
  while(!try_start_ram_read(addr, num_words)){}
}


static inline __attribute__((always_inline)) riscv_valid_flag_t try_finish_ram_write(uint32_t num_words){
  // No write response data
  // Simply read and return response valid bit
  // Hardware automatically clears valid bit + num words on read of valid=1
  RAM_WR_RESP->num_words = num_words; // Requested num of words
  return RAM_WR_RESP->valid;
}
static inline __attribute__((always_inline)) void finish_ram_write(uint32_t num_words){
  RAM_WR_RESP->num_words = num_words;
  while(!RAM_WR_RESP->valid){}
}
// Caution trying for different num_words might not make sense?
/*static inline __attribute__((always_inline)) riscv_valid_flag_t try_finish_ram_read(uint32_t* data, uint8_t num_words){
  // Have valid read response data?
  RAM_RD_RESP->num_words = num_words; // Requested num of words
  riscv_valid_flag_t rv = RAM_RD_RESP->valid;
  // If not then done now
  if(!rv){
    return rv;
  }
  // Valid is not auto cleared by hardware
  // Save the valid data
  // TODO skip copy if data pointer is mmio regs already
  for(uint32_t i = 0; i < num_words; i++)
  {
    data[i] = RAM_RD_RESP->data[i];
  }
  // Manually clear the valid buffer
  RAM_RD_RESP->num_words = 0;
  RAM_RD_RESP->valid = 0;
  // Done
  return rv;
}*/
static inline __attribute__((always_inline)) void finish_ram_read(uint32_t* data, uint8_t num_words){
  // Wait for finish
  RAM_RD_RESP->num_words = num_words; // Requested num of words
  while(!RAM_RD_RESP->valid){}
  // Valid is not auto cleared by hardware
  // Save the valid data
  // TODO skip copy if data pointer is mmio regs already?
  for(uint32_t i = 0; i < num_words; i++)
  {
    data[i] = RAM_RD_RESP->data[i];
  }
  // Manually clear the valid buffer
  RAM_RD_RESP->num_words = 0;
  RAM_RD_RESP->valid = 0;
  // Done
}

// One in flight, start one and finishes one
// Does not need to check before starting next xfer
static inline __attribute__((always_inline)) void ram_write(uint32_t addr, uint32_t* data, uint8_t num_words){
  // Start
  // Dont need try_ logic to check if valid been cleared, just set
  // Start
  RAM_WR_REQ->addr = addr;
  RAM_WR_REQ->num_words = num_words;
  // TODO skip copy if data pointer is mmio regs already?
  for(uint32_t i = 0; i < num_words; i++)
  {
    RAM_WR_REQ->data[i] = data[i];
  }
  RAM_WR_REQ->valid = 1;
  // Finish
  finish_ram_write(num_words);
}
static inline __attribute__((always_inline)) void ram_read(uint32_t addr, uint32_t* data, uint8_t num_words){
  // Start
  // Dont need try_ logic to check if valid been cleared, just set
  RAM_RD_REQ->addr = addr;
  RAM_RD_REQ->num_words = num_words;
  RAM_RD_REQ->valid = 1;
  // Wait for finish
  finish_ram_read(data, num_words);
}


// Frame sync
#define FRAME_SIGNAL_ADDR (RAM_RD_RESP_ADDR + sizeof(riscv_ram_read_resp_t))
static volatile int32_t* FRAME_SIGNAL = (int32_t*)FRAME_SIGNAL_ADDR;


// Kernel hardware
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color, does get correctly packed at 4 bytes sizeof()
typedef struct kernel_in_t{
  int32_t x; int32_t y;
  uint32_t frame_count;
  //pixel_t p_in,; // Only valid if ENABLE_PIXEL_IN_READ
}kernel_in_t;
// kernel_out_t is just pixel_t for now...
#define KERNEL_DATA_IN_ADDR (FRAME_SIGNAL_ADDR + sizeof(int32_t))
static volatile kernel_in_t* KERNEL_DATA_IN = (kernel_in_t*)KERNEL_DATA_IN_ADDR;
#define KERNEL_VALID_IN_ADDR (KERNEL_DATA_IN_ADDR + sizeof(kernel_in_t))
static volatile uint32_t* KERNEL_VALID_IN = (uint32_t*)KERNEL_VALID_IN_ADDR;
#define KERNEL_DATA_OUT_ADDR (KERNEL_VALID_IN_ADDR + sizeof(uint32_t))
static volatile pixel_t* KERNEL_DATA_OUT = (pixel_t*)KERNEL_DATA_OUT_ADDR;
#define KERNEL_VALID_OUT_ADDR (KERNEL_DATA_OUT_ADDR + sizeof(pixel_t))
static volatile uint32_t* KERNEL_VALID_OUT = (uint32_t*)KERNEL_VALID_OUT_ADDR;
#ifdef __PIPELINEC__
#include "kernel_in_t_bytes_t.h"
#include "pixel_t_bytes_t.h"
//
#define min(x,y)\
(x) < (y) ? (x) : (y)
pixel_t kernel_func(kernel_in_t inputs)
{
  pixel_t pixel;
  int32_t x = inputs.x;
  int32_t y = inputs.y;
  int32_t frame_count = inputs.frame_count;
  // Example uses 71x40 blocky resolution
  // match to roughly 1/4th of 640x480
  // TODO real full resolution demo? How to change all these magic numbers?
  x = x >> 2;
  y = y >> 2;
  y -= (FRAME_HEIGHT/8); // Adjust screen to show more vertical sky to account for zoom out
  // TODO real time from clock?
  int32_t t = frame_count << 6;

  // Thanks internet!
  // https://www.shadertoy.com/view/4ft3Wn
  //-------------------------    
  // animation
  //-------------------------    
  int32_t tt = min(4095,512+(t&4095));
  // vert
  int32_t ft = tt&1023;
  int32_t it = 1023-((tt>>2)&0xff00);
  int32_t q = 1023-ft;
  q = (q*ft)>>10;
  q = (q*it)>>10;
  q = (q*it)>>9; // was 10
  int32_t v0 = q>>3;
  // hori
  q = 4095-tt;
  q = (q*q)>>9; // was 10
  int32_t u0 = q>>8;
  

  int32_t R, B;

  //-------------------------    
  // Section A (2 MUL, 3 ADD)
  //-------------------------    
  int32_t u = x-36-u0;
  int32_t v = 18-y;
  int32_t z = v-v0;
  int32_t u2 = u*u;
  int32_t v2 = z*z;
  int32_t h = u2 + v2;
  //-------------------------  
  
  if( h < 200 ) 
  {
      //-------------------------------------
      // Section B, Sphere (4/7 MUL, 5/9 ADD)
      //-------------------------------------
      R = 420;
      B = 520;

      int32_t t = 5200 + h*8;
      int32_t p = (t*u)>>7;
      int32_t q = (t*z)>>7;
      
      // bounce light
      int32_t w = 18 + (((p*5-q*13))>>9) - (v0>>1);
      if( w>0 ) R += w*w;
      
      // sky light / ambient occlusion
      int32_t o = q + 900 + (v0<<4);
      R = (R*o)>>12;
      B = (B*o)>>12;

      // sun/key light
      if( p > -q )
      {
          int32_t w = (p+q)>>3;
          R += w;
          B += w;
      }
      //-------------------------  
  }
  else if( v<0 )
  {
      //-------------------------------------
      // Section C, Ground (5/9 MUL, 6/9 ADD)
      //-------------------------------------
      R = 150 + 2*v;
      B = 50;

      int32_t p = h + 8*v2;
      int32_t c = -v*(240+16*v0) - p;

      // sky light / ambient occlusion
      if( c>1200 )
      {
          int32_t o = (25*c)>>3;
          o = (c*(7840-o)>>9) - 8560;
          R = (R*o)>>10;
          B = (B*o)>>10;
      }

      // sun/key light with soft shadow
      int32_t w = 4*v + 50;
      int32_t s = u - w;
      int32_t d = s*s + (u+v0)*(w+24+v0) - 90;
      if( d>0 ) R += d;
  }
  else
  {
      //------------------------------
      // Section D, Sky (1 MUL, 2 ADD)
      //------------------------------
      int32_t c = x + 4*y;
      R = 132 + c;
      B = 192 + c;
      //-------------------------  
  }
  
  //-------------------------
  // Section E (3 MUL, 1 ADD)
  //-------------------------
  R = min(R,255);
  B = min(B,255);
  
  int32_t G = (R*11 + 5*B)>>4;
  //-------------------------  

  //return vec3(R,G,B);
  pixel.a = 0;
  pixel.r = R;
  pixel.g = G;
  pixel.b = B;
  return pixel;
}
#endif

/*//TODO CHANGE FOR KERNEL  
static inline __attribute__((always_inline)) riscv_valid_flag_t try_start_ram_read(
  uint32_t addr, uint32_t num_words
){
  // If the request flag is valid from a previous req
  // then done now, couldnt start
  if(RAM_RD_REQ->valid){
    return 0;
  }
  // Start
  RAM_RD_REQ->addr = addr;
  RAM_RD_REQ->num_words = num_words;
  RAM_RD_REQ->valid = 1;
  return 1;
}
static inline __attribute__((always_inline)) void start_ram_read(uint32_t addr, uint32_t num_words){
  while(!try_start_ram_read(addr, num_words)){}
}

static inline __attribute__((always_inline)) riscv_valid_flag_t try_finish_ram_read(uint32_t* data, uint8_t num_words){
  // Have valid read response data?
  RAM_RD_RESP->num_words = num_words; // Requested num of words
  riscv_valid_flag_t rv = RAM_RD_RESP->valid;
  // If not then done now
  if(!rv){
    return rv;
  }
  // Valid is not auto cleared by hardware
  // Save the valid data
  // TODO skip copy if data pointer is mmio regs already
  for(uint32_t i = 0; i < num_words; i++)
  {
    data[i] = RAM_RD_RESP->data[i];
  }
  // Manually clear the valid buffer
  RAM_RD_RESP->num_words = 0;
  RAM_RD_RESP->valid = 0;
  // Done
  return rv;
}
*/
static inline __attribute__((always_inline)) void finish_kernel_pipeline(pixel_t* data){
  // Wait for finish
  while(!*KERNEL_VALID_OUT){}
  // Valid is not auto cleared by hardware
  // Save the valid data
  // TODO skip copy if data pointer is mmio regs already?
  *data = *KERNEL_DATA_OUT;
  // Manually clear the valid buffer
  *KERNEL_VALID_OUT = 0;
  // Done
}

static inline __attribute__((always_inline)) void kernel_hw(
  int32_t x, int32_t y,
  uint32_t frame_count,
  pixel_t* pixel_in,
  pixel_t* pixel_out
){
  // Start
  // Dont need try_ logic to check if valid been cleared, just set
  KERNEL_DATA_IN->x = x;
  KERNEL_DATA_IN->y = y;
  KERNEL_DATA_IN->frame_count = frame_count;
  //KERNEL_DATA_IN->pixel_in = *pixel_in;
  *KERNEL_VALID_IN = 1;
  // Wait for finish
  finish_kernel_pipeline(pixel_out);
}