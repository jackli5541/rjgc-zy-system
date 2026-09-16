$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $projectRoot '.local-processes.json'

if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Host '没有本地服务进程记录。'
    exit 0
}

$state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json

function Stop-ProcessTree([int]$RootProcessId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $RootProcessId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-ProcessTree -RootProcessId $child.ProcessId
    }
    Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
}

foreach ($processId in @($state.api, $state.worker, $state.frontend)) {
    Stop-ProcessTree -RootProcessId $processId
}
Remove-Item -LiteralPath $stateFile
Write-Host '本地前后端已停止；PostgreSQL 容器保持运行。'
