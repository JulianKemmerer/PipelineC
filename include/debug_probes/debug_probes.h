#pragma once
#include "compiler.h" // For preprocessor cat PPCAT

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

// PROBE0
#ifndef probe0_print
#define probe0_print            PPCAT(probe0,_print)
#endif
#ifndef probe0_t
#define probe0_t                PPCAT(probe0,_t)
#endif
#define PROBE0_SIZE             PPCAT(probe0_t,_SIZE)
#define probe0_size_t           PPCAT(probe0_t,_size_t)
#define probe0_bytes_to_type    PPCAT(bytes_to_,probe0_t)
#define probe0_type_to_bytes    PPCAT(probe0_t,_to_bytes)
#define probe0_t_bytes_t        PPCAT(probe0_t,_bytes_t)
#define probe0_t_array_1_t      PPCAT(probe0_t,_array_1_t)

#ifdef probe1
// PROBE1
#ifndef probe1_print
#define probe1_print            PPCAT(probe1,_print)
#endif
#ifndef probe1_t
#define probe1_t                PPCAT(probe1,_t)
#endif
#define PROBE1_SIZE             PPCAT(probe1_t,_SIZE)
#define probe1_size_t           PPCAT(probe1_t,_size_t)
#define probe1_bytes_to_type    PPCAT(bytes_to_,probe1_t)
#define probe1_type_to_bytes    PPCAT(probe1_t,_to_bytes)
#define probe1_t_bytes_t        PPCAT(probe1_t,_bytes_t)
#define probe1_t_array_1_t      PPCAT(probe1_t,_array_1_t)
#endif

#ifdef probe2
#error "More probes!"
#endif
