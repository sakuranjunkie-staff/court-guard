#!/usr/bin/env python
"""PreToolUse hook: advise (never deny) when a tool call carries long arguments.

v0.2 redesign. A call that reaches PreToolUse has already parsed correctly -
it did NOT leak. Denying it forces the model to re-generate the same payload
another way (e.g. a long Write), which is one MORE long generation and one more
chance to corrupt. So v0.2 lets the call run and injects additionalContext
steering the model to keep FOLLOWING calls short. The trigger is long arguments
in any tool (Bash/PowerShell command, Write content, Edit new_string, Agent
prompt) - not just shell commands.

Thresholds: COURT_GUARD_CMD_MAXLEN (default 200, shell commands),
COURT_GUARD_ARG_MAXLEN (default 3000, content-bearing args).
Fail-open: any error -> silent allow.
"""
import sys, json, re, os


def intdef(name, default):
    try:
        return int(os.environ.get(name) or default)
    except Exception:
        return default


def arg_len(tool, ti):
    if tool == "Write":
        return len(ti.get("content") or ""), "content"
    if tool in ("Edit", "MultiEdit"):
        edits = ti.get("edits")
        if isinstance(edits, list):
            return sum(len((e or {}).get("new_string") or "") for e in edits), "edits"
        return len(ti.get("new_string") or ""), "new_string"
    if tool in ("Agent", "Task"):
        return len(ti.get("prompt") or ""), "prompt"
    return 0, ""


def shell_reason(cmd, maxlen):
    has_newline = "\n" in cmd
    low = cmd.lower()
    if has_newline and ("<<" in cmd or "@'" in cmd or '@"' in cmd):
        return "heredoc/here-string"
    if "new-object -comobject" in low:
        return "PowerShell COM"
    if len(cmd) > maxlen and re.search(r"python[0-9]?\s+-c|-Command\b", cmd):
        return "long inline script"
    if has_newline and len(cmd) > maxlen:
        return "multiline & long (%d chars)" % len(cmd)
    return None


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "ignore"))
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    cmd_max = intdef("COURT_GUARD_CMD_MAXLEN", 200)
    arg_max = intdef("COURT_GUARD_ARG_MAXLEN", 3000)

    reason = None
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command") or ""
        if isinstance(cmd, str) and cmd:
            reason = shell_reason(cmd, cmd_max)
    else:
        n, field = arg_len(tool, ti)
        if n > arg_max:
            reason = "long %s (%d chars)" % (field, n)

    if not reason:
        return  # silent allow

    msg = (
        "court-guard: %s in %s. Long tool arguments are the court-bug trigger. "
        "This call ran, but keep the NEXT calls short: chunk long edits into "
        "several small ones, pass long content by file reference instead of "
        "generating it inline, keep Agent prompts brief. "
        "/ 長い引数は court バグの引き金。この呼び出しは通したが、以後は短く"
        "（編集は分割・長文はファイル参照・Agentのpromptは短く）。" % (reason, tool)
    )
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }, ensure_ascii=True))


try:
    main()
except Exception:
    pass  # fail-open
