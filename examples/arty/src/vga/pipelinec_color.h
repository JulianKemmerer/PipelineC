// See make_image_files.py
// pipelinec_color : ../../../../pipelinec_color.jpg
#define pipelinec_color_W 320
#define pipelinec_color_H 68
#define pipelinec_color_pixel_addr(pos) ((pos.y*pipelinec_color_W) + pos.x)
#define pipelinec_color_DECL \
static color_12b_t pipelinec_color[pipelinec_color_W*pipelinec_color_H];\
#pragma VAR_VHDL_INIT pipelinec_color /media/1TB/Dropbox/PipelineC/git/PipelineC/examples/arty/src/vga/pipelinec_color.vhd
