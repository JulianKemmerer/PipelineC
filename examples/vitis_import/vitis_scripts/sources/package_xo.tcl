set script_path [ file dirname [ file normalize [ info script ] ] ]
set script_path $script_path/..
set PIPELINEC_PROJ_DIR $script_path/../OUT

source sources/utils.tcl

create_project project_1 $script_path/project_1 -part xcu50-fsvh2104-2-e -force

set fp [open ${PIPELINEC_PROJ_DIR}/vhdl_files.txt r]
set file_data [read $fp]
read_vhdl -vhdl2008 -library work $file_data
set_property file_type {VHDL} [get_files  ${PIPELINEC_PROJ_DIR}/top/top.vhd]
close $fp

update_compile_order -fileset sources_1

create_bd_design "my_ip"
create_bd_cell -type module -reference top top_0
make_bd_pins_external  [get_bd_cells top_0]
make_bd_intf_pins_external  [get_bd_cells top_0]
save_bd_design
validate_bd_design

make_wrapper -files [get_files $script_path/project_1/project_1.srcs/sources_1/bd/my_ip/my_ip.bd] -top
add_files -norecurse $script_path/project_1/project_1.gen/sources_1/bd/my_ip/hdl/my_ip_wrapper.v
set_property top my_ip_wrapper [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project -root_dir $script_path/ip_repo -vendor user.org -library user -taxonomy /UserIP -module my_ip -import_files
update_compile_order -fileset sources_1
set_property ipi_drc {ignore_freq_hz false} [ipx::find_open_core user.org:user:my_ip:1.0]
set_property sdx_kernel true [ipx::find_open_core user.org:user:my_ip:1.0]
set_property sdx_kernel_type rtl [ipx::find_open_core user.org:user:my_ip:1.0]
set_property vitis_drc {ctrl_protocol ap_ctrl_none} [ipx::find_open_core user.org:user:my_ip:1.0]
set_property ipi_drc {ignore_freq_hz true} [ipx::find_open_core user.org:user:my_ip:1.0]

map_clock clk_300p0_0
map_axi_stream pipelineC_ip_in_data_0 pipelineC_ip_in_valid_0 in_ready_return_output_0 clk_300p0_0 input_stream slave
map_axi_stream out_data_return_output_0 out_valid_return_output_0 pipelineC_ip_out_ready_0 clk_300p0_0 output_stream master

set_property core_revision 1 [ipx::find_open_core user.org:user:my_ip:1.0]
ipx::create_xgui_files [ipx::find_open_core user.org:user:my_ip:1.0]
ipx::update_checksums [ipx::find_open_core user.org:user:my_ip:1.0]
ipx::check_integrity -kernel -xrt [ipx::find_open_core user.org:user:my_ip:1.0]
ipx::save_core [ipx::find_open_core user.org:user:my_ip:1.0]
package_xo  -xo_path $script_path/xo/my_ip.xo -kernel_name my_ip -ip_directory $script_path/ip_repo -ctrl_protocol ap_ctrl_none -force
update_ip_catalog
ipx::check_integrity -quiet -kernel -xrt [ipx::find_open_core user.org:user:my_ip:1.0]
ipx::archive_core $script_path/ip_repo/user.org_user_my_ip_1.0.zip [ipx::find_open_core user.org:user:my_ip:1.0]
