import random

MNIST_IMAGE_WIDTH=28
MNIST_IMAGE_HEIGHT=28
MNIST_IMAGE_SIZE=MNIST_IMAGE_WIDTH * MNIST_IMAGE_HEIGHT
MNIST_LABELS=10

print("PIXELS:")
for j in range(0,MNIST_IMAGE_SIZE):
  print(int(random.uniform(0, 1)*255),",")
print("")

print("BIASES:")
for i in range(0, MNIST_LABELS):
  print(random.uniform(0, 1),",")
print("")

print("WEIGHTS:")
for i in range(0,MNIST_LABELS*MNIST_IMAGE_SIZE):
  print(random.uniform(0, 1),",")
print("")

print("WEIGHTS 2D:")
for i in range(0,MNIST_LABELS):
  for j in range(0,MNIST_IMAGE_SIZE):
    print(f"weight[{i}][{j}] = {random.uniform(0, 1)};")
print("")

N=16
print(f"WEIGHTS BY {N}:")
for i in range(0,MNIST_LABELS*int(MNIST_IMAGE_SIZE/N)):
  s="{{"
  for n_i in range(0,N):
    s+= str(random.uniform(0, 1)) + " ,"
  s=s.strip(',')
  s += "}},"
  print(s)
print("")

print(f"PIXELS BY {N}:")
for j in range(0,int(MNIST_IMAGE_SIZE/N)):
  s="{{"
  for n_i in range(0,N):
    s+= str(int(random.uniform(0, 1)*255)) + " ,"
  s=s.strip(',')
  s += "}},"
  print(s)
print("")
