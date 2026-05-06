# 启动代码
``` powershell
conda activate RAG
cd E:\code\ZTECom

powershell -ExecutionPolicy Bypass -File .\algorithm\showcase_java\showcase-server\start-showcase.ps1 -RestartPython 1 -RestartJava 1 -GpuLayers 20
```