# What: remove the live-capture scheduled task from the VPS.
# In: optional -TaskName. Run from an elevated PowerShell. Out: the task is gone.

param([string]$TaskName = "FnOCollector-Live")

$ErrorActionPreference = "Stop"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'."
} else {
    Write-Host "Task '$TaskName' does not exist."
}
