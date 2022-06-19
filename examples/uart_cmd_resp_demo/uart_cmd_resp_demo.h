// PC to FPGA is command, FPGA to PC is response
// Same struct both ways
#define READ_CMD 0
#define WRITE_CMD 1
typedef struct uart_cmd_resp_t{
    uint8_t cmd; // Read or write
    uint32_t addr;
    uint32_t data;
} uart_cmd_resp_t;

#define LEDS_ADDR 420