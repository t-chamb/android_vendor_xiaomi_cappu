#!/usr/bin/env python3
"""Grow the GraphicBuffer allocations in the Android 7 blobs.

The blobs do `operator new(232)` (136 on 32-bit) and then call a GraphicBuffer constructor that
now lives in the Android 12 libui (or a shim that constructs the Android 12
class in place).  The Android 12 object is 256 bytes (160 on 32-bit), so the constructor would
write 24 bytes past the allocation.  This rewrites each `mov w0, #232` that
feeds such an allocation to `mov w0, #256`.  Originals are kept as *.gb232.orig.
Idempotent.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "proprietary"

# (objdump, extra args, [(old insn bytes, new insn bytes)], old-or-new operand regex, lib dirs)
ABIS = [
    # arm64: mov w0, #0xe8 (232) -> mov w0, #0x100 (256)
    ("aarch64-linux-gnu-objdump", [], [(bytes.fromhex("001d8052"), bytes.fromhex("00208052"))],
     r"\s*([0-9a-f]+):\s+mov\s+w0, #0x(?:e8|100)\b", ["vendor/lib64", "lib64"]),
    # arm (Thumb): movs r0, #136 -> movs r0, #160, or the 4-byte mov.w form
    ("arm-none-eabi-objdump", ["-M", "force-thumb"],
     [(bytes.fromhex("8820"), bytes.fromhex("a020")), (bytes.fromhex("4ff08800"), bytes.fromhex("4ff0a000"))],
     r"\s*([0-9a-f]+):\s+mov(?:s|\.w)\s+r0, #(?:136|160)\b", ["vendor/lib", "lib"]),
]


def sites(lib, objdump, args, operand):
    dis = subprocess.run([objdump, "-d", "--no-show-raw-insn", *args, str(lib)],
                         capture_output=True, text=True).stdout.splitlines()
    out, unmatched = [], 0
    for i, line in enumerate(dis):
        if re.search(r"blx?\s.*_ZN7android13GraphicBufferC[12]E", line):
            for prev in reversed(dis[max(0, i - 120):i]):
                m = re.match(operand, prev)
                if m:
                    out.append(int(m.group(1), 16))
                    break
            else:
                unmatched += 1
    return sorted(set(out)), unmatched


def vaddr_to_offset(lib):
    segs = []
    for line in subprocess.run(["readelf", "-lW", str(lib)], capture_output=True, text=True).stdout.splitlines():
        f = line.split()
        if f and f[0] == "LOAD":
            segs.append((int(f[2], 16), int(f[1], 16), int(f[4], 16)))  # vaddr, offset, filesz

    def conv(addr):
        for vaddr, off, size in segs:
            if vaddr <= addr < vaddr + size:
                return addr - vaddr + off
        sys.exit(f"{lib}: {addr:#x} is not in a LOAD segment")
    return conv


def main():
    for objdump, args, encodings, operand, dirs in ABIS:
        libs = sorted(l for d in dirs for l in (ROOT / d).rglob("*.so"))
        for lib in libs:
            syms = subprocess.run(["readelf", "-W", "--dyn-syms", str(lib)], capture_output=True, text=True).stdout
            if "GraphicBufferC" not in syms:
                continue
            data = bytearray(lib.read_bytes())
            conv = vaddr_to_offset(lib)
            found, unmatched = sites(lib, objdump, args, operand)
            changed = 0
            for addr in map(conv, found):
                for old, new in encodings:
                    cur = bytes(data[addr:addr + len(old)])
                    if cur == old:
                        data[addr:addr + len(old)] = new
                        changed += 1
                        break
                    if cur == new:
                        break
                else:
                    sys.exit(f"{lib}: unexpected bytes at file offset {addr:#x}")
            if changed:
                orig = lib.with_name(lib.name + ".gb232.orig")
                if not orig.exists():
                    shutil.copy2(lib, orig)
                lib.write_bytes(data)
            note = f" ({unmatched} constructor call(s) without a recognised allocation)" if unmatched else ""
            print(f"{lib.relative_to(ROOT)}: {len(found)} site(s), patched {changed} now{note}")


main()
