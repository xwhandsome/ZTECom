param(
    [string]$PythonEnv = "E:\app\anaconda\envs\RAG",
    [int]$PythonPort = 8000,
    [int]$JavaPort = 8080,
    [string]$ModelPath = "E:\app\llm_models\qwen2.5-1.5b-instruct-q5_k_m.gguf",
    [string]$EnableLLM = "auto",
    [int]$GpuLayers = 0,
    [int]$RestartPython = 0,
    [int]$RestartUnhealthyPython = 1,
    [int]$RestartJava = 0,
    [int]$StartupTimeoutSec = 35
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..")).Path
$JavaRoot = $PSScriptRoot
$LogDir = Join-Path $JavaRoot "target\run-logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-LocalPort {
    param([int]$Port)
    return @(Get-LocalPortOwnerIds -Port $Port).Count -gt 0
}

function Get-LocalPortOwnerIds {
    param([int]$Port)
    $owners = @()
    try {
        $owners += Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq "Listen" -or $_.State -eq "Bound" } |
            Select-Object -ExpandProperty OwningProcess
    } catch {
        $owners = @()
    }

    if (@($owners).Count -eq 0) {
        $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
        $owners += netstat -ano -p tcp |
            Select-String -Pattern $pattern |
            ForEach-Object { [int]$_.Matches[0].Groups[1].Value }
    }

    return @($owners | Where-Object { $_ } | Select-Object -Unique)
}

function Test-HttpOk {
    param([string]$Url)
    try {
        $response = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 3
        return $response.status -eq "ok"
    } catch {
        return $false
    }
}

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSec)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk -Url $Url) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Stop-LocalPortOwners {
    param([int]$Port, [string]$Label)
    $owners = @(Get-LocalPortOwnerIds -Port $Port)
    foreach ($owner in $owners) {
        try {
            $process = Get-Process -Id $owner -ErrorAction Stop
            Write-Host "Stopping $Label process $($process.ProcessName) [$owner] on port $Port."
            Stop-Process -Id $owner -Force
        } catch {
            Write-Warning "Could not stop process $owner on port ${Port}: $($_.Exception.Message)"
        }
    }
    if ($owners.Count -gt 0) {
        Start-Sleep -Seconds 2
    }
}

function Start-PythonApi {
    $modelExists = Test-Path -LiteralPath $ModelPath
    $llmEnabled = $EnableLLM -eq "1" -or $EnableLLM -ieq "true" -or ($EnableLLM -ieq "auto" -and $modelExists)
    $llmFlag = if ($llmEnabled) { "1" } else { "0" }
    $pathPrefix = "$PythonEnv\Lib\site-packages\nvidia\cuda_runtime\bin;$PythonEnv\Lib\site-packages\nvidia\cublas\bin;$PythonEnv\Lib\site-packages\llama_cpp\lib;$PythonEnv;$PythonEnv\Library\bin"
    $pythonOut = Join-Path $LogDir "python-api.out.log"
    $pythonErr = Join-Path $LogDir "python-api.err.log"
    $pythonCmd = "/c set ""CONDA_PREFIX=$PythonEnv"" && set ""PYTHONNOUSERSITE=1"" && set ""PATH=$pathPrefix;%PATH%"" && set ""ZTECOM_ENABLE_LLM=$llmFlag"" && set ""ZTECOM_MODEL_PATH=$ModelPath"" && set ""ZTECOM_LLM_N_CTX=2048"" && set ""ZTECOM_LLM_MAX_TOKENS=256"" && set ""ZTECOM_RAG_LLM_MAX_TOKENS=160"" && set ""ZTECOM_LLM_TEMPERATURE=0.1"" && set ""ZTECOM_LLM_GPU_LAYERS=$GpuLayers"" && cd /d ""$ProjectRoot"" && ""$pythonExe"" ""algorithm\main.py"" --api --host 127.0.0.1 --port $PythonPort > ""$pythonOut"" 2> ""$pythonErr"""
    Start-Process -FilePath $env:ComSpec -ArgumentList $pythonCmd -WindowStyle Hidden
    Write-Host "Started Python API on http://127.0.0.1:$PythonPort (LLM=$llmFlag, GPU layers=$GpuLayers)"
}

$pythonExe = Join-Path $PythonEnv "python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

$pythonHealthUrl = "http://127.0.0.1:$PythonPort/api/health"
if (($RestartPython -ne 0) -and (Test-LocalPort -Port $PythonPort)) {
    Stop-LocalPortOwners -Port $PythonPort -Label "Python API"
}

if ((Test-LocalPort -Port $PythonPort) -and (Test-HttpOk -Url $pythonHealthUrl)) {
    Write-Host "Python API on port $PythonPort is healthy; leaving it running. Use -RestartPython 1 to restart it."
} else {
    if (Test-LocalPort -Port $PythonPort) {
        if ($RestartUnhealthyPython -eq 0) {
            throw "Python API port $PythonPort is in use but $pythonHealthUrl is not healthy. Re-run with -RestartUnhealthyPython 1 or stop the process manually."
        }
        Write-Warning "Python API port $PythonPort is in use, but health check failed. Restarting the port owner."
        Stop-LocalPortOwners -Port $PythonPort -Label "Python API"
    }
    Start-PythonApi
    if (-not (Wait-HttpOk -Url $pythonHealthUrl -TimeoutSec $StartupTimeoutSec)) {
        $pythonErr = Join-Path $LogDir "python-api.err.log"
        throw "Python API did not become healthy within $StartupTimeoutSec seconds. Check log: $pythonErr"
    }
    Write-Host "Python API health check passed."
}

if (Test-LocalPort -Port $JavaPort) {
    if ($RestartJava -ne 0) {
        Stop-LocalPortOwners -Port $JavaPort -Label "Java showcase"
    } else {
        Write-Host "Java showcase port $JavaPort is already in use; leaving it running. Use -RestartJava 1 to restart it."
    }
}

if (-not (Test-LocalPort -Port $JavaPort)) {
    $javaOut = Join-Path $LogDir "java.out.log"
    $javaErr = Join-Path $LogDir "java.err.log"
    $javaArgs = "--server.port=$JavaPort --python.agent.base-url=http://127.0.0.1:$PythonPort"
    $javaCmd = "/c cd /d ""$JavaRoot"" && mvnw.cmd spring-boot:run -Dspring-boot.run.arguments=""$javaArgs"" > ""$javaOut"" 2> ""$javaErr"""
    Start-Process -FilePath $env:ComSpec -ArgumentList $javaCmd -WindowStyle Hidden
    Write-Host "Started Java showcase on http://127.0.0.1:$JavaPort/"
} else {
    Write-Host "Java showcase remains on http://127.0.0.1:$JavaPort/"
}

Write-Host "Frontend: http://127.0.0.1:$JavaPort/"
Write-Host "Java health proxy: http://127.0.0.1:$JavaPort/showcase/api/health"
Write-Host "Python health: http://127.0.0.1:$PythonPort/api/health"
Write-Host "Logs: $LogDir"
