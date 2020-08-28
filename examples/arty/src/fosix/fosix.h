// POSIX-like interfaces for FPGA...FOSIX?
// System calls requests are made from a process to the system
// System calls responses are from a the system to a process

// Types, constants, etc for fosix system calls

#pragma once

#define fd_t int32_t
#define size_t uint32_t
#define BUF_SIZE 128
#define LOG2_BUF_SIZE 7
#define PATH_SIZE 16

typedef struct open_req_t
{
	char path[PATH_SIZE];
	uint8_t valid; // TODO replace with uint1_t
} open_req_t;
open_req_t OPEN_REQ_T_NULL()
{
  open_req_t rv;
  size_t i;
  for(i=0;i<PATH_SIZE;i=i+1)
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
	fd_t fildes;
  uint8_t valid; // TODO replace with uint1_t
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
	fd_t fildes;
	uint8_t buf[BUF_SIZE];
	size_t nbyte;
	uint8_t valid; // TODO replace with uint1_t
} write_req_t;
write_req_t WRITE_REQ_T_NULL()
{
  write_req_t rv;
  rv.fildes = -1;
  size_t i;
  for(i=0;i<BUF_SIZE;i=i+1)
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
	size_t nbyte;
	uint8_t valid; // TODO replace with uint1_t
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
	fd_t fildes;
	size_t nbyte;
	uint8_t valid; // TODO replace with uint1_t
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
	size_t nbyte;
  uint8_t buf[BUF_SIZE];
	uint8_t valid; // TODO replace with uint1_t
} read_resp_t;
read_resp_t READ_RESP_T_NULL()
{
  read_resp_t rv;
  rv.nbyte = 0;
  size_t i;
  for(i=0;i<BUF_SIZE;i=i+1)
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
	fd_t fildes;
	uint8_t valid; // TODO replace with uint1_t
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
  uint8_t valid; // TODO replace with uint1_t
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

typedef struct posix_proc_to_sys_t
{
	open_proc_to_sys_t sys_open;
	write_proc_to_sys_t sys_write;
  read_proc_to_sys_t sys_read;
  close_proc_to_sys_t sys_close;
} posix_proc_to_sys_t;
posix_proc_to_sys_t POSIX_PROC_TO_SYS_T_NULL()
{
  posix_proc_to_sys_t rv;
  rv.sys_open = OPEN_PROC_TO_SYS_T_NULL();
  rv.sys_write = WRITE_PROC_TO_SYS_T_NULL();
  rv.sys_read = READ_PROC_TO_SYS_T_NULL();
  rv.sys_close = CLOSE_PROC_TO_SYS_T_NULL();
  return rv;
}

typedef struct posix_sys_to_proc_t
{
	open_sys_to_proc_t sys_open;
	write_sys_to_proc_t sys_write;
  read_sys_to_proc_t sys_read;
  close_sys_to_proc_t sys_close;
} posix_sys_to_proc_t;
posix_sys_to_proc_t POSIX_SYS_TO_PROC_T_NULL()
{
  posix_sys_to_proc_t rv;
  rv.sys_open = OPEN_SYS_TO_PROC_T_NULL();
  rv.sys_write = WRITE_SYS_TO_PROC_T_NULL();
  rv.sys_read = READ_SYS_TO_PROC_T_NULL();
  rv.sys_close = CLOSE_SYS_TO_PROC_T_NULL();
  return rv;
}

// Helper funcs for setting certain flags
posix_sys_to_proc_t sys_to_proc_clear_ready(posix_sys_to_proc_t sys_to_proc)
{
  sys_to_proc.sys_open.req_ready = 0;
  sys_to_proc.sys_write.req_ready = 0;
  sys_to_proc.sys_read.req_ready = 0;
  sys_to_proc.sys_close.req_ready = 0;
  return sys_to_proc;
}
posix_sys_to_proc_t sys_to_proc_set_ready(posix_sys_to_proc_t sys_to_proc)
{
  sys_to_proc.sys_open.req_ready = 1;
  sys_to_proc.sys_write.req_ready = 1;
  sys_to_proc.sys_read.req_ready = 1;
  sys_to_proc.sys_close.req_ready = 1;
  return sys_to_proc;
}
