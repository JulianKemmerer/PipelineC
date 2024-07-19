#include <stdint.h>
#include "mem_map.h"

int memtest(volatile uint8_t* ptr, int size){
	// 32b (4 bytes) word test
	volatile uint32_t* word_ptr = (uint32_t*)ptr;
	// Write zeros
	for(int i = 0; i < size/4; i+=1)
	{
		word_ptr[i] = 0;
	}
	// Read back zeros and check
	for(int i = 0; i < size/4; i+=1)
	{
		if(word_ptr[i]!=0){
			return 0;
		}
	}
	// Write values
	for(int i = 0; i < size/4; i+=1)
	{
		word_ptr[i] = i;
	}
	// Read back values and check
	for(int i = 0; i < size/4; i+=1)
	{
		if(word_ptr[i]!=i){
			return 0;
		}
	}
	return 1;
}

void main() {
	int count = 0;
	int passing = 1;
	while(passing){
		// 1b leds get slow changing upper bits
		//*LED = count >> 22;
		*LED = count;
		count += 1;
		#ifdef MMIO_BRAM0
		passing = memtest(BRAM0, MMIO_BRAM0_SIZE);
		if(!passing) break;
		#endif
		#ifdef MMIO_AXI0
		passing = memtest(AXI0, MMIO_AXI0_SIZE);
		if(!passing) break;
		#endif
	}
	while(1){
		// Failed no blink forever
		*LED = 1 << 1;
	}
}
/*
// Sim debug version that doesnt run forever
int main() {
	int count = 0;
	while(count < 10){
		// 1b led get slow changing upper bits
		*LED = count >> 12;
		count += 1;
	}
	*RETURN_OUTPUT = count;
	return count;
}
*/