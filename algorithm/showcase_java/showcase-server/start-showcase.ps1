param(
    [string]$PythonEnv = "E:\app\anaconda\envs\RAG",
    [int]$PythonPort = 8000,
    [int]$JavaPort = 8080,
    [string]$ModelPath = "E:\app\llm_models\qwen2.5-1.5b-instruct-q5_k_m.gguf",
    [string]$EnableLLM = "auto",
    [int]$GpuLayers = 0
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
    $modelExists = Test-Path -LiteralPath $ModelPath
    $llmEnabled = $EnableLLM -eq "1" -or $EnableLLM -ieq "true" -or ($EnableLLM -ieq "auto" -and $modelExists)
    $llmFlag = if ($llmEnabled) { "1" } else { "0" }
    $pathPrefix = "$PythonEnv\Lib\site-packages\nvidia\cuda_runtime\bin;$PythonEnv\Lib\site-packages\nvidia\cublas\bin;$PythonEnv\Lib\site-packages\llama_cpp\lib;$PythonEnv;$PythonEnv\Library\bin"
    $pythonOut = Join-Path $LogDir "python-api.out.log"
    $pythonErr = Join-Path $LogDir "python-api.err.log"
    $pythonCmd = "/c set ""CONDA_PREFIX=$PythonEnv"" && set ""PYTHONNOUSERSITE=1"" && set ""PATH=$pathPrefix;%PATH%"" && set ""ZTECOM_ENABLE_LLM=$llmFlag"" && set ""ZTECOM_MODEL_PATH=$ModelPath"" && set ""ZTECOM_LLM_N_CTX=2048"" && set ""ZTECOM_LLM_MAX_TOKENS=256"" && set ""ZTECOM_LLM_TEMPERATURE=0.1"" && set ""ZTECOM_LLM_GPU_LAYERS=$GpuLayers"" && cd /d ""$ProjectRoot"" && ""$pythonExe"" ""algorithm\main.py"" --api --host 127.0.0.1 --port $PythonPort > ""$pythonOut"" 2> ""$pythonErr"""
    Start-Process -FilePath $env:ComSpec -ArgumentList $pythonCmd -WindowStyle Minimized
    Write-Host "Started Python API on http://127.0.0.1:$PythonPort (LLM=$llmFlag, GPU layers=$GpuLayers)"
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
