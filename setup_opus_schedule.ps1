# setup_opus_schedule.ps1 — Opus 12h review scheduled tasks
# Report must be READY at 8:00 AM / 8:00 PM.
# Opus call takes 3-5 min, so tasks run at 7:55 to deliver by 8:00.

$pythonPath = "C:\Users\boein\AppData\Local\Programs\Python\Python313\python.exe"
$scriptPath = "C:\Projects\supervisor\opus_12h_review.py"
$workDir    = "C:\Projects\supervisor"

# Remove all old tasks
foreach ($name in @("Opus_12h_Review_9AM","Opus_12h_Review_9PM","Opus_12h_Review_8AM","Opus_12h_Review_8PM")) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}

# 7:55 AM task — report ready by 8:00 AM
$trigger = New-ScheduledTaskTrigger -Daily -At "07:55"
$action  = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory $workDir
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Opus_12h_Review_8AM" -Trigger $trigger -Action $action -Settings $settings -Description "Opus 12h review - report ready by 8:00 AM" -Force

# 7:55 PM task — report ready by 8:00 PM
$trigger = New-ScheduledTaskTrigger -Daily -At "19:55"
$action  = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory $workDir
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Opus_12h_Review_8PM" -Trigger $trigger -Action $action -Settings $settings -Description "Opus 12h review - report ready by 8:00 PM" -Force

Write-Host "Tasks created: 7:55 AM and 7:55 PM (reports ready by 8:00)"
