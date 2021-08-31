#pragma once
#include "fosix_msg.h"

// Hardware specific packing and unpacking of bytes + helpers

// Bytes[1+] are specific to syscall

// Auto generated code for converting to and from bytes
// Requests
#include "open_req_t_bytes_t.h"
#include "write_req_t_bytes_t.h"
#include "read_req_t_bytes_t.h"
#include "close_req_t_bytes_t.h"
// Responses
#include "open_resp_t_bytes_t.h"
#include "write_resp_t_bytes_t.h"
#include "read_resp_t_bytes_t.h"
#include "close_resp_t_bytes_t.h"

// Process to system request
fosix_parsed_req_msg_t msg_to_request(fosix_msg_s msg_stream)
{
  fosix_msg_decoded_t decoded_msg = decode_msg(msg_stream);
  fosix_parsed_req_msg_t req;
  req.syscall_num = decoded_msg.syscall_num;
  req.sys_open  = bytes_to_open_req_t(decoded_msg.payload_data);
  req.sys_write = bytes_to_write_req_t(decoded_msg.payload_data);
  req.sys_read = bytes_to_read_req_t(decoded_msg.payload_data);
  req.sys_close = bytes_to_close_req_t(decoded_msg.payload_data);
  return req;
}

// System to process response
fosix_parsed_resp_msg_t msg_to_response(fosix_msg_s msg_stream)
{
  fosix_parsed_resp_msg_t resp;
  fosix_msg_decoded_t decoded_msg = decode_msg(msg_stream);
  resp.syscall_num = decoded_msg.syscall_num;
  resp.sys_open  = bytes_to_open_resp_t(decoded_msg.payload_data);
  resp.sys_write = bytes_to_write_resp_t(decoded_msg.payload_data);
  resp.sys_read = bytes_to_read_resp_t(decoded_msg.payload_data);
  resp.sys_close = bytes_to_close_resp_t(decoded_msg.payload_data);
  return resp;
}


