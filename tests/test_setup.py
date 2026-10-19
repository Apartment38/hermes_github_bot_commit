"""Setup/configuration tests using only the public context contract."""

import argparse
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "setup_test_plugin", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)],
)
entry = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = entry
spec.loader.exec_module(entry)
plugin = sys.modules[spec.name + ".github_bot"]


class Context:
    plugin_id = "effective-test-id"

    def __init__(self, identity=None):
        self.settings = {"unrelated": "keep", "identity": identity}
        self.reads = []
        self.saved = []

    def get_config(self, key, default=None):
        self.reads.append(key)
        return self.settings.get(key, default)

    def set_config(self, key, value):
        self.saved.append((key, value))
        self.settings[key] = value

    def register_middleware(self, kind, callback):
        self.middleware = callback

    def register_cli_command(self, name, help, setup, callback):
        self.cli = callback


class SetupTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        import types
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: Path(temporary.name)
        modules = patch.dict(sys.modules, {"hermes_constants": constants})
        modules.start()
        self.addCleanup(modules.stop)

    def test_registration_is_lazy_and_callbacks_keep_separate_contexts(self):
        first = Context({"app_slug": "first", "bot_id": "1", "secret": "never-copy"})
        second = Context({"app_slug": "second", "bot_id": "2"})
        with patch.object(plugin, "wrapper_directory") as publish, patch("subprocess.run") as network:
            entry.register(first)
            entry.register(second)
            self.assertEqual(first.reads + second.reads, [])
            publish.assert_not_called()
            network.assert_not_called()
        for ctx, name in ((first, "first[bot]"), (second, "second[bot]")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(ctx.cli(argparse.Namespace(action="status")), 0)
            self.assertIn(name, output.getvalue())
            self.assertEqual(ctx.reads, ["identity"])
            self.assertFalse(ctx.saved)
        self.assertEqual(plugin.read_identity(first), {"app_slug": "first", "bot_id": "1"})

    def run_setup(self, slug, response=None, error=None):
        ctx = Context()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, response), side_effect=error) as lookup:
            result = plugin.cli(ctx, argparse.Namespace(action="setup", app_slug=slug))
        return result, ctx, lookup

    def test_slug_only_setup(self):
        result, ctx, lookup = self.run_setup("example-app", '{"id":123456}')
        self.assertEqual(result, 0)
        self.assertEqual(ctx.saved, [("identity", {"app_slug": "example-app", "bot_id": "123456"})])
        self.assertEqual(ctx.settings["unrelated"], "keep")
        self.assertEqual(lookup.call_args.args[0], ["curl", "-fsSL", "--max-time", "30", "https://api.github.com/users/example-app%5Bbot%5D"])

    def test_lookup_failures_do_not_save(self):
        for response in ["not json", "{}", "[]", '{"id":null}', '{"id":true}', '{"id":0}', '{"id":-1}', '{"id":1.5}', '{"id":"123"}']:
            with self.subTest(response=response):
                result, ctx, _ = self.run_setup("example-app", response)
                self.assertEqual(result, 1)
                self.assertEqual(ctx.saved, [])
        for error in [FileNotFoundError("curl"), subprocess.CalledProcessError(22, "curl"), subprocess.TimeoutExpired("curl", 35)]:
            with self.subTest(error=error):
                result, ctx, _ = self.run_setup("example-app", error=error)
                self.assertEqual(result, 1)
                self.assertEqual(ctx.saved, [])

    def test_invalid_slug_never_queries_github(self):
        for slug in ("bad/slug", " example-app ", ""):
            result, ctx, lookup = self.run_setup(slug)
            self.assertEqual(result, 1)
            self.assertEqual(ctx.saved, [])
            lookup.assert_not_called()

    def test_interactive_requires_tty_and_handles_cancel(self):
        for tty, error in ((False, None), (True, EOFError()), (True, KeyboardInterrupt())):
            ctx = Context()
            with patch.object(sys.stdin, "isatty", return_value=tty), patch("builtins.input", side_effect=error) as prompt, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(plugin.cli(ctx, argparse.Namespace(action="setup", app_slug=None)), 1)
            if not tty:
                prompt.assert_not_called()
            self.assertFalse(ctx.saved)
        parser = argparse.ArgumentParser()
        plugin.setup_parser(parser)
        self.assertEqual(parser.parse_args(["setup", "--app-slug", "example-app"]).app_slug, "example-app")
        with patch.object(sys.stdin, "isatty", return_value=True), patch("builtins.input", return_value="example-app"), patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, '{"id":1}')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(plugin.cli(Context(), argparse.Namespace(action="setup", app_slug=None)), 0)

    def test_status_missing_malformed_or_valid_is_read_only(self):
        for identity in (None, [], {}, {"app_slug":"app", "bot_id":True}, {"app_slug":"app", "bot_id":"1"}):
            ctx = Context(identity)
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                result = plugin.cli(ctx, argparse.Namespace(action="status"))
            self.assertEqual(result, 0 if identity == {"app_slug":"app", "bot_id":"1"} else 1)
            self.assertEqual(ctx.reads, ["identity"])
            self.assertFalse(ctx.saved)
            self.assertNotIn(".env", out.getvalue() + err.getvalue())
            if result == 0:
                self.assertIn("plugins.entries.effective-test-id.settings.identity", out.getvalue())
                self.assertIn("1+app[bot]@users.noreply.github.com", out.getvalue())

    def test_configuration_errors_have_distinct_diagnostics(self):
        for operation, action, expected in (("get_config", "status", "configuration read failed"), ("set_config", "setup", "configuration write failed")):
            ctx = Context()
            with patch.object(ctx, operation, side_effect=OSError("denied")), patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, '{"id":1}')), contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(plugin.cli(ctx, argparse.Namespace(action=action, app_slug="app")), 1)
            self.assertIn(expected, err.getvalue())

    def test_setup_refreshes_only_existing_launcher_and_reports_publication_failure(self):
        import tempfile
        import types
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            constants = types.ModuleType("hermes_constants")
            constants.get_hermes_home = lambda: home
            ctx = Context()
            with patch.dict(sys.modules, {"hermes_constants": constants}), patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, '{"id":1}')), contextlib.redirect_stdout(io.StringIO()), patch.object(plugin, "wrapper_directory") as publish:
                self.assertEqual(plugin.cli(ctx, argparse.Namespace(action="setup", app_slug="app")), 0)
                publish.assert_not_called()
                launcher = home / "cache" / "hermes-github-bot-commit" / "bin" / "git"
                launcher.parent.mkdir(parents=True)
                launcher.write_text("old")
                self.assertEqual(plugin.cli(ctx, argparse.Namespace(action="setup", app_slug="app")), 0)
                publish.assert_called_once_with(home, {"app_slug": "app", "bot_id": "1"})
                publish.side_effect = OSError("read-only launcher")
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(plugin.cli(ctx, argparse.Namespace(action="setup", app_slug="new-app")), 1)
                self.assertIn("settings saved", err.getvalue())
                self.assertIn("launcher refresh failed", err.getvalue())
                self.assertEqual(ctx.settings["identity"]["app_slug"], "new-app")
