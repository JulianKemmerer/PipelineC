#!/usr/bin/env python3
import os
import sys

# sudo ./debug_probes 0 | ./plot_probes.py

# Read from std in pipe
text = sys.stdin.read()
lines = []
include = False
for tok in text.split("\n"):
    if include:
        lines.append(tok)
    # Look for probe names
    if ":" in tok:
        # Get field names
        field_names = tok.split(":")[1].strip().split(",")
        # print("field_names", field_names)
        include = True

# Each field has a list of values
field_value_lists = []
for field_i in range(0, len(field_names)):
    field_value_lists.append([])
for line in lines:
    field_toks = line.split(",")
    if len(field_toks) != len(field_names):
        break
    for field_i in range(0, len(field_names)):
        field_tok = field_toks[field_i]
        field_value_lists[field_i].append(field_tok)
for field_i in range(0, len(field_names)):
    field_name = field_names[field_i]
    # print("Field:",field_name)
    # print(field_value_lists[field_i])

import tempfile

fp = tempfile.NamedTemporaryFile(mode="w")
# fp = open("out.vcd",'w')
from vcd import VCDWriter

with VCDWriter(fp, timescale="1 ns", date="today") as writer:
    field_types = []
    field_vars = []
    for field_i in range(0, len(field_names)):
        # Setup name and type
        field_name = field_names[field_i]
        try:
            int_val = int(field_value_lists[field_i][0])
            field_type = "integer"  #'real'
            field_size = 64  # hardcode assume big enough for now, TODO FIX
            field_var = writer.register_var(
                "debug_probes", field_name, field_type, size=field_size
            )  # init=1.23
        except:
            field_type = "string"
            field_var = writer.register_var("debug_probes", field_name, field_type)
        field_types.append(field_type)
        field_vars.append(field_var)

    # Then values values
    n_values = len(field_value_lists[0])  # Assume all arrays same len
    for value_i in range(0, n_values):
        for field_i in range(0, len(field_names)):
            field_name = field_names[field_i]
            field_type = field_types[field_i]
            field_var = field_vars[field_i]
            if field_type == "integer":
                value = int(field_value_lists[field_i][value_i])
            else:
                value = field_value_lists[field_i][value_i]
                # continue # for now
            timestamp = int(value_i)
            # print("field",field_name)
            # print("value",value)
            # print("timestamp",timestamp)
            writer.change(field_var, timestamp, value)

    # Final change to make final cycle show up
    timestamp = n_values
    for field_i in range(0, len(field_names)):
        field_name = field_names[field_i]
        field_var = field_vars[field_i]
        writer.change(field_var, timestamp, "X")

# print("fp.name",fp.name)

# Run gtk wave
os.system("gtkwave " + fp.name)
