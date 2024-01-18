# `The Design`:
```
Radio tuned center on FM station -> IQ from radio -> 
FIR w/ decim by D: ~300KHz band-> ~300KSPS IQ ->
  In this case D is large and needs to be broken into stages:
    D = d0 * d1 * d2 etc 
FM DEMOD differentiator -> ~300KSPS 16b Raw FM signal (has mono+stereo+etc)
FIR w/ decim by (N/M): 15KHz band low pass for mono audio 
  Interpolate by N w/ FIR
  Decim by M w/ FIR
  -> 48KSPS 16b audio samples (noisey)
FM deemphasis (flatten noise) -> 48KSPS 16b audio samples .wav file
```

## `FIR Design`:
* FIR transition width ~= 1/3 of band
* Stopband + transition width should all fall WITHIN the Nyquist freq
* http://t-filter.engineerjs.com/
```py
# Last two FIRs are same 
# 10x decim ratio to sample rate
# (Same FIR taps)
def print_fir_config(fs, decim_factors):
  for d in decim_factors: 
    bw_in = fs/2
    fs_out = fs/d
    bw_out = fs_out/2
    tw = bw_out/3
    pass_width = bw_out-tw
    stop = bw_out
    print(fs,"Hz decim by",d)
    print("pass",0,"Hz->",pass_width,"Hz","tw",tw)
    print("stop",stop,"Hz->",bw_in,"Hz")
    fs = fs_out

print_fir_config(125e6, [5,10,10])
print_fir_config(6e6, [5,5,5])
print_fir_config(6e6, [24])
```


# `Future Radio Platform`:
IQ from radio 125MSPS
125MSPS decim by D=500 = 250KSPS (~300KSPS requirement)
  stages=[5,10,10]
250KSPS upsample by N=24 = 6MSPS
then downsample by M=125 = 48KSPS
  stages=[5,5,5 # can reuse 5x decim?]


TODO DECIDE on how to handle some `static` stateful functions not meeting 125MHz
...likely need CDC in final design running after radio decim slower...


# `Simulation`:

* Work in progress `tb/` dir.
* `compare_samples.py` produces input samples and compares output.
* `rm sim_output.log; python3 compare_samples.py && ../../../src/pipelinec tb.c --sim --comb --cocotb --ghdl --run 250 &> sim_output.log && python3 compare_samples.py`


# `Hardware Test`:

Hear audio? :)
