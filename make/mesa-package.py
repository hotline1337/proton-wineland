#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile


ARCHITECTURES = {
    "x86_64": ("x86_64-linux-gnu", "x86_64", "ELF64", "Advanced Micro Devices X86-64", "64"),
    "i386": ("i386-linux-gnu", "i686", "ELF32", "Intel 80386", "32"),
}


def architecture(name):
    if name not in ARCHITECTURES:
        raise ValueError(f"Unsupported Mesa architecture: {name}")
    return ARCHITECTURES[name]


def command(arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True,
                          env=dict(os.environ, LC_ALL="C")).stdout


def validate_driver(driver, arch):
    _, _, elf_class, machine, _ = architecture(arch)
    output = command(["readelf", "--file-header", "--dynamic", str(driver)])
    for name, expected in (("Class", elf_class), ("Machine", machine)):
        if not re.search(r"^\s*" + name + r":\s*" + re.escape(expected) + r"\s*$", output, re.M):
            raise ValueError(f"Wrong {name} for {arch}: {driver}")
    if not re.search(r"^\s*Data:.*little endian\s*$", output, re.M):
        raise ValueError(f"Expected a little-endian driver: {driver}")
    if not re.search(r"^\s*Type:\s*DYN\b", output, re.M):
        raise ValueError(f"Expected a shared driver: {driver}")
    needed = re.findall(r"\(NEEDED\).*\[([^]]+)\]", output)
    if any(name.startswith("libdrm") for name in needed):
        raise ValueError(f"Mesa must embed its private DRM dependency: {driver}")
    if re.search(r"\((?:RPATH|RUNPATH)\)", output):
        raise ValueError(f"Unexpected driver library search path: {driver}")


def atomic_json(destination, data):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, delete=False) as temporary:
        path = pathlib.Path(temporary.name)
        try:
            json.dump(data, temporary, indent=2)
            temporary.write("\n")
            temporary.close()
            path.chmod(0o644)
            os.replace(path, destination)
        finally:
            path.unlink(missing_ok=True)


def install(driver, upstream_manifest, destination, arch):
    triplet, suffix, _, _, bits = architecture(arch)
    manifest = json.loads(upstream_manifest.read_text())
    icd = manifest.get("ICD") if isinstance(manifest, dict) else None
    if not isinstance(icd, dict) or not isinstance(icd.get("library_path"), str):
        raise ValueError(f"Invalid Vulkan ICD manifest: {upstream_manifest}")
    if not isinstance(icd.get("api_version"), str) or not re.fullmatch(r"\d+\.\d+\.\d+", icd["api_version"]):
        raise ValueError(f"Invalid Vulkan API version: {upstream_manifest}")
    if not isinstance(manifest.get("file_format_version"), str):
        raise ValueError(f"Missing ICD file format version: {upstream_manifest}")
    if "library_arch" in icd and icd["library_arch"] != bits:
        raise ValueError(f"Wrong ICD architecture: {upstream_manifest}")
    validate_driver(driver, arch)
    relative = f"lib/mesa/{triplet}/libvulkan_radeon.so"
    library = destination / relative
    library.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(driver, library)
    icd["library_path"] = "../../../" + relative
    atomic_json(destination / f"share/mesa/icd.d/radeon_icd.{suffix}.json", manifest)


def metadata(source, patches, destination, arches):
    for arch in arches:
        architecture(arch)
    if not arches:
        raise ValueError("Mesa metadata requires architectures")
    if patches is not None and not patches.is_dir():
        raise ValueError("Invalid Mesa patch directory")
    commit = command(["git", "-C", str(source), "rev-parse", "--verify", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid Mesa source commit")
    records = []
    seen = set()
    for patch in sorted(patches.glob("*.patch")) if patches is not None else ():
        content = patch.read_bytes()
        match = re.match(rb"From ([0-9a-f]{40}) ", content)
        if match:
            identity = match[1].decode("ascii")
        elif (content.startswith(b"diff --git ") and
              re.search(rb"^--- (?:a/|/dev/null\b)", content, re.M) and
              re.search(rb"^\+\+\+ (?:b/|/dev/null\b)", content, re.M)):
            result = subprocess.run(["git", "-C", str(source), "apply", "--numstat", "--"], input=content,
                                    check=False, capture_output=True)
            if result.returncode or not result.stdout:
                raise ValueError(f"Invalid raw patch: {patch}")
            identity = hashlib.sha256(content).hexdigest()
        else:
            raise ValueError(f"Invalid patch: {patch}")
        if identity in seen:
            raise ValueError(f"Duplicate patch identity: {patch}")
        seen.add(identity)
        records.append(identity)
    atomic_json(destination / "share/mesa/build.json", {
        "mesa": commit, "patches": records, "architectures": list(dict.fromkeys(arches)),
    })


def data(mesa, libdrm, destination):
    config = destination / "share/mesa/drirc.d"
    files = [(mesa / "src/util/00-mesa-defaults.conf", config / "00-mesa-defaults.conf")]
    files += [(mesa / "src/amd/vulkan" / name, config / name)
              for name in ("00-radv-defaults.conf", "01-radv-performance.conf")]
    files.append((libdrm / "data/amdgpu.ids", destination / "share/mesa/libdrm/amdgpu.ids"))
    contents = [(target, source.read_bytes()) for source, target in files]
    link = config / "99-system.conf"
    for target in [path for path, _ in contents] + [link]:
        for parent in target.parents:
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise FileExistsError(f"Conflicting Mesa data directory: {parent}")
            if parent == destination:
                break
    for target, content in contents:
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise FileExistsError(f"Conflicting Mesa data: {target}")
    if link.is_symlink():
        if os.readlink(link) != "/etc/drirc":
            raise FileExistsError(f"Conflicting system drirc link: {link}")
    elif link.exists():
        raise FileExistsError(f"Conflicting system drirc link: {link}")
    for target, content in contents:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != content:
            with target.open("wb") as output:
                output.write(content)
    if not link.is_symlink():
        link.symlink_to("/etc/drirc")


def main():
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="operation", required=True)
    install_parser = subcommands.add_parser("install")
    for argument in ("driver", "manifest", "destination"):
        install_parser.add_argument(argument, type=pathlib.Path)
    install_parser.add_argument("arch", choices=ARCHITECTURES)
    metadata_parser = subcommands.add_parser("metadata")
    for argument in ("source", "destination"):
        metadata_parser.add_argument(argument, type=pathlib.Path)
    metadata_parser.add_argument("--patches", type=pathlib.Path)
    metadata_parser.add_argument("architectures", nargs="+", choices=ARCHITECTURES)
    data_parser = subcommands.add_parser("data")
    for argument in ("mesa", "libdrm", "destination"):
        data_parser.add_argument(argument, type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.operation == "install":
            install(args.driver, args.manifest, args.destination, args.arch)
        elif args.operation == "metadata":
            metadata(args.source, args.patches, args.destination, args.architectures)
        else:
            data(args.mesa, args.libdrm, args.destination)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
