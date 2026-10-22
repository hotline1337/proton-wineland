"""Test private RADV discovery without loading Vulkan or changing host drivers."""

import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mesa


class MesaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = self.root / "files"
        self.host = self.root / "host"
        self.runtime = self.root / "pressure-vessel/vulkan/icd.d"
        self.env = {"PROTON_RADV": "1", "HOME": str(self.root / "home"),
                    "XDG_CONFIG_DIRS": str(self.root / "config"),
                    "XDG_DATA_DIRS": str(self.host)}
        self.log = mock.Mock()
        self.bundled = []
        self.metadata = {"mesa": "a" * 40, "patches": ["b" * 40, "c" * 40],
                         "architectures": ["x86_64", "i386"]}
        for arch, triplet, elf_class, machine in mesa.ARCHITECTURES.values():
            driver = self.files / "lib/mesa" / triplet / "libvulkan_radeon.so"
            driver.parent.mkdir(parents=True)
            header = bytearray(20)
            header[:6] = b"\x7fELF" + bytes((elf_class, 1))
            header[18:20] = machine.to_bytes(2, "little")
            driver.write_bytes(header)
            manifest = self.files / "share/mesa/icd.d" / ("radeon_icd." + arch + ".json")
            self.manifest(manifest, "../../../lib/mesa/" + triplet + "/libvulkan_radeon.so")
            self.bundled.append(manifest)
        self.write_metadata()
        self.data = self.files / "share/mesa"
        drirc = self.data / "drirc.d"
        drirc.mkdir()
        for name in mesa.DRIRC_FILES:
            (drirc / name).write_text("<driconf/>\n", encoding="utf-8")
        (drirc / "99-system.conf").symlink_to("/etc/drirc")
        libdrm = self.data / "libdrm"
        libdrm.mkdir()
        (libdrm / "amdgpu.ids").write_text("# Test AMD GPU name table\n", encoding="utf-8")
        machine = mock.patch.object(mesa.platform, "machine", return_value="x86_64")
        machine.start()
        self.addCleanup(machine.stop)
        runtime = mock.patch.object(mesa, "RUNTIME_ICD_DIR", self.runtime)
        runtime.start()
        self.addCleanup(runtime.stop)
        system = mock.patch.object(mesa, "SYSTEM_ROOTS", ())
        system.start()
        self.addCleanup(system.stop)
        defaults = mock.patch.object(mesa, "_default_manifests", wraps=mesa._default_manifests)
        self.defaults = defaults.start()
        self.addCleanup(defaults.stop)

    def manifest(self, path, library):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"file_format_version": "1.0.0", "ICD": {
            "library_path": library, "api_version": "1.4.0"}}), encoding="utf-8")
        return path

    def write_metadata(self):
        path = self.files / "share/mesa/build.json"
        path.write_text(json.dumps(self.metadata), encoding="utf-8")

    def host_manifest(self, name, library):
        return self.manifest(self.host / "vulkan/icd.d" / name, library)

    def configure(self):
        return mesa.configure(self.env, self.files, self.log)

    def selected(self):
        return self.env["VK_DRIVER_FILES"].split(os.pathsep)

    def test_disabled_is_noop_even_without_bundle(self):
        for value in (None, "", "0", "true", "yes"):
            with self.subTest(value=value):
                if value is None:
                    self.env.pop("PROTON_RADV", None)
                else:
                    self.env["PROTON_RADV"] = value
                before = dict(self.env)
                with mock.patch.object(mesa, "_bundle", side_effect=AssertionError):
                    self.assertFalse(self.configure())
                self.assertEqual(self.env, before)
        self.log.assert_not_called()

    def test_preserves_other_gpus_and_replaces_both_host_radv_architectures(self):
        self.host_manifest("radeon_icd.x86_64.json", "/usr/lib/libvulkan_radeon.so")
        self.host_manifest("radeon_icd.i686.json", "/usr/lib32/libvulkan_radeon.so")
        intel = self.host_manifest("intel_icd.x86_64.json", "libvulkan_intel.so")
        nvidia = self.host_manifest("nvidia_icd.json", "libGLX_nvidia.so.0")
        amdvlk = self.host_manifest("amd_icd64.json", "/opt/amdvlk/amdvlk64.so")
        self.env["LD_LIBRARY_PATH"] = "/existing/lib"
        self.env["VK_LOADER_DRIVERS_SELECT"] = "*radeon*,*nvidia*"
        self.env["VK_LOADER_DRIVERS_DISABLE"] = "*lvp*"
        self.assertTrue(self.configure())
        self.assertEqual(self.selected(), list(map(str, self.bundled + [amdvlk, intel, nvidia])))
        self.assertEqual(self.env["VK_ICD_FILENAMES"], self.env["VK_DRIVER_FILES"])
        self.assertEqual(self.env["LD_LIBRARY_PATH"], "/existing/lib")
        self.assertEqual(self.env["VK_LOADER_DRIVERS_SELECT"], "*radeon*,*nvidia*")
        self.assertEqual(self.env["VK_LOADER_DRIVERS_DISABLE"], "*lvp*")

    def test_preserves_renamed_non_radv_manifest(self):
        path = self.host_manifest("radeon_icd.custom.json", "libcustom_driver.so")
        self.assertTrue(self.configure())
        self.assertIn(str(path), self.selected())

    def test_replaces_radv_by_library_not_manifest_filename(self):
        self.host_manifest("0.json", "/overrides/lib/libvulkan_radeon.so")
        self.host_manifest("1.json", "libvulkan_radeon.so.1")
        self.assertTrue(self.configure())
        self.assertEqual(self.selected(), list(map(str, self.bundled)))

    def test_explicit_overrides_are_unchanged_including_empty(self):
        for name in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES", "VK_ADD_DRIVER_FILES"):
            for value in ("", "/custom/driver.json", "/custom/icd.d"):
                with self.subTest(name=name, value=value):
                    env = dict(self.env, **{name: value})
                    before = dict(env)
                    self.assertFalse(mesa.configure(env, self.files, self.log))
                    self.assertEqual(env, before)

    def test_pressure_vessel_pair_is_runtime_inventory(self):
        radv = self.manifest(self.runtime / "radeon_icd.x86_64.json", "/overrides/lib/libvulkan_radeon.so")
        nvidia = self.manifest(self.runtime / "nvidia_icd.json", "/overrides/lib/libGLX_nvidia.so.0")
        self.env.update(container="pressure-vessel", VK_DRIVER_FILES=str(radv) + ":" + str(nvidia),
                        VK_ICD_FILENAMES=str(radv) + ":" + str(nvidia))
        self.assertTrue(self.configure())
        self.assertEqual(self.selected(), list(map(str, self.bundled + [nvidia])))
        self.defaults.assert_not_called()

    def test_pressure_vessel_legacy_only_inventory(self):
        radv = self.manifest(self.runtime / "radeon_icd.i686.json", "libvulkan_radeon.so")
        self.env.update(container="pressure-vessel", VK_ICD_FILENAMES=str(radv))
        self.assertTrue(self.configure())
        self.assertEqual(self.selected(), list(map(str, self.bundled)))

    def test_pressure_vessel_different_override_pair_is_not_replaced(self):
        radv = self.manifest(self.runtime / "radeon_icd.x86_64.json", "libvulkan_radeon.so")
        self.env.update(container="pressure-vessel", VK_DRIVER_FILES=str(radv),
                        VK_ICD_FILENAMES="/user/driver.json")
        before = dict(self.env)
        self.assertFalse(self.configure())
        self.assertEqual(self.env, before)

    def test_pressure_vessel_custom_or_missing_path_is_not_replaced(self):
        for path in (self.runtime / "missing.json", self.runtime / "../outside.json",
                     self.host / "vulkan/icd.d/custom.json"):
            with self.subTest(path=path):
                self.env.update(container="pressure-vessel", VK_DRIVER_FILES=str(path))
                before = dict(self.env)
                self.assertFalse(self.configure())
                self.assertEqual(self.env, before)

    def test_incomplete_bundle_is_atomic(self):
        self.bundled[1].unlink()
        before = dict(self.env)
        self.assertFalse(self.configure())
        self.assertEqual(self.env, before)

    def test_wow64_only_needs_declared_64_bit_driver(self):
        self.metadata["architectures"] = ["x86_64"]
        self.write_metadata()
        self.bundled[1].unlink()
        self.assertTrue(self.configure())
        self.assertEqual(self.selected(), [str(self.bundled[0])])

    def test_missing_build_metadata_is_atomic(self):
        (self.files / "share/mesa/build.json").unlink()
        before = dict(self.env)
        self.assertFalse(self.configure())
        self.assertEqual(self.env, before)

    def test_invalid_build_metadata_is_atomic(self):
        invalid = [None, [], {}, {"architectures": []},
                   dict(self.metadata, architectures=["i386"]),
                   dict(self.metadata, architectures=["x86_64", "aarch64"]),
                   dict(self.metadata, architectures=["x86_64", "x86_64"]),
                   dict(self.metadata, architectures=["x86_64", {}]),
                   dict(self.metadata, mesa="HEAD"),
                   dict(self.metadata, mesa="z" * 40),
                   dict(self.metadata, mesa="a" * 64),
                   dict(self.metadata, patches=["invalid"]),
                   dict(self.metadata, patches=["g" * 64]),
                   dict(self.metadata, patches=["f" * 63]),
                   dict(self.metadata, patches=["f" * 65]),
                   dict(self.metadata, patches=["a" * 64, "a" * 64]),
                   dict(self.metadata, patches=["b" * 40, "b" * 40]),
                   dict(self.metadata, patches="not a list")]
        for metadata in invalid:
            with self.subTest(metadata=metadata):
                self.metadata = metadata
                self.write_metadata()
                before = dict(self.env)
                self.assertFalse(self.configure())
                self.assertEqual(self.env, before)

    def test_raw_patch_sha256_identity_is_accepted(self):
        self.metadata["patches"].append("d" * 64)
        self.write_metadata()
        self.assertTrue(self.configure())
        self.assertEqual(self.env["PROTON_RADV_VERSION"], "a" * 40 + "+3")

    def test_success_reports_source_and_patch_count(self):
        self.assertTrue(self.configure())
        self.assertEqual(self.env["PROTON_RADV_VERSION"], "a" * 40 + "+2")
        self.log.assert_called_once_with("Using bundled radv-salkim " + "a" * 12 +
                                         " with 2 local patches (x86_64, i386)")

    def test_data_paths_use_private_directories(self):
        self.assertTrue(self.configure())
        self.assertEqual(self.env["DRIRC_CONFIGDIR"], str(self.data / "drirc.d"))
        self.assertEqual(self.env["AMDGPU_ASIC_ID_TABLE_PATHS"], str(self.data / "libdrm"))

    def test_explicit_data_paths_are_preserved(self):
        for value in ("", "/user/config:/user/fallback"):
            with self.subTest(value=value):
                env = dict(self.env, DRIRC_CONFIGDIR=value, AMDGPU_ASIC_ID_TABLE_PATHS=value)
                self.assertTrue(mesa.configure(env, self.files, self.log))
                self.assertEqual(env["DRIRC_CONFIGDIR"], value)
                self.assertEqual(env["AMDGPU_ASIC_ID_TABLE_PATHS"], value)

    def test_missing_data_is_atomic(self):
        paths = [self.data / "drirc.d" / name for name in mesa.DRIRC_FILES]
        paths.append(self.data / "libdrm/amdgpu.ids")
        for path in paths:
            with self.subTest(path=path):
                contents = path.read_bytes()
                path.unlink()
                before = dict(self.env)
                self.assertFalse(self.configure())
                self.assertEqual(self.env, before)
                path.write_bytes(contents)

    def test_system_config_link_is_required_but_target_can_be_absent(self):
        system = self.data / "drirc.d/99-system.conf"
        system.unlink()
        before = dict(self.env)
        self.assertFalse(self.configure())
        self.assertEqual(self.env, before)
        system.symlink_to("/incorrect/drirc")
        self.assertFalse(self.configure())
        self.assertEqual(self.env, before)
        system.unlink()
        system.symlink_to("/etc/drirc")
        self.assertTrue(self.configure())

    def test_repeat_setup_restores_data_paths_if_removed(self):
        self.assertTrue(self.configure())
        self.env.pop("DRIRC_CONFIGDIR")
        self.env.pop("AMDGPU_ASIC_ID_TABLE_PATHS")
        self.assertTrue(self.configure())
        self.assertEqual(self.env["DRIRC_CONFIGDIR"], str(self.data / "drirc.d"))
        self.assertEqual(self.env["AMDGPU_ASIC_ID_TABLE_PATHS"], str(self.data / "libdrm"))

    def test_wrong_driver_architecture_is_atomic(self):
        driver = self.files / "lib/mesa/i386-linux-gnu/libvulkan_radeon.so"
        driver.write_bytes(b"not an ELF driver")
        before = dict(self.env)
        self.assertFalse(self.configure())
        self.assertEqual(self.env, before)

    def test_bundle_driver_path_must_match_private_directory(self):
        self.manifest(self.bundled[0], "/usr/lib/libvulkan_radeon.so")
        before = dict(self.env)
        self.assertFalse(self.configure())
        self.assertEqual(self.env, before)

    def test_unknown_or_malformed_host_manifests_are_preserved(self):
        invalid = self.host_manifest("invalid.json", "libvulkan_radeon.so")
        invalid.write_text("not JSON", encoding="utf-8")
        unknown = self.host_manifest("unknown.json", None)
        self.assertTrue(self.configure())
        self.assertEqual(self.selected(), list(map(str, self.bundled + [invalid, unknown])))

    def test_duplicate_manifest_paths_are_deduplicated(self):
        nvidia = self.host_manifest("nvidia_icd.json", "libGLX_nvidia.so.0")
        self.env["XDG_DATA_DIRS"] = str(self.host) + ":" + str(self.host)
        self.assertTrue(self.configure())
        self.assertEqual(self.selected(), list(map(str, self.bundled + [nvidia])))

    def test_home_and_xdg_driver_paths_are_discovered(self):
        paths = [self.root / "home/.config/vulkan/icd.d/a.json",
                 self.root / "home/.local/share/vulkan/icd.d/b.json",
                 self.root / "config/vulkan/icd.d/c.json"]
        for path in paths:
            self.manifest(path, "libcustom.so")
        self.assertTrue(self.configure())
        self.assertTrue(set(map(str, paths)) <= set(self.selected()))

    def test_default_search_preserves_loader_directory_order(self):
        system_root = self.root / "system"
        roots = [self.root / "home/.config", self.root / "config", system_root,
                 self.root / "home/.local/share", self.host]
        paths = [self.manifest(root / "vulkan/icd.d/driver.json", "libcustom.so") for root in roots]
        with mock.patch.object(mesa, "SYSTEM_ROOTS", (system_root,)):
            self.assertEqual(list(mesa._default_manifests(self.env)), paths)

    def test_relative_xdg_paths_do_not_add_working_directory(self):
        self.env.update(XDG_DATA_HOME="relative/path", XDG_CONFIG_HOME="relative/path",
                        XDG_DATA_DIRS="relative/path", XDG_CONFIG_DIRS="relative/path")
        self.assertEqual(list(mesa._default_manifests(self.env)), [])

    def test_repeated_setup_keeps_selection(self):
        self.host_manifest("nvidia_icd.json", "libGLX_nvidia.so.0")
        self.assertTrue(self.configure())
        before = dict(self.env)
        self.assertTrue(self.configure())
        self.assertEqual(self.env, before)

    def test_no_arm64_fallback(self):
        before = dict(self.env)
        with mock.patch.object(mesa.platform, "machine", return_value="aarch64"):
            self.assertFalse(self.configure())
        self.assertEqual(self.env, before)


