# Declare _bootstrap, the new entry point
.globl _bootstrap
# Declare main, the C code entry point
.globl main

# Upon startup set the stack pointer to point at the end of the stack
# And then start user main()
_bootstrap:
la sp, __stacktop
jal main