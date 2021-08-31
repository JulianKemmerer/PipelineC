// POSIX-like interfaces for FPGA...FOSIX?
// System calls requests are made from a process to the system
// System calls responses are from the system to a process

// Types, constants, etc for fosix system calls
#include "uintN_t.h"
#include "intN_t.h"

#pragma once

// Syscall table
#define syscall_num_t uint8_t
#define FOSIX_READ  0
#define FOSIX_WRITE 1
#define FOSIX_OPEN  2
#define FOSIX_CLOSE 3
// TODO memfd_create
#define FOSIX_UNKNOWN 255

// Exchanging the small/est possible messages / buffer sizes
// syscall id byte
// followed by syscall specific bytes
// Path is really largest requirement
#define fosix_fd_t int32_t
#define fosix_size_t uint32_t
#define FOSIX_BUF_SIZE 32
#define FOSIX_LOG2_BUF_SIZE 5
#define FOSIX_PATH_SIZE 32

typedef struct open_req_t
{
	char path[FOSIX_PATH_SIZE];
} open_req_t;
typedef struct open_resp_t
{
	fosix_fd_t fildes;
} open_resp_t;

typedef struct write_req_t
{
	fosix_fd_t fildes;
	uint8_t buf[FOSIX_BUF_SIZE];
	fosix_size_t nbyte;
} write_req_t;
typedef struct write_resp_t
{
	fosix_size_t nbyte;
} write_resp_t;

typedef struct read_req_t
{
	fosix_fd_t fildes;
	fosix_size_t nbyte;
} read_req_t;
typedef struct read_resp_t
{
	fosix_size_t nbyte;
  uint8_t buf[FOSIX_BUF_SIZE];
} read_resp_t;

typedef struct close_req_t
{
	fosix_fd_t fildes;
} close_req_t;
typedef struct close_resp_t
{
	int32_t err;
} close_resp_t;

// Types holding the wires of all parsed message struct types
typedef struct fosix_parsed_req_msg_t
{
  syscall_num_t syscall_num; // use as valid+decode
	open_req_t sys_open;
	write_req_t sys_write;
  read_req_t sys_read;
  close_req_t sys_close;
} fosix_parsed_req_msg_t;
typedef struct fosix_parsed_resp_msg_t
{
  syscall_num_t syscall_num; // use as valid+decode
	open_resp_t sys_open;
	write_resp_t sys_write;
  read_resp_t sys_read;
  close_resp_t sys_close;
} fosix_parsed_resp_msg_t;

