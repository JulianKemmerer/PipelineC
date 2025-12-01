// AXI buses (type of shared resource bus)
#define MMIO_AXI0_ADDR MM_REGS_END_ADDR
#define MMIO_AXI0_SIZE 268435456 // XIL_MEM_SIZE 2^28 bytes , 256MB DDR3 = 28b address
static volatile uint8_t* AXI0 = (uint8_t*)MMIO_AXI0_ADDR;
#define MMIO_AXI0_END_ADDR (MMIO_AXI0_ADDR+MMIO_AXI0_SIZE)

// Often dont care if writes are finished before returning frame_buf_write returning
// turn off waiting for writes to finish and create a RAW hazzard
// Do not read after write (not reliable to read back data after write has supposedly 'finished')
//#define MMIO_AXI0_RAW_HAZZARD