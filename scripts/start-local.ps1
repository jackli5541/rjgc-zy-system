$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
$venvPython = Join-Path $backendRoot '.venv\Scripts\python.exe'
$stateFile = Join-Path $projectRoot '.local-processes.json'

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw '请先运行 scripts/init-local.ps1。'
}

Write-Host '正在应用数据库迁移...'
Push-Location $backendRoot
try {
    & $venvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败，服务未启动。' }
}
finally {
    Pop-Location
}

$api = Start-Process -FilePath $venvPython -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--reload','--reload-dir','app' -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru
$worker = Start-Process -FilePath $venvPython -ArgumentList '-m','watchfiles','--filter','python','app.worker.main','app' -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru
$node = (Get-Command node -ErrorAction Stop).Source
$vite = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
$frontend = Start-Process -FilePath $node -ArgumentList $vite,'--host','0.0.0.0','--port','8080' -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru

@{ api = $api.Id; worker = $worker.Id; frontend = $frontend.Id } | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
Write-Host "本地服务已启动：http://localhost:8080（API：http://localhost:8000，API 与任务进程已开启热重载）"
