#ifndef SKY130_VEX2_SOC_H
#define SKY130_VEX2_SOC_H

#include <stdint.h>

#define TOHOST (*(volatile uint32_t *)0x20000000u)

/* Write nonzero to tohost to halt the SoC. Prefer 1..255 for PASS codes. */
static inline void halt(uint32_t code)
{
  TOHOST = code;
  for (;;)
    ;
}

#endif
