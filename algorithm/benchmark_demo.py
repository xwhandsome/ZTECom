from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from agent_py.engine import CareAgent
from agent_py.memory import MemoryStore
from agent_py.rag import KeywordRAG


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "docs" / "performance.md"

DEMO_STEPS = [
    ("Demo1 创建提醒", "明早7点提醒奶奶吃降压药", "health_assistant"),
    ("Demo2 修改提醒", "改成7点半", "health_assistant"),
    ("Demo3 多轮补槽", "提醒奶奶吃降压药", "health_assistant"),
    ("Demo3 补充时间", "明早8点", "health_assistant"),
    ("Demo4 查询环境", "卧室温度怎么样", "health_assistant"),
    ("Demo5 环境联动", "如果卧室低于20度，晚上9点后自动开空调到24度", "health_assistant"),
    ("Demo6 知识问答", "这个药饭前还是饭后吃", "health_assistant"),
    ("Demo7 通知确认", "通知我儿子我今晚不舒服", "tool_short"),
    ("Demo8 会话续接", "查一下现在有哪些提醒", "health_assistant"),
]

LLM_FALLBACK_TEXT = "给奶奶安排明天早晨七点服用降压药"


def main() -> None:
    agent = CareAgent(memory=MemoryStore(":memory:"), rag=KeywordRAG())
    session_id = "bench"
    agent.reset(session_id)
    rows: list[dict[str, Any]] = []

    for name, text, mode in DEMO_STEPS:
        response, elapsed = timed(lambda: agent.chat(session_id, text, mode=mode))
        rows.append(record(name, text, response, elapsed))
        pending = response.get("pending_action")
        if response.get("requires_confirmation") and pending:
            confirmed, confirm_elapsed = timed(
                lambda: agent.confirm(session_id, pending["action_id"], True, mode=mode)
            )
            rows.append(record(f"{name} 确认", "确认执行", confirmed, confirm_elapsed))

    llm_response, llm_elapsed = timed(lambda: agent.chat(session_id, LLM_FALLBACK_TEXT))
    rows.append(record("LLM 兜底样例", LLM_FALLBACK_TEXT, llm_response, llm_elapsed))

    stable_rows = []
    agent.reset("bench-30")
    for index in range(30):
        response, elapsed = timed(lambda: agent.chat("bench-30", "卧室温度怎么样"))
        stable_rows.append(record(f"连续30轮-{index + 1:02d}", "卧室温度怎么样", response, elapsed))
    rows.extend(stable_rows)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(agent, rows, stable_rows), encoding="utf-8")
    print(f"Benchmark report written to {REPORT_PATH}")


def timed(fn):
    started = time.perf_counter()
    response = fn()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return response, elapsed_ms


def record(name: str, text: str, response: dict[str, Any], elapsed_ms: int) -> dict[str, Any]:
    assistant_text = response.get("assistant_text", "")
    return {
        "name": name,
        "text": text,
        "elapsed_ms": elapsed_ms,
        "reported_latency_ms": response.get("latency_ms"),
        "intent": response.get("intent"),
        "success": response.get("intent") != "unknown" and not assistant_text.startswith("\u64cd\u4f5c\u5931\u8d25"),
        "llm_used": bool(response.get("llm_used")),
        "tool_events": [event.get("tool_name") for event in response.get("tool_events", [])],
        "knowledge_refs": [ref.get("title") for ref in response.get("knowledge_refs", [])],
    }


def render_report(agent: CareAgent, rows: list[dict[str, Any]], stable_rows: list[dict[str, Any]]) -> str:
    latencies = [row["elapsed_ms"] for row in rows]
    stable_latencies = [row["elapsed_ms"] for row in stable_rows]
    tool_count = sum(len(row["tool_events"]) for row in rows)
    llm_count = sum(1 for row in rows if row["llm_used"])
    success_count = sum(1 for row in rows if row["success"])
    health = agent.health()

    lines = [
        "# 性能报告",
        "",
        "## 环境",
        "",
        f"- Python: `{sys.version.split()[0]}`",
        f"- 模型启用: `{health['llm']['enabled']}`",
        f"- 模型路径: `{health['llm']['model_path']}`",
        f"- 模型存在: `{health['llm']['model_exists']}`",
        f"- LLM runtime: `{health['llm']['message']}`",
        f"- 知识片段数: `{health['kb_chunks']}`",
        f"- GPU layers: `{os.environ.get('ZTECOM_LLM_GPU_LAYERS', '0')}`",
        "",
        "## 汇总",
        "",
        f"- 总请求数: `{len(rows)}`",
        f"- 成功数: `{success_count}`",
        f"- 工具事件数: `{tool_count}`",
        f"- LLM 调用次数: `{llm_count}`",
        f"- 延迟 p50: `{percentile(latencies, 50)} ms`",
        f"- 延迟 p95: `{percentile(latencies, 95)} ms`",
        f"- 延迟 max: `{max(latencies) if latencies else 0} ms`",
        f"- 连续 30 轮 p95: `{percentile(stable_latencies, 95)} ms`",
        "",
        "## 明细",
        "",
        "| 用例 | 意图 | 耗时(ms) | LLM | 工具事件 | 知识引用 |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {name} | {intent} | {elapsed_ms} | {llm_used} | {tools} | {refs} |".format(
                name=row["name"],
                intent=row["intent"],
                elapsed_ms=row["elapsed_ms"],
                llm_used=row["llm_used"],
                tools=", ".join(row["tool_events"]) or "-",
                refs=", ".join(row["knowledge_refs"]) or "-",
            )
        )
    lines.extend(
        [
            "",
            "## 已知限制",
            "",
            "- 当前环境联动为本地模拟即时评估，不包含后台定时调度。",
            "- LLM 只用于意图与槽位兜底，不参与医疗知识生成。",
            "- 用药合理性判断仍以本地卡片和安全提示为主，不替代医生或药师。",
            "",
        ]
    )
    return "\n".join(lines)


def percentile(values: list[int], pct: int) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    index = round((pct / 100) * (len(sorted_values) - 1))
    return sorted_values[index]


if __name__ == "__main__":
    main()
