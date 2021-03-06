#include "fosix.h"

#define BRAM_WIDTH BUF_SIZE // Same as FOSIX example buffer size for now
#define LOG2_BRAM_WIDTH LOG2_BUF_SIZE //7
typedef struct bram_mem_elem_t
{
	uint8_t bytes[BRAM_WIDTH];
} bram_mem_elem_t;
bram_mem_elem_t BRAM_MEM_ELEM_T_NULL()
{
  bram_mem_elem_t rv;
  size_t i;
  for(i=0;i<BRAM_WIDTH;i=i+1)
  {
    rv.bytes[i] = 0;
  }
  return rv;
}
#define BRAM_DEPTH 128
#define bram_addr_t uint7_t
#define BRAM_SIZE (BRAM_WIDTH*BRAM_DEPTH)

// Hard coded device paths for now
uint1_t path_is_bram(open_req_t req)
{
  //"bram\0"
  char bram_path[5];
  bram_path[0] = 'b';
  bram_path[1] = 'r';
  bram_path[2] = 'a';
  bram_path[3] = 'm';
  bram_path[4] = 0;
  
  // Compute all the conditions for match in parallel
  uint1_t bools[6];
  uint8_t c;
  for(c=0; c<5; c=c+1)
  {
    bools[c] = req.path[c]==bram_path[c];
  }
  bools[5] = req.valid;
  
  return uint1_array_and6(bools);
}

// TODO
// For now assuming
//    interface will always request BUF_SIZE bytes
//    at even BUF_SIZE divisible byte addresses

// Simple single state machine to start
typedef enum bram_state_t {
  RESET,
  WAIT_REQ, // Wait for valid request
  WAIT_OPEN_RESP, // Wait until ready for open response
  WAIT_WRITE_RESP, // Wait to output write resp
  WAIT_READ_RESP, // Wait to output read resp
  WAIT_CLOSE_RESP
} bram_state_t;

// Clock cross into fosix
posix_h2c_t bram_h2c;
#include "posix_h2c_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "bram_h2c_clock_crossing.h"
// Clock cross out of fosix
posix_c2h_t bram_c2h;
#include "posix_c2h_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "bram_c2h_clock_crossing.h"

