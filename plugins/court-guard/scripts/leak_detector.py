#!/usr/bin/env python
"""Stop hook: detect leaked tool-call XML in the final assistant message
(the Claude Code "court/invoke" corruption) and warn or auto-retry once.

Modes (env COURT_GUARD_MODE): 'warn' (default) emits a systemMessage;
'retry' blocks once so the model re-issues the call cleanly.
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


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "ignore"))
    msg = data.get("last_assistant_message") or ""
    extra = load_extra()

    warn = (
        "court-guard: a tool call may have leaked into the visible text (%s) and did "
        "NOT run. Re-issue that one call cleanly, exactly once. If it persists, restart "
        "the session - do NOT /compact. / ツール呼び出しの断片が本文へ漏れ、実行されて"
        "いない可能性。1回だけクリーンに撃ち直し、直らなければ /compact せず再起動。"
    )

    # Already forced one continuation -> never block again; warn only if still leaking.
    if data.get("stop_hook_active"):
        if leak_hit(msg, extra):
            emit({"systemMessage": "court-guard: leak persists after one retry; restart recommended. / 再撃ち後も漏れ継続、再起動推奨。"})
        return

    hit = leak_hit(msg, extra)
    if not hit:
        return

    mode = (os.environ.get("COURT_GUARD_MODE") or "warn").lower()
    reason = warn % hit
    if mode == "retry":
        emit({"decision": "block", "reason": reason})
        return
    emit({"systemMessage": reason})


try:
    main()
except Exception:
    pass  # fail-open: never break the turn
