#!/usr/bin/env python
"""PreToolUse guard: block heavy/complex inline Bash/PowerShell commands.

Reduces the frequency of the Claude Code "court"/malformed-tool-call bug,
whose strongest trigger is heavy inline commands (multiline, heredocs,
PowerShell COM, long `python -c` bodies). On a match we DENY with a reason
so the model reroutes the work into a scratchpad script file or a sub-agent.

Threshold configurable via COURT_GUARD_CMD_MAXLEN (default 200).
Fail-open: any error -> allow (never break the user's workflow).
"""
import sys, json, re, os


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", "ignore")
    data = json.loads(raw)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not isinstance(cmd, str) or not cmd:
        return

    try:
        maxlen = int(os.environ.get("COURT_GUARD_CMD_MAXLEN") or "200")
    except ValueError:
        maxlen = 200

    has_newline = "\n" in cmd
    length = len(cmd)
    low = cmd.lower()

    reason = None
    if has_newline and ("<<" in cmd or "@'" in cmd or '@"' in cmd):
        reason = "heredoc/here-string"
    elif "new-object -comobject" in low:
        reason = "PowerShell COM (New-Object -ComObject)"
    elif length > maxlen and re.search(r"python[0-9]?\s+-c|-Command\b", cmd):
        reason = "long inline script (python -c / -Command)"
    elif has_newline and length > maxlen:
        reason = "multiline & long (%d chars)" % length

    if not reason:
        return

    msg = (
        "court-guard: heavy inline command detected (%s). This is a strong trigger "
        "for the tool-call corruption bug. Write it to a .ps1/.py scratchpad file and "
        "call it with a short command, or hand heavy multi-step work to a sub-agent. "
        "/ 重いインラインコマンド検知（%s）。スクリプト化して短いコマンドで叩くか、"
        "重い作業はサブエージェントへ。" % (reason, reason)
    )
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        }
    }
    # ensure_ascii=True: emit pure-ASCII JSON (\uXXXX) so the Japanese text
    # survives regardless of the platform stdout encoding (Windows cp932 would
    # otherwise mojibake it). The harness JSON-parses this back to real chars.
    sys.stdout.write(json.dumps(out, ensure_ascii=True))


try:
    main()
except Exception:
    pass  # fail-open
