"""Hermes integration; Git policy lives in the independently executable git_wrapper.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import sys
import uuid


def wrapper_directory(home: Path) -> Path:
    """Publish a profile-specific launcher, without embedding any identity values."""
    directory = home / "cache" / "hermes-github-bot-commit" / "bin"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    helper = Path(__file__).with_name("git_wrapper.py").resolve()
    # Hermes can bootstrap managed dependencies into sys.path without using a
    # venv executable. Bare sys.executable children do not inherit that path.
    import dotenv
    dependency_root = str(Path(dotenv.__file__).resolve().parent.parent)
    bootstrap = (
        f"import sys; sys.path.insert(0, {dependency_root!r}); "
        "import runpy; helper = sys.argv.pop(1); "
        "runpy.run_path(helper, run_name='__main__')"
    )
    content = (
        "#!/bin/sh\nexec "
        + " ".join(shlex.quote(x) for x in (
            sys.executable, "-c", bootstrap, str(helper), "--env-file", str(home / ".env"), "--"
        ))
        + ' "$@"'
        + "\n"
    )
    target = directory / "git"
    if not target.exists() or target.read_text() != content:
        temporary = directory / f".git-{uuid.uuid4().hex}"
        try:
            temporary.write_text(content)
            temporary.chmod(0o700)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return directory


def shell_command(command: str, directory: Path) -> str:
    """Keep execution in the current shell so cwd and exported variables persist.

    Hermes only snapshots the environment after the command returns. An explicit
    exit/exec or errexit terminates that shell before its snapshot, so it cannot
    persist our temporary PATH. Background children inherit the active wrapper.
    """
    status = "_github_bot_status_" + uuid.uuid4().hex
    path = "_github_bot_path_" + uuid.uuid4().hex
    quoted = shlex.quote(str(directory))
    # Evaluate separately so a user syntax error returns to our cleanup rather
    # than leaving the wrapper PATH in Hermes's persistent shell snapshot.
    return (
        f"export PATH={quoted}:\"$PATH\"\n"
        + "eval " + shlex.quote(command)
        + f"\n{status}=$?\n"
        + f'{path}={quoted}\n'
        + f'PATH=${{PATH//"${path}":/}}\nPATH=${{PATH%:/"${path}"}}\nexport PATH\n'
        + f'eval "unset {status} {path}; (exit ${{{status}}})"\n'
    )


def python_code(code: str, directory: Path) -> str:
    """Execute the original module verbatim with temporary subprocess PATH.

    execute_code kernels can persist between calls: a finally block must remove
    our path even when user code raises. Keep top-level names in the same scope.
    """
    name = "_github_bot_os_" + uuid.uuid4().hex
    path = str(directory)
    return (
        f"import os as {name}\n"
        + f"{name}.environ['PATH'] = {path!r} + ':' + {name}.environ.get('PATH', '')\n"
        + f"try:\n    exec(compile({code!r}, '<github-bot-commit execute_code>', 'exec', dont_inherit=True), globals())"
        + "\nfinally:\n"
        + f"    {name}.environ['PATH'] = ':'.join(p for p in {name}.environ.get('PATH', '').split(':') if p != {path!r})\n"
        + f"    del {name}\n"
    )


def middleware(tool_name=None, args=None, **kwargs):
    if tool_name not in {"terminal", "execute_code"} or not isinstance(args, dict):
        return None
    from hermes_cli.config import cfg_get, read_raw_config_readonly
    from hermes_constants import get_hermes_home

    backend = cfg_get(
        read_raw_config_readonly(), "terminal", "backend",
        default=os.environ.get("TERMINAL_ENV", "local"),
    )
    if backend != "local" or sys.platform not in {"linux", "darwin"}:
        return None
    key = "command" if tool_name == "terminal" else "code"
    if not isinstance(args.get(key), str):
        return None
    directory = wrapper_directory(Path(get_hermes_home()))
    transform = shell_command if key == "command" else python_code
    return {
        "args": {**args, key: transform(args[key], directory)},
        "source": "hermes-github-bot-commit",
        "reason": "Apply GitHub commit identity in the local harness",
    }


def setup_parser(parser):
    parser.add_argument("action", choices=["setup", "status"])


def cli(args):
    from hermes_constants import get_env_path
    from .git_wrapper import IdentityError, load_identity, validate_identity

    if args.action == "setup":
        from hermes_cli.config import save_env_value
        import subprocess

        slug = input("GitHub App slug: ").strip()
        try:
            validate_identity(slug, "1")
            response = subprocess.run(
                ["curl", "-fsSL", "--max-time", "30",
                 f"https://api.github.com/users/{slug}%5Bbot%5D"],
                check=True, capture_output=True, text=True, timeout=35,
            )
            # Parse .id directly, without requiring a separate jq installation.
            payload = json.loads(response.stdout)
            bot_id = payload.get("id") if isinstance(payload, dict) else None
            if type(bot_id) is not int or bot_id <= 0:
                raise IdentityError("github-bot-commit: GitHub returned no valid bot ID")
            bot_id = str(bot_id)
            validate_identity(slug, bot_id)
        except (IdentityError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"github-bot-commit: setup failed: {exc}", file=sys.stderr)
            return 1
        save_env_value("GITHUB_APP_SLUG", slug)
        save_env_value("GITHUB_BOT_ID", bot_id)
    try:
        name, email = load_identity(get_env_path())
    except IdentityError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"env_file": str(get_env_path()), "name": name, "email": email}))
    return 0
