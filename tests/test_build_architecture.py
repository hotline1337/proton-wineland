"""Check target selection and compiler flags without building Proton."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConfigureArchitectureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.engine = self.directory / "container"
        self.engine.write_text('#!/bin/sh\ncase "$*" in *"stat --format"*) echo 0 ;; esac\n')
        self.engine.chmod(0o755)

    def configure(self, *options, **flags):
        environment = os.environ.copy()
        environment.pop("CFLAGS", None)
        environment.pop("RUSTFLAGS", None)
        environment.update(flags)
        return subprocess.run(
            [str(ROOT / "configure.sh"), f"--container-engine={self.engine}", *options],
            cwd=self.directory, env=environment, capture_output=True, text=True, timeout=30,
        )

    def variables(self, *names):
        result = subprocess.run(
            ["make", "--no-print-directory", "-s", "--eval",
             "print: ; @printf '%s\\n' " + " ".join(f"'$({name})'" for name in names),
             "print"],
            cwd=self.directory, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.splitlines()

    def test_x86_64_defaults(self):
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        architecture, cflags, rustflags, image = self.variables(
            "TARGET_ARCH", "x86_64_CFLAGS", "x86_64_RUSTFLAGS", "STEAMRT_IMAGE")
        self.assertEqual(architecture, "x86_64")
        self.assertIn("-march=nocona", cflags)
        self.assertIn("-Ctarget-cpu=nocona", rustflags)
        self.assertIn("/sdk/x86_64:", image)

    def test_arm64_defaults(self):
        result = self.configure("--target-arch=arm64")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        architecture, cflags, ecflags, rustflags, ecrustflags, image = self.variables(
            "TARGET_ARCH", "aarch64_CFLAGS", "arm64ec_CFLAGS", "aarch64_RUSTFLAGS",
            "arm64ec_RUSTFLAGS", "STEAMRT_IMAGE")
        self.assertEqual(architecture, "arm64")
        self.assertEqual(cflags, "-O2 -march=armv8.2-a -mtune=cortex-x3")
        self.assertEqual(ecflags, cflags)
        self.assertEqual(rustflags, "-Copt-level=3 -Ctarget-cpu=armv8.2-a")
        self.assertEqual(ecrustflags, rustflags)
        self.assertIn("/sdk/arm64-llvm:", image)
        self.assertNotIn("nocona", (self.directory / "Makefile").read_text())

    def test_arm64_custom_flags_do_not_reach_x86_pe(self):
        result = self.configure("--target-arch=arm64", CFLAGS="-O3 -mcpu=cortex-a76",
                                RUSTFLAGS="-Copt-level=2 -Ctarget-cpu=cortex-a76")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cflags, ecflags, x86flags, rustflags, ecrustflags, x86rustflags = self.variables(
            "aarch64_CFLAGS", "arm64ec_CFLAGS", "x86_64_CFLAGS", "aarch64_RUSTFLAGS",
            "arm64ec_RUSTFLAGS", "x86_64_RUSTFLAGS")
        self.assertEqual(cflags, "-O3 -mcpu=cortex-a76")
        self.assertEqual(ecflags, cflags)
        self.assertNotIn("cortex-a76", x86flags)
        self.assertEqual(rustflags, "-Copt-level=2 -Ctarget-cpu=cortex-a76")
        self.assertEqual(ecrustflags, rustflags)
        self.assertNotIn("cortex-a76", x86rustflags)

    def test_invalid_architecture_with_explicit_sdk_fails(self):
        result = self.configure("--target-arch=riscv64", "--proton-sdk-image=unused")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown target architecture: riscv64", result.stderr)
        self.assertFalse((self.directory / "Makefile").exists())


class WrapperArchitectureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        (self.directory / "Makefile.in").symlink_to(ROOT / "Makefile.in")

    def make(self, architecture, *options):
        return subprocess.run(
            ["make", "--no-print-directory", "-f", str(ROOT / "Makefile"),
             "build_name=fixture", f"target_arch={architecture}", "MAKE=true", *options],
            cwd=self.directory, capture_output=True, text=True, timeout=30,
        )

    def build_directory(self, architecture):
        suffix = "-arm64" if architecture == "arm64" else ""
        directory = self.directory / f"build/build-fixture{suffix}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "Makefile").touch()
        return directory

    def test_configure_target_and_sdk(self):
        for architecture in ("x86_64", "arm64"):
            with self.subTest(architecture=architecture):
                result = self.make(architecture, "-n", "configure", "protonsdk_version=fixture")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"--target-arch={architecture}", result.stdout)
                sdk = "arm64-llvm" if architecture == "arm64" else "x86_64"
                self.assertIn(f"/steamrt4/sdk/{sdk}:fixture", result.stdout)
                suffix = "-arm64" if architecture == "arm64" else ""
                self.assertIn(f"mkdir -p build/build-fixture{suffix}\n", result.stdout)

    def test_local_arm_sdk_uses_llvm(self):
        result = self.make("arm64", "-n", "protonsdk", "protonsdk_version=local")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BUILD_ARCH=aarch64 proton-llvm", result.stdout)

    def test_invalid_architecture_fails(self):
        result = self.make("riscv64", "-n", "configure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown target_arch=riscv64", result.stderr)

    def test_module_copies_selected_architectures(self):
        for architecture in ("x86_64", "arm64"):
            for module, pefile, sofile in (("dsound", "dsound.dll", "dsound.so"),
                                           ("winewayland.drv", "winewayland.drv", "winewayland.so")):
                with self.subTest(architecture=architecture, module=module):
                    build = self.build_directory(architecture)
                    pe_archs = ["i386", "x86_64"]
                    unix_archs = pe_archs
                    if architecture == "arm64":
                        pe_archs += ["aarch64"]
                        unix_archs = ["aarch64"]
                    for arch in pe_archs:
                        objarch = "aarch64" if architecture == "arm64" else arch
                        source = build / f"obj-wine-{objarch}/dlls/{module}/{arch}-windows/{pefile}"
                        source.parent.mkdir(parents=True, exist_ok=True)
                        source.write_text(arch)
                    for arch in unix_archs:
                        (build / f"obj-wine-{arch}/dlls/{module}/{sofile}").write_text(arch)
                    result = self.make(architecture, f"module={module}", "module")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    destination = self.directory / f"build/{module}/lib/wine"
                    for arch in pe_archs:
                        self.assertEqual((destination / f"{arch}-windows/{pefile}").read_text(), arch)
                    for arch in unix_archs:
                        self.assertEqual((destination / f"{arch}-unix/{sofile}").read_text(), arch)

    def test_arm_development_library_copies(self):
        build = self.build_directory("arm64")
        archs = ("i386-windows", "x86_64-windows", "aarch64-windows", "aarch64-unix")
        for helper in ("lsteamclient", "vrclient", "wineopenxr"):
            with self.subTest(helper=helper):
                for arch in archs:
                    filename = helper
                    if helper == "vrclient" and not arch.startswith("i386"):
                        filename += "_x64"
                    filename += ".so" if arch.endswith("unix") else ".dll"
                    source = build / f"dist/files/lib/wine/{arch}/{filename}"
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text(arch)
                result = self.make("arm64", helper)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                destination = self.directory / f"build/{helper}/lib/wine"
                self.assertEqual({path.name for path in destination.iterdir()}, set(archs))
                self.assertEqual(next((destination / "aarch64-unix").iterdir()).read_text(),
                                 "aarch64-unix")

    def test_inner_arm_module_uses_native_object(self):
        makefile = (ROOT / "Makefile.in").read_text()
        rules = makefile[makefile.index(".PHONY: module32"):makefile.index("else # outside of the container")]
        rules = rules[:rules.index("###############################")]
        fixture = self.directory / "modules.mk"
        fixture.write_text("WINE_aarch64_OBJ := obj-wine-aarch64\n"
                           "WINE_i386_OBJ := obj-wine-i386\n"
                           "WINE_x86_64_OBJ := obj-wine-x86_64\n"
                           ".PHONY: all-source wine-configure wine-aarch64-configure\n" + rules)
        result = subprocess.run(
            ["make", "--no-print-directory", "-n", "-f", str(fixture), "TARGET_ARCH=arm64",
             "MAKE=true", "module=dsound", "module"],
            cwd=self.directory, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("obj-wine-aarch64/dlls/dsound", result.stdout)
        self.assertNotIn("obj-wine-i386", result.stdout)
        self.assertNotIn("obj-wine-x86_64", result.stdout)


if __name__ == "__main__":
    unittest.main()
