#include <stdint.h>
#include "mem_map.h"

void main() {
	int count = 0;
	while(1){
		// 1b leds get slow changing upper bits
		//*LED = count >> 22;
		*LED = count / 220000;
		count += 1;
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