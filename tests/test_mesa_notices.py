import importlib.util
import pathlib
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "make/mesa-notices.py"
SPEC = importlib.util.spec_from_file_location("mesa_notices", SCRIPT)
NOTICES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NOTICES)


class MesaNoticesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)

    def source(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def package_fixture(self):
        mesa, libdrm = self.root / "mesa", self.root / "libdrm"
        for directory in NOTICES.MESA_TREES:
            (mesa / directory).mkdir(parents=True, exist_ok=True)
        for name in ("MIT", "Apache-2.0", "BSL-1.0"):
            self.source("mesa/licenses/" + name, (name + " full licence text").encode())
        self.source("mesa/docs/license.rst", b"Mesa licence documentation")
        self.source("mesa/src/util/blake3/README", b"BLAKE3 version 1.8.2.")
        for path in ("src/util/softfloat.c", "src/c11/impl/threads_posix.c", "src/amd/vulkan/radv_device.c", "include/vulkan/vulkan_core.h"):
            self.source("mesa/" + path, b"/* Copyright Actual Author */\nint source_only;\n")
        for path in ("xf86drm.c", "amdgpu/amdgpu_device.c", "include/drm/drm.h"):
            self.source("libdrm/" + path, b"/* Copyright DRM Author */\nint source_only;\n")
        protocols = self.root / "wayland-protocols"
        self.source("wayland-protocols/COPYING", b"Copyright Wayland Authors\nMIT terms.")
        for path in NOTICES.WAYLAND_PROTOCOLS:
            self.source("wayland-protocols/" + path, b'<protocol><copyright>Copyright Protocol Author\nMIT terms.</copyright><interface name="not_distributed"/></protocol>')
        asset = self.source("BLAKE3.txt", b"Apache License\nCopyright 2019 Jack O'Connor and Samuel Neves\nComplete licence terms.")
        return mesa, libdrm, self.root / "dest", asset, protocols

    def test_softfloat_complete_notice_without_code(self):
        legal = b"/*\nLicense for Berkeley SoftFloat\nCopyright Example\nRedistribution and use allowed.\nBSD condition one.\nBSD condition two.\nBSD condition three.\nDisclaimer.\n*/"
        path = self.source("softfloat.c", legal + b"\n#include <math.h>\nint secret_source_code = 1;\n")
        self.assertEqual(NOTICES.legal_headers(path), [legal])

    def test_multiple_leading_blocks_and_no_later_code(self):
        path = self.source("driver.c", b"/* Driver description */\n/* Copyright A */\n/* SPDX-License-Identifier: MIT */\nint code;\n/* Copyright later */")
        self.assertEqual(NOTICES.legal_headers(path), [b"/* Copyright A */", b"/* SPDX-License-Identifier: MIT */"])

    def test_line_comments_and_hash_prologue(self):
        path = self.source("generator.py", b"#!/usr/bin/python3\n# Copyright A\n# SPDX-License-Identifier: MIT\n\nimport sys\n")
        self.assertEqual(NOTICES.legal_headers(path), [b"#!/usr/bin/python3\n# Copyright A\n# SPDX-License-Identifier: MIT\n"])
        path = self.source("driver.cpp", b"// Copyright B\n// MIT permission\n\nint code;\n")
        self.assertEqual(NOTICES.legal_headers(path), [b"// Copyright B\n// MIT permission\n"])

    def test_c_preprocessor_is_not_a_hash_comment(self):
        path = self.source("driver.c", b"#define SECRET 42\n/* Copyright later */\n")
        self.assertEqual(NOTICES.legal_headers(path), [b"/* Copyright later */"])

    def test_header_guard_and_multiline_directive_before_copyright(self):
        path = self.source("driver.h", b"#ifndef HEADER\n#define HEADER\n#define VALUE \\\n    42\n/* Copyright Khronos */\ntypedef int foo;\n")
        self.assertEqual(NOTICES.legal_headers(path), [b"/* Copyright Khronos */"])

    def test_xml_copyright_preserved_without_protocol(self):
        block = b"<copyright>Copyright Example\nPermission is hereby granted.\nDisclaimer.</copyright>"
        path = self.source("protocol.xml", b'<?xml version="1.0"?><protocol>' + block + b'<interface name="secret"/></protocol>')
        self.assertEqual(NOTICES.legal_headers(path), [block])

    def test_malformed_xml_copyright_fails(self):
        path = self.source("protocol.xml", b"<protocol><copyright>Copyright Example</protocol>")
        with self.assertRaises(ValueError):
            NOTICES.legal_headers(path)

    def test_copyright_not_replaced_by_generic_mit_template(self):
        source = self.source("src/driver.c", b"/* Copyright 2026 Actual Author */\nint code;\n")
        self.source("licenses/MIT", b"MIT Copyright (c) <year> <copyright holders>")
        output = self.root / "COPYRIGHTS"
        NOTICES.collect(self.root, [source], output, ["src/driver.c"])
        self.assertIn(b"Copyright 2026 Actual Author", output.read_bytes())
        self.assertNotIn(b"int code", output.read_bytes())

    def test_identical_notices_group_sources(self):
        paths = [self.source(name, b"/* Copyright A */\nint code;\n") for name in ("a.c", "b.c")]
        output = self.root / "COPYRIGHTS"
        NOTICES.collect(self.root, paths, output, ["a.c", "b.c"])
        result = output.read_bytes()
        self.assertIn(b"a.c\nb.c\n", result)
        self.assertEqual(result.count(b"Copyright A"), 1)

    def test_missing_required_file_or_notice_fails(self):
        with self.assertRaises(FileNotFoundError):
            NOTICES.collect(self.root, [self.root / "absent"], self.root / "COPYRIGHTS", [])
        source = self.source("no-notice.c", b"int code;\n")
        with self.assertRaises(ValueError):
            NOTICES.collect(self.root, [source], self.root / "COPYRIGHTS", ["no-notice.c"])

    def test_non_utf8_notice_preserves_bytes(self):
        block = b"/* Copyright \xa9 Example */"
        path = self.source("driver.c", block + b"\nint code;\n")
        self.assertEqual(NOTICES.legal_headers(path), [block])

    def test_symlink_not_followed(self):
        self.source("outside/real.c", b"/* Copyright A */\n")
        link = self.root / "src/link.c"
        link.parent.mkdir()
        link.symlink_to(self.root / "outside/real.c")
        output = self.root / "COPYRIGHTS"
        NOTICES.collect(self.root, [link.parent], output, [])
        self.assertEqual(output.read_bytes(), b"")

    def test_package_requires_assets(self):
        with self.assertRaises(FileNotFoundError):
            NOTICES.package(self.root / "mesa", self.root / "libdrm", self.root / "dest", self.root / "license", self.root / "wayland-protocols")

    def test_package_copies_full_texts_and_notices_without_sources(self):
        arguments = self.package_fixture()
        NOTICES.package(*arguments)
        NOTICES.package(*arguments)
        destination = arguments[2]
        self.assertEqual((destination / "mesa/licenses/MIT").read_bytes(), b"MIT full licence text")
        self.assertEqual((destination / "mesa/BLAKE3-LICENSE_A2").read_bytes(), arguments[3].read_bytes())
        self.assertIn(b"Copyright Actual Author", (destination / "mesa/COPYRIGHTS").read_bytes())
        self.assertIn(b"Copyright DRM Author", (destination / "libdrm/COPYRIGHTS").read_bytes())
        self.assertFalse(any(path.suffix in (".c", ".h") for path in destination.rglob("*")))
        self.assertNotIn(b"source_only", (destination / "mesa/COPYRIGHTS").read_bytes())

    def test_package_includes_generated_protocol_copyrights(self):
        arguments = self.package_fixture()
        NOTICES.package(*arguments)
        destination = arguments[2] / "mesa/wayland-protocols"
        result = (destination / "COPYRIGHTS").read_bytes()
        for protocol in NOTICES.WAYLAND_PROTOCOLS:
            self.assertIn(protocol.encode(), result)
        self.assertIn(b"Copyright Protocol Author", result)
        self.assertNotIn(b"not_distributed", result)
        self.assertEqual((destination / "COPYING").read_bytes(), (arguments[4] / "COPYING").read_bytes())

    def test_package_rejects_missing_protocol_copyright(self):
        arguments = self.package_fixture()
        (arguments[4] / NOTICES.WAYLAND_PROTOCOLS[0]).write_bytes(b"<protocol/>")
        with self.assertRaises(ValueError):
            NOTICES.package(*arguments)

    def test_package_includes_upstream_presentation_protocol_copyright(self):
        arguments = self.package_fixture()
        path = "stable/presentation-time/presentation-time.xml"
        self.source("wayland-protocols/" + path, b'<protocol><copyright>Copyright Collabora</copyright></protocol>')
        NOTICES.package(*arguments)
        notices = (arguments[2] / "mesa/wayland-protocols/COPYRIGHTS").read_bytes()
        self.assertIn(path.encode(), notices)
        self.assertIn(b"Copyright Collabora", notices)

    def test_package_rejects_missing_required_licence(self):
        arguments = self.package_fixture()
        (arguments[0] / "licenses/BSL-1.0").unlink()
        with self.assertRaises(FileNotFoundError):
            NOTICES.package(*arguments)

    def test_package_rejects_stale_blake3_asset(self):
        arguments = self.package_fixture()
        (arguments[0] / "src/util/blake3/README").write_bytes(b"BLAKE3 version 9.0.0.")
        with self.assertRaises(ValueError):
            NOTICES.package(*arguments)

    def test_package_rejects_generic_blake3_licence_without_copyright(self):
        arguments = self.package_fixture()
        arguments[3].write_bytes(b"Apache License template without copyright")
        with self.assertRaises(ValueError):
            NOTICES.package(*arguments)


if __name__ == "__main__":
    unittest.main()
