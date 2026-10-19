# Handoff: public PluginContext identity migration

## Scope

Implement the plan in `.hermes/plans/2026-10-19_011720-plugin-config-identity.md`.
Keep native tool_request middleware, local Linux/macOS activation, temporary PATH,
and the Git wrapper's per-invocation effective-origin policy. No custom backend,
core patch, shell-text Git filter, or repository/global Git identity configuration
is introduced. The rejected Git-native alternative is not documented as a mode.

## Configuration and transport contract

Identity is one public attribution mapping under
`plugins.entries.<effective-plugin-id>.settings.identity`, with string members
`app_slug` and `bot_id`. Registration binds the supplied PluginContext without
reading settings or publishing files. Callbacks resolve settings and the active
profile at execution time using public ctx.get_config/ctx.set_config APIs.

Setup writes the validated pair in one ctx.set_config call. `--app-slug` supports
unattended setup; interactive setup requires a TTY. Status reports the effective
settings key and derived name/email. Legacy environment identity is ignored;
existing users rerun setup per profile. Old entries are left untouched and may be
removed manually. Plugin code must not directly open Hermes configuration,
.env, or credential stores.

The standalone wrapper receives `--wrapper-dir PATH --identity-json JSON --`
followed by Git arguments. Identity validation remains lazy, after the qualifying
GitHub operation gate. Missing/invalid settings must replace the published valid
record, never retain stale identity. Launchers are atomically replaced only when
changed and need no external Python dependency.

Direct config/Desktop edits affect newly activated tool calls. Existing background
jobs inherit the wrapper path and see the last launcher published by middleware or
setup, not arbitrary config changes instantly. Disabling the plugin affects
subsequent calls, not existing children. Setup refreshes an existing launcher after
the settings save; publication failure is partial success, not settings rollback.

## Preserved starting work

The pre-existing fixes exclude resolved current and legacy profile wrappers when
finding original Git, isolate fixture Git from inherited wrapper PATH, and cover
indirect shell commands. Existing artwork and github-app-setup-guide.md are
unrelated and must remain untouched. Changes remain uncommitted; no installation,
user profile config, remote publication, or Git identity settings are authorized.

## Verification

Baseline rerun before implementation: 25 tests passed with real Hermes integration
(no skips); standalone baseline: 25 tests, 2 integration skips.

Final parent-run verification:
- Standalone: 38 tests run, passing with 2 optional integration skips.
- Real Hermes integration: 38 passed, no skips, on inherited and clean PATH.
- Plugin doctor --ci: passed runtime discovery/import/registration.
- Catalog validate --install-deps --json in a separate venv and disposable home:
  all checks passed, warnings empty; dependency list empty; security scan safe.
  Isolation verdict is host. The validator notes that register_cli_command is
  skipped inside the plugin host because CLI subcommands are wired locally.
- Static added-line scan found no hardcoded credential assignments, shell=True,
  pickle loading, or added eval/exec calls. Existing approved-code transforms
  remain unchanged.
- Standalone audit instrumentation denies settings/credential file opens;
  generated launchers run with python -S. Existing real-Git metadata, replay,
  transport, credential passthrough, profile, and shell/Python-state tests pass.
- Source search found no runtime dotenv, get_env_path, save_env_value,
  --env-file, or legacy identity environment lookup. Remaining file-name/env
  references in tests are negative assertions; docs retain migration guidance.
- git diff --check passed. Hashes of unrelated artwork and App setup guide
  are unchanged.

Existing backend-selection imports remain unchanged; this validator emitted no
undocumented-core import warnings. Independent review passed with no blocking
security or logic findings. Its background-refresh coverage suggestion was
addressed with a synchronized persistent child: changed identity updates actual
commit metadata, then identity removal blocks the next write without moving HEAD.
Concurrent publication coverage checks complete launcher reads; concurrent launcher
execution under replacement is an optional further stress test, not exercised here.

A minimum release providing all required APIs has not been established from
release evidence. Documentation names the required public methods instead of
inventing a requires_hermes floor. Passing local validation is not catalog admission.
