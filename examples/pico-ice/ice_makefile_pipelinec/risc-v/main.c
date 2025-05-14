#include <stdint.h>
#include "mem_map.h"

void main() {
	int count = 0;
	while(1){
		// 1b leds get slow changing upper bits
		mm_ctrl_regs->led = count >> 22;
		count += 1;
	}
}
