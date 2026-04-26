from __future__ import annotations

from agent_py.engine import CareAgent
from agent_py.memory import MemoryStore
from agent_py.rag import KeywordRAG


def make_agent():
    return CareAgent(memory=MemoryStore(":memory:"), rag=KeywordRAG())


def test_create_then_update_reminder_keeps_context():
    agent = make_agent()
    agent.reset("s1")

    created = agent.chat("s1", "明早7点提醒奶奶吃降压药")
    assert created["intent"] == "create_reminder"
    assert "已创建用药提醒" in created["assistant_text"]

    updated = agent.chat("s1", "改成7点半")
    state = agent.state("s1")

    assert updated["intent"] == "update_reminder"
    assert len(state["reminders"]) == 1
    assert state["reminders"][0]["medicine"] == "降压药"
    assert state["reminders"][0]["time_text"].endswith("07:30")


def test_environment_rule_is_saved():
    agent = make_agent()
    agent.reset("s2")

    result = agent.chat("s2", "如果卧室低于20度，晚上9点后自动开空调到24度")
    state = agent.state("s2")

    assert result["intent"] == "upsert_env_rule"
    assert state["env_rules"][0]["room"] == "卧室"
    assert state["env_rules"][0]["threshold"] == 20
    assert state["env_rules"][0]["target_temp"] == 24


def test_notify_family_requires_confirmation_and_runs_once():
    agent = make_agent()
    agent.reset("s3")

    pending = agent.chat("s3", "通知我儿子我今晚不舒服")
    assert pending["intent"] == "notify_family"
    assert pending["requires_confirmation"] is True
    action_id = pending["pending_action"]["action_id"]

    confirmed = agent.confirm("s3", action_id, True)
    repeated = agent.confirm("s3", action_id, True)

    assert "已模拟通知儿子" in confirmed["assistant_text"]
    assert confirmed["tool_events"][0]["tool_name"] == "notify_family"
    assert repeated["assistant_text"] == "当前没有需要确认的操作。"


def test_rag_returns_local_reference_after_reminder_context():
    agent = make_agent()
    agent.reset("s4")

    agent.chat("s4", "明早7点提醒奶奶吃降压药")
    result = agent.chat("s4", "这个药饭前还是饭后吃")

    assert result["intent"] == "knowledge_query"
    assert result["knowledge_refs"]
    assert "本地知识库" in result["assistant_text"]


def test_tool_short_redirects_knowledge_questions_without_rag():
    agent = make_agent()
    agent.reset("s5")

    result = agent.chat("s5", "这个药饭前还是饭后吃", mode="tool_short")

    assert result["intent"] == "knowledge_query"
    assert result["mode"] == "tool_short"
    assert result["knowledge_refs"] == []
    assert "请在健康助手中提问" in result["assistant_text"]


def test_tool_short_keeps_tool_calls_brief():
    agent = make_agent()
    agent.reset("s6")

    result = agent.chat("s6", "明早7点提醒奶奶吃降压药", mode="tool_short")
    state = agent.state("s6")

    assert result["intent"] == "create_reminder"
    assert result["assistant_text"] == "已创建提醒。"
    assert len(state["reminders"]) == 1


def test_tool_short_notify_confirmation_runs_once():
    agent = make_agent()
    agent.reset("s7")

    pending = agent.chat("s7", "通知我儿子我今晚不舒服", mode="tool_short")
    action_id = pending["pending_action"]["action_id"]
    confirmed = agent.confirm("s7", action_id, True, mode="tool_short")
    repeated = agent.confirm("s7", action_id, True, mode="tool_short")

    assert pending["requires_confirmation"] is True
    assert pending["assistant_text"] == "请确认是否通知儿子。"
    assert confirmed["assistant_text"] == "已模拟通知。"
    assert confirmed["tool_events"][0]["tool_name"] == "notify_family"
    assert repeated["assistant_text"] == "当前没有需要确认的操作。"


def test_explains_notify_confirmation_as_knowledge_question():
    agent = make_agent()
    agent.reset("s8")

    result = agent.chat("s8", "为什么通知家属要确认")

    assert result["intent"] == "knowledge_query"
    assert result["knowledge_refs"]
    assert "通知家属" in result["knowledge_refs"][0]["title"]


def test_health_does_not_require_model(monkeypatch):
    monkeypatch.delenv("ZTECOM_ENABLE_LLM", raising=False)
    monkeypatch.delenv("ZTECOM_MODEL_PATH", raising=False)
    agent = make_agent()

    health = agent.health()

    assert health["status"] == "ok"
    assert "llm" in health
    assert health["llm"]["enabled"] is False
