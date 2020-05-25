// Types, constants, etc for fosix sys calls

#pragma once

#define fd_t int32_t
#define size_t uint32_t
#define BUF_SIZE 128
#define PATH_SIZE 16

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

typedef struct posix_c2h_t
{
	open_c2h_t sys_open;
	write_c2h_t sys_write;
} posix_c2h_t;
posix_c2h_t POSIX_C2H_T_NULL()
{
  posix_c2h_t rv;
  rv.sys_open = OPEN_C2H_T_NULL();
  rv.sys_write = WRITE_C2H_T_NULL();
  return rv;
}

typedef struct posix_h2c_t
{
	open_h2c_t sys_open;
	write_h2c_t sys_write;
} posix_h2c_t;
posix_h2c_t POSIX_H2C_T_NULL()
{
  posix_h2c_t rv;
  rv.sys_open = OPEN_H2C_T_NULL();
  rv.sys_write = WRITE_H2C_T_NULL();
  return rv;
}
