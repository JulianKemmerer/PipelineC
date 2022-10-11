#include <stdint.h>
#include "../mem_map.h"

void main() {
	int count = 0;
	while(1){
		// 4b leds get slow changing upper bits
		*LEDS = count >> 22;
		count += 1;
	}
}

// Sim debug version that doesnt run forever
/*int main() {
	int count = 0;
	while(count < 10){
		// 4b leds get slow changing upper bits
		*LEDS = count >> 12;
		count += 1;
	}
	*RETURN_OUTPUT = count;
	return count;
}*/