// Counter from the pico-ice RISC-V demo. The UART joins the example in M4.
#include <stdint.h>

static const uint32_t table[] = {3, 1, 4, 1, 5, 9, 2, 6};
static const char msg[] = "Hello from Pypeline CPU!";
static volatile uint32_t bss_counter;
static volatile uint32_t data_seed = 12345;

uint32_t checksum(void) {
    uint32_t sum = data_seed;
    for (unsigned i = 0; i < 8; ++i) {
        sum = sum * 31 + table[i] / 3 + table[i] % 3;
        ++bss_counter;
    }
    for (const char *p = msg; *p; ++p)
        sum ^= (uint32_t)*p << (bss_counter & 7);
    return sum;
}

int main(void) {
    volatile uint32_t count = 0;
    for (unsigned i = 0; i < 100; ++i)
        ++count;
    // Reference: compile checksum() for the host and print its uint32_t result.
    return checksum() == 0x784d8099u ? 0 : 1;
}
