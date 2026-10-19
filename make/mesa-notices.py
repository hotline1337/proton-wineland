#!/usr/bin/env python3
import argparse
import pathlib
import re
import shutil


MESA_TREES = ("include", "src/amd", "src/compiler", "src/vulkan", "src/util", "src/loader", "src/c11", "src/x11", "src/gallium/include")
WAYLAND_PROTOCOLS = ("staging/fifo/fifo-v1.xml", "staging/commit-timing/commit-timing-v1.xml", "unstable/linux-dmabuf/linux-dmabuf-unstable-v1.xml", "stable/presentation-time/presentation-time.xml", "staging/tearing-control/tearing-control-v1.xml", "staging/linux-drm-syncobj/linux-drm-syncobj-v1.xml", "staging/color-management/color-management-v1.xml")
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp", ".inc", ".S", ".s", ".asm", ".glsl", ".comp", ".vert", ".frag", ".geom", ".tesc", ".tese", ".cl", ".py", ".sh", ".build", ".txt", ".xml"}
HASH_SUFFIXES = {".py", ".sh", ".build", ".txt", ".asm", ".S", ".s"}
LEGAL = re.compile(rb"copyright|SPDX-License-Identifier|Permission is hereby granted|Redistribution and use|License for", re.I)
COMMENT = rb"/\*.*?\*/|(?://[^\n]*(?:\n|$))+"
PREPROCESSOR = re.compile(rb"\s*#(?:[^\n]|(?<=\\)\n)*(?:\n|$)")


def legal_headers(path):
    data = path.read_bytes().removeprefix(b"\xef\xbb\xbf")
    if path.suffix == ".xml":
        blocks = re.findall(rb"<copyright(?:\s+[^>]*)?>.*?</copyright\s*>", data, re.S)
        if b"<copyright" in data and not blocks:
            raise ValueError(f"Malformed copyright block: {path}")
        return blocks
    pattern = COMMENT + (rb"|(?:\#[^\n]*(?:\n|$))+" if path.suffix in HASH_SUFFIXES else b"")
    leading = re.compile(rb"\s*(" + pattern + rb")", re.S)
    headers = []
    offset = 0
    while True:
        match = leading.match(data, offset)
        if not match:
            directive = PREPROCESSOR.match(data, offset)
            if directive:
                offset = directive.end()
                continue
            break
        block = match[1]
        if LEGAL.search(block):
            headers.append(block)
        offset = match.end()
    return headers


def collect(root, paths, destination, required):
    records = {}
    seen = set()
    for entry in paths:
        if not entry.exists():
            raise FileNotFoundError(entry)
        candidates = entry.rglob("*") if entry.is_dir() else (entry,)
        for path in sorted(candidates):
            if path.is_symlink() or not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            blocks = legal_headers(path)
            if blocks:
                seen.add(relative)
                records.setdefault(b"\n\n".join(blocks), []).append(relative)
    if missing := set(required) - seen:
        raise ValueError(f"Missing required notices in {root}: {', '.join(sorted(missing))}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        for block, sources in records.items():
            output.write(("\n".join(sources) + "\n\n").encode("utf-8"))
            output.write(block + b"\n\n")


def package(mesa, libdrm, destination, blake3, protocols):
    for path in (mesa / "licenses", mesa / "docs/license.rst", mesa / "src/util/blake3/README", blake3, protocols / "COPYING"):
        if not path.exists():
            raise FileNotFoundError(path)
    if "version 1.8.2" not in (mesa / "src/util/blake3/README").read_text():
        raise ValueError("Review the BLAKE3 licence asset for this Mesa revision")
    if b"Copyright 2019 Jack O'Connor and Samuel Neves" not in blake3.read_bytes():
        raise ValueError("BLAKE3 licence asset lacks its copyright notice")
    for name in ("MIT", "Apache-2.0", "BSL-1.0"):
        if not (mesa / "licenses" / name).is_file():
            raise FileNotFoundError(mesa / "licenses" / name)
    collect(mesa, [mesa / path for path in MESA_TREES], destination / "mesa/COPYRIGHTS", (
        "src/util/softfloat.c", "src/c11/impl/threads_posix.c", "src/amd/vulkan/radv_device.c", "include/vulkan/vulkan_core.h",
    ))
    collect(libdrm, sorted(libdrm.glob("*.c")) + sorted(libdrm.glob("*.h")) + [libdrm / "amdgpu", libdrm / "include"], destination / "libdrm/COPYRIGHTS", (
        "xf86drm.c", "amdgpu/amdgpu_device.c", "include/drm/drm.h",
    ))
    collect(protocols, [protocols / path for path in WAYLAND_PROTOCOLS], destination / "mesa/wayland-protocols/COPYRIGHTS", WAYLAND_PROTOCOLS)
    shutil.copyfile(protocols / "COPYING", destination / "mesa/wayland-protocols/COPYING")
    shutil.copytree(mesa / "licenses", destination / "mesa/licenses", dirs_exist_ok=True)
    shutil.copyfile(mesa / "docs/license.rst", destination / "mesa/license.rst")
    shutil.copyfile(blake3, destination / "mesa/BLAKE3-LICENSE_A2")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mesa", type=pathlib.Path)
    parser.add_argument("libdrm", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--blake3-license", type=pathlib.Path, default=pathlib.Path(__file__).parent / "licenses/mesa-blake3.txt")
    parser.add_argument("--wayland-protocols", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        package(args.mesa, args.libdrm, args.destination, args.blake3_license, args.wayland_protocols)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
