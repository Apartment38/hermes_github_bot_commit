<p align="center">
    <img src="Engraved_Hermes_Commit_Seal.png"
</p>

# Hermes GitHub Bot Commit Plugin

A native Hermes plugin that applies a bot identity to commits in repositories
whose effective `origin` fetch URL points to **github.com**. It runs in the
harness, with no added prompts, skills, or model-facing tools.

It changes commit metadata, not GitHub authentication. Pushes continue to use
the credentials and configuration Hermes normally supplies to Git. The bot
account must already exist; setup derives its GitHub noreply address automatically.

## Workflow

Once the plugin is installed & configured, hermes should automatically use the App Identity in GitHub repos for actions other than commits.
If you don't have automatic commits enabled (out of scope of this plugin), ask hermes to commit changes once it's done editing files.
You will still need to manage pushes, pulls, & PR's.

## Quickstart
1. Install the plugin:
```bash
hermes plugins install Apartment38/hermes_github_bot_commit --enable
```
2. [Create a GitHub App](#create-a-github-app-and-find-its-slug)
3. Configure the plugin to use the App Slug:
```bash
hermes github-bot-commit setup
```

## Requirements

- Linux or macOS, Hermes's **local** terminal backend, and Git 2.31 or later.
- `curl` and access to api.github.com during setup (no `jq` required).
- Hermes supporting native `tool_request` middleware, `register_cli_command`,
  profile-aware `get_hermes_home()`, and public `PluginContext.get_config()` /
  `set_config()` settings APIs. These APIs are documented in the
  [plugin guide](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins#store-settings-and-runtime-state).
  A minimum compatible release has not been established from release evidence;
  no speculative `requires_hermes` floor is declared.
- Python 3.11 or later. The plugin and standalone wrapper use only the standard
  library; no additional Python runtime dependency is required.

## Install and configure

There are two ways to install this plugin: from a local source checkout, or
directly from GitHub through Hermes's plugin manager.

### Install from GitHub (recommended)

Open a terminal, activate the **same profile** you use for Hermes, and run:

```bash
hermes plugin install Apartment38/hermes_github_bot_commit
```

If your Hermes release reports that `plugin` is not a command, use the plural
form instead:

```bash
hermes plugins install Apartment38/hermes_github_bot_commit
```

Use `plugins` in place of `plugin` in the install examples below on those releases.
Hermes clones the repository into the active profile's plugin directory and then asks:

```
Enable 'hermes-github-bot-commit' now? [y/N]
```

Replying `y` (or `yes`) enables the plugin for your session. For a non-interactive
install, use `--enable` to enable it immediately, or `--no-enable` to skip the
prompt entirely:

```bash
hermes plugin install Apartment38/hermes_github_bot_commit --enable
# or
hermes plugin install Apartment38/hermes_github_bot_commit --no-enable
```

If you installed without enabling it, enable the plugin afterwards:

```bash
hermes plugins enable hermes-github-bot-commit
```


### Create a GitHub App and find its slug

If you already have a GitHub App, skip to step 4 to find its slug. Otherwise,
register an app to give your Hermes commits a distinct bot identity. Use a
separate app for each agent if you want their commits to be distinguishable.

1. **Choose the owner and open the registration form.**
   - **Personal account:** Go to your GitHub profile picture → **Settings** →
     **Developer settings** → **GitHub Apps** → **New GitHub App**, or open
     [the personal registration form](https://github.com/settings/apps/new).
   - **Organization:** Go to your profile picture → **Your organizations** →
     the organization's **Settings** → **Developer settings** → **GitHub Apps** →
     **New GitHub App**. The direct URL is
     `https://github.com/organizations/ORG/settings/apps/new` (replace `ORG`).
     You need organization ownership or the appropriate app-management permission.

2. **Complete the registration form.**

   | GitHub setting | Value for this plugin |
   | --- | --- |
   | **GitHub App name** | A unique name, such as `my-hermes-agent` (up to 34 characters). |
   | **Description** | Optional; describe the agent or purpose. |
   | **Homepage URL** | Your GitHub account or organization URL; no dedicated website is needed. |
   | **Callback URL** | Leave blank. |
   | **Request user authorization (OAuth) during installation** | Off. |
   | **Enable Device Flow** | Off. |
   | **Setup URL** | Leave blank. |
   | **Webhooks → Active** | Off; this plugin does not receive events. |
   | **Repository, organization, and account permissions** | Leave at their defaults: **No access**, apart from automatically granted **Metadata: Read-only**. This plugin does not need repository write permissions. |
   | **Where can this GitHub App be installed?** | **Only on this account** is sufficient for this plugin. Choose **Any account** only if you separately intend to install the app on other accounts. |

3. Click **Create GitHub App**.

4. **Copy the App Slug.** Open the app's public page from its settings. The
   slug is the final part of its public URL: for
   `https://github.com/apps/my-hermes-agent`, enter `my-hermes-agent`.
   Use the URL slug, not the display name, numeric App ID, Client ID, or
   installation ID, and do **not** append `[bot]`.

That is all the GitHub App information this plugin needs. You do **not** need to
install the app on repositories, generate a private key, or obtain an access
token for this plugin. It changes commit attribution only; pushes still use
Hermes's existing Git credentials. App installation and authentication are
separate concerns if you later want other tools to act as the app.

### Configure the bot identity

After installation and app registration, configure the identity once per profile:

```bash
hermes github-bot-commit setup
hermes github-bot-commit status
```

When prompted for `GitHub App slug:`, paste the slug from step 4.
`setup` asks only for the GitHub App slug (without `[bot]`), fetches the bot ID
from `https://api.github.com/users/${APP_SLUG}%5Bbot%5D` using `curl -fsSL`,
and parses `.id` in Python. For unattended use, supply the slug explicitly:

```bash
hermes github-bot-commit setup --app-slug example-app
```

Interactive setup requires a TTY and handles cancelled input without saving.
Both values are validated and saved together through `PluginContext.set_config()`
as one non-secret identity mapping in the active profile's `config.yaml`.
`status` is read-only and reports the effective settings key and derived bot
name/email, not a credential-file path.

### Install from a source checkout

Copy this directory into the **active Hermes profile's** plugin directory, for
example `$HERMES_HOME/plugins/hermes-github-bot-commit` (default
`~/.hermes/plugins/hermes-github-bot-commit`):

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/plugins/hermes-github-bot-commit"
cp __init__.py github_bot.py git_wrapper.py plugin.yaml README.md \
  "${HERMES_HOME:-$HOME/.hermes}/plugins/hermes-github-bot-commit/"
```

Then enable the plugin and run the setup wizard:

```bash
hermes plugins enable hermes-github-bot-commit
hermes github-bot-commit setup
hermes github-bot-commit status
```

Use the same profile for installation, setup, and your Hermes session.

### Pin to a specific revision

When installing from GitHub, you can pin the plugin to an exact, immutable
commit SHA instead of a branch or tag. Hermes checks out the commit detached,
verifies that `HEAD` exactly matches the requested SHA, and records the pin in
the current profile:

```bash
hermes plugin install Apartment38/hermes_github_bot_commit --ref 0123456789abcdef0123456789abcdef01234567
```

`hermes plugins update` refuses to move a pinned plugin; use
`hermes plugin install Apartment38/hermes_github_bot_commit --force --ref <new-sha>`
to update it deliberately.

`setup` validates the slug and the API's positive integer ID before one settings
write. Lookup errors leave the saved identity unchanged. The resulting settings
have this shape (the effective plugin ID may differ by installation; `status`
reports the resolved key):

```yaml
plugins:
  entries:
    hermes-github-bot-commit:
      settings:
        identity:
          app_slug: example-app
          bot_id: "123456"
```

Both members must be strings; `bot_id` must be a positive decimal ID. These are
public attribution settings, not authentication credentials. Only these two
members are carried into the generated launcher; no full config or secret store
is serialized. Commits do not make network requests.

Migration: rerun `hermes github-bot-commit setup` in each profile. Legacy
`GITHUB_APP_SLUG`, `GITHUB_BOT_ID`, `GITHUB_AUTHOR_NAME`, and
`GITHUB_AUTHOR_EMAIL` environment entries are ignored. The plugin does not read,
write, or automatically migrate `.env`; old entries are left untouched and may
be removed manually.

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
# APP_SLUG and BOT_ID below denote the configured settings, not environment inputs.
APP_SLUG="example-app"
BOT_ID="123456"
GIT_COMMITTER_NAME="${APP_SLUG}[bot]" \
GIT_COMMITTER_EMAIL="${BOT_ID}+${APP_SLUG}[bot]@users.noreply.github.com" \
git commit \
  --author="${APP_SLUG}[bot] <${BOT_ID}+${APP_SLUG}[bot]@users.noreply.github.com>" \
  -m "$MESSAGE"
```

Arguments are passed directly to Git; commit messages are never reconstructed
or evaluated by a shell. Existing message files, hooks, signing options, Git
configuration, `HOME`, SSH configuration, credential helpers, and tokens remain
under the user's control. The plugin writes no repository or global Git config.

The temporary launcher lives in the active profile's
`cache/hermes-github-bot-commit/bin/`. It contains the interpreter and helper
paths, wrapper directory, and a serialized non-secret identity record. The child
uses only Python's standard library and never opens Hermes settings or credential
files. No global Python installation or `PYTHONPATH` change is needed. Restart
Hermes after updating plugin code so its in-memory middleware uses the new
implementation.

Each eligible tool call reads current settings through its bound PluginContext
and atomically publishes the active profile's launcher, only rewriting changed
contents. Missing or malformed settings replace any previous valid identity, so
qualifying writes fail with setup guidance rather than retaining stale settings.
Direct config/Desktop edits affect newly activated tool calls. An already-running
background job sees the profile launcher last published by middleware or setup,
not arbitrary config edits instantly. Successful setup also refreshes an existing
launcher; if publication fails after settings were saved, it reports that partial
success separately (the settings save is not rolled back).

Foreground tool execution removes the wrapper path afterward while
preserving cwd, exported variables, and command exit status. Background children
retain their launch environment, including the profile wrapper path. Later Git
invocations use that launcher's last published identity as described above.
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

Run the last two commands with an isolated `HERMES_HOME`; use an isolated Python
environment too when adding `validate --install-deps`. Standalone tests require
no extra Python dependencies. CI tests Python 3.11 and 3.14 on Linux and macOS.
`HERMES_SOURCE` enables the optional integration checks against an existing
Hermes checkout; they otherwise report as skipped.

Relevant Hermes contracts: [native plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins),
[middleware](https://hermes-agent.nousresearch.com/docs/developer-guide/middleware),
and [local credentials](https://hermes-agent.nousresearch.com/docs/user-guide/configuration#local-backend).
