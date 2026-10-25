---
description: Safely update this VPS from GitHub (pull, config drift check, quality gate, data check, report)
argument-hint: [force]
---

You are updating the **india-fno-collector** project on the Windows VPS from GitHub. Run the steps
below in order, in this project folder, using PowerShell. Arguments given: `$ARGUMENTS`.

## Rules (never break these)
- Never read, print, copy or send `.env` or `access_token.txt`. Never place orders. This project only reads data.
- Work only inside this project folder. Do not change Windows settings, firewall or scheduled tasks.
- Never run `git reset --hard`, `git clean`, `git push`, `git stash drop`, or any force option. If git
  complains, STOP and report; do not "fix" it by discarding anything.
- Never overwrite `config\config.yaml` as a whole; make only the minimal edits described in step 4.
- If any step fails, STOP at that step and report it. Do not continue to later steps.

## Step 0: is it safe to update now?
1. Print the current time in India (`Get-Date`, the VPS is on India Standard Time) and the live status:
   `.venv\Scripts\python scripts\live_status.py` (it is fine if it says there are no records).
2. Do **not** update on a weekday between 08:30 and 15:45 India time, because the live capture is running
   or about to start. If it is inside that window and `$ARGUMENTS` does not contain the word `force`,
   STOP and tell the user to run `/vps-update` after 15:45 (or `/vps-update force`).

## Step 1: what will change
1. `git status --short` must show nothing for tracked files (ignored files such as `.env`, `data`,
   `config\config.yaml`, `.venv`, `logs` do not appear). If tracked files are modified, STOP and list them.
2. Remember the current commit: `git rev-parse --short HEAD`.
3. `git fetch origin`, then `git log --oneline HEAD..origin/main`.
4. If there is nothing new, say "already up to date at <commit>", run only steps 5 to 7, and finish.

## Step 2: pull
`git pull --ff-only origin main`. If this fails for any reason, STOP and report the exact message.
Afterwards show `git diff --stat ORIG_HEAD HEAD` (files changed) and note whether `pyproject.toml`,
`config\config.example.yaml` or `deploy\windows\install_tasks.ps1` changed.

## Step 3: dependencies
If `pyproject.toml` changed, run `git diff ORIG_HEAD HEAD -- pyproject.toml` and show the dependency
lines that changed. Do not install new packages yourself: tell the user which pins are needed.
Always refresh the editable install: `.venv\Scripts\python -m pip install --no-deps -e .`

## Step 4: config drift
Run `.venv\Scripts\python scripts\check_config.py`.
- If it prints `config loads OK` and no differences: nothing to do.
- If settings are missing from `config\config.yaml`: that is fine when the example's default is acceptable;
  report them. If the loader says the config is INVALID because of an unknown key (a renamed or removed
  setting), fix it minimally: copy `config\config.yaml` to `config\config.yaml.bak`, then edit only the
  affected lines (rename or delete the old key, add the new one with the value from
  `config\config.example.yaml`). Keep the local values for `live.allowed_hosts` (this computer's name) and
  `paths.nifty_candles_root` (empty). Run `check_config.py` again until it loads.

## Step 5: quality gate
Run `.venv\Scripts\python scripts\run_all.py`. It must print `ALL CHECKS PASSED`. If not, STOP, report the
failing step with its output, and say the live capture should not be restarted until it is fixed.

## Step 6: data check
Run `.venv\Scripts\python scripts\check_manifest.py --dataset all`. A line saying a dataset's manifest was
not found is normal for a dataset that has not been backfilled yet; any other problem is an error to report.

## Step 7: scheduled task (read-only)
`Get-ScheduledTask -TaskName FnOCollector-Live | Get-ScheduledTaskInfo | Format-List TaskName, LastRunTime, LastTaskResult, NextRunTime`.
If the task does not exist, say so. If `deploy\windows\install_tasks.ps1` changed in step 2, tell the user
the task must be re-registered from an elevated (administrator) PowerShell; you cannot do that yourself.

## Final report (plain text, in this order)
1. Commit before -> commit after (or "already up to date").
2. Files changed (short list) and whether pyproject / example config / install script changed.
3. Config edits made (or none).
4. `run_all.py` result and number of tests passed.
5. Manifest check result per dataset.
6. Scheduled task state.
7. Anything the user must do (administrator steps, new dependencies, a restart).
