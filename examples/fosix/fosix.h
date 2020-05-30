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

typedef struct open_c2h_t
{
	open_req_t req;
	uint1_t resp_ready;
} open_c2h_t;
open_c2h_t OPEN_C2H_T_NULL()
{
  open_c2h_t rv;
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

typedef struct open_h2c_t
{
	open_resp_t resp;
	uint1_t req_ready;
} open_h2c_t;
open_h2c_t OPEN_H2C_T_NULL()
{
  open_h2c_t rv;
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

typedef struct write_c2h_t
{
	write_req_t req;
	uint1_t resp_ready;
} write_c2h_t;
write_c2h_t WRITE_C2H_T_NULL()
{
  write_c2h_t rv;
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

typedef struct write_h2c_t
{
  write_resp_t resp;
	uint1_t req_ready;
} write_h2c_t;
write_h2c_t WRITE_H2C_T_NULL()
{
  write_h2c_t rv;
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

typedef struct read_c2h_t
{
	read_req_t req;
	uint1_t resp_ready;
} read_c2h_t;
read_c2h_t READ_C2H_T_NULL()
{
  read_c2h_t rv;
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

typedef struct read_h2c_t
{
  read_resp_t resp;
	uint1_t req_ready;
} read_h2c_t;
read_h2c_t READ_H2C_T_NULL()
{
  read_h2c_t rv;
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

typedef struct close_c2h_t
{
	close_req_t req;
	uint1_t resp_ready;
} close_c2h_t;
close_c2h_t CLOSE_C2H_T_NULL()
{
  close_c2h_t rv;
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

typedef struct close_h2c_t
{
	close_resp_t resp;
	uint1_t req_ready;
} close_h2c_t;
close_h2c_t CLOSE_H2C_T_NULL()
{
  close_h2c_t rv;
  rv.resp = CLOSE_RESP_T_NULL();
  rv.req_ready = 0;
  return rv;
}

typedef struct posix_c2h_t
{
	open_c2h_t sys_open;
	write_c2h_t sys_write;
  read_c2h_t sys_read;
  close_c2h_t sys_close;
} posix_c2h_t;
posix_c2h_t POSIX_C2H_T_NULL()
{
  posix_c2h_t rv;
  rv.sys_open = OPEN_C2H_T_NULL();
  rv.sys_write = WRITE_C2H_T_NULL();
  rv.sys_read = READ_C2H_T_NULL();
  rv.sys_close = CLOSE_C2H_T_NULL();
  return rv;
}

typedef struct posix_h2c_t
{
	open_h2c_t sys_open;
	write_h2c_t sys_write;
  read_h2c_t sys_read;
  close_h2c_t sys_close;
} posix_h2c_t;
posix_h2c_t POSIX_H2C_T_NULL()
{
  posix_h2c_t rv;
  rv.sys_open = OPEN_H2C_T_NULL();
  rv.sys_write = WRITE_H2C_T_NULL();
  rv.sys_read = READ_H2C_T_NULL();
  rv.sys_close = CLOSE_H2C_T_NULL();
  return rv;
}

// Helper funcs for setting certain flags
posix_h2c_t h2c_clear_ready(posix_h2c_t h2c)
{
  h2c.sys_open.req_ready = 0;
  h2c.sys_write.req_ready = 0;
  h2c.sys_read.req_ready = 0;
  h2c.sys_close.req_ready = 0;
  return h2c;
}
posix_h2c_t h2c_set_ready(posix_h2c_t h2c)
{
  h2c.sys_open.req_ready = 1;
  h2c.sys_write.req_ready = 1;
  h2c.sys_read.req_ready = 1;
  h2c.sys_close.req_ready = 1;
  return h2c;
}
