# Small ROM workload for FPGA fit checks. Exercise DMEM and send its value to the mailbox.
.section .text.init
.globl _start
_start:
    la t0, sample
    li t1, 1
    sw t1, 0(t0)
    lw t2, 0(t0)
    sw t2, tohost, t3
1:  j 1b

.section .bss
.balign 4
sample: .space 4
