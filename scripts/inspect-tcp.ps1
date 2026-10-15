param(
    [ValidateRange(1, 12)]
    [int]$Samples = 3,
    [ValidateRange(1, 30)]
    [int]$IntervalSeconds = 10,
    [string]$OutputPath
)

# Read-only snapshots. Do not collect addresses, command lines or credentials.
$ErrorActionPreference = 'Stop'
$snapshots = @()
for ($sampleIndex = 0; $sampleIndex -lt $Samples; $sampleIndex++) {
    $connections = @(Get-NetTCPConnection | Select-Object State, OwningProcess, LocalPort, RemotePort)
    $processNames = @{}
    Get-Process | ForEach-Object { $processNames[[int]$_.Id] = $_.ProcessName }
    $states = @($connections | Group-Object State | Sort-Object Count -Descending | ForEach-Object {
        [pscustomobject]@{ State = $_.Name; Count = $_.Count }
    })
    $owners = @($connections | Group-Object OwningProcess, State | Sort-Object Count -Descending | Select-Object -First 30 | ForEach-Object {
        $entry = $_.Group[0]
        [pscustomobject]@{
            ProcessId = $entry.OwningProcess
            Process = $processNames[[int]$entry.OwningProcess]
            State = [string]$entry.State
            Count = $_.Count
        }
    })
    $localPorts = @($connections | Group-Object LocalPort, State | Sort-Object Count -Descending | Select-Object -First 30 | ForEach-Object {
        [pscustomobject]@{ Port = $_.Group[0].LocalPort; State = [string]$_.Group[0].State; Count = $_.Count }
    })
    $remotePorts = @($connections | Group-Object RemotePort, State | Sort-Object Count -Descending | Select-Object -First 30 | ForEach-Object {
        [pscustomobject]@{ Port = $_.Group[0].RemotePort; State = [string]$_.Group[0].State; Count = $_.Count }
    })
    $snapshot = [pscustomobject]@{
        Timestamp = (Get-Date).ToUniversalTime().ToString('o')
        Total = $connections.Count
        States = $states
        TopProcesses = $owners
        TopLocalPorts = $localPorts
        TopRemotePorts = $remotePorts
    }
    $snapshots += $snapshot
    Write-Host "TCP snapshot $($sampleIndex + 1)/${Samples}: $($snapshot.Total)"
    $states | Format-Table -AutoSize | Out-Host
    $owners | Format-Table -AutoSize | Out-Host
    if ($sampleIndex + 1 -lt $Samples) { Start-Sleep -Seconds $IntervalSeconds }
}
if ($OutputPath) {
    $snapshots | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Write-Host "Saved aggregate snapshots to $OutputPath"
}
