$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$venvPython = Join-Path $backendRoot '.venv\Scripts\python.exe'

Set-Location $projectRoot
docker compose up -d postgres
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 容器启动失败。' }

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv (Join-Path $backendRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 虚拟环境创建失败。' }
}

& $venvPython -m pip install -r (Join-Path $backendRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败。' }
Set-Location $backendRoot
& $venvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败。' }
& $venvPython -m app.bootstrap
if ($LASTEXITCODE -ne 0) { throw '系统初始化失败。' }

Set-Location (Join-Path $projectRoot 'frontend')
npm install
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }

Write-Host '本地环境初始化完成。运行 scripts/start-local.bat（或 start-local.ps1）启动前后端。'
