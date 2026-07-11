# court-guard

日本語版: [README.ja.md](README.ja.md)

Mitigation, detection, and recovery for the Claude Code / Opus 4.8 **tool-call corruption bug** (the "court/invoke" leak), where a tool call is emitted as broken tokens: the opening tag corrupts, the call is never executed, and the tool-call XML leaks into the visible reply. Once it leaks, the conversation history is contaminated and the model tends to repeat it. Reported most on Opus 4.8 (1M context) on Windows.

## This does NOT cure the bug

The bug happens in the model's own token generation (decoding). A Claude Code plugin runs in the harness - there is no layer where it can intervene while the broken tokens are being produced. **court-guard cannot prevent the corruption.** It only lowers how often it triggers, and shortens the damage after it happens.

| It can | It cannot |
|---|---|
| Detect leaked tool-call XML at end of turn (main and subagents) and force one clean retry | Prevent the broken token generation itself |
| Nag the model persistently once the history is contaminated | Intervene mid-stream while tokens are generated |
| Steer the model away from long tool arguments (the trigger) without blocking the call | Remove history contamination (the leaked text stays) |
| Flag Write/Edit that did not reach disk (experimental) | Detect Read/Grep "phantom" output (nothing to compare against) |

## What's inside (v0.2.x)

- **leak_detector** (Stop + SubagentStop): scans the final assistant message for leaked tool-call XML. On SubagentStop, where `last_assistant_message` is not documented, it falls back to reading the transcript tail — so leaks inside subagents are also caught and retried once. Default mode is now `retry`: it blocks the turn once so the model re-issues the call cleanly — the block `reason` is the ONLY channel that actually reaches the model (a `systemMessage` warning is user-visible only, which is why the old `warn` default did nothing for auto-recovery). Fenced/inline code is stripped before matching to avoid false positives. Loop-safe via `stop_hook_active`.
- **contamination_notice** (UserPromptSubmit, new): if the session transcript already contains leaked tool-call XML, injects a persistent notice into the model's context on every prompt: don't imitate the corrupted text, keep all tool arguments short, recommend restart on recurrence. This targets the imitation loop — the mechanism that makes one leak turn into many.
- **heavy_cmd_guard** (PreToolUse, redesigned): no longer denies. A call that reached this hook already parsed correctly; denying it forces the model to re-generate the same payload another way — one more long generation, one more chance to corrupt. Instead it lets the call run and injects `additionalContext` steering the model to keep following calls short. Now also watches long `Write` content, `Edit` new_string and `Agent` prompts, not just shell commands. When the history is already contaminated, a long call escalates the advice: delegate the chunk to a subagent with a short reference-style prompt (a subagent's context starts clean), hand-paste file updates, or restart — the one situation where "use a subagent" is mechanically the right call.
- **write_verify** (PostToolUse, experimental): warns if a Write/Edit target is missing/empty on disk after a reported success.
- **/court-guard:court-recover** (command): a manual recovery playbook (re-issue once, don't /compact, restart if it persists, verify prior writes).

## Install

```
/plugin marketplace add sakuranjunkie-staff/court-guard
/plugin install court-guard@court-guard
```

## Configuration (environment variables)

- `COURT_GUARD_ENFORCE` = `1` to make heavy_cmd_guard DENY over-threshold calls instead of advising. The deny reason instructs a concrete split (single-purpose commands / skeleton-plus-small-Edits / reference-style Agent prompts) and explicitly forbids rerouting the body into one long Write. Session-level rationale: advice is a hope, a deny is a guarantee - and the model's own compliant short calls become the in-context examples it imitates. Off by default (advisory).
- `COURT_GUARD_MODE` = `retry` (default) or `warn` - auto-retry-once vs user-visible-warning-only (the model never sees a warn).
- `COURT_GUARD_CMD_MAXLEN` = integer (default `200`) - shell-command length threshold for the advisory.
- `COURT_GUARD_ARG_MAXLEN` = integer (default `3000`) - Write/Edit/Agent argument length threshold for the advisory.
- `leak_patterns.txt` in the plugin data dir (`$CLAUDE_PLUGIN_DATA`) - extra regex, one per line, to match how the corruption looks in YOUR logs.

## Caveats

- **False positives:** if a reply legitimately discusses tool-call XML *outside* code fences, `leak_detector`/`contamination_notice` may fire (quoting it inside backticks or fenced blocks is ignored). Worst case in `retry` mode is one spurious extra turn; it never loops.
- `retry` re-issues the turn once; if the retry also leaks, court-guard stops and recommends a restart. It does not loop.
- The biggest lever is outside any plugin: the bug is reported mostly on **Opus 4.8 with the 1M context tier**. If you can work in the standard 200k tier (`/model claude-opus-4-8`, no `[1m]`), do that and restart sessions liberally — restarting is the only real cure for a contaminated history.
- Requires `python` on PATH. Windows users: ensure `python` resolves in the shell Claude Code uses.

## Changelog

| Version | Date | Summary |
|---|---|---|
| v0.3.0 | 2026-07-12 | Optional enforce mode (`COURT_GUARD_ENFORCE=1`): deny over-threshold calls with concrete split instructions, instead of advising. Contamination escalation folded into both modes |
| v0.2.2 | 2026-07-12 | Contamination-aware escalation: on a long call in an already-contaminated history, advise routing the chunk to a subagent (short reference-style prompt), hand-pasting file updates, or restarting |
| v0.2.1 | 2026-07-12 | Leak detection inside subagents: leak_detector registered on SubagentStop, with a transcript-tail fallback where `last_assistant_message` is not provided |
| v0.2 | 2026-07-12 | Full redesign after v0.1 field-tested as ineffective: detection defaults to `retry` (a warn never reaches the model), deny-based guard replaced with advisory context (denying a parsed call only forces one more long generation), long Write/Edit/Agent arguments watched, `contamination_notice` added against the imitation loop, code fences excluded from matching |
| v0.1 | 2026-07-11 | Initial release: deny-based heavy_cmd_guard, warn-based leak_detector, write_verify, /court-recover |

Please report real-world results via issues.

## License

MIT
