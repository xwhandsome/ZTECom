from __future__ import annotations

from agent_py.engine import CareAgent
from agent_py.memory import MemoryStore
from agent_py.rag import KeywordRAG


class FakeLLMStatus:
    def to_dict(self):
        return {
            "enabled": True,
            "runtime_available": True,
            "model_path": "fake.gguf",
            "model_exists": True,
            "loaded": True,
            "message": "fake_runtime_ok",
        }


class AliasSlotLLM:
    def status(self, probe_runtime=False):
        return FakeLLMStatus()

    def parse_intent_json(self, user_text, slots):
        return (
            {
                "intent": "create_reminder",
                "slots": {
                    "reminder_type": "服用降压药",
                    "to": "奶奶",
                    "time": "明天早晨七点",
                },
                "confidence": 0.91,
            },
            FakeLLMStatus(),
        )


class RagSummaryLLM:
    def status(self, probe_runtime=False):
        return FakeLLMStatus()

    def parse_intent_json(self, user_text, slots):
        raise AssertionError("RAG knowledge questions should not use the NLU JSON parser")

    def synthesize_rag_answer(self, user_text, refs, context_hint=None):
        assert len(refs) == 1
        assert "氨氯地平" in refs[0]["title"]
        assert context_hint and "氨氯地平" in context_hint
        return "LLM归纳：氨氯地平通常可在一天中的任意时间服用，建议每天固定在相近时间。具体剂量和调整仍应遵医嘱。", FakeLLMStatus()


class FailingLLM:
    def status(self, probe_runtime=False):
        return FakeLLMStatus()

    def parse_intent_json(self, user_text, slots):
        raise AssertionError("LLM should not run for a high-confidence slot-fill prompt")


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


def test_reminder_and_env_rule_can_be_toggled_and_deleted():
    agent = make_agent()
    agent.reset("crud")

    first = agent.chat("crud", "明早7点提醒奶奶吃降压药")
    agent.chat("crud", "明早8点提醒奶奶吃阿司匹林")
    first_id = first["tool_events"][0]["output"]["reminder"]["id"]

    disabled = agent.set_reminder_enabled("crud", first_id, False)
    assert disabled["status"] == "ok"
    assert next(item for item in disabled["state"]["reminders"] if item["id"] == first_id)["enabled"] is False

    deleted = agent.delete_reminder("crud", first_id)
    assert deleted["status"] == "ok"
    assert all(item["id"] != first_id for item in deleted["state"]["reminders"])

    new_reminder = agent.chat("crud", "明早9点提醒奶奶吃维生素")
    assert new_reminder["tool_events"][0]["output"]["reminder"]["id"] == "rem-003"

    rule_result = agent.chat("crud", "如果卧室低于20度，晚上9点后自动开空调到24度")
    rule_id = rule_result["tool_events"][0]["output"]["rule"]["id"]

    rule_disabled = agent.set_env_rule_enabled("crud", rule_id, False)
    assert rule_disabled["status"] == "ok"
    assert rule_disabled["state"]["env_rules"][0]["enabled"] is False

    rule_deleted = agent.delete_env_rule("crud", rule_id)
    assert rule_deleted["status"] == "ok"
    assert rule_deleted["state"]["env_rules"] == []


def test_environment_rule_is_saved():
    agent = make_agent()
    agent.reset("s2")

    result = agent.chat("s2", "如果卧室低于20度，晚上9点后自动开空调到24度")
    state = agent.state("s2")

    assert result["intent"] == "upsert_env_rule"
    assert state["env_rules"][0]["room"] == "卧室"
    assert state["env_rules"][0]["threshold"] == 20
    assert state["env_rules"][0]["target_temp"] == 24
    assert [event["tool_name"] for event in result["tool_events"]] == ["upsert_env_rule", "control_device"]
    assert result["tool_events"][1]["input"]["trigger"] == "env_rule_immediate_check"
    assert state["device_state"]["卧室:空调"]["status"] == "on"
    assert state["device_state"]["卧室:空调"]["target_temp"] == 24


