#!/usr/bin/env python
"""PreToolUse hook: steer the model away from long tool arguments - the
court-bug trigger. Risk attaches to the length of ONE call (short calls pass
even in contaminated sessions), so work must be SPLIT, not inlined.

Two modes:
- advisory (default): let the call run, inject additionalContext telling the
  model to keep following calls short. Rationale: a call that reached this
  hook already parsed - its generation risk is already paid; denying it only
  forces one more generation.
- enforce (COURT_GUARD_ENFORCE=1): DENY calls whose length is REDUCIBLE -
  shell command chains (splitting never mutilates content) and Agent prompts
  (reference-passing is always available). Long Write/Edit content is NOT
  denied in a clean session: new documents/code are irreducible length - they
  must flow through some tool call, and denying them only turns the same
  tokens into chunked Edits with extra failure modes. Content tools are
  denied only when the history is already contaminated, where re-issuing
  long writes is known to re-leak; there the directive is hand-paste or
  subagent delegation. Session-level rationale for deny: advice is a hope,
  a deny is a guarantee - and the model's own compliant short calls become
  the in-context examples it imitates.

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


def enforce_on():
    return (os.environ.get("COURT_GUARD_ENFORCE") or "").lower() in (
        "1", "true", "deny", "on", "yes")


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


def split_hint(tool, cmd_max, arg_max):
    if tool in ("Bash", "PowerShell"):
        return (
            "re-issue as single-purpose calls, one job each (aim under %d chars; "
            "the working directory persists between calls). Do NOT reroute the "
            "whole body into one long Write - if a script file is needed, build "
            "it with a short Write plus several small Edits. "
            "/ 一呼び出し一仕事に割って撃ち直せ（作業ディレクトリは持続する）。"
            "丸ごと長いWriteへ迂回するな——スクリプトが要るなら短いWrite＋小さな"
            "Editの積み増しで作れ。" % cmd_max)
    if tool == "Write":
        return (
            "write a short skeleton first, then extend it with several small "
            "Edits (each well under %d chars). "
            "/ まず短い骨組みをWriteし、小さなEditを重ねて育てろ。" % arg_max)
    if tool in ("Edit", "MultiEdit"):
        return ("split the replacement into several smaller Edits. "
                "/ 置換を複数の小さなEditに割れ。")
    return (
        "shorten the prompt: point at files on disk ('read X, then do Y') "
        "instead of inlining content. "
        "/ promptを短くしろ——内容を書き下ろさず「ファイルXを読んでYをやれ」で指せ。")


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
    dirty = bool(tp and os.path.isfile(tp) and history_contaminated(tp))
    content_tool = tool in ("Write", "Edit", "MultiEdit")
    hint = split_hint(tool, cmd_max, arg_max)
    dirty_note = (
        " History is ALREADY contaminated - long calls are likely to leak "
        "again; prefer delegating the chunk to a subagent (short reference "
        "prompt - its context starts clean) or hand-pasting file updates; "
        "if neither fits, recommend a restart. "
        "/ 履歴は汚染済み＝再漏れ濃厚。塊はサブへ（短い参照promptで）、"
        "ファイル更新は手貼りへ、無理なら再起動を勧めろ。" if dirty else "")

    # Deny only reducible length (commands, Agent prompts). New content in
    # Write/Edit has nowhere shorter to exist - deny it only when the history
    # is contaminated and re-issuing long writes is known to re-leak.
    if enforce_on() and (not content_tool or dirty):
        if content_tool:
            hint = (
                "do NOT re-issue this long write here. Output the full text "
                "in your reply for the user to hand-paste, or delegate it to "
                "a subagent with a short reference prompt. "
                "/ 汚染下で長い書き込みを繰り返すな。全文を地の文で出して"
                "手貼りしてもらうか、短い参照promptでサブに委ねろ。")
        msg = (
            "court-guard ENFORCE: blocked %s in %s. Long single calls are the "
            "court-bug trigger; risk attaches to ONE call's length: %s%s"
            % (reason, tool, hint, dirty_note))
        out = {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        }}
    else:
        msg = (
            "court-guard: %s in %s. Long tool arguments are the court-bug "
            "trigger; risk attaches to ONE call's length. This call ran, but "
            "keep the NEXT calls short - %s%s" % (reason, tool, hint, dirty_note))
        out = {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }}
    sys.stdout.write(json.dumps(out, ensure_ascii=True))


try:
    main()
except Exception:
    pass  # fail-open
