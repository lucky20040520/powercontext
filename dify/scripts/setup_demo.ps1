param([string]$Root = 'D:\DifyDemo')
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path "$Root\cache", "$Root\python", "$Root\bin", "$Root\tmp" | Out-Null
$env:UV_TOOL_DIR = "$Root\tools"
$env:UV_TOOL_BIN_DIR = "$Root\bin"
$env:UV_CACHE_DIR = "$Root\cache"
$env:UV_PYTHON_INSTALL_DIR = "$Root\python"
$env:TEMP = "$Root\tmp"
$env:TMP = "$Root\tmp"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv from https://docs.astral.sh/uv/ first, then rerun.' }
uv tool install --python 3.14.5 'powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@927bb6ee1ee46fab38a1993c9d9a3fbf7a1da0fb'
if ($LASTEXITCODE -ne 0) { throw 'PowerContext installation failed.' }
Write-Host "Installed pinned PowerContext under $Root. Next: run start_demo.ps1."