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

## Measurement

- **Latency**: the testbench ([`../../simulation/tb_fw_nmnist.v`](../../simulation/tb_fw_nmnist.v)) replays the
  sample's event times on the free-running clock, wakes the core for each event once it is asleep, and reports the
  awake cycles per event, late deliveries (events that fell due while the previous one was still being processed)
  and the decision time.
- **Energy**: `./simulation/run_gls.sh nmnist --vcd` on a short export (`--max_events 100`) gives the gate-level
  activity of the per-event processing; `power/run_avg_power.sh` turns it into awake and sleep power; and
  [`../../power/nmnist_energy.py`](../../power/nmnist_energy.py) combines that with the full-stream testbench
  report into energy per event, energy to the decision and energy per sample.

Results are summarised in the root README and `docs/results/nmnist_*.txt`.
