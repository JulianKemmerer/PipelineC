// This is the main program to run on host for supporting fosix

#include <math.h>
#include <time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

#include "../aws-fpga-dma/dma_msg_sw.c"
#include "protocol.h"

posix_h2c_t do_syscall_get_resp(posix_c2h_t req)
{
  posix_h2c_t resp;
  if(req.sys_open.req.valid)
  {
    resp.sys_open.resp.fildes = open(req.sys_open.req.path, O_RDWR); //, 0777);
    resp.sys_open.resp.valid = 1;
  }
  else if(req.sys_write.req.valid)
  {
    resp.sys_write.resp.nbyte = write(req.sys_write.req.fildes, &(req.sys_write.req.buf[0]), req.sys_write.req.nbyte);
    resp.sys_write.resp.valid = 1;
  }
  return resp;
}

// Init + control loop + close
//  TODO exit control loop correctly?
int main(int argc, char **argv) 
{
	// Init direct memory access to/from FPGA
	init_dma();
	
	// Control loop
  while(1)
  {
    // Read request dma msg
    dma_msg_t read_msg = dma_read();
    
    // Convert to host request struct
    posix_c2h_t request = dma_to_request(read_msg);
    
    // Do the requested syscall and form response
    posix_h2c_t response = do_syscall_get_resp(request);
    
    // Convert to dma message
    dma_msg_s write_msg = response_to_dma(response);
    
    // Write response dma msg 
    if(write_msg.valid) dma_write(write_msg.data);  
  }  

	// Close direct memory access to/from FPGA
	close_dma();    
}
