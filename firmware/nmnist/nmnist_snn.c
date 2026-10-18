/* Event-driven (asynchronous) N-MNIST classifier for sky130_vex2_soc.
 *
 *   N-MNIST events pooled to NMNIST_IN channels --W1--> NMNIST_HID integrate-and-fire neurons --W2--> NMNIST_OUT
 *   output integrators. ONE EVENT AT A TIME: no time step, no leak, no layer barrier. Every event updates the
 *   hidden membranes, hidden spikes update the outputs immediately, and the decision (argmax with margin) is
 *   checked after every event.
 *
 * Clock-gated schedule (the testbench plays the sample's event times on the free-running clk):
 *   init -> sleep -> [ wake at event i -> process event i -> sleep ] x N_EV -> wake -> halt
 * The core only runs while an event is processed; gpio_done rises at the first decision.
 *
 * PASS: tohost = decided class + 1 (== NMNIST_EXPECT + 1) and the output integrators equal the Python reference.
 * FAIL codes: 0xE0pp wrong class pp, 0xE1kk output k differs from the reference, 0xE2pp undecided (argmax pp).
 */
#include <stdint.h>
#include "../common/soc.h"
#ifndef NMNIST_WEIGHTS_H_FILE
#define NMNIST_WEIGHTS_H_FILE "weights.h"   /* the Makefile points this at NMNIST_DIR/weights.h */
#endif
#include NMNIST_WEIGHTS_H_FILE

static int32_t v[NMNIST_HID];      /* membranes, saturated to the int16 range as in the reference */
static uint8_t fired[NMNIST_HID];  /* refractory flag (one spike per sample) when NMNIST_REFRACTORY */
static int32_t o[NMNIST_OUT];      /* output integrators */

static inline int32_t sat16(int32_t x)
{
  if (x > 32767)
    return 32767;
  if (x < -32768)
    return -32768;
  return x;
}

static void process_event(uint32_t c)
{
  const int8_t *row = &W1[c * NMNIST_HID];
  for (int j = 0; j < NMNIST_HID; j++) {
    int32_t x = sat16(v[j] + (int32_t)row[j]);
#if NMNIST_REFRACTORY
    if (x >= NMNIST_THETA && !fired[j]) {
      fired[j] = 1;
#else
    if (x >= NMNIST_THETA) {
#endif
      const int8_t *w2 = &W2[j * NMNIST_OUT];
      for (int k = 0; k < NMNIST_OUT; k++)
        o[k] += (int32_t)w2[k];
      x = 0;
    }
    v[j] = x;
  }
}

/* argmax(o) if top1 - top2 >= NMNIST_MARGIN, else -1 */
static int decide(void)
{
  int32_t b1 = o[0], b2 = (int32_t)0x80000000;
  int bi = 0;
  for (int k = 1; k < NMNIST_OUT; k++) {
    if (o[k] > b1) {
      b2 = b1;
      b1 = o[k];
      bi = k;
    } else if (o[k] > b2) {
      b2 = o[k];
    }
  }
  return (b1 - b2 >= NMNIST_MARGIN) ? bi : -1;
}

int main(void)
{
  int pred = -1;

  gpio_set_done(0);
  sleep_until_wake();                 /* init done; the TB wakes the core at the first event */

  for (int e = 0; e < NMNIST_N_EV; e++) {
    process_event(EVENTS[e]);
    if (pred < 0) {
      pred = decide();
      if (pred >= 0)
        gpio_set_done(1);             /* decision latency: the TB records this edge */
    }
    sleep_until_wake();               /* next event, or the final wake for halt */
  }

  for (int k = 0; k < NMNIST_OUT; k++)
    if (o[k] != REF_O[k])
      return 0xE100 | k;
  if (pred < 0) {
    int bi = 0;
    for (int k = 1; k < NMNIST_OUT; k++)
      if (o[k] > o[bi])
        bi = k;
    if (NMNIST_REF_DECISION_EV < 0)
      return 11 + bi;                 /* undecided, as the reference (short stream): PASS code 11..20 */
    return 0xE200 | bi;
  }
  if (pred == NMNIST_EXPECT)
    return pred + 1;
  return 0xE000 | (pred & 0xFF);
}
