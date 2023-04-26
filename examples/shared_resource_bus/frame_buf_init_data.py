import random
dims = [640,480]
n_pixels = 64
rv = '#define FRAME_BUF_INIT_DATA "('
n_pixels_list = []
for y in range(0, dims[1]):
  for x in range(0, dims[0]):
    if random.randint(0, 1) == 1:
      n_pixels_list.append(1)
    else:
      n_pixels_list.append(0)
    if len(n_pixels_list) == n_pixels:
      pixels_array_str = "("
      for p in n_pixels_list:
        if p == 1:
          pixels_array_str += '\\"1\\", '
        else:
          pixels_array_str += '\\"0\\", '
      n_pixels_list = []
      pixels_array_str = pixels_array_str.strip(' ')
      pixels_array_str = pixels_array_str.strip(',')
      pixels_array_str += ")"
      rv += "( data => " + pixels_array_str + "),\\n\\\n"
rv = rv.strip('\n')
rv = rv.strip(' ')
rv = rv.strip('\\')
rv = rv.strip('\\n')
rv = rv.strip(' ')
rv = rv.strip(',')
rv += ')"'
rv += "\n"
print(rv)
