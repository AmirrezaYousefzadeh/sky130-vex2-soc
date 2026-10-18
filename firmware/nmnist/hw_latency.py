#!/usr/bin/env python3
"""Accuracy versus real hardware time for the event-driven N-MNIST workload on sky130_vex2_soc, against the frame-based
MNIST MLP on the same SoC.

1. Timing model of the firmware, calibrated on the per-event log of the RTL testbench (run_sim.sh nmnist with
   -DEVENT_LOG=<csv>): awake cycles of event i = c0 + c1 * (hidden spikes fired by event i); fitted by least squares.
2. Replay of every test sample through the exact per-event reference with that cost model and the single-core queue
   discipline of the testbench: an event is delivered when it is due and the core is asleep, delivery_i =
   max(t_i, done_{i-1}); done_i = delivery_i + wake overhead + cycles_i * T_clk. The output of event i becomes valid at
   done_i, which includes any processing backlog. Accuracy is then evaluated on a time grid in *hardware* time, next to the
   sensor-time curve (reference outputs valid at the event time itself).
3. The MNIST MLP: int8 inference of the exported network on the 8x8 MNIST test set (same arithmetic as mnist_mlp.c), one
   frame per --frame_ms, so the output is valid at frame_ms + runtime after the stimulus onset.

  python3 hw_latency.py --event_log nmnist_events.csv --prepared <dir> --out docs/results/nmnist_hw_latency.json \
      --fig docs/figures/nmnist_vs_mnist_latency.png
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from train_export import load_raw, to_samples, SACCADE_US  # noqa: E402


def c_array(text, name):
    m = re.search(rf"\b{name}\[(\d+)\]\s*=\s*\{{([^}}]*)\}}", text)
    return np.array([int(v) for v in m.group(2).split(",")], np.int64)


def define(text, name):
    return int(re.search(rf"#define\s+{name}\s+(-?\d+)", text).group(1))


def run_events_spikes(W1, W2, theta, chans, refractory):
    """Exact per-event execution; returns o after every event (n_ev, OUT) and spikes fired per event (n_ev,)."""
    H, OUT = W1.shape[1], W2.shape[1]
    v = np.zeros(H, np.int64); o = np.zeros(OUT, np.int64); fired = np.zeros(H, bool)
    hist = np.zeros((len(chans), OUT), np.int64); nsp = np.zeros(len(chans), np.int64)
    for e, c in enumerate(chans):
        v = np.clip(v + W1[c], -32768, 32767); s = v >= theta
        if refractory: s &= ~fired; fired |= s
        k = int(s.sum())
        if k: v[s] = 0; o = o + W2[s].sum(0)
        hist[e] = o; nsp[e] = k
    return hist, nsp


def mnist_mlp_accuracy(weights_h: Path, data_dir: Path):
    """int8 MLP of firmware/mnist (64 -> 32 -> 10) on the 8x8-pooled MNIST test set, the arithmetic of mnist_mlp.c."""
    import torch, torch.nn.functional as F
    from torchvision import datasets, transforms
    h = weights_h.read_text()
    W1 = c_array(h, "W1").reshape(32, 64); B1 = c_array(h, "B1"); W2 = c_array(h, "W2").reshape(10, 32); B2 = c_array(h, "B2")
    M, S = define(h, "H_REQUANT_M"), define(h, "H_REQUANT_S")
    test = datasets.MNIST(str(data_dir), train=False, download=True, transform=transforms.ToTensor())
    x = torch.stack([img for img, _ in test]); y = np.array([lab for _, lab in test])
    x8 = F.adaptive_avg_pool2d(x, (8, 8)).reshape(len(x), 64).numpy()
    xq = np.clip(np.round(x8 * 255.0), 0, 255).astype(np.int64)
    acc1 = xq @ W1.T + B1
    hid = np.clip((acc1 * M) >> S, 0, 127)
    logits = hid @ W2.T + B2
    return float((logits.argmax(1) == y).mean()), len(y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, default=HERE / "weights.h")
    ap.add_argument("--event_log", type=Path, required=True, help="CSV written by tb_fw_nmnist.v with -DEVENT_LOG")
    ap.add_argument("--prepared", type=Path, default=None); ap.add_argument("--data", type=Path, default=HERE / "data")
    ap.add_argument("--clk_ns", type=float, default=20.0)
    ap.add_argument("--wake_cycles", type=int, default=None, help="fixed wake/sleep overhead per event (default: from the fit intercept)")
    ap.add_argument("--n_samples", type=int, default=0)
    ap.add_argument("--frame_ms", default="300,100", help="frame periods of the frame-based MNIST reference")
    ap.add_argument("--mnist_runtime_cycles", type=int, default=69328, help="MNIST MLP inference cycles (docs/results/power_energy.txt)")
    ap.add_argument("--mnist_weights", type=Path, default=HERE.parent / "mnist" / "weights.h")
    ap.add_argument("--mnist_data", type=Path, default=HERE.parent / "mnist" / "data")
    ap.add_argument("--grid_ms", type=float, default=1.0); ap.add_argument("--t_end_ms", type=float, default=100.0)
    ap.add_argument("--out", type=Path, required=True); ap.add_argument("--fig", type=Path, default=None)
    ap.add_argument("--plot_only", action="store_true", help="re-draw the figure from an existing --out JSON")
    a = ap.parse_args()
    if a.plot_only:
        res = json.load(open(a.out)); plot(res, a.fig); return
    h = a.weights.read_text()
    hid, outn, theta, margin, refr = (define(h, n) for n in ("NMNIST_HID", "NMNIST_OUT", "NMNIST_THETA", "NMNIST_MARGIN", "NMNIST_REFRACTORY"))
    G = define(h, "NMNIST_GRID"); W1 = c_array(h, "W1").reshape(-1, hid); W2 = c_array(h, "W2").reshape(hid, outn)
    ev_sample = c_array(h, "EVENTS"); sample_idx = int(json.load(open(a.weights.parent / "report.json"))["sample"]["index"])
    # ---- 1. calibrate the cost model on the embedded sample
    log = np.loadtxt(a.event_log, delimiter=",", skiprows=1, dtype=np.int64)
    _, spk_sample = run_events_spikes(W1, W2, theta, ev_sample, refr)
    assert len(log) == len(ev_sample), (len(log), len(ev_sample))
    A = np.stack([np.ones(len(log)), spk_sample], 1).astype(np.float64)
    (c0, c1), *_ = np.linalg.lstsq(A, log[:, 3].astype(np.float64), rcond=None)
    resid = log[:, 3] - A @ np.array([c0, c1])
    fit = {"c0_cycles": float(c0), "c1_cycles_per_spike": float(c1), "residual_rms_cycles": float(np.sqrt((resid ** 2).mean())),
           "residual_max_cycles": float(np.abs(resid).max()), "events": int(len(log)), "mean_awake_cycles": float(log[:, 3].mean())}
    print(f"cost model: awake cycles = {c0:.1f} + {c1:.1f} x spikes (rms residual {fit['residual_rms_cycles']:.1f} cycles, max {fit['residual_max_cycles']:.0f})")
    # check the queue model against the testbench on the embedded sample
    t_ev = None  # the TB log holds due cycles = event times in cycles
    due = log[:, 1]; deliver_tb = log[:, 2]
    done = 0; deliver_model = np.zeros(len(log), np.int64)
    for i in range(len(log)):
        d = max(int(due[i]), int(done)); deliver_model[i] = d; done = d + int(round(c0 + c1 * spk_sample[i]))
    fit["delivery_error_cycles_max"] = int(np.abs(deliver_model - deliver_tb).max())
    fit["delivery_error_cycles_mean"] = float(np.abs(deliver_model - deliver_tb).mean())
    print(f"queue model vs testbench deliveries: mean |error| {fit['delivery_error_cycles_mean']:.1f} cycles, max {fit['delivery_error_cycles_max']} cycles")
    # ---- 2. every test sample
    te, labels = to_samples(*load_raw("test", a.data, a.prepared), G, int(a.t_end_ms * 1000))
    n = a.n_samples or len(te)
    grid = np.arange(a.grid_ms * 1000, a.t_end_ms * 1000 + 1, a.grid_ms * 1000)
    acc_sensor = np.zeros(len(grid)); acc_hw = np.zeros(len(grid))
    dec_sensor, dec_hw, backlog_max, backlog_mean, duty, late_frac, dec_correct = [], [], [], [], [], [], []
    T = a.clk_ns * 1e-3  # us per cycle
    for i in range(n):
        tt, cc = te[i]; y = labels[i]
        if len(cc) == 0: continue
        hist, nsp = run_events_spikes(W1, W2, theta, cc, refr)
        cyc = np.round(c0 + c1 * nsp).astype(np.int64)
        done_us = np.zeros(len(cc)); prev = 0.0; busy = 0.0
        for e in range(len(cc)):
            d = max(float(tt[e]), prev); done_us[e] = d + cyc[e] * T; prev = done_us[e]; busy += cyc[e] * T
        backlog = done_us - tt - cyc * T                       # waiting time before processing
        backlog_max.append(backlog.max()); backlog_mean.append(backlog.mean()); duty.append(busy / max(tt[-1], 1))
        late_frac.append(float((backlog > 0).mean()))
        pred = hist.argmax(1); valid = hist.max(1) > hist.min(1)
        for name, times, acc in (("sensor", tt.astype(np.float64), acc_sensor), ("hw", done_us, acc_hw)):
            idx = np.searchsorted(times, grid, side="right") - 1
            ok = (idx >= 0)
            correct = np.zeros(len(grid), bool)
            correct[ok] = (pred[idx[ok]] == y) & valid[idx[ok]]
            acc += correct
        srt = np.sort(hist, 1); gap = srt[:, -1] - srt[:, -2]; hit = np.flatnonzero(gap >= margin)
        if len(hit):
            dec_sensor.append(float(tt[hit[0]]) / 1000); dec_hw.append(done_us[hit[0]] / 1000); dec_correct.append(pred[hit[0]] == y)
    acc_sensor /= n; acc_hw /= n
    # ---- 3. frame-based MNIST MLP
    mlp_acc, n_mnist = mnist_mlp_accuracy(a.mnist_weights, a.mnist_data)
    mlp_runtime_ms = a.mnist_runtime_cycles * a.clk_ns * 1e-6
    frames = [float(f) for f in a.frame_ms.split(",")]
    res = {"cost_model": fit, "clk_ns": a.clk_ns, "n_samples": n, "grid_ms": (grid / 1000).tolist(),
           "accuracy_vs_time_sensor": acc_sensor.tolist(), "accuracy_vs_time_hardware": acc_hw.tolist(),
           "decision": {"margin": margin, "decided_fraction": len(dec_hw) / n, "accuracy": float(np.mean(dec_correct)) if dec_correct else None,
                        "sensor_ms_median": float(np.median(dec_sensor)), "hardware_ms_median": float(np.median(dec_hw)),
                        "sensor_ms_mean": float(np.mean(dec_sensor)), "hardware_ms_mean": float(np.mean(dec_hw))},
           "real_time": {"awake_duty_mean": float(np.mean(duty)), "awake_duty_max": float(np.max(duty)),
                         "backlog_us_max": float(np.max(backlog_max)), "backlog_us_median_of_max": float(np.median(backlog_max)),
                         "late_event_fraction_mean": float(np.mean(late_frac)),
                         "samples_with_duty_above_1": int(np.sum(np.array(duty) > 1.0)),
                         "min_clock_mhz_for_mean_rate": float(1e3 / a.clk_ns * np.mean(duty))},
           "mnist_mlp": {"accuracy": mlp_acc, "n_test": n_mnist, "runtime_ms": mlp_runtime_ms, "frame_ms": frames}}
    a.out.parent.mkdir(parents=True, exist_ok=True); json.dump(res, open(a.out, "w"), indent=1)
    for k in (10, 20, 30, 50, 100):
        j = int(k / a.grid_ms) - 1
        if j < len(grid): print(f"  {k:3d} ms: sensor-time accuracy {acc_sensor[j]:.4f}, hardware-time {acc_hw[j]:.4f}")
    rt = res["real_time"]; d = res["decision"]
    print(f"decision (margin {margin}): median {d['sensor_ms_median']:.2f} ms sensor time, {d['hardware_ms_median']:.2f} ms hardware time, accuracy {d['accuracy']:.4f}")
    print(f"real time: awake duty mean {rt['awake_duty_mean']:.3f} max {rt['awake_duty_max']:.3f}; worst backlog {rt['backlog_us_max']:.0f} us; "
          f"{rt['samples_with_duty_above_1']} samples need more than 100 % duty; minimum clock for the mean event rate {rt['min_clock_mhz_for_mean_rate']:.1f} MHz")
    print(f"MNIST MLP: {100*mlp_acc:.2f} % on {n_mnist} test images, runtime {mlp_runtime_ms:.2f} ms")
    if a.fig: plot(res, a.fig)


def plot(res, fig_path: Path):
    import numpy as np
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]; INK2, MUTED, GRID, AXIS, SURF = "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
    g = np.array(res["grid_ms"]); acc_hw = np.array(res["accuracy_vs_time_hardware"]); acc_sensor = np.array(res["accuracy_vs_time_sensor"])
    frames = res["mnist_mlp"]["frame_ms"]; mlp_acc = res["mnist_mlp"]["accuracy"]; mlp_runtime_ms = res["mnist_mlp"]["runtime_ms"]
    fig, ax = plt.subplots(figsize=(6.4, 3.6), facecolor=SURF); ax.set_facecolor(SURF)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_color(AXIS)
    ax.grid(True, color=GRID, linewidth=0.6); ax.set_axisbelow(True); ax.tick_params(colors=MUTED, labelsize=8)
    t_max = max(frames) + mlp_runtime_ms + 20
    ax.plot(g, acc_hw, color=SERIES[0], linewidth=2, label="N-MNIST, event-driven SNN on the SoC (hardware time)")
    ax.plot([g[-1], t_max], [acc_hw[-1], acc_hw[-1]], color=SERIES[0], linewidth=1.2, linestyle=":", label="N-MNIST, decision held after the saccade")
    ax.plot(g, acc_sensor, color=SERIES[0], linewidth=0.8, linestyle="--", alpha=0.6, label="N-MNIST, sensor time (no processing delay; coincides)")
    for k, f in enumerate(frames):
        t_ready = f + mlp_runtime_ms
        ax.step([0, t_ready, t_max], [0, mlp_acc, mlp_acc], where="post", color=SERIES[1 + k], linewidth=2,
                label=f"MNIST, frame every {f:.0f} ms + MLP on the SoC ({100*mlp_acc:.1f} %)")
    ax.set_xlim(0, t_max); ax.set_ylim(0, 1.02)
    ax.set_xlabel("time since stimulus onset (ms)", color=INK2, fontsize=9); ax.set_ylabel("accuracy", color=INK2, fontsize=9)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    fig.tight_layout(); fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=160); fig.savefig(fig_path.with_suffix(".pdf")); print("wrote", fig_path)


if __name__ == "__main__":
    main()
