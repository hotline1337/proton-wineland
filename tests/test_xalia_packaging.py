"""Test Xalia packaging in temporary directories without building Proton."""

import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class XaliaPackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / "source"
        self.object = self.directory / "object"
        (self.source / "contrib").mkdir(parents=True)
        self.object.mkdir()
        self.fixups = (ROOT / "xalia-fixups.gudl").read_bytes()
        (self.source / "xalia-fixups.gudl").write_bytes(self.fixups)
        makefile = (ROOT / "Makefile.in").read_text()
        # Use the actual Mono and Xalia rules without synchronizing other components.
        rules = makefile[makefile.index("WINEMONO_VER :="):makefile.index("xalia-distclean::")]
        self.makefile = self.directory / "Makefile"
        self.makefile.write_text(
            f"SRC := {self.source}\nOBJ := {self.object}\n"
            "DST_DIR := $(OBJ)/dist/files\nSHELL := /bin/bash\n" + rules
        )
        self.version = next(line.split(":=", 1)[1].strip() for line in rules.splitlines()
                            if line.startswith("WINEMONO_VER :="))
        self.xalia_version = next(line.split(":=", 1)[1].strip() for line in rules.splitlines()
                                  if line.startswith("XALIA_VER :="))
        self.target = self.object / ".xalia-dist"
        self.installed = self.object / "dist/files/share/xalia"

    def fixtures(self, architecture, include_sdl=True):
        suffix = "arm64-mono" if architecture == "arm64" else "mono"
        archive = self.source / "contrib" / f"xalia-{self.xalia_version}-net48-{suffix}.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("SDL3.dll", b"bundled SDL")
            package.writestr("main.gudl", b"\xef\xbb\xbf// original rules\n")
        return self.mono_fixture(architecture, include_sdl)

    def mono_fixture(self, architecture, include_sdl=True, contents=None):
        suffix = "arm64" if architecture == "arm64" else "x86"
        archive = self.source / "contrib" / f"wine-mono-{self.version}-{suffix}.tar.xz"
        with tarfile.open(archive, "w:xz") as package:
            filename = f"wine-mono-{self.version}/lib/{architecture}/"
            filename += "SDL3.dll" if include_sdl else "other.dll"
            if contents is None:
                contents = architecture.encode()
            member = tarfile.TarInfo(filename)
            member.size = len(contents)
            package.addfile(member, io.BytesIO(contents))
        return archive

    def build(self, architecture):
        return subprocess.run(
            ["make", "--no-print-directory", "-j2", "-f", str(self.makefile),
             f"TARGET_ARCH={architecture}", str(self.target)],
            cwd=self.object, capture_output=True, text=True, timeout=30,
        )

    def check_success(self, architecture):
        self.fixtures(architecture)
        result = self.build(architecture)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.target.is_file())
        self.assertTrue((self.object / ".wine-mono-dist").is_file())
        library = self.installed / "SDL3.dll"
        self.assertTrue(library.is_symlink())
        self.assertEqual(os.readlink(library),
                         f"../wine/mono/wine-mono/lib/{architecture}/SDL3.dll")
        self.assertEqual(library.read_bytes(), architecture.encode())
        self.assertEqual((self.installed / "main.gudl").read_bytes(),
                         self.fixups + b"// original rules\n")

    def test_x86_64_package(self):
        self.check_success("x86_64")

    def test_arm64_package(self):
        self.check_success("arm64")

    def check_missing_library(self, architecture):
        self.fixtures(architecture, include_sdl=False)
        result = self.build(architecture)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.installed / "SDL3.dll").is_symlink())
        self.assertEqual((self.installed / "SDL3.dll").read_bytes(), b"bundled SDL")

    def test_missing_x86_64_library_fails(self):
        self.check_missing_library("x86_64")

    def test_missing_arm64_library_fails(self):
        self.check_missing_library("arm64")

    def test_updated_mono_refreshes_package(self):
        architecture = "x86_64"
        self.check_success(architecture)
        archive = self.mono_fixture(architecture, contents=b"updated SDL")
        updated = self.target.stat().st_mtime_ns + 2_000_000_000
        os.utime(archive, ns=(updated, updated))
        result = self.build(architecture)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unzip", result.stdout)
        self.assertEqual((self.installed / "SDL3.dll").read_bytes(), b"updated SDL")


if __name__ == "__main__":
    unittest.main()
