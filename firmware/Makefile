# Firmware for sky130_vex2_soc
ROOT      := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
FW        := $(ROOT)/firmware
BUILD     := $(FW)/build
MNIST     := $(FW)/mnist

TOOLCHAIN ?= $(ROOT)/tools/riscv-none-elf-gcc/bin/riscv-none-elf
CC        := $(TOOLCHAIN)-gcc
OBJDUMP   := $(TOOLCHAIN)-objdump
SIZE      := $(TOOLCHAIN)-size
ELF2MEM   := $(ROOT)/firmware/scripts/elf2mem.py

ARCH      := -march=rv32im -mabi=ilp32
CFLAGS    := $(ARCH) -Os -g -ffreestanding -nostdlib -Wall -Wextra \
             -fno-builtin -fno-common -ffunction-sections -fdata-sections \
             -I$(FW)
LDFLAGS   := $(ARCH) -nostdlib -T$(FW)/link.ld -Wl,--gc-sections -Wl,-Map=$(BUILD)/mnist_mlp.map

.PHONY: all clean train sizes

# Fresh build tree every time so stale objects/hex do not accumulate.
all:
	$(MAKE) clean
	$(MAKE) $(BUILD)/mnist_mlp.elf $(BUILD)/imem.hex $(BUILD)/dmem.hex sizes

train: $(MNIST)/weights.h

$(MNIST)/weights.h: $(MNIST)/train_export.py
	python3 $(MNIST)/train_export.py --out $(MNIST)/weights.h --epochs 3

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/crt0.o: $(FW)/crt0.S | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/mnist_mlp.o: $(MNIST)/mnist_mlp.c $(MNIST)/weights.h $(FW)/common/soc.h | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/mnist_mlp.elf: $(BUILD)/crt0.o $(BUILD)/mnist_mlp.o
	$(CC) $(LDFLAGS) $^ -o $@ -lgcc
	$(OBJDUMP) -d $@ > $(BUILD)/mnist_mlp.dis

$(BUILD)/imem.hex $(BUILD)/dmem.hex: $(BUILD)/mnist_mlp.elf
	python3 $(ELF2MEM) $< --imem $(BUILD)/imem.hex --dmem $(BUILD)/dmem.hex

sizes: $(BUILD)/mnist_mlp.elf
	$(SIZE) $<

clean:
	rm -rf $(BUILD)
