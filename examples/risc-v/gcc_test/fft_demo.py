# Helper script for fft demo c code
# reset; gcc fft_demo.c -lm -o fft_demo && ./fft_demo | python3 fft_demo.py
import sys
from PIL import Image, ImageColor
import numpy as np
from matplotlib import pyplot as plt

# Helper for plotting signals and looking at spectrum
def plot_signal(s, fs, fc, title="", use_psd=False):
  N=len(s)

  is_complex = True
  if type(s[0]) is not np.complex128:
    is_complex = False
    s = s.real

  # Time Domain Plot
  plt.figure()
  #plt.subplot(311)
  plt.title(title + f": Time domain {N} samples")
  t_s = np.arange(N) / fs 
  if is_complex:
    plt.plot(t_s, s.real, 'k', label='I')
    plt.plot(t_s, s.imag, 'r', label='Q')
  else:
    plt.plot(t_s, s, 'k', label='s')
  plt.legend(loc="upper left")
  plt.xlim(t_s[0], t_s[-1])
  plt.xlabel('Time (s)')
  plt.ylabel('Amplitude')

  # Frequency Domain Plot
  # Take the fourier transform of the signal and perform FFT Shift
  S_unshifted = np.fft.fft(s, N)
  #S = np.fft.fftshift(S_unshifted / N)s
  plt.figure()
  plt.title(title + f": {N} point FFT")
  plt.plot(range(0,N), S_unshifted.real, 'k', label='I')
  plt.plot(range(0,N), S_unshifted.imag, 'r', label='Q')
  plt.xlabel('Frequency Bins')
  plt.ylabel('FFT output (max=NFFT)')
  plt.legend(loc="upper left")
  '''
  plt.subplot(212)
  plt.title("20*log10(abs(fft output)" + title)
  plt.plot(f_hz, 20*np.log10(np.abs(S)))
  f_hz = (fc + (np.arange(0, fs, fs/N) - (fs/2) + (fs/N)))
  plt.xlim(f_hz[0], f_hz[-1])
  #plt.ylim(-100, 0)
  plt.xlabel('Frequency (Hz)')
  plt.ylabel('Amplitude (dBFS)')
  #plt.show()
  '''

  if use_psd:
    plt.figure()
    #plt.subplot(313)
    plt.title("PSD " + title)
    plt.psd(s, NFFT=1024, Fs=fs, Fc=fc)
    plt.xlim(f_hz[0], f_hz[-1])
  #plt.show()

# Parse the C code output from std in
vga_data = []
vga_x_max = 0
vga_y_max = 0
input_i = []
input_j = []
#output_fi = []
output_i = []
output_j = []
output_p = []
for line in sys.stdin:
  toks = line.split(",")
  # Input signal
  if "i,xi,xj" in line:
    input_i.append(float(toks[4]))
    input_j.append(float(toks[5]))
    #print("i,xi,xj",line)
  # Output signal
  elif "i,re,im,p" in line:
    #output_fi.append(float(toks[4]))
    output_i.append(float(toks[5]))
    output_j.append(float(toks[6]))
    output_p.append(float(toks[7]))
  # Output image
  elif "x,y,c" in line:
    #print("x,y,c",line)
    x = int(toks[3])
    y = int(toks[4])
    c = int(toks[5])
    if x > vga_x_max:
      vga_x_max = x
    if y > vga_y_max:
      vga_y_max = y
    vga_data.append((x,y,c))


# Convert input to np complex and plot
input_i = np.array(input_i)
input_j = np.array(input_j)
s = (input_i + 1j*input_j)
N=len(s)
freq = 0.0 # center/LO freq
fs = 64.0 # ?
plot_signal(s, fs, freq, "Input Signal")


# Plot fft output from C code
plt.figure()
plt.title("C code FFT output")
plt.plot(range(0,N), output_i, 'k', label='I')
plt.plot(range(0,N), output_j, 'r', label='Q')
plt.legend(loc="upper left")
plt.xlabel('Frequency bins')
plt.ylabel('FFT output (max=NFFT)')
'''
plt.figure()
plt.title(f"C code fft power")
plt.plot(output_fi, output_p, 'k')
plt.xlabel('Frequency (?)')
plt.ylabel('Power (?)')
'''


plt.show()


# Fake screen to prototype drawing
im = Image.new('1', (vga_x_max+1,vga_y_max+1)) # create the Image of size 1 pixel
for (x,y,c) in vga_data:
  # TODO use c value
  im.putpixel((x,y), ImageColor.getcolor('black', '1')) # or whatever color you wish
im.save('fft_demo.png') # or any image format
