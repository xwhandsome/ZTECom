# 老人关怀端侧智能体代码说明

## 1. 项目定位

本项目是一个“老人关怀 + 用药提醒 + 环境联动 + 本地知识问答”的端侧智能体演示系统。

整体分为两部分：

- `Python`：算法主链路，负责意图识别、槽位抽取、多轮状态、工具调用、SQLite 记忆、本地 RAG、LLM 兜底。
- `Java Spring Boot`：本地展示台和 BFF 代理，负责静态页面托管，并把前端请求转发给 Python API。

Java 不承载模型逻辑，不直接读取 SQLite，也不接外部 AI 接口。比赛规定入口以 `algorithm/main.py` 的 `run()` 为准。

## 2. 目录结构

```text
algorithm/
  main.py                         Python 比赛入口，提供 CLI 和 API 启动能力
  start_python_api.ps1            Python API 启动脚本
  smoke_test.ps1                  前后端冒烟测试脚本
  benchmark_demo.py               Demo 与性能测试脚本
  agent_py/                       Python 智能体核心代码
    api.py                        FastAPI 路由
    engine.py                     Agent 主流程和状态机
    nlu.py                        规则优先的意图识别和槽位抽取
    tools.py                      工具执行器
    memory.py                     SQLite 多表记忆层
    rag.py                        本地知识卡片检索
    llm_adapter.py                llama.cpp / GGUF 本地模型适配
    models.py                     内部数据结构
    config.py                     路径与环境配置
  showcase_java/
    showcase-server/              Java Spring Boot 展示层
      start-showcase.ps1          Python + Java 联合启动脚本
      src/main/java/...           Java BFF 代理代码
      src/main/resources/static/  前端 HTML/CSS/JS
```

项目数据主要放在仓库根目录的 `data/` 下：

```text
data/
  agent_state.sqlite3             SQLite 本地状态库
  kb/                             本地知识卡片 Markdown
  docs/                           性能报告、方案材料
```

## 3. 运行环境

Python 环境固定使用：

```powershell
E:\app\anaconda\envs\RAG\python.exe
```

当前目标版本：

```text
Python 3.11.15
```

本地模型默认路径：

```text
E:\app\llm_models\qwen2.5-1.5b-instruct-q5_k_m.gguf
```

启动脚本会设置必要的 DLL 和模型环境变量。`GpuLayers=0` 表示使用 CPU 推理；如果本机 llama-cpp CUDA 运行正常，可以手动调高 GPU 层数。

## 4. 启动方式

