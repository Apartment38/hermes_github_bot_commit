"""Git identity policy. This process never imports Hermes or changes Git config."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

from dotenv import dotenv_values

COMMIT_VALUE_OPTIONS = {
    "-m", "-F", "-C", "-c", "-t", "--message", "--file", "--reuse-message",
    "--reedit-message", "--template", "--fixup", "--squash", "--cleanup", "--date",
    "--pathspec-from-file", "--trailer",
}


def takes_commit_value(arg: str) -> bool:
    if arg in COMMIT_VALUE_OPTIONS:
        return True
    if arg.startswith("-") and not arg.startswith("--"):
        short = arg[1:]
        for index, flag in enumerate(short):
            if flag in "mFCct":
                return index == len(short) - 1
            if flag == "S":  # Optional signing key consumes the rest of this token.
                return False
    return False


class IdentityError(ValueError):
    """Configuration cannot safely represent a Git identity."""


def validate_identity(name: str | None, email: str | None) -> tuple[str, str]:
    for key, value in (("GITHUB_AUTHOR_NAME", name), ("GITHUB_AUTHOR_EMAIL", email)):
        if (not value or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)
                or "<" in value or ">" in value or (key.endswith("EMAIL") and any(c.isspace() for c in value))):
            raise IdentityError(f"github-bot: set a valid {key} in the active Hermes .env; run hermes github-bot setup")
    return name, email


def load_identity(path: Path) -> tuple[str, str]:
    try:
        # No variable interpolation or shell evaluation. Other .env values stay out
        # of the Git subprocess, including authentication/provider credentials.
        values = dotenv_values(path, interpolate=False)
    except (OSError, UnicodeError) as exc:
        raise IdentityError("github-bot: cannot read the active Hermes .env") from exc
    return validate_identity(values.get("GITHUB_AUTHOR_NAME"), values.get("GITHUB_AUTHOR_EMAIL"))


def github_url(value: str) -> bool:
    if "://" in value:
        try:
            parsed = urlsplit(value)
            return parsed.scheme in {"https", "http", "ssh", "git"} and parsed.hostname == "github.com"
        except ValueError:
            return False
    match = re.fullmatch(r"(?:[^/@:]+@)?([^/:]+):(.+)", value)
    return bool(match and match[1].lower() == "github.com")


def split_command(argv: list[str]) -> tuple[list[str], str, list[str]]:
    """Retain repository/config options when running read-only policy probes."""
    index = 0
    paired = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"}
    while index < len(argv):
        arg = argv[index]
        if not arg.startswith("-") or arg == "-":
            return argv[:index], arg, argv[index + 1:]
        if arg in {"--help", "--version", "--list-cmds"}:
            return argv, "", []
        index += 2 if arg in paired else 1
    return argv, "", []


def probe(git: str, options: list[str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [git, *options, *args], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        encoding="utf-8", errors="replace", timeout=10,
    )


def resolve_alias(git: str, argv: list[str], wrapper_dir: Path) -> list[str]:
    """Expand ordinary aliases; retain Git's own shell-alias cwd/config semantics."""
    seen = set()
    builtins = set(probe(git, [], "--list-cmds=builtins").stdout.split())
    for _ in range(20):
        options, command, rest = split_command(argv)
        if not command or command in seen or command in builtins:
            return argv
        seen.add(command)
        result = probe(git, options, "config", "--get", f"alias.{command}")
        if result.returncode:
            return argv
        alias = result.stdout.rstrip("\n")
        if alias.startswith("!"):
            # Git prepends its exec-path (which can contain another git binary)
            # before shell aliases. Restore our wrapper for nested Git invocations.
            body = f'!export PATH={shlex.quote(str(wrapper_dir))}:"$PATH"; ' + alias[1:]
            return [*options, "-c", f"alias.{command}={body}", command, *rest]
        argv = [*options, *shlex.split(alias), *rest]
    raise IdentityError("github-bot: Git alias nesting exceeds 20 levels")


def creates_commits(command: str, args: list[str]) -> bool:
    flags = []
    index = 0
    while index < len(args) and args[index] != "--":
        flags.append(args[index])
        index += 2 if takes_commit_value(args[index]) else 1
    if "--help" in flags or "-h" in flags or "--dry-run" in flags:
        return False
    if any(flag in flags for flag in ("--abort", "--quit")):
        return False
    if command == "stash":
        return not args or args[0].startswith("-") or args[0] in {"push", "save", "create"}
    if command == "notes":
        return any(arg in {"add", "append", "copy", "edit", "merge", "prune", "remove"} for arg in args)
    return command in {"commit", "merge", "pull", "rebase", "cherry-pick", "revert", "am", "commit-tree"}


def replay_in_progress(git: str, options: list[str]) -> bool:
    for item in ("CHERRY_PICK_HEAD", "rebase-merge", "rebase-apply"):
        result = probe(git, options, "rev-parse", "--path-format=absolute", "--git-path", item)
        if not result.returncode and Path(result.stdout.rstrip("\n")).exists():
            return True
    return False


def commit_author(args: list[str], name: str, email: str) -> list[str]:
    """Override author options before the pathspec separator, preserving messages."""
    result = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            break
        if arg == "--author":
            index += 2
            continue
        if takes_commit_value(arg):
            result.extend(args[index:index + 2])
            index += 2
            continue
        if not arg.startswith("--author=") and arg != "--reset-author":
            result.append(arg)
        index += 1
    return [*result, f"--author={name} <{email}>", *args[index:]]


def invocation(git: str, argv: list[str], env_file: Path, wrapper_dir: Path) -> tuple[list[str], dict[str, str]]:
    if split_command(argv)[1] == "push":
        return argv, os.environ.copy()
    argv = resolve_alias(git, argv, wrapper_dir)
    options, command, args = split_command(argv)
    env = os.environ.copy()
    if not creates_commits(command, args):
        return argv, env
    origin = probe(git, options, "remote", "get-url", "origin")
    if origin.returncode or not github_url(origin.stdout.strip()):
        return argv, env
    name, email = load_identity(env_file)
    env.update(GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)
    replay = command in {"rebase", "cherry-pick", "am"} or (
        command == "commit" and replay_in_progress(git, options)
    )
    if not replay:
        env.update(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email)
        if command == "commit":
            argv = [*options, command, *commit_author(args, name, email)]
    return argv, env


def main():
    if len(sys.argv) < 4 or sys.argv[1] != "--env-file" or sys.argv[3] != "--":
        print("github-bot: invalid wrapper invocation", file=sys.stderr)
        return 128
    env_file = Path(sys.argv[2])
    wrapper_dir = env_file.parent / "cache" / "hermes-github-bot" / "bin"
    search_path = os.pathsep.join(
        p for p in os.get_exec_path() if Path(p or ".").resolve() != wrapper_dir.resolve()
    )
    git = shutil.which("git", path=search_path)
    if not git:
        print("github-bot: cannot find the original git executable", file=sys.stderr)
        return 127
    try:
        argv, env = invocation(git, sys.argv[4:], env_file, wrapper_dir)
    except (IdentityError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 128
    os.execve(git, [git, *argv], env)


if __name__ == "__main__":
    raise SystemExit(main())
