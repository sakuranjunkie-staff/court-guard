#!/usr/bin/env python
"""Stop hook: detect leaked tool-call XML in the final assistant message
(the Claude Code "court/invoke" corruption) and auto-retry once.

Modes (env COURT_GUARD_MODE): 'retry' (default) blocks once so the model
re-issues the call cleanly; 'warn' only emits a user-visible systemMessage.
NOTE: systemMessage is shown to the USER only - the model never sees it.
Only a block reason reaches the model, which is why 'retry' is the default.

Fenced/inline code is stripped before matching, so legitimately quoting
tool-call XML inside code blocks does not false-positive.
Loop-safe via stop_hook_active. Fail-open on any error.
Extra regex patterns: one per line in $CLAUDE_PLUGIN_DATA/leak_patterns.txt.
"""
import sys, json, re, os

PATTERNS = [
    r'<\s*antml:invoke\b',
    r'<\s*invoke\s+name\s*=',
    r'<\s*antml:parameter\b',
    r'<\s*parameter\s+name\s*=',
    r'</?\s*antml:function_calls\s*>',
    r'</?\s*function_calls\s*>',
]


def strip_code(text):
    # remove fenced blocks and inline code: quoted XML there is not a leak
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def load_extra():
    d = os.environ.get("CLAUDE_PLUGIN_DATA") or ""
    p = os.path.join(d, "leak_patterns.txt") if d else ""
    out = []
    if p and os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        out.append(line)
        except Exception:
            pass
    return out


def leak_hit(text, extra):
    text = strip_code(text)
    for pat in PATTERNS + extra:
        try:
            m = re.search(pat, text)
        except re.error:
            continue
        if m:
            return m.group(0)
    return None


def emit(obj):
    # ensure_ascii=True: pure-ASCII JSON so Japanese survives any stdout
    # encoding (Windows cp932 would mojibake it); harness parses it back.
    sys.stdout.write(json.dumps(obj, ensure_ascii=True))


def last_assistant_from_transcript(path):
    # SubagentStop is not documented to carry last_assistant_message;
    # fall back to the transcript tail so detection works there too.
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > 400_000:
                fh.seek(size - 400_000)
                fh.readline()
            last = ""
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
                if isinstance(content, str):
                    last = content
                elif isinstance(content, list):
                    texts = [b.get("text") or "" for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    if texts:
                        last = "\n".join(texts)
            return last
    except Exception:
        return ""


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "ignore"))
    msg = data.get("last_assistant_message") or ""
    if not msg and data.get("transcript_path"):
        msg = last_assistant_from_transcript(data["transcript_path"])
    extra = load_extra()

    reason_tpl = (
        "court-guard: a tool call leaked into the visible text (%s) and did NOT run. "
        "Re-issue that one call cleanly, exactly once, keeping its arguments SHORT "
        "(chunk long edits, pass long content by file reference). If it leaks again, "
        "stop and tell the user to restart the session - do NOT /compact. "
        "/ ツール呼び出しが本文へ漏れて未実行。引数を短く保って1回だけ撃ち直せ。"
        "再発したら撃ち続けず再起動を勧めろ。/compact は禁止。"
    )

    # Already forced one continuation -> never block again; warn only if still leaking.
    if data.get("stop_hook_active"):
        if leak_hit(msg, extra):
            emit({"systemMessage": "court-guard: leak persists after one retry; restart the session (do NOT /compact). / 再撃ち後も漏れ継続、/compactせず再起動を。"})
        return

    hit = leak_hit(msg, extra)
    if not hit:
        return

    mode = (os.environ.get("COURT_GUARD_MODE") or "retry").lower()
    reason = reason_tpl % hit
    if mode == "warn":
        emit({"systemMessage": reason})
        return
    emit({"decision": "block", "reason": reason})


try:
    main()
except Exception:
    pass  # fail-open: never break the turn
