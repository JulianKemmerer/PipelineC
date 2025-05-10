# Based on https://pico2-ice.tinyvision.ai/md_mpy.html
# and Discord conversations
from machine import Pin
import ice

# Frequency config should match main.py too so same at reboot
fpga = ice.fpga(
    cdone=Pin(40),
    clock=Pin(21),  # aka ICE_35
    creset=Pin(31),
    cram_cs=Pin(5),
    cram_mosi=Pin(4),
    cram_sck=Pin(6),
    frequency=12,  # Frequency for ICE_35
)

# Stop the FPGA
fpga.stop()

# Do flash operations
file = open("gateware.bin", "br")
flash = ice.flash(miso=Pin(4), mosi=Pin(7), sck=Pin(6), cs=Pin(5))
# flash.erase(4096)  # Optional
flash.write(file)

# Start FPGA
fpga.start()
fpga.reset()  # in new versions

# Now FPGA should be up and running new gateware...
