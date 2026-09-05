# Run in an elevated PowerShell window on the Windows computer.
# Opens only this application's TCP port on its Tailscale IPv4 address.
param([ValidateRange(1, 65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$TailscaleExe = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (-not (Test-Path $TailscaleExe)) { throw 'Install and connect Tailscale first.' }
$PeerAddress = (& $TailscaleExe ip -4 | Select-Object -First 1).Trim()
if ($LASTEXITCODE -ne 0 -or $PeerAddress -notmatch '^100\.(\d{1,3}\.){2}\d{1,3}$') {
    throw 'No active Tailscale IPv4 address was found.'
}
$RuleName = 'PocketBridge-Tailscale'
$Existing = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
if ($Existing) {
    Set-NetFirewallRule -Name $RuleName -Enabled True -Action Allow -Direction Inbound -Profile Any
    $Existing | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress $PeerAddress -RemoteAddress '100.64.0.0/10'
    $Existing | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port
} else {
    New-NetFirewallRule -Name $RuleName -DisplayName 'PocketBridge (Tailscale only)' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
        -LocalAddress $PeerAddress -RemoteAddress '100.64.0.0/10' -Profile Any
}
Write-Host "PocketBridge allowed at ${PeerAddress}:$Port for Tailscale peers."

