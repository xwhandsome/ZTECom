# 性能报告

## 环境

- Python: `3.11.15`
- 模型启用: `True`
- 模型路径: `E:\app\llm_models\qwen2.5-1.5b-instruct-q5_k_m.gguf`
- 模型存在: `True`
- LLM runtime: `runtime_ok`
- 知识片段数: `45`
- GPU layers: `0`

## 汇总

- 总请求数: `41`
- 成功数: `41`
- 工具事件数: `39`
- LLM 调用次数: `1`
- 延迟 p50: `0 ms`
- 延迟 p95: `1 ms`
- 延迟 max: `2575 ms`
- 连续 30 轮 p95: `1 ms`

## 明细

| 用例 | 意图 | 耗时(ms) | LLM | 工具事件 | 知识引用 |
| --- | --- | ---: | --- | --- | --- |
| Demo1 创建提醒 | create_reminder | 2 | False | create_reminder | - |
| Demo2 修改提醒 | update_reminder | 0 | False | update_reminder | - |
| Demo3 多轮补槽 | create_reminder | 0 | False | - | - |
| Demo3 补充时间 | create_reminder | 0 | False | create_reminder | - |
| Demo4 查询环境 | query_sensor | 0 | False | query_sensor | - |
| Demo5 环境联动 | upsert_env_rule | 1 | False | upsert_env_rule, control_device | - |
| Demo6 知识问答 | knowledge_query | 1 | False | - | 饭前饭后与服药时间说明, Demo6 本地知识问答, 用药提醒安全边界 |
| Demo7 通知确认 | notify_family | 1 | False | - | - |
| Demo7 通知确认 确认 | notify_family | 0 | False | notify_family | - |
| Demo8 会话续接 | query_reminder | 0 | False | query_reminder | - |
| LLM 兜底样例 | create_reminder | 2575 | True | create_reminder | - |
| 连续30轮-01 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-02 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-03 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-04 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-05 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-06 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-07 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-08 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-09 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-10 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-11 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-12 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-13 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-14 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-15 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-16 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-17 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-18 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-19 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-20 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-21 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-22 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-23 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-24 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-25 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-26 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-27 | query_sensor | 1 | False | query_sensor | - |
| 连续30轮-28 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-29 | query_sensor | 0 | False | query_sensor | - |
| 连续30轮-30 | query_sensor | 0 | False | query_sensor | - |

## 已知限制

- 当前环境联动为本地模拟即时评估，不包含后台定时调度。
- LLM 只用于意图与槽位兜底，不参与医疗知识生成。
- 用药合理性判断仍以本地卡片和安全提示为主，不替代医生或药师。
