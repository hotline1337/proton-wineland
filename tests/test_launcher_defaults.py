"""Exercise launcher defaults from its actual environment-selection statements."""

import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "proton").read_text())
SESSION = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "Session")
INIT_SESSION = next(node for node in SESSION.body if isinstance(node, ast.FunctionDef)
                    and node.name == "init_session")


def has_string(node, text):
    return any(isinstance(value, ast.Constant) and value.value == text for value in ast.walk(node))


def compile_statements(statements):
    return compile(ast.Module(body=statements, type_ignores=[]), str(ROOT / "proton"), "exec")


class LauncherDefaults(unittest.TestCase):
    def wow64(self, appid, override=None, settings=None, architecture="x86_64"):
        environment = {"SteamGameId": appid}
        if override is not None:
            environment["PROTON_USE_WOW64"] = override
        session = SimpleNamespace(env=environment, compat_config=set())
        method = next(node for node in SESSION.body if isinstance(node, ast.FunctionDef)
                      and node.name == "check_environment")
        namespace = {"nonzero": lambda value: value not in ("0", "", "false")}
        exec(compile_statements([method]), namespace)
        session.check_environment = lambda *args: namespace["check_environment"](session, *args)
        statements = INIT_SESSION.body[:3] + [node for node in INIT_SESSION.body
                                             if has_string(node, "PROTON_USE_WOW64")]
        namespace.update({
            "self": session,
            "g_compatdata": SimpleNamespace(prefix_dir="/fake-prefix"),
            "g_proton": SimpleNamespace(user_settings_file="/fake-settings"),
            "file_exists": lambda *args, **kwargs: settings is not None,
            "platform": SimpleNamespace(machine=lambda: architecture),
        })
        with patch.dict("sys.modules", {"user_settings": SimpleNamespace(user_settings=settings or {})}):
            exec(compile_statements(statements), namespace)
        return session

    def test_dating_defaults(self):
        session = self.wow64("4005300")
        self.assertEqual(session.env["PROTON_USE_WOW64"], "1")
        self.assertEqual(session.env["WINEARCH"], "wow64")
        self.assertIn("wow64", session.compat_config)

    def test_explicit_wow64_choices(self):
        for value in ("0", "", "1"):
            with self.subTest(value=value):
                session = self.wow64("4005300", override=value)
                self.assertEqual(session.env["PROTON_USE_WOW64"], value)
                self.assertEqual("WINEARCH" in session.env, value == "1")
                self.assertEqual("wow64" in session.compat_config, value == "1")

    def test_user_settings_wow64_choices(self):
        for value in ("0", "", "1"):
            with self.subTest(value=value):
                session = self.wow64("4005300", settings={"PROTON_USE_WOW64": value})
                self.assertEqual(session.env["PROTON_USE_WOW64"], value)
                self.assertEqual("WINEARCH" in session.env, value == "1")

    def test_launch_environment_precedes_settings(self):
        session = self.wow64("4005300", override="0", settings={"PROTON_USE_WOW64": "1"})
        self.assertEqual(session.env["PROTON_USE_WOW64"], "0")
        self.assertNotIn("WINEARCH", session.env)

    def test_user_settings_architecture_is_preserved(self):
        session = self.wow64("4005300", settings={"WINEARCH": "win64"})
        self.assertEqual(session.env["WINEARCH"], "win64")

    def test_other_games_and_arm(self):
        self.assertNotIn("PROTON_USE_WOW64", self.wow64("0").env)
        self.assertNotIn("WINEARCH", self.wow64("4005300", architecture="aarch64").env)
        self.assertEqual(self.wow64("0", override="1").env["WINEARCH"], "wow64")


if __name__ == "__main__":
    unittest.main()
