proc map_clock {axi_clk} {
    ipx::infer_bus_interface $axi_clk xilinx.com:signal:clock_rtl:1.0 [ipx::find_open_core user.org:user:my_ip:1.0]
    ipx::add_bus_parameter FREQ_TOLERANCE_HZ [ipx::get_bus_interfaces $axi_clk -of_objects [ipx::current_core]]
    set_property value -1 [ipx::get_bus_parameters FREQ_TOLERANCE_HZ -of_objects [ipx::get_bus_interfaces $axi_clk -of_objects [ipx::current_core]]]
}
proc map_axi_stream {data valid ready axi_clock port_name axi_type} {
ipx::add_bus_interface $port_name [ipx::find_open_core user.org:user:my_ip:1.0]
set_property abstraction_type_vlnv xilinx.com:interface:axis_rtl:1.0 [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]
set_property interface_mode $axi_type [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]
set_property bus_type_vlnv xilinx.com:interface:axis:1.0 [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]
ipx::add_port_map TDATA [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]
set_property physical_name $data [ipx::get_port_maps TDATA -of_objects [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]]
ipx::add_port_map TVALID [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]
set_property physical_name $valid [ipx::get_port_maps TVALID -of_objects [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]]
ipx::add_port_map TREADY [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]
set_property physical_name $ready [ipx::get_port_maps TREADY -of_objects [ipx::get_bus_interfaces $port_name -of_objects [ipx::find_open_core user.org:user:my_ip:1.0]]]
ipx::associate_bus_interfaces -busif $port_name -clock $axi_clock [ipx::find_open_core user.org:user:my_ip:1.0]
}
