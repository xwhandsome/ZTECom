param(
    [string]$ModelPath = "E:\app\llm_models\qwen2.5-1.5b-instruct-q5_k_m.gguf",
    [string]$EnableLLM = "auto",
    [int]$GpuLayers = 0
)

$env:CONDA_PREFIX="E:\app\anaconda\envs\RAG"
$env:PYTHONNOUSERSITE="1"
$env:PATH="$env:CONDA_PREFIX\Lib\site-packages\nvidia\cuda_runtime\bin;$env:CONDA_PREFIX\Lib\site-packages\nvidia\cublas\bin;$env:CONDA_PREFIX\Lib\site-packages\llama_cpp\lib;$env:CONDA_PREFIX;$env:CONDA_PREFIX\Library\bin;$env:PATH"

$modelExists = Test-Path -LiteralPath $ModelPath
$llmEnabled = $EnableLLM -eq "1" -or $EnableLLM -ieq "true" -or ($EnableLLM -ieq "auto" -and $modelExists)
$env:ZTECOM_ENABLE_LLM = if ($llmEnabled) { "1" } else { "0" }
$env:ZTECOM_MODEL_PATH = $ModelPath
$env:ZTECOM_LLM_N_CTX = "2048"
$env:ZTECOM_LLM_MAX_TOKENS = "256"
$env:ZTECOM_LLM_TEMPERATURE = "0.1"
$env:ZTECOM_LLM_GPU_LAYERS = "$GpuLayers"

& "$env:CONDA_PREFIX\python.exe" "$PSScriptRoot\main.py" --api --host 127.0.0.1 --port 8000
