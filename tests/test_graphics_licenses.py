"""Check binary license installation without building or installing Proton."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "make/graphics-licenses.mk"


def install_notices(source, destination, *variables):
    return subprocess.run(
        ["make", "--no-print-directory", "-s", "-f", str(RULES),
         f"SRCDIR={source}", f"DST_BASE={destination}", *variables,
         "graphics-licenses"],
        capture_output=True, text=True,
    )


class GraphicsLicenseTests(unittest.TestCase):
    def test_original_notices_are_installed_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            result = install_notices(ROOT, destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = destination / "licenses"
            for path in (
                "dxvk/LICENSE",
                "dxvk/subprojects/dxbc-spirv/LICENSE",
                "vkd3d-proton/LICENSE",
                "vkd3d-proton/COPYING",
                "vkd3d-proton/AUTHORS",
                "vkd3d-proton/subprojects/dxil-spirv/LICENSE.MIT",
                "vkd3d-proton/subprojects/dxil-spirv/subprojects/dxbc-spirv/LICENSE",
                "dxvk/subprojects/libdisplay-info/data/COPYING.hwdata",
                "extras/dxvk-low-latency/LICENSE",
                "extras/vkd3d-low-latency/LICENSE",
                "extras/dxvk-sarek/LICENSE",
            ):
                self.assertTrue((installed / path).is_file(), path)
            for notice in installed.rglob("*"):
                if notice.is_file():
                    original = ROOT / notice.relative_to(installed)
                    self.assertEqual(notice.read_bytes(), original.read_bytes(), str(original))

    def test_missing_required_notice_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            result = install_notices(Path(directory) / "missing", Path(directory) / "dist")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dxvk/LICENSE", result.stderr)

    def test_changed_notice_is_refreshed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "src"
            destination = Path(directory) / "dist"
            notice = source / "dxvk/LICENSE"
            notice.parent.mkdir(parents=True)
            notice.write_text("Original notice\n")
            selection = "GRAPHICS_LICENSE_FILES=dxvk/LICENSE"
            result = install_notices(source, destination, selection)
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = destination / "licenses/dxvk/LICENSE"
            notice.write_text("Updated notice\n")
            modified = installed.stat().st_mtime_ns + 2_000_000_000
            os.utime(notice, ns=(modified, modified))
            result = install_notices(source, destination, selection)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(installed.read_bytes(), notice.read_bytes())


if __name__ == "__main__":
    unittest.main()
