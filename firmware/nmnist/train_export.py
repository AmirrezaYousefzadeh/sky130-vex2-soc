#!/usr/bin/env python3
"""Train an event-driven (asynchronous) N-MNIST spiking classifier for sky130_vex2_soc and export it for bare-metal C.

Network (integer, fits in 8 KiB DMEM next to the event list of one sample):
  N-MNIST events (34x34 pixels x 2 polarities, first saccade = first 100 ms) are pooled on a GxG grid per polarity
  -> N_IN = 2*G*G input channels -> HID integrate-and-fire neurons -> OUT = 10 output integrators.
Execution on the SoC (firmware/nmnist/nmnist_snn.c): ONE EVENT AT A TIME, no time step and no leak:
  event on channel c:   v[j] += W1[c][j]  for all j          (saturating 16-bit)
                        if v[j] >= THETA (and not yet fired when refractory=sample): spike j -> v[j] = 0,
                                                             o[k] += W2[j][k] for all k
  decision:             argmax(o) as soon as top1 - top2 >= MARGIN (the output can be read after any event)
Training uses the same arithmetic on 1 ms micro-bins (surrogate gradients, weights rounded with a straight-through
estimator); the exported weights are then evaluated event by event with the exact integer reference below, which is
also what the firmware is checked against (bit-exact output integrators).

  python3 train_export.py --pool 8 --hidden 32 --epochs 20 --out weights.h
Writes: weights.h (C header), events.hex (event times in clock cycles for the testbench), report.json.
Data: Tonic downloads N-MNIST into --data (1.2 GB); --prepared can point at pre-extracted npz files instead.
"""
from __future__ import annotations
import argparse, json, math, time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
SACCADE_US = 100_000


# ------------------------------------------------------------------------------------------------ data
def load_raw(split: str, data: Path, prepared: Path | None):
    """Returns (t_us int32, ch int16 (p*34*34 + y*34 + x), offsets int64, labels int16) of one split."""
    if prepared is not None and (prepared / f"nmnist_{split}.npz").exists():
        d = np.load(prepared / f"nmnist_{split}.npz")
        return d["t"], d["ch"], d["offsets"], d["labels"]
    cache = data / f"nmnist_raw_{split}.npz"
    if cache.exists():
        d = np.load(cache)
        return d["t"], d["ch"], d["offsets"], d["labels"]
    import tonic
    ds = tonic.datasets.NMNIST(save_to=str(data), train=(split == "train"))
    ts, chs, offs, labels, n = [], [], [0], [], 0
    for ev, y in ds:
        o = np.argsort(ev["t"], kind="stable")
        t = ev["t"][o].astype(np.int64); keep = t < SACCADE_US * 3 + 20_000          # whole sample, 3 saccades
        ch = (ev["p"][o].astype(np.int64) * 34 * 34 + ev["y"][o].astype(np.int64) * 34 + ev["x"][o].astype(np.int64))
        ts.append(t[keep].astype(np.int32)); chs.append(ch[keep].astype(np.int16)); n += int(keep.sum()); offs.append(n); labels.append(int(y))
    t, ch, offsets, labels = np.concatenate(ts), np.concatenate(chs), np.array(offs, np.int64), np.array(labels, np.int16)
    data.mkdir(parents=True, exist_ok=True)
    np.savez(cache, t=t, ch=ch, offsets=offsets, labels=labels)
    return t, ch, offsets, labels


