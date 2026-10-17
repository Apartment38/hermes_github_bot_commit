"""Setup lookup tests with isolated configuration and mocked GitHub responses."""

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "setup_test_plugin", ROOT / "github_bot.py",
    submodule_search_locations=[str(ROOT)],
)
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class SetupTests(unittest.TestCase):
    def run_setup(self, slug, response=None, error=None):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("UNRELATED=keep\n")
            saved = []

            def save(key, value):
                saved.append((key, value))
                with path.open("a") as stream:
                    stream.write(f"{key}={value}\n")

            config = types.ModuleType("hermes_cli.config")
            config.save_env_value = save
            constants = types.ModuleType("hermes_constants")
            constants.get_env_path = lambda: path
            with patch.dict(sys.modules, {"hermes_cli.config": config, "hermes_constants": constants}), patch("builtins.input", return_value=slug) as prompt, patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, response), side_effect=error) as lookup:
                result = plugin.cli(argparse.Namespace(action="setup"))
            self.assertEqual(prompt.call_count, 1)
            return result, saved, lookup, path.read_text()

    def test_slug_only_setup(self):
        result, saved, lookup, content = self.run_setup("example-app", '{"id":123456}')
        self.assertEqual(result, 0)
        self.assertEqual(saved, [("GITHUB_APP_SLUG", "example-app"), ("GITHUB_BOT_ID", "123456")])
        self.assertIn("UNRELATED=keep", content)
        self.assertEqual(lookup.call_args.args[0], ["curl", "-fsSL", "--max-time", "30", "https://api.github.com/users/example-app%5Bbot%5D"])

    def test_lookup_failures_do_not_save(self):
        for response in ["not json", "{}", "[]", '{"id":null}', '{"id":true}', '{"id":0}', '{"id":"123"}']:
            with self.subTest(response=response):
                result, saved, _, content = self.run_setup("example-app", response)
                self.assertEqual(result, 1)
                self.assertEqual(saved, [])
                self.assertEqual(content, "UNRELATED=keep\n")
        for error in [FileNotFoundError("curl"), subprocess.CalledProcessError(22, "curl"), subprocess.TimeoutExpired("curl", 35)]:
            with self.subTest(error=error):
                result, saved, _, _ = self.run_setup("example-app", error=error)
                self.assertEqual(result, 1)
                self.assertEqual(saved, [])

    def test_invalid_slug_never_queries_github(self):
        result, saved, lookup, _ = self.run_setup("bad/slug")
        self.assertEqual(result, 1)
        self.assertEqual(saved, [])
        lookup.assert_not_called()
