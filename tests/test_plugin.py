"""Behavior tests use real Git and isolated homes; no network or user's Git config."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import github_bot
import git_wrapper


class GitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="github-bot-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "hermes profile"
        self.home.mkdir()
        self.env_file = self.home / ".env"
        self.env_file.write_text('GITHUB_AUTHOR_NAME="Test Bot"\nGITHUB_AUTHOR_EMAIL=bot@example.test\n')
        self.bin = github_bot.wrapper_directory(self.home)
        self.real_git = shutil.which("git")
        self.env = {
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Original Author", "GIT_AUTHOR_EMAIL": "original@example.test",
            "GIT_COMMITTER_NAME": "Original Committer", "GIT_COMMITTER_EMAIL": "committer@example.test",
            "GIT_EDITOR": "true", "GIT_SEQUENCE_EDITOR": "true",
        }
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Configured User")
        self.git("config", "user.email", "configured@example.test")
        self.git("remote", "add", "origin", "git@github.com:example/project.git")

    def git(self, *args, bot=True, check=True, cwd=None, env=None, input=None):
        result = subprocess.run(
            [str(self.bin / "git") if bot else self.real_git, *args],
            cwd=cwd or self.repo, env=env or self.env, text=True, input=input,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if check and result.returncode:
            self.fail(f"git {args} failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        return result

    def commit(self, message="test", bot=True):
        self.git("commit", "--allow-empty", "-m", message, bot=bot)

    def identities(self, ref="HEAD"):
        return self.git("show", "-s", "--format=%an|%ae|%cn|%ce", ref).stdout.strip().split("|")

    def assertBot(self, ref="HEAD"):
        self.assertEqual(self.identities(ref), ["Test Bot", "bot@example.test"] * 2)

    def assertReplay(self):
        self.assertEqual(self.identities(), ["Original Author", "original@example.test", "Test Bot", "bot@example.test"])

    def test_launcher_retains_dependency_path_from_host(self):
        # Model Hermes's managed Python: dependencies exist in the host's
        # sys.path, but are not installed into the bare child interpreter.
        interpreter = self.root / "bare-python"
        interpreter.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -S "$@"\n')
        interpreter.chmod(0o700)
        with patch.object(github_bot.sys, "executable", str(interpreter)):
            github_bot.wrapper_directory(self.home)
        self.commit("bootstrapped dependency")
        self.assertBot()

    def test_commit_amend_and_message_options(self):
        self.commit("--reset-author")
        self.assertBot()
        self.assertEqual(self.git("log", "-1", "--format=%B").stdout.strip(), "--reset-author")
        self.git("commit", "--amend", "--allow-empty", "--no-edit", "--author", "Other <other@example.test>")
        self.assertBot()
        self.git("commit", "--amend", "--allow-empty", "--reset-author", "-m", "--author=literal")
        self.assertBot()
        self.assertEqual(self.git("log", "-1", "--format=%B").stdout.strip(), "--author=literal")
        self.commit("--help")
        self.assertBot()
        self.git("commit", "--allow-empty", "-mcomment", "--reset-author")
        self.assertBot()
        self.assertEqual(self.git("log", "-1", "--format=%B").stdout.strip(), "comment")

    def test_remote_gate_and_missing_identity(self):
        self.env_file.unlink()
        self.assertNotEqual(self.git("commit", "--allow-empty", "-m", "blocked", check=False).returncode, 0)
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD", check=False).returncode, 0)
        self.git("status")
        self.git("remote", "set-url", "origin", "https://github.com.evil.test/owner/repo")
        self.commit()
        self.assertEqual(self.identities()[0], "Original Author")
        self.git("remote", "remove", "origin")
        self.commit("no origin")

    def test_git_c_and_worktree(self):
        self.git("-C", str(self.repo), "commit", "--allow-empty", "-m", "outside", cwd=self.root)
        self.assertBot()
        worktree = self.root / "work tree"
        self.git("worktree", "add", "-b", "work", str(worktree))
        self.git("commit", "--allow-empty", "-m", "worktree", cwd=worktree)
        self.assertEqual(self.git("show", "-s", "--format=%cn", "work").stdout.strip(), "Test Bot")
        self.git("--git-dir", str(self.repo / ".git"), "--work-tree", str(self.repo), "commit", "--allow-empty", "-m", "explicit", cwd=self.root)
        self.assertBot()

    def test_aliases_and_scripts(self):
        self.git("config", "alias.save", "commit --allow-empty")
        self.git("save", "-m", "alias")
        self.assertBot()
        self.git("config", "alias.script", "!git commit --allow-empty")
        self.git("script", "-m", "shell alias")
        self.assertBot()
        self.git("config", "alias.commit", "status")  # Git builtins cannot be shadowed.
        self.commit("builtin")
        self.assertBot()
        subprocess.run(["sh", "-c", 'git commit --allow-empty -m script'], cwd=self.repo, env=self.env, check=True, capture_output=True)
        self.assertBot()

    def test_url_rewrite(self):
        self.git("remote", "set-url", "origin", "short:example/project")
        self.git("config", "url.https://github.com/.insteadOf", "short:")
        self.commit()
        self.assertBot()

    def test_cherry_pick_rebase_and_revert(self):
        self.commit("base")
        self.git("checkout", "-b", "source")
        (self.repo / "source").write_text("source")
        self.git("add", "source")
        self.git("commit", "-m", "original", bot=False)
        source = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "main")
        self.commit("different base")
        self.git("cherry-pick", source)
        self.assertReplay()
        self.git("revert", "--no-edit", "HEAD")
        self.assertBot()
        self.git("checkout", "source")
        (self.repo / "second").write_text("second patch")
        self.git("add", "second")
        self.git("commit", "-m", "second original", bot=False)
        self.git("rebase", "main")
        self.assertReplay()

    def test_merge_stash_notes_and_commit_tree(self):
        self.commit("base")
        self.git("checkout", "-b", "feature")
        self.commit("feature", bot=False)
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "feature", "-m", "merge")
        self.assertBot()
        (self.repo / "tracked").write_text("v1")
        self.git("add", "tracked")
        self.git("commit", "-m", "tracked")
        (self.repo / "tracked").write_text("v2")
        self.git("stash", "push")
        self.assertBot("refs/stash")
        self.git("notes", "add", "-m", "note")
        self.assertBot("refs/notes/commits")
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        commit = self.git("commit-tree", tree, "-p", "HEAD", "-m", "plumbing").stdout.strip()
        self.assertBot(commit)

    def test_am_preserves_patch_author(self):
        self.commit("base")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        (self.repo / "patch").write_text("content")
        self.git("add", "patch")
        self.git("commit", "-m", "patch", bot=False)
        patch_text = self.git("format-patch", "-1", "--stdout").stdout
        self.git("reset", "--hard", base)
        self.git("am", input=patch_text)
        self.assertReplay()

    def test_conflicted_cherry_pick_manual_commit_and_abort_without_identity(self):
        (self.repo / "conflict").write_text("base\n")
        self.git("add", "conflict")
        self.git("commit", "-m", "base")
        self.git("checkout", "-b", "source")
        (self.repo / "conflict").write_text("source\n")
        self.git("commit", "-am", "original", bot=False)
        source = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "main")
        (self.repo / "conflict").write_text("main\n")
        self.git("commit", "-am", "divergent")
        self.assertNotEqual(self.git("cherry-pick", source, check=False).returncode, 0)
        (self.repo / "conflict").write_text("resolved\n")
        self.git("add", "conflict")
        self.git("-C", str(self.repo), "commit", "--no-edit", cwd=self.root)
        self.assertReplay()
        self.git("reset", "--hard", "HEAD^")
        self.git("cherry-pick", source, check=False)
        self.env_file.unlink()
        self.git("cherry-pick", "--abort")
        self.git("status")

    def test_pull_merge_and_rebase_use_existing_ssh_transport(self):
        (self.repo / "base").write_text("base")
        self.git("add", "base")
        self.git("commit", "-m", "base")
        bare = self.root / "upstream.git"
        self.git("init", "--bare", str(bare))
        self.git("push", str(bare), "main")
        upstream = self.root / "upstream-work"
        self.git("clone", "-b", "main", str(bare), str(upstream))
        (upstream / "upstream").write_text("upstream")
        self.git("add", "upstream", cwd=upstream)
        self.git("commit", "-m", "upstream", cwd=upstream, bot=False)
        self.git("push", "origin", "main", cwd=upstream)
        self.commit("local change")
        ssh = self.root / "existing-ssh"
        marker = self.root / "ssh-used"
        ssh.write_text(f"#!/bin/sh\nprintf used > {shlex.quote(str(marker))}\nexec {shlex.quote(self.real_git)} upload-pack {shlex.quote(str(bare))}\n")
        ssh.chmod(0o700)
        env = {**self.env, "GIT_SSH_COMMAND": str(ssh), "GIT_SSH_VARIANT": "ssh"}
        self.git("pull", "--no-rebase", "origin", "main", env=env)
        self.assertBot()
        self.assertTrue(marker.exists())
        # Add independent commits to each side, then replay the locally authored one.
        (upstream / "upstream2").write_text("upstream2")
        self.git("add", "upstream2", cwd=upstream)
        self.git("commit", "-m", "upstream2", cwd=upstream, bot=False)
        self.git("push", "origin", "main", cwd=upstream)
        (self.repo / "local").write_text("local")
        self.git("add", "local")
        self.git("commit", "-m", "local original", bot=False)
        self.git("pull", "--rebase", "origin", "main", env=env)
        self.assertReplay()

    def test_execute_code_subprocess_and_profile_isolation(self):
        code = "import subprocess\nsubprocess.run(['git', 'commit', '--allow-empty', '-m', 'python'], check=True)\n"
        env = {**self.env, "PATH": os.environ["PATH"]}
        result = subprocess.run([sys.executable, "-c", github_bot.python_code(code, self.bin)], cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertBot()
        second = self.root / "second-profile"
        second.mkdir()
        (second / ".env").write_text('GITHUB_AUTHOR_NAME="Second Bot"\nGITHUB_AUTHOR_EMAIL=second@example.test\n')
        second_bin = github_bot.wrapper_directory(second)
        env = {**self.env, "PATH": str(second_bin) + os.pathsep + os.environ["PATH"]}
        subprocess.run([str(second_bin / "git"), "commit", "--allow-empty", "-m", "second"], cwd=self.repo, env=env, check=True, capture_output=True)
        self.assertEqual(self.identities(), ["Second Bot", "second@example.test"] * 2)

    def test_literal_dotenv_and_identity_validation(self):
        marker = self.root / "should-not-exist"
        self.env_file.write_text(f"GITHUB_AUTHOR_NAME='Bot $(touch {marker}) ${{USER}}'\nGITHUB_AUTHOR_EMAIL=bot@example.test\n")
        self.commit()
        self.assertIn("${USER}", self.identities()[0])
        self.assertFalse(marker.exists())
        for name, email in [("", "b@e"), ("Bad <name>", "b@e"), ("Bot", "bad email"), ("Bot\nName", "b@e")]:
            with self.assertRaises(git_wrapper.IdentityError):
                git_wrapper.validate_identity(name, email)

    def test_push_passthrough_environment_and_credentials(self):
        fake = self.root / "fake-bin"
        fake.mkdir()
        record = self.root / "push.json"
        script = fake / "git"
        script.write_text(f"#!{sys.executable}\nimport os,sys,json\nif sys.argv[1:] == ['--list-cmds=builtins']:\n print('push')\nelse:\n open({str(record)!r}, 'w').write(json.dumps([sys.argv[1:],dict(os.environ)]))\n")
        script.chmod(0o700)
        env = {**self.env, "PATH": f"{self.bin}:{fake}", "GH_TOKEN": "existing-token", "GIT_ASKPASS": "/existing/helper", "GIT_SSH_COMMAND": "existing-ssh"}
        self.env_file.unlink()
        self.git("push", "origin", "main", env=env)
        args, actual = json.loads(record.read_text())
        self.assertEqual(args, ["push", "origin", "main"])
        for key in ("HOME", "GH_TOKEN", "GIT_ASKPASS", "GIT_SSH_COMMAND", "GIT_AUTHOR_NAME", "GIT_COMMITTER_EMAIL", "PATH"):
            self.assertEqual(actual[key], env[key])

    def test_local_push_uses_credential_helper_configuration(self):
        # No network: an ext transport inspects credential resolution, then uses
        # receive-pack against a disposable local bare repository.
        self.commit("push")
        bare = self.root / "bare.git"
        self.git("init", "--bare", str(bare))
        helper = self.root / "credential-helper"
        marker = self.root / "credential-used"
        helper.write_text(f"#!/bin/sh\ncat >/dev/null\nprintf called > {str(marker)!r}\nprintf 'username=existing-user\\npassword=existing-password\\n'\n")
        helper.chmod(0o700)
        self.git("config", "credential.helper", str(helper))
        transport = self.root / "transport"
        transport.write_text(f"#!/bin/sh\nprintf 'protocol=https\\nhost=github.com\\n\\n' | {shutil.which('git')} credential fill >/dev/null\nexec {shutil.which('git')} receive-pack {str(bare)!r}\n")
        transport.chmod(0o700)
        self.git("config", "protocol.ext.allow", "always")
        self.git("push", "ext::" + str(transport), "HEAD:refs/heads/main")
        self.assertTrue(marker.exists())
        self.assertEqual(self.git("--git-dir", str(bare), "rev-parse", "main").stdout, self.git("rev-parse", "HEAD").stdout)


class TransformTests(unittest.TestCase):
    def test_shell_cleanup_preserves_path_for_plain_and_pattern_directories(self):
        original = "/home/example/bin:/usr/local/bin:/usr/bin:/bin"
        for path in (
            "/home/example/.hermes/cache/hermes-github-bot/bin",
            "/home/example/[profile]*/bin",
        ):
            with self.subTest(path=path):
                command = github_bot.shell_command("true", Path(path))
                result = subprocess.run(
                    ["/bin/bash", "-c", command + '\nprintf "%s" "$PATH"'],
                    env={"PATH": original}, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, original)

    def test_shell_state_status_and_background(self):
        with tempfile.TemporaryDirectory(prefix="github bot '") as temporary:
            directory = Path(temporary) / "bin"
            directory.mkdir()
            command = f"cd {shlex.quote(temporary)}\nexport SAVED=yes\nexport PATH=\"$PATH:/new\"\nfalse # final comment"
            transformed = github_bot.shell_command(command, directory)
            result = subprocess.run(["bash", "-c", transformed + '\nresult=$?; printf "%s|%s|%s|%s" "$result" "$SAVED" "$PWD" "$PATH"'], text=True, capture_output=True)
            self.assertTrue(result.stdout.startswith(f"1|yes|{temporary}|"), result)
            self.assertNotIn(str(directory), result.stdout)
            self.assertTrue(result.stdout.endswith(":/new"))
            child = github_bot.shell_command('sh -c \'printf "%s" "$PATH"\' &\nwait', directory)
            result = subprocess.run(["bash", "-c", child], capture_output=True, text=True)
            self.assertIn(str(directory), result.stdout)
            malformed = github_bot.shell_command("echo (", directory)
            result = subprocess.run(["bash", "-c", malformed + '\nprintf "%s" "$PATH"'], capture_output=True, text=True)
            self.assertNotIn(str(directory), result.stdout)

    def test_python_future_multiline_strings_globals_and_failure_cleanup(self):
        directory = Path("/tmp/github bot/bin")
        code = '"""doc"""\nfrom __future__ import annotations\ntext = """one\ntwo"""\ndef f(x: Missing): return x\n'
        namespace = {}
        before = os.environ.get("PATH")
        exec(github_bot.python_code(code, directory), namespace)
        self.assertEqual(namespace["text"], "one\ntwo")
        self.assertEqual(namespace["f"].__annotations__, {"x": "Missing"})
        self.assertEqual(os.environ.get("PATH"), before)
        with self.assertRaises(RuntimeError):
            exec(github_bot.python_code("raise RuntimeError('failure')", directory), namespace)
        self.assertEqual(os.environ.get("PATH"), before)

    def test_url_matching(self):
        for value in ["git@github.com:a/b", "ssh://git@github.com:22/a/b", "https://github.com/a/b", "git://github.com/a/b"]:
            self.assertTrue(git_wrapper.github_url(value), value)
        for value in ["https://github.com.evil/a", "https://github.com@evil/a", "git@github-work:a/b", "/tmp/github.com:a", "file://github.com/a"]:
            self.assertFalse(git_wrapper.github_url(value), value)


if __name__ == "__main__":
    unittest.main()
