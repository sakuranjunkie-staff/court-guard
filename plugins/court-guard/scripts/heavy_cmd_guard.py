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

LEAK_PATTERNS = [
    r'<\s*antml:invoke\b', r'<\s*invoke\s+name\s*=',
    r'<\s*antml:parameter\b', r'<\s*parameter\s+name\s*=',
    r'</?\s*antml:function_calls\s*>', r'</?\s*function_calls\s*>',
]


def history_contaminated(path):
    # Cheap tail scan, only run when a long-arg call was already detected.
    # If the main history holds leaked XML, a subagent (clean context) is
    # strictly safer for chunky work - escalate the advice accordingly.
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > 400_000:
                fh.seek(size - 400_000)
                fh.readline()
            for raw in fh:
                if b'"assistant"' not in raw:
                    continue
                try:
                    entry = json.loads(raw.decode("utf-8", "ignore"))
                except Exception:
                    continue
                if entry.get("type") != "assistant":
                    continue
                content = (entry.get("message") or {}).get("content")
                texts = []
                if isinstance(content, str):
                    texts = [content]
                elif isinstance(content, list):
                    texts = [b.get("text") or "" for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                for t in texts:
                    t = re.sub(r"```.*?```", "", t, flags=re.S)
                    t = re.sub(r"`[^`\n]*`", "", t)
                    if any(re.search(p, t) for p in LEAK_PATTERNS):
                        return True
    except Exception:
        pass
    return False


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

    tp = data.get("transcript_path") or ""
    if tp and os.path.isfile(tp) and history_contaminated(tp):
        msg = (
            "court-guard: %s in %s while this history is ALREADY contaminated - "
            "long calls here are likely to leak again. Escalate now: (1) delegate "
            "the remaining chunk to a subagent with a SHORT reference-style prompt "
            "('read file X and do Y') - its context starts clean; (2) for file "
            "updates, output the text in your reply for the user to hand-paste; "
            "(3) if neither fits, recommend a session restart. "
            "/ 汚染済み履歴での長い引数＝再漏れ濃厚。塊ごとサブへ（短い参照prompt"
            "で・サブの文脈はクリーン）、ファイル更新は手貼りへ、無理なら再起動を"
            "勧めろ。" % (reason, tool)
        )
    else:
        msg = (
            "court-guard: %s in %s. Long tool arguments are the court-bug trigger; "
            "risk attaches to the length of ONE call, so split work into short calls. "
            "This call ran, but keep the NEXT calls short: one job per command (no "
            "long && chains; the working dir persists between calls), chunk long "
            "edits, pass long content by file reference, keep Agent prompts brief. "
            "/ 長い引数は court バグの引き金（リスクは1呼び出しの長さに付く）。以後は"
            "短く割れ（一呼び出し一仕事・長い&&連結禁止・編集は分割・長文はファイル"
            "参照・Agentのpromptは短く）。" % (reason, tool)
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
