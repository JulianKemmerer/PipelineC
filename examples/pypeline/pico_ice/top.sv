module top(
  // These pins should all exist in ice40.pcf
  inout ICE_35,
  inout ICE_39,
  inout ICE_40,
  inout ICE_41,
  inout ICE_25,
  inout ICE_27,
  inout ICE_11,
  inout ICE_9,
  inout ICE_45,
  inout ICE_47,
  inout ICE_2,
  inout ICE_4,
  inout ICE_44,
  inout ICE_46,
  inout ICE_48,
  inout ICE_3,
  inout ICE_31,
  inout ICE_34,
  inout ICE_38,
  inout ICE_43,
  inout ICE_28,
  inout ICE_32,
  inout ICE_36,
  inout ICE_42,
  inout ICE_23,
  inout ICE_26
);
  // ICE_35 has a default 12MHz clock in pico and pico2
  // PLL instance to make a clock based on 12MHz
  wire pll_clk;
  wire pll_locked;
  pll pll_inst(
    .clock_in(ICE_35),
    .clock_out(pll_clk),
    .locked(pll_locked)
  );

  // Pypeline generated top level instance
  pypeline_top pypeline_inst(
    // Its port names (Input[T]/Output[T] names in the .py design) exactly match
    // wires in this top level .sv, so the wildcard .* implicit port connection
    // connects them automatically
    .*
  );
endmodule
