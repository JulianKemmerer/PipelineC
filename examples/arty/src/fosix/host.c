// This is the main program to run on the host to act as a fosix sys device
// gcc host.c -o host -I ../../../../

#include <math.h>
#include <time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

#include "../uart/uart_msg_sw.c"
#include "host_uart.h"

/*
reset;
gcc host.c -o host -I ../../../../
rm /tmp/in;
rm -f /tmp/out;
head -c 16384 < /dev/urandom > /tmp/in
sudo ./host
hexdump -Cv /tmp/in -n 128
sudo hexdump -Cv /tmp/out -n 128
*/

fosix_sys_to_proc_t do_syscall_get_resp(fosix_proc_to_sys_t req, fosix_msg_t msg)
{
  fosix_sys_to_proc_t resp = POSIX_SYS_TO_PROC_T_NULL();
  if(req.sys_open.req.valid)
  {
    // OPEN
    // Temp hacky since dont have flags from FPGA
    // Try to create, will fail if exists
    int fildes = open(req.sys_open.req.path, O_RDWR|O_CREAT, S_IRUSR | S_IWUSR);
    if(fildes<0)
    {
      // Try again not creating the file
      fildes = open(req.sys_open.req.path, O_RDWR, S_IRUSR | S_IWUSR);
    }
    resp.sys_open.resp.fildes = fildes;
    resp.sys_open.resp.valid = 1;
    if(fildes>255 | fildes<0)
    {
      printf("File descriptor too large / err %d, %s ...TODO: fix.\n", fildes, req.sys_open.req.path);
      perror("Failed to open");
      exit(-1);
    }
  }
  else if(req.sys_write.req.valid)
  {
    // WRITE
    //printf("FOSIX: WRITE\n");
    resp.sys_write.resp.nbyte = write(req.sys_write.req.fildes, &(req.sys_write.req.buf[0]), req.sys_write.req.nbyte);
    resp.sys_write.resp.valid = 1;
  }
  else if(req.sys_read.req.valid)
  {
    // READ
    resp.sys_read.resp.nbyte = read(req.sys_read.req.fildes, &(resp.sys_read.resp.buf[0]), req.sys_read.req.nbyte);
    //printf("FOSIX: READ fd %d, nbyte %d, rv %d\n", req.sys_read.req.fildes, req.sys_read.req.nbyte, resp.sys_read.resp.nbyte);
    resp.sys_read.resp.valid = 1;
  }
  else if(req.sys_close.req.valid)
  {
    // CLOSE
    //printf("FOSIX: CLOSE\n");
    resp.sys_close.resp.err = close(req.sys_close.req.fildes);
    resp.sys_close.resp.valid = 1;
    if(resp.sys_close.resp.err)
    {
      printf("Close err? fd %d\n", req.sys_close.req.fildes);
      exit(-1);
    }
  }
  else
  {
    printf("FOSIX: TIMEOUT / UNKNOWN SYSTEM CALL REQUEST: %d\n", decode_syscall_id(msg));
  }
  return resp;
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
    fosix_msg_t read_msg = uart_msg_t_to_fosix_msg_t(read_uart_msg);
    //printf("FOSIX: Read msg...\n");
    
    // Convert to sys request struct
    fosix_proc_to_sys_t request = msg_to_request(read_msg);
    
    // Do the requested syscall and form response
    fosix_sys_to_proc_t response = do_syscall_get_resp(request, read_msg);
    
    // Convert to message
    fosix_msg_s write_msg = response_to_msg(response);
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
