# Firmware for sky130_vex2_soc
#   make -C firmware all                  # MNIST MLP (default workload)
#   make -C firmware all WORKLOAD=nmnist  # event-driven N-MNIST SNN
ROOT      := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
FW        := $(ROOT)/firmware
BUILD     := $(FW)/build
MNIST     := $(FW)/mnist
NMNIST    := $(FW)/nmnist

TOOLCHAIN ?= $(ROOT)/tools/riscv-none-elf-gcc/bin/riscv-none-elf
CC        := $(TOOLCHAIN)-gcc
OBJDUMP   := $(TOOLCHAIN)-objdump
SIZE      := $(TOOLCHAIN)-size
ELF2MEM   := $(ROOT)/firmware/scripts/elf2mem.py

WORKLOAD  ?= mnist
ifeq ($(WORKLOAD),mnist)
  NAME := mnist_mlp
  SRC  := $(MNIST)/mnist_mlp.c
  HDR  := $(MNIST)/weights.h
else ifeq ($(WORKLOAD),nmnist)
  NMNIST_DIR ?= $(NMNIST)            # directory with weights.h / events.hex / events.vh (e.g. a trimmed copy)
  NAME := nmnist_snn
  SRC  := $(NMNIST)/nmnist_snn.c
  HDR  := $(NMNIST_DIR)/weights.h
  EXTRA_CFLAGS := -DNMNIST_WEIGHTS_H_FILE='"$(abspath $(NMNIST_DIR))/weights.h"'
else
  $(error unknown WORKLOAD '$(WORKLOAD)' (mnist|nmnist))
endif

ARCH      := -march=rv32im_zicsr -mabi=ilp32
OPT       ?= -Os
CFLAGS    := $(ARCH) $(OPT) -g -ffreestanding -nostdlib -Wall -Wextra \
             -fno-builtin -fno-common -ffunction-sections -fdata-sections \
             -I$(FW) $(EXTRA_CFLAGS)
LDFLAGS   := $(ARCH) -nostdlib -T$(FW)/link.ld -Wl,--gc-sections -Wl,-Map=$(BUILD)/$(NAME).map

.PHONY: all clean train train-nmnist sizes

# Fresh build tree every time so stale objects/hex do not accumulate.
all:
	$(MAKE) clean
	$(MAKE) $(BUILD)/$(NAME).elf $(BUILD)/imem.hex $(BUILD)/dmem.hex sizes WORKLOAD=$(WORKLOAD)

train: $(MNIST)/weights.h

$(MNIST)/weights.h: $(MNIST)/train_export.py
	python3 $(MNIST)/train_export.py --out $(MNIST)/weights.h --epochs 3

# N-MNIST: trains the event-driven network and exports weights.h, events.hex, events.vh, report.json
train-nmnist:
	python3 $(NMNIST)/train_export.py --out $(NMNIST)/weights.h

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/crt0.o: $(FW)/crt0.S | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/$(NAME).o: $(SRC) $(HDR) $(FW)/common/soc.h | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/$(NAME).elf: $(BUILD)/crt0.o $(BUILD)/$(NAME).o
	$(CC) $(LDFLAGS) $^ -o $@ -lgcc
	$(OBJDUMP) -d $@ > $(BUILD)/$(NAME).dis

$(BUILD)/imem.hex $(BUILD)/dmem.hex: $(BUILD)/$(NAME).elf
	python3 $(ELF2MEM) $< --imem $(BUILD)/imem.hex --dmem $(BUILD)/dmem.hex

sizes: $(BUILD)/$(NAME).elf
	$(SIZE) $<

clean:
	rm -rf $(BUILD)
