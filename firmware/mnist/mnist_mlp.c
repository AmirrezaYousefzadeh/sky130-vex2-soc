/* 3-layer fully-connected MNIST classifier for sky130_vex2_soc.
 *
 *   INPUT (8x8=64) --FC+ReLU--> HIDDEN (32) --FC--> LOGITS (10)
 *
 * Clock-gated schedule (TB times the sleeps on free-running clk):
 *   init -> sleep -> (TB waits 10k) wake -> one inference -> sleep
 *        -> (TB waits 10k) wake -> halt
 *
 * PASS: tohost = predicted class + 1  (match MNIST_EXPECT)
 */
#include <stdint.h>
#include "../common/soc.h"
#include "weights.h"

static int32_t hidden[MNIST_HID];
static int32_t logits[MNIST_OUT];

static int32_t clamp_i32(int32_t v, int32_t lo, int32_t hi)
{
  if (v < lo)
    return lo;
  if (v > hi)
    return hi;
  return v;
}

static void fc_relu_quant(
    const int8_t *w,
    const int32_t *b,
    const uint8_t *x,
    int32_t *y,
    int in_n,
    int out_n,
    int do_relu_quant)
{
  for (int o = 0; o < out_n; o++) {
    int32_t acc = b[o];
    const int8_t *row = w + o * in_n;
    for (int i = 0; i < in_n; i++)
      acc += (int32_t)row[i] * (int32_t)x[i];
    if (do_relu_quant) {
      int32_t q = (int32_t)(((int64_t)acc * (int64_t)H_REQUANT_M) >> H_REQUANT_S);
      y[o] = clamp_i32(q, 0, 127);
    } else {
      y[o] = acc;
    }
  }
}

static void fc_from_i8(
    const int8_t *w,
    const int32_t *b,
    const int32_t *x,
    int32_t *y,
    int in_n,
    int out_n)
{
  for (int o = 0; o < out_n; o++) {
    int32_t acc = b[o];
    const int8_t *row = w + o * in_n;
    for (int i = 0; i < in_n; i++)
      acc += (int32_t)row[i] * x[i];
    y[o] = acc;
  }
}

static int argmax10(const int32_t *v)
{
  int best_i = 0;
  int32_t best = v[0];
  for (int i = 1; i < MNIST_OUT; i++) {
    if (v[i] > best) {
      best = v[i];
      best_i = i;
    }
  }
  return best_i;
}

static int run_inference(const uint8_t *img)
{
  fc_relu_quant(W1, B1, img, hidden, MNIST_IN, MNIST_HID, 1);
  fc_from_i8(W2, B2, hidden, logits, MNIST_HID, MNIST_OUT);
  return argmax10(logits);
}

int main(void)
{
  /* Power-on wake already ran crt0 init. First gated sleep (TB holds ~10k). */
  gpio_set_done(0);
  sleep_until_wake();

  int pred = run_inference(INPUT_IMG);
  gpio_set_done(1);

  /* Second gated sleep (TB holds ~10k), then wake to halt. */
  sleep_until_wake();

  if (pred == MNIST_EXPECT)
    return pred + 1;
  return 0xE000 | (pred & 0xFF);
}
