// Pull in the AWS DMA in and out message hooks
// so we can send and receive dma messages from our fosix_aws_fpga_dma 
#include "fosix_aws_fpga_dma.c"

// Pull in BRAM file device
//#include "bram.c"

// Because some external host picks some of the file descriptor numbers
// but on chip resources need their own/pick their own separate file descriptors
// Create a lookup table that can bypass/make "virtual" file descriptors?
typedef struct fd_lut_elem_t
{
  fd_t local_fd;
  fd_t host_fd;
  //uint1_t is_bram;
  uint1_t valid;
} fd_lut_elem_t;
#define POSIX_NUM_FILDES 4
#define fd_match_or uint1_array_or4
typedef struct fd_lut_t
{
  fd_lut_elem_t elem[POSIX_NUM_FILDES];
} fd_lut_t;

typedef struct fd_lut_update_t
{
  fd_lut_t fd_lut;
  fd_t fildes;
} fd_lut_update_t;
fd_lut_update_t insert_fd(fd_lut_t fd_lut, fd_t host_fildes) //, uint1_t is_bram, )
{
  // Kinda need to assume we will 
  // find empty space for new fildes in table for now...
  // How to error if cant?
  
  // Pick an unused local fildes
  // At most POSIX_NUM_FILDES can be used so one will be free
  fd_t new_local_fildes = -1;
  uint1_t not_found_new_fildes = 1;
  fd_t possible_new_local_fildes;
  uint8_t i;
  for(possible_new_local_fildes=0; possible_new_local_fildes<POSIX_NUM_FILDES; possible_new_local_fildes=possible_new_local_fildes+1)
  {
    if(not_found_new_fildes)
    {
      // Is possible_new_local_fildes available for use?
      // Compare all table elements in parallel
      uint1_t elem_match[POSIX_NUM_FILDES];
      for(i=0;i<POSIX_NUM_FILDES;i=i+1)
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
  for(i=0;i<POSIX_NUM_FILDES;i=i+1)
  {
    if(not_inserted)
    {
      // Insert here if empty
      if(!fd_lut.elem[i].valid)
      {
        fd_lut.elem[i].host_fd = host_fildes;
        fd_lut.elem[i].local_fd = new_local_fildes;
        //fd_lut.elem[i].is_bram = is_bram;
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

fd_t translate_fd(fd_t local_fildes, fd_lut_t fd_lut)
{
  // Match local fd in table
  // Default dont modify?
  fd_t host_fd = local_fildes;
  uint8_t i;
  for(i=0;i<POSIX_NUM_FILDES;i=i+1)
  {
    if((fd_lut.elem[i].local_fd == local_fildes) & fd_lut.elem[i].valid)
    {
      host_fd = fd_lut.elem[i].host_fd;
    }
  }
  return host_fd;
}

fd_lut_t remove_fd(fd_t local_fildes, fd_lut_t fd_lut)
{
  uint8_t i;
  for(i=0;i<POSIX_NUM_FILDES;i=i+1)
  {
    if(fd_lut.elem[i].local_fd == local_fildes)
    {
      fd_lut.elem[i].valid = 0;
    }
  }
  return fd_lut;
}

/*
uint1_t fd_is_bram(fd_t local_fildes, fd_lut_t fd_lut)
{
  uint1_t rv = 0;
  uint8_t i;
  for(i=0;i<POSIX_NUM_FILDES;i=i+1)
  {
    if((fd_lut.elem[i].local_fd == local_fildes) & fd_lut.elem[i].valid)
    {
      rv = fd_lut.elem[i].is_bram;
    }
  }
  return rv;
}
*/

// Clock cross into main
posix_h2c_t posix_h2c;
#include "posix_h2c_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "posix_h2c_clock_crossing.h"
// Clock cross out of main
posix_c2h_t posix_c2h;
#include "posix_c2h_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "posix_c2h_clock_crossing.h"

// Slow bulky single state machine for now...
// Need to enforce only one system call "in flight" at a time
// Because otherwise would need more complicated way of 
// tagging and identifying what responses are to what requests
// maybe take hints from software async syscalls? TODO
// OK to have dumb constant priority 
// and valid<->ready combinatorial feedback for now too...
typedef enum fosix_state_t {
  WAIT_REQ, // Wait for request from main
  WAIT_RESP // Wait for response into main
} fosix_state_t;
fosix_state_t fosix_state;
syscall_t in_flight_syscall;
//uint1_t in_flight_syscall_dev_is_bram;
fd_lut_t fosix_fd_lut;

#pragma MAIN_MHZ fosix 150.0
void fosix()
{
  // Inputs
  posix_h2c_t h2c_stdio;
  //posix_h2c_t h2c_bram;
  posix_c2h_t c2h_main;
  // Outputs
  posix_c2h_t c2h_stdio;
  //posix_c2h_t c2h_bram;
  posix_h2c_t h2c_main;
  
  // Read inputs driven from other modules
  //
  // Read h2c_stdio output from fosix_aws_fpga_dma
  posix_h2c_t_array_1_t h2c_stdios;
  h2c_stdios = aws_h2c_READ();
  h2c_stdio = h2c_stdios.data[0];
  //// Read h2c_bram output from bram
  //posix_h2c_t_array_1_t h2c_brams;
  //h2c_brams = bram_h2c_READ();
  //h2c_bram = h2c_brams.data[0];
  // Read c2h output from main
  posix_c2h_t_array_1_t c2h_mains;
  c2h_mains = posix_c2h_READ();
  c2h_main = c2h_mains.data[0];
  //
  // Default outputs so each state is easier to write
  c2h_stdio = POSIX_C2H_T_NULL();
  //c2h_bram = POSIX_C2H_T_NULL();
  h2c_main = POSIX_H2C_T_NULL();
  //////////////////////////////////////////////////////////////////////

  
  // WAIT ON REQUESTS //////////////////////////////////////////////////
  if(fosix_state==WAIT_REQ)
  {
    // Start off signaling ready for all requests from main
    h2c_main = h2c_set_ready(h2c_main);
    
    // Wait for an incoming request from main to a "host device"
    // Find one system call making a request
    // and invalidate the ready for all other requests
    // Depending on requested syscall and host device
    // connect req.valid and req_ready
    // Hard coded devices for now
    // Connect host device with opposite direction flow control
    // And set state for handling response when it comes
    
    // OPEN
    if(c2h_main.sys_open.req.valid)
    {
      h2c_main = h2c_clear_ready(h2c_main);
      
      /*
      // BRAM
      if(path_is_bram(c2h_main.sys_open.req))
      {
        c2h_bram.sys_open.req = c2h_main.sys_open.req;
        h2c_main.sys_open.req_ready = h2c_bram.sys_open.req_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {*/
        // Only other devices are stdio paths for now
        c2h_stdio.sys_open.req = c2h_main.sys_open.req;
        h2c_main.sys_open.req_ready = h2c_stdio.sys_open.req_ready;
        //in_flight_syscall_dev_is_bram = 0;
      //}
      // Move on to waiting for response if was ready for request
      in_flight_syscall = POSIX_OPEN;
      if(h2c_main.sys_open.req_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // WRITE
    else if(c2h_main.sys_write.req.valid)
    {
      h2c_main = h2c_clear_ready(h2c_main);
      
      // Translate from local file descriptor to host fd
      // Before connecting to host c2h device busses
      // Saving a copy of local fd
      fd_t local_fd = c2h_main.sys_write.req.fildes;
      c2h_main.sys_write.req.fildes = translate_fd(c2h_main.sys_write.req.fildes, fosix_fd_lut);
      
      /*
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        c2h_bram.sys_write.req = c2h_main.sys_write.req;
        h2c_main.sys_write.req_ready = h2c_bram.sys_write.req_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {*/
        // Only other devices are stdio paths for now
        c2h_stdio.sys_write.req = c2h_main.sys_write.req;
        h2c_main.sys_write.req_ready = h2c_stdio.sys_write.req_ready;
        //in_flight_syscall_dev_is_bram = 0;
      //}
      // Move on to waiting for response if was ready for request
      in_flight_syscall = POSIX_WRITE;
      if(h2c_main.sys_write.req_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // READ
    else if(c2h_main.sys_read.req.valid)
    {
      h2c_main = h2c_clear_ready(h2c_main);
      
      // Translate from local file descriptor to host fd
      // Before connecting to host c2h device busses
      // Saving a copy of local fd
      fd_t local_fd = c2h_main.sys_read.req.fildes;
      c2h_main.sys_read.req.fildes = translate_fd(c2h_main.sys_read.req.fildes, fosix_fd_lut);
      
      /*
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        c2h_bram.sys_read.req = c2h_main.sys_read.req;
        h2c_main.sys_read.req_ready = h2c_bram.sys_read.req_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {*/
        // Only other devices are stdio paths for now
        c2h_stdio.sys_read.req = c2h_main.sys_read.req;
        h2c_main.sys_read.req_ready = h2c_stdio.sys_read.req_ready;
        //in_flight_syscall_dev_is_bram = 0;
      //}
      // Move on to waiting for response if was ready for request
      in_flight_syscall = POSIX_READ;
      if(h2c_main.sys_read.req_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // CLOSE
    else if(c2h_main.sys_close.req.valid)
    {
      h2c_main = h2c_clear_ready(h2c_main);
      
      // Translate from local file descriptor to host fd
      // Before connecting to host c2h device busses
      // Saving a copy of local fd
      fd_t local_fd = c2h_main.sys_close.req.fildes;
      c2h_main.sys_close.req.fildes = translate_fd(c2h_main.sys_close.req.fildes, fosix_fd_lut);
      
      /*
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        c2h_bram.sys_close.req = c2h_main.sys_close.req;
        h2c_main.sys_close.req_ready = h2c_bram.sys_close.req_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {*/
        // Only other devices are stdio paths for now
        c2h_stdio.sys_close.req = c2h_main.sys_close.req;
        h2c_main.sys_close.req_ready = h2c_stdio.sys_close.req_ready;
        //in_flight_syscall_dev_is_bram = 0;
      //}
      // Move on to waiting for response if was ready for request
      in_flight_syscall = POSIX_CLOSE;
      if(h2c_main.sys_close.req_ready)
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
    // Connect host device with opposite direction flow control
    // And record state based on response
    
    // OPEN
    if(in_flight_syscall == POSIX_OPEN)
    {
      /*
      // BRAM
      if(in_flight_syscall_dev_is_bram)
      {
        h2c_main.sys_open.resp = h2c_bram.sys_open.resp;
        c2h_bram.sys_open.resp_ready = c2h_main.sys_open.resp_ready;
      }
      // ALL OTHERS
      else
      {*/
        // Only other devices are stdio paths for now
        h2c_main.sys_open.resp = h2c_stdio.sys_open.resp;
        c2h_stdio.sys_open.resp_ready = c2h_main.sys_open.resp_ready;
      //}

      // Move on to waiting for next request 
      // if was valid response when ready seen
      if(h2c_main.sys_open.resp.valid & c2h_main.sys_open.resp_ready)
      {
        fosix_state = WAIT_REQ;
        // Make updates as needed based on response
        // OPEN file descriptors table update
        // Insert file host decriptor response into table
        // And give main a local file descriptor
        fd_lut_update_t fd_lut_update = insert_fd(fosix_fd_lut, h2c_main.sys_open.resp.fildes); //, in_flight_syscall_dev_is_bram, );
        fosix_fd_lut = fd_lut_update.fd_lut;
        h2c_main.sys_open.resp.fildes = fd_lut_update.fildes;
      }
    }
    // WRITE
    else if(in_flight_syscall == POSIX_WRITE)
    {
      /*
      // BRAM
      if(in_flight_syscall_dev_is_bram)
      {
        h2c_main.sys_write.resp = h2c_bram.sys_write.resp;
        c2h_bram.sys_write.resp_ready = c2h_main.sys_write.resp_ready;
      }
      // ALL OTHERS
      else
      {*/
        // Only other devices are stdio paths for now
        h2c_main.sys_write.resp = h2c_stdio.sys_write.resp;
        c2h_stdio.sys_write.resp_ready = c2h_main.sys_write.resp_ready;
      //}

      // Move on to waiting for next request 
      // if was valid response when ready seen
      if(h2c_main.sys_write.resp.valid & c2h_main.sys_write.resp_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
    // READ
    else if(in_flight_syscall == POSIX_READ)
    {
      /*
      // BRAM
      if(in_flight_syscall_dev_is_bram)
      {
        h2c_main.sys_read.resp = h2c_bram.sys_read.resp;
        c2h_bram.sys_read.resp_ready = c2h_main.sys_read.resp_ready;
      }
      // ALL OTHERS
      else
      {*/
        // Only other devices are stdio paths for now
        h2c_main.sys_read.resp = h2c_stdio.sys_read.resp;
        c2h_stdio.sys_read.resp_ready = c2h_main.sys_read.resp_ready;
      //}

      // Move on to waiting for next request 
      // if was valid response when ready seen
      if(h2c_main.sys_read.resp.valid & c2h_main.sys_read.resp_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
    // CLOSE
    else if(in_flight_syscall == POSIX_CLOSE)
    {
      /*
      // BRAM
      if(in_flight_syscall_dev_is_bram)
      {
        h2c_main.sys_close.resp = h2c_bram.sys_close.resp;
        c2h_bram.sys_close.resp_ready = c2h_main.sys_close.resp_ready;
      }
      // ALL OTHERS
      else
      {*/
        // Only other devices are stdio paths for now
        h2c_main.sys_close.resp = h2c_stdio.sys_close.resp;
        c2h_stdio.sys_close.resp_ready = c2h_main.sys_close.resp_ready;
      //}

      // Move on to waiting for next request 
      // if was valid response when ready seen
      if(h2c_main.sys_close.resp.valid & c2h_main.sys_close.resp_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
  }
  
  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write c2h_stdio output into fosix_aws_fpga_dma
  posix_c2h_t_array_1_t c2h_stdios;
  c2h_stdios.data[0] = c2h_stdio;
  aws_c2h_WRITE(c2h_stdios);
  //// Write c2h_bram output into bram
  //posix_c2h_t_array_1_t c2h_brams;
  //c2h_brams.data[0] = c2h_bram;
  //bram_c2h_WRITE(c2h_brams);
  // Write h2c_main output into main
  posix_h2c_t_array_1_t h2c_mains;
  h2c_mains.data[0] = h2c_main;
  posix_h2c_WRITE(h2c_mains);
}