// BRAM storage
bram_mem_elem_t bram_ram[BRAM_DEPTH];
bram_state_t bram_state;
size_t bram_req_nbyte;
size_t bram_byte_offset;
size_t bram_byte_count;
#define BRAM_DELAY 2
uint1_t bram_valid_delay[BRAM_DELAY];
bram_mem_elem_t bram_output;
uint1_t bram_output_valid;
#pragma MAIN_MHZ bram 150.0
void bram(uint1_t rst)
{
  // Inputs
  posix_c2h_t c2h;
  // Outputs
  posix_h2c_t h2c;
  
  // Read inputs driven from other modules
  //
  // Read c2h output from fosix
  posix_c2h_t_array_1_t c2hs;
  c2hs = bram_c2h_READ();
  c2h = c2hs.data[0];
  //
  // Default output values so each state is easier to write
  h2c = POSIX_H2C_T_NULL();
  //////////////////////////////////////////////////////////////////////
  
  // At end of storage?
  uint1_t at_capacity = bram_byte_count >= BRAM_SIZE;
  // At end of file?
  uint1_t at_eof = bram_byte_offset >= bram_byte_count;
  
  // BRAM input signals defaults
  bram_addr_t addr = 0;
  bram_mem_elem_t wr_data = BRAM_MEM_ELEM_T_NULL();
  uint1_t wr_en = 0;
  uint1_t valid = 0;
  
  if(bram_state==RESET)
  {
    bram_state = WAIT_REQ;
  }
  // Wait for incoming request
  else if(bram_state==WAIT_REQ)
  {
    // Start by signaling ready for all requests
    h2c = h2c_set_ready(h2c);
    // Find one system call making a request
    // and invalidate the ready for all other requests
    // Then start syscall logic and wait to output response
    // OK to have dumb constant priority 
    // and valid<->ready combinatorial feedback for now
    if(c2h.sys_open.req.valid)
    {
      h2c = h2c_clear_ready(h2c);
      h2c.sys_open.req_ready = 1;
      bram_state = WAIT_OPEN_RESP;
      // OPEN resets read/write pos
      bram_byte_offset = 0;
    }
    else if(c2h.sys_write.req.valid)
    {
      h2c = h2c_clear_ready(h2c);
      h2c.sys_write.req_ready = 1;
      
      //If at capacity then dont do anything to BRAM,
      // respond with 0 bytes writen
      if(at_capacity)
      {
        bram_req_nbyte = 0;
        valid = 1;
      }
      else
      {
        // Do write
        // Send inputs into bram module
        wr_en = c2h.sys_write.req.nbyte > 0; // TODO NON BUF_SIZE BYTES
        addr = bram_byte_offset >> LOG2_BRAM_WIDTH; // / BRAM_WIDTH
        wr_data.bytes = c2h.sys_write.req.buf;
        bram_req_nbyte = c2h.sys_write.req.nbyte;
        valid = 1;
        // Increment pos to reflect bytes
        bram_byte_offset = bram_byte_offset + bram_req_nbyte;
        // Update count if increased
        if(bram_byte_offset > bram_byte_count)
        {
          bram_byte_count = bram_byte_offset;
        }
      }
      // Begin waiting for bram delay and user resp ready
      bram_state = WAIT_WRITE_RESP;
    }
    else if(c2h.sys_read.req.valid)
    {
      h2c = h2c_clear_ready(h2c);
      h2c.sys_read.req_ready = 1;
      //If at EOF then dont do anything to BRAM,
      // respond with 0 bytes read
      if(at_eof)
      {
        bram_req_nbyte = 0;
        valid = 1;
      }
      else
      {
        // Do read
        // Send inputs into bram module
        wr_en = 0;
        addr = bram_byte_offset >> LOG2_BRAM_WIDTH; // / BRAM_WIDTH
        bram_req_nbyte = c2h.sys_read.req.nbyte;
        valid = 1;
        // Increment pos to reflect bytes
        bram_byte_offset = bram_byte_offset + bram_req_nbyte;
      }
      // Begin waiting for bram delay and user resp ready
      bram_state = WAIT_READ_RESP;
    }
    else if(c2h.sys_close.req.valid)
    {
      h2c = h2c_clear_ready(h2c);
      h2c.sys_close.req_ready = 1;
      bram_state = WAIT_CLOSE_RESP;
    }
  }
  else if(bram_state==WAIT_OPEN_RESP)
  {
    // File descriptor can be anything we want
    // Handled in fosix fd lookup table...
    // Just signal valid until ready
    h2c.sys_open.resp.valid = 1;
    h2c.sys_open.resp.fildes = 0;
    if(c2h.sys_open.resp_ready)
    {
      // Next request
      bram_state = WAIT_REQ;
    }
  } 
  else if(bram_state==WAIT_WRITE_RESP)
  {
    // Wait for valid delay to indicate done, valid resp
    if(bram_output_valid)
    {
      // Output valid response
      h2c.sys_write.resp.valid = 1;
      h2c.sys_write.resp.nbyte = bram_req_nbyte;
      
      // And wait for ready for response
      if(c2h.sys_write.resp_ready)
      {
        // Done with write
        // Clear buffer
        bram_output_valid = 0;
        // Next request
        bram_state = WAIT_REQ;
      }
    }
  }
  else if(bram_state==WAIT_READ_RESP)
  {
    // Wait for valid delay to indicate done, valid resp
    if(bram_output_valid)
    {
      // Output valid response
      h2c.sys_read.resp.valid = 1;
      h2c.sys_read.resp.buf = bram_output.bytes;
      h2c.sys_read.resp.nbyte = bram_req_nbyte;
      
      // And wait for ready for response
      if(c2h.sys_read.resp_ready)
      {
        // Done with read
        // Clear buffer
        bram_output_valid = 0;
        // Next request
        bram_state = WAIT_REQ;
      }
    }
  }
  else if(bram_state==WAIT_CLOSE_RESP)
  {
    // Just signal valid until ready, no err
    h2c.sys_close.resp.valid = 1;
    if(c2h.sys_close.resp_ready)
    {
      // Next request
      bram_state = WAIT_REQ;
    }
  } 
  
  // Global function BRAM instance
  //  Single port, read first, 2 clk delay (in and out regs)
  bram_mem_elem_t read_data = bram_ram_RAM_SP_RF_2(addr, wr_data, wr_en);
  
  // Capture output data into register when delayed valid is output 
  if(bram_valid_delay[0])
  {
    bram_output = read_data;
    bram_output_valid = 1;
  }
  
  // Delay input valid alongside BRAM
  size_t d;
  for(d=0;d<(BRAM_DELAY-1);d=d+1)
  {
    bram_valid_delay[d] = bram_valid_delay[d+1];
  }
  bram_valid_delay[BRAM_DELAY-1] = valid;
  
  if(rst)
  {
    bram_state = RESET;
    bram_byte_offset = 0;
    bram_byte_count = 0;
    bram_output_valid = 0;
    for(d=0;d<(BRAM_DELAY-1);d=d+1)
    {
      bram_valid_delay[d] = 0;
    }
  }
  
  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write bram h2c into fosix
  posix_h2c_t_array_1_t h2cs;
  h2cs.data[0] = h2c;
  bram_h2c_WRITE(h2cs);
}
