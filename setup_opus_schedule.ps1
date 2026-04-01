# setup_opus_schedule.ps1 — Create Windows scheduled tasks for Opus 12h review
# Run this script as Administrator once to set up the schedule.

$pythonPath = "C:\Users\boein\AppData\Local\Programs\Python\Python313\python.exe"
$scriptPath = "C:\Projects\supervisor\opus_12h_review.py"
$workDir    = "C:\Projects\supervisor"

# 9:00 AM task
$trigger9AM = New-ScheduledTaskTrigger -Daily -At "09:00"
$action9AM  = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory $workDir
Register-ScheduledTask -TaskName "Opus_12h_Review_9AM" -Trigger $trigger9AM -Action $action9AM -Description "Opus 12-hour strategic review (morning)" -Force

# 9:00 PM task
$trigger9PM = New-ScheduledTaskTrigger -Daily -At "21:00"
$action9PM  = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory $workDir
Register-ScheduledTask -TaskName "Opus_12h_Review_9PM" -Trigger $trigger9PM -Action $action9PM -Description "Opus 12-hour strategic review (evening)" -Force

Write-Host "Scheduled tasks created:"
Write-Host "  Opus_12h_Review_9AM — daily at 09:00"
Write-Host "  Opus_12h_Review_9PM — daily at 21:00"
