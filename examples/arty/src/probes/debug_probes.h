#pragma once

// Each probe is either read or write so only need to provide probe identifier
typedef struct probes_cmd_t
{
  uint8_t probe_id;
}probes_cmd_t;

// A guess?
#define MAX_PROBE_SIZE 256
