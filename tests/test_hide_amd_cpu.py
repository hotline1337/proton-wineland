import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class HideAmdCpu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / "proton"
        tree = ast.parse(source.read_text())
        session = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Session")
        init = next(node for node in session.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        cls.namespace = {
            "os": os,
            "g_proton": SimpleNamespace(version_file="/nonexistent-proton-version"),
            "default_compat_config": lambda: set(),
            "default_cpu_limit": {},
        }
        exec(compile(ast.Module(body=[init], type_ignores=[]), str(source), "exec"), cls.namespace)

    def session(self, appid, value=None):
        env = {"SteamGameId": appid}
        if value is not None:
            env["WINE_HIDE_AMD_CPU"] = value
        result = SimpleNamespace()
        with patch.dict(os.environ, env, clear=True):
            self.namespace["__init__"](result)
        return result.env

    def test_crysis_defaults(self):
        for appid in ("17300", "17340"):
            with self.subTest(appid=appid):
                self.assertEqual(self.session(appid)["WINE_HIDE_AMD_CPU"], "1")

    def test_user_values_are_preserved(self):
        for appid in ("17300", "17340"):
            for value in ("0", "1", ""):
                with self.subTest(appid=appid, value=value):
                    self.assertEqual(self.session(appid, value)["WINE_HIDE_AMD_CPU"], value)

    def test_other_games(self):
        self.assertNotIn("WINE_HIDE_AMD_CPU", self.session("1282690"))
        self.assertNotIn("WINE_HIDE_AMD_CPU", self.session("0"))
        self.assertEqual(self.session("1282690", "0")["WINE_HIDE_AMD_CPU"], "0")


if __name__ == "__main__":
    unittest.main()
