$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $projectRoot '.local-processes.json'

if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Host '没有本地服务进程记录。'
    exit 0
}

$state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
foreach ($processId in @($state.api, $state.worker, $state.frontend)) {
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $stateFile
Write-Host '本地前后端已停止；PostgreSQL 容器保持运行。'
