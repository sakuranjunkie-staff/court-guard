#!/usr/bin/env python
"""UserPromptSubmit hook: if this session's history already contains leaked
tool-call XML (the court/invoke corruption), inject a steering notice into the
model's context on every prompt.

Rationale: once a leak lands in the history, the model tends to imitate it and
the corruption repeats. Nothing can clean the history, but a persistent
"do not imitate, keep tool arguments short" reminder counteracts the imitation
loop. additionalContext from UserPromptSubmit IS visible to the model.

Scans only the tail of the transcript (last ~400 KB) for speed. Fail-open.
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
TAIL_BYTES = 400_000

NOTICE = (
    "court-guard: this session's history contains leaked/corrupted tool-call XML "
    "from an earlier turn. Do NOT imitate that text. Keep EVERY tool-call argument "
    "short: chunk long edits into several small ones, pass long content by file "
    "reference instead of generating it inline, keep Agent prompts brief. If another "
    "call leaks, stop retrying and recommend a session restart (never /compact). "
    "/ この履歴には壊れたツール呼び出しXMLが残っている。真似するな。全ツール引数を短く"
    "（長い編集は分割・長文はファイル参照で渡す・Agentのpromptは短く）。再発したら"
    "撃ち続けず再起動を勧めろ。/compactは禁止。"
)


def strip_code(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def assistant_texts(path):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > TAIL_BYTES:
            fh.seek(size - TAIL_BYTES)
            fh.readline()  # drop the partial line
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
                yield content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        yield block.get("text") or ""


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "ignore"))
    path = data.get("transcript_path") or ""
    if not path or not os.path.isfile(path):
        return
    for text in assistant_texts(path):
        text = strip_code(text)
        for pat in PATTERNS:
            if re.search(pat, text):
                sys.stdout.write(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": NOTICE,
                    }
                }, ensure_ascii=True))
                return


try:
    main()
except Exception:
    pass  # fail-open
