// Network, big endian, byte order
// MAC0 is most signficant byte
// MAC5 is least signficant byte
// "0:1:2:3:4:5"
#define FPGA_MAC0	0xA0
#define FPGA_MAC1	0xB1
#define FPGA_MAC2	0xC2
#define FPGA_MAC3	0xD3
#define FPGA_MAC4	0xE4
#define FPGA_MAC5	0xF5

uint8_t FPGA_MAC_BYTES[6] = {FPGA_MAC0, FPGA_MAC1, FPGA_MAC2, FPGA_MAC3, FPGA_MAC4, FPGA_MAC5};

#define FPGA_MAC uint8_array6_be(FPGA_MAC_BYTES)