def test_sensor_status_question_uses_tool_not_rag():
    agent = make_agent()
    agent.reset("s2_sensor")

    result = agent.chat("s2_sensor", "\u5367\u5ba4\u6e29\u5ea6\u600e\u4e48\u6837")

    assert result["intent"] == "query_sensor"
    assert result["tool_events"][0]["tool_name"] == "query_sensor"
    assert result["knowledge_refs"] == []


def test_light_brightness_can_be_adjusted_by_dialogue():
    agent = make_agent()
    agent.reset("light")

    result = agent.chat("light", "把卧室灯亮度调到70%")
    state = agent.state("light")

    assert result["intent"] == "control_device"
    assert result["tool_events"][0]["tool_name"] == "control_device"
    assert result["slots"]["device"] == "灯"
    assert result["slots"]["brightness"] == 70
    assert state["device_state"]["卧室:灯"]["status"] == "on"
    assert state["device_state"]["卧室:灯"]["brightness"] == 70
    assert "亮度70%" in result["assistant_text"]


def test_known_intent_missing_slot_uses_slot_fill_without_llm():
    agent = CareAgent(memory=MemoryStore(":memory:"), rag=KeywordRAG(), llm=FailingLLM())
    agent.reset("s2_slot_fill")

    result = agent.chat("s2_slot_fill", "\u63d0\u9192\u5976\u5976\u5403\u964d\u538b\u836f")

    assert result["intent"] == "create_reminder"
    assert result["llm_used"] is False
    assert result["missing_slots"] == ["time"]
    assert result["requires_confirmation"] is False


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
    assert "氨氯地平" in result["assistant_text"]
    assert result["knowledge_refs"][0]["title"] == "氨氯地平（amlodipine）"
    assert "可在一天中的任意时间服用" in result["assistant_text"]
    assert not result["assistant_text"].startswith("根据本地知识库《饭前饭后与服药时间说明》：**适用问题**")


def test_medicine_recommendation_question_uses_rag_not_reminder_creation():
    agent = make_agent()
    agent.reset("s4_question")

    result = agent.chat("s4_question", "发烧了吃什么药？")

    assert result["intent"] == "knowledge_query"
    assert result["tool_events"] == []
    assert result["missing_slots"] == []
    assert result["knowledge_refs"]
    assert result["knowledge_refs"][0]["title"] == "对乙酰氨基酚（Acetaminophen）"


def test_rag_uses_llm_summary_when_model_is_available():
    agent = CareAgent(memory=MemoryStore(":memory:"), rag=KeywordRAG(), llm=RagSummaryLLM())
    agent.reset("s4_llm")

    agent.chat("s4_llm", "明早7点提醒奶奶吃降压药")
    result = agent.chat("s4_llm", "这个药饭前还是饭后吃")

    assert result["intent"] == "knowledge_query"
    assert result["llm_used"] is True
    assert "LLM归纳" in result["assistant_text"]
    assert "氨氯地平" in result["assistant_text"]
    assert result["knowledge_refs"][0]["title"] == "氨氯地平（amlodipine）"


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


def test_llm_alias_slots_are_normalized_before_planning():
    agent = CareAgent(memory=MemoryStore(":memory:"), rag=KeywordRAG(), llm=AliasSlotLLM())
    agent.reset("s9")

    result = agent.chat("s9", "给奶奶安排明天早晨七点服用降压药")
    state = agent.state("s9")

    assert result["llm_used"] is True
    assert result["intent"] == "create_reminder"
    assert result["missing_slots"] == []
    assert result["slots"]["medicine"] == "降压药"
    assert result["slots"]["person"] == "奶奶"
    assert result["slots"]["time_text"].endswith("07:00")
    assert len(state["reminders"]) == 1


def test_health_does_not_require_model(monkeypatch):
    monkeypatch.delenv("ZTECOM_ENABLE_LLM", raising=False)
    monkeypatch.delenv("ZTECOM_MODEL_PATH", raising=False)
    agent = make_agent()

    health = agent.health()

    assert health["status"] == "ok"
    assert "llm" in health
    assert health["llm"]["enabled"] is False
