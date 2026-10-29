"""Inspect Mesa build integration without downloading or compiling anything."""

import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest
import io


ROOT = Path(os.environ.get("PROTON_SOURCE", Path(__file__).resolve().parents[1]))


class MesaBuildRulesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.makefile = self.directory / "Makefile"

    def inspect(self, arches=("i386", "x86_64")):
        makefile = f"""
.DEFAULT_GOAL := snapshot
SHELL := /bin/bash
SRCDIR := {ROOT}
SRC := $(SRCDIR)
OBJ := {self.directory}
DST_BASE := $(OBJ)/dist
DST_DIR := $(DST_BASE)/files
DST_LIBDIR := $(DST_DIR)/lib
HOST_ARCH := x86_64
TARGET_ARCH := x86_64
unix_ARCHS := {" ".join(arches)}
ARCHS := $(addsuffix -unix,$(unix_ARCHS))
i386_CFLAGS := -O2 -fPIC -mstackrealign
x86_64_CFLAGS := -O2 -fPIC -march=x86-64-v3
OBJCOPY := objcopy
include $(SRC)/make/utility.mk
include $(SRC)/make/rules-common.mk
include $(SRC)/make/rules-meson.mk

define rules-source
$(call toupper,$(1))_SRC := $(OBJ)/src-$(1)
$(call toupper,$(1))_ORIGIN := $(realpath $(2))
$(OBJ)/.$(1)-source:
$(OBJ)/.$(1)-post-source: $(OBJ)/.$(1)-source
endef

include $(SRC)/make/build-mesa.mk

$(info SNAP_ARCHS=$(MESA_ARCHS))
$(info SNAP_OPTIONS=$(MESA_MESON_ARGS))
$(info SNAP_ENV64=$(MESA_x86_64_ENV))
$(info SNAP_ENV32=$(MESA_i386_ENV))
$(info SNAP_XCB64=$(MESA_XCB_x86_64_DST))
$(info SNAP_XCB32=$(MESA_XCB_i386_DST))
.PHONY: snapshot
snapshot:
\t@:
"""
        self.makefile.write_text(makefile)
        result = subprocess.run(
            ["make", "--no-print-directory", "-p", "-q", "-f", str(self.makefile), "snapshot"],
            cwd=self.directory, capture_output=True, text=True, timeout=30,
        )
        self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
        snapshots = dict(re.findall(r"^SNAP_(\w+)=(.*)$", result.stdout, re.M))
        return snapshots, result.stdout, result.stderr

    def rule(self, database, target):
        database = database.split("# Files\n", 1)[-1]
        match = re.search(r"^" + re.escape(target) + r":(.*?)(?=\n\n)", database, re.M | re.S)
        self.assertIsNotNone(match, target)
        return match.group(0)

    def test_native_architectures_and_wow64(self):
        snapshots, database, _ = self.inspect()
        self.assertEqual(snapshots["ARCHS"], "i386 x86_64")
        self.assertTrue(snapshots["XCB32"].endswith("dst-mesa-xcb-i386"))
        self.assertTrue(snapshots["XCB64"].endswith("dst-mesa-xcb-x86_64"))
        snapshots, database, _ = self.inspect(("x86_64",))
        self.assertEqual(snapshots["ARCHS"], "x86_64")
        self.assertEqual(snapshots["XCB32"], "")
        self.assertNotIn("mesa-i386-build:", database)

    def test_radv_aco_only_and_offline_dependencies(self):
        snapshots, _, _ = self.inspect()
        options = snapshots["OPTIONS"].split()
        for option in ("-Dvulkan-drivers=amd", "-Dgallium-drivers=", "-Dllvm=disabled",
                       "-Damd-options=", "-Dplatforms=x11,wayland", "-Dopengl=false",
                       "-Dglx=disabled", "-Degl=disabled", "-Dgbm=disabled", "-Db_lto=false",
                       "-Dspirv-tools=disabled",
                       "--wrap-mode=nodownload", "-Dlibdrm:default_library=static",
                       "-Dlibdrm:b_staticpic=true", "-Dlibdrm:amdgpu=enabled",
                       "-Dlibdrm:intel=disabled", "-Dlibdrm:radeon=disabled",
                       "-Dlibdrm:nouveau=disabled", "-Dlibdrm:vmwgfx=disabled"):
            self.assertIn(option, options)

    def test_gcc_and_architecture_pkgconfig(self):
        snapshots, _, _ = self.inspect()
        for bits, triplet in (("64", "x86_64-linux-gnu"), ("32", "i686-linux-gnu")):
            environment = snapshots[f"ENV{bits}"]
            self.assertIn(f'CC="{triplet}-gcc"', environment)
            self.assertIn(f'CXX="{triplet}-g++"', environment)
            self.assertNotIn("clang", environment)
        self.assertIn("-march=x86-64-v3", snapshots["ENV64"])
        self.assertIn("dst-mesa-xcb-i386/lib/i386-linux-gnu/pkgconfig", snapshots["ENV32"])
        self.assertIn("dst-mesa-xcb-x86_64/lib/x86_64-linux-gnu/pkgconfig", snapshots["ENV64"])
        for bits in ("32", "64"):
            environment = snapshots[f"ENV{bits}"]
            loader_path = re.search(r'LD_LIBRARY_PATH="([^"]*)"', environment)
            self.assertIsNotNone(loader_path)
            self.assertNotIn("mesa-xcb", loader_path[1])

    def test_configure_depends_on_source_and_xcb_stage(self):
        _, database, _ = self.inspect()
        for arch in ("i386", "x86_64"):
            rule = self.rule(database, str(self.directory / f".mesa-{arch}-configure"))
            self.assertIn(f".mesa-xcb-{arch}-build", rule)
            self.assertIn(".mesa-post-source", rule)
        patched = self.rule(database, str(self.directory / ".mesa-post-source"))
        self.assertIn(".mesa-upstream-post-source", patched)
        self.assertIn(str(ROOT / "make/build-mesa.mk"), patched)
        self.assertNotIn("patch --batch", patched)
        for patch in (ROOT / "patches/mesa").glob("*.patch"):
            self.assertNotIn(str(patch), patched)

    def test_distribution_is_private_and_xcb_is_build_only(self):
        _, database, _ = self.inspect()
        for arch in ("i386", "x86_64"):
            rule = self.rule(database, str(self.directory / f".mesa-{arch}-dist"))
            self.assertIn("mesa-package.py", rule)
            self.assertNotIn("find -type", rule)
            self.assertNotIn("libxcb", rule)
        self.assertNotRegex(database, r"(?m)^mesa-xcb-(?:i386|x86_64)-dist:")
        all_dist = self.rule(database, "all-dist")
        self.assertIn("mesa-dist", all_dist)
        self.assertNotIn("mesa-xcb", all_dist)

    def test_arm_build_excludes_mesa(self):
        source = (ROOT / "Makefile.in").read_text()
        self.assertRegex(source, r"ifeq \(\$\(TARGET_ARCH\),x86_64\)\s*"
                         r"include \$\(SRC\)/make/build-mesa\.mk\s*endif")


class MesaPatchedSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / "fixture"
        self.build = self.directory / "build"
        self.source.mkdir()
        self.build.mkdir()
        (self.source / "make").symlink_to(ROOT / "make", target_is_directory=True)
        upstream = self.source / "mesa"
        upstream.mkdir()
        (upstream / "sample.c").write_text("old\n")
        (upstream / "meson.build").write_text("project('fixture', 'c')\n")
        patchdir = self.source / "patches/mesa"
        patchdir.mkdir(parents=True)
        self.patch = patchdir / "0001-fix.patch"
        self.write_patch("new")
        archives = self.build / "downloads/mesa"
        archives.mkdir(parents=True)
        archive = archives / "libdrm-2.4.133.tar.xz"
        with tarfile.open(archive, "w:xz") as target:
            contents = b"fixture libdrm\n"
            member = tarfile.TarInfo("libdrm-2.4.133/README")
            member.size = len(contents)
            target.addfile(member, io.BytesIO(contents))
        self.makefile = self.directory / "Makefile"
        self.makefile.write_text(f"""
SHELL := /bin/bash
SRCDIR := {self.source}
SRC := $(abspath $(SRCDIR))
OBJ := {self.build}
unix_ARCHS :=
include {ROOT}/make/utility.mk
include {ROOT}/make/rules-source.mk
include {ROOT}/make/build-mesa.mk
""")
        self.stamp = self.build / ".mesa-post-source"
        self.patched = self.build / "src-mesa/sample.c"

    def write_patch(self, value):
        self.patch.write_text("--- a/sample.c\n+++ b/sample.c\n@@ -1 +1 @@\n-old\n+" + value + "\n")

    def prepare(self, *options):
        result = subprocess.run(
            ["make", "--no-print-directory", "-f", str(self.makefile), str(self.stamp), *options],
            cwd=self.build, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_relative_source_directory_copies_checkout(self):
        relative = os.path.relpath(self.source, self.build)
        self.prepare("SRCDIR=" + relative)
        self.assertEqual(self.patched.read_text(), "old\n")

    def test_unchanged_checkout_does_not_rebuild(self):
        self.prepare()
        self.assertEqual(self.patched.read_text(), "old\n")
        previous = self.stamp.stat().st_mtime_ns
        result = self.prepare()
        self.assertEqual(self.stamp.stat().st_mtime_ns, previous)
        self.assertNotIn("patch --batch", result.stdout)

    def test_modified_checkout_replaces_staged_source(self):
        self.prepare()
        (self.source / "mesa/sample.c").write_text("branch update\n")
        self.prepare()
        self.assertEqual(self.patched.read_text(), "branch update\n")

    def test_unused_patch_changes_do_not_rebuild(self):
        self.prepare()
        previous = self.stamp.stat().st_mtime_ns
        self.write_patch("unused kernel feature")
        self.prepare()
        self.assertEqual(self.stamp.stat().st_mtime_ns, previous)
        self.assertEqual(self.patched.read_text(), "old\n")

    def test_source_switch_removes_stale_files(self):
        obsolete = self.source / "mesa/obsolete.c"
        obsolete.write_text("old branch\n")
        self.prepare()
        staged = self.build / "src-mesa/obsolete.c"
        self.assertTrue(staged.exists())
        obsolete.unlink()
        self.prepare()
        self.assertFalse(staged.exists())


class MesaPatchContentTests(unittest.TestCase):
    def test_branding_is_applied_first(self):
        patches = sorted((ROOT / "patches/mesa").glob("*.patch"))
        self.assertTrue(patches)
        self.assertEqual(patches[0].name, "0000-radv-identify-salkim-driver.patch")

    def test_patch_subjects_are_unnumbered(self):
        for patch in (ROOT / "patches/mesa").glob("*.patch"):
            with self.subTest(patch=patch.name):
                subjects = re.findall(r"^Subject: (.*)$", patch.read_text(), re.M)
                for subject in subjects:
                    self.assertTrue(subject.startswith("[PATCH] "), subject)

    def test_shipped_patches_exclude_test_files(self):
        patches = sorted((ROOT / "patches/mesa").glob("*.patch"))
        self.assertTrue(patches)
        for patch in patches:
            with self.subTest(patch=patch.name):
                result = subprocess.run(
                    ["git", "apply", "--numstat", str(patch)],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.strip())
                for line in result.stdout.splitlines():
                    path = Path(line.split("\t", 2)[2])
                    self.assertFalse({"test", "tests"}.intersection(path.parts), str(path))


class MesaBrandingTests(unittest.TestCase):
    def test_branding_changes_only_the_public_driver_name(self):
        relative = Path("src/amd/vulkan/radv_physical_device.c")
        current = (ROOT / "mesa" / relative).read_text()
        old = 'snprintf(p->driverName, VK_MAX_DRIVER_NAME_SIZE, "radv");'
        new = 'snprintf(p->driverName, VK_MAX_DRIVER_NAME_SIZE, "radv-salkim");'
        self.assertEqual(current.count(new), 1)
        original = current.replace(new, old)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / relative
            source.parent.mkdir(parents=True)
            source.write_text(original)
            result = subprocess.run(
                ["patch", "--batch", "--fuzz=0", "-Np1", "-i",
                 str(ROOT / "patches/mesa/0000-radv-identify-salkim-driver.patch")],
                cwd=root, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            old = 'snprintf(p->driverName, VK_MAX_DRIVER_NAME_SIZE, "radv");'
            new = 'snprintf(p->driverName, VK_MAX_DRIVER_NAME_SIZE, "radv-salkim");'
            self.assertEqual(original.count(old), 1)
            self.assertEqual(source.read_text(), original.replace(old, new))
            self.assertIn('.driverName = "radv"', source.read_text())


if __name__ == "__main__":
    unittest.main()
