# It does not appear possible to specify
# bootstrap assembly directly in asm("...") C code.
# For that reason setup that occurs 
# before the C code entry point is done here

# Declare _bootstrap, the new entry point
.globl _bootstrap
# Declare main, the C code entry point
.globl main

# Upon startup set the stack pointer to point at the end of the stack
# And then start user main()
_bootstrap:
la sp, stack_end
jal main

# Declare a stack area of memory? 
# (must be after entry point? or last in order?)
stack_begin:
.zero 256
stack_end: