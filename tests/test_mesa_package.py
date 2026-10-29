import copy
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "make/mesa-package.py"
SPEC = importlib.util.spec_from_file_location("mesa_package", SCRIPT)
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)
MANIFEST = {"file_format_version": "1.0.0", "vendor_data": {"preserved": True}, "ICD": {
    "api_version": "1.4.344", "library_path": "/build/libvulkan_radeon.so", "library_arch": "64", "metadata": "keep",
}}


def elf_header(arch="x86_64", extra=""):
    _, _, elf_class, machine, _ = PACKAGE.architecture(arch)
    return f"  Class: {elf_class}\n  Data: 2's complement, little endian\n  Type: DYN (Shared object file)\n  Machine: {machine}\n" + extra


class MesaPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.driver = self.root / "driver.so"
        self.driver.write_bytes(b"driver data")
        self.manifest = self.root / "upstream.json"
        self.manifest.write_text(json.dumps(MANIFEST))
        self.destination = self.root / "dist"

    def install(self, arch="x86_64", output=None):
        with mock.patch.object(PACKAGE, "command", return_value=output or elf_header(arch)):
            PACKAGE.install(self.driver, self.manifest, self.destination, arch)

    def test_private_paths_and_manifest_metadata(self):
        self.install()
        driver = self.destination / "lib/mesa/x86_64-linux-gnu/libvulkan_radeon.so"
        manifest = self.destination / "share/mesa/icd.d/radeon_icd.x86_64.json"
        self.assertEqual(driver.read_bytes(), b"driver data")
        result = json.loads(manifest.read_text())
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o644)
        expected = copy.deepcopy(MANIFEST)
        expected["ICD"]["library_path"] = "../../../lib/mesa/x86_64-linux-gnu/libvulkan_radeon.so"
        self.assertEqual(result, expected)
        self.assertEqual((manifest.parent / result["ICD"]["library_path"]).resolve(), driver)
        self.assertFalse((self.destination / "share/vulkan/icd.d").exists())

    def test_both_architectures_coexist(self):
        self.install()
        manifest = copy.deepcopy(MANIFEST)
        manifest["ICD"]["library_arch"] = "32"
        self.manifest.write_text(json.dumps(manifest))
        self.install("i386")
        self.assertTrue((self.destination / "lib/mesa/i386-linux-gnu/libvulkan_radeon.so").is_file())
        self.assertTrue((self.destination / "share/mesa/icd.d/radeon_icd.i686.json").is_file())
        self.assertTrue((self.destination / "share/mesa/icd.d/radeon_icd.x86_64.json").is_file())

    def test_wrong_elf_class_or_machine_rejected(self):
        for output in (elf_header("i386"), elf_header().replace("Advanced Micro Devices X86-64", "AArch64")):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.install(output=output)
        self.assertFalse(self.destination.exists())

    def test_wrong_endian_and_not_shared_rejected(self):
        for output in (elf_header().replace("little endian", "big endian"), elf_header().replace("DYN", "EXEC")):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.install(output=output)

    def test_forbidden_drm_dependencies_rejected(self):
        for library in ("libdrm.so.2", "libdrm_amdgpu.so.1"):
            output = elf_header(extra=f"  0x1 (NEEDED) Shared library: [{library}]\n")
            with self.subTest(library=library), self.assertRaises(ValueError):
                self.install(output=output)

    def test_rpath_and_runpath_rejected(self):
        for tag in ("RPATH", "RUNPATH"):
            output = elf_header(extra=f"  0x1 ({tag}) Library rpath: [/build/libs]\n")
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self.install(output=output)

    def test_normal_shared_dependencies_allowed(self):
        self.install(output=elf_header(extra="  0x1 (NEEDED) Shared library: [libc.so.6]\n"))

    def test_invalid_json_or_manifest_rejected_before_copy(self):
        for data in ("not-json", "[]", "{}", json.dumps({"ICD": []}), json.dumps({"ICD": {"library_path": 1}})):
            self.manifest.write_text(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.install()
        self.assertFalse(self.destination.exists())

    def test_invalid_api_version_and_wrong_manifest_arch_rejected(self):
        for field, value in (("api_version", "invalid"), ("api_version", 1.4), ("library_arch", "32")):
            manifest = copy.deepcopy(MANIFEST)
            manifest["ICD"][field] = value
            self.manifest.write_text(json.dumps(manifest))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.install()

    def test_missing_optional_library_arch_preserved(self):
        manifest = copy.deepcopy(MANIFEST)
        del manifest["ICD"]["library_arch"]
        self.manifest.write_text(json.dumps(manifest))
        self.install()
        result = json.loads((self.destination / "share/mesa/icd.d/radeon_icd.x86_64.json").read_text())
        self.assertNotIn("library_arch", result["ICD"])

    def test_command_uses_readelf_and_c_locale(self):
        result = subprocess.CompletedProcess([], 0, elf_header(), "")
        with mock.patch.object(PACKAGE.subprocess, "run", return_value=result) as run:
            PACKAGE.validate_driver(self.driver, "x86_64")
        self.assertEqual(run.call_args.args[0], ["readelf", "--file-header", "--dynamic", str(self.driver)])
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")

    @unittest.skipUnless(shutil.which("gcc") and shutil.which("readelf"), "GCC and readelf required")
    def test_real_elf_both_architectures_and_runpath(self):
        for arch, flag in (("x86_64", "-m64"), ("i386", "-m32")):
            manifest = copy.deepcopy(MANIFEST)
            manifest["ICD"]["library_arch"] = PACKAGE.architecture(arch)[4]
            self.manifest.write_text(json.dumps(manifest))
            arguments = ["gcc", flag, "-shared", "-fPIC", "-nostdlib", "-xc", "-", "-o", str(self.driver)]
            subprocess.run(arguments, input=b"int test_driver(void) { return 17; }", check=True, capture_output=True)
            PACKAGE.install(self.driver, self.manifest, self.destination, arch)
            other = "i386" if arch == "x86_64" else "x86_64"
            with self.assertRaises(ValueError):
                PACKAGE.validate_driver(self.driver, other)
            subprocess.run(arguments + ["-Wl,-rpath,/private/build"], input=b"int test_driver(void) { return 17; }", check=True, capture_output=True)
            with self.assertRaises(ValueError):
                PACKAGE.validate_driver(self.driver, arch)

    def patch(self, name, commit):
        path = self.root / "patches" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"From {commit} Mon Sep 17 00:00:00 2001\nSubject: [PATCH] Existing commit\n")
        return path

    def test_metadata_commit_patch_order_and_unique_architectures(self):
        self.patch("0002-second.patch", "2" * 40)
        self.patch("0001-first.patch", "1" * 40)
        with mock.patch.object(PACKAGE, "command", return_value="a" * 40 + "\n"):
            PACKAGE.metadata(self.root, self.root / "patches", self.destination, ["x86_64", "i386", "x86_64"])
        result = json.loads((self.destination / "share/mesa/build.json").read_text())
        self.assertEqual(result, {"mesa": "a" * 40, "patches": ["1" * 40, "2" * 40], "architectures": ["x86_64", "i386"]})

    def test_metadata_direct_checkout_has_no_external_patches(self):
        self.patch("0001-unused.patch", "1" * 40)
        with mock.patch.object(PACKAGE, "command", return_value="a" * 40):
            PACKAGE.metadata(self.root, None, self.destination, ["x86_64", "i386"])
        result = json.loads((self.destination / "share/mesa/build.json").read_text())
        self.assertEqual(result, {"mesa": "a" * 40, "patches": [], "architectures": ["x86_64", "i386"]})

    def test_metadata_invalid_patch_or_duplicate_rejected(self):
        for invalid in ("short", "z" * 40):
            self.patch("0001.patch", invalid)
            with mock.patch.object(PACKAGE, "command", return_value="a" * 40), self.assertRaises(ValueError):
                PACKAGE.metadata(self.root, self.root / "patches", self.destination, ["x86_64"])
        self.patch("0001.patch", "1" * 40)
        self.patch("0002.patch", "1" * 40)
        with mock.patch.object(PACKAGE, "command", return_value="a" * 40), self.assertRaises(ValueError):
            PACKAGE.metadata(self.root, self.root / "patches", self.destination, ["x86_64"])

    def raw_patch(self, name="0010-branding.patch"):
        path = self.root / "patches" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"diff --git a/driver.c b/driver.c\n"
                         b"--- a/driver.c\n+++ b/driver.c\n"
                         b"@@ -1 +1 @@\n-radv\n+radv-salkim\n")
        return path

    def test_metadata_raw_patch_hashes_exact_contents(self):
        self.patch("0001-existing.patch", "1" * 40)
        raw = self.raw_patch()
        digests = []
        for suffix in (b"", b"\n"):
            raw.write_bytes(raw.read_bytes() + suffix)
            with mock.patch.object(PACKAGE, "command", return_value="a" * 40):
                PACKAGE.metadata(self.root, self.root / "patches", self.destination, ["x86_64"])
            result = json.loads((self.destination / "share/mesa/build.json").read_text())
            digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            self.assertEqual(result["patches"], ["1" * 40, digest])
            digests.append(digest)
        self.assertNotEqual(*digests)

    def test_metadata_duplicate_raw_patch_rejected(self):
        self.raw_patch("0001.patch")
        self.raw_patch("0002.patch")
        with mock.patch.object(PACKAGE, "command", return_value="a" * 40), self.assertRaises(ValueError):
            PACKAGE.metadata(self.root, self.root / "patches", self.destination, ["x86_64"])
        self.assertFalse(self.destination.exists())

    def test_metadata_malformed_raw_patch_rejected(self):
        raw = self.raw_patch()
        valid = raw.read_bytes()
        invalid = (b"not a patch\n", b"diff --git a/driver.c b/driver.c\n",
                   valid.replace(b"+++ b/driver.c\n", b""),
                   valid.replace(b"@@ -1 +1 @@", b"@@ -1,3 +1,3 @@"),
                   valid.replace(b"+radv-salkim\n", b""))
        for content in invalid:
            with self.subTest(content=content):
                raw.write_bytes(content)
                with mock.patch.object(PACKAGE, "command", return_value="a" * 40), self.assertRaises(ValueError):
                    PACKAGE.metadata(self.root, self.root / "patches", self.destination, ["x86_64"])
                self.assertFalse(self.destination.exists())

    def test_metadata_invalid_head_or_architecture_rejected(self):
        self.patch("0001.patch", "1" * 40)
        for commit in ("invalid", "z" * 40):
            with mock.patch.object(PACKAGE, "command", return_value=commit), self.assertRaises(ValueError):
                PACKAGE.metadata(self.root, self.root / "patches", self.destination, ["x86_64"])
        with self.assertRaises(ValueError):
            PACKAGE.metadata(self.root, self.root / "patches", self.destination, ["arm64"])

    @unittest.skipUnless(shutil.which("git"), "Git required")
    def test_metadata_raw_patch_from_nested_build_directory(self):
        source = self.root / "source"
        for directory in (self.root, source):
            subprocess.run(["git", "init", "--quiet", str(directory)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c",
                        "user.email=test@example.invalid", "commit", "--allow-empty",
                        "--quiet", "-m", "Fixture"], check=True, capture_output=True)
        head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        raw = self.raw_patch("0000-branding.patch")
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        build = self.root / "build"
        build.mkdir()
        for source_arg in (str(source), "../source"):
            with self.subTest(source=source_arg):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "metadata", source_arg,
                     "../dist", "x86_64", "i386", "--patches", "../patches"],
                    cwd=build, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                metadata = json.loads((self.destination / "share/mesa/build.json").read_text())
                self.assertEqual(metadata, {"mesa": head, "patches": [digest],
                                            "architectures": ["x86_64", "i386"]})
                self.assertFalse((source / "driver.c").exists())
                status = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True)
                self.assertEqual(status, "")

    @unittest.skipUnless(shutil.which("git"), "Git required")
    def test_metadata_reads_real_git_head(self):
        source = self.root / "source"
        subprocess.run(["git", "init", "--quiet", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "--quiet", "-m", "Fixture"], check=True, capture_output=True)
        head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        self.patch("0001.patch", "1" * 40)
        PACKAGE.metadata(source, self.root / "patches", self.destination, ["x86_64"])
        result = json.loads((self.destination / "share/mesa/build.json").read_text())
        self.assertEqual(result["mesa"], head)

    def test_atomic_metadata_preserves_previous_file_on_failure(self):
        target = self.root / "build.json"
        target.write_text("previous\n")
        with mock.patch.object(PACKAGE.os, "replace", side_effect=OSError("failed")), self.assertRaises(OSError):
            PACKAGE.atomic_json(target, {"new": True})
        self.assertEqual(target.read_text(), "previous\n")
        self.assertEqual(list(self.root.glob("tmp*")), [])

    def data_sources(self):
        mesa, libdrm = self.root / "mesa", self.root / "libdrm"
        sources = {
            mesa / "src/util/00-mesa-defaults.conf": b"Mesa defaults\n",
            mesa / "src/amd/vulkan/00-radv-defaults.conf": b"RADV defaults\n",
            mesa / "src/amd/vulkan/01-radv-performance.conf": b"RADV performance\n",
            libdrm / "data/amdgpu.ids": b"AMD device identifiers\n",
        }
        for path, contents in sources.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        return mesa, libdrm, sources

    def test_data_copies_exact_source_bytes_and_static_system_link(self):
        mesa, libdrm, sources = self.data_sources()
        PACKAGE.data(mesa, libdrm, self.destination)
        config = self.destination / "share/mesa/drirc.d"
        for source, contents in sources.items():
            target = config / source.name if source.suffix == ".conf" else self.destination / "share/mesa/libdrm/amdgpu.ids"
            self.assertEqual(target.read_bytes(), contents)
        link = config / "99-system.conf"
        self.assertTrue(link.is_symlink())
        self.assertEqual(str(link.readlink()), "/etc/drirc")

    def test_data_second_run_is_idempotent(self):
        mesa, libdrm, _ = self.data_sources()
        PACKAGE.data(mesa, libdrm, self.destination)
        target = self.destination / "share/mesa/drirc.d/00-radv-defaults.conf"
        inode, timestamp = target.stat().st_ino, target.stat().st_mtime_ns
        PACKAGE.data(mesa, libdrm, self.destination)
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(target.stat().st_mtime_ns, timestamp)

    def test_data_missing_source_fails_before_any_mutation(self):
        mesa, libdrm, sources = self.data_sources()
        list(sources)[-1].unlink()
        with self.assertRaises(FileNotFoundError):
            PACKAGE.data(mesa, libdrm, self.destination)
        self.assertFalse(self.destination.exists())

    def test_data_updates_generated_files_when_sources_change(self):
        mesa, libdrm, sources = self.data_sources()
        PACKAGE.data(mesa, libdrm, self.destination)
        for source in sources:
            source.write_bytes(b"Updated defaults\n")
        PACKAGE.data(mesa, libdrm, self.destination)
        for target in (self.destination / "share/mesa/drirc.d").glob("0*.conf"):
            self.assertEqual(target.read_bytes(), b"Updated defaults\n")
        self.assertEqual((self.destination / "share/mesa/libdrm/amdgpu.ids").read_bytes(),
                         b"Updated defaults\n")

    def test_data_directory_collision_rejected_without_partial_install(self):
        mesa, libdrm, _ = self.data_sources()
        target = self.destination / "share/mesa/drirc.d/01-radv-performance.conf"
        target.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            PACKAGE.data(mesa, libdrm, self.destination)
        self.assertTrue(target.is_dir())
        self.assertFalse((target.parent / "00-mesa-defaults.conf").exists())
        self.assertFalse((target.parent / "99-system.conf").is_symlink())

    def test_data_system_link_collision_rejected_before_copy(self):
        mesa, libdrm, _ = self.data_sources()
        link = self.destination / "share/mesa/drirc.d/99-system.conf"
        link.parent.mkdir(parents=True)
        link.symlink_to("/different/system/config")
        with self.assertRaises(FileExistsError):
            PACKAGE.data(mesa, libdrm, self.destination)
        self.assertEqual(str(link.readlink()), "/different/system/config")
        self.assertEqual(list(link.parent.iterdir()), [link])

    def test_data_regular_file_at_system_link_is_not_overwritten(self):
        mesa, libdrm, _ = self.data_sources()
        target = self.destination / "share/mesa/drirc.d/99-system.conf"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"User configuration\n")
        with self.assertRaises(FileExistsError):
            PACKAGE.data(mesa, libdrm, self.destination)
        self.assertEqual(target.read_bytes(), b"User configuration\n")

    def test_data_source_target_symlink_is_not_followed(self):
        mesa, libdrm, _ = self.data_sources()
        outside = self.root / "outside"
        outside.write_bytes(b"User configuration\n")
        target = self.destination / "share/mesa/drirc.d/00-mesa-defaults.conf"
        target.parent.mkdir(parents=True)
        target.symlink_to(outside)
        with self.assertRaises(FileExistsError):
            PACKAGE.data(mesa, libdrm, self.destination)
        self.assertEqual(outside.read_bytes(), b"User configuration\n")

    def test_data_parent_directory_symlink_is_not_followed(self):
        mesa, libdrm, _ = self.data_sources()
        outside = self.root / "outside"
        outside.mkdir()
        config = self.destination / "share/mesa/drirc.d"
        config.parent.mkdir(parents=True)
        config.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(FileExistsError):
            PACKAGE.data(mesa, libdrm, self.destination)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
