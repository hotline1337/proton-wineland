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


if __name__ == "__main__":
    unittest.main()
