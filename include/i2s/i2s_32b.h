// Code for converting i2s stream to and from 32b chunks, ex for AXI
#include "uintN_t.h"
#include "arrays.h"
#include "stream/stream.h"
#include "stream/serializer.h"
#include "stream/deserializer.h"

// Type for the unpacked, aligned, easy to debug samples data as layed out in memory
typedef struct i2s_sample_in_mem_t{
  int32_t l;
  int32_t r;
}i2s_sample_in_mem_t;
#include "i2s_sample_in_mem_t_bytes_t.h" // Auto gen func casting i2s_sample_in_mem_t to-from byte array
i2s_sample_in_mem_t i2s_samples_in_mem(i2s_samples_t samples){
  i2s_sample_in_mem_t rv;
  rv.l = samples.l_data.qmn; // fixed point type
  rv.r = samples.r_data.qmn; // fixed point type
  return rv;
}
i2s_samples_t i2s_samples_from_mem(i2s_sample_in_mem_t mem){
  i2s_samples_t rv;
  rv.l_data.qmn = mem.l; // fixed point type
  rv.r_data.qmn = mem.r; // fixed point type
  return rv;
}

// Convert rounded type to 4 byte chunks
// Macro to define serializer for a struct type
type_byte_serializer(i2s_sample_in_mem_to_bytes, i2s_sample_in_mem_t, 4)

// Convert samples stream to u32 stream
typedef struct samples_to_u32_t{
  stream(uint32_t) out_stream;
  uint1_t ready_for_samples;
}samples_to_u32_t;
samples_to_u32_t samples_to_u32(stream(i2s_samples_t) samples, uint1_t out_stream_ready){
  samples_to_u32_t rv;

  // Round 24b samples to u32 for storage
  i2s_sample_in_mem_t wr_data = i2s_samples_in_mem(samples.data);

  // Convert rounded type to 4 byte chunks
  i2s_sample_in_mem_to_bytes_t to_bytes = i2s_sample_in_mem_to_bytes(wr_data, samples.valid, out_stream_ready);
  rv.ready_for_samples = to_bytes.in_data_ready;

  // Output 4 bytes as u32
  rv.out_stream.data = uint8_array4_le(to_bytes.out_data);
  rv.out_stream.valid = to_bytes.valid;
  
  return rv;
}


// Convert 4 byte chunks to rounded type
// Macro to define deserializer for a struct type
type_byte_deserializer(i2s_samples_in_mem_from_bytes, 4, i2s_sample_in_mem_t)

// Convert u32 stream to samples stream
typedef struct u32_to_samples_t{
  stream(i2s_samples_t) out_stream;
  uint1_t ready_for_data_in;
}u32_to_samples_t;
u32_to_samples_t u32_to_samples(stream(uint32_t) in_stream, uint1_t out_stream_ready){
  u32_to_samples_t rv;

  // Input u32 to 4 bytes
  uint8_t rd_data[4];
  uint32_t i;
  for(i = 0; i < 4; i+=1)
  {
    rd_data[i] = in_stream.data >> (i*8);
  }

  // Convert 4 byte chunks into rounded for memory samples type
  i2s_samples_in_mem_from_bytes_t from_bytes = i2s_samples_in_mem_from_bytes(rd_data, in_stream.valid, out_stream_ready);
  rv.ready_for_data_in = from_bytes.in_data_ready;

  // Round back down to the real 24b samples
  i2s_samples_t samples = i2s_samples_from_mem(from_bytes.data);
  rv.out_stream.data = samples;
  rv.out_stream.valid = from_bytes.valid;
  
  return rv;
}
