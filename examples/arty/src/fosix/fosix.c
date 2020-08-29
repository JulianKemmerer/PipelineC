#include "compiler.h"

// System devices?
// Host OS device hooks (UART based)
#include "sys_host_uart.c"
// BRAM system device hooks
#include "sys_bram.c"

// Because some external sys picks the file descriptor numbers
// but on chip resources need their own/pick their own separate file descriptors
// Create a lookup table that can bypass/make "virtual" file descriptors?
typedef struct fd_lut_elem_t
{
  fosix_fd_t local_fd;
  fosix_fd_t host_fd;
  uint1_t is_bram;
  uint1_t valid;
} fd_lut_elem_t;
#define FOSIX_NUM_FILDES 4
#define fd_match_or uint1_array_or4
typedef struct fd_lut_t
{
  fd_lut_elem_t elem[FOSIX_NUM_FILDES];
} fd_lut_t;

typedef struct fd_lut_update_t
{
  fd_lut_t fd_lut;
  fosix_fd_t fildes;
} fd_lut_update_t;
fd_lut_update_t insert_fd(fosix_fd_t host_fildes, uint1_t is_bram, fd_lut_t fd_lut)
{
  // Kinda need to assume we will 
  // find empty space for new fildes in table for now...
  // How to error if cant?
  
  // Pick an unused local fildes
  // At most FOSIX_NUM_FILDES can be used so one will be free
  fosix_fd_t new_local_fildes = -1;
  uint1_t not_found_new_fildes = 1;
  fosix_fd_t possible_new_local_fildes;
  uint8_t i;
  for(possible_new_local_fildes=0; possible_new_local_fildes<FOSIX_NUM_FILDES; possible_new_local_fildes=possible_new_local_fildes+1)
  {
    if(not_found_new_fildes)
    {
      // Is possible_new_local_fildes available for use?
      // Compare all table elements in parallel
      uint1_t elem_match[FOSIX_NUM_FILDES];
      for(i=0;i<FOSIX_NUM_FILDES;i=i+1)
      {
        elem_match[i] = (fd_lut.elem[i].local_fd == possible_new_local_fildes) & fd_lut.elem[i].valid;
      }
      uint1_t any_elem_match = fd_match_or(elem_match);
      // If no table elements match then use possibile fildes
      if(!any_elem_match)
      {
        new_local_fildes = possible_new_local_fildes;
        not_found_new_fildes = 0;
      }
    } 
  }
  
  // Put new local fildes in table
  uint1_t not_inserted = 1;
  for(i=0;i<FOSIX_NUM_FILDES;i=i+1)
  {
    if(not_inserted)
    {
      // Insert here if empty
      if(!fd_lut.elem[i].valid)
      {
        fd_lut.elem[i].host_fd = host_fildes;
        fd_lut.elem[i].local_fd = new_local_fildes;
        fd_lut.elem[i].is_bram = is_bram;
        fd_lut.elem[i].valid = 1;
        not_inserted = 0;
      }
    }
  }
  
  fd_lut_update_t fd_lut_update;
  fd_lut_update.fd_lut = fd_lut;
  fd_lut_update.fildes = new_local_fildes;
  return fd_lut_update;
}

fosix_fd_t translate_fd(fosix_fd_t local_fildes, fd_lut_t fd_lut)
{
  // Match local fd in table
  // Default dont modify?
  fosix_fd_t host_fd = local_fildes;
  uint8_t i;
  for(i=0;i<FOSIX_NUM_FILDES;i=i+1)
  {
    if((fd_lut.elem[i].local_fd == local_fildes) & fd_lut.elem[i].valid)
    {
      host_fd = fd_lut.elem[i].host_fd;
    }
  }
  return host_fd;
}

fd_lut_t remove_fd(fosix_fd_t local_fildes, fd_lut_t fd_lut)
{
  uint8_t i;
  for(i=0;i<FOSIX_NUM_FILDES;i=i+1)
  {
    if(fd_lut.elem[i].local_fd == local_fildes)
    {
      fd_lut.elem[i].valid = 0;
    }
  }
  return fd_lut;
}

fd_lut_t clear_lut(fd_lut_t fd_lut)
{
  uint8_t i;
  for(i=0;i<FOSIX_NUM_FILDES;i=i+1)
  {
    fd_lut.elem[i].valid = 0;
  }
  return fd_lut;
}