def pool_events(t, ch, G: int):
    """Pool 34x34 pixels to GxG (crop the centre, square blocks); returns (t, pooled channel) with out-of-crop events dropped."""
    k = {8: 4, 10: 3, 12: 2, 16: 2, 17: 2}[G]
    c = G * k; off = (34 - c) // 2
    ch = ch.astype(np.int64)
    p, rem = ch // (34 * 34), ch % (34 * 34)
    y, x = rem // 34, rem % 34
    keep = (x >= off) & (x < off + c) & (y >= off) & (y < off + c)
    pc = p[keep] * G * G + ((y[keep] - off) // k) * G + (x[keep] - off) // k
    return t[keep], pc.astype(np.int16)


def to_samples(t, ch, offsets, labels, G: int, t_end_us: int):
    """List of (t_us, pooled ch) per sample within [0, t_end_us), plus labels."""
    out = []
    for i in range(len(labels)):
        a, b = offsets[i], offsets[i + 1]
        tt, cc = t[a:b].astype(np.int64), ch[a:b]
        keep = tt < t_end_us
        tt, cc = pool_events(tt[keep], cc[keep], G)
        out.append((tt.astype(np.int32), cc))
    return out, labels.astype(np.int64)


def dense_bins(samples, n_in: int, dt_us: int, T: int):
    """(N, T, n_in) uint8 event counts per micro-bin."""
    X = np.zeros((len(samples), T, n_in), np.uint8)
    for i, (tt, cc) in enumerate(samples):
        b = tt // dt_us; keep = b < T
        np.add.at(X[i], (b[keep], cc[keep].astype(np.int64)), 1)
    return X


# ------------------------------------------------------------------------------------------------ model
class RoundSTE(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x): return torch.round(x)
    @staticmethod
    def backward(ctx, g): return g


class SpikeFn(torch.autograd.Function):
    scale = 5.0
    @staticmethod
    def forward(ctx, x):
        ctx.save_for_backward(x); return (x >= 0).to(x.dtype)
    @staticmethod
    def backward(ctx, g):
        (x,) = ctx.saved_tensors; return g / (SpikeFn.scale * x.abs() + 1.0) ** 2


class IFNet(torch.nn.Module):
    def __init__(self, n_in, hid, out, wbits, theta, vbits=16, obits=32, refractory="none", temp0=64.0):
        super().__init__()
        self.n_in, self.hid, self.out, self.theta, self.refractory = n_in, hid, out, theta, refractory
        self.wmax = 2 ** (wbits - 1) - 1; self.vmax = 2 ** (vbits - 1) - 1; self.omax = 2 ** (obits - 1) - 1
        self.W1 = torch.nn.Parameter(torch.randn(n_in, hid)); self.W2 = torch.nn.Parameter(torch.randn(hid, out))
        self.log_temp = torch.nn.Parameter(torch.tensor(math.log(temp0)))

    def q(self): return RoundSTE.apply(self.W1.clamp(-self.wmax, self.wmax)), RoundSTE.apply(self.W2.clamp(-self.wmax, self.wmax))

    def forward(self, x):
        W1, W2 = self.q(); B, T, _ = x.shape
        v = x.new_zeros(B, self.hid); o = x.new_zeros(B, self.out); fired = x.new_zeros(B, self.hid); hist = []; nsp = x.new_zeros(())
        for t in range(T):
            v = (v + x[:, t] @ W1).clamp(-self.vmax - 1, self.vmax)
            s = SpikeFn.apply((v - self.theta) / self.theta)
            if self.refractory == "sample": s = s * (1 - fired); fired = (fired + s).clamp(max=1)
            v = v * (1 - s); nsp = nsp + s.sum()
            o = (o + s @ W2).clamp(-self.omax - 1, self.omax); hist.append(o)
        return torch.stack(hist, 1), nsp

    def loss(self, hist, y, spike_penalty=0.0, nsp=None, weighting="ramp"):
        B, T, C = hist.shape
        w = torch.arange(1, T + 1, device=hist.device).float() if weighting == "ramp" else torch.ones(T, device=hist.device)
        w = w / w.sum()
        ce = F.cross_entropy((hist / self.log_temp.exp()).reshape(B * T, C), y.repeat_interleave(T), reduction="none").reshape(B, T)
        l = (ce * w[None]).sum(1).mean()
        if spike_penalty > 0 and nsp is not None: l = l + spike_penalty * nsp / (B * self.hid * T)
        return l

    @torch.no_grad()
    def calibrate(self, x, target_rate=0.05, iters=8):
        for name in ("W1",):
            lo, hi = math.log(1e-2), math.log(1e3)
            for _ in range(iters):
                mid = 0.5 * (lo + hi); backup = self.W1.clone(); self.W1.mul_(math.exp(mid))
                _, nsp = self.forward(x); rate = float(nsp) / (x.shape[0] * self.hid * x.shape[1]); self.W1.copy_(backup)
                if rate < target_rate: lo = mid
                else: hi = mid
            self.W1.mul_(math.exp(0.5 * (lo + hi)))
        self.W2.mul_(0.5)


# ------------------------------------------------------------------------------------------------ exact per-event reference
def run_events(W1, W2, theta, chans, refractory, vmax=32767, omax=2 ** 31 - 1, margin=None):
    """Exact integer per-event execution of one sample. Returns final o, o after every event (n_ev, OUT), spikes, decision index."""
    H, OUT = W1.shape[1], W2.shape[1]
    v = np.zeros(H, np.int64); o = np.zeros(OUT, np.int64); fired = np.zeros(H, bool)
    hist = np.zeros((len(chans), OUT), np.int64); nsp = 0; decided = -1
    for e, c in enumerate(chans):
        v = np.clip(v + W1[c], -vmax - 1, vmax)
        s = v >= theta
        if refractory == "sample": s &= ~fired; fired |= s
        if s.any():
            v[s] = 0; o = np.clip(o + W2[s].sum(0), -omax - 1, omax); nsp += int(s.sum())
        hist[e] = o
        if decided < 0 and margin is not None and len(o) > 1:
            srt = np.sort(o)
            if srt[-1] - srt[-2] >= margin: decided = e
    return o, hist, nsp, decided


def evaluate_events(W1, W2, theta, samples, labels, refractory, margins, grid_us):
    """Accuracy at the end, accuracy versus time (grid), margin decisions (accuracy, latency), spikes per sample."""
    n = len(samples); acc_t = np.zeros(len(grid_us)); correct = 0; spikes = 0
    mstats = {m: {"correct": 0, "decided": 0, "lat": []} for m in margins}
    for i, ((tt, cc), y) in enumerate(zip(samples, labels)):
        o, hist, nsp, _ = run_events(W1, W2, theta, cc, refractory)
        spikes += nsp
        if len(cc) == 0: continue
        correct += int(o.argmax() == y and o.max() > o.min())
        idx = np.searchsorted(tt, grid_us, side="right") - 1
        og = np.where(idx[:, None] >= 0, hist[np.maximum(idx, 0)], 0)
        acc_t += (og.argmax(1) == y) & (og.max(1) > og.min(1))
        srt = np.sort(hist, 1); gap = srt[:, -1] - srt[:, -2]; pred = hist.argmax(1)
        for m in margins:
            hit = np.flatnonzero(gap >= m)
            if len(hit):
                mstats[m]["decided"] += 1; mstats[m]["correct"] += int(pred[hit[0]] == y); mstats[m]["lat"].append(float(tt[hit[0]]) / 1000)
    res = {"accuracy": correct / n, "spikes_per_sample": spikes / n, "accuracy_vs_time": {"ms": (grid_us / 1000).tolist(), "acc": (acc_t / n).tolist()},
           "margins": {str(m): {"accuracy": s["correct"] / n, "decided": s["decided"] / n,
                                "latency_ms_median": float(np.median(s["lat"])) if s["lat"] else None,
                                "latency_ms_mean": float(np.mean(s["lat"])) if s["lat"] else None} for m, s in mstats.items()}}
    return res


# ------------------------------------------------------------------------------------------------ export
def c_array(name, arr, ctype):
    return f"static const {ctype} {name}[{arr.size}] = {{ {', '.join(str(int(v)) for v in arr.flatten())} }};\n"


def export(out: Path, W1, W2, theta, margin, refractory, G, sample, label, ref_o, ref_decision, ref_spikes, clk_ns, meta):
    n_in, hid = W1.shape; outn = W2.shape[1]
    tt, cc = sample
    h = ["/* Auto-generated by train_export.py -- do not edit. Event-driven N-MNIST IF network for sky130_vex2_soc. */",
         "#ifndef NMNIST_WEIGHTS_H", "#define NMNIST_WEIGHTS_H", "#include <stdint.h>",
         f"#define NMNIST_GRID {G}", f"#define NMNIST_IN {n_in}", f"#define NMNIST_HID {hid}", f"#define NMNIST_OUT {outn}",
         f"#define NMNIST_THETA {theta}", f"#define NMNIST_MARGIN {margin}", f"#define NMNIST_REFRACTORY {1 if refractory == 'sample' else 0}",
         f"#define NMNIST_N_EV {len(cc)}", f"#define NMNIST_EXPECT {label}", f"#define NMNIST_REF_DECISION_EV {ref_decision}",
         f"#define NMNIST_REF_SPIKES {ref_spikes}",
         "/* W1[c*NMNIST_HID + j]: weight from input channel c to hidden neuron j; W2[j*NMNIST_OUT + k] */",
         c_array("W1", W1.astype(np.int8), "int8_t"), c_array("W2", W2.astype(np.int8), "int8_t"),
         "/* input channels of the test sample's events, in time order (times live in events.hex for the testbench) */",
         c_array("EVENTS", cc.astype(np.uint8), "uint8_t"),
         "/* output integrators after the last event, from the exact Python reference (bit-exact check) */",
         c_array("REF_O", ref_o.astype(np.int32), "int32_t"), "#endif"]
    out.write_text("\n".join(h) + "\n")
    cyc = np.ceil(tt.astype(np.float64) * 1000.0 / clk_ns).astype(np.int64)
    (out.parent / "events.hex").write_text("\n".join(f"{int(c):08x}" for c in cyc) + "\n")
    (out.parent / "events.vh").write_text(f"// generated by train_export.py: event count of the exported sample (times in events.hex, in cycles of {clk_ns} ns)\n"
                                          f"localparam integer N_EV = {len(cc)};\n")
    json.dump(meta, open(out.parent / "report.json", "w"), indent=1)


# ------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=8, choices=[8, 10, 12, 16, 17])
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--wbits", type=int, default=8)
    ap.add_argument("--theta", type=int, default=256)
    ap.add_argument("--refractory", default="none", choices=["none", "sample"])
    ap.add_argument("--dt_us", type=int, default=1000)
    ap.add_argument("--t_end_ms", type=float, default=100.0)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=0.5)
    ap.add_argument("--spike_penalty", type=float, default=0.0)
    ap.add_argument("--jitter_us", type=float, default=0.0, help="Gaussian time jitter augmentation (re-binned every epoch)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--margins", default="64,128,256,512,1024")
    ap.add_argument("--margin", default="auto", help="exported margin: integer or 'auto' (smallest margin within 0.5 points of the final accuracy)")
    ap.add_argument("--clk_ns", type=float, default=20.0)
    ap.add_argument("--n_eval", type=int, default=0, help="test samples for the per-event evaluation (0 = all)")
    ap.add_argument("--sample", type=int, default=-1, help="test sample index to export (-1 = first correctly decided one)")
    ap.add_argument("--max_events", type=int, default=0, help="export only the first K events of the sample (0 = all); for short power runs")
    ap.add_argument("--data", type=Path, default=HERE / "data")
    ap.add_argument("--prepared", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=HERE / "weights.h")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    torch.manual_seed(a.seed); np.random.seed(a.seed)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    G, n_in, T, t_end_us = a.pool, 2 * a.pool * a.pool, int(round(a.t_end_ms * 1000 / a.dt_us)), int(a.t_end_ms * 1000)
    t0 = time.time()
    tr = to_samples(*load_raw("train", a.data, a.prepared), G, t_end_us)
    te = to_samples(*load_raw("test", a.data, a.prepared), G, t_end_us)
    print(f"data: {len(tr[0])} train / {len(te[0])} test samples, {n_in} channels, mean {np.mean([len(c) for _, c in tr[0]]):.0f} events in {a.t_end_ms:.0f} ms ({time.time()-t0:.0f} s)", flush=True)
    rng = np.random.default_rng(a.seed)
    Xte = torch.from_numpy(dense_bins(te[0], n_in, a.dt_us, T)); yte = torch.from_numpy(te[1])

    def train_bins():
        if a.jitter_us <= 0:
            return torch.from_numpy(dense_bins(tr[0], n_in, a.dt_us, T))
        jit = [((tt + rng.normal(0, a.jitter_us, len(tt))).clip(0).astype(np.int32), cc) for tt, cc in tr[0]]
        return torch.from_numpy(dense_bins(jit, n_in, a.dt_us, T))
    Xall = train_bins(); yall = torch.from_numpy(tr[1])
    # hold out 10 % of the training set for checkpoint selection (the test set is only used for reporting)
    perm0 = torch.from_numpy(rng.permutation(len(Xall))); n_val = len(Xall) // 10
    val_idx, tr_idx = perm0[:n_val], perm0[n_val:]
    Xtr, ytr, Xva, yva = Xall[tr_idx], yall[tr_idx], Xall[val_idx], yall[val_idx]
    model = IFNet(n_in, a.hidden, 10, a.wbits, a.theta, refractory=a.refractory).to(dev)
    model.calibrate(Xtr[:64].to(dev).float())
    opt = torch.optim.Adam([{"params": [model.W1, model.W2], "lr": a.lr}, {"params": [model.log_temp], "lr": 1e-2}])
    steps = a.epochs * (len(Xtr) // a.batch); sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, steps, eta_min=a.lr * 0.02)

    def accuracy(X, Y):
        model.eval(); correct = 0; spk = 0.0
        with torch.no_grad():
            for s in range(0, len(X), 1024):
                hist, nsp = model(X[s:s + 1024].to(dev).float()); correct += (hist[:, -1].argmax(1).cpu() == Y[s:s + 1024]).sum().item(); spk += nsp.item()
        return correct / len(X), spk / len(X)
    best = (-1, None)
    for ep in range(a.epochs):
        if ep > 0 and a.jitter_us > 0:
            Xall = train_bins(); Xtr, Xva = Xall[tr_idx], Xall[val_idx]
        model.train(); perm = torch.randperm(len(Xtr)); tot = 0.0; nb = 0
        for s in range(0, len(Xtr) - a.batch + 1, a.batch):
            idx = perm[s:s + a.batch]; x = Xtr[idx].to(dev).float(); y = ytr[idx].to(dev)
            hist, nsp = model(x); loss = model.loss(hist, y, a.spike_penalty, nsp)
            opt.zero_grad(set_to_none=True); loss.backward(); opt.step(); sched.step(); tot += loss.item(); nb += 1
        acc, spk = accuracy(Xva, yva)
        print(f"epoch {ep+1}: loss {tot/nb:.4f} val acc (micro-bin model) {acc:.4f} hidden spikes/sample {spk:.1f} ({time.time()-t0:.0f} s)", flush=True)
        if acc >= best[0]: best = (acc, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()})
    model.load_state_dict(best[1])
    test_acc, _ = accuracy(Xte, yte)
    print(f"best val acc {best[0]:.4f}; test acc (micro-bin model) {test_acc:.4f}", flush=True)
    W1, W2 = (w.detach().cpu().numpy().astype(np.int64) for w in model.q())
    # ---- exact per-event evaluation (what the firmware does)
    n = a.n_eval or len(te[0]); margins = [int(m) for m in a.margins.split(",")]
    grid = np.arange(1000, t_end_us + 1, 1000)
    t1 = time.time()
    res = evaluate_events(W1, W2, a.theta, te[0][:n], te[1][:n], a.refractory, margins, grid)
    print(f"per-event reference on {n} test samples: accuracy {res['accuracy']:.4f}, hidden spikes/sample {res['spikes_per_sample']:.1f} ({time.time()-t1:.0f} s)")
    for m in margins:
        s = res["margins"][str(m)]; print(f"  margin {m:5d}: decision accuracy {s['accuracy']:.4f} decided {s['decided']:.3f} latency median {s['latency_ms_median']} ms mean {s['latency_ms_mean']}")
    acc_t = res["accuracy_vs_time"]["acc"]; print("  accuracy at 10/20/30/50/100 ms:", [round(acc_t[i - 1], 4) for i in (10, 20, 30, 50, 100) if i <= len(acc_t)])
    if a.margin == "auto":   # smallest margin within 0.5 points of the final accuracy, else the most accurate one
        ok = [m for m in margins if res["margins"][str(m)]["accuracy"] >= res["accuracy"] - 0.005]
        margin = ok[0] if ok else max(margins, key=lambda m: res["margins"][str(m)]["accuracy"])
    else:
        margin = int(a.margin)
    # ---- pick the sample to export and its reference trajectory
    idx = a.sample
    if idx < 0:
        for i, ((tt, cc), y) in enumerate(zip(te[0], te[1])):
            o, hist, nsp, dec = run_events(W1, W2, a.theta, cc, a.refractory, margin=margin)
            if dec >= 0 and hist[dec].argmax() == y and o.argmax() == y: idx = i; break
    tt, cc = te[0][idx]; y = int(te[1][idx])
    if a.max_events > 0: tt, cc = tt[:a.max_events], cc[:a.max_events]
    o, hist, nsp, dec = run_events(W1, W2, a.theta, cc, a.refractory, margin=margin)
    print(f"exported sample {idx}: label {y}, {len(cc)} events, decision at event {dec} (t = {tt[dec]/1000 if dec >= 0 else -1:.2f} ms), {nsp} hidden spikes, final o {o.tolist()}")
    meta = {"config": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()}, "n_in": n_in, "T": T,
            "micro_bin_val_accuracy": best[0], "micro_bin_test_accuracy": test_acc,
            "per_event": res, "margin": margin, "sample": {"index": idx, "label": y, "n_events": int(len(cc)), "decision_event": int(dec),
            "decision_ms": float(tt[dec]) / 1000 if dec >= 0 else None, "hidden_spikes": int(nsp), "final_o": o.tolist()},
            "memory_bytes": {"W1": int(W1.size), "W2": int(W2.size), "events": int(len(cc))}}
    export(a.out, W1, W2, a.theta, margin, a.refractory, G, (tt, cc), y, o, dec, nsp, a.clk_ns, meta)
    print(f"wrote {a.out}, events.hex, report.json ({time.time()-t0:.0f} s)")


if __name__ == "__main__":
    main()
