# setup_handoff_refresh.ps1 - Handoff bundle auto-refresh (every 6h)
# Registers 4 daily tasks at 00:00, 06:00, 12:00, 18:00 ET.
# Each task runs C:\Projects\handoff\_refresh_bundle.py which sequentially
# invokes _dump_state.py then _make_share_bundle.py.
#
# Bundle is read-only on enzobot/ (no live-bot interruption).
# NO Anthropic API calls; safe to run during bot operation.
#
# Run ONCE elevated:  powershell -ExecutionPolicy Bypass -File .\setup_handoff_refresh.ps1
# Rollback:           .\teardown_handoff_refresh.ps1

$pythonPath = "C:\Users\boein\AppData\Local\Programs\Python\Python313\python.exe"
$scriptPath = "C:\Projects\handoff\_refresh_bundle.py"
$workDir    = "C:\Projects\handoff"

$schedule = @(
    @{ Name = "Handoff_Refresh_00"; Time = "00:00" },
    @{ Name = "Handoff_Refresh_06"; Time = "06:00" },
    @{ Name = "Handoff_Refresh_12"; Time = "12:00" },
    @{ Name = "Handoff_Refresh_18"; Time = "18:00" }
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

foreach ($t in $schedule) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $t.Time
    $action  = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory $workDir
    Register-ScheduledTask `
        -TaskName $t.Name `
        -Trigger $trigger `
        -Action  $action `
        -Settings $settings `
        -Description "Handoff bundle refresh - fires daily at $($t.Time) ET. Wrapper runs _dump_state.py then _make_share_bundle.py. Read-only on enzobot/. No API calls." `
        -Force | Out-Null
    Write-Host "Registered: $($t.Name) @ $($t.Time)"
}

Write-Host ""
Write-Host "Done. 4 tasks registered."
Write-Host "Verify: Get-ScheduledTask -TaskName Handoff_Refresh_* | Select TaskName,State"
Write-Host "Manual fire test: Start-ScheduledTask -TaskName Handoff_Refresh_06"
Write-Host "Log: C:\Projects\handoff\_autorefresh.log"
