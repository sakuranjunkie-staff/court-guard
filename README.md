# court-guard

Mitigation, detection, and recovery for the Claude Code / Opus 4.8 **tool-call corruption bug** (the "court/invoke" leak), where a tool call is emitted as broken tokens: the opening tag corrupts, the call is never executed, and the tool-call XML leaks into the visible reply. Once it leaks, the conversation history is contaminated and the model tends to repeat it. Reported most on Opus 4.8 (1M context) on Windows.

## This does NOT cure the bug

The bug happens in the model's own token generation (decoding). A Claude Code plugin runs in the harness - there is no layer where it can intervene while the broken tokens are being produced. **court-guard cannot prevent the corruption.** It only lowers how often it triggers, and shortens the damage after it happens.

| It can | It cannot |
|---|---|
| Block heavy inline commands before they run (they are a strong trigger) | Prevent the broken token generation itself |
| Detect leaked tool-call XML at end of turn and warn | Intervene mid-stream while tokens are generated |
| Optionally auto-retry the turn once (opt-in) | Remove history contamination (the leaked text stays) |
| Flag Write/Edit that did not reach disk (experimental) | Detect Read/Grep "phantom" output (nothing to compare against) |

## What's inside

- **heavy_cmd_guard** (PreToolUse): denies heavy/complex inline Bash/PowerShell (multiline+long, heredocs, PowerShell COM, long `python -c`/`-Command`) and tells the model to use a script file or sub-agent. Threshold via `COURT_GUARD_CMD_MAXLEN` (default 200).
- **leak_detector** (Stop): scans the final assistant message for leaked tool-call XML. Default mode `warn` shows a warning; mode `retry` blocks the turn once so the model re-issues the call cleanly. Loop-safe via `stop_hook_active`.
- **write_verify** (PostToolUse, experimental): warns if a Write/Edit target is missing/empty on disk after a reported success.
- **/court-guard:court-recover** (command): a manual recovery playbook (re-issue once, don't /compact, restart if it persists, verify prior writes).

## Install

```
/plugin marketplace add sakuranjunkie-staff/court-guard
/plugin install court-guard@court-guard
```

## Configuration (environment variables)

- `COURT_GUARD_MODE` = `warn` (default) or `retry` - warn-only vs auto-retry-once.
- `COURT_GUARD_CMD_MAXLEN` = integer (default `200`) - heavy-command length threshold.
- `leak_patterns.txt` in the plugin data dir (`$CLAUDE_PLUGIN_DATA`) - extra regex, one per line, to match how the corruption looks in YOUR logs.

## Caveats

- **False positives:** if a reply legitimately discusses tool-call XML, `leak_detector` may fire. That's why the default is `warn` (low harm). Use `retry` only if your workflow rarely writes such text.
- `retry` re-issues the turn once; if the retry also leaks, court-guard stops and recommends a restart. It does not loop.
- Requires `python` on PATH. Windows users: ensure `python` resolves in the shell Claude Code uses.

## Status

v0.1. The guard and the recovery command are the solid core. `leak_detector` `retry` mode and `write_verify` are new and marked experimental - please report real-world results via issues.

## License

MIT
