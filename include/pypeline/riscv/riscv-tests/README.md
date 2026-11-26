# RISC-V ISA test sources

The 42 assembly files under `isa/rv32ui`, their 42 includes under
`isa/rv64ui`, and `isa/macros/scalar/test_macros.h` come verbatim from
[riscv-tests at 3df703cd](https://github.com/riscv-software-src/riscv-tests/tree/3df703cd).
They carry the upstream [BSD license](LICENSE). The corresponding upstream
[environment revision is 6de71edb](https://github.com/riscv/riscv-test-env/tree/6de71edb).
The single-cycle core uses its own [trap-free test environment](../test_env/riscv_test.h).
