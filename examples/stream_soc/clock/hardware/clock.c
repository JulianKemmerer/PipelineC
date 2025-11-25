uint32_t cpu_clock;
#pragma MAIN cpu_clock_main
void cpu_clock_main(){
  static uint32_t cycle_counter;
  cpu_clock = cycle_counter;
  cycle_counter = cycle_counter + 1;
}