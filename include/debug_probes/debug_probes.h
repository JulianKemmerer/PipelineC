#pragma once

// Each probe is either read or write so only need to provide probe identifier
typedef struct probes_cmd_t
{
  uint8_t probe_id;
}probes_cmd_t;
#ifdef __PIPELINEC__
#include "probes_cmd_t_bytes_t.h"
#else
#include <stddef.h>
#include "type_bytes_t.h/probes_cmd_t_bytes_t.h/probes_cmd_t_bytes.h"
#include "type_bytes_t.h/uint8_t_bytes_t.h/uint8_t_bytes.h"
#endif

// A guess?
#define MAX_PROBE_SIZE 256