### 4.1 一键启动 Python 和 Java

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\algorithm\showcase_java\showcase-server\start-showcase.ps1 -RestartPython 1 -RestartJava 1
```

启动后访问：

```text
前端页面: http://127.0.0.1:8080/
Java 健康检查代理: http://127.0.0.1:8080/showcase/api/health
Python 健康检查: http://127.0.0.1:8000/api/health
```

运行日志位于：

```text
algorithm/showcase_java/showcase-server/target/run-logs
```

### 4.2 只启动 Python API

```powershell
powershell -ExecutionPolicy Bypass -File .\algorithm\start_python_api.ps1
```

等价于启动 FastAPI 服务：

```powershell
E:\app\anaconda\envs\RAG\python.exe algorithm\main.py --api --host 127.0.0.1 --port 8000
```

### 4.3 CLI 单轮测试

```powershell
E:\app\anaconda\envs\RAG\python.exe algorithm\main.py --once "明早7点提醒奶奶吃降压药"
```

不带参数运行时进入交互式 CLI：

```powershell
E:\app\anaconda\envs\RAG\python.exe algorithm\main.py
```

## 5. Python 主流程

一次用户输入的核心处理流程如下：

1. `NLU`：先用规则识别意图和槽位。
2. `LLM 兜底`：规则无法完整解析、疑问句需要总结或 RAG 命中后需要自然表达时，按配置调用本地 GGUF 模型。
3. `补槽`：缺少时间、药名、设备、房间等必要信息时，进入 pending 状态并追问。
4. `规划`：有限状态机生成工具步骤，不使用自由链式推理直接执行。
5. `工具调用`：执行提醒、设备、传感器、环境规则、通知等本地模拟工具。
6. `状态更新`：把会话、提醒、设备、规则、工具事件写入 SQLite。
7. `RAG`：知识问答从 `data/kb` 中检索 Markdown 知识卡片，并返回引用。
8. `回复生成`：根据模式返回完整回复或工具短回复。

前端传入的 `mode` 会影响回复策略：

- `health_assistant`：健康助手主页面，允许 RAG 问答和 Agent 工具调用。
- `tool_short`：右下角工具助手浮窗，只处理提醒、设备、环境、通知类指令，回复保持短句。

## 6. 已实现工具

Python 工具层主要包括：

- `create_reminder`：创建用药提醒。
- `update_reminder`：修改最近或指定用药提醒。
- `query_reminder`：查询提醒。
- `query_sensor`：查询房间传感器。
- `control_device`：控制设备。
- `upsert_env_rule`：新增或更新环境联动规则。
- `notify_family`：模拟通知家属，需要二次确认。

设备状态约定：

- 空调使用 `target_temp` 表示目标温度。
- 灯使用 `brightness` 表示亮度百分比。

前端待办列表还支持通过 API 删除、启用和停用提醒或环境规则。

## 7. SQLite 记忆层

SQLite 文件默认位于：

```text
data/agent_state.sqlite3
```

当前使用多表结构维护状态：

- `sessions`：会话摘要、pending action、最近意图、最近提醒。
- `family_contacts`：家属联系人。
- `reminders`：用药提醒。
- `device_states`：设备状态。
- `sensors`：传感器状态。
- `env_rules`：环境联动规则。
- `tool_events`：工具调用历史。
- `conversation_messages`：对话消息。

这种结构比单条 JSON 更适合做查询、展示、启停、删除和后续扩展。

## 8. API 接口

Python API：

```text
GET    /api/health
POST   /api/chat
POST   /api/confirm
GET    /api/state/{session_id}
POST   /api/reset
DELETE /api/reminders/{session_id}/{reminder_id}
POST   /api/reminders/{session_id}/{reminder_id}/enabled
DELETE /api/env-rules/{session_id}/{rule_id}
POST   /api/env-rules/{session_id}/{rule_id}/enabled
```

Java BFF 对应代理：

```text
GET    /showcase/api/health
POST   /showcase/api/chat
POST   /showcase/api/confirm
GET    /showcase/api/state/{sessionId}
POST   /showcase/api/reset
DELETE /showcase/api/reminders/{sessionId}/{reminderId}
POST   /showcase/api/reminders/{sessionId}/{reminderId}/enabled
DELETE /showcase/api/env-rules/{sessionId}/{ruleId}
POST   /showcase/api/env-rules/{sessionId}/{ruleId}/enabled
```

聊天请求示例：

```json
{
  "session_id": "demo",
  "user_text": "明早7点提醒奶奶吃降压药",
  "mode": "health_assistant"
}
```

确认请求示例：

```json
{
  "session_id": "demo",
  "action_id": "act-xxxx",
  "approved": true,
  "mode": "health_assistant"
}
```

`/api/chat` 主要返回字段：

```text
assistant_text
intent
slots
missing_slots
plan_steps
tool_events
knowledge_refs
requires_confirmation
pending_action
latency_ms
llm_used
llm_status
```

## 9. Java 展示层

前端页面使用原生 `HTML + CSS + JavaScript`，无 Vue/React 构建链。

页面包括：

- `控制中心`：展示提醒数量、规则数量、设备状态、传感器状态、最近工具调用和最近意图。
- `健康助手`：主 RAG 对话页，同时展示本轮解析、槽位、计划步骤、工具事件、知识引用和 LLM 状态。
- `待办列表`：展示提醒、环境规则、通知记录和工具事件，并支持提醒/规则的删除、启用、停用。
- `工具助手浮窗`：快捷工具入口，只处理短工具指令。

Java 只代理 Python API。Python 不在线时，Java 会返回明确的离线状态，避免前端空白或暴露后端异常堆栈。

## 10. 本地知识库

知识库卡片位于：

```text
data/kb
```

当前 RAG 是知识卡片式关键词检索，不依赖向量数据库。优点是轻量、可解释、易维护，适合比赛演示和端侧部署。

建议维护的卡片类型：

- 药品卡片：适用症状、用法用量、不良反应、禁忌。
- 用药安全边界：哪些问题不能替代医生判断。
- 提醒规则卡片：饭前饭后、固定时间、漏服处理等。
- 家庭照护卡片：异常状态、通知家属、环境舒适范围。
- 设备规则卡片：空调、灯光、传感器含义。
- Demo 脚本卡片：保证演示问法能稳定命中。

## 11. 测试方式

### 11.1 Python 单元测试

```powershell
E:\app\anaconda\envs\RAG\python.exe -m pytest tests
```

### 11.2 Java 单元测试

```powershell
cd algorithm\showcase_java\showcase-server
cmd /c mvnw.cmd test
```

### 11.3 冒烟测试

先启动 Python 和 Java，再执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\algorithm\smoke_test.ps1
```

