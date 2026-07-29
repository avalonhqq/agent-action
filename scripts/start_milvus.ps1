param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

# WSL can stop when no foreground Linux process remains, which also stops Docker.
# Persist the keepalive PID so repeatedly running this script does not spawn duplicates.
$runtimeDirectory = Join-Path $env:LOCALAPPDATA "BiliSupportAI"
$keepalivePidFile = Join-Path $runtimeDirectory "wsl-milvus-keepalive.pid"
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

$keepalive = $null
if (Test-Path $keepalivePidFile) {
    $savedPid = Get-Content $keepalivePidFile -ErrorAction SilentlyContinue
    if ($savedPid) {
        $keepalive = Get-Process -Id $savedPid -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessName -eq "wsl" }
    }
}

if (-not $keepalive) {
    $keepalive = Start-Process `
        -FilePath "wsl.exe" `
        -ArgumentList @("-d", $Distro, "--exec", "tail", "-f", "/dev/null") `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $keepalivePidFile -Value $keepalive.Id -Encoding ASCII
}

Start-Sleep -Seconds 2

# wsl.exe passes Windows backslashes through a Linux argument parser. Doubling them
# prevents paths such as C:\workspace from becoming C:workspace.
$escapedProjectRoot = $ProjectRoot.Replace("\", "\\")
$wslProjectRoot = (
    wsl.exe -d $Distro -- wslpath -a $escapedProjectRoot
).Trim()
if (-not $wslProjectRoot) {
    throw "Cannot convert the project path to a WSL path: $ProjectRoot"
}

wsl.exe -d $Distro -- sh -lc "
    systemctl start docker &&
    cd '$wslProjectRoot' &&
    docker compose up -d milvus &&
    docker compose ps milvus-etcd milvus-minio milvus
"

Write-Host "WSL keepalive PID: $($keepalive.Id)"
Write-Host "Milvus is starting; the first health check usually takes about one minute."
Write-Host (
    'Check: wsl -d {0} -- sh -lc "cd ''{1}'' && docker compose ps milvus"' `
        -f $Distro, $wslProjectRoot
)
