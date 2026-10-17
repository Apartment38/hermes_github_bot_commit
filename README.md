# Hermes GitHub Bot Identity

A native Hermes plugin that applies a bot identity to commits in repositories
whose effective `origin` fetch URL points to **github.com**. It runs in the
harness, with no added prompts, skills, or model-facing tools.

It changes commit metadata, not GitHub authentication. Pushes continue to use
the credentials and configuration Hermes normally supplies to Git. The bot
account must already exist; use an email associated with that account (including
its GitHub-provided noreply address) for GitHub attribution.

## Requirements

- Linux or macOS, Hermes's **local** terminal backend, and Git 2.31 or later.
- A current Hermes release supporting native `tool_request` middleware,
  `register_cli_command`, and profile-aware configuration helpers. The implementation
  was checked against Hermes checkout `d923a5eb487` (October 17, 2026).
- Python 3.11 or later and `python-dotenv>=1.0,<2` in Hermes's runtime. The manifest
  declares this dependency for Hermes's plugin dependency manager.

## Install and configure

Copy this directory into the **active Hermes profile's** plugin directory,
for example `$HERMES_HOME/plugins/hermes-github-bot` (default
`~/.hermes/plugins/hermes-github-bot`). For a source checkout:

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/plugins/hermes-github-bot"
cp __init__.py github_bot.py git_wrapper.py plugin.yaml README.md \
  "${HERMES_HOME:-$HOME/.hermes}/plugins/hermes-github-bot/"
hermes plugins enable hermes-github-bot
hermes github-bot setup
hermes github-bot status
```

Use the same profile for installation, setup, and your Hermes session. Once this
repository is published, it can also be installed with Hermes's normal
`hermes plugins install owner/repository` workflow. Follow any dependency
preparation instructions Hermes displays; do not install into its managed
runtime with raw pip.

`setup` validates both values before saving them using Hermes's `.env` writer:

```dotenv
GITHUB_AUTHOR_NAME="Example Bot"
GITHUB_AUTHOR_EMAIL="123456+example-bot@users.noreply.github.com"
```

You may also edit these two entries yourself. They are read afresh for each
qualifying Git invocation; other `.env` values are never forwarded by this
plugin. Shell substitution and `${VARIABLE}` interpolation are disabled when
reading identity values. Bot credentials or tokens are unnecessary.

## Behavior

The plugin temporarily activates a profile-specific Git wrapper for `terminal`
and `execute_code`. Scripts and subprocesses using ordinary `git` resolution
inherit it, including terminal calls by delegated Hermes subagents. The wrapper
checks the repository at invocation time, so `cd`, `git -C`, worktrees,
`--git-dir`, and `--work-tree` select the correct repository.

- Normal commits and amendments use the bot as both author and committer.
  Conflicting `--author` and `--reset-author` options are overridden.
- Rebase, cherry-pick, and `am` preserve Git's original-author behavior, using
  the bot as committer. A manual `git commit` inside an active replay likewise
  lets Git preserve the original author. Explicit replay options that reset
  authorship keep their usual Git meaning.
- Merge/pull, revert, stash creation, notes mutations, and `commit-tree` receive
  the appropriate bot identity. Fast-forwards create no new commit objects.
- HTTPS/HTTP, SSH, SCP-style, and Git-protocol URLs match the exact hostname
  `github.com`. Git's `insteadOf` URL rewrites are honored. An SSH alias such as
  `git@github-work:owner/repo` is not matched unless Git rewrites it to github.com.
  The fetch URL of `origin`, rather than a push-only URL or another remote, is
  the gate. GitHub Enterprise hosts are not included.
- Missing/invalid identity blocks qualifying GitHub operations with a setup
  error. Read-only commands, abort/quit operations, non-GitHub repositories,
  repositories without `origin`, and pushes still work.

For ordinary `git commit`, the wrapper executes the argument/environment
equivalent of:

```bash
GIT_COMMITTER_NAME="$GITHUB_AUTHOR_NAME" \
GIT_COMMITTER_EMAIL="$GITHUB_AUTHOR_EMAIL" \
git commit --author="$GITHUB_AUTHOR_NAME <$GITHUB_AUTHOR_EMAIL>" -m "$MESSAGE"
```

Arguments are passed directly to Git; commit messages are never reconstructed
or evaluated by a shell. Existing message files, hooks, signing options, Git
configuration, `HOME`, SSH configuration, credential helpers, and tokens remain
under the user's control. The plugin writes no repository or global Git config.

The temporary launcher lives in the active profile's
`cache/hermes-github-bot/bin/`. It contains only interpreter, plugin, and `.env`
paths. Foreground tool execution removes the wrapper path afterward while
preserving cwd, exported variables, and command exit status. Background children
retain their launch environment and finish with the policy they started with.
Disabling the plugin affects subsequent calls, not existing background jobs.

## Boundaries

This is automatic handling of standard Git CLI workflows, **not a security
boundary**. Hermes middleware exceptions are fail-open. If the plugin fails to
load, is disabled, or middleware itself fails, Hermes can run its normal path.
Configuration failures detected inside the activated wrapper do block Git.

Absolute Git paths, `PATH` replacement, `sudo`, clean/login environments that
discard the wrapper, Git libraries (libgit2/Dulwich), and bulk history imports
(`fast-import`, `filter-branch`, `filter-repo`) are outside scope. External tools
that create commits through an API are also outside scope. Git hooks/internal
helpers inherit the active Git operation's environment; commits they create in
other repositories are outside the per-invocation wrapper guarantee. No remote
terminal backend or Windows support is claimed.

## Verification

The test suite uses disposable repositories and homes, with no GitHub network
access and no writes to the user's Hermes configuration:

```bash
python -m unittest discover -s tests -v
HERMES_SOURCE=/path/to/hermes-agent python -m unittest discover -s tests -v
hermes plugins doctor . --ci
hermes plugins validate .
```

Run the last two commands with an isolated `HERMES_HOME`. For standalone tests,
install `python-dotenv>=1.0,<2` in your own test environment. CI tests Python 3.11
and 3.14 on Linux and macOS. `HERMES_SOURCE` enables the optional integration
checks against an existing Hermes checkout; they otherwise report as skipped.

Relevant Hermes contracts: [native plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins),
[middleware](https://hermes-agent.nousresearch.com/docs/developer-guide/middleware),
and [local credentials](https://hermes-agent.nousresearch.com/docs/user-guide/configuration#local-backend).
