# This file contains timing models, and other estimation tools that characterize devices
# The goal to is reduce time spent calling on or iterating with slow synthesis+pnr tools
# Primarily this begins with modelings timing delays, but could model resource usage too in future

# In line with issues like:
# https://github.com/JulianKemmerer/PipelineC/issues/46
# https://github.com/JulianKemmerer/PipelineC/issues/48
# https://github.com/JulianKemmerer/PipelineC/issues/64

# (C) 2022 Victor Surez Rovere <suarezvictor@gmail.com>
# NOTE: only for integer operations (not floats)

import os, re, math

ops = {}


def part_supported(part_str):
    return part_str == "xc7a35ticsg324-1l"


def estimate_int_timing(integer_op, widths_vector):
    timing_model = {  # category, origin, slope
        "arith": (1.92, 0.04),
        "comp": (2.49, 0.0),
        "equal": (1.72, 0.04),
        "logical": (1.28, 0.0),
        "shift": (3.42, 0.0),
    }

    categ = ""
    if integer_op in ["PLUS", "MINUS", "NEGATE"]:
        categ = "arith"
    if integer_op in ["GT", "GTE", "LT", "LTE"]:
        categ = "comp"
    if integer_op in ["EQ", "NEQ"]:
        categ = "equal"
    if integer_op in ["AND", "OR", "XOR", "NOT"]:
        categ = "logical"
    if integer_op in ["SL", "SR"]:
        categ = "shift"
    if categ not in timing_model:
        return None  # unknown operation

    bits = max(widths_vector)
    origin, slope = timing_model[categ]
    return origin + bits * slope


def func_name_to_op_and_widths(func_name):
    p = func_name.find("_OP_")
    if p >= 0:
        optyp = func_name[:p]
        _ = func_name.find("_", p + 4)
        op = func_name[p + 4 : _]
        widths = re.findall(r"int[0-9]+", func_name[4:])
        if not len(widths):
            return None
        widths = [int(w[3:]) for w in widths]  # cut 'int'
        return op, widths
    return None


def process_delays(dir_path):
    print("real\top\testimation\twidths")
    mindelay = 1e6
    total = count = 0
    for path in os.listdir(dir_path):
        full = os.path.join(dir_path, path)
        if os.path.isfile(full):
            op_and_widths = func_name_to_op_and_widths(path)
            if op_and_widths is not None:
                op, widths = op_and_widths
                estim_ns = estimate_int_timing(op, widths)
                with open(full, "r") as file:
                    time_ns = float(file.read())

                if estim_ns is not None:
                    if time_ns < mindelay:
                        mindelay = time_ns
                    total += (time_ns - estim_ns) ** 2
                    count += 1
                    print(
                        str(time_ns)
                        + "\t"
                        + op
                        + "\t"
                        + str(estim_ns)
                        + "\t".join([str(w) for w in widths])
                    )

    rms = math.sqrt(total / count)
    print("Count:", count, ", minimum delay (ns):", mindelay, ", RMS error (ns):", rms)
