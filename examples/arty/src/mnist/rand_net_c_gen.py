import random
for l in range(0,10):
  print("network.b[",l,"] = ", random.uniform(0, 1), ";")
  for i in range(0,(8*8)):
    print("network.W[", l, "]", "[", i, "] = ", random.uniform(0, 1), ";")
