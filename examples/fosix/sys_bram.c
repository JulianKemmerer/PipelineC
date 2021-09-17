#include "compiler.h"
#include "wire.h"
#include "fosix.h"

#define BRAM_WIDTH FOSIX_BUF_SIZE // Same as FOSIX example buffer size for now
#define LOG2_BRAM_WIDTH FOSIX_LOG2_BUF_SIZE
typedef struct bram_mem_elem_t
{
	uint8_t bytes[BRAM_WIDTH];
} bram_mem_elem_t;
#define BRAM_SIZE (16*1024)
#define BRAM_DEPTH (BRAM_SIZE/BRAM_WIDTH)
#define bram_addr_t uint16_t

// TODO
// For now assuming
//    interface will always request FOSIX_BUF_SIZE bytes
//    at even FOSIX_BUF_SIZE divisible byte addresses

// Simple single state machine to start
typedef enum bram_state_t {
  RESET,
  WAIT_REQ, // Wait for valid request
  WAIT_OPEN_RESP, // Wait until ready for open response
  WAIT_WRITE_RESP, // Wait to output write resp
  WAIT_READ_RESP, // Wait to output read resp
  WAIT_CLOSE_RESP
} bram_state_t;

// Clock cross into fosix router thing
fosix_sys_to_proc_t bram_sys_to_proc;
#include "clock_crossing/bram_sys_to_proc.h"
// Clock cross out of fosix router thing
fosix_proc_to_sys_t bram_proc_to_sys;
#include "clock_crossing/bram_proc_to_sys.h"

MAIN_MHZ(sys_bram, UART_CLK_MHZ) // use uart clock from now
void sys_bram()
{
  // Read inputs driven from other modules
  //
  // Read proc_to_sys output from fosix router thing
  fosix_proc_to_sys_t proc_to_sys;
  WIRE_READ(fosix_proc_to_sys_t, proc_to_sys, bram_proc_to_sys)
  
  // Outputs
  // Default output values so each state is easier to write
  fosix_sys_to_proc_t sys_to_proc;
  //////////////////////////////////////////////////////////////////////
  
  // BRAM storage
  static bram_mem_elem_t bram_ram[BRAM_DEPTH];
  static bram_state_t bram_state;
  static fosix_size_t bram_req_nbyte;
  static fosix_size_t bram_byte_offset;
  static fosix_size_t bram_byte_count;
  #define BRAM_DELAY 2
  static uint1_t bram_valid_delay[BRAM_DELAY];
  static bram_mem_elem_t bram_output;
  static uint1_t bram_output_valid;
  
  // At end of storage?
  uint1_t at_capacity = bram_byte_count >= BRAM_SIZE;
  // At end of file?
  uint1_t at_eof = bram_byte_offset >= bram_byte_count;
  
  // BRAM input signals defaults
  bram_addr_t addr = 0;
  bram_mem_elem_t wr_data;
  uint1_t wr_en = 0;
  uint1_t valid = 0;
  
  if(bram_state==RESET)
  {
    bram_state = WAIT_REQ;
  }
  // Wait for incoming request
  else if(bram_state==WAIT_REQ)
  {
    // Start by signaling ready for requests
    sys_to_proc.proc_to_sys_msg_ready = 1;
    // Parse request
    fosix_parsed_req_msg_t req = msg_to_request(proc_to_sys.msg);
    if(req.syscall_num == FOSIX_OPEN)
    {
      bram_state = WAIT_OPEN_RESP;
      // OPEN resets read/write pos
      bram_byte_offset = 0;
    }
    else if(req.syscall_num == FOSIX_WRITE)
    {      
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
        wr_en = req.sys_write.nbyte > 0; // TODO NON FOSIX_BUF_SIZE BYTES
        addr = bram_byte_offset >> LOG2_BRAM_WIDTH; // / BRAM_WIDTH
        wr_data.bytes = req.sys_write.buf;
        bram_req_nbyte = req.sys_write.nbyte;
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
    else if(req.syscall_num == FOSIX_READ)
    {
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
        bram_req_nbyte = req.sys_read.nbyte;
        valid = 1;
        // Increment pos to reflect bytes
        bram_byte_offset = bram_byte_offset + bram_req_nbyte;
      }
      // Begin waiting for bram delay and user resp ready
      bram_state = WAIT_READ_RESP;
    }
    else if(req.syscall_num == FOSIX_CLOSE)
    {
      bram_state = WAIT_CLOSE_RESP;
    }
  }
  else if(bram_state==WAIT_OPEN_RESP)
  {
    // File descriptor can be anything we want
    // Handled in fosix fd lookup table...
    // Just signal valid until ready
    open_resp_t open_resp;
    open_resp.fildes = 0;
    fosix_msg_decoded_t open_resp_msg = UNKNOWN_MSG();
    open_resp_msg.syscall_num = FOSIX_OPEN;
    OPEN_RESP_T_TO_BYTES(open_resp_msg.payload_data, open_resp)
    sys_to_proc.msg.data = decoded_msg_to_msg(open_resp_msg);
    sys_to_proc.msg.valid = 1;
    if(proc_to_sys.sys_to_proc_msg_ready)
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
      write_resp_t write_resp;
      write_resp.nbyte = bram_req_nbyte;
      fosix_msg_decoded_t write_resp_msg = UNKNOWN_MSG();
      write_resp_msg.syscall_num = FOSIX_WRITE;
      WRITE_RESP_T_TO_BYTES(write_resp_msg.payload_data, write_resp)
      sys_to_proc.msg.data = decoded_msg_to_msg(write_resp_msg);
      sys_to_proc.msg.valid = 1;
      // And wait for ready for response
      if(proc_to_sys.sys_to_proc_msg_ready)
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
      read_resp_t read_resp;
      read_resp.buf = bram_output.bytes;
      read_resp.nbyte = bram_req_nbyte;
      fosix_msg_decoded_t read_resp_msg = UNKNOWN_MSG();
      read_resp_msg.syscall_num = FOSIX_READ;
      READ_RESP_T_TO_BYTES(read_resp_msg.payload_data, read_resp)
      sys_to_proc.msg.data = decoded_msg_to_msg(read_resp_msg);
      sys_to_proc.msg.valid = 1;
      // And wait for ready for response
      if(proc_to_sys.sys_to_proc_msg_ready)
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
    close_resp_t close_resp;
    close_resp.err = 0;
    fosix_msg_decoded_t close_resp_msg = UNKNOWN_MSG();
    close_resp_msg.syscall_num = FOSIX_CLOSE;
    CLOSE_RESP_T_TO_BYTES(close_resp_msg.payload_data, close_resp)
    sys_to_proc.msg.data = decoded_msg_to_msg(close_resp_msg);
    sys_to_proc.msg.valid = 1;
    if(proc_to_sys.sys_to_proc_msg_ready)
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
  fosix_size_t d;
  for(d=0;d<(BRAM_DELAY-1);d=d+1)
  {
    bram_valid_delay[d] = bram_valid_delay[d+1];
  }
  bram_valid_delay[BRAM_DELAY-1] = valid;
  
  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write bram sys_to_proc into fosix router thing
  WIRE_WRITE(fosix_sys_to_proc_t, bram_sys_to_proc, sys_to_proc)
}