uint1_t fd_is_bram(fosix_fd_t local_fildes, fd_lut_t fd_lut)
{
  uint1_t rv = 0;
  uint8_t i;
  for(i=0;i<FOSIX_NUM_FILDES;i=i+1)
  {
    if((fd_lut.elem[i].local_fd == local_fildes) & fd_lut.elem[i].valid)
    {
      rv = fd_lut.elem[i].is_bram;
    }
  }
  return rv;
}

// Clock cross into main
fosix_sys_to_proc_t main_sys_to_proc;
#include "fosix_sys_to_proc_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "main_sys_to_proc_clock_crossing.h"
// Clock cross out of main
fosix_proc_to_sys_t main_proc_to_sys;
#include "fosix_proc_to_sys_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "main_proc_to_sys_clock_crossing.h"

// Slow bulky single state machine for now...
// Need to enforce only one system call "in flight" at a time
// Because otherwise would need more complicated way of 
// tagging and identifying what responses are to what requests
// maybe take hints from software async syscalls? TODO
// OK to have dumb constant priority 
// and valid<->ready combinatorial feedback for now too...
typedef enum fosix_state_t {
  RESET,
  WAIT_REQ, // Wait for request from main
  WAIT_RESP // Wait for response into main
} fosix_state_t;
fosix_state_t fosix_state;
syscall_t in_flight_syscall;
uint1_t in_flight_syscall_dev_is_bram;
fd_lut_t fosix_fd_lut;

