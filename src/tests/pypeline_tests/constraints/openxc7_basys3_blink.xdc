# Basys 3 rev. B pins used by examples/blink.c.
# Source: https://github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc
set_property -dict { PACKAGE_PIN W5 IOSTANDARD LVCMOS33 } [get_ports clk_33p33]
set_property -dict { PACKAGE_PIN U16 IOSTANDARD LVCMOS33 } [get_ports {blink_return_output[0]}]
