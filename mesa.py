"""Opt-in selection of Proton's private RADV build before Vulkan is loaded."""

import json
import os
from pathlib import Path
import platform


ARCHITECTURES = {"x86_64": ("x86_64", "x86_64-linux-gnu", 2, 62),
                 "i386": ("i686", "i386-linux-gnu", 1, 3)}
RUNTIME_ICD_DIR = Path("/usr/lib/pressure-vessel/overrides/share/vulkan/icd.d")
SYSTEM_ROOTS = (Path("/usr/local/etc"), Path("/etc"))
DRIRC_FILES = ("00-mesa-defaults.conf", "00-radv-defaults.conf", "01-radv-performance.conf")


def _paths(value):
    return [Path(path) for path in value.split(os.pathsep) if path]


def _library(path):
    try:
        library = json.loads(path.read_text(encoding="utf-8"))["ICD"]["library_path"]
        return library if isinstance(library, str) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _is_radv(path):
    library = _library(path)
    if library is None:
        return False
    name = Path(library).name
    return name == "libvulkan_radeon.so" or name.startswith("libvulkan_radeon.so.")


def _bundle(files):
    metadata = json.loads((files / "share/mesa/build.json").read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("invalid bundled RADV build metadata")
    requested = metadata.get("architectures")
    if (not isinstance(requested, list) or "x86_64" not in requested or
            any(not isinstance(arch, str) or arch not in ARCHITECTURES for arch in requested) or
            len(set(requested)) != len(requested)):
        raise ValueError("invalid bundled RADV architecture list")
    revision = metadata.get("mesa")
    patches = metadata.get("patches")
    if (not isinstance(revision, str) or len(revision) != 40 or
            any(character not in "0123456789abcdef" for character in revision) or
            not isinstance(patches, list) or
            any(not isinstance(commit, str) or len(commit) not in (40, 64) or
                any(character not in "0123456789abcdef" for character in commit)
                for commit in patches) or len(set(patches)) != len(patches)):
        raise ValueError("invalid bundled RADV source revisions")
    manifests = []
    for name, (arch, triplet, elf_class, machine) in ARCHITECTURES.items():
        if name not in requested:
            continue
        manifest = files / "share/mesa/icd.d" / ("radeon_icd." + arch + ".json")
        library = _library(manifest)
        if not library:
            raise ValueError("missing or invalid bundled " + arch + " manifest")
        driver = (manifest.parent / library).resolve()
        expected = (files / "lib/mesa" / triplet / "libvulkan_radeon.so").resolve()
        if driver != expected:
            raise ValueError("unexpected bundled " + arch + " driver path")
        with driver.open("rb") as stream:
            header = stream.read(20)
        if (len(header) < 20 or header[:4] != b"\x7fELF" or
                header[4] != elf_class or header[5] != 1 or
                int.from_bytes(header[18:20], "little") != machine):
            raise ValueError("invalid bundled " + arch + " driver architecture")
        manifests.append(manifest)
    return manifests, metadata


def _data_paths(files):
    root = files / "share/mesa"
    drirc = root / "drirc.d"
    for name in DRIRC_FILES:
        if not (drirc / name).is_file():
            raise ValueError("missing bundled RADV configuration " + name)
    system = drirc / "99-system.conf"
    if not system.is_symlink() or system.readlink() != Path("/etc/drirc"):
        raise ValueError("missing bundled RADV system configuration link")
    libdrm = root / "libdrm"
    if not (libdrm / "amdgpu.ids").is_file():
        raise ValueError("missing bundled AMD GPU name table")
    return {"DRIRC_CONFIGDIR": str(drirc), "AMDGPU_ASIC_ID_TABLE_PATHS": str(libdrm)}


def _runtime_override(env):
    variables = [name for name in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES") if name in env]
    if not variables:
        return None
    values = [env[name] for name in variables]
    paths = _paths(values[0])
    # Pressure-vessel deliberately exports host-driver manifests in its own
    # namespace. They are the runtime inventory, not a user driver override.
    if (env.get("container") != "pressure-vessel" or not paths or
            any(value != values[0] for value in values) or
            any(path.parent != RUNTIME_ICD_DIR or path.suffix != ".json" or
                not path.is_file() for path in paths)):
        raise ValueError("keeping explicit Vulkan driver selection")
    return paths


def _default_manifests(env):
    home = env.get("HOME", "")
    roots = []
    config = env.get("XDG_CONFIG_HOME") or (str(Path(home) / ".config") if home else "")
    roots.extend(path for path in _paths(config) if path.is_absolute())
    roots.extend(path for path in _paths(env.get("XDG_CONFIG_DIRS") or "/etc/xdg")
                 if path.is_absolute())
    roots.extend(SYSTEM_ROOTS)
    data = env.get("XDG_DATA_HOME") or (str(Path(home) / ".local/share") if home else "")
    roots.extend(path for path in _paths(data) if path.is_absolute())
    roots.extend(path for path in _paths(env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share")
                 if path.is_absolute())
    for root in dict.fromkeys(roots):
        yield from sorted((root / "vulkan/icd.d").glob("*.json"))


def configure(env, files_dir, log):
    """Replace discovered RADV ICDs without changing other GPU drivers or libraries.

    Call before importing utilities or any module which loads Vulkan. Selection
    applies to this interpreter and is inherited by all subsequently launched
    Wine processes. No global library search paths are changed.
    """
    if env.get("PROTON_RADV") != "1":
        return False
    if platform.machine() not in ("x86_64", "amd64"):
        log("Bundled RADV is only available on x86-64")
        return False
    try:
        files = Path(files_dir).resolve()
        bundled, metadata = _bundle(files)
        data_paths = _data_paths(files)
        if "VK_ADD_DRIVER_FILES" in env:
            raise ValueError("keeping explicit VK_ADD_DRIVER_FILES")
        # Repeated launches through the same Proton inherit our selection.
        selected = env.get("VK_DRIVER_FILES", "")
        prefix = os.pathsep.join(map(str, bundled))
        if not (env.get("VK_ICD_FILENAMES") == selected and
                (selected == prefix or selected.startswith(prefix + os.pathsep))):
            runtime = _runtime_override(env)
            existing = runtime if runtime is not None else _default_manifests(env)
            manifests = list(bundled)
            seen = {path.resolve() for path in bundled}
            for path in existing:
                resolved = path.resolve()
                if resolved not in seen and not _is_radv(path):
                    manifests.append(path)
                    seen.add(resolved)
            selected = os.pathsep.join(map(str, manifests))
    except (OSError, ValueError, RuntimeError) as error:
        log("Cannot enable bundled RADV: " + str(error))
        return False

    # Also set the legacy variable for older loaders in child processes.
    env["VK_DRIVER_FILES"] = selected
    env["VK_ICD_FILENAMES"] = selected
    # The packaged system-config link keeps /etc/drirc after Mesa's defaults.
    # Explicit data overrides, including empty values, remain authoritative.
    for name, value in data_paths.items():
        env.setdefault(name, value)
    env["PROTON_RADV_VERSION"] = metadata["mesa"] + "+" + str(len(metadata["patches"]))
    log("Using bundled radv-salkim " + metadata["mesa"][:12] + " with " +
        str(len(metadata["patches"])) + " local patches (" +
        ", ".join(metadata["architectures"]) + ")")
    return True
