"""Send N MNIST test images through ESP32 -> FPGA and report accuracy.
Usage:  python test_mnist.py COM7 100
Needs torchvision (same as train-model.py). Close idf.py monitor first."""
import sys
import numpy as np
import esp_link
from torchvision import datasets

port = sys.argv[1] if len(sys.argv) > 1 else "COM7"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
ds = datasets.MNIST(root="data", train=False, download=True)   # run from the folder that has 'data'
ser = esp_link.open_port(port)
ok = bad = none = 0
for i in range(n):
    img, label = ds[i]
    px = (np.array(img, dtype=np.uint8) >> 1).flatten()      # 0..127, same as training
    d = esp_link.predict(ser, px.tobytes())
    if d is None: none += 1; tag = "NO REPLY"
    elif d == label: ok += 1; tag = "ok"
    else: bad += 1; tag = "WRONG"
    print(f"{i:4d} label={label} fpga={d}  {tag}")
print(f"\ncorrect {ok}/{n} = {100*ok/n:.1f}%   wrong {bad}   no reply {none}")