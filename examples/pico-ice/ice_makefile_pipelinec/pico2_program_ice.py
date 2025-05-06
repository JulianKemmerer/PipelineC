# from https://pico2-ice.tinyvision.ai/md_mpy.html
from machine import Pin
import ice

file = open("gateware.bin", "br")
flash = ice.flash(miso=Pin(4), mosi=Pin(7), sck=Pin(6), cs=Pin(5))
flash.erase(4096)  # Optional
flash.write(file)
# Optional
#   frequency config needs to match top.sv SB_HFOSC#(.CLKHF_DIV param?
fpga = ice.fpga(
    cdone=Pin(40),
    clock=Pin(21),
    creset=Pin(31),
    cram_cs=Pin(5),
    cram_mosi=Pin(4),
    cram_sck=Pin(6),
    frequency=12,
)
fpga.start()
# start() does not reboot FPGA?
# Start the FPGA with the same bitstream now too
fpga.cram(file)
