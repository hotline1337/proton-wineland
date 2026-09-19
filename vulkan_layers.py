"""Per-launch Vulkan loader ordering for the Wayland Steam overlay bridge."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SETTINGS = "vulkan/loader_settings.d/vk_loader_settings.json"
STEAM_LAYERS = {"x86_64": "VK_LAYER_VALVE_steam_overlay_64",
                "i386": "VK_LAYER_VALVE_steam_overlay_32"}


def _paths(value):
    return [Path(p) for p in value.split(os.pathsep) if p and os.path.isabs(p)]


def _search_roots(env):
    home = env.get("HOME", "")
    roots = []
    for variable, default in (("XDG_CONFIG_HOME", ".config"),
                              ("XDG_DATA_HOME", ".local/share")):
        value = env.get(variable) or (os.path.join(home, default) if home else "")
        roots.extend(_paths(value))
    roots.extend(_paths(env.get("XDG_CONFIG_DIRS") or "/etc/xdg"))
    roots.extend((Path("/etc"), Path("/usr/local/etc")))
    roots.extend(_paths(env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"))
    return list(dict.fromkeys(roots))


def _implicit_manifests(env):
    if env.get("VK_IMPLICIT_LAYER_PATH"):
        paths = _paths(env["VK_IMPLICIT_LAYER_PATH"])
    else:
        paths = _paths(env.get("VK_ADD_IMPLICIT_LAYER_PATH", ""))
        paths += [p / "vulkan/implicit_layer.d" for p in _search_roots(env)]
    for path in dict.fromkeys(paths):
        if path.is_file():
            yield path
        else:
            yield from sorted(path.glob("*.json"))


def _steam_manifests(env, arches):
    wanted = {STEAM_LAYERS[arch] for arch in arches}
    found = {}
    for path in _implicit_manifests(env):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            layers = data.get("layers", [data.get("layer", {})])
            for layer in layers:
                name = layer.get("name")
                if name in wanted and name not in found:
                    found[name] = str(path)
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return found if wanted <= found.keys() else None


def _probe(env):
    # A subprocess uses Wine's library search environment without loading Vulkan
    # or changing the environment of the Proton interpreter itself.
    result = subprocess.run([sys.executable, os.path.abspath(__file__), "--probe"],
                            env=env, capture_output=True, text=True, timeout=5)
    if result.returncode:
        return None
    return json.loads(result.stdout)


def configure(env, manifest_dir, arches, cache_dir, log):
    """Install private loader ordering, returning False to disable the bridge.

    Only Steam and the translator are ordered explicitly. All other layers keep
    their normal activation rules and are discovered by the loader itself.
    """
    try:
        # Do not replace or merge the user's Vulkan Configurator policy.
        if any((root / SETTINGS).exists() for root in _search_roots(env)):
            log("Keeping existing Vulkan loader settings")
            return False

        steam = _steam_manifests(env, arches)
        if steam is None:
            log("Cannot locate Steam overlay manifests for Vulkan layer ordering")
            return False

        layers = [{"name": STEAM_LAYERS[arch], "path": steam[STEAM_LAYERS[arch]],
                   "control": "auto", "treat_as_implicit_manifest": True}
                  for arch in arches]
        for arch in arches:
            path = Path(manifest_dir) / ("VkLayer_WINELAND_translate_" + arch + ".json")
            layer = json.loads(path.read_text(encoding="utf-8"))["layer"]
            layers.append({"name": layer["name"], "path": str(path), "control": "auto"})
        layers.append({"control": "unordered_layer_location"})
        contents = json.dumps({"file_format_version": "1.0.0",
                               "settings": {"layers": layers}}, indent=2) + "\n"

        # Immutable, content-addressed files remain valid for surviving Wine
        # children and concurrent launches. Nothing is written to the user's XDG
        # directories. Other XDG lookups simply continue through the old paths.
        root = Path(cache_dir) / hashlib.sha256(contents.encode()).hexdigest()[:16]
        target = root / SETTINGS
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                                 dir=target.parent, delete=False) as stream:
                    temp_path = stream.name
                    stream.write(contents)
                os.replace(temp_path, target)
                temp_path = None
            finally:
                if temp_path is not None:
                    os.unlink(temp_path)

        candidate = dict(env)
        candidate["XDG_CONFIG_DIRS"] = str(root) + os.pathsep + (env.get("XDG_CONFIG_DIRS") or "/etc/xdg")
        available = _probe(candidate)
        expected = [layer["name"] for layer in layers[:-1]
                    if available and layer["name"] in available]
        if (not available or STEAM_LAYERS["x86_64"] not in expected or
                "VK_LAYER_WINELAND_translate_x86_64" not in expected or
                available[:len(expected)] != expected):
            log("Runtime Vulkan loader cannot apply private layer ordering")
            return False

        env["XDG_CONFIG_DIRS"] = candidate["XDG_CONFIG_DIRS"]
        env["PROTON_WAYLAND_VULKAN_LAYER_ORDER"] = "1"
        log("Vulkan layer order: Steam overlay, Wineland translation, other enabled layers")
        return True
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        log("Cannot configure Vulkan layer ordering: " + str(error))
        return False


def _enumerate_layers():
    import ctypes as c

    class Properties(c.Structure):
        _fields_ = [("name", c.c_char * 256), ("spec", c.c_uint32),
                    ("implementation", c.c_uint32), ("description", c.c_char * 256)]

    loader = c.CDLL("libvulkan.so.1")
    version = c.c_uint32()
    get_version = loader.vkEnumerateInstanceVersion
    get_version.argtypes = [c.POINTER(c.c_uint32)]
    get_version.restype = c.c_int32
    if get_version(c.byref(version)) or version.value < ((1 << 22) | (4 << 12) | 304):
        raise RuntimeError("Vulkan loader settings require loader 1.4.304 or later")
    enumerate_layers = loader.vkEnumerateInstanceLayerProperties
    enumerate_layers.argtypes = [c.POINTER(c.c_uint32), c.POINTER(Properties)]
    enumerate_layers.restype = c.c_int32
    for _ in range(3):
        count = c.c_uint32()
        if enumerate_layers(c.byref(count), None):
            break
        properties = (Properties * count.value)()
        result = enumerate_layers(c.byref(count), properties)
        if result == 0:
            return [p.name.decode() for p in properties[:count.value]]
        if result != 5:  # VK_INCOMPLETE
            break
    raise RuntimeError("Cannot enumerate Vulkan layers")


if __name__ == "__main__" and sys.argv[1:] == ["--probe"]:
    print(json.dumps(_enumerate_layers()))
