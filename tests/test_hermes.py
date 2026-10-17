"""Optional real Hermes integration: set HERMES_SOURCE to a compatible checkout."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("HERMES_SOURCE"), "set HERMES_SOURCE for Hermes integration")
class HermesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.environ["HERMES_SOURCE"])
        spec = importlib.util.spec_from_file_location("tested_github_plugin", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
        cls.plugin = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.plugin
        spec.loader.exec_module(cls.plugin)

    def test_runtime_discovery_and_catalog_validation(self):
        from hermes_cli.plugin_dev import doctor_plugin
        from hermes_cli.plugin_validate import validate_plugin_dir
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HERMES_HOME": home}):
            doctor = doctor_plugin(ROOT)
            self.assertTrue(doctor.ok, doctor.format_text())
            self.assertFalse(doctor.findings, doctor.format_text())
            report = validate_plugin_dir(ROOT)
            self.assertTrue(report.ok, report.to_dict())
            self.assertFalse(report.warnings, report.to_dict())

    def test_setup_updates_only_identity_and_middleware_obeys_profiles_and_backend(self):
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        import argparse
        # Bind through the same public context override the multiplex gateway uses.
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / ".env").write_text("UNRELATED=keep-this\n")
            token = set_hermes_home_override(home)
            self.addCleanup(reset_hermes_home_override, token)
            with patch("builtins.input", side_effect=["CLI Bot", "cli@example.test"]):
                self.assertEqual(self.plugin.github_bot.cli(argparse.Namespace(action="setup")), 0)
                self.assertIn("UNRELATED=keep-this", (home / ".env").read_text())
                (home / "config.yaml").write_text("terminal:\n  backend: local\n")
                transformed = self.plugin.github_bot.middleware(tool_name="terminal", args={"command": "git --version", "timeout": 42})
                self.assertEqual(transformed["args"]["timeout"], 42)
                result = subprocess.run(["bash", "-c", transformed["args"]["command"]], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith("git version"))
                self.assertIsNone(self.plugin.github_bot.middleware(tool_name="read_file", args={"path": "x"}))
                (home / "config.yaml").write_text("terminal:\n  backend: docker\n")
                self.assertIsNone(self.plugin.github_bot.middleware(tool_name="terminal", args={"command": "git status"}))
