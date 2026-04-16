$env:CONDA_PREFIX="E:\app\anaconda\envs\RAG"
$env:PYTHONNOUSERSITE="1"
$env:PATH="$env:CONDA_PREFIX\Lib\site-packages\nvidia\cuda_runtime\bin;$env:CONDA_PREFIX\Lib\site-packages\nvidia\cublas\bin;$env:CONDA_PREFIX\Lib\site-packages\llama_cpp\lib;$env:CONDA_PREFIX;$env:CONDA_PREFIX\Library\bin;$env:PATH"

& "$env:CONDA_PREFIX\python.exe" "$PSScriptRoot\main.py" --api --host 127.0.0.1 --port 8000
