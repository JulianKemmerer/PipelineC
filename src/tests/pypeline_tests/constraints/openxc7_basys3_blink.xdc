# Basys 3 rev. B pins for examples/pypeline/blink.py (inst/openxc7_bitstream_test.py).
# W5 is the board's 100 MHz oscillator and blink.py is written for 25 MHz, so on
# a real board the LED toggles every 0.25 s rather than every 1 s.
# Source: https://github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc
set_property -dict { PACKAGE_PIN W5 IOSTANDARD LVCMOS33 } [get_ports clk_25p0]
set_property -dict { PACKAGE_PIN U16 IOSTANDARD LVCMOS33 } [get_ports {blink_return_output[0]}]