class LauncherStartupTests(unittest.TestCase):
    def test_driver_selection_precedes_vulkan_imports(self):
        tree = ast.parse((ROOT / "proton").read_text(encoding="utf-8"))
        selector = next(node for node in tree.body if isinstance(node, ast.If)
                        and any(isinstance(value, ast.Call)
                                and isinstance(value.func, ast.Attribute)
                                and isinstance(value.func.value, ast.Name)
                                and value.func.value.id == "mesa"
                                and value.func.attr == "configure" for value in ast.walk(node)))
        condition = compile(ast.Expression(selector.test), str(ROOT / "proton"), "eval")
        for value in (None, "", "0", "1", "true"):
            namespace = {"os": mock.Mock(environ={"PROTON_RADV": value})}
            self.assertEqual(eval(condition, namespace), value == "1")
        imports = [node for node in tree.body if isinstance(node, ast.Import)
                   and any(alias.name in ("protonfixes", "utilities", "vulkan_layers")
                           for alias in node.names)]
        self.assertEqual(len(imports), 3)
        self.assertTrue(all(selector.lineno < node.lineno for node in imports))
        configure = next(node for node in ast.walk(selector) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Attribute) and node.func.attr == "configure")
        self.assertIsInstance(configure.args[0], ast.Attribute)
        self.assertEqual(configure.args[0].value.id, "os")
        self.assertEqual(configure.args[0].attr, "environ")


if __name__ == "__main__":
    unittest.main()
