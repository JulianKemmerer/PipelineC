# Helper script to write C and VHDL constants from image file
from PIL import Image
import sys
import os

# Sized to fit at min 640x480
MAX_W = 320
MAX_H = 240

# Open image
img_file = sys.argv[1]
print(img_file)
img_name = os.path.splitext(os.path.basename(img_file))[0]
print(img_name)
im = Image.open(img_file)
width, height = im.size

# Need resize?
if width > MAX_W or height > MAX_H:
    w_mult = width / MAX_W
    h_mult = height / MAX_H
    mult = max(w_mult, h_mult)
    # Resize both dims to be smaller by equal proportions
    new_w = int(width / mult)
    new_h = int(height / mult)
    newsize = (new_w, new_h)
    im = im.resize(newsize)
    width, height = im.size

# Start out file text
c_text = f"""// See make_image_files.py
// {img_name} : {img_file}
#define {img_name}_W {width}
#define {img_name}_H {height}
#define {img_name}_pixel_addr(pos) ((pos.y*{img_name}_W) + pos.x)
"""
vhd_out_name = img_name + ".vhd"
vhd_out_abs_path = os.path.abspath(vhd_out_name)
vhd_text = f"""-- See make_image_files.py
-- {img_name} : {img_file}
(
"""

# Convert from 8b to 4b colors
def scale_rgb(in_bits, rgb, out_bits):
    def scale(x):
        return int((x / (pow(2, in_bits) - 1)) * (pow(2, out_bits) - 1))

    r, g, b = rgb
    r_new = scale(r)
    g_new = scale(g)
    b_new = scale(b)
    return (r_new, g_new, b_new)


# im = im.convert(mode='P', colors=pow(2,12))

# Convert 8b RGB to 4b RGB
c_text += f"#define {img_name}_DECL \\\n"
c_text += f"static color_12b_t {img_name}[{img_name}_W*{img_name}_H];\\\n"
c_text += f"#pragma VAR_VHDL_INIT {img_name} {vhd_out_abs_path}\\\n"
rgb_im = im.convert("RGB")
# pixel_addr = (rel_pos.y*RECT_W) + rel_pos.x;
for y in range(0, height):
    for x in range(0, width):
        rgb_8b = rgb_im.getpixel((x, y))
        rgb_4b = scale_rgb(8, rgb_8b, 4)
        r, g, b = rgb_4b
        # c_text += f"{img_name}[{x}][{y}].r = {r};\\\n"
        # c_text += f"{img_name}[{x}][{y}].g = {g};\\\n"
        # c_text += f"{img_name}[{x}][{y}].b = {b};\\\n"
        vhd_text += f"(red => to_unsigned({r}, 4), green => to_unsigned({g}, 4), blue => to_unsigned({b}, 4)),\n"
vhd_text = vhd_text.strip(",\n")
vhd_text += "\n)"
c_text = c_text.strip("\\\n")
c_text += "\n"

# Write output files
fout_name = img_name + ".h"
fout = open(fout_name, "w")
fout.write(c_text)
fout.close()
print(fout_name)
fout = open(vhd_out_name, "w")
fout.write(vhd_text)
fout.close()
print(vhd_out_name)
