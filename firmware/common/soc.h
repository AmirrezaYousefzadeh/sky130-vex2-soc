#ifndef SKY130_VEX2_SOC_H
#define SKY130_VEX2_SOC_H

#include <stdint.h>

#define TOHOST   (*(volatile uint32_t *)0x20000000u)
#define GPIO     (*(volatile uint32_t *)0x20000004u)
#define SLEEP    (*(volatile uint32_t *)0x20000008u)
#define STATUS   (*(volatile uint32_t *)0x2000000Cu)

#define GPIO_DONE_BIT  (1u << 0)
#define STATUS_SLEEPING (1u << 0)

/* Write nonzero to tohost to halt the SoC. Prefer 1..255 for PASS codes. */
static inline void halt(uint32_t code)
{
  TOHOST = code;
  for (;;)
    ;
}

static inline void gpio_set_done(int done)
{
  GPIO = done ? GPIO_DONE_BIT : 0u;
}

/* Request clock-gate sleep; returns after TB wake (+ MEIP pulse / mret). */
static inline void sleep_until_wake(void)
{
  SLEEP = 1u;
  /* One nop so the store retires before we depend on wake; core_clk may
   * already be gated here — execution resumes after the TB wake edge. */
  __asm__ volatile ("nop");
}

#endif
