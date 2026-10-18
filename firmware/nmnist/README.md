# Event-driven N-MNIST workload (asynchronous inference, one event at a time)

A second workload for `sky130_vex2_soc` next to the MNIST MLP: a spiking classifier for the N-MNIST event
stream that is **trained and executed event by event, without a time step, a bin or a leak tick**. The
firmware wakes for every input event, updates the network, checks the decision and sleeps again, so the core's
duty cycle follows the sensor's event rate and the decision is available as soon as the evidence suffices.

## Network

| | MNIST MLP (`../mnist`) | N-MNIST SNN (this) |
|---|---|---|
| input | 8x8 grey image (64 values) | N-MNIST events pooled to 8x8 per polarity (128 channels), first saccade (100 ms) |
| hidden | 32 ReLU, int8 weights | 32 integrate-and-fire neurons, int8 weights, threshold 256, no leak |
| output | 10 logits | 10 integrators fed by hidden spikes (int8 weights) |
| execution | one dense pass per image | per event: `v += W1[c]`, spike if `v >= THETA`, `o += W2[j]`; decision when top1 - top2 >= MARGIN |
| DMEM | 2.4 KB weights | 4.4 KB weights + 1 byte per event of the sample |

Per event, the firmware ([`nmnist_snn.c`](nmnist_snn.c)) adds the weight row of the event's channel to the 32
membranes, fires the neurons that crossed the threshold (reset to zero; optionally once per sample) and adds their
output weights to the ten integrators. The output can be read after any event; the first event at which the
margin is reached raises `gpio_done`, the testbench records that time as the decision latency.

## Training and export

[`train_export.py`](train_export.py) downloads N-MNIST through Tonic (1.2 GB) or reads pre-extracted arrays
(`--prepared`), trains the network with surrogate gradients on 1 ms micro-bins (weights rounded with a
straight-through estimator, anytime cross-entropy weighted towards later times), then evaluates the exported
integer weights **event by event with the exact reference of the firmware** on the test set: accuracy, accuracy
versus time since stimulus onset, spikes per sample, and decision accuracy/latency for several margins. It exports:

- `weights.h`: `W1`, `W2`, the constants, the channel sequence of one test sample (`EVENTS`), its label and the
  reference output integrators after the last event (`REF_O`, checked bit-exactly by the firmware);
- `events.hex` / `events.vh`: the event times of that sample in clock cycles, replayed by the testbench;
- `report.json`: everything measured.

```bash
make -C firmware train-nmnist                                  # or: python3 firmware/nmnist/train_export.py --help
make -C firmware all WORKLOAD=nmnist
./simulation/run_sim.sh nmnist                                 # RTL, full stream, PASS + decision latency
```

Options worth knowing: `--pool 8|10|12|16` (input grid), `--hidden`, `--refractory none|sample`, `--margins`,
`--margin auto|N`, `--max_events K` (export only the first K events of the sample for a short power run),
`--sample i` (which test sample to embed).

## Where the data lives, and what the testbench does

The channel of every event of the embedded sample (which of the 128 pooled inputs fired, in order) is a byte array
in the RISC-V data memory. Its *timing* is not: a sensor would deliver the events one by one at their own times,
and that is what the testbench emulates. It holds the event timestamps (`events.hex`, in clock cycles) and, at each
event's time, wakes the core; the firmware pops the next channel from its list, processes it, and sleeps again. If an
event falls due while the previous one is still being processed, the testbench waits for the core to sleep and
delivers it late, exactly as a sensor FIFO would. So the core's compute time, idle time and backlog are those of a
real-time stream; only the transport of the channel id (preloaded instead of an input port) is simplified. Adding an
event input port would have meant changing and re-hardening the SoC.

## Measurement

- **Latency**: the testbench ([`../../simulation/tb_fw_nmnist.v`](../../simulation/tb_fw_nmnist.v)) replays the
  sample's event times on the free-running clock, wakes the core for each event once it is asleep, and reports the
  awake cycles per event, late deliveries (events that fell due while the previous one was still being processed)
  and the decision time. With `-DEVENT_LOG=<csv>` it also logs every event's due time, delivery time and awake cycles.