MAIN_MHZ(fosix, UART_CLK_MHZ)
void fosix()
{
  // Inputs
  // Read inputs driven from other modules
  //
  // Read sys_to_proc_host output from host
  fosix_sys_to_proc_t sys_to_proc_host;
  WIRE_READ(fosix_sys_to_proc_t, sys_to_proc_host, host_sys_to_proc)
  // Read sys_to_proc_bram output from bram
  fosix_sys_to_proc_t sys_to_proc_bram;
  WIRE_READ(fosix_sys_to_proc_t, sys_to_proc_bram, bram_sys_to_proc)
  // Read proc_to_sys output from main process
  fosix_proc_to_sys_t proc_to_sys_main;
  WIRE_READ(fosix_proc_to_sys_t, proc_to_sys_main, main_proc_to_sys)
  
  // Outputs
  // Default outputs so each state is easier to write
  fosix_proc_to_sys_t proc_to_sys_host = POSIX_PROC_TO_SYS_T_NULL();
  fosix_proc_to_sys_t proc_to_sys_bram = POSIX_PROC_TO_SYS_T_NULL();
  fosix_sys_to_proc_t sys_to_proc_main = POSIX_SYS_TO_PROC_T_NULL();
  //////////////////////////////////////////////////////////////////////

  if(fosix_state==RESET)
  {
    fosix_state = WAIT_REQ;
  }
  
  // WAIT ON REQUESTS //////////////////////////////////////////////////
  else if(fosix_state==WAIT_REQ)
  {
    // Start off signaling ready for all requests from main
    sys_to_proc_main = sys_to_proc_set_ready(sys_to_proc_main);
    
    // Wait for an incoming request from main to a "host device"
    // Find one system call making a request
    // and invalidate the ready for all other requests
    // Depending on requested syscall and sys device
    // connect req.valid and req_ready
    // Hard coded devices for now
    // Connect sys device with opposite direction flow control
    // And set state for handling response when it comes
    
    // OPEN
    if(proc_to_sys_main.sys_open.req.valid)
    {
      sys_to_proc_main = sys_to_proc_clear_ready(sys_to_proc_main);
      // BRAM
      if(path_is_bram(proc_to_sys_main.sys_open.req))
      {
        proc_to_sys_bram.sys_open.req = proc_to_sys_main.sys_open.req;
        sys_to_proc_main.sys_open.req_ready = sys_to_proc_bram.sys_open.req_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        proc_to_sys_host.sys_open.req = proc_to_sys_main.sys_open.req;
        sys_to_proc_main.sys_open.req_ready = sys_to_proc_host.sys_open.req_ready;
        in_flight_syscall_dev_is_bram = 0;
      }
      // Move on to waiting for response if was ready for request
      in_flight_syscall = FOSIX_OPEN;
      if(sys_to_proc_main.sys_open.req_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // WRITE
    else if(proc_to_sys_main.sys_write.req.valid)
    {
      sys_to_proc_main = sys_to_proc_clear_ready(sys_to_proc_main);
      
      // Translate from local file descriptor to sys fd
      // Before connecting to sys proc_to_sys device busses
      // Saving a copy of local fd
      fosix_fd_t local_fd = proc_to_sys_main.sys_write.req.fildes;
      proc_to_sys_main.sys_write.req.fildes = translate_fd(proc_to_sys_main.sys_write.req.fildes, fosix_fd_lut);
      
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        proc_to_sys_bram.sys_write.req = proc_to_sys_main.sys_write.req;
        sys_to_proc_main.sys_write.req_ready = sys_to_proc_bram.sys_write.req_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        proc_to_sys_host.sys_write.req = proc_to_sys_main.sys_write.req;
        sys_to_proc_main.sys_write.req_ready = sys_to_proc_host.sys_write.req_ready;
        in_flight_syscall_dev_is_bram = 0;
      }
      // Move on to waiting for response if was ready for request
      in_flight_syscall = FOSIX_WRITE;
      if(sys_to_proc_main.sys_write.req_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // READ
    else if(proc_to_sys_main.sys_read.req.valid)
    {
      sys_to_proc_main = sys_to_proc_clear_ready(sys_to_proc_main);
      
      // Translate from local file descriptor to sys fd
      // Before connecting to sys proc_to_sys device busses
      // Saving a copy of local fd
      fosix_fd_t local_fd = proc_to_sys_main.sys_read.req.fildes;
      proc_to_sys_main.sys_read.req.fildes = translate_fd(proc_to_sys_main.sys_read.req.fildes, fosix_fd_lut);
      
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        proc_to_sys_bram.sys_read.req = proc_to_sys_main.sys_read.req;
        sys_to_proc_main.sys_read.req_ready = sys_to_proc_bram.sys_read.req_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        proc_to_sys_host.sys_read.req = proc_to_sys_main.sys_read.req;
        sys_to_proc_main.sys_read.req_ready = sys_to_proc_host.sys_read.req_ready;
        in_flight_syscall_dev_is_bram = 0;
      }
      // Move on to waiting for response if was ready for request
      in_flight_syscall = FOSIX_READ;
      if(sys_to_proc_main.sys_read.req_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // CLOSE
    else if(proc_to_sys_main.sys_close.req.valid)
    {
      sys_to_proc_main = sys_to_proc_clear_ready(sys_to_proc_main);
      
      // Translate from local file descriptor to sys fd
      // Before connecting to sys proc_to_sys device busses
      // Saving a copy of local fd
      fosix_fd_t local_fd = proc_to_sys_main.sys_close.req.fildes;
      proc_to_sys_main.sys_close.req.fildes = translate_fd(proc_to_sys_main.sys_close.req.fildes, fosix_fd_lut);
      
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        proc_to_sys_bram.sys_close.req = proc_to_sys_main.sys_close.req;
        sys_to_proc_main.sys_close.req_ready = sys_to_proc_bram.sys_close.req_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        proc_to_sys_host.sys_close.req = proc_to_sys_main.sys_close.req;
        sys_to_proc_main.sys_close.req_ready = sys_to_proc_host.sys_close.req_ready;
        in_flight_syscall_dev_is_bram = 0;
      }
      // Move on to waiting for response if was ready for request
      in_flight_syscall = FOSIX_CLOSE;
      if(sys_to_proc_main.sys_close.req_ready)
      {
        fosix_state = WAIT_RESP;
        // Make updates as needed based on response
        // CLOSE file descriptors table update
        // TODO move to response maybe close failed?
        fosix_fd_lut = remove_fd(local_fd, fosix_fd_lut);
      }
    }
  }
  
  // WAIT ON RESPONSES /////////////////////////////////////////////////
  else if(fosix_state==WAIT_RESP)
  {
    // Connect valid and ready on the
    // specific device and syscall response expected
    // Until a response is seen
    // Hard coded devices for now
    // Connect sys device with opposite direction flow control
    // And record state based on response
    
    // OPEN
    if(in_flight_syscall == FOSIX_OPEN)
    {
      // BRAM
      if(in_flight_syscall_dev_is_bram)
      {
        sys_to_proc_main.sys_open.resp = sys_to_proc_bram.sys_open.resp;
        proc_to_sys_bram.sys_open.resp_ready = proc_to_sys_main.sys_open.resp_ready;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        sys_to_proc_main.sys_open.resp = sys_to_proc_host.sys_open.resp;
        proc_to_sys_host.sys_open.resp_ready = proc_to_sys_main.sys_open.resp_ready;
      }

      // Move on to waiting for next request 
      // if was valid response when ready seen
      if(sys_to_proc_main.sys_open.resp.valid & proc_to_sys_main.sys_open.resp_ready)
      {
        fosix_state = WAIT_REQ;
        // Make updates as needed based on response
        // OPEN file descriptors table update
        // Insert file sys decriptor response into table
        // And give main a local file descriptor
        fd_lut_update_t fd_lut_update = insert_fd(sys_to_proc_main.sys_open.resp.fildes, in_flight_syscall_dev_is_bram, fosix_fd_lut);
        fosix_fd_lut = fd_lut_update.fd_lut;
        sys_to_proc_main.sys_open.resp.fildes = fd_lut_update.fildes;
      }
    }
    // WRITE
    else if(in_flight_syscall == FOSIX_WRITE)
    {
      // BRAM
      if(in_flight_syscall_dev_is_bram)
      {
        sys_to_proc_main.sys_write.resp = sys_to_proc_bram.sys_write.resp;
        proc_to_sys_bram.sys_write.resp_ready = proc_to_sys_main.sys_write.resp_ready;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        sys_to_proc_main.sys_write.resp = sys_to_proc_host.sys_write.resp;
        proc_to_sys_host.sys_write.resp_ready = proc_to_sys_main.sys_write.resp_ready;
      }

      // Move on to waiting for next request 
      // if was valid response when ready seen
      if(sys_to_proc_main.sys_write.resp.valid & proc_to_sys_main.sys_write.resp_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
    // READ
    else if(in_flight_syscall == FOSIX_READ)
    {
      // BRAM
      if(in_flight_syscall_dev_is_bram)
      {
        sys_to_proc_main.sys_read.resp = sys_to_proc_bram.sys_read.resp;
        proc_to_sys_bram.sys_read.resp_ready = proc_to_sys_main.sys_read.resp_ready;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        sys_to_proc_main.sys_read.resp = sys_to_proc_host.sys_read.resp;
        proc_to_sys_host.sys_read.resp_ready = proc_to_sys_main.sys_read.resp_ready;
      }

      // Move on to waiting for next request 
      // if was valid response when ready seen
      if(sys_to_proc_main.sys_read.resp.valid & proc_to_sys_main.sys_read.resp_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
    // CLOSE
    else if(in_flight_syscall == FOSIX_CLOSE)
    {
      // BRAM
      if(in_flight_syscall_dev_is_bram)
      {
        sys_to_proc_main.sys_close.resp = sys_to_proc_bram.sys_close.resp;
        proc_to_sys_bram.sys_close.resp_ready = proc_to_sys_main.sys_close.resp_ready;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        sys_to_proc_main.sys_close.resp = sys_to_proc_host.sys_close.resp;
        proc_to_sys_host.sys_close.resp_ready = proc_to_sys_main.sys_close.resp_ready;
      }

      // Move on to waiting for next request 
      // if was valid response when ready seen
      if(sys_to_proc_main.sys_close.resp.valid & proc_to_sys_main.sys_close.resp_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
  }
  
  /*
  if(rst)
  {
    fosix_state = RESET;
    fosix_fd_lut = clear_lut(fosix_fd_lut);
  }
  */
  
  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write proc_to_sys_host output into host 
  WIRE_WRITE(fosix_proc_to_sys_t, host_proc_to_sys, proc_to_sys_host)
  // Write proc_to_sys_bram output into bram
  WIRE_WRITE(fosix_proc_to_sys_t, bram_proc_to_sys, proc_to_sys_bram)
  // Write sys_to_proc_main output into main
  WIRE_WRITE(fosix_sys_to_proc_t, main_sys_to_proc, sys_to_proc_main)
}

