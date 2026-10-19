"""Optional real Hermes integration: set HERMES_SOURCE to a compatible checkout."""

import argparse
import contextlib
import importlib.util
import io
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
        from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
        with tempfile.TemporaryDirectory() as temporary:
            homes = [Path(temporary) / "one", Path(temporary) / "two"]
            token = set_hermes_home_override(homes[0])
            try:
                manager = PluginManager()
                ctx = PluginContext(PluginManifest(name="context-test", key="effective-test-id"), manager)
                self.plugin.register(ctx)
                callback = manager._middleware["tool_request"][0]
                cli = manager._cli_commands["github-bot-commit"]["handler_fn"]
                for index, home in enumerate(homes):
                    profile = set_hermes_home_override(home)
                    try:
                        ctx.set_config("unrelated", {"keep": True})
                        with contextlib.redirect_stdout(io.StringIO()), patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, '{"id":123456}')) as lookup:
                            self.assertEqual(cli(argparse.Namespace(action="setup", app_slug=f"cli-app-{index}")), 0)
                        lookup.assert_called_once()
                        self.assertEqual(ctx.get_config("identity"), {"app_slug": f"cli-app-{index}", "bot_id": "123456"})
                        self.assertEqual(ctx.get_config("unrelated"), {"keep": True})
                        transformed = callback(tool_name="terminal", args={"command": "git --version", "timeout": 42})
                        self.assertEqual(transformed["args"]["timeout"], 42)
                        result = subprocess.run(["bash", "-c", transformed["args"]["command"]], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertTrue(result.stdout.startswith("git version"))
                        launcher = home / "cache" / "hermes-github-bot-commit" / "bin" / "git"
                        original = launcher.read_text()
                        self.assertIn(f"cli-app-{index}", original)
                        # Git calls hidden inside scripts, Make recipes, quoted
                        # commands, or dynamically chosen executables still activate.
                        for command in ("./release.sh", "make release", "$(printf git) status", "(git status)"):
                            with self.subTest(command=command):
                                self.assertIsNotNone(callback(tool_name="terminal", args={"command": command}))
                        self.assertEqual(launcher.read_text(), original)
                        ctx.set_config("identity", {"app_slug": "changed-app", "bot_id": "789"})
                        callback(tool_name="execute_code", args={"code": "pass"})
                        self.assertIn("changed-app", launcher.read_text())
                        for invalid in (None, {"app_slug": "invalid", "bot_id": True}):
                            if invalid is None:
                                # Host set_config(None) currently preserves existing values;
                                # simulate a Desktop/direct removal in this disposable home.
                                import yaml
                                config = yaml.safe_load((home / "config.yaml").read_text())
                                del config["plugins"]["entries"][ctx.plugin_id]["settings"]["identity"]
                                (home / "config.yaml").write_text(yaml.safe_dump(config))
                            else:
                                ctx.set_config("identity", invalid)
                            self.assertIsNotNone(callback(tool_name="terminal", args={"command": "git status"}))
                            self.assertNotIn("changed-app", launcher.read_text())
                        self.assertIsNone(callback(tool_name="read_file", args={"path": "x"}))
                        import yaml
                        config = yaml.safe_load((home / "config.yaml").read_text())
                        config["terminal"] = {"backend": "docker"}
                        (home / "config.yaml").write_text(yaml.safe_dump(config))
                        self.assertIsNone(callback(tool_name="terminal", args={"command": "git status"}))
                    finally:
                        reset_hermes_home_override(profile)
                # Disabling unloads callbacks for subsequent calls; published launchers
                # intentionally remain available to already-running background jobs.
                self.assertTrue(manager.unload(ctx.plugin_id))
                self.assertFalse(manager._middleware.get("tool_request"))
                self.assertNotIn("github-bot-commit", manager._cli_commands)
                self.assertTrue((homes[0] / "cache" / "hermes-github-bot-commit" / "bin" / "git").exists())
            finally:
                reset_hermes_home_override(token)
