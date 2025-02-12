#pragma once
#include "compiler.h"
#include "uintN_t.h"

// Hacky fake template stuff?
#define stream(T)\
PPCAT(T,_stream_t)

#define DECL_STREAM_TYPE(data_t)\
typedef struct stream(data_t){\
        data_t data;\
        uint1_t valid;\
}stream(data_t);

// Macro for one item stream buffer
// TODO this is old and not right remove?
// At least fix to use static locals for regs...
/*
#define SBUF(type, name) type name##_data;\
type name(type data, uint1_t read){\
        if(data.valid)\
        {\
                name##_data = data;\
        }\
        type rv;\
        rv = name##_data;\
        rv.valid = 0;\
        if(read)\
        {\
                rv.valid = name##_data.valid;\
                name##_data.valid = 0;\
        }\
        return rv;\
}
*/

// Skid buffer for registering DVR handshake
#define SKID_BUF(type, name)\
typedef struct PPCAT(name,_t){\
  /* Outputs from module*/\
  /*  Output .data and .valid stream*/\
  stream(type) stream_out;\
  /*  Output ready for input axis stream*/\
  uint1_t ready_for_stream_in;\
}PPCAT(name,_t);\
PPCAT(name,_t) name(\
  /* Inputs to module*/\
  /*  Input .data and .valid stream*/\
  stream(type) stream_in,\
  /*  Input ready for output axis stream*/\
  uint1_t ready_for_stream_out\
){\
  /* Demo logic for skid buffer*/\
  /* Static = register*/\
  static stream(type) buff;\
  static stream(type) skid_buff;\
  /* Idea of skid buffer is to switch between two buffers*/\
  /* to skid to a stop while avoiding a comb. path from */\
  /*  ready_for_stream_out -> ready_for_stream_in*/\
  /* loosely like a 2-element FIFO...*/\
  static uint1_t output_is_skid_buff; /* aka input_is_buff*/\
  \
  /* Output signals*/\
  PPCAT(name,_t) o; /* Default value all zeros*/\
  \
  /* Connect output based on buffer in use*/\
  /* ready for input if other buffer is empty(not valid)*/\
  if(output_is_skid_buff){\
    o.stream_out = skid_buff;\
    o.ready_for_stream_in = ~buff.valid;\
  }else{\
    o.stream_out = buff;\
    o.ready_for_stream_in = ~skid_buff.valid;\
  }\
  \
  /* Input ready writes buffer*/\
  if(o.ready_for_stream_in){\
    if(output_is_skid_buff){\
      buff = stream_in;\
    }else{\
      skid_buff = stream_in;\
    }\
  }\
  \
  /* No Output or output ready*/\
  /* clears buffer and switches to next buffer*/\
  if(~o.stream_out.valid | ready_for_stream_out){\
    if(output_is_skid_buff){\
      skid_buff.valid = 0;\
    }else{\
      buff.valid = 0;\
    }\
    output_is_skid_buff = ~output_is_skid_buff;\
  }\
  \
  return o;\
}
