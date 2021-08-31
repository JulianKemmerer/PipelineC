// This is the main program to run on the host to act as a fosix sys device
// gcc host_arty.c -o host_arty -I ../../

#include <math.h>
#include <time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

// Code defining msgs to from FPGA
#include "../arty/src/uart/uart_msg_sw.c"
#include "host_uart.h"
#include "fosix_msg_sw.h"

// Do the request system call and return response message
fosix_msg_s do_syscall_get_resp(fosix_msg_t read_msg_data)
{
  // Implied valid from getting read data
  fosix_msg_s read_msg;
  read_msg.data = read_msg_data;
  read_msg.valid = 1;
  
  // Parse incoming request message
  fosix_parsed_req_msg_t req = msg_to_request(read_msg);
  fosix_msg_decoded_t decoded_msg = decode_msg(read_msg);
  // Prepare a response
  fosix_parsed_resp_msg_t resp;
  resp.syscall_num = req.syscall_num;
  if(req.syscall_num==FOSIX_OPEN)
  {
    // OPEN
    // Temp hacky since dont have flags from FPGA
    // Try to create, will fail if exists
    int fildes = open(req.sys_open.path, O_RDWR|O_CREAT, S_IRUSR | S_IWUSR);
    if(fildes<0)
    {
      // Try again not creating the file
      fildes = open(req.sys_open.path, O_RDWR, S_IRUSR | S_IWUSR);
    }
    resp.sys_open.fildes = fildes;
    //printf("FOSIX: OPEN %s %d\n",req.sys_open.path, resp.sys_open.fildes);
    if(fildes>255 | fildes<0)
    {
      printf("File descriptor too large / err %d, %s ...TODO: fix.\n", fildes, req.sys_open.path);
      perror("Failed to open");
      exit(-1);
    }
  }
  else if(req.syscall_num==FOSIX_WRITE)
  {
    // WRITE
    //printf("FOSIX: WRITE FD %d\n",req.sys_write.fildes);
    resp.sys_write.nbyte = write(req.sys_write.fildes, &(req.sys_write.buf[0]), req.sys_write.nbyte);
  }
  else if(req.syscall_num==FOSIX_READ)
  {
    // READ
    resp.sys_read.nbyte = read(req.sys_read.fildes, &(resp.sys_read.buf[0]), req.sys_read.nbyte);
    //printf("FOSIX: READ fd %d, nbyte %d, rv %d\n", req.sys_read.fildes, req.sys_read.nbyte, resp.sys_read.nbyte);
  }
  else if(req.syscall_num==FOSIX_CLOSE)
  {
    // CLOSE
    //printf("FOSIX: CLOSE\n");
    resp.sys_close.err = close(req.sys_close.fildes);
    if(resp.sys_close.err)
    {
      printf("Close err? fd %d\n", req.sys_close.fildes);
      exit(-1);
    }
  }
  else
  {
    printf("FOSIX: TIMEOUT / UNKNOWN SYSTEM CALL REQUEST: %d\n", decoded_msg.syscall_num);
  }
  // Pack up the response into a message
  fosix_msg_s write_msg;
  write_msg.data = response_to_msg(resp);
  write_msg.valid = resp.syscall_num != FOSIX_UNKNOWN;
  return write_msg;
}

// Init + control loop + close
//  TODO exit control loop correctly?
int main(int argc, char **argv) 
{
	// Init messages to/from FPGA
  printf("Initializing messages to/from FPGA...\n");
	init_msgs();
  
	// Control loop
  printf("Beginning FOSIX Host control loop (you should reset FPGA now)...\n");
  int exit = 0;
  while(!exit)
  {
    // Read request dma msg
    //printf("FOSIX: Reading msg...\n");
    uart_msg_t read_uart_msg;
    msg_read(&read_uart_msg);
    
    // Convert to message
    fosix_msg_t read_msg = uart_msg_t_to_fosix_msg_t(read_uart_msg);
    //printf("FOSIX: Read msg...\n");
    
    // Do the requested syscall and form response
    fosix_msg_s write_msg = do_syscall_get_resp(read_msg);
    
    // Convert to message
    uart_msg_s write_uart_msg = fosix_msg_s_to_uart_msg_s(write_msg);
    
    // Write response msg 
    if(write_uart_msg.valid)
    {
      //printf("FOSIX: Writing msg...\n");
      msg_write(&(write_uart_msg.data));
      //printf("FOSIX: Wrote msg...\n");
    }
    else
    {
      printf("FOSIX: NO SYSTEM CALL RESPONSE\n");
      exit = 1;
    }
  }

	// Close direct memory access to/from FPGA
  printf("Closing messages to/from FPGA...\n");
	close_msgs();    
}
