---
description: Recover from a leaked/malformed tool call (court/invoke bug) - re-issue once, else advise restart.
---
The previous turn may have leaked a tool call into the visible text (the Opus 4.8 "court/invoke" bug), which means the tool did NOT actually run.

Do exactly this:
1. Identify the single tool call that leaked as text and did not execute.
2. Re-issue that ONE call cleanly, exactly once.
3. If it leaks again, STOP. Do not repeat it, and do not run /compact (that makes it worse). Tell the user to restart the session.
4. If you edited files earlier this session, verify the changes actually reached disk (e.g. a PowerShell `Test-Path`/content read), because Write/Edit "success" can be phantom under this bug.
