param([string]$Root = 'D:\DifyDemo')
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path "$Root\runtime", "$Root\logs" | Out-Null
$env:POWERCONTEXT_HOME = ("$Root\runtime" -replace '\\','/')
$env:PYTHONDONTWRITEBYTECODE = '1'
$configPath = "$Root\runtime\server.env"
if (-not (Test-Path -LiteralPath $configPath)) {
    $demoKey = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
    [IO.File]::WriteAllLines($configPath, @("POWERCONTEXT_HOME=$env:POWERCONTEXT_HOME", "POWERCONTEXT_SERVER_WORKSPACE=$env:POWERCONTEXT_HOME", 'POWERCONTEXT_SERVER_AUTH_ENABLED=true', "POWERCONTEXT_SERVER_AUTH_TOKEN=$demoKey"))
}
$pc = "$Root\bin\powercontext.exe"
$py = "$Root\tools\powercontext\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pc)) { $pc = 'D:\uv\bin\powercontext.exe'; $py = 'D:\uv\tools\powercontext\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $pc)) { throw 'Run setup_demo.ps1 first.' }
foreach ($demoPort in @(8017, 8018)) {
    $demoSocket = [Net.Sockets.TcpClient]::new()
    try { $demoSocket.Connect('127.0.0.1', $demoPort); throw "Port $demoPort is already running; do not start duplicate services." }
    catch [Net.Sockets.SocketException] { }
    finally { $demoSocket.Dispose() }
}
$pcProcess = Start-Process -FilePath $pc -ArgumentList @('server','run','--host','127.0.0.1','--port','8017','--env-file',$configPath) -WorkingDirectory "$Root\runtime" -WindowStyle Hidden -RedirectStandardOutput "$Root\logs\server.out.log" -RedirectStandardError "$Root\logs\server.err.log" -PassThru
$gatewayProcess = Start-Process -FilePath $py -ArgumentList @("$PSScriptRoot\gateway.py",$configPath) -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput "$Root\logs\gateway.out.log" -RedirectStandardError "$Root\logs\gateway.err.log" -PassThru
@{powercontext=$pcProcess.Id; gateway=$gatewayProcess.Id} | ConvertTo-Json | Set-Content -LiteralPath "$Root\runtime\processes.json" -Encoding utf8
Write-Host 'Services are starting. Check http://127.0.0.1:8017/health/live; see D-drive logs for errors.'
Write-Host "Secret is stored only in $configPath. Enter it into Dify's POWERCONTEXT_TOKEN Secret field."