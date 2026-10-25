---
description: Report how the live capture is doing on this VPS (read-only)
argument-hint: [YYYY-MM-DD]
---

Report the health of the live option-chain capture on this VPS. This is read-only: change nothing.

Rules: never read, print or send `.env` or `access_token.txt`; never place orders; work only in this
project folder, in PowerShell. Optional date argument: `$ARGUMENTS` (default: today).

1. Print the current India time (`Get-Date`) and the installed commit: `git rev-parse --short HEAD`.
2. Run `.venv\Scripts\python scripts\live_status.py` (add `--date <date>` if a date was given). Show the full output.
3. Show the scheduled task: `Get-ScheduledTask -TaskName FnOCollector-Live | Get-ScheduledTaskInfo | Format-List TaskName, LastRunTime, LastTaskResult, NextRunTime`.
4. Show the last 15 lines of today's log: `Get-Content (Get-ChildItem logs\run_live_*.log | Sort-Object LastWriteTime | Select-Object -Last 1).FullName -Tail 15`.
5. Show free disk space on the drive that holds this folder and the size of `data` (`Get-ChildItem data -Recurse -File | Measure-Object Length -Sum`).
6. Summarise in plain words: is the capture healthy (verdict OK), what the verdict problems are if any,
   how many cycles and rows so far, the slowest call and any rate-limit answers, and whether anything needs the user.
