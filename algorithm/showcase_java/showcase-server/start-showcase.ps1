param(
    [string]$PythonEnv = "E:\app\anaconda\envs\RAG",
    [int]$PythonPort = 8000,
    [int]$JavaPort = 8080
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..")).Path
$JavaRoot = $PSScriptRoot
$LogDir = Join-Path $JavaRoot "target\run-logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-LocalPort {
    param([int]$Port)
    try {
        return [bool](Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue)
    } catch {
        return $false
    }
}

$pythonExe = Join-Path $PythonEnv "python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

if (Test-LocalPort -Port $PythonPort) {
    Write-Host "Python API port $PythonPort is already in use; leaving it running."
} else {
    $pathPrefix = "$PythonEnv\Lib\site-packages\nvidia\cuda_runtime\bin;$PythonEnv\Lib\site-packages\nvidia\cublas\bin;$PythonEnv\Lib\site-packages\llama_cpp\lib;$PythonEnv;$PythonEnv\Library\bin"
    $pythonOut = Join-Path $LogDir "python-api.out.log"
    $pythonErr = Join-Path $LogDir "python-api.err.log"
    $pythonCmd = "/c set ""CONDA_PREFIX=$PythonEnv"" && set ""PYTHONNOUSERSITE=1"" && set ""PATH=$pathPrefix;%PATH%"" && cd /d ""$ProjectRoot"" && ""$pythonExe"" ""algorithm\main.py"" --api --host 127.0.0.1 --port $PythonPort > ""$pythonOut"" 2> ""$pythonErr"""
    Start-Process -FilePath $env:ComSpec -ArgumentList $pythonCmd -WindowStyle Minimized
    Write-Host "Started Python API on http://127.0.0.1:$PythonPort"
}

if (Test-LocalPort -Port $JavaPort) {
    Write-Host "Java showcase port $JavaPort is already in use; leaving it running."
} else {
    $javaOut = Join-Path $LogDir "java.out.log"
    $javaErr = Join-Path $LogDir "java.err.log"
    $javaArgs = "--server.port=$JavaPort --python.agent.base-url=http://127.0.0.1:$PythonPort"
    $javaCmd = "/c cd /d ""$JavaRoot"" && mvnw.cmd spring-boot:run -Dspring-boot.run.arguments=""$javaArgs"" > ""$javaOut"" 2> ""$javaErr"""
    Start-Process -FilePath $env:ComSpec -ArgumentList $javaCmd -WindowStyle Minimized
    Write-Host "Started Java showcase on http://127.0.0.1:$JavaPort/"
}

Write-Host "Frontend: http://127.0.0.1:$JavaPort/"
Write-Host "Java health proxy: http://127.0.0.1:$JavaPort/showcase/api/health"
Write-Host "Python health: http://127.0.0.1:$PythonPort/api/health"
Write-Host "Logs: $LogDir"
