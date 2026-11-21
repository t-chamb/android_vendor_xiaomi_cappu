#!/usr/bin/env python3
"""Replace the PowerVR DDK 1.7 user-space driver with DDK 1.9@4893595.

Source: an Android 8.1 MT8173 blob set (github.com/iiowoii3389/android_vendor_xiaomi_cappu,
branch lineage-15.1-test), whose kernel tree carries the matching 1.9 kernel driver.

Taken from 1.9: the GPU libraries, gralloc (now gralloc.mt8173.so), Vulkan with its
libufwriter dependency, the firmware, and the newer libgralloc_extra/libged that keep buffer
metadata in GED. Kept from the Android 7 set: libgpu_aux and libion_mtk (1.9 finds every
symbol it needs in them) and everything outside the GPU stack.

usage: import-ddk19.py <path to the 1.9 vendor tree's proprietary/ directory>
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OURS = HERE / "proprietary"
MK = HERE / "cappu-vendor.mk"

FROM_19 = [
    "vendor/firmware/rgx.fw.signed",
] + [f"vendor/{arch}/{name}" for arch in ("lib", "lib64") for name in (
    "libsrv_um.so", "libIMGegl.so", "libusc.so", "libglslcompiler.so", "libufwriter.so",
    "libPVRScopeServices.so", "libgralloc_extra.so", "libged.so",
    "egl/libEGL_mtk.so", "egl/libGLESv1_CM_mtk.so", "egl/libGLESv2_mtk.so",
    "hw/gralloc.mt8173.so", "hw/vulkan.mt8173.so",
)]

# 1.7-only pieces: folded into libIMGegl / the kernel driver in 1.9, or renamed.
REMOVE = [
    "vendor/bin/pvrsrvctl",
    "vendor/lib64/libsrv_init.so",
    "vendor/lib/libpvrANDROID_WSEGL.so", "vendor/lib64/libpvrANDROID_WSEGL.so",
    "vendor/lib/hw/gralloc.mt8173.img.so", "vendor/lib64/hw/gralloc.mt8173.img.so",
]


def line(rel):
    return f"    vendor/xiaomi/cappu/proprietary/{rel}:system/{rel} \\"


def main():
    src = Path(sys.argv[1])
    for rel in FROM_19:
        if not (src / rel).is_file():
            raise SystemExit(f"missing in source: {rel}")

    mk = MK.read_text().splitlines()
    for rel in REMOVE:
        hits = [i for i, l in enumerate(mk) if l.strip().startswith(f"vendor/xiaomi/cappu/proprietary/{rel}:")]
        if len(hits) != 1:
            raise SystemExit(f"{rel}: expected one makefile line, found {len(hits)}")
        del mk[hits[0]]
        (OURS / rel).unlink()

    listed = {re.split(r"[:\s]", l.strip())[0] for l in mk if "proprietary/" in l}
    insert_at = max(i for i, l in enumerate(mk) if "proprietary/vendor/lib64/hw/" in l)
    for rel in FROM_19:
        dst = OURS / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, dst)
        if f"vendor/xiaomi/cappu/proprietary/{rel}" not in listed:
            mk.insert(insert_at, line(rel))
            insert_at += 1

    # The last entry of a PRODUCT_COPY_FILES block has no continuation backslash; keep every
    # block well-formed by re-deriving the trailing backslashes.
    out = []
    for i, l in enumerate(mk):
        if "proprietary/" in l and l.rstrip().endswith("\\"):
            nxt = mk[i + 1] if i + 1 < len(mk) else ""
            if "proprietary/" not in nxt:
                l = l.rstrip()[:-1].rstrip()
        elif "proprietary/" in l and not l.rstrip().endswith("\\"):
            nxt = mk[i + 1] if i + 1 < len(mk) else ""
            if "proprietary/" in nxt:
                l = l.rstrip() + " \\"
        out.append(l)
    MK.write_text("\n".join(out) + "\n")
    print(f"copied {len(FROM_19)} files from DDK 1.9, removed {len(REMOVE)} DDK 1.7-only files")


if __name__ == "__main__":
    main()
