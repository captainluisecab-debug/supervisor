# setup_opus_schedule.ps1 — Create Windows scheduled tasks for Opus 12h review
# Schedule: 8:00 AM and 8:00 PM daily, FOREVER, no exceptions.
# Run this script as Administrator.

$pythonPath = "C:\Users\boein\AppData\Local\Programs\Python\Python313\python.exe"
$scriptPath = "C:\Projects\supervisor\opus_12h_review.py"
$workDir    = "C:\Projects\supervisor"

# Remove old tasks if they exist
Unregister-ScheduledTask -TaskName "Opus_12h_Review_9AM" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Opus_12h_Review_9PM" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Opus_12h_Review_8AM" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Opus_12h_Review_8PM" -Confirm:$false -ErrorAction SilentlyContinue

# 8:00 AM task — runs on AC power AND battery
$trigger8AM = New-ScheduledTaskTrigger -Daily -At "08:00"
$action8AM  = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory $workDir
$settings8AM = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Opus_12h_Review_8AM" -Trigger $trigger8AM -Action $action8AM -Settings $settings8AM -Description "Opus 12-hour strategic review (morning) - MANDATORY" -Force

# 8:00 PM task — runs on AC power AND battery
$trigger8PM = New-ScheduledTaskTrigger -Daily -At "20:00"
$action8PM  = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory $workDir
$settings8PM = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Opus_12h_Review_8PM" -Trigger $trigger8PM -Action $action8PM -Settings $settings8PM -Description "Opus 12-hour strategic review (evening) - MANDATORY" -Force

Write-Host "Scheduled tasks created:"
Write-Host "  Opus_12h_Review_8AM - daily at 08:00 (battery-safe)"
Write-Host "  Opus_12h_Review_8PM - daily at 20:00 (battery-safe)"
