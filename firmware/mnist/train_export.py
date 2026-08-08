#!/usr/bin/env python3
"""Train a tiny 3-layer MNIST MLP and export int8 weights + one test image for bare-metal C.

Architecture (fits in 8 KiB DMEM):
  8x8 downsampled input (64) -> hidden 32 -> output 10
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

IN = 64
HID = 32
OUT = 10


class TinyMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(IN, HID)
        self.fc2 = nn.Linear(HID, OUT)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        return self.fc2(x)


def downsample_28_to_8(img: torch.Tensor) -> torch.Tensor:
    """img: (N,1,28,28) or (1,28,28) float in [0,1] -> (N,64) or (64,)"""
    squeeze = img.dim() == 3
    if squeeze:
        img = img.unsqueeze(0)
    # 28 -> average 3.5-ish blocks: use adaptive avg pool to 8x8
    x = F.adaptive_avg_pool2d(img, (8, 8))
    x = x.view(x.size(0), -1)
    return x.squeeze(0) if squeeze else x


def quantize_layer(weight: np.ndarray, bias: np.ndarray, in_scale: float):
    """Symmetric int8 weights; bias kept as int32 in same accumulator scale."""
    max_abs = np.max(np.abs(weight)) + 1e-12
    w_scale = max_abs / 127.0
    w_q = np.clip(np.round(weight / w_scale), -127, 127).astype(np.int8)
    # y = (W_q * x_q) * (w_scale * in_scale) + b
    # Store bias already divided so int32 MAC + bias_q, then scale later if needed.
    # For inference we use float-free path:
    #   acc = sum(W_q[i,j] * x_q[j]) + b_q[i]
    #   where b_q = round(b / (w_scale * in_scale))
    b_q = np.round(bias / (w_scale * in_scale)).astype(np.int32)
    out_scale = w_scale * in_scale
    return w_q, b_q, out_scale


def c_array(name: str, arr: np.ndarray, ctype: str) -> str:
    flat = arr.flatten()
    body = ", ".join(str(int(v)) for v in flat)
    return f"static const {ctype} {name}[{flat.size}] = {{ {body} }};\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("weights.h"))
    ap.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[2] / "firmware" / "mnist" / "data")
    args = ap.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tfm = transforms.ToTensor()
    train = datasets.MNIST(args.data, train=True, download=True, transform=tfm)
    test = datasets.MNIST(args.data, train=False, download=True, transform=tfm)
    train_loader = DataLoader(train, batch_size=256, shuffle=True, num_workers=2)
    test_loader = DataLoader(test, batch_size=512, shuffle=False, num_workers=2)

    model = TinyMLP().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)

    print(f"training on {device} for {args.epochs} epoch(s)...")
    model.train()
    for epoch in range(args.epochs):
        total, correct, loss_sum = 0, 0, 0.0
        for x, y in train_loader:
            x = downsample_28_to_8(x.to(device))
            y = y.to(device)
            logits = model(x)
            loss = F.cross_entropy(logits, y)
            opt.zero_grad()
            loss.backward()
            opt.step()
            loss_sum += float(loss.item()) * y.size(0)
            pred = logits.argmax(1)
            correct += int((pred == y).sum().item())
            total += y.size(0)
        print(
            f"  epoch {epoch+1}: loss={loss_sum/total:.4f} "
            f"train_acc={100.0*correct/total:.2f}%"
        )

    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for x, y in test_loader:
            x = downsample_28_to_8(x.to(device))
            y = y.to(device)
            pred = model(x).argmax(1)
            correct += int((pred == y).sum().item())
            total += y.size(0)
    float_acc = 100.0 * correct / total
    print(f"float test accuracy: {float_acc:.2f}%")

    # Pick a correctly classified test sample for the firmware demo.
    sample_img = None
    sample_label = None
    with torch.no_grad():
        for x, y in test_loader:
            x8 = downsample_28_to_8(x.to(device))
            pred = model(x8).argmax(1).cpu()
            for i in range(x.size(0)):
                if int(pred[i]) == int(y[i]):
                    sample_img = x8[i].cpu().numpy().astype(np.float32)
                    sample_label = int(y[i])
                    break
            if sample_img is not None:
                break
    assert sample_img is not None

    # Quantize activations to int8 in [0,255] style from float [0,1]
    x_q = np.clip(np.round(sample_img * 255.0), 0, 255).astype(np.int8)
    # store as uint8 values in int16-friendly range 0..255 using uint8 in C
    x_u8 = np.clip(np.round(sample_img * 255.0), 0, 255).astype(np.uint8)
    x_scale = 1.0 / 255.0

    w1 = model.fc1.weight.detach().cpu().numpy().astype(np.float64)  # HID x IN
    b1 = model.fc1.bias.detach().cpu().numpy().astype(np.float64)
    w2 = model.fc2.weight.detach().cpu().numpy().astype(np.float64)  # OUT x HID
    b2 = model.fc2.bias.detach().cpu().numpy().astype(np.float64)

    w1_q, b1_q, h_scale = quantize_layer(w1, b1, x_scale)

    # Simulate int8 hidden activations with ReLU, then requantize for layer 2.
    # acc1 = W1_q @ x + b1_q ; hidden_f = acc1 * h_scale ; relu ; quantize to int8
    acc1 = w1_q.astype(np.int32) @ x_u8.astype(np.int32) + b1_q
    hidden_f = np.maximum(acc1.astype(np.float64) * h_scale, 0.0)
    h_max = max(np.max(hidden_f), 1e-12)
    h_q_scale = h_max / 127.0
    h_q = np.clip(np.round(hidden_f / h_q_scale), 0, 127).astype(np.int8)

    w2_q, b2_q, out_scale = quantize_layer(w2, b2, h_q_scale)

    # Reference int inference
    acc2 = w2_q.astype(np.int32) @ h_q.astype(np.int32) + b2_q
    pred_q = int(np.argmax(acc2))
    print(f"quantized prediction on sample: {pred_q} (label {sample_label})")

    # Full quantized accuracy (approx, using per-sample hidden requant with fixed h_q_scale
    # from the calibration sample's h_max would be wrong; use global calibration)
    # Recalibrate h_q_scale on a batch:
    calib_hidden = []
    with torch.no_grad():
        for x, _ in DataLoader(train, batch_size=512, shuffle=True):
            x8 = downsample_28_to_8(x).numpy()
            xu = np.clip(np.round(x8 * 255.0), 0, 255).astype(np.uint8)
            a = xu.astype(np.int32) @ w1_q.T.astype(np.int32) + b1_q
            hf = np.maximum(a.astype(np.float64) * h_scale, 0.0)
            calib_hidden.append(hf)
            if sum(h.shape[0] for h in calib_hidden) >= 2048:
                break
    calib = np.concatenate(calib_hidden, axis=0)
    h_max = max(float(np.percentile(calib, 99.5)), 1e-12)
    h_q_scale = h_max / 127.0
    w2_q, b2_q, out_scale = quantize_layer(w2, b2, h_q_scale)

    correct_q, total_q = 0, 0
    with torch.no_grad():
        for x, y in test_loader:
            x8 = downsample_28_to_8(x).numpy()
            xu = np.clip(np.round(x8 * 255.0), 0, 255).astype(np.uint8)
            a1 = xu.astype(np.int32) @ w1_q.T.astype(np.int32) + b1_q
            hf = np.maximum(a1.astype(np.float64) * h_scale, 0.0)
            hq = np.clip(np.round(hf / h_q_scale), 0, 127).astype(np.int8)
            a2 = hq.astype(np.int32) @ w2_q.T.astype(np.int32) + b2_q
            pred = np.argmax(a2, axis=1)
            correct_q += int((pred == y.numpy()).sum())
            total_q += y.size(0)
    quant_acc = 100.0 * correct_q / total_q
    print(f"quantized test accuracy: {quant_acc:.2f}%")

    # Recompute sample with final scales
    a1 = w1_q.astype(np.int32) @ x_u8.astype(np.int32) + b1_q
    hf = np.maximum(a1.astype(np.float64) * h_scale, 0.0)
    hq = np.clip(np.round(hf / h_q_scale), 0, 127).astype(np.int8)
    a2 = w2_q.astype(np.int32) @ hq.astype(np.int32) + b2_q
    pred_q = int(np.argmax(a2))
    if pred_q != sample_label:
        # find another sample that matches under final quant
        found = False
        with torch.no_grad():
            for x, y in test_loader:
                x8 = downsample_28_to_8(x).numpy()
                xu = np.clip(np.round(x8 * 255.0), 0, 255).astype(np.uint8)
                a1 = xu.astype(np.int32) @ w1_q.T.astype(np.int32) + b1_q
                hf = np.maximum(a1.astype(np.float64) * h_scale, 0.0)
                hq = np.clip(np.round(hf / h_q_scale), 0, 127).astype(np.int8)
                a2 = hq.astype(np.int32) @ w2_q.T.astype(np.int32) + b2_q
                pred = np.argmax(a2, axis=1)
                for i in range(x.size(0)):
                    if int(pred[i]) == int(y[i]):
                        x_u8 = xu[i]
                        sample_label = int(y[i])
                        pred_q = int(pred[i])
                        found = True
                        break
                if found:
                    break
        assert found

    # For on-device inference we avoid float: fold ReLU+requant into
    #   h_q = min(127, max(0, (acc1 * h_scale) / h_q_scale))
    #     = min(127, max(0, acc1 * (h_scale/h_q_scale)))
    # Use fixed-point multiply: h_q = sat((acc1 * M) >> S) with M,S chosen.
    ratio = h_scale / h_q_scale
    # Find shift S such that M = round(ratio * 2^S) fits in int32 and is accurate.
    S = 16
    M = int(np.round(ratio * (1 << S)))
    # Verify on sample
    a1 = w1_q.astype(np.int32) @ x_u8.astype(np.int32) + b1_q
    hq_ref = np.clip(np.round(np.maximum(a1.astype(np.float64) * h_scale, 0.0) / h_q_scale), 0, 127).astype(np.int32)
    hq_fx = np.clip((a1.astype(np.int64) * M) >> S, 0, 127).astype(np.int32)
    # ReLU already via clip min 0
    max_err = int(np.max(np.abs(hq_ref - hq_fx)))
    print(f"fixed-point requant: M={M} S={S} max_err={max_err}")

    a2 = w2_q.astype(np.int32) @ hq_fx.astype(np.int32) + b2_q
    pred_fx = int(np.argmax(a2))
    print(f"firmware sample: label={sample_label} pred={pred_fx}")

    # Emit C header used by mnist_mlp.c
    lines = []
    lines.append("/* Auto-generated by train_export.py — do not edit. */\n")
    lines.append("#ifndef MNIST_WEIGHTS_H\n#define MNIST_WEIGHTS_H\n\n")
    lines.append("#include <stdint.h>\n\n")
    lines.append(f"#define MNIST_IN  {IN}\n")
    lines.append(f"#define MNIST_HID {HID}\n")
    lines.append(f"#define MNIST_OUT {OUT}\n")
    lines.append(f"#define MNIST_EXPECT {sample_label}\n")
    lines.append(f"#define H_REQUANT_M {M}\n")
    lines.append(f"#define H_REQUANT_S {S}\n\n")
    lines.append(c_array("W1", w1_q, "int8_t"))  # HID*IN row-major
    lines.append(c_array("B1", b1_q, "int32_t"))
    lines.append(c_array("W2", w2_q, "int8_t"))
    lines.append(c_array("B2", b2_q, "int32_t"))
    lines.append(c_array("INPUT_IMG", x_u8, "uint8_t"))
    lines.append("\n#endif /* MNIST_WEIGHTS_H */\n")
    args.out.write_text("".join(lines))
    print(f"wrote {args.out}")

    meta = args.out.with_suffix(".meta.txt")
    meta.write_text(
        f"float_acc={float_acc:.2f}\n"
        f"quant_acc={quant_acc:.2f}\n"
        f"label={sample_label}\n"
        f"pred={pred_fx}\n"
        f"M={M} S={S}\n"
    )


if __name__ == "__main__":
    main()
