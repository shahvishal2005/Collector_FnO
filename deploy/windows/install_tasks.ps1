# What: register the Windows Task Scheduler job that runs the live capture on the VPS each weekday.
# In: optional -ProjectDir and -StartTime. Run ONCE from an ELEVATED PowerShell (Run as administrator).
# Out: a scheduled task "FnOCollector-Live" that starts before the open and restarts after a crash.
#
# The job: starts at -StartTime (default 08:40) Monday to Friday, runs scripts\run_live.py with the
# project's own Python, runs whether or not anyone is logged on, is restarted up to 20 times (one
# minute apart) if it exits with an error, and never starts a second copy while one is running.
# The collector itself waits for login time, handles holidays and exits after the close.

param(
    [string]$ProjectDir = "C:\Indian Market\india-fno-collector",
    [string]$StartTime = "08:40",
    [string]$TaskName = "FnOCollector-Live"
)

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Run this script from an elevated PowerShell (Run as administrator)." }

$python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$script = Join-Path $ProjectDir "scripts\run_live.py"
if (-not (Test-Path $python)) { throw "Python not found: $python (build the .venv first)." }
if (-not (Test-Path $script)) { throw "Script not found: $script" }
if (-not (Test-Path (Join-Path $ProjectDir "config\config.yaml"))) { throw "config\config.yaml is missing." }
if (-not (Test-Path (Join-Path $ProjectDir ".env"))) { throw ".env is missing." }

$action = New-ScheduledTaskAction -Execute $python -Argument "scripts\run_live.py" -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $StartTime
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 10) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# S4U: run whether the user is logged on or not, without storing a password.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered task '$TaskName': weekdays at $StartTime, project $ProjectDir"
Write-Host "Check it:  Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Run now (a test, outside hours): .venv\Scripts\python scripts\run_live.py --test --ignore-hours --max-cycles 2"
