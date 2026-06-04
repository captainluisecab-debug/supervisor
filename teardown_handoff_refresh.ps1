# teardown_handoff_refresh.ps1 - Remove all Handoff_Refresh_* scheduled tasks.
# Safe to run anytime. Stops scheduled refreshes; manual refresh via _make_share_bundle.py still works.

foreach ($name in @("Handoff_Refresh_00","Handoff_Refresh_06","Handoff_Refresh_12","Handoff_Refresh_18")) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Unregistered (or absent): $name"
}
Write-Host "Done. Verify: Get-ScheduledTask -TaskName Handoff_Refresh_* (should return nothing)."
