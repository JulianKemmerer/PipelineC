#pragma once
typedef struct sccb_op_start_t{
  uint32_t id;
  uint32_t is_read;
  uint32_t addr;
  uint32_t write_data;
} sccb_op_start_t;
#ifdef __PIPELINEC__
DECL_STREAM_TYPE(sccb_op_start_t)
#endif

typedef struct sccb_op_finish_t{
  uint32_t read_data;
} sccb_op_finish_t;
#ifdef __PIPELINEC__
DECL_STREAM_TYPE(sccb_op_finish_t)
#endif