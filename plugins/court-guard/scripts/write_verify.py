#!/usr/bin/env python
"""PostToolUse (Write|Edit) EXPERIMENTAL: confirm the edit reached disk.

If the tool reported success but the target file is missing or empty, warn.
Cannot detect 'phantom content' when the hook's own tool_response is corrupted;
best-effort only. Fail-open.
"""
import sys, json, os


def emit(obj):
    # ensure_ascii=True: pure-ASCII JSON so Japanese survives any stdout
    # encoding (Windows cp932 would mojibake it); harness parses it back.
    sys.stdout.write(json.dumps(obj, ensure_ascii=True))


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "ignore"))
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("path")
    if not path:
        return
    if not os.path.isfile(path):
        emit({"systemMessage": "court-guard(write_verify): %s does not exist after a reported write - possible phantom write. Verify with PowerShell/Test-Path. / 書き込み後に存在せず＝幻の書き込みの可能性。" % path})
        return
    try:
        if os.path.getsize(path) == 0:
            emit({"systemMessage": "court-guard(write_verify): %s is empty after write. / 書き込み後に空。" % path})
    except Exception:
        pass


try:
    main()
except Exception:
    pass