- **Hardware time for the whole test set** ([`hw_latency.py`](hw_latency.py)): the awake cycles of an event are
  `c0 + c1 x (hidden spikes it fires)`, fitted on that log; every test sample is then replayed through the exact
  reference with that cost and the single-core queue of the testbench, which gives the accuracy versus *hardware*
  time (output valid only once the event has been processed), the backlog statistics and the minimum clock that keeps
  up with the stream. The same script evaluates the MNIST MLP of this repository (int8, 8x8) and draws both on one
  time axis, the MLP as a frame-based pipeline (frame period + 1.39 ms of inference).
- **Energy**: `./simulation/run_gls.sh nmnist --vcd` on a short export (`--max_events 100`) gives the gate-level
  activity of the per-event processing; `power/run_avg_power.sh` turns it into awake and sleep power; and
  [`../../power/nmnist_energy.py`](../../power/nmnist_energy.py) combines that with the full-stream testbench
  report into energy per event, energy to the decision and energy per sample.

## Results (checked-in snapshot, 50 MHz, sky130_fd_sc_ms, TT 1.8 V)

Exact per-event reference on the 10,000 test samples (`report.json`): **96.5 %** accuracy at the end of the
first saccade; 369 hidden spikes per sample; with the exported margin of 256 the decision is correct for 94.3 % of
the samples (96.8 % decide within 100 ms) at a median of **26.9 ms** after stimulus onset (82 % accuracy at 20 ms,
91.5 % at 30 ms, 95.8 % at 50 ms). A refractory period of one spike per sample drops accuracy to 70 %; a 10x10 grid
or 48 hidden neurons gain at most one point and do not fit next to the event list in 8 KiB.

Embedded test sample (digit 0, 1,745 events in 100 ms), firmware built with `-O3`, testbench replay on the RTL
(`docs/results/nmnist_sim.txt`), gate-level SDF run of the first 100 events for power (`nmnist_gls_short.txt`,
`nmnist_power_energy.txt`), combined by `nmnist_energy.py` (`nmnist_energy.txt`):

| Metric | Value |
|---|---|
| awake cycles per event | 917 mean, 1,222 max (18.3 µs mean at 50 MHz) |
| real-time behaviour | 921 of 1,745 events delivered late, worst backlog 113 µs (the core keeps up on average: 32 % duty) |
| decision | event 202, 26.62 ms after stream start (event time 26.57 ms, 44 µs processing backlog), bit-exact with the reference |
| awake / sleep power (OpenSTA) | 12.75 mW / 0.19 mW |
| energy per event | 234 nJ |
| energy to the decision | **51.5 µJ** (47.2 µJ awake + 4.3 µJ sleep) |
| energy per 100 ms sample | 421 µJ; 4.23 mW average at the sample's real-time event rate |

Hardware-time latency over the whole test set (`docs/results/nmnist_hw_latency.json`, figure
`docs/figures/nmnist_vs_mnist_latency.png`): cost model 901 + 70 cycles per hidden spike (rms residual 59 cycles,
delivery times within 61 cycles of the testbench on average); accuracy 81 % at 20 ms, 92 % at 30 ms, 96 % at 50 ms
in hardware time, indistinguishable from sensor time; margin decision at a median of 26.9 ms (hardware) for 97 % of
the samples, 97.4 % of those decisions correct; awake duty 27 % mean, 55 % maximum; worst backlog 3.4 ms; the mean event
rate is sustained down to a 13.5 MHz clock. The frame-based MNIST MLP of this repository answers 1.39 ms after a frame
is complete, i.e. at 101 or 301 ms for 100 or 300 ms frame periods, with 87.5 % accuracy (its 3-epoch 8x8 training).

For comparison, the dense MNIST MLP inference on the same SoC costs 12.65 µJ: processing 1,745 events through
32 neurons in software is about 56,000 neuron updates against 2,400 multiply-accumulates. The per-event schedule
buys the early decision (26 ms into a 100 ms stimulus) and a duty cycle that follows the sensor, not energy.

Caveat on the power model: `run_avg_power.sh` applies a global toggle rate (0.01 per cycle) to all nets, the
measured activity only to the SRAM `ce`/`we` pins, and a case analysis of the core clock gate for sleep. The
awake power is therefore the same for both workloads (12.75 mW) and the energy figures above scale with awake
cycles and duty, not with the switching detail of the per-event code. A per-pin activity flow (as in the author's
`sky130-snn-bmi` repository) would refine the absolute numbers; the cycle counts and the latency are exact.
