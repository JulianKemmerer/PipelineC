#include <stdint.h>
#include "mem_map.h"

// Helper funcs to read and write uart
int try_read_uart(uint8_t* data_out){
  return try_read_handshake(data_out, sizeof(uint8_t), (void*)&mm_handshake_data->uart_rx, (void*)&mm_handshake_valid->uart_rx);
}
int try_write_uart(uint8_t* data_in){
	return try_write_handshake((void*)&mm_handshake_data->uart_tx, (void*)&mm_handshake_valid->uart_tx, data_in, sizeof(uint8_t));
}

void main() {
	int count = 0;
	while(1){
		// 1b leds get slow changing upper bits
		mm_ctrl_regs->led = count >> 19;
		count += 1;

		// UART case change demo
		char in_char;
		if(try_read_uart(&in_char)){
			char out_char = in_char;
			uint8_t case_diff = 'a' - 'A';
			if(in_char >= 'a' && in_char <= 'z'){
				out_char = in_char - case_diff;
			}else if(in_char >= 'A' && in_char <= 'Z'){
				out_char = in_char + case_diff;
			}
			while(!try_write_uart(&out_char)){}
		}
	}
}
