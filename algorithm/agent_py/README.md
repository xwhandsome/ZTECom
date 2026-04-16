# Python 端运行说明

使用 RAG Conda 环境运行：

```powershell
$env:CONDA_PREFIX="E:\app\anaconda\envs\RAG"
$env:PYTHONNOUSERSITE="1"
$env:PATH="$env:CONDA_PREFIX\Lib\site-packages\nvidia\cuda_runtime\bin;$env:CONDA_PREFIX\Lib\site-packages\nvidia\cublas\bin;$env:CONDA_PREFIX\Lib\site-packages\llama_cpp\lib;$env:CONDA_PREFIX;$env:CONDA_PREFIX\Library\bin;$env:PATH"
& "$env:CONDA_PREFIX\python.exe" algorithm\main.py --api --host 127.0.0.1 --port 8000
```

CLI 单轮测试：

```powershell
& "E:\app\anaconda\envs\RAG\python.exe" algorithm\main.py --once "明早7点提醒奶奶吃降压药"
```

可选本地模型：

```powershell
$env:ZTECOM_ENABLE_LLM="1"
$env:ZTECOM_MODEL_PATH="E:\models\your-model.gguf"
```

没有模型或 llama-cpp 初始化失败时，规则、工具和本地关键词 RAG 仍会继续工作。

SQLite 状态库默认写入 `data/agent_state.sqlite3`，使用多表关系结构：

```sql
SELECT * FROM sessions;
SELECT * FROM reminders WHERE session_id = 'demo';
SELECT * FROM tool_events WHERE session_id = 'demo' ORDER BY ts DESC;
SELECT * FROM conversation_messages WHERE session_id = 'demo' ORDER BY ts;
```

`sessions` 保存会话级状态，`reminders` 保存用药提醒，`device_states` 保存设备状态，`sensors` 保存传感器状态，`env_rules` 保存环境联动规则，`tool_events` 保存工具调用记录，`conversation_messages` 保存对话历史。
