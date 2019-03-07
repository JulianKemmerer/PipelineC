```
██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗ ██████╗
██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝██╔════╝
██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ██║     
██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ██║     
██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗╚██████╗
╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝
```

C for hardware architectures based on pipelines.

Get started by reading the wiki. https://github.com/JulianKemmerer/PipelineC/wiki

PipelineC code generates synthesizable VHDL describing a hardware pipeline. This is the most basic feature of most industry High Level Synthesis (HLS) tools.

The spectrum of HLS tools tends to look like so:
```
A)
Pro: Highly abstracted and easy to use 
Con: Poor results (compared to hand written hardware description language)   
    to
B)
Pro: Excellent results
Con: So low level you might as well be writing in a hardware description language
```
On the A) side you make little to no modifications to the original code. Any software developer off the street can be up and running quickly. 

On the B) side of things you are likely doing a complete rewrite of the code to 'some ugly pragma ridden version of C'. You likely still require a hardware engineer on your team even if a skilled software developer is writing the code.

Right now PipelineC is closer to the B side of things - closer to writing hardware description language. I haven't made it too ugly yet and so far only basic hardware knowledge is required. For software folks I want writing PipelineC to feel like solving a programming puzzle in C, not a whole new programming language. The rules of the puzzle hide/imply hardware concepts. For hardware folks I want PipelineC to be a better hardware description language.


