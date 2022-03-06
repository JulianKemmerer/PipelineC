remove_files /media/1TB/Dropbox/PipelineC/git/PipelineC-Graphics/build/*; 
remove_files /media/1TB/Dropbox/PipelineC/git/PipelineC-Graphics/fullsynth/*;
source /media/1TB/Dropbox/PipelineC/git/PipelineC-Graphics/fullsynth/read_vhdl.tcl;
update_compile_order -fileset sources_1
reset_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1

