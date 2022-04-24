// Full part string examples:
// xc7a35ticsg324-1l     Artix 7 35T (Arty)
// xc7a100tcsg324-1      Artix 7 100T (Arty)
// xcvu9p-flgb2104-2-i   Virtex Ultrascale Plus (AWS F1)
// xcvu33p-fsvh2104-2-e  Virtex Ultrascale Plus
// xc7v2000tfhg1761-2    Virtex 7
// EP2AGX45CU17I3        Arria II GX
// 10CL120ZF780I8G       Cyclone 10 LP
// 5CGXFC9E7F35C8        Cyclone V GX
// EP4CE22F17C6          Cyclone IV
// 10M50SCE144I7G        Max 10
// LFE5U-85F-6BG381C     ECP5U
// LFE5UM5G-85F-8BG756C  ECP5UM5G
// ICE40UP5K-SG48        ICE40UP
// T8F81                 Trion T8 (Xyloni)
// Ti60F225              Titanium
#pragma PART "xc7a100tcsg324-1"

// More recent (and most likely test+working) examples towards the bottom of list \/
// Please see: https://github.com/JulianKemmerer/PipelineC/wiki/Examples
//#include "examples/aws-fpga-dma/loopback.c"
//#include "examples/aws-fpga-dma/work.c"
//#include "examples/fosix/hello_world.c"
//#include "examples/fosix/bram_loopback.c"
//#include "examples/arty/src/uart/uart_loopback_no_fc.c"
//#include "examples/arty/src/work/work.c"
//#include "examples/arty/src/uart_ddr3_loopback/app.c"
//#include "examples/arty/src/ddr3/mig_app.c"
//#include "examples/arty/src/uart/uart_loopback_msg.c"
//#include "examples/littleriscy/riscv.c"
//#include "examples/NexusProofOfWork/NXSTest_syn.c"
//#include "examples/fir.c"
//#include "examples/arty/src/i2s/i2s_passthrough_app.c"
//#include "examples/arty/src/audio/distortion.c"
//#include "examples/arty/src/i2s/i2s_app.c"
//#include "examples/fosix/main_bram_loopback.c"
//#include "examples/groestl/groestl.c"
//#include "examples/aes/aes.c"
//#include "examples/fosix/main_game_clk_step.c"
//#include "examples/llvm/rsqrtf.c"
//#include "examples/verilator/math_pkg/u24add/u24add.c"
//#include "examples/verilator/math_pkg/u24mult/u24mult.c"
//#include "examples/verilator/math_pkg/i25sub/i25sub.c"
//#include "examples/verilator/math_pkg/fp32_to_i32/fp32_to_i32.c"
//#include "examples/verilator/math_pkg/i32_to_fp32/i32_to_fp32.c"
//#include "examples/verilator/math_pkg/fp32add/fp32add.c"
//#include "examples/verilator/math_pkg/fp32sub/fp32sub.c"
//#include "examples/verilator/math_pkg/fp32mult/fp32mult.c"
//#include "examples/verilator/math_pkg/fp32div/fp32div.c"
//#include "examples/verilator/math_pkg/rsqrtf/rsqrtf.c"
//#include "examples/arty/src/vga/bouncing_images.c"
//#include "examples/pipeline_feedback_on_self.c"
//#include "examples/arty/src/vga/pong.c"
//#include "examples/arty/src/vga/pong_volatile.c"
//#include "examples/arty/src/mnist/neural_network_fsm_basic.c"
//#include "examples/arty/src/mnist/neural_network_fsm_n_wide.c"
//#include "examples/arty/src/mnist/neural_network_fsm.c"
//#include "examples/arty/src/eth/loopback_app.c"
//#include "examples/arty/src/eth/work_app.c"
//#include "examples/blink.c"
//#include "examples/edaplay.c"
//#include "examples/arty/src/blink.c"
//#include "examples/verilator/blink.c"
//#include "examples/pipeline.c"
//#include "examples/pipeline_and_fsm.c"
//#include "examples/clock_crossing.c"
//#include "examples/async_clock_crossing.c"
//#include "examples/fsm_style.c"
//#include "examples/arty/src/vga/mandelbrot.c"
//#include "examples/arty/src/mnist/eth_app.c"
//#include "examples/prim_mult_demo.c"
//#include "examples/async_wires.c"
//#include "examples/internal_clocks.c"
//#include "examples/arty/src/uart/uart_clk_step.c"
//#include "examples/find_min_n.c"
#include "vga/test_pattern.c"

// Below is recent scratch work - enjoy
