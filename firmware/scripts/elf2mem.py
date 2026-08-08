#!/usr/bin/env python3
"""Convert an ELF32 little-endian RISC-V image into IMEM/DMEM hex for $readmemh.

IMEM base: 0x00000000 (word array, 2048 x 32)
DMEM base: 0x10000000 (word array, 2048 x 32)
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

IMEM_BASE = 0x00000000
DMEM_BASE = 0x10000000
MEM_WORDS = 2048
MEM_BYTES = MEM_WORDS * 4


def parse_elf32(data: bytes):
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    (ei_class, ei_data) = data[4], data[5]
    if ei_class != 1:
        raise ValueError("need ELF32")
    if ei_data != 1:
        raise ValueError("need little-endian ELF")

    (
        e_type,
        e_machine,
        e_version,
        e_entry,
        e_phoff,
        e_shoff,
        e_flags,
        e_ehsize,
        e_phentsize,
        e_phnum,
        e_shentsize,
        e_shnum,
        e_shstrndx,
    ) = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)

    segments = []
    off = e_phoff
    for _ in range(e_phnum):
        (
            p_type,
            p_offset,
            p_vaddr,
            p_paddr,
            p_filesz,
            p_memsz,
            p_flags,
            p_align,
        ) = struct.unpack_from("<IIIIIIII", data, off)
        off += e_phentsize
        if p_type != 1:  # PT_LOAD
            continue
        segments.append(
            {
                "vaddr": p_vaddr,
                "filesz": p_filesz,
                "memsz": p_memsz,
                "data": data[p_offset : p_offset + p_filesz],
            }
        )
    return e_entry, segments


def place(mem: bytearray, base: int, vaddr: int, blob: bytes, label: str):
    if vaddr < base or vaddr + len(blob) > base + MEM_BYTES:
        raise ValueError(
            f"{label} segment VA 0x{vaddr:08x}+{len(blob)} out of range "
            f"[0x{base:08x}, 0x{base + MEM_BYTES:08x})"
        )
    off = vaddr - base
    mem[off : off + len(blob)] = blob


def to_hex(mem: bytearray) -> str:
    lines = ["@00000000"]
    for i in range(0, MEM_BYTES, 4):
        w = int.from_bytes(mem[i : i + 4], "little")
        lines.append(f"{w:08x}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("elf", type=Path)
    ap.add_argument("--imem", type=Path, required=True)
    ap.add_argument("--dmem", type=Path, required=True)
    args = ap.parse_args()

    data = args.elf.read_bytes()
    entry, segs = parse_elf32(data)
    imem = bytearray(MEM_BYTES)
    dmem = bytearray(MEM_BYTES)

    for seg in segs:
        va = seg["vaddr"]
        blob = seg["data"]
        if va < DMEM_BASE:
            place(imem, IMEM_BASE, va, blob, "IMEM")
        else:
            place(dmem, DMEM_BASE, va, blob, "DMEM")

    args.imem.write_text(to_hex(imem))
    args.dmem.write_text(to_hex(dmem))
    print(
        f"elf2mem: entry=0x{entry:08x} "
        f"imem={args.imem} dmem={args.dmem}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
