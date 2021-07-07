// POSIX-like interfaces for FPGA...FOSIX?
// System calls requests are made from a process to the system
// System calls responses are from a the system to a process

// Types, constants, etc for fosix system calls
#include "uintN_t.h"
#include "intN_t.h"

#pragma once

// Syscall table
#define syscall_t uint8_t
#define FOSIX_READ  0
#define FOSIX_WRITE 1
#define FOSIX_OPEN  2
#define FOSIX_CLOSE 3
#define FOSIX_UNKNOWN 255

#define fosix_fd_t int32_t
#define fosix_size_t uint32_t
#define FOSIX_BUF_SIZE 128
#define FOSIX_LOG2_BUF_SIZE 7
#define FOSIX_PATH_SIZE 16

typedef struct open_req_t
{
	char path[FOSIX_PATH_SIZE];
	uint1_t valid;
} open_req_t;
open_req_t OPEN_REQ_T_NULL()
{
  open_req_t rv;
  fosix_size_t i;
  for(i=0;i<FOSIX_PATH_SIZE;i=i+1)
  {
    rv.path[i] = 0;
  }
  rv.valid = 0;
  return rv;
}

typedef struct open_proc_to_sys_t
{
	open_req_t req;
	uint1_t resp_ready;
} open_proc_to_sys_t;
open_proc_to_sys_t OPEN_PROC_TO_SYS_T_NULL()
{
  open_proc_to_sys_t rv;
  rv.req = OPEN_REQ_T_NULL();
  rv.resp_ready = 0;
  return rv;
}

typedef struct open_resp_t
{
	fosix_fd_t fildes;
  uint1_t valid;
} open_resp_t;
open_resp_t OPEN_RESP_T_NULL()
{
  open_resp_t rv;
  rv.fildes = -1;
  rv.valid = 0;
  return rv;
}

typedef struct open_sys_to_proc_t
{
	open_resp_t resp;
	uint1_t req_ready;
} open_sys_to_proc_t;
open_sys_to_proc_t OPEN_SYS_TO_PROC_T_NULL()
{
  open_sys_to_proc_t rv;
  rv.resp = OPEN_RESP_T_NULL();
  rv.req_ready = 0;
  return rv;
}

typedef struct write_req_t
{
	fosix_fd_t fildes;
	uint8_t buf[FOSIX_BUF_SIZE];
	fosix_size_t nbyte;
	uint1_t valid;
} write_req_t;
write_req_t WRITE_REQ_T_NULL()
{
  write_req_t rv;
  rv.fildes = -1;
  fosix_size_t i;
  for(i=0;i<FOSIX_BUF_SIZE;i=i+1)
  {
    rv.buf[i] = 0;
  }
  rv.nbyte = 0;
  rv.valid = 0;
  return rv;
}

typedef struct write_proc_to_sys_t
{
	write_req_t req;
	uint1_t resp_ready;
} write_proc_to_sys_t;
write_proc_to_sys_t WRITE_PROC_TO_SYS_T_NULL()
{
  write_proc_to_sys_t rv;
  rv.req = WRITE_REQ_T_NULL();
  rv.resp_ready = 0;
  return rv;
}

typedef struct write_resp_t
{
	fosix_size_t nbyte;
	uint1_t valid;
} write_resp_t;
write_resp_t WRITE_RESP_T_NULL()
{
  write_resp_t rv;
  rv.nbyte = 0;
  rv.valid = 0;
  return rv;
}

typedef struct write_sys_to_proc_t
{
  write_resp_t resp;
	uint1_t req_ready;
} write_sys_to_proc_t;
write_sys_to_proc_t WRITE_SYS_TO_PROC_T_NULL()
{
  write_sys_to_proc_t rv;
  rv.resp = WRITE_RESP_T_NULL();
  rv.req_ready = 0;
  return rv;
}

typedef struct read_req_t
{
	fosix_fd_t fildes;
	fosix_size_t nbyte;
	uint1_t valid;
} read_req_t;
read_req_t READ_REQ_T_NULL()
{
  read_req_t rv;
  rv.fildes = -1;
  rv.nbyte = 0;
  rv.valid = 0;
  return rv;
}

typedef struct read_proc_to_sys_t
{
	read_req_t req;
	uint1_t resp_ready;
} read_proc_to_sys_t;
read_proc_to_sys_t READ_PROC_TO_SYS_T_NULL()
{
  read_proc_to_sys_t rv;
  rv.req = READ_REQ_T_NULL();
  rv.resp_ready = 0;
  return rv;
}

typedef struct read_resp_t
{
	fosix_size_t nbyte;
  uint8_t buf[FOSIX_BUF_SIZE];
	uint1_t valid;
} read_resp_t;
read_resp_t READ_RESP_T_NULL()
{
  read_resp_t rv;
  rv.nbyte = 0;
  fosix_size_t i;
  for(i=0;i<FOSIX_BUF_SIZE;i=i+1)
  {
    rv.buf[i] = 0;
  }
  rv.valid = 0;
  return rv;
}

