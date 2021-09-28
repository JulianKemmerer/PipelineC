#include "compiler.h"

#include "fosix.h"

// System devices?
// Host OS device hooks (UART based)
#include "sys_host_uart.c"
// BRAM system device hooks
#include "sys_bram.c"

// Syscall helper func
// Special type for user storage that isnt full messages?
// Possible to use a single or two messages?
typedef struct syscall_io_t
{
  // As written, with input and output registers and start+done signals, each syscall takes at least 2 clocks
  // (could instead use: duplicated instances or share an instance input and output wires need FEEDBACK pragma)
  uint1_t start; // Start flag (inputs valid)
  uint1_t done; // Done flag (outputs valid)
  syscall_num_t num; // System call number in progress
  fosix_fd_t fd; // File descriptor for syscall
  char path[FOSIX_PATH_SIZE]; // Path buf for open()
  uint8_t buf[FOSIX_BUF_SIZE]; // IO buf for write+read
  fosix_size_t buf_nbytes; // Input number of bytes
  fosix_size_t buf_nbytes_ret; // Return count of bytes
}syscall_io_t;

// Helper FSM for one at a time in flight
// make request, then wait for response, FOSIX operations
typedef enum syscall_state_t {
  REQ,
  RESP
} syscall_state_t;
typedef struct syscall_func_t 
{
  fosix_proc_to_sys_t proc_to_sys;
  syscall_io_t syscall_io;
}syscall_func_t;
syscall_func_t syscall_func(fosix_sys_to_proc_t sys_to_proc, syscall_io_t syscall_io)
{
  // Default output/reset/null values
  syscall_func_t o;
  o.syscall_io = syscall_io; // Default pass through
  // Except done flag
  o.syscall_io.done = 0;
  
  // Subroutine state
  static syscall_state_t state; 
  
  if(state==REQ)
  {
    // Request
    fosix_msg_decoded_t decoded_msg = UNKNOWN_MSG();
    decoded_msg.syscall_num = syscall_io.num;
    if(syscall_io.num==FOSIX_OPEN)
    {
      // Request to open
      open_req_t open_req;
      open_req.path = syscall_io.path;
      OPEN_REQ_T_TO_BYTES(decoded_msg.payload_data, open_req)
      o.proc_to_sys.msg.data = decoded_msg_to_msg(decoded_msg);
      o.proc_to_sys.msg.valid = 1;        
      // Keep trying to request until finally was ready
      if(sys_to_proc.proc_to_sys_msg_ready)
      {
        // Then wait for response
        state = RESP;
      }
    }
    else if(syscall_io.num==FOSIX_WRITE)
    {
      // Request to write
      write_req_t write_req;
      write_req.buf = syscall_io.buf;
      write_req.nbyte = syscall_io.buf_nbytes;
      write_req.fildes = syscall_io.fd;
      WRITE_REQ_T_TO_BYTES(decoded_msg.payload_data, write_req)
      o.proc_to_sys.msg.data = decoded_msg_to_msg(decoded_msg);
      o.proc_to_sys.msg.valid = 1;
      // Keep trying to request until finally was ready
      if(sys_to_proc.proc_to_sys_msg_ready)
      {
        // Then wait for response
        state = RESP;
      }
    }
    else if(syscall_io.num==FOSIX_READ)
    {
      // Request to read
      read_req_t read_req;
      read_req.nbyte = syscall_io.buf_nbytes;
      read_req.fildes = syscall_io.fd;
      READ_REQ_T_TO_BYTES(decoded_msg.payload_data, read_req)
      o.proc_to_sys.msg.data = decoded_msg_to_msg(decoded_msg);
      o.proc_to_sys.msg.valid = 1;
      // Keep trying to request until finally was ready
      if(sys_to_proc.proc_to_sys_msg_ready)
      {
        // Then wait for response
        state = RESP;
      }
    }
    else if(syscall_io.num==FOSIX_CLOSE)
    {
      // Request to close
      close_req_t close_req;
      close_req.fildes = syscall_io.fd;
      CLOSE_REQ_T_TO_BYTES(decoded_msg.payload_data, close_req)
      o.proc_to_sys.msg.data = decoded_msg_to_msg(decoded_msg);
      o.proc_to_sys.msg.valid = 1;
      // Keep trying to request until finally was ready
      if(sys_to_proc.proc_to_sys_msg_ready)
      {
        // Then wait for response
        state = RESP;
      }
    }
  }
  else if(state==RESP)
  {
    fosix_parsed_resp_msg_t resp = msg_to_response(sys_to_proc.msg);
    if(syscall_io.num==FOSIX_OPEN)
    {
      // Wait here ready for response
      o.proc_to_sys.sys_to_proc_msg_ready = 1;
      // Until we get valid response
      if(resp.syscall_num == FOSIX_OPEN)
      { 
        // Return file descriptor
        o.syscall_io.fd = resp.sys_open.fildes;
        // Signal done, return to start
        o.syscall_io.done = 1;
        state = REQ;
      }
    }
    else if(syscall_io.num==FOSIX_WRITE)
    {
      // Wait here ready for response
      o.proc_to_sys.sys_to_proc_msg_ready = 1;
      // Until we get valid response
      if(resp.syscall_num == FOSIX_WRITE)
      { 
        // Save syscall_io.num bytes
        o.syscall_io.buf_nbytes_ret = resp.sys_write.nbyte;
        // Signal done, return to start
        o.syscall_io.done = 1;
        state = REQ;
      }
    }
    else if(syscall_io.num==FOSIX_READ)
    {
      // Wait here ready for response
      o.proc_to_sys.sys_to_proc_msg_ready = 1;
      // Until we get valid response
      if(resp.syscall_num == FOSIX_READ)
      { 
        // Save syscall_io.num bytes and bytes
        o.syscall_io.buf_nbytes_ret = resp.sys_read.nbyte;
        o.syscall_io.buf = resp.sys_read.buf;
        // Signal done, return to start
        o.syscall_io.done = 1;
        state = REQ;
      }
    }
    else if(syscall_io.num==FOSIX_CLOSE)
    {
      // Wait here ready for response
      o.proc_to_sys.sys_to_proc_msg_ready = 1;
      // Until we get valid response
      if(resp.syscall_num == FOSIX_CLOSE)
      { 
        // Not looking at err code
        // Signal done, return to start
        o.syscall_io.done = 1;
        state = REQ;
      }
    }
  }
  
  return o;
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

// Do not modify inputs after start, and do not use outputs until done

#define OPEN_THEN(syscall_io, fd_out, path_in, then) \
/* Subroutine arguments*/ \
syscall_io.path = path_in; \
syscall_io.start = 1; \
syscall_io.num = FOSIX_OPEN; \
/* Syscall return values*/ \
fd_out = syscall_io.fd; /* File descriptor*/ \
if(syscall_io.done) \
{ \
  /* State to return to from syscall*/ \
  then \
}

#define WRITE_THEN(syscall_io, rv, fd_in, buf_in, count, then) \
/* Subroutine arguments */ \
syscall_io.buf = buf_in; \
syscall_io.buf_nbytes = count; \
syscall_io.fd = fd_in; \
syscall_io.start = 1; \
syscall_io.num = FOSIX_WRITE; \
/* Syscall return values */ \
rv = syscall_io.buf_nbytes_ret; \
if(syscall_io.done) \
{ \
  /* State to return to from syscall */ \
  then \
}

#define STRWRITE_THEN(syscall_io, rv, fd_in, buf_in, then) \
WRITE_THEN(syscall_io, rv, fd_in, buf_in, strlen(buf_in)+1 /* w/ null term*/, then)

#define READ_THEN(syscall_io, rv, fd_in, buf_out, count, then) \
/* Subroutine arguments */ \
syscall_io.buf_nbytes = count; \
syscall_io.fd = fd_in; \
syscall_io.start = 1; \
syscall_io.num = FOSIX_READ; \
/* Syscall return values */ \
buf_out = syscall_io.buf; \
rv = syscall_io.buf_nbytes_ret; \
if(syscall_io.done) \
{ \
  /* State to return to from syscall */ \
  then \
}

#define CLOSE_THEN(syscall_io, rv, fd_in, then) \
/* Subroutine arguments */ \
syscall_io.fd = fd_in; \
syscall_io.start = 1; \
syscall_io.num = FOSIX_CLOSE; \
/* Syscall return values */ \
rv = 0; /* Assume ok for now */ \
if(syscall_io.done) \
{ \
  /* State to return to from syscall */ \
  then \
}


// NEED Antikernel like NoC routing instead of using file descriptor numbers + paths
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
#include "clock_crossing/main_sys_to_proc.h"
// Clock cross out of main
fosix_proc_to_sys_t main_proc_to_sys;
#include "clock_crossing/main_proc_to_sys.h"

// NEED Antikernel like NoC routing instead of using file descriptor numbers+paths
// Slow bulky single state machine 'router' for now...
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
syscall_num_t in_flight_syscall;
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
  fosix_proc_to_sys_t proc_to_sys_host;
  fosix_proc_to_sys_t proc_to_sys_bram;
  fosix_sys_to_proc_t sys_to_proc_main;
  //////////////////////////////////////////////////////////////////////

  if(fosix_state==RESET)
  {
    fosix_state = WAIT_REQ;
  }
  // WAIT ON REQUESTS //////////////////////////////////////////////////
  else if(fosix_state==WAIT_REQ)
  {
    // Start off signaling ready for all requests from main
    sys_to_proc_main.proc_to_sys_msg_ready = 1;
    
    // Wait for an incoming request from main to a "host device"
    // Find one system call making a request
    // and invalidate the ready for all other requests
    // Depending on requested syscall and sys device
    // connect req.valid and req_ready
    // Hard coded devices for now
    // Connect sys device with opposite direction flow control
    // And set state for handling response when it comes
    fosix_parsed_req_msg_t req = msg_to_request(proc_to_sys_main.msg);
    fosix_msg_decoded_t decoded_msg = UNKNOWN_MSG();
    decoded_msg.syscall_num = req.syscall_num;
    fosix_msg_t req_msg; // Outgoing
    // OPEN
    if(req.syscall_num==FOSIX_OPEN)
    {
      sys_to_proc_main.proc_to_sys_msg_ready = 0;
      
      OPEN_REQ_T_TO_BYTES(decoded_msg.payload_data, req.sys_open)
      // BRAM
      if(req.sys_open.path=="bram")
      {
        proc_to_sys_bram.msg.valid = 1;
        sys_to_proc_main.proc_to_sys_msg_ready = sys_to_proc_bram.proc_to_sys_msg_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        proc_to_sys_host.msg.valid = 1;
        sys_to_proc_main.proc_to_sys_msg_ready = sys_to_proc_host.proc_to_sys_msg_ready;
        in_flight_syscall_dev_is_bram = 0;
      }
      // Move on to waiting for response if was ready for request
      in_flight_syscall = FOSIX_OPEN;
      if(sys_to_proc_main.proc_to_sys_msg_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // WRITE
    else if(req.syscall_num==FOSIX_WRITE)
    {
      sys_to_proc_main.proc_to_sys_msg_ready = 0;
      
      // Translate from local file descriptor to sys fd
      // Before connecting to sys proc_to_sys device busses
      // Saving a copy of local fd
      fosix_fd_t local_fd = req.sys_write.fildes;
      req.sys_write.fildes = translate_fd(req.sys_write.fildes, fosix_fd_lut);
      
      WRITE_REQ_T_TO_BYTES(decoded_msg.payload_data, req.sys_write)
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        proc_to_sys_bram.msg.valid = 1;
        sys_to_proc_main.proc_to_sys_msg_ready = sys_to_proc_bram.proc_to_sys_msg_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        proc_to_sys_host.msg.valid = 1;
        sys_to_proc_main.proc_to_sys_msg_ready = sys_to_proc_host.proc_to_sys_msg_ready;
        in_flight_syscall_dev_is_bram = 0;
      }
      // Move on to waiting for response if was ready for request
      in_flight_syscall = FOSIX_WRITE;
      if(sys_to_proc_main.proc_to_sys_msg_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // READ
    else if(req.syscall_num==FOSIX_READ)
    {
      sys_to_proc_main.proc_to_sys_msg_ready = 0;
      
      // Translate from local file descriptor to sys fd
      // Before connecting to sys proc_to_sys device busses
      // Saving a copy of local fd
      fosix_fd_t local_fd = req.sys_read.fildes;
      req.sys_read.fildes = translate_fd(req.sys_read.fildes, fosix_fd_lut);
      
      READ_REQ_T_TO_BYTES(decoded_msg.payload_data, req.sys_read)
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        proc_to_sys_bram.msg.valid = 1;
        sys_to_proc_main.proc_to_sys_msg_ready = sys_to_proc_bram.proc_to_sys_msg_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        proc_to_sys_host.msg.valid = 1;
        sys_to_proc_main.proc_to_sys_msg_ready = sys_to_proc_host.proc_to_sys_msg_ready;
        in_flight_syscall_dev_is_bram = 0;
      }
      // Move on to waiting for response if was ready for request
      in_flight_syscall = FOSIX_READ;
      if(sys_to_proc_main.proc_to_sys_msg_ready)
      {
        fosix_state = WAIT_RESP;
      }
    }
    // CLOSE
    else if(req.syscall_num==FOSIX_CLOSE)
    {
      sys_to_proc_main.proc_to_sys_msg_ready = 0;
      
      // Translate from local file descriptor to sys fd
      // Before connecting to sys proc_to_sys device busses
      // Saving a copy of local fd
      fosix_fd_t local_fd = req.sys_close.fildes;
      req.sys_close.fildes = translate_fd(req.sys_close.fildes, fosix_fd_lut);
      
      CLOSE_REQ_T_TO_BYTES(decoded_msg.payload_data, req.sys_close)
      // BRAM
      if(fd_is_bram(local_fd, fosix_fd_lut))
      {
        proc_to_sys_bram.msg.valid = 1;
        sys_to_proc_main.proc_to_sys_msg_ready = sys_to_proc_bram.proc_to_sys_msg_ready;
        in_flight_syscall_dev_is_bram = 1;
      }
      // ALL OTHERS
      else
      {
        // Only other devices are stdio paths for now
        proc_to_sys_host.msg.valid = 1;
        sys_to_proc_main.proc_to_sys_msg_ready = sys_to_proc_host.proc_to_sys_msg_ready;
        in_flight_syscall_dev_is_bram = 0;
      }
      // Move on to waiting for response if was ready for request
      in_flight_syscall = FOSIX_CLOSE;
      if(sys_to_proc_main.proc_to_sys_msg_ready)
      {
        fosix_state = WAIT_RESP;
        // Make updates as needed based on response
        // CLOSE file descriptors table update
        // TODO move to response maybe close failed?
        fosix_fd_lut = remove_fd(local_fd, fosix_fd_lut);
      }
    }
    
    // Default response data
    req_msg = decoded_msg_to_msg(decoded_msg);
    proc_to_sys_bram.msg.data = req_msg;
    proc_to_sys_host.msg.data = req_msg;
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
    // BRAM
    if(in_flight_syscall_dev_is_bram)
    {
      sys_to_proc_main.msg = sys_to_proc_bram.msg;
      proc_to_sys_bram.sys_to_proc_msg_ready = proc_to_sys_main.sys_to_proc_msg_ready;
    }
    // ALL OTHERS
    else
    {
      // Only other devices are stdio paths for now
      sys_to_proc_main.msg = sys_to_proc_host.msg;
      proc_to_sys_host.sys_to_proc_msg_ready = proc_to_sys_main.sys_to_proc_msg_ready;
    }
    
    // Wow this managing of file descriptors is f'd
    // Extra work now to convert bytes to wires, modify wire, then back to bytes
    fosix_parsed_resp_msg_t resp = msg_to_response(sys_to_proc_main.msg);
    
    // OPEN
    if(in_flight_syscall == FOSIX_OPEN)
    {
      // Move on to waiting for next request 
      // if was valid response when ready seen
      if((resp.syscall_num==FOSIX_OPEN) & proc_to_sys_main.sys_to_proc_msg_ready)
      {
        fosix_state = WAIT_REQ;
        // Make updates as needed based on response
        // OPEN file descriptors table update
        // Insert file sys decriptor response into table
        // And give main a local file descriptor
        fd_lut_update_t fd_lut_update = insert_fd(resp.sys_open.fildes, in_flight_syscall_dev_is_bram, fosix_fd_lut);
        fosix_fd_lut = fd_lut_update.fd_lut;
        resp.sys_open.fildes = fd_lut_update.fildes;
        fosix_msg_decoded_t open_resp_msg = UNKNOWN_MSG();
        open_resp_msg.syscall_num = FOSIX_OPEN;
        OPEN_RESP_T_TO_BYTES(open_resp_msg.payload_data, resp.sys_open)
        sys_to_proc_main.msg.data = decoded_msg_to_msg(open_resp_msg);
        sys_to_proc_main.msg.valid = 1;
      }
    }
    // WRITE
    else if(in_flight_syscall == FOSIX_WRITE)
    {
      // Move on to waiting for next request 
      // if was valid response when ready seen
      if((resp.syscall_num==FOSIX_WRITE)& proc_to_sys_main.sys_to_proc_msg_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
    // READ
    else if(in_flight_syscall == FOSIX_READ)
    {
      // Move on to waiting for next request 
      // if was valid response when ready seen
      if((resp.syscall_num==FOSIX_READ) & proc_to_sys_main.sys_to_proc_msg_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
    // CLOSE
    else if(in_flight_syscall == FOSIX_CLOSE)
    {
      // Move on to waiting for next request 
      // if was valid response when ready seen
      if((resp.syscall_num==FOSIX_CLOSE) & proc_to_sys_main.sys_to_proc_msg_ready)
      {
        fosix_state = WAIT_REQ;
      }
    }
  }
  
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


// Derived FSM IO for syscalls
typedef struct syscall_i_t
{
  syscall_num_t num; // System call number in progress
  fosix_fd_t fd; // File descriptor for syscall
  char path[FOSIX_PATH_SIZE]; // Path buf for open()
  uint8_t buf[FOSIX_BUF_SIZE]; // IO buf for write+read
  fosix_size_t buf_nbytes; // Input number of bytes
}syscall_i_t;
typedef struct syscall_o_t
{
  fosix_fd_t fd; // File descriptor for syscall
  uint8_t buf[FOSIX_BUF_SIZE]; // IO buf for write+read
  fosix_size_t buf_nbytes_ret; // Return count of bytes
}syscall_o_t;

// Make a single instance of the syscall fsm function
// Uses single sintance global wires connecting to fosix stuff
syscall_o_t syscall(syscall_i_t i)
{
  syscall_o_t o;
  uint1_t func_running = 1;
  while(func_running)
  {
    // Inputs
    fosix_sys_to_proc_t sys_to_proc;
    WIRE_READ(fosix_sys_to_proc_t, sys_to_proc, main_sys_to_proc)  
    syscall_io_t io;
    io.start = 1;
    io.num = i.num;
    io.fd = i.fd;
    io.path = i.path;
    io.buf = i.buf;
    io.buf_nbytes = i.buf_nbytes;
    
    // The function
    syscall_func_t sc;  
    sc = syscall_func(sys_to_proc, io);
    
    // Outputs
    io = sc.syscall_io;
    o.fd = io.fd;
    o.buf = io.buf;
    o.buf_nbytes_ret = io.buf_nbytes_ret;
    fosix_proc_to_sys_t proc_to_sys = sc.proc_to_sys;
    WIRE_WRITE(fosix_proc_to_sys_t, main_proc_to_sys, proc_to_sys)
    
    // Detect end of comb logic fsm
    // TODO: implement break;
    if(io.done)
    {
      func_running = 0;
    }
    
    // Loop iteration needs to take atleast 1 clk
    // (No logic above take any clock cycles, all comb. logic)
    __clk();
  }
  return o;
}
#include "syscall_SINGLE_INST.h"

fosix_fd_t open(char path[FOSIX_PATH_SIZE])
{
  syscall_i_t i;
  i.num = FOSIX_OPEN;
  i.path = path;
  syscall_o_t o = syscall(i);
  return o.fd;
}
#include "open_SINGLE_INST.h"
  
fosix_size_t write(fosix_fd_t fd, char buf[FOSIX_BUF_SIZE], fosix_size_t buf_nbytes)
{
  syscall_i_t i;
  i.num = FOSIX_WRITE;
  i.buf = buf;
  i.buf_nbytes = buf_nbytes;
  i.fd = fd;
  syscall_o_t o = syscall(i);
  return o.buf_nbytes_ret;
} 
#include "write_SINGLE_INST.h"

// Needs to be macro since can't pass string arg for strlen through func args
#define STRWRITE(fd_in, buf_in)\
write(fd_in, buf_in, strlen(buf_in)+1 /* w/ null term*/);

typedef struct read_t
{
  uint8_t buf[FOSIX_BUF_SIZE];
  fosix_size_t buf_nbytes_ret;
}read_t;
read_t read(fosix_fd_t fd, fosix_size_t buf_nbytes)
{
  syscall_i_t i;
  i.num = FOSIX_READ;
  i.buf_nbytes = buf_nbytes;
  i.fd = fd;
  syscall_o_t o = syscall(i);
  read_t r;
  r.buf = o.buf;
  r.buf_nbytes_ret = o.buf_nbytes_ret;
  return r;
} 
#include "read_SINGLE_INST.h"

/*TEMP NOT USED CANT SPECIFY AS BEING THERE AS A SINGLE INST
// Temp return fd const 0
fosix_fd_t close(fosix_fd_t fd)
{
  syscall_i_t i;
  i.num = FOSIX_CLOSE;
  i.fd = fd;
  syscall_o_t o = syscall(i);
  return 0;
} 
#include "close_SINGLE_INST.h"
*/
