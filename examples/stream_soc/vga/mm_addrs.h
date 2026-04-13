// Frame buffer in AXI0 DDR
#define FB0_ADDR MMIO_AXI0_ADDR
static volatile pixel_t* FB0 = (pixel_t*)FB0_ADDR;
#define FB0_END_ADDR (FB0_ADDR + FB_SIZE)