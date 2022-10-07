#include "mem_map.h"

int fib(int n){
	if (n <= 1)
			return n;
	return fib(n - 1) + fib(n - 2);
}

int main() {
	int n = 3; // 0 1 1 2 3 5
	int rv = fib(n);
	*RETURN_OUTPUT = rv;
	return rv;
}