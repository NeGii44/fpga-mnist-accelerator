import torch, torch.nn as nn, torch.optim as optim
import torchvision, torchvision.transforms as transforms
import numpy as np, os

torch.manual_seed(0)
OUT = "hex_files"

class HardwareMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(784, 60, bias=False)
        self.fc2 = nn.Linear(60, 30, bias=False)
        self.fc3 = nn.Linear(30, 10, bias=False)
    def forward(self, x):
        x = x.view(-1, 784)
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)

def to_hex8(v):
    v = int(max(min(v, 127), -128))
    return f"{(v & 0xFF):02X}"

def quantize(W):
    t = W.detach().numpy()
    return np.round(t * (127.0 / np.max(np.abs(t)))).astype(np.int64)

def export_wide(Wq, path):            # Wq: [out, in]; one line = 10 neurons, neuron i in bits [8i+:8]
    out_n, in_n = Wq.shape
    with open(path, "w") as f:
        for p in range(out_n // 10):
            for s in range(in_n):
                f.write("".join(to_hex8(Wq[p*10 + i, s]) for i in reversed(range(10))) + "\n")

def to_int_images(raw):
    return np.round(raw.numpy().reshape(-1, 784) / 255.0 * 127).astype(np.int64)

def pick_shift(acc):
    peak = np.percentile(acc[acc > 0], 99.9)
    s = 0
    while peak / (1 << s) > 127:
        s += 1
    return s

def hw_forward(x, W1, W2, W3, s1, s2):          # bit-exact model of the RTL
    a1 = np.minimum(np.maximum(x @ W1.T, 0) >> s1, 127)
    a2 = np.minimum(np.maximum(a1 @ W2.T, 0) >> s2, 127)
    return a2 @ W3.T

def main():
    tf = transforms.Compose([transforms.ToTensor()])
    trainset = torchvision.datasets.MNIST('./data', train=True,  download=True, transform=tf)
    testset  = torchvision.datasets.MNIST('./data', train=False, download=True, transform=tf)
    trainloader = torch.utils.data.DataLoader(trainset, batch_size=64, shuffle=True)
    testloader  = torch.utils.data.DataLoader(testset, batch_size=1000)

    model = HardwareMLP()
    opt = optim.Adam(model.parameters(), lr=0.002)
    crit = nn.CrossEntropyLoss()
    for ep in range(5):
        model.train(); tot = 0
        for xb, yb in trainloader:
            opt.zero_grad(); loss = crit(model(xb), yb); loss.backward(); opt.step(); tot += loss.item()
        print(f"Epoch {ep+1}/5 loss {tot/len(trainloader):.4f}")

    model.eval(); c = n = 0
    with torch.no_grad():
        for xb, yb in testloader:
            c += (model(xb).argmax(1) == yb).sum().item(); n += len(yb)
    print(f"Float accuracy: {100*c/n:.2f}%")

    W1, W2, W3 = (quantize(m.weight) for m in (model.fc1, model.fc2, model.fc3))

    # pick shifts on training images, measure on test images
    xc = to_int_images(trainset.data[:5000])
    acc1 = xc @ W1.T;                      s1 = pick_shift(acc1)
    a1 = np.minimum(np.maximum(acc1, 0) >> s1, 127)
    acc2 = a1 @ W2.T;                      s2 = pick_shift(acc2)

    xt = to_int_images(testset.data)
    pred = hw_forward(xt, W1, W2, W3, s1, s2).argmax(1)
    print(f"HARDWARE-EXACT accuracy: {100*(pred == testset.targets.numpy()).mean():.2f}%")
    print(f"\n>>> SHIFT1 = {s1}   SHIFT2 = {s2}   <<<  (paste into accelerator_top.sv)")

    os.makedirs(OUT, exist_ok=True)
    export_wide(W1, f"{OUT}/fc1_wide.hex")
    export_wide(W2, f"{OUT}/fc2_wide.hex")
    export_wide(W3, f"{OUT}/fc3_wide.hex")

    img = xt[0]
    with open(f"{OUT}/sample_image.hex", "w") as f:
        for v in img: f.write(to_hex8(v) + "\n")
    with open(f"{OUT}/sample_image.h", "w") as f:
        f.write("uint8_t mnist_image[784] = {" + ",".join(str(int(v)) for v in img) + "};\n")
    print(f"Sample image label = {int(testset.targets[0])}, hardware-model prediction = {int(pred[0])}")

if __name__ == "__main__":
    main()