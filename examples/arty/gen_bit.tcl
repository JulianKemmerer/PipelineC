remove_files /media/1TB/Dropbox/PipelineC/git/PipelineC-Graphics/build/*; source /media/1TB/Dropbox/PipelineC/git/PipelineC-Graphics/build/read_vhdl.tcl;
update_compile_order -fileset sources_1
launch_runs impl_1 -to_step write_bitstream -jobs 2

