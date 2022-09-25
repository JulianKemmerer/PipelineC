int fib(int n){
	if (n <= 1)
			return n;
	return fib(n - 1) + fib(n - 2);
}

// Attribute required for specifying a particular
// location in memory for the entry point/init instructions
__attribute__ ((section(".text.init")))
int main() {
	int n = 10;
	return fib(n);
}