typedef struct read_sys_to_proc_t
{
  read_resp_t resp;
	uint1_t req_ready;
} read_sys_to_proc_t;
read_sys_to_proc_t READ_SYS_TO_PROC_T_NULL()
{
  read_sys_to_proc_t rv;
  rv.resp = READ_RESP_T_NULL();
  rv.req_ready = 0;
  return rv;
}

typedef struct close_req_t
{
	fosix_fd_t fildes;
	uint1_t valid;
} close_req_t;
close_req_t CLOSE_REQ_T_NULL()
{
  close_req_t rv;
  rv.fildes = -1;
  rv.valid = 0;
  return rv;
}

typedef struct close_proc_to_sys_t
{
	close_req_t req;
	uint1_t resp_ready;
} close_proc_to_sys_t;
close_proc_to_sys_t CLOSE_PROC_TO_SYS_T_NULL()
{
  close_proc_to_sys_t rv;
  rv.req = CLOSE_REQ_T_NULL();
  rv.resp_ready = 0;
  return rv;
}

typedef struct close_resp_t
{
	int32_t err;
  uint1_t valid;
} close_resp_t;
close_resp_t CLOSE_RESP_T_NULL()
{
  close_resp_t rv;
  rv.err = 0;
  rv.valid = 0;
  return rv;
}

typedef struct close_sys_to_proc_t
{
	close_resp_t resp;
	uint1_t req_ready;
} close_sys_to_proc_t;
close_sys_to_proc_t CLOSE_SYS_TO_PROC_T_NULL()
{
  close_sys_to_proc_t rv;
  rv.resp = CLOSE_RESP_T_NULL();
  rv.req_ready = 0;
  return rv;
}

typedef struct fosix_proc_to_sys_t
{
	open_proc_to_sys_t sys_open;
	write_proc_to_sys_t sys_write;
  read_proc_to_sys_t sys_read;
  close_proc_to_sys_t sys_close;
} fosix_proc_to_sys_t;
fosix_proc_to_sys_t POSIX_PROC_TO_SYS_T_NULL()
{
  fosix_proc_to_sys_t rv;
  rv.sys_open = OPEN_PROC_TO_SYS_T_NULL();
  rv.sys_write = WRITE_PROC_TO_SYS_T_NULL();
  rv.sys_read = READ_PROC_TO_SYS_T_NULL();
  rv.sys_close = CLOSE_PROC_TO_SYS_T_NULL();
  return rv;
}

typedef struct fosix_sys_to_proc_t
{
	open_sys_to_proc_t sys_open;
	write_sys_to_proc_t sys_write;
  read_sys_to_proc_t sys_read;
  close_sys_to_proc_t sys_close;
} fosix_sys_to_proc_t;
fosix_sys_to_proc_t POSIX_SYS_TO_PROC_T_NULL()
{
  fosix_sys_to_proc_t rv;
  rv.sys_open = OPEN_SYS_TO_PROC_T_NULL();
  rv.sys_write = WRITE_SYS_TO_PROC_T_NULL();
  rv.sys_read = READ_SYS_TO_PROC_T_NULL();
  rv.sys_close = CLOSE_SYS_TO_PROC_T_NULL();
  return rv;
}

// Helper funcs for setting certain flags
fosix_sys_to_proc_t sys_to_proc_clear_ready(fosix_sys_to_proc_t sys_to_proc)
{
  sys_to_proc.sys_open.req_ready = 0;
  sys_to_proc.sys_write.req_ready = 0;
  sys_to_proc.sys_read.req_ready = 0;
  sys_to_proc.sys_close.req_ready = 0;
  return sys_to_proc;
}
fosix_sys_to_proc_t sys_to_proc_set_ready(fosix_sys_to_proc_t sys_to_proc)
{
  sys_to_proc.sys_open.req_ready = 1;
  sys_to_proc.sys_write.req_ready = 1;
  sys_to_proc.sys_read.req_ready = 1;
  sys_to_proc.sys_close.req_ready = 1;
  return sys_to_proc;
}

// Helper macros
#define SYSCALL_DECL(name) \
/* State for using syscalls */ \
static syscall_io_t name##_reg; \
/* Syscall IO signaling keeps regs contents */ \
syscall_io_t name = name##_reg; \
/* Other than start bit which auto clears*/ \
name.start = 0;

#define SYSCALL(name, sys_to_proc, proc_to_sys) \
/* Auto clear done*/ \
name.done = 0; \
if(name##_reg.start) \
{ \
  syscall_func_t name##_sc = syscall_func(sys_to_proc, name##_reg); \
  proc_to_sys = name##_sc.proc_to_sys; \
  name = name##_sc.syscall_io; \
} \
/* Ignore start bit if during done time */ \
if(name.done | name##_reg.done) \
{ \
  name.start = 0; \
} \
name##_reg = name;