### 11.4 性能测试

```powershell
E:\app\anaconda\envs\RAG\python.exe algorithm\benchmark_demo.py
```

性能报告输出到：

```text
data/docs/performance.md
```

## 12. 常见问题

### 12.1 页面显示 Python 异常

先检查 Python 健康检查：

```text
http://127.0.0.1:8000/api/health
```

再查看日志：

```text
algorithm/showcase_java/showcase-server/target/run-logs
```

如果端口已有旧进程，使用联合启动脚本并带重启参数：

```powershell
powershell -ExecutionPolicy Bypass -File .\algorithm\showcase_java\showcase-server\start-showcase.ps1 -RestartPython 1 -RestartJava 1
```

### 12.2 `Started Python API ... (LLM=1, GPU layers=0)` 是什么意思

含义是：

- `LLM=1`：本地模型功能已开启。
- `GPU layers=0`：模型使用 CPU 推理。

如果要尝试 GPU，可以在启动脚本中传入更高的 `GpuLayers`，但比赛演示默认建议使用 CPU，以稳定为先。

### 12.3 RAG 回答不是模型自由生成吗

当前 RAG 先检索本地知识卡片，再在可用时调用本地 LLM 做基于片段的总结。模型不可用时，会退化为知识片段摘取。系统不接外网，也不会生成真实医疗诊断建议。

### 12.4 为什么有些药品问题回答保守

系统定位是提醒和照护辅助，不替代医生或药师。药品用法会优先引用本地卡片；如果卡片信息不足，会明确提示依据不足，而不是编造。

## 13. 演示建议

推荐演示顺序：

1. Reset 演示环境。
2. Demo1 创建用药提醒。
3. Demo2 修改提醒，证明多轮上下文。
4. Demo4 查询环境。
5. Demo5 创建环境联动规则，并展示自动联动工具事件。
6. Demo6 知识问答，展示本地知识引用和 LLM 状态。
7. Demo7 通知家属，展示二次确认。
8. 待办列表启停或删除提醒/规则。

这样可以覆盖比赛关注的端侧 Agent、工具调用、状态记忆、本地 RAG、LLM 兜底和 Java 展示闭环。


# 启动代码
``` powershell
conda activate RAG
cd E:\code\ZTECom

powershell -ExecutionPolicy Bypass -File .\algorithm\showcase_java\showcase-server\start-showcase.ps1 -RestartPython 1 -RestartJava 1 -GpuLayers 20
```