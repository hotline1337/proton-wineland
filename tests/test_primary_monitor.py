"""Run with python tests/test_primary_monitor.py; no Wine or desktop changes."""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_monitor


def gnome_output(connector, primary, crtc=0):
    return [0, 0, crtc, [0], connector, [0], [],
            {"primary": {"type": "b", "data": primary}}]


def gnome_state(outputs):
    return {"type": "ua(uxiiiiiuaua{sv})a(uxiausauaua{sv})a(uxuudu)ii",
            "data": [1, [], outputs, [], 65535, 65535]}


def cosmic_output(name="DP-3", primary=True, enabled=True):
    # Match cosmic-randr list --kdl, including its nested mode list.
    flag = "" if primary is None else "  xwayland_primary #" + str(primary).lower() + "\n"
    return ('output "' + name + '" enabled=#' + str(enabled).lower() + ' {\n'
            '  description make="LG Electronics" model="LG ULTRAGEAR+"\n'
            '  position 5120 291\n  scale 1.00\n' + flag +
            '  modes {\n    mode 5120 2160 240084 current=#true preferred=#true\n  }\n}\n')


class PrimaryMonitorTests(unittest.TestCase):
    def setUp(self):
        self.env = {"XDG_CURRENT_DESKTOP": "GNOME", "PATH": "/usr/bin"}
        self.state = gnome_state([gnome_output("DP-2", False, 5),
                                 gnome_output("DP-3", True, 4)])
        self.executables = {"busctl": "/usr/bin/busctl", "kscreen-doctor": "/usr/bin/kscreen-doctor",
                            "niri": "/usr/bin/niri", "cosmic-randr": "/usr/bin/cosmic-randr"}
        self.which = mock.patch.object(shutil, "which", side_effect=lambda name, **_: self.executables.get(name))
        self.which.start()
        self.addCleanup(self.which.stop)
        self.run_patch = mock.patch.object(subprocess, "run")
        self.run = self.run_patch.start()
        self.run.return_value = SimpleNamespace(stdout=json.dumps(self.state))
        self.addCleanup(self.run_patch.stop)
        self.log = mock.Mock()

    def detect(self):
        desktop_monitor.setup_primary_monitor(self.env, self.log)
        return self.env.get("WAYLANDDRV_PRIMARY_MONITOR")

    def test_gnome_reads_output_primary_flag(self):
        self.assertEqual(self.detect(), "DP-3")
        self.run.assert_called_once()
        command = self.run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/busctl")
        self.assertIn("--json=short", command)
        self.assertIn("--auto-start=no", command)
        self.assertIn("--allow-interactive-authorization=no", command)
        self.assertEqual(command[-1], "GetResources")
        self.assertEqual(self.run.call_args.kwargs["timeout"], 2)
        self.log.assert_called_once_with("Using GNOME primary monitor DP-3")

    def test_gnome_changed_primary_independent_of_output_order(self):
        # After switching to DP-2, GetCurrentState can still mark both logical
        # monitors primary; GetResources reports the updated output flags.
        outputs = [gnome_output("DP-2", True, 5), gnome_output("DP-3", False, 4)]
        for ordered in (outputs, list(reversed(outputs))):
            with self.subTest(outputs=ordered):
                self.env.pop("WAYLANDDRV_PRIMARY_MONITOR", None)
                self.run.return_value.stdout = json.dumps(gnome_state(ordered))
                self.assertEqual(self.detect(), "DP-2")
                self.assertEqual(self.run.call_args.args[0][-1], "GetResources")

    def test_gnome_desktop_variants(self):
        for variable, value in (("XDG_CURRENT_DESKTOP", "ubuntu:GNOME"),
                                ("XDG_CURRENT_DESKTOP", "GNOME-Classic:GNOME"),
                                ("XDG_SESSION_DESKTOP", "gnome")):
            with self.subTest(variable=variable, value=value):
                self.env = {variable: value}
                self.assertEqual(self.detect(), "DP-3")

    def test_explicit_override_including_empty_is_untouched(self):
        for desktop in ("GNOME", "KDE", "niri", "COSMIC"):
            for value in ("DP-9", ""):
                self.env = {"XDG_CURRENT_DESKTOP": desktop, "WAYLANDDRV_PRIMARY_MONITOR": value}
                self.assertEqual(self.detect(), value)
        self.run.assert_not_called()

    def test_unknown_desktop_does_not_query(self):
        for desktop in ("sway", "Hyprland", "", "GNOME-ish", "niri-ish", "COSMIC-ish"):
            self.env = {"XDG_CURRENT_DESKTOP": desktop}
            self.assertIsNone(self.detect())
        self.run.assert_not_called()

    def test_missing_utility_keeps_fallback(self):
        self.executables.clear()
        for desktop in ("GNOME", "KDE", "niri", "COSMIC"):
            self.env = {"XDG_CURRENT_DESKTOP": desktop}
            self.assertIsNone(self.detect())
        self.run.assert_not_called()

    def test_query_failure_keeps_fallback(self):
        for desktop in ("GNOME", "KDE", "niri", "COSMIC"):
            self.env = {"XDG_CURRENT_DESKTOP": desktop}
            for error in (OSError("not available"), subprocess.TimeoutExpired("query", 2),
                          subprocess.CalledProcessError(1, "query")):
                with self.subTest(desktop=desktop, error=error):
                    self.run.side_effect = error
                    self.assertIsNone(self.detect())

    def test_malformed_response_keeps_fallback(self):
        invalid = (None, [], {}, {"data": None}, {"data": []},
                   {"data": [1, [], None, [], 65535, 65535]},
                   gnome_state([None]), gnome_state([[0]]),
                   gnome_state([[0, 0, 0, [0], "DP-3", [0], [], None]]),
                   gnome_state([[0, 0, 0, [0], "DP-3", [0], [], {"primary": True}]]),
                   gnome_state([gnome_output("DP-3", True, "0")]),
                   gnome_state([gnome_output("DP-3", True, True)]),
                   gnome_state([gnome_output("DP-3", "true")]),
                   gnome_state([gnome_output("DP-3", 1)]),
                   gnome_state([gnome_output(None, True)]),
                   gnome_state([gnome_output("", True)]))
        for state in invalid:
            with self.subTest(state=state):
                self.run.return_value.stdout = json.dumps(state)
                self.assertIsNone(self.detect())
        self.run.return_value.stdout = "not JSON"
        self.assertIsNone(self.detect())

    def test_missing_or_ambiguous_primary_keeps_fallback(self):
        for outputs in ([], [gnome_output("DP-2", False)],
                        [gnome_output("DP-2", True), gnome_output("DP-3", True)]):
            with self.subTest(outputs=outputs):
                self.run.return_value.stdout = json.dumps(gnome_state(outputs))
                self.assertIsNone(self.detect())

    def test_gnome_ignores_disabled_outputs(self):
        self.run.return_value.stdout = json.dumps(gnome_state([
            gnome_output("DP-2", True, -1), gnome_output("DP-3", True, 4)]))
        self.assertEqual(self.detect(), "DP-3")

    def test_gnome_requires_boolean_primary_property(self):
        for primary in (None, {}, {"type": "s", "data": "true"},
                        {"type": "s", "data": True}, {"type": "b"}):
            with self.subTest(primary=primary):
                output = gnome_output("DP-3", True)
                output[7] = {} if primary is None else {"primary": primary}
                self.run.return_value.stdout = json.dumps(gnome_state([output]))
                self.assertIsNone(self.detect())

    def test_gnome_host_launcher(self):
        self.executables = {"steam-runtime-launch-client": "/runtime/steam-runtime-launch-client"}
        self.assertEqual(self.detect(), "DP-3")
        self.assertEqual(self.run.call_args.args[0][:4],
                         ["/runtime/steam-runtime-launch-client", "--alongside-steam", "--", "/usr/bin/busctl"])

    def niri(self, name="DP-2"):
        self.env = {"XDG_CURRENT_DESKTOP": "niri", "NIRI_SOCKET": "/run/user/1000/niri.sock"}
        self.run.return_value.stdout = json.dumps({
            "name": name, "current_mode": 0,
            "logical": {"x": 3840, "y": 0, "width": 5120, "height": 2160,
                        "scale": 1.0, "transform": "Normal"}})

    def test_niri_uses_focused_output_once(self):
        self.niri()
        self.assertEqual(self.detect(), "DP-2")
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0],
                         ["/usr/bin/niri", "msg", "--json", "focused-output"])
        self.assertEqual(self.run.call_args.kwargs["timeout"], 2)
        self.log.assert_called_once_with("Using niri focused monitor DP-2")

    def test_niri_desktop_variants(self):
        self.niri()
        for variable, value in (("XDG_CURRENT_DESKTOP", "niri"),
                                ("XDG_CURRENT_DESKTOP", "custom:niri"),
                                ("XDG_SESSION_DESKTOP", "niri")):
            with self.subTest(variable=variable, value=value):
                self.env = {variable: value}
                self.assertEqual(self.detect(), "DP-2")

    def test_niri_host_launcher(self):
        self.niri()
        self.executables = {"steam-runtime-launch-client": "/runtime/steam-runtime-launch-client"}
        self.assertEqual(self.detect(), "DP-2")
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0],
                         ["/runtime/steam-runtime-launch-client", "--alongside-steam", "--",
                          "/usr/bin/niri", "msg", "--json", "focused-output"])
        self.assertEqual(self.run.call_args.kwargs["env"]["NIRI_SOCKET"], "/run/user/1000/niri.sock")

    def test_niri_missing_disabled_or_malformed_output_keeps_fallback(self):
        self.niri()
        for state in (None, [], {}, {"name": "DP-2"},
                      {"name": "DP-2", "logical": None},
                      {"name": "DP-2", "logical": []},
                      {"name": "", "logical": {}},
                      {"name": 2, "logical": {}}):
            with self.subTest(state=state):
                self.run.return_value.stdout = json.dumps(state)
                self.assertIsNone(self.detect())
        self.run.return_value.stdout = "not JSON"
        self.assertIsNone(self.detect())

    def test_niri_next_launch_reads_current_focus(self):
        for name in ("DP-2", "DP-3"):
            self.niri(name)
            self.assertEqual(self.detect(), name)
        self.assertEqual(self.run.call_count, 2)

    def cosmic(self, output=None):
        self.env = {"XDG_CURRENT_DESKTOP": "COSMIC"}
        self.run.return_value.stdout = output if output is not None else (
            cosmic_output("DP-2", False) + cosmic_output("DP-3"))

    def test_cosmic_reads_configured_primary_once(self):
        self.cosmic()
        self.assertEqual(self.detect(), "DP-3")
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0], ["/usr/bin/cosmic-randr", "list", "--kdl"])
        self.assertEqual(self.run.call_args.kwargs["timeout"], 2)
        self.log.assert_called_once_with("Using COSMIC Xwayland-primary monitor DP-3")

    def test_cosmic_desktop_variants(self):
        self.cosmic()
        for variable, value in (("XDG_CURRENT_DESKTOP", "COSMIC"),
                                ("XDG_CURRENT_DESKTOP", "custom:COSMIC"),
                                ("XDG_SESSION_DESKTOP", "cosmic")):
            with self.subTest(variable=variable, value=value):
                self.env = {variable: value}
                self.assertEqual(self.detect(), "DP-3")

    def test_cosmic_host_launcher(self):
        self.cosmic()
        self.executables = {"steam-runtime-launch-client": "/runtime/steam-runtime-launch-client"}
        self.assertEqual(self.detect(), "DP-3")
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0],
                         ["/runtime/steam-runtime-launch-client", "--alongside-steam", "--",
                          "/usr/bin/cosmic-randr", "list", "--kdl"])

    def test_cosmic_ignores_disabled_primary_and_output_order(self):
        for output in (cosmic_output("DP-2", True, False) + cosmic_output("DP-3"),
                       cosmic_output("DP-3") + cosmic_output("DP-2", True, False)):
            self.cosmic(output)
            self.assertEqual(self.detect(), "DP-3")

    def test_cosmic_missing_or_ambiguous_primary_keeps_fallback(self):
        for output in ("", cosmic_output(primary=None), cosmic_output(primary=False),
                       cosmic_output(enabled=False), cosmic_output() + cosmic_output("DP-2")):
            with self.subTest(output=output):
                self.cosmic(output)
                self.assertIsNone(self.detect())

    def test_cosmic_malformed_output_keeps_fallback(self):
        valid = cosmic_output()
        invalid = ("not KDL", "null", "{}", "}", valid + "}", valid + "output",
                   valid.rsplit("}", 1)[0], valid.replace("  }\n", ""),
                   valid.replace('"DP-3"', '"DP-3'), valid.replace('"DP-3"', '""'),
                   valid.replace('model="LG ULTRAGEAR+"', 'model="LG ULTRAGEAR+'),
                   valid.replace("enabled=#true", "enabled=true"),
                   valid.replace("xwayland_primary #true", "xwayland_primary true"),
                   valid.replace("xwayland_primary #true", 'xwayland_primary "#true"'),
                   valid.replace("xwayland_primary #true", "xwayland_primary #true extra"),
                   valid.replace("  modes {", "  xwayland_primary #false\n  modes {"),
                   valid.replace("  modes {", "  unknown {"),
                   valid.replace("    mode ", "    xwayland_primary #true\n    mode "))
        for output in invalid:
            with self.subTest(output=output):
                self.cosmic(output)
                self.assertIsNone(self.detect())

    def test_cosmic_metadata_is_not_a_primary_flag_or_block_boundary(self):
        output = cosmic_output(primary=False).replace(
            'model="LG ULTRAGEAR+"', 'model="xwayland_primary #true { }"')
        self.cosmic(output)
        self.assertIsNone(self.detect())
        self.cosmic(cosmic_output().replace('model="LG ULTRAGEAR+"', 'model="{ }"'))
        self.assertEqual(self.detect(), "DP-3")

    def test_cosmic_next_launch_reads_current_primary(self):
        for name in ("DP-3", "DP-2"):
            self.cosmic(cosmic_output(name))
            self.assertEqual(self.detect(), name)
        self.assertEqual(self.run.call_count, 2)

    def kde(self):
        self.env = {"XDG_CURRENT_DESKTOP": "KDE"}
        self.run.return_value.stdout = json.dumps({"outputs": [
            {"name": "DP-2", "connected": True, "enabled": True, "priority": 2},
            {"name": "DP-3", "connected": True, "enabled": True, "priority": 1}]})

    def test_kde_direct_query_unchanged(self):
        self.kde()
        self.assertEqual(self.detect(), "DP-3")
        self.assertEqual(self.run.call_args.args[0], ["/usr/bin/kscreen-doctor", "-j"])
        self.log.assert_called_once_with("Using Plasma primary monitor DP-3")

    def test_kde_host_query_unchanged(self):
        self.kde()
        self.executables = {"steam-runtime-launch-client": "/runtime/steam-runtime-launch-client"}
        self.assertEqual(self.detect(), "DP-3")
        self.assertEqual(self.run.call_args.args[0],
                         ["/runtime/steam-runtime-launch-client", "--alongside-steam", "--",
                          "/usr/bin/kscreen-doctor", "-j"])

    def test_kde_full_session_still_works(self):
        self.kde()
        self.env = {"KDE_FULL_SESSION": "true"}
        self.assertEqual(self.detect(), "DP-3")

    def test_parsers_do_not_query_or_change_environment(self):
        inputs = {
            "KDE": json.dumps({"outputs": [
                {"name": "DP-3", "connected": True, "enabled": True, "priority": 1}]}),
            "GNOME": json.dumps(self.state),
            "NIRI": json.dumps({"name": "DP-3", "logical": {"x": 5120, "y": 0}}),
            "COSMIC": cosmic_output(),
        }
        before = dict(self.env)
        for desktop, (_, _, parse) in desktop_monitor._DESKTOPS.items():
            with self.subTest(desktop=desktop):
                self.assertEqual(parse(inputs[desktop]), ["DP-3"])
        self.assertEqual(self.env, before)
        self.run.assert_not_called()
        self.log.assert_not_called()

    def test_composite_desktop_precedence_is_preserved(self):
        self.kde()
        self.env["XDG_CURRENT_DESKTOP"] = "COSMIC:niri:GNOME:KDE"
        self.assertEqual(self.detect(), "DP-3")
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0], ["/usr/bin/kscreen-doctor", "-j"])

    def test_failed_query_does_not_try_another_desktop(self):
        self.env["XDG_CURRENT_DESKTOP"] = "GNOME:niri:COSMIC"
        self.run.side_effect = subprocess.CalledProcessError(1, "busctl")
        before = dict(self.env)
        self.assertIsNone(self.detect())
        self.assertEqual(self.env, before)
        self.run.assert_called_once()
        self.log.assert_not_called()

    def test_command_table_is_not_mutated_by_host_launch(self):
        before = dict(desktop_monitor._DESKTOPS)
        self.executables = {"steam-runtime-launch-client": "/runtime/steam-runtime-launch-client"}
        self.assertEqual(self.detect(), "DP-3")
        self.assertEqual(desktop_monitor._DESKTOPS, before)
        self.assertTrue(all(isinstance(command, tuple) for _, command, _ in before.values()))

    def test_selected_name_is_validated_before_export(self):
        self.kde()
        self.run.return_value.stdout = json.dumps({"outputs": [
            {"name": 123, "connected": True, "enabled": True, "priority": 1}]})
        before = dict(self.env)
        self.assertIsNone(self.detect())
        self.assertEqual(self.env, before)
        self.log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
